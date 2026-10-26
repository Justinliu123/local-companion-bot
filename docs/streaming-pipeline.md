# 流式响应管线：从"说完再回"到"边听边说"

> 让机器人能在用户**还没说完**时就开始接收输入、判断要不要回应、必要时打断自己。
>
> 配合 [[companion-features.md]] 与 [[voice-biometrics.md]]，构成完整的低延迟对话体验。

---

## 1. 现状与目标

### 1.1 现状（batch 模式）

```
用户说完 → VAD 触发 → ASR 整段处理 → LLM 生成 → TTS 合成 → 播放
```

**总延迟**：1.6-2.1 秒（用户体感"说完要等一会儿才回"）

### 1.2 目标（streaming 模式）

```
用户说话期间持续接收输入
  ↓
停顿即可启动回应
  ↓
判断该不该回应
  ↓
边生成边合成边播放
  ↓
可被用户中途打断
```

**总延迟**：0.6-0.9 秒（用户体感"几乎无延迟"）

---

## 2. 流式管线架构

```
┌──────────────────────────────────────────────────────────────────┐
│                   Streaming Pipeline                             │
│                                                                  │
│  麦克风 ─→ 音频流 (100-200ms/chunk)                               │
│                ↓                                                 │
│         [Streaming ASR]                                          │
│                ↓ 增量识别文本                                     │
│         [Sentence Boundary Detector]                             │
│                ↓ (标点 + VAD 静音 + min length)                   │
│         ┌──────────────────────┐                                 │
│         │  [Should-Respond Gate]                                 │
│         └──┬───────────────┬────┘                                 │
│       是 ↓               否 ↓                                    │
│  [LLM streaming]       保持沉默（继续监听）                      │
│       ↓ token 流                                                  │
│  [TTS streaming]                                                 │
│       ↓ 音频块                                                    │
│  [扬声器]                                                        │
│       ↑                                                          │
│       └── [VAD Interrupt Handler] 用户开始说话 → 立即停 TTS       │
└──────────────────────────────────────────────────────────────────┘
```

### 2.1 五道延迟关口

| 关口 | 现状 | 流式优化 | 关键参数 |
|------|------|---------|---------|
| **VAD 静音检测** | 500ms | 200-300ms | `min_silence_ms` |
| **ASR 全段处理** | 500-1000ms | 0（并行） | 改用 streaming ASR |
| **LLM 首 token** | 150ms | 100ms | `streaming: true` + KV cache 复用 |
| **TTS 首音频** | 500ms | 300ms | 小批次文本 + 预热音色 |
| **合计** | **1.6-2.1s** | **0.6-0.9s** | — |

### 2.2 关键参数

```yaml
streaming:
  # VAD
  vad_min_silence_ms: 250           # 短一些启动更快，但太短容易误触发
  vad_speech_pad_ms: 200            # 音频前后填充
  
  # ASR
  asr_chunk_ms: 200                 # ASR 输入块大小
  asr_max_buffer_ms: 8000           # 单段最长，超过强制切分
  
  # 句子边界检测
  sentence_end_punctuation: "。！？?!. \n"
  sentence_min_chars: 3             # 短于此长度的输入视为语气词
  
  # 预测启动
  predict_at_silence_ms: 200        # VAD 检测到 200ms 静音即启动 LLM（不等完整 VAD）
  
  # 中途打断
  interrupt:
    enabled: true
    vad_threshold: 0.4              # 用户声音达到此阈值即视为打断
    min_user_speech_ms: 150         # 至少 150ms 才算真的在说话（防误触发）
```

---

## 3. Streaming ASR 选择

不是所有 ASR 都支持流式：

| ASR | 流式支持 | 中文质量 | 推荐度 |
|------|---------|---------|--------|
| **Paraformer (FunASR)** | ✅ 原生流式 | SOTA | ⭐⭐⭐⭐⭐ |
| SenseVoice | ❌ 仅离线 | SOTA | ⭐⭐⭐ |
| Whisper.cpp | ❌ 仅离线 | 良好 | ⭐⭐ |
| **Sherpa-onnx Paraformer** | ✅ 流式 + ONNX 部署 | SOTA | ⭐⭐⭐⭐⭐ |

**推荐改用 Paraformer-streaming 或 sherpa-onnx Paraformer**。原来的 SenseVoice 改成流式会复杂且效果差。

如需保留 SenseVoice（更轻量），用"按 chunk 切分"近似流式：

```python
# 伪流式：每 200ms 切一段送 ASR
chunk_size = int(sample_rate * 0.2)  # 200ms
for i in range(0, len(audio), chunk_size):
    chunk = audio[i:i+chunk_size]
    partial = asr.recognize(chunk)
    yield partial
```

但延迟和准确率都不如真正的 Paraformer streaming。

---

## 4. "判断该不该回应"决策门

### 4.1 决策表

