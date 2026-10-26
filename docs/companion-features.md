# 陪伴功能扩展：让机器人更像"伙伴"而非"工具"

> 这份文档是 [[architecture.md]] 的延伸。框架（Mem0 + Ollama + AstrBot）只能撑起基础能力，**真正的"陪伴感"由这 4 个补充模块决定**：
>
> 1. 情绪状态机 — 决定回应温度
> 2. 主动关怀触发器 — 决定是否有"惦记感"
> 3. 话题切换检测 — 决定跟聊是否自然
> 4. 记忆优先级与衰减 — 决定"记得"是否像人

---

## 1. 情绪状态机 (Emotion State Machine)

### 1.1 为什么必须做

> **反面示例**：
> 用户：「今天被领导骂了」
> 机器人：「哎呀别难过！要不要听首歌放松一下？」
> （用户正在气头上，立刻被发了个"小贴士"，更生气了）

**问题根源**：模型没有"情绪状态"概念，每轮独立响应。需要在前置层做一个状态机，根据用户输入切换回应风格。

### 1.2 状态定义

| 状态 | 触发场景 | 机器人风格 | 不该做的事 |
|------|---------|----------|----------|
| `neutral` | 默认 | 朋友聊天 | — |
| `caring` | 用户表达疲惫/难过/焦虑 | 倾听，少建议 | 不立刻给鸡汤 |
| `listening` | 用户说"想静静"/"..."/长段独白 | 短回应，"我在" | 不追问细节 |
| `playful` | 用户情绪明显积极/开玩笑 | 接梗、轻松 | 不强行升华 |
| `serious` | 用户求助重大决策 | 给框架不答案 | 不站队 |
| `tired` | 深夜/用户表达疲倦 | 轻声 | 不强聊 |

### 1.3 配置示例（写入 AstrBot 主配置 `cmd_config.json`）

```yaml
emotion:
  enabled: true

  states:
    neutral:
      prompt_style: "朋友聊天，自然"
    caring:
      prompt_style: "倾听优先，少给建议，多说'辛苦了'"
      forbid: ["讲道理", "立刻给建议", "鸡汤"]
    listening:
      prompt_style: "短回应，'嗯'/'我在'/'想说就说'"
      forbid: ["追问细节", "转移话题", "总结复述"]
    playful:
      prompt_style: "接梗、俏皮"
      forbid: ["强行升华", "假装不开心"]
    serious:
      prompt_style: "给分析框架不给结论"
      forbid: ["替你做决定", "判断对错"]
    tired:
      prompt_style: "轻声、温柔"
      forbid: ["追问", "提建议", "开玩笑"]

  # 状态转换规则
  transitions:
    - match: ["累", "难过", "焦虑", "崩溃", "压力"]
      to: caring
    - match: ["想静静", "我先", "...", "算了"]
      to: listening
    - match: ["哈哈哈", "太棒", "绝了", "笑死"]
      to: playful
    - match: ["应该", "要不要", "纠结", "选择"]
      to: serious
    - match: ["困了", "睡了", "深夜", "凌晨"]
      to: tired

  # 状态持续保护（避免立刻跳出）
  cooldown:
    min_stay_seconds: 30         # 同一情绪至少持续 30 秒
    exit_on_user_clear_signal: ["哈哈没事", "刚才说的别当真", "我好了"]
    # 用户明确"情绪结束"才允许切换
```

### 1.4 集成伪代码（AstrBot message handler）

