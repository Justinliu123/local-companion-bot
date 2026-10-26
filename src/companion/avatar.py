"""
形象层适配器：把陪伴机器人的状态信号翻译成桌宠（dsh-pet）的 HTTP 调用。

只依赖标准库（urllib + asyncio.to_thread），不引入任何新依赖。
形象层是**表现层** —— 任何失败都吞掉并记录，绝不影响对话主链路。

上游接口见 docs/avatar-integration.md；完整契约以 dsh-pet 的 openapi.yaml 为准。

接口速查（基址 http://127.0.0.1:3080/dsh-pet-7340）：
    POST /lock?pet=              占用锁（不传 lock=新建，传了=续期）→ {lockId, expiresAt}
    POST /lock/release?pet=&lock= 释放锁
    POST /broadcast?pet=&lock=   投喂气泡（不生成、只搬运）
    POST /anim?pet=&lock=        点播动画
    POST /bubble/clear?pet=&lock= 清空气泡
    POST /work-status            外部写入工作状态 {state, task?}（固定外部槽，最后写入者生效）
    POST /menu/item              注册右键菜单项 {owner, labels, target?}
    GET  /menu/events?owner=&wait= 长轮询读菜单点击
    GET  /state?since=&timeout=  读全部状态位（长轮询）
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 档位表
# ---------------------------------------------------------------------------
# dsh-pet 的 events.<name> 数组**索引即档位**，且明确规定「只可追加末尾，不可中间插入」。
# 我们自己也要守这个约定：新增状态往末尾加，别动已有下标。
#
# ⚠️ 数组元素是**动画池里的动画名**，不是随便写的字符串 —— 桌宠找不到同名动画就是 404。
# 下面的默认值是占位，装好 dsh-pet 后必须按它实际带的动画池核对一遍
# （见 docs/avatar-integration.md §3.1）。

TIER_IDLE = 0
TIER_LISTENING = 1
TIER_CARING = 2
TIER_PLAYFUL = 3
TIER_SERIOUS = 4
TIER_TIRED = 5
TIER_THINKING = 6
TIER_SPEAKING = 7
TIER_PROACTIVE = 8
TIER_ERROR = 9

#: 档位 → 桌宠动画名。装好 dsh-pet 后按它实际的动画池校准。
DEFAULT_TIER_ANIMATIONS = {
    TIER_IDLE: "待机",
    TIER_LISTENING: "待机",
    TIER_CARING: "待机",
    TIER_PLAYFUL: "待机",
    TIER_SERIOUS: "待机",
    TIER_TIRED: "打瞌睡",
    TIER_THINKING: "待机",
    TIER_SPEAKING: "待机",
    TIER_PROACTIVE: "待机",
    TIER_ERROR: "待机",
}

#: 情绪状态（emotion.py 的 EmotionState）→ 档位
EMOTION_TO_TIER = {
    "neutral": TIER_IDLE,
    "listening": TIER_LISTENING,
    "caring": TIER_CARING,
    "playful": TIER_PLAYFUL,
    "serious": TIER_SERIOUS,
    "tired": TIER_TIRED,
}

#: dsh-pet 内置的六档工作状态（README 的「思考/工作/整理/等待/成功/出错」）
WORK_STATUS_THINKING = "思考"
WORK_STATUS_WORKING = "工作"
WORK_STATUS_ORGANIZING = "整理"
WORK_STATUS_WAITING = "等待"
WORK_STATUS_SUCCESS = "成功"
WORK_STATUS_ERROR = "出错"


@dataclass
class AvatarConfig:
    enabled: bool = False
    #: dsh-pet standalone 默认 http://127.0.0.1:3080/dsh-pet-7340
    base_url: str = "http://127.0.0.1:3080/dsh-pet-7340"
    pet_id: str = "main"
    timeout: float = 3.0
    #: 连续失败多少次后自我关闭，避免对着没人监听的端口刷日志
    max_consecutive_failures: int = 5
    #: 档位 → 动画名覆盖（把默认占位换成桌宠实际带的动画名）
    tier_animations: dict = field(default_factory=dict)
    #: 右键菜单项的 owner 名（注册菜单项时用）
    menu_owner: str = "companion-bot"


class AvatarClient:
    """
    桌宠（dsh-pet）HTTP 客户端。

    典型用法::

        avatar = AvatarClient(config["avatar"])
        await avatar.say("今天过得怎么样？", tier=TIER_CARING)
        await avatar.set_state(TIER_THINKING)
    """

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.config = AvatarConfig(
            enabled=bool(cfg.get("enabled", False)),
            base_url=str(cfg.get("base_url", AvatarConfig.base_url)).rstrip("/"),
            pet_id=str(cfg.get("pet_id", "main")),
            timeout=float(cfg.get("timeout", 3.0)),
            max_consecutive_failures=int(cfg.get("max_consecutive_failures", 5)),
            tier_animations={int(k): v for k, v in (cfg.get("tier_animations") or {}).items()},
            menu_owner=str(cfg.get("menu_owner", "companion-bot")),
        )
        self._lock_id: Optional[str] = None
        self._failures = 0
        self._disabled_by_failure = False

    # ---- 对外接口 ---------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self.config.enabled and not self._disabled_by_failure

    def animation_for(self, tier: int) -> Optional[str]:
        """档位 → 动画名。返回 None 表示这个档位没有对应动画，跳过调用。"""
        if tier in self.config.tier_animations:
            return self.config.tier_animations[tier]
        return DEFAULT_TIER_ANIMATIONS.get(tier)

    async def say(self, text: str, tier: Optional[int] = None) -> bool:
        """
        把**已经生成好**的回复投喂进气泡。

        桌宠不调模型、只负责显示 —— 回复文本来自我们的 LLM。
        """
        if not self.enabled or not text.strip():
            return False
        body: dict = {"text": text}
        anim = self.animation_for(tier) if tier is not None else None
        if anim:
            body["anim"] = anim
        return await self._locked_call("/broadcast", body)

    async def set_state(self, tier: int) -> bool:
        """切到某个档位动画（如「思考中」「说话中」）。"""
        if not self.enabled:
            return False
        anim = self.animation_for(tier)
        if not anim:
            return False
        return await self._locked_call("/anim", {"anim": anim})

    async def set_emotion(self, emotion_state: str) -> bool:
        """情绪状态名 → 档位 → 动画。"""
        tier = EMOTION_TO_TIER.get(emotion_state)
        if tier is None:
            return False
        return await self.set_state(tier)

    async def set_work_status(self, state: str, task: Optional[str] = None) -> bool:
        """
        写 dsh-pet 的「工作状态」槽位（固定外部槽，最后写入者生效）。

        state 用它内置的六档：思考/工作/整理/等待/成功/出错。
        这条**不需要锁**。
        """
        if not self.enabled or not state:
            return False
        body: dict = {"state": state}
        if task:
            body["task"] = task
        return await self._post("/work-status", body) is not None

    async def clear_work_status(self) -> bool:
        """清空工作状态槽，回空闲（幂等，204）。"""
        if not self.enabled:
            return False
        return await self._call("DELETE", "/work-status", None, None) is not None

    async def clear_bubble(self) -> bool:
        """提前收起气泡（不等它自己 10 秒消失）。"""
        if not self.enabled:
            return False
        return await self._locked_call("/bubble/clear", {})

    async def register_menu_item(self, labels: list[str], target: Optional[str] = None) -> bool:
        """
        在桌宠右键菜单的「更多」下注册我们自己的功能项。

        同一 owner 的菜单项**整体覆盖** —— 重复调用会替换掉上一次的。
        配 ``poll_menu_events`` 使用：用户在桌宠上点了 → 我们收到事件 → 驱动 LLM。
        """
        if not self.enabled or not labels:
            return False
        body: dict = {"owner": self.config.menu_owner, "labels": labels}
        if target:
            body["target"] = target
        return await self._post("/menu/item", body) is not None

    async def poll_menu_events(self, wait_ms: int = 1000) -> dict:
        """长轮询读菜单点击（读取即清空）。返回 {标签: pet_id}。"""
        if not self.enabled:
            return {}
        result = await self._get(
            "/menu/events",
            query={"owner": self.config.menu_owner, "wait": str(wait_ms)},
        )
        if not result:
            return {}
        events = result.get("events") or result.get("data") or {}
        return events if isinstance(events, dict) else {}

    async def close(self) -> None:
        """释放锁。"""
        if self._lock_id:
            lock_id, self._lock_id = self._lock_id, None
            await self._post("/lock/release", {}, query={"lock": lock_id})

    # ---- 锁 ---------------------------------------------------------------

    async def _locked_call(self, path: str, body: dict) -> bool:
        """
        第三方调用桌宠动作必须持锁，否则返回 lock-required。

        锁的语义是「联动演出期间独占这只宠物」—— 演出结束就该释放，
        否则桌宠会被锁住、连待机动画都不动了。
        """
        lock_id = await self._acquire_lock()
        if not lock_id:
            return False
        try:
            return await self._post(path, body, query={"lock": lock_id}) is not None
        finally:
            await self._post("/lock/release", {}, query={"lock": lock_id})
            if self._lock_id == lock_id:
                self._lock_id = None

    async def _acquire_lock(self) -> Optional[str]:
        result = await self._post("/lock", {})
        if not result:
            return None
        lock_id = result.get("lockId") or result.get("lock_id")
        if not lock_id:
            log.debug("avatar: /lock 未返回 lockId，响应=%s", result)
            return None
        self._lock_id = lock_id
        return lock_id

    # ---- HTTP -------------------------------------------------------------

    async def _post(
        self,
        path: str,
        body: Optional[dict] = None,
        query: Optional[dict] = None,
    ) -> Optional[dict]:
        return await self._call("POST", path, body, query)

    async def _get(
        self,
        path: str,
        body: Optional[dict] = None,
        query: Optional[dict] = None,
    ) -> Optional[dict]:
        return await self._call("GET", path, body, query)

    async def _call(
        self,
        method: str,
        path: str,
        body: Optional[dict],
        query: Optional[dict],
    ) -> Optional[dict]:
        if not self.enabled:
            return None
        try:
            return await asyncio.to_thread(self._call_sync, method, path, body, query)
        except Exception as exc:  # 兜底：形象层绝不能把异常抛回主链路
            log.warning("avatar: %s %s 调用失败：%s", method, path, exc)
            return None

    def _call_sync(
        self,
        method: str,
        path: str,
        body: Optional[dict],
        query: Optional[dict],
    ) -> Optional[dict]:
        params = dict(query or {})
        # 所有宠物相关接口都要带 pet
        if path not in ("/work-status", "/menu/item", "/menu/events"):
            params.setdefault("pet", self.config.pet_id)
        url = self.config.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            self._note_failure(f"HTTP {exc.code}: {raw[:200]}")
            return None  # 失败：调用方靠 None 判断，不靠 body
        except Exception as exc:
            self._note_failure(str(exc))
            return None

        self._failures = 0
        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> Optional[dict]:
        # 空 body（204）算成功，只是没有载荷
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    def _note_failure(self, reason: str) -> None:
        self._failures += 1
        if self._failures >= self.config.max_consecutive_failures:
            if not self._disabled_by_failure:
                self._disabled_by_failure = True
                log.warning(
                    "avatar: 连续 %d 次失败，形象层自动关闭（最后一次错误：%s）。"
                    "确认 dsh-pet 是否在跑：dsh-pet-standalone",
                    self._failures,
                    reason,
                )
        else:
            log.debug(
                "avatar: 请求失败（%d/%d）：%s",
                self._failures,
                self.config.max_consecutive_failures,
                reason,
            )
