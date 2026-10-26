# 声纹识别与语音情感识别

> 补充模块：让陪伴机器人能"认出是谁在说话"、"听到对方情绪"。
>
> 完整集成设计见 [[companion-features.md]]。

---

## 1. 在整体架构中的位置

```
麦克风
  │
  ▼
Silero-VAD（音频分段）
  │
  ▼
[本模块]  声纹识别  ──→  user_id（不同人不同记忆空间）
  │
  ▼
[本模块]  语音情感识别  ──→  emotion hint（喂给情绪状态机）
  │
  ▼
SenseVoice ASR  ──→  文本
  │
  ▼
进入文字处理流程（参见 [[architecture.md]]）
```

**声纹**：必须发生在 VAD 之后，**用整段语音计算**。
**情感**：可以与 ASR 并行，**用同一段语音同时做识别和情感分类**。

---

## 2. 声纹识别（Speaker Identification）

### 2.1 工作原理

```
注册阶段（enrollment）：
  用户 A 说话 3+ 段，每段 5+ 秒
      ↓
  Resemblyzer 提取 embedding（256 维向量）
      ↓
  平均后存入 data/voiceprints/{user_id}.npy

识别阶段（identification）：
  任何新音频
      ↓
  Resemblyzer 提取 embedding
      ↓
  与已注册的所有 embedding 算余弦相似度
      ↓
  相似度 ≥ 阈值 → 命中；否则 → "未知"
```

### 2.2 关键参数

| 参数 | 默认值 | 调整建议 |
|------|--------|---------|
| `enrollment_samples` | 3 | 越多越准，但用户体验差；3 段够用 |
| `enrollment_min_duration_sec` | 5 | 短于 5 秒的样本忽略（embedding 不稳） |
| `threshold` | 0.75 | 越高越严格（少误识别）；越低越宽松（多识别） |
| `embedding_dim` | 256 | Resemblyzer 固定 |

阈值调试建议：从 0.70 起测，假阳性多就调到 0.80，假阴性多就降到 0.65。

### 2.3 多用户模式

启用声纹后，机器人可以识别不同人：
- **不同的人有独立的记忆空间**（Mem0 用 user_id 区分）
- **不同的人可以有不同的角色定位**（配置文件里定义）
- **不同的人触发不同的主动关怀规则**（如"老婆生日"vs"老板催活"）

配置文件示意：

```yaml
voiceprint:
  enabled: true
  storage: ./data/voiceprints/

  # 多用户配置（可选）
  users:
    - id: me
      role: owner               # 主要使用者，机器人对其最亲密
      greet: "嗨，又见面了。今天想聊什么？"
    - id: wife
      role: family              # 家人，机器人以晚辈身份互动
      greet: "姐，今天辛苦了。"
    - id: kid
      role: child               # 孩子，机器人耐心引导
      greet: "嘿，今天学了什么？"

  # 默认 fallback（识别不出是谁时）
  default_user: me
```

### 2.4 隐私保护（必须做）

声纹属于生物特征，必须做好：

| 措施 | 实现 |
|------|------|
| 只存 embedding | 不存原音频，注册完立刻删除临时 wav |
| `.gitignore` 屏蔽 | `data/voiceprints/` 已默认 ignore |
| 删除接口 | `delete(user_id)` 命令立即清除 |
| 加密存储（可选进阶） | embedding 用机器专属 key 加密后存盘 |

### 2.5 注册流程 UX

第一次使用机器人时，需要引导用户注册：

```
机器人：「为了更好地记住你，需要录几段你的声音。
        可以对着麦克风随便说几句话，每段 5 秒以上，录 3 段。
        说 '开始' 我们就开始录。」

用户：「开始」

机器人：「请说话...」  [录音 8 秒]
机器人：「再录一段...」  [录音 8 秒]
机器人：「最后一段...」  [录音 8 秒]
机器人：「好的，已经记住你的声音了。我叫小明，是吗？」
```

---

## 3. 语音情感识别（Voice Emotion Detection）

### 3.1 工作原理

```
音频段
  ↓
emotion2vec_base 特征提取 + 分类
  ↓
7 类概率分布：{angry: 0.05, happy: 0.02, neutral: 0.78, ...}
  ↓
argmax + 阈值过滤
  ↓
{emotion: "neutral", confidence: 0.78}
```

### 3.1.1 两种来源（2026-10 更新）

| 方案 | 类别数 | 额外模型 | 显存 | 何时用 |
|------|-------|---------|------|--------|
| **SenseVoice-Small 自带标签** | 粗（`<|HAPPY|>` / `<|SAD|>` / `<|ANGRY|>` 等） | **无** | 0 | ✅ **默认首选** —— ASR 反正要跑，情感标签顺手拿 |
| `emotion2vec_base` | 7 类细粒度 | 有 | 0（CPU） | 验收测试发现 SenseVoice 分类太粗时（例如分不清"惊讶"与"害怕"）再启用 |