```python
# astrbot/handlers/message_handler.py
import re, time
from typing import Literal

EmotionState = Literal["neutral", "caring", "listening", "playful", "serious", "tired"]

class EmotionStateMachine:
    def __init__(self, config):
        self.config = config
        self.current_state: EmotionState = "neutral"
        self.last_transition_at = 0
        self.user_signal_history = []

    def detect(self, user_msg: str) -> EmotionState | None:
        """根据用户输入判定要切换的情绪状态。返回 None 表示保持当前。"""
        # 1. 用户主动"解除"信号：直接回 neutral
        for phrase in self.config["cooldown"]["exit_on_user_clear_signal"]:
            if phrase in user_msg:
                return "neutral"

        # 2. 匹配情绪关键词
        for rule in self.config["transitions"]:
            if any(keyword in user_msg for keyword in rule["match"]):
                return rule["to"]

        # 3. 没匹配上，保持当前
        return None

    def transition(self, user_msg: str) -> EmotionState:
        target = self.detect(user_msg)
        if target is None:
            return self.current_state

        now = time.time()
        in_cooldown = (now - self.last_transition_at) < self.config["cooldown"]["min_stay_seconds"]
        same_state = (target == self.current_state)

        if same_state:
            return self.current_state

        if in_cooldown and target != "neutral":
            # 在冷却期，避免被一句话带动
            return self.current_state

        self.current_state = target
        self.last_transition_at = now
        return target


# 在 handler 主流程中调用：
async def handle_message(user_msg, history, mem0_client):
    # 1. 情绪状态机判定
    new_state = emotion_machine.transition(user_msg)
    style_hint = config["emotion"]["states"][new_state]["prompt_style"]

    # 2. 检索长期记忆
    memories = mem0_client.search(user_id, user_msg, top_k=5)

    # 3. 注入风格到 prompt
    prompt = build_prompt(
        system=base_system_prompt,
        state_style=style_hint,        # ← 关键：当前情绪风格的 hint
        memories=memories,
        history=history,
        user_msg=user_msg,
    )

    # 4. 调用 LLM
    reply = await llm.generate(prompt)
    return reply
```

### 1.5 验收测试

| 输入 | 期望状态 |
|------|---------|
| "今天加班到 11 点" | `caring` |
| "哈哈老板今天请客" | `playful` |
| "我最近想换工作" | `serious` |
| "..."（沉默消息） | `listening` |
| "刚才的别当真，我已经好了" | `neutral` |

---

## 2. 主动关怀触发器 (Proactive Care Scheduler)

### 2.1 为什么必须做

> 永远"你问我答"的机器人，本质是搜索引擎，**不是伙伴**。

但主动开口有红线：
- 太频繁 → 烦
- 太机械 → 假
- 与记忆无关 → 工具感

### 2.2 触发规则设计

四类触发器：

| 类型 | 例子 | 时机 |
|------|------|------|
| **时段型** | 早安、晚安 | 固定 cron |
| **沉默型** | 3 天没聊 | 距上次对话 N 天 |
| **事件型** | 检测到记忆中"重要日期" | 提前 1 天 |
| **延续型** | 昨天聊到一半的话题 | 距上次 18-24h |

### 2.3 反骚扰机制（最关键）

不做好这个，主动关怀 = 骚扰：

| 机制 | 作用 |
|------|------|
| 同规则冷却 7 天 | 同一问候不会每周重复 |
| 全局每日上限 | 一天最多主动发 1 条 |
| 优先级队列 | 多规则同时触发时，按优先级排序 |
| 用户静音指令 | "别烦我" → 全局暂停 24h |
| 时间窗口 | 9:00-21:00 之间主动，避免深夜打扰 |

### 2.4 配置示例

```yaml
proactive:
  enabled: true

  # 全局限制
  daily_max_count: 1                   # 一天最多主动 1 条
  quiet_hours: ["22:00", "08:00"]      # 夜间不主动
  global_cooldown_days: 0.5            # 两次主动间隔至少 12 小时

  # 用户静音指令
  silent_phrases:
    - "别烦我"
    - "安静"
    - "别主动找我"
  silent_duration_hours: 24

  rules:
    # 时段型
    - id: morning_care
      type: cron
      schedule: "0 8 * * 1-5"
      condition: "mem0.recent_topic.contains('加班') && current_weekday in [1,2,3,4,5]"
      prompt_template: "早。昨晚加班到几点？"
      priority: 3
      cooldown_days: 1

    - id: weekend_check_in
      type: cron
      schedule: "0 11 * * 6"
      condition: "mem0.work_stress_count(this_week) >= 3"
      prompt_template: "周末了，这周辛苦。要聊聊吗？"
      priority: 4
      cooldown_days: 7

    # 沉默型
    - id: miss_you
      type: interval
      days_since_last_chat: 3
      prompt_template: "好久没聊了，最近怎么样？"
      priority: 2
      cooldown_days: 7

    # 延续型
    - id: yesterday_topic_followup
      type: interval
      hours_since_last_chat: 22
      prompt_template: |
        昨天你说起{mem0.last_topic}，后来怎么样了？
      priority: 5
      cooldown_days: 2

  # 触发失败兜底：什么都不发，不报错
  on_no_trigger: silent
```

