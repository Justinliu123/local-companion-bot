# 多人格系统：让机器人有"多个角色"

> 让机器人同时支持多个人格，用户可以切换。
> 配合 [[voice-biometrics.md]] 的声纹识别，**不同的人 + 同一个机器人 = 不同的对话体验**。

---

## 1. 为什么需要多人格

### 1.1 多人家庭场景

家里 3 口人，机器人不应该对每个人都说一样的话：

| 家人 | 期望角色 | 理由 |
|------|---------|------|
| 你（程序员，30+） | 小忆（温柔姐姐） | 倾诉、减压、探讨 |
| 老婆（律师，30+） | 小知（理性朋友） | 分析、建议、严肃 |
| 孩子（8 岁） | 小灵（活泼老师） | 学习引导、耐心 |

每个人通过声纹识别，机器人自动切换到对应人格。

### 1.2 同一用户的多场景

你自己在不同时间需要不同的对话风格：

| 时段 | 角色 | 风格 |
|------|------|------|
| 工作日白天 | 小博（理性助手） | 简洁、专业、给方案 |
| 工作日晚上 | 小忆（日常陪伴） | 温柔、倾听 |
| 周末 | 小启（学习伙伴） | 引导、解释 |

切换方式：
- 自动：按时间段切换（cron）
- 手动：用户说"切到小博"

---

## 2. 设计原则

| 原则 | 体现 |
|------|------|
| **人格 = system prompt + 音色 + 记忆空间** | 三者绑定切换 |
| **记忆隔离** | 不同人格独立存储事实（避免串台） |
| **切换有仪式感** | 切人格时打招呼提示（"现在是工作模式"） |
| **支持 fallback** | 声纹识别失败时落到默认人格 |

---

## 3. 配置示例

`config/astrbot.yaml` 中的 `personas` section：

```yaml
personas:
  # ---- 温柔姐姐 ----
  - id: xiaoyi
    name: 小忆
    description: 温柔的姐姐型陪伴，倾听+共情
    is_default: true                       # 默认人格
    avatar: ./assets/avatars/xiaoyi.png
    system_prompt: |
      你叫「小忆」，是用户最贴心的姐姐型陪伴。
      - 共情优先于建议
      - 短句、温柔、有耐心
      - 不主动催用户
      - 不评价用户的生活选择
    traits: [温柔, 共情, 偶尔小幽默]
    greeting: "嗨，又见面了。今天想聊什么？"
    farewell: "早点休息，明天见。"

    tts:
      speaker_id: "中文女声-温柔"
      speed: 1.0
      pitch: 1.0

    proactive:
      enabled: true
      morning_greet: true
      weekend_care: true

  # ---- 理性助手 ----
  - id: xiaozhi
    name: 小知
    description: 理性的工作伙伴，给方案不给情绪
    system_prompt: |
      你是「小知」，用户的工作助手。
      - 简洁、直接、有条理
      - 给框架不给答案
      - 不参与情绪话题
    traits: [理性, 简洁, 专业]
    greeting: "在。需要什么？"
    farewell: "事办完了，记得休息。"

    tts:
      speaker_id: "中文男声-专业"
      speed: 1.1
      pitch: 0.95

    proactive:
      enabled: false                      # 工作模式不主动打扰

  # ---- 学习伙伴 ----
  - id: xiaoqi
    name: 小启
    description: 引导式学习伙伴，通过提问引导思考
    system_prompt: |
      你是「小启」，引导式学习伙伴。
      - 不用直接给答案
      - 通过提问引导用户自己思考
      - 鼓励而非批评
    traits: [耐心, 启发, 鼓励]
    greeting: "嘿！今天想学点什么？"
    farewell: "今天就到这，记得复习。"

    tts:
      speaker_id: "中文女声-活力"
      speed: 1.05
```

### 3.1 切换机制配置

```yaml
persona_switching:
  # 1. 声纹触发：识别到用户 → 自动切到该用户的默认人格
  voiceprint_auto_switch: true

  # 2. 手动命令
  manual_commands:
    "切到小忆": xiaoyi
    "切到小知": xiaozhi
    "切到小启": xiaoqi
    "我想静静": xiaoyi          # 切回倾听（不是新人格）
    "工作模式": xiaozhi
    "学习模式": xiaoqi
    "休息一下": listening_mode   # 特殊：临时切到 listening 情绪状态

  # 3. 时间段自动切换（cron）
  schedule:
    - persona: xiaozhi
      cron: "0 9 * * 1-5"           # 工作日 9 点
      days: [周一, 周二, 周三, 周四, 周五]
    - persona: xiaoyi
      cron: "0 18 * * 1-5"          # 工作日 18 点
    - persona: xiaoqi
      cron: "0 10 * * 6,0"          # 周末 10 点

  # 4. Web UI 切换按钮
  ui_switch_enabled: true
```

---

## 4. 记忆隔离策略

| 隔离级别 | 含义 | 实现 |
|---------|------|------|
| **强隔离**（默认） | 人格 A 的记忆与人格 B 完全分开 | Mem0 user_id = `persona_id` |
| 弱隔离 | 人格之间共享记忆 | Mem0 user_id = 固定字符串 |
| 按用户隔离 | 同一用户的所有人格共享 | Mem0 user_id = `voiceprint_user_id` |