**决策**：默认走 SenseVoice 自带标签，`voice_emotion.source: sensevoice`。
emotion2vec 保留在配置里作为开关，不是删掉 —— 细粒度在"判断用户是不是强撑着"这类场景仍有价值。

### 3.2 标签集

emotion2vec_base 输出 7 类：

| 英文 | 中文 | 触发状态 |
|------|------|---------|
| `angry` | 生气 | `caring`（先倾听） |
| `happy` | 开心 | `playful` |
| `sad` | 难过 | `caring`（先倾听） |
| `neutral` | 平静 | `neutral` |
| `surprised` | 惊讶 | `neutral` |
| `fear` | 害怕 | `caring`（先倾听） |
| `disgust` | 厌恶 | `caring`（先倾听） |

### 3.3 与文本情感的融合

**两条信号都可能错**，必须融合：

| 文本关键词 | 语音情感 | 综合判断 |
|-----------|---------|---------|
| "我没事" | 难过 | **听语音**（用户嘴上说没事但声音难过） |
| "我今天很累" | 平静 | **听文本**（用户陈述事实，不在情绪中） |
| "哈哈" | 难过 | **取文本**（可能是苦笑，文本更准） |
| "我被骂了" | 开心 | **存疑**（用户可能在讲别人故事） |

实现策略（伪代码见 [[../src/companion/emotion.py]]）：

```python
def transition(user_msg, voice_signal=None):
    text_target = detect_from_text(user_msg)
    
    if voice_signal:
        voice_emotion, confidence = voice_signal
        if confidence >= 0.7:
            voice_target = VOICE_TO_STATE[voice_emotion]
            # 高置信度语音情感，文本无明确信号 → 采用语音
            if text_target is None:
                target = voice_target
            # 文本信号更明确（如"哈哈"）→ 采用文本
            elif text_signal_explicit(user_msg):
                target = text_target
            # 两者冲突但都不绝对 → 取保守的 caring
            else:
                target = "caring"
        else:
            target = text_target or "neutral"
    else:
        target = text_target or "neutral"
    
    return apply_with_cooldown(target)
```

### 3.4 准确率现实预期

不要把语音情感识别想得太神：

| 场景 | 准确率 |
|------|--------|
| 测试集（emotion2vec 训练数据） | 80-85% |
| 真人清晰说话 | 65-75% |
| 嘈杂环境 | 50-60% |
| 耳语 / 咆哮 | 40-50% |

**核心原则**：把它当"辅助信号"，不是"判定依据"。高置信度（>0.7）才用，否则 fall back 到文本或 neutral。

---

## 4. 性能与 VRAM

### 4.1 模型大小

| 模型 | 参数 | 推理显存 (FP16) |
|------|------|-----------------|
| Resemblyzer | ~5M | ~20 MB |
| emotion2vec_base | ~95M | ~400 MB |
| SenseVoice-Small（情感来源，顺带） | 234M | CPU，0 VRAM |

两个生物特征模块加起来不到 0.5 GB，建议**全部 CPU 推理**：
- 单次推理延迟 < 100 ms（音频长度 8s）
- 完全省下 GPU 显存给 LLM 和 TTS

### 4.2 启用语音生物特征后的总账

```
L1 控制面        RAM ~330 MB
L2 主 LLM 9B    VRAM ~11 - 14.6 GB（含桌面常驻 ~4 GB）
L3 语音栈（全部加载时）：
  ├─ VAD          CPU
  ├─ ASR          CPU（含情感标签）
  ├─ TTS          VRAM ~4.0 GB（VoxCPM2 `--n-gpu-layers 8`，实测）
  ├─ 声纹          CPU
  └─ 语音情感       CPU（走 SenseVoice 标签时 0 额外开销）
─────────────────────────────────────
语音峰值合计     VRAM ~13.4 - 17.4 GB / RAM ~600 MB
完全空闲          VRAM ~0（机器人自身）/ RAM ~400 MB
```

> ⚠️ 2026-10-24 实测修正：语音峰值上界已到 16 GB 物理上限，必须先降级
> （关后台程序 + TTS 用 `--n-gpu-layers 8`）→ 峰值 ~12.5 GB。详见 [[hardware-budget.md]]。

**结论**：加上这两个功能，VRAM 峰值只增加约 400 MB（如果放 CPU 就 0 增加），完全可以接受。

### 4.3 何时触发识别

不是每条消息都要跑全部：

| 阶段 | 是否跑 |
|------|--------|
| 打字聊天 | 不跑（纯文本） |
| 语音聊天 · 听 | 跑声纹 + 情感 |
| 语音聊天 · 说 | 不跑（只放音） |

如果性能仍有问题，可以：
- 声纹缓存：同一 session 内识别过的人，5 分钟内不重复识别
- 情感缓存：每段音频识别一次就够了