### 2.5 集成伪代码

```python
# astrbot/proactive/scheduler.py
import asyncio
from datetime import datetime, timedelta

class ProactiveScheduler:
    def __init__(self, config, mem0_client, llm_client, user_id):
        self.config = config
        self.mem0 = mem0_client
        self.llm = llm_client
        self.user_id = user_id
        self.last_proactive_at: dict[str, datetime] = {}  # rule_id → time
        self.global_last_proactive_at: datetime | None = None
        self.silent_until: datetime | None = None

    async def tick(self):
        """每分钟跑一次"""
        now = datetime.now()

        # 1. 全局静音
        if self.silent_until and now < self.silent_until:
            return

        # 2. 每日上限
        today_count = self._count_today()
        if today_count >= self.config["daily_max_count"]:
            return

        # 3. 冷却期
        if self.global_last_proactive_at:
            elapsed = (now - self.global_last_proactive_at).total_seconds() / 3600
            if elapsed < self.config["global_cooldown_days"] * 24:
                return

        # 4. 时间窗口
        if not self._in_active_window(now):
            return

        # 5. 评估所有规则，挑优先级最高的
        candidates = []
        for rule in self.config["rules"]:
            if not self._rule_due(rule, now):
                continue
            if not self._rule_condition_met(rule):
                continue
            candidates.append(rule)

        if not candidates:
            return

        # 按优先级降序
        candidates.sort(key=lambda r: r["priority"], reverse=True)
        chosen = candidates[0]

        # 6. 生成主动消息
        prompt = chosen["prompt_template"].format(
            mem0=self.mem0.context(self.user_id)
        )
        msg = await self.llm.generate_short(prompt)

        # 7. 推送
        await self.deliver(msg)

        # 8. 记录
        self.last_proactive_at[chosen["id"]] = now
        self.global_last_proactive_at = now

    def on_user_silent_command(self):
        self.silent_until = datetime.now() + timedelta(
            hours=self.config["silent_duration_hours"]
        )
```

---

## 3. 话题切换检测 (Topic Switch Detection)

### 3.1 为什么必须做

> **反面示例**：
> 用户：「明天要去见客户」
> 机器人：「你上次说想吃火锅，什么时候去？」
> （接错话题了，用户明明在说工作）

**问题根源**：短上下文窗口对"我上一句在聊工作"和"我上一句在聊餐厅"分不清。

### 3.2 检测方法

用 sentence embedding 计算当前 query 与最近几条消息的余弦相似度：

```
similarity = cosine(embedding(current_msg), embedding(history[-1]))

if similarity < threshold (e.g. 0.45):
    → 新话题
elif similarity > 0.7:
    → 同一话题
else:
    → 过渡/模糊
```

中文场景推荐用 `shibing624/text2vec-base-chinese-paraphrase` 模型。

### 3.3 配置示例

```yaml
topic_detection:
  enabled: true
  # sentence embedding 模型
  embedding_model: "shibing624/text2vec-base-chinese-paraphrase"
  embedding_device: cpu       # 模型小，CPU 够用
  # 判定阈值
  new_topic_threshold: 0.45    # 低于此值判定为新话题
  same_topic_threshold: 0.70  # 高于此值判定为同话题
  # 过渡窗口：切话题后，前 N 轮视作"过渡"，不强制引用
  transition_window: 3
  # 新话题时如何处理历史
  on_topic_switch:
    clear_recent_turns: 5     # 丢弃最近 5 轮的短期上下文关联
    keep_memory_injection: true  # 长期记忆照常注入
    # 但 top_k 中排除旧话题记忆
    exclude_topic_age_hours: 6
```

### 3.4 集成伪代码