| 用户输入 | 决策 | 后续动作 |
|---------|------|---------|
| 纯语气词（"嗯"/"哦"/"啊"/"..."/空白） | **不回应** | 继续监听 |
| 用户明示（"别说话"/"安静"/"够了"） | **不回应 + 静默 60s** | 进入 quiet mode |
| 自言自语（"我想想..."/"那个..."） | **暂不回应** | 等下一句连起来判断 |
| 自我修正（"我想说... 不对..."） | **不打断** | 等待修正完成 |
| 陈述但无表情（"今天天气不错"） | 视人格决定 | 默认回应一两句 |
| 提问或感叹 | **回应** | 进入 LLM 流式生成 |
| 连续话题延续词（"然后呢"/"继续"） | **回应** | 延续上一话题 |

### 4.2 实现：规则分类器

参考实现见 [[../src/companion/streaming.py]] 的 `ShouldRespondGate` 类：

```python
# 规则 1：纯语气词（不回应）
INTERJECTIONS = {"嗯", "哦", "啊", "嗳", "嘿", "噢", "嗯嗯", "哦哦", "啊啊"}

# 规则 2：明示停止
STOP_PHRASES = {"别说了", "别说话", "安静", "够了", "停", "闭嘴", "不说了"}

# 规则 3：自言自语开场
SELF_TALK_STARTERS = {"我想想", "那个", "就是说", "怎么说呢", "其实"}

# 规则 4：提问/感叹
QUESTION_PUNCTUATION = {"?", "？", "?", "？", "呢", "吗"}
EXCLAMATION_PUNCTUATION = {"!", "！"}
```

### 4.3 决策流程

```python
def should_respond(text: str, audio_present: bool) -> tuple[bool, str]:
    # 1. 静音检测：没声音当然不回应
    if not audio_present:
        return False, "no_audio"
    
    text_stripped = text.strip()
    
    # 2. 纯语气词
    if text_stripped in INTERJECTIONS or len(text_stripped) == 0:
        return False, "interjection"
    
    # 3. 用户明示停止
    if any(p in text for p in STOP_PHRASES):
        return False, "user_stop"
    
    # 4. 自言自语开场
    if any(text.startswith(s) for s in SELF_TALK_STARTERS):
        return False, "self_talk"
    
    # 5. 短输入（< 3 字）— 默认不回应（除非有问号）
    if len(text_stripped) < 3 and not any(c in text for c in QUESTION_PUNCTUATION):
        return False, "too_short"
    
    # 6. 句子未完（无结束标点 + 流式中）— 等待
    # 由 SentenceBoundaryDetector 负责；本函数不处理
    
    # 默认：回应
    return True, "default"
```

---

## 5. 句子边界检测

### 5.1 触发条件

```python
class SentenceBoundaryDetector:
    """判断当前 ASR 输出是否已经"足够完整"可以开始回应"""
    
    END_PUNCTUATION = {"。", "！", "？", "!", "?", ".", "\n"}
    MIN_CHARS = 3
    
    def is_complete(self, text: str, last_vad_silence_ms: int) -> tuple[bool, str]:
        # 1. 有结束标点
        if any(text.endswith(p) for p in self.END_PUNCTUATION):
            return True, "punctuation"
        
        # 2. VAD 检测到停顿 ≥ 250ms
        if last_vad_silence_ms >= 250:
            # 但内容太短就别回
            if len(text.strip()) < self.MIN_CHARS:
                return False, "too_short_after_silence"
            return True, "silence"
        
        # 3. 都没有 → 还在说
        return False, "still_speaking"
```

### 5.2 启动预测（最激进模式）

如果 LLM 够快，可以在 VAD 检测到 200ms 静音时**不等完整停顿**就启动：

```
[完整停顿检测：500ms]        → 安全但慢
[预测启动：200ms 静音即启动] → 快但有"听错"风险（用户继续说）
```

如果用户继续说，**取消当前 LLM 输出，从新输入重启**。代价是一次无效推理。

建议：默认 250ms 预测启动，可在 `astrbot.yaml` 调：

```yaml
streaming:
  predict_at_silence_ms: 250   # 越短越激进
  cancel_on_user_continue: true
  cancel_grace_ms: 100          # 给用户 100ms 继续说，避免频繁 cancel
```

---

## 6. 中途打断

### 6.1 实现思路

播放 TTS 音频时，VAD 继续监听麦克风：

```
TTS 播放中 → 用户开始说话（VAD 阈值 > 0.4，持续 > 150ms）
  ↓
立即停止 TTS 音频输出
  ↓
保留 TTS 已生成的进度（如用户回头问）
  ↓
切换到 listening 模式
  ↓
等待用户完整输入
```

### 6.2 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `interrupt.vad_threshold` | 0.4 | 用户声音达到此概率即视为打断 |
| `interrupt.min_user_speech_ms` | 150 | 至少 150ms 才算真在说话（防止 TTS 误触发） |
| `interrupt.cancel_grace_ms` | 100 | 取消前给用户 100ms"确认" |

### 6.3 实现

```python
# 伪代码
async def monitor_interrupt(playing_task: asyncio.Task, audio_stream):
    while not playing_task.done():
        chunk = await audio_stream.read(50)  # 50ms 块
        if vad.detect_user_speech(chunk) > 0.4:
            # 用户在说话
            playing_task.cancel()
            return "user_interrupted"
        await asyncio.sleep(0.05)
```

