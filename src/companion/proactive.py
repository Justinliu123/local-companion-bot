"""
主动关怀调度
完整设计见 docs/companion-features.md §2
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable


@dataclass
class ProactiveConfig:
    daily_max_count: int = 1
    quiet_hours: list = field(default_factory=lambda: ["22:00", "08:00"])
    global_cooldown_hours: float = 12.0
    silent_phrases: list = field(default_factory_factory=lambda: ["别烦我", "安静"])
    silent_duration_hours: int = 24
    rules: list = field(default_factory=list)


class ProactiveScheduler:
    """
    每分钟跑一次 tick()，评估所有规则，挑优先级最高的发一条。
    用户说"别烦我"则全局静音 24 小时。
    """

    def __init__(
        self,
        config: dict,
        mem0_client,
        llm_client,
        user_id: str,
        deliver_fn: Callable[[str], Awaitable[None]],
    ):
        self.config = ProactiveConfig(**config)
        self.mem0 = mem0_client
        self.llm = llm_client
        self.user_id = user_id
        self.deliver = deliver_fn

        self.last_proactive_at: dict[str, datetime] = {}
        self.global_last_proactive_at: Optional[datetime] = None
        self.silent_until: Optional[datetime] = None
        self.today_count: int = 0
        self.today_date: datetime.date = datetime.now().date()

    def on_user_silent_command(self):
        self.silent_until = datetime.now() + timedelta(
            hours=self.config.silent_duration_hours
        )

    def on_user_message(self, text: str):
        for phrase in self.config.silent_phrases:
            if phrase in text:
                self.on_user_silent_command()
                return

    def _in_active_window(self, now: datetime) -> bool:
        start = self.config.quiet_hours[1]  # e.g. "08:00"
        end = self.config.quiet_hours[0]    # e.g. "22:00"
        cur = now.strftime("%H:%M")
        return start <= cur <= end

    def _reset_daily_count_if_new_day(self, now: datetime):
        if now.date() != self.today_date:
            self.today_count = 0
            self.today_date = now.date()

    def _rule_due(self, rule: dict, now: datetime) -> bool:
        last = self.last_proactive_at.get(rule["id"])
        if last and (now - last).days < rule.get("cooldown_days", 7):
            return False
        return True

    def _rule_condition_met(self, rule: dict) -> bool:
        # 真实实现需根据 mem0 数据动态求值；此处简化
        return True

    async def tick(self):
        now = datetime.now()
        self._reset_daily_count_if_new_day(now)

        if self.silent_until and now < self.silent_until:
            return
        if self.today_count >= self.config.daily_max_count:
            return
        if self.global_last_proactive_at:
            elapsed_h = (now - self.global_last_proactive_at).total_seconds() / 3600
            if elapsed_h < self.config.global_cooldown_hours:
                return
        if not self._in_active_window(now):
            return

        candidates = [r for r in self.config.rules if self._rule_due(r, now) and self._rule_condition_met(r)]
        if not candidates:
            return

        candidates.sort(key=lambda r: r.get("priority", 0), reverse=True)
        chosen = candidates[0]

        mem_ctx = self.mem0.context(self.user_id) if self.mem0 else {}
        try:
            prompt = chosen["prompt_template"].format(mem0=mem_ctx)
        except KeyError:
            prompt = chosen["prompt_template"]

        msg = await self.llm.generate_short(prompt)
        await self.deliver(msg)

        self.last_proactive_at[chosen["id"]] = now
        self.global_last_proactive_at = now
        self.today_count += 1

    async def run_forever(self):
        while True:
            try:
                await self.tick()
            except Exception as e:
                # 主动任务失败不能影响主对话；只记日志
                print(f"[proactive] tick failed: {e}")
            await asyncio.sleep(60)