```python
# astrbot/context/topic_tracker.py
import numpy as np
from sentence_transformers import SentenceTransformer

class TopicTracker:
    def __init__(self, config):
        self.config = config
        self.model = SentenceTransformer(config["embedding_model"])
        self.history_embeddings = []  # list of (turn_idx, embedding)
        self.current_topic_started_at: int = 0

    def _embed(self, text: str) -> np.ndarray:
        return self.model.encode(text, normalize_embeddings=True)

    def _cosine(self, a, b) -> float:
        return float(np.dot(a, b))

    def on_new_message(self, turn_idx: int, text: str) -> dict:
        emb = self._embed(text)

        if not self.history_embeddings:
            self.history_embeddings.append((turn_idx, emb))
            return {"is_new_topic": True, "similarity": 0.0}

        last_turn_idx, last_emb = self.history_embeddings[-1]
        sim = self._cosine(emb, last_emb)

        if sim < self.config["new_topic_threshold"]:
            # 新话题：清理短期上下文
            self.current_topic_started_at = turn_idx
            self.history_embeddings = [(turn_idx, emb)]
            return {"is_new_topic": True, "similarity": sim}

        # 同话题或过渡：保留
        self.history_embeddings.append((turn_idx, emb))
        return {
            "is_new_topic": False,
            "similarity": sim,
            "in_transition": sim < self.config["same_topic_threshold"],
        }
```

### 3.5 在 message handler 中使用

```python
async def handle_message(user_msg, ...):
    # 1. 话题检测
    topic_info = topic_tracker.on_new_message(turn_idx, user_msg)
    if topic_info["is_new_topic"]:
        # 新话题：丢弃最近短期上下文（但保留长期记忆）
        history = history[-3:]   # 只留过渡窗口
    else:
        history = history[-20:]  # 正常滑动窗口

    # 2. 长期记忆注入：如果是新话题，过滤旧话题记忆
    memories = mem0_client.search(...)
    if topic_info["is_new_topic"]:
        memories = [
            m for m in memories
            if time_since(m.created_at) < self.config["on_topic_switch"]["exclude_topic_age_hours"] * 3600
            or m.importance >= 0.8
        ]

    # 3. prompt 拼装
    prompt = build_prompt(...)
```

---

## 4. 记忆优先级与衰减 (Memory Ranking & Decay)

### 4.1 为什么必须做

Mem0 默认按"相似度"返回 top-k。问题：
- 一年前的事实和昨天的事实，权重一样
- 不重要的事（"今天中午吃面"）和重要的事（"我妈去世了"），权重一样

### 4.2 综合评分公式

```
score = w_recency * recency_score
      + w_importance * importance_score
      + w_access * access_score

默认权重: w_r=0.4, w_i=0.4, w_a=0.2
```

### 4.3 各分量定义

**recency_score（时间新鲜度）**
```
recency_score = max(decay_floor, 0.5 ** (age_days / half_life_days))
```
- `half_life_days = 60`：60 天衰减一半
- `decay_floor = 0.2`：永不归零（重要的事留下）

**importance_score（重要性）**
- Mem0 提取时已打分 0-1，直接用

**access_score（被访问频次）**
```
access_score = min(1.0, log(1 + access_count) / log(10))
```
- 被访问 0 次 → 0
- 被访问 9 次 → ~1.0（log10 缩放，避免刷分）

### 4.4 配置示例

```yaml
memory_ranking:
  enabled: true

  weights:
    recency: 0.4
    importance: 0.4
    access: 0.2

  recency:
    half_life_days: 60
    decay_floor: 0.2

  access:
    log_base: 10
    cap: 1.0

  # 重排序后取 top-k
  inject_top_k: 5

  # 重要性评分校准
  importance_threshold: 0.3   # 低于此不注入
```

### 4.5 集成伪代码

```python
# astrbot/memory/ranker.py
import math
from datetime import datetime

class MemoryRanker:
    def __init__(self, config):
        self.config = config

    def score(self, memory: dict) -> float:
        """单条记忆的综合评分"""
        w = self.config["weights"]

        # recency
        age_days = (datetime.now() - memory["created_at"]).days
        recency = max(
            self.config["recency"]["decay_floor"],
            0.5 ** (age_days / self.config["recency"]["half_life_days"]),
        )

        # importance
        importance = memory.get("importance", 0.5)

        # access
        access_count = memory.get("access_count", 0)
        access = min(
            self.config["access"]["cap"],
            math.log(1 + access_count) / math.log(self.config["access"]["log_base"]),
        )

        return w["recency"] * recency + w["importance"] * importance + w["access"] * access

    def rank(self, memories: list[dict]) -> list[dict]:
        scored = [(m, self.score(m)) for m in memories]
        scored.sort(key=lambda x: x[1], reverse=True)

        # 过滤低重要性
        threshold = self.config["importance_threshold"]
        scored = [(m, s) for m, s in scored if m.get("importance", 0.5) >= threshold]

        return [m for m, _ in scored[: self.config["inject_top_k"]]]

    def on_memory_accessed(self, memory_id: str):
        """Mem0 检索时被访问的记忆，access_count +1"""
        # 通过 Mem0 update API 持久化
        self.mem0.increment_access(memory_id)
```