---

## 5. 配置示例（AstrBot 主配置 `cmd_config.json`）

```yaml
voice:
  # ---- 声纹识别 ----
  voiceprint:
    enabled: true
    storage: ./data/voiceprints/
    model: resemblyzer          # 或 3d_speaker（更高精度）
    threshold: 0.75
    enrollment_samples: 3
    enrollment_min_duration_sec: 5.0

    # 多用户定义（可选）
    users:
      - id: me
        role: owner
        greet: "嗨，又来了。今天想聊啥？"
      - id: family
        role: family
        greet: "姐，今天怎么样？"

    default_user: me

  # ---- 语音情感识别 ----
  voice_emotion:
    enabled: true
    # sensevoice  → 用 ASR 自带的情感标签（首选，零额外模型依赖）
    # emotion2vec → 7 类细粒度，粒度不够时再切
    source: sensevoice
    model: iic/emotion2vec_base
    device: cpu                  # 推荐 CPU，VRAM 紧张留给 TTS
    confidence_threshold: 0.6
    cache_seconds: 5             # 同段音频 5 秒内不重复识别
```

---

## 6. 集成进 handler.py

```python
# 在 handler.py 的 handle() 中：
async def handle(self, user_msg: str, audio: np.ndarray | None = None,
                 sample_rate: int = 16000) -> str:
    self.turn_idx += 1

    # ---- 1. 声纹识别（如果有音频）----
    user_id = self.user_id
    if audio is not None and self.config.get("voice", {}).get("voiceprint", {}).get("enabled"):
        identified, confidence = self.speaker_id.identify(audio, sample_rate)
        if identified:
            user_id = identified
            log.info(f"identified speaker: {identified} (conf={confidence:.2f})")

    # ---- 2. 语音情感识别 ----
    voice_signal = None
    if audio is not None and self.config.get("voice", {}).get("voice_emotion", {}).get("enabled"):
        emo = self.emotion_detector.detect(audio, sample_rate)
        voice_signal = (emo["emotion"], emo["confidence"])

    # ---- 3. 情绪状态机（融合文本 + 语音）----
    emotion_state = self.emotion.transition(user_msg, voice_signal=voice_signal)
    style_hint = self.emotion.current_style_hint()

    # ---- 4. 话题检测 ----
    topic_info = self.topic.on_new_message(self.turn_idx, user_msg)

    # ---- 5. 短期上下文窗口 ----
    ...

    # ---- 6. 长期记忆检索（按 user_id 区分）----
    candidates = await self.mem0.search(user_id, user_msg, top_k=20)
    ranked = self.ranker.rank(candidates)

    # ---- 7. prompt 拼装 ----
    ...
```

---

## 7. 验收测试

部署完成后，按这些场景测试：

| # | 场景 | 期望 |
|---|------|------|
| 1 | 注册新用户 | 录入 3 段音频后，机器人能认出 |
| 2 | 单用户识别 | 同一人再来，识别成功率 > 90% |
| 3 | 多用户识别 | 切换说话人，识别正确 |
| 4 | 陌生人 | 不在声纹库的人 → 不识别（None） |
| 5 | 删除声纹 | 立即生效，后续识别失败 |
| 6 | 悲伤语音 | 文本无关键词，机器人切到 caring 状态 |
| 7 | 开心语音 + 悲伤文本 | "我被甩了"（平淡语气）→ 文本优先 |
| 8 | 假平静 | "我没事"（实际声音抖）→ 切 caring |
| 9 | 性能 | 8 秒音频完整识别 < 200 ms |
| 10 | 隐私 | 删除声纹后，磁盘上 npy 文件也被清除 |

---

## 8. 已知风险与降级

| 风险 | 应对 |
|------|------|
| 声纹模型识别错 | confidence < threshold → 默认用户 + 日志告警 |
| 情感识别低准确率 | confidence < 阈值 → 当作 neutral，不强行切换状态 |
| 用户换感冒嗓子哑 | 重新注册（或临时提高 threshold 到 0.85） |
| 多用户都注册失败 | 关闭 voiceprint.enabled，回退到默认用户 |
| emotion2vec 下载失败 | 默认走 SenseVoice 自带情感标签（不受影响）；或 fallback 到 wav2vec2-base + 简单 MLP head |

---

## 9. 进阶方向（不在本阶段实施）

| 方向 | 说明 |
|------|------|
| 跨设备同步声纹 | 多台机器共享声纹库（家庭成员在不同房间） |
| 实时情感追踪 | 不是一次性分类，而是把整段对话的情感曲线画出来 |
| 情绪触发主动关怀 | 检测到用户连续多次 sad → 主动发关怀消息（而非被动回复） |
| 声纹反欺骗 | 防录音回放攻击（活体检测） |
| 多说话人分离 | 一段音频里多人轮流说（pyannote.audio diarization） |