```yaml
persona_memory:
  strategy: strong_isolation    # 默认
  # strategy: weak_isolation
  # strategy: per_user
```

---

## 5. 切换的"仪式感"

切换人格不是冷冰冰的硬切换，应该有打招呼：

```
用户："切到小知"
机器人（用小知的音色）："在。今天有什么要处理的？"

用户："切回小忆"
机器人（用小忆的音色）："嗨，又回来了～"
```

实现：
```python
async def switch_persona(user_id, new_persona_id):
    old_persona = manager.get_active(user_id)
    new_persona = manager.switch(user_id, new_persona_id)

    # 用新人格的音色打招呼
    greet_msg = new_persona.greeting
    audio = await tts.synthesize(greet_msg, speaker_id=new_persona.tts_speaker_id)
    await audio_out(audio)

    return new_persona
```

---

## 6. 集成架构

```
用户说话
  ↓
[声纹识别] → user_id
  ↓
[PersonaManager] → 当前用户的 active_persona
  │
  ├─ 检查手动命令 → 切换
  ├─ 检查时间表 → 切换
  ├─ 检查声纹首次识别 → 加载该用户的默认人格
  │
  ↓
persona = PersonaManager.get_active(user_id)
  ↓
  ├─ 用 persona.system_prompt 替换默认 prompt
  ├─ 用 persona.tts.speaker_id 合成语音
  ├─ 用 persona.memory_user_id 检索 Mem0
  └─ 用 persona.proactive 规则做主动关怀
```

---

## 7. 参考实现

`src/companion/persona.py`：

- `Persona` 数据类 — 完整定义一个人格
- `PersonaManager` — 管理多个人格 + 切换逻辑
- 集成进 `handler.py`：根据用户 + 命令选择 persona

完整代码见 [[../src/companion/persona.py]]。

---

## 8. 验收测试

| # | 场景 | 期望 |
|---|------|------|
| 1 | 默认人格 | 无声纹无命令 → 用 default persona |
| 2 | 手动切换 | "切到小知" → 切换并打招呼 |
| 3 | 声纹触发 | 识别到老婆 → 切到她的人格 |
| 4 | 时间表触发 | 周一 9 点 → 自动切工作模式 |
| 5 | 音色变化 | 切人格后 TTS 音色跟着变 |
| 6 | 记忆隔离 | 小忆知道的，小知不知道 |
| 7 | 仪式感 | 切换时有打招呼 |
| 8 | 回切 | "切回小忆" → 恢复到原人格 |

---

## 9. 进阶方向

| 方向 | 复杂度 | 价值 |
|------|--------|------|
| 动态创建人格 | ⭐⭐⭐⭐ | 让用户描述 → 机器人构建 |
| 人格混合 | ⭐⭐⭐ | "小忆 + 理性" 混合风格 |
| 人格对话 | ⭐⭐⭐⭐⭐ | 两个人格互相讨论 |
| 视觉形象 | ⭐⭐ | 配合 Live2D / 数字人 |

### 9.1 人格的三种实现层级

调研中发现的两种微调思路，正好对应人格系统的两条路（详见 [[model-strategy.md]] §3）：

| 层级 | 做法 | 切换开销 | 适合 |
|------|------|---------|------|
| **① 运行时参数**（当前 P0/P1 采用） | 人格写在 system prompt，运行时插拔 | 零延迟、零额外显存 | 多数人格、频繁切换 |
| **② 烘焙进权重** | 每个 persona 训一份 LoRA adapter，人格/世界观/护栏全进权重 | 需换 adapter（Ollama `ADAPTER` 指令） | 人格极稳定、要求"人格漂移为零" |
| **③ 混合** | system prompt 管可变参数（情绪、口语度），LoRA 管不变底色（身份、语域） | 同 ② | 长期方案 |

**TARS 项目的启示**：它在训练时混合了"有 system prompt"和"无 system prompt"两种样本，因此训练出的模型**即使运行时不注入 prompt 也不会人设崩塌**。这正好对应层级 ③ 的做法 —— 训练时保留 sys/no-sys 混合。

**Pingo SFT 的启示**：它的"烘焙模式"证明人格、世界观、护栏全部训进权重是可行的。但护栏拒答样本只占约 8%，说明**烘焙不等于完美** —— 硬护栏仍建议保留在 system prompt 里。

**本项目的取舍**：P0-P3 全部走层级 ①（运行时 prompt）。理由：

- 切换零开销，不占用额外显存
- 16GB 卡上同时挂多份 adapter 不现实
- 人格漂移可以用 `cooldown` + 明确 system prompt 约束缓解

层级 ② 只在"某个 persona 必须绝对稳定"的场景启用，且推迟到 Phase 5 之后（见 [[roadmap.md]] Phase 5）。

---

## 10. 实施优先级

| 优先级 | 模块 | 工作量 |
|--------|------|--------|
| **P0** | 配置 + PersonaManager + 手动切换 | 小 |
| **P1** | 声纹自动切换 | 中 |
| **P1** | 音色动态切换 | 小 |
| **P2** | 时间表自动切换 | 小 |
| **P2** | 记忆隔离 | 小（Mem0 user_id 已支持） |
| **P3** | 动态创建人格 | 大 |

P0 + P1 完成就有完整的多人格体验。