---

## 7. 流式 LLM 与 TTS

### 7.1 LLM streaming

Ollama 原生支持 streaming：

```python
async for chunk in ollama.chat(
    model="qwen3.5:9b-q4_K_M",
    messages=[...],
    stream=True,
    think=False,               # Qwen3.5 必须显式关思考模式
):
    token = chunk["message"]["content"]
    yield token
```

AstrBot 的 LLM 抽象层应该已经支持 `stream=True`，确认即可。

### 7.2 TTS streaming

VoxCPM2 / IndexTTS2 / Qwen3-TTS 支持流式合成。两种策略：

| 策略 | 延迟 | 音色质量 | 实现难度 |
|------|------|---------|---------|
| **整句合成** | 高（500ms+） | 高 | 低 |
| **按标点切分合成** | 中（300ms/段） | 中 | 低 |
| **token 级合成** | 低（100ms） | 低（声音断） | 高 |

**推荐按标点切分**：每拿到一个结束标点的文本块就送 TTS：

```python
async for token in llm_stream:
    buffer += token
    if any(buffer.endswith(p) for p in "。！？!?"):
        # 这一句完整了，合成 + 播放
        audio = await tts.synthesize(buffer, emotion=current_emotion_state)
        await audio_queue.put(audio)
        buffer = ""
```

> `emotion` 参数把情绪状态机的当前状态传给 TTS（IndexTTS2 的情感向量 / Qwen3-TTS 的自然语言描述 / VoxCPM2 的音色描述提示），
> 让声音也跟着状态走 —— 这是陪伴感的重要一环。映射见 `astrbot.yaml` 的 `voice.tts.emotion_hints`。

---

## 8. 完整时序图

```
t=0ms    用户开始说话 "我今天..."
t=200    ASR chunk 1: "我"
t=400    ASR chunk 2: "我今天"
t=600    ASR chunk 3: "我今天加"
...持续到...
t=2000   ASR: "我今天加班了"
         VAD: 静音 250ms detected
t=2050   Should-Respond Gate: ✅ "加班" 是有内容
t=2100   LLM start, prompt 已就绪
t=2200   LLM first token: "辛苦了"
t=2300   TTS start synthesizing
t=2600   TTS first audio chunk ready
t=2700   Speaker: 播放第一段
t=2800   LLM token 2: "，"
t=2900   LLM token 3: "吃饭"
...持续流式...
t=4500   LLM 完成
t=4700   TTS 完成
t=5000   Speaker: 播放完成
```

**用户从停嘴到听到机器人声音：~600-700ms**。

---

## 9. 验收测试

| # | 场景 | 期望 |
|---|------|------|
| 1 | 完整句子 | 用户说完停顿 250ms → 机器人开始发声 |
| 2 | 长句子 | 用户说话 5 秒未完 → 不打断 |
| 3 | 纯语气词 | "嗯" → 沉默不回应 |
| 4 | 用户明示 | "别说了" → 沉默 60s |
| 5 | 中途打断 | 机器人说话时用户开始说 → 机器人立刻停 |
| 6 | 取消重启 | 用户停顿 200ms 后继续说 → 取消正在生成的 LLM，从新输入重启 |
| 7 | 延迟测量 | 端到端 < 1 秒（理想 < 800ms） |
| 8 | 流式 TTS | 机器人说话过程无明显卡顿 |
| 9 | 长语音 | 用户说 30 秒 → ASR 增量识别不丢字 |
| 10 | 多说话人 | 切换说话人 → 不混淆上下文 |

---

## 10. 性能与资源

### 10.1 增加的运行时开销

| 组件 | CPU | VRAM |
|------|------|------|
| Streaming ASR (Paraformer) | ~5% | 0 (CPU only) |
| VAD (Silero, 持续监听) | < 1% | 0 |
| 句子边界检测 | < 1% | 0 |
| Should-Respond Gate | < 1% | 0 |
| 流式 LLM | 同非流式 | 同非流式 |
| 流式 TTS | 同非流式 | 同非流式 |
| **总增量** | ~7% CPU | **0** |

**结论**：流式化主要增加 CPU，不占额外 VRAM。

### 10.2 关闭流式（退化路径）

如果性能不够或出问题，可以关闭：

```yaml
streaming:
  enabled: false
# 退化到 batch 模式（~1.6-2.1s 延迟）
```

---

## 11. 实施优先级

| 优先级 | 模块 | 工作量 | 收益 |
|--------|------|--------|------|
| **P0** | 改用 Paraformer streaming ASR | 中 | 大（消除 ASR 延迟） |
| **P0** | LLM + TTS streaming | 小 | 中 |
| **P1** | Should-Respond Gate | 小 | 中（避免尴尬回应） |
| **P1** | VAD Interrupt | 小 | 大（体验质变） |
| **P2** | 预测启动（200ms 即启动 LLM） | 小 | 中 |
| **P2** | Sentence Boundary Detector | 小 | 中 |

P0 完成：从"明显延迟"变成"正常速度"。
P1 完成：从"正常"变成"自然"。
P2 完成：从"自然"变成"贴人"。