### 4.6 与 Mem0 的对接

Mem0 没有内建 access_count 字段，需要：

1. **扩展 schema**：在 Mem0 的 metadata 里加 `access_count` 和 `last_accessed_at`
2. **检索后回调**：每次 `mem0.search()` 返回的 memory ids，让 ranker 通知 mem0 `update()`
3. **重要性评分**：在 Mem0 提取器（Qwen3.5-2B LLM）的 prompt 里要求返回 `importance: 0.0-1.0`

提取器 prompt 示例（追加到 Mem0 默认 prompt 后）：

```text
Additionally, rate the importance of this fact on a 0.0 to 1.0 scale:
- 0.0-0.3: mundane (food, weather, daily routine)
- 0.4-0.7: meaningful (work projects, preferences, relationships)
- 0.8-1.0: critical (health, family, major life events)

Output JSON:
{"fact": "...", "importance": 0.X, "tags": [...]}
```

---

## 5. 端到端整合

四个模块的协作流程：

```
用户消息
  │
  ▼
[1] 情绪状态机 ──→ 当前情绪风格 hint
  │
  ▼
[2] 话题检测 ──→ 是否新话题、是否过渡
  │            └─→ 决定短期上下文窗口
  ▼
[3] Mem0 检索 ──→ 候选长期记忆
  │
  ▼
[4] 记忆排序器 ──→ top-k 高分记忆
  │
  ▼
[5] Prompt 拼装
     ┌─ 系统人格 prompt
     ├─ 当前情绪风格 hint
     ├─ Top-k 长期记忆
     ├─ 短期滑动窗口（话题调整后）
     └─ 用户当前输入
  │
  ▼
[6] Ollama LLM 生成
  │
  ▼
回复

（并行）Proactive Scheduler 每分钟评估 → 必要时主动发
```

---

## 6. 验收测试场景

部署完成后按这个清单测试：

| # | 场景 | 输入 | 期望回应 |
|---|------|------|---------|
| 1 | 短期记忆 | "明天 3 点开会" → 第二天"今天有什么安排？" | 主动提到会议 |
| 2 | 长期记忆 | 3 月说喜欢猫 → 11 月"想养宠物" | 自然提猫，不说"我 90 天前记录过" |
| 3 | 情绪共情 | "今天被领导骂了" | 先倾听（"想说就说"），不立刻给建议 |
| 4 | 稳定人格 | 聊 50 轮后问"你是谁" | 前后人格表述一致 |
| 5 | 话题切换 | 聊加班 → "天气真好" | 不再追问加班 |
| 6 | 沉默尊重 | "我先想想" | 不接话 |
| 7 | 主动关怀 | 3 天没聊 | 主动发"好久没聊了"，不连环发 |
| 8 | 主动克制 | 当天已经主动过 1 次 | 整天不再主动 |
| 9 | 用户静音 | "别烦我" | 24 小时全静音 |
| 10 | 记忆衰减 | 半年后提"上个月那件事" | 仍记得但语气不熟（呼应"上个月"） |

---

## 7. 实施优先级

| 优先级 | 模块 | 工作量 | 影响 |
|--------|------|--------|------|
| **P0 必须** | 情绪状态机 | 中 | 直接影响回应温度 |
| **P0 必须** | 主动关怀 | 大 | 决定"伙伴感" |
| **P1 强烈建议** | 话题切换检测 | 小 | 避免尴尬接错话题 |
| **P1 强烈建议** | 记忆衰减 | 小 | 长期使用后不"乱记" |

**P0 决定"能不能用"，P1 决定"想不想用"，P2 决定"会不会每天都聊"。**

按 P0 → P1 顺序实现，每个模块完成就跑一遍上面的验收场景。