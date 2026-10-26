# 本地运行栈（2026-10-25 实测可跑）

> 这台机器上的**实际运行形态**，与 [[deployment.md]] 的通用部署指南互补。
> 所有组件都在 `D:\dev`，互不污染对方的 Python 环境。

## 模块化：四个组件，各自独立启停

```
D:\dev\companion\
├── config.json            统一配置（路径 / 端口 / 环境变量）
├── companionctl.ps1       控制器（start / stop / restart / status / logs）
├── companionctl.bat       cmd 包装
├── logs\                  每个组件的日志
└── .pids\                 各组件 pid
```

```bash
cd D:\dev\companion

companionctl.bat status              # 看四个组件状态 + 显存
companionctl.bat start all           # 一键全起
companionctl.bat start tts asr       # 只起某几个
companionctl.bat stop bot            # 只停某个
companionctl.bat logs tts            # 看某个组件的日志
```

| 组件 | 角色 | 位置 | 环境 | 端口 |
|------|------|------|------|------|
| `ollama` | 对话大脑 | `D:\dev\ollama\ollama.exe` | 绿色版 | 11434 |
| `tts` | 嗓子（Qwen3-TTS，备选） | `D:\dev\qwen3_tts_server.py` | `D:\dev\voxcpm-py` | 8008 |
| `vcpm` | 嗓子（**VoxCPM2，主用**） | `D:\dev\voxcpm2_server.py` | `D:\dev\voxcpm-py` | 8010 |
| `asr` | 耳朵（识别） | `D:\dev\sensevoice_server.py` | `D:\dev\voxcpm-py` | 8009 |
| `bot` | 编排 + WebUI | `D:\dev\AstrBot` | `D:\dev\astrbot-venv` | 6185 |

> ⚠️ 控制器输出**故意用英文**：本机控制台 codepage 是 GBK，中文会乱码，
> 甚至让 PowerShell 解析失败（.ps1 必须存成 UTF-8 **带 BOM**，否则 GBK 读中文注释直接报错）。
> ⚠️ `cmd.exe /c` 带引号命令时，整条命令要**再包一层引号**，否则 cmd 会剥掉引号导致解析失败。

## 组件与文件

| 组件 | 位置 | 环境 | 端口 |
|------|------|------|------|
| **Ollama** v0.40.10 | `D:\dev\ollama\ollama.exe` | 绿色版，无需安装 | 11434 |
| Ollama 模型 | `D:\dev\ollama-models` | `OLLAMA_MODELS` 指向 | — |
| **AstrBot** v4.29.3 | `D:\dev\AstrBot` | `D:\dev\astrbot-venv` | 6185 (WebUI) / 6186 (webchat) |
| **Qwen3-TTS 服务**（备选） | `D:\dev\qwen3_tts_server.py` | `D:\dev\voxcpm-py` | 8008 |
| **VoxCPM2 服务**（主用） | `D:\dev\voxcpm2_server.py` | `D:\dev\voxcpm-py` | 8010 |
| VoxCPM2 权重 | `D:\dev\models\VoxCPM2-official` | safetensors 4.3 GB + audiovae 0.36 GB | — |
| Qwen3-TTS 权重 | `D:\dev\models\Qwen3-TTS-12Hz-1.7B-VoiceDesign` | — | — |
| **SenseVoice 服务** | `D:\dev\sensevoice_server.py` | `D:\dev\voxcpm-py` | 8009 |
| SenseVoice 权重 | `D:\dev\models\sensevoice\` | sherpa-onnx int8 ONNX | — |
| VoxCPM2 权重 | `D:\dev\models\VoxCPM2-official` | — | — |
| CUDA Toolkit 13.4.1 | `D:\dev\CUDA` | 编译 llama.cpp-omni 用 | — |
| ASR 质检模型 | `D:\dev\models\whisper-small` | 系统 Python 3.14 | — |

## 启动顺序

```bash
cd D:\dev\companion && companionctl.bat start all
```

WebUI：http://localhost:6185 （`astrbot` / `astrbot2026`）

> 也可以只起需要的：`companionctl.bat start tts asr`（纯 TTS/ASR 测试，不需要 LLM 和 AstrBot）。

> ⚠️ **Windows 控制台编码**：AstrBot 日志里有 emoji，GBK 控制台会抛 `UnicodeEncodeError` 并吞掉后续日志。
> 启动前设 `PYTHONIOENCODING=utf-8` 和 `PYTHONUTF8=1`。
> ⚠️ **`.bat` 文件必须纯 ASCII**：中文注释在 cmd 的 GBK 下会让 `REM` 行解析错乱。

## Ollama 环境变量（已在 `D:\dev\start-ollama.bat` 里）

```
OLLAMA_HOST=127.0.0.1:11434          # 不要 0.0.0.0（Ollama 无鉴权）
OLLAMA_MODELS=D:\dev\ollama-models
OLLAMA_CONTEXT_LENGTH=8192           # ⚠️ 显存 <24GiB 时默认只有 4096
OLLAMA_KV_CACHE_TYPE=q8_0            # KV cache 量化
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KEEP_ALIVE=5m                 # per-model，提取器可单独设 30s
```

实测：Ollama v0.40.10 自动选中 `cuda_v13` runtime（`compute=12.0 libdirs=ollama,cuda_v13`），Blackwell 正常。

## TTS 服务接口

```bash
# 健康检查（loaded=false 表示模型还没进显存）
curl http://127.0.0.1:8008/health

# 合成
curl -X POST http://127.0.0.1:8008/tts -H "Content-Type: application/json" \
  --data-binary @req.json -o out.wav
# 响应头带元数据：X-Sample-Rate / X-Duration / X-RTF / X-Segments

# 释放显存（配合 L3 懒加载 watchdog）
curl -X POST http://127.0.0.1:8008/shutdown
```

请求体：

```json
{"text": "...", "instruct": "音色+情绪描述", "emotion": "caring",
 "language": "Chinese", "batch_size": 4, "split": true}
```

### ⚠️ VoxCPM2 服务必须关掉 torch.compile

`D:\dev\voxcpm2_server.py` 里：

```python
VoxCPM2.from_pretrained(model_path, device="cuda", load_denoiser=False,
                         optimize=False)   # ← 关掉 torch.compile
```

**开着会出两个问题**（实测，同一句话 5 次）：

| | 输出正确性 | RTF |
|---|---|---|
| `optimize=True`（torch.compile） | 5 次里 3 次是乱码（幻觉成日文/英文） | 4.2 ~ 4.9 |
| `optimize=False` | **6/6 正确** | **1.76** |

原因是句长变化会触发 dynamic shape 重编译，编译出来的图在变长输入上产出垃圾。
命令行加 `--compile` 可以显式打开（默认关）。

> ⚠️ 服务**跑久了还会劣化**（RTF 从 1.76 掉到 4+，即使 LLM 没常驻显存也会掉）。
> `companionctl.bat restart vcpm` 立刻恢复。服务里加了"显存不足就 `empty_cache`"的兜底，
> 但碎片化严重时重启最省事。

### 音色克隆（零样本，不需要训练）

VoxCPM2 自带三种音色能力：

| 方式 | 参数 | 需要什么 |
|------|------|---------|
| Voice Design | `text="(一位温柔年轻女性)你好"` | 一句描述 |
| **零样本克隆** | `reference_wav_path="ref.wav"` | 一段参考音频 |
| 极致克隆 | 再加 `prompt_wav_path` + `prompt_text` | 参考音频 **+ 它的准确文字稿** |
| LoRA 微调 | 仓库的 `scripts/train_voxcpm_finetune.py` | 5~10 分钟该说话人音频 |

克隆出来的音色还能带风格控制：`"(语速稍快,欢快语气)你好"`。

**本机已接好**：参考音频放 `D:\dev\voices\<名字>.wav`（可选同名 `.txt` 放准确文字稿），
服务端 `GET /health` 会列出可用音色，`POST /tts` 传 `{"voice": "<名字>"}` 即可：

```bash
curl http://127.0.0.1:8010/health          # voices 列表
curl -X POST http://127.0.0.1:8010/tts -H "Content-Type: application/json" \
  --data-binary '{"text":"你好呀","voice":"低沉男声"}' -o out.wav
```

AstrBot provider 侧配 `voxcpm2_voice`（名字）即可让机器人固定用这个音色：

```json
{ "id": "voxcpm2_local", "type": "voxcpm2_local", "provider_type": "text_to_speech",
  "voxcpm2_server_url": "http://127.0.0.1:8010",
  "voxcpm2_voice": "低沉男声" }
```

**实测（2026-10-25）**：用参考音频克隆同一句话，基频跟着参考走，ASR 内容 100% 正确：

| 音频 | F0 | 说明 |
|---|---|---|
| 参考 / 低沉男声 | 122.4 Hz | 参考音频 |
| **克隆 / 低沉男声** | **137.1 Hz** | ← 男声区间，音色跟过去了 |
| 参考 / 清脆少女 | 304.8 Hz | 参考音频 |
| **克隆 / 清脆少女** | **280.7 Hz** | ← 女声区间 |
| 对照 / 默认女声（不克隆） | 281.5 Hz | voice-design 生成 |

AstrBot 端到端也验过：机器人输出的音频 F0 115~150 Hz，确实是克隆的男声。

> ⚠️ 克隆**别人**的声音需要对方同意 —— 未经同意做语音克隆属深度伪造，
> 在多地违法，商用还要标注 AI 生成。本机这套用于自己的声音、家人自愿提供的声音。

## AstrBot 的 TTS provider

**接入方式**：AstrBot 的 provider 类型是**硬编码 match**
（`astrbot/core/provider/manager.py` 的 `dynamic_import_provider`），没有 fallback 到
`provider_cls_map`，所以自定义 provider 必须改源码 —— 用可重放的 patch 脚本：

```bash
python scripts/patch-astrbot-qwen3tts.py --astrbot D:/dev/AstrBot
```

它做 5 件事（幂等）：

| # | 文件 | 改动 |
|---|------|------|
| 1 | `astrbot/core/provider/sources/qwen3_tts_source.py` | 放入 provider 实现（装饰器注册到 `provider_cls_map`）|
| 2 | `astrbot/core/provider/manager.py` | 插入 `case "qwen3_tts":` 分支（不加则模块永不被 import）|
| 3 | `astrbot/core/platform/sources/webchat/request_flags.py` | **强制 `enable_streaming=False`**（忽略前端 flags）← TTS 生效的关键 |
| 4 | `astrbot/dashboard/services/live_chat_service.py` | 透传 `action_type`（可选，用于 Live 模式）|
| 5 | `astrbot/core/platform/sources/webchat/webchat_event.py` | **record 部件补 `stored_filename`** ← 前端能播放音频的关键 |

> ⚠️ **AstrBot 升级会丢这些改动** —— 升级后重跑 patch 脚本即可。

### ⚠️⚠️⚠️ 为什么 TTS 在 WebUI 里不生效（改默认值没用！）

**第一层：流式模式下 TTS 被 stage 直接跳过。**

```
webchat 的 request_flags.py 注入 enable_streaming=True
  → 覆盖 provider_settings.streaming_response
  → agent 结果类型 = STREAMING_FINISH
  → result_decorate stage 在 TTS 分支之前 `if is_stream: return`  ← 直接跳过
  → 本地 TTS provider 永远不被调用（文字有、语音没有）
```

**第二层（更隐蔽）：改服务端默认值根本没用。**

前端 `Chat.vue` / `StandaloneChat.vue` 硬编码 `const enableStreaming = ref(true)`，
并通过 `flags` 传给后端。而 `resolve_webchat_request_flags()` 的取值优先级是
**flags > 顶层字段 > 服务端默认值** —— 前端的 flags 永远赢。

**第三层：流式模式下就算补上 TTS 也来不及。**

```
13:26:08  respond.stage:237  Prepare to send - astrbot/astrbot:      ← 空链，先发了
13:26:13  result_decorate.stage:207  TTS request: 小忆，你好呀！      ← TTS 后跑
13:27:50  result_decorate.stage:209  TTS result: ...wav             ← 音频生成了，但消息早发出去了
```

流式模式下消息由 respond stage 通过 `async_stream` 直接推给平台适配器（绕过 chain 处理），
TTS 补出来的 Record 赶不上发送。

**所以正解是在 `resolve_webchat_request_flags()` 里强制 `enable_streaming = False`**
（忽略前端 flags）。代价是没有打字机效果 —— 对话式语音回复本来也不需要。

> 顺带：`stage.py` 的 `is_stream` 分支里也补了 TTS（见下），但那条路因为时序问题
> 实际用不上，保留作为兜底。

### ⚠️⚠️⚠️ 为什么音频附件在 WebUI 里显示不出来

后端已经产出 `Record` 组件、SSE 里也有 `{"type":"record", ...}`，但 WebUI 上只有文字、没有播放器。

前端 `partUrl()` 的取值顺序是：

```
embedded_url -> embedded_file.url -> attachment_id -> stored_filename/filename
```

而 `webchat_event.py` 实时推送的 record 部件原本只有 `data: "[RECORD]xxx.wav"`，
**四个字段一个都没有** → `partUrl()` 返回空串 → `<audio src="">` 渲染不出来。

修法：record 部件补上 `stored_filename`（文件名就存在 `data/attachments/` 下），
前端会自动走 `/api/v1/files/content?filename=xxx.wav`。

> 注意：`message_parts_helper.py` 那条路径（**消息保存**用）本来就带 `attachment_id`，
> 所以**刷新页面看历史消息**是能播放的 —— 只有**实时推送**的那一下缺字段。

### ⚠️⚠️ 为什么 TTS 一开始不生效（最容易卡住的地方）

`enable_streaming` **默认是 `True`**（webchat 的 `request_flags.py` 注入），它会覆盖
`provider_settings.streaming_response`。而流式模式下：

```
agent 结果类型 = STREAMING_FINISH
  → result_decorate stage 在 TTS 分支之前 `if is_stream: return`   ← 直接跳过
  → 本地 TTS provider 永远不被调用（文字有、语音没有）
```

关掉流式后走缓冲路径，结果类型是 `LLM_RESULT` → stage.py 的**原生 TTS 逻辑**正常生效
（按 Plain 段合成 → 产出 `Record` 组件 → 附件落盘）。

排查这类问题时，在 `result_decorate/stage.py` 的 `if is_stream:` 处临时加一行
`logger.info(f"content_type={result.result_content_type}")` 就能一眼看出走的是哪条路。

### ⚠️ Live 模式（`action_type="live"`）的另一条路

`action_type="live"` 走 `run_live_agent`（`astr_agent_run_util.py`），它**自己**按句分块合成 TTS
（`[Live Agent Feeder] 分句: ...`），音频通过 live chat 的 **WebSocket** 推给前端。

但这条路**只对 Live Chat 的麦克风输入有效**（需要 STT provider），且：
- `/api/v1/live-chat/ws` 强制 `ct="live"`（语音输入），文字发不进去
- `/api/v1/unified-chat/ws` + `ct="chat"` 的回包路由到 `message_id` 队列，
  而 ws 订阅监听的是 `ws_sub_*` 队列 → **文字聊天的 ws 客户端收不到消息**
- HTTP `/api/chat/send` + `action_type="live"` → TTS 会跑，但音频进 back_queue，
  HTTP 端点不消费它 → 看不到音频

**结论：文字聊天要用语音，走 `enable_streaming=false` 的普通路径（上面那个），别用 Live 模式。**

### provider 设计要点

- 推理跑在**独立进程**（TTS 服务），AstrBot 只发 HTTP 请求 —— torch + qwen-tts 只装在
  `D:\dev\voxcpm-py`，不污染 AstrBot 的 venv
- **AstrBot 自己会按句切分**、逐句调 `get_audio`（见 `core/astr_agent_run_util.py`），
  所以 provider 收到的是单句，**不需要**再切分（服务端 `split` 传 false）
- `instruct` 同时控制音色与情绪 —— 情绪状态机的 `emotion_hints` 可直接映射

**配置项**（写在 `data/cmd_config.json` 的 `provider` 列表）：

```json
{
  "id": "qwen3_tts_local",
  "provider": "local",
  "type": "qwen3_tts",
  "provider_type": "text_to_speech",
  "enable": true,
  "qwen3_tts_server_url": "http://127.0.0.1:8008",
  "qwen3_tts_instruct": "一位温柔的年轻女性，声音轻柔舒缓，语速偏慢",
  "qwen3_tts_emotion": "caring",
  "qwen3_tts_language": "Chinese",
  "qwen3_tts_timeout": 120,
  "qwen3_tts_batch_size": 4
}
```

并在 `provider_tts_settings` 里打开总开关：

```json
{"enable": true, "provider_id": "qwen3_tts_local"}
```

### LLM provider（Ollama）

同一个 `provider` 列表里：

```json
{
  "id": "ollama_local_9b",
  "provider": "ollama",
  "type": "openai_chat_completion",
  "provider_type": "chat_completion",
  "enable": true,
  "key": ["ollama"],
  "api_base": "http://127.0.0.1:11434/v1",
  "ollama_disable_thinking": true,
  "model": "qwen3.5:9b-q4_K_M",
  "repeat_penalty": 1.0
}
```

- `ollama_disable_thinking: true` → AstrBot 转成 `reasoning_effort=none` → Ollama 转成 `think=false`
  （不加的话每条回复多 800+ token，延迟从 2s 变 30-60s）
- `repeat_penalty: 1.0` —— Ollama 默认 1.1 会损害 Qwen3.5 质量

## 验证脚本

```bash
# 端到端：provider → HTTP → TTS 服务 → WAV → ASR 校验
cd D:/dev/AstrBot
D:/dev/astrbot-venv/Scripts/python.exe D:/dev/test-astrbot-tts.py

# 完整对话链路（LLM → TTS → Record 组件），与 WebUI 点"发送"同一条路
python D:/dev/test-astrbot-api.py "你好呀"

# Live Chat ws（麦克风那条路，需要 STT）
python D:/dev/test-astrbot-live.py "你好呀"

# ASR 单独校验某个 wav
python D:/dev/verify-tts.py out.wav --text "原文"
```

实测输出（2026-10-25）：

```
# provider 级
provider 类: ProviderQwen3TTS
[Qwen3-TTS] 生成完成 3.520s (RTF 3.669) -> qwen3_tts_...wav
时长 3.5s | 相似度 93% | 判定: 完整
转写: 你好呀,我是小易,今天過得怎麼樣?
✅ 链路完整可用

# 完整对话级（WebUI 默认参数）
send 耗时 61.1s
含 record 组件: YES
音频文件: 20261025115201069_ea2f.wav
→ ASR 转写：完整的中文回复（18.1s 音频）
```

> ⚠️ `provider_cls_map` 只有在 provider **模块被 import 后**才填充。独立脚本里要显式
> `from astrbot.core.provider.sources.qwen3_tts_source import ProviderQwen3TTS`
> 才能触发装饰器注册（AstrBot 运行时由 `dynamic_import_provider` 自动触发）。

## 语音对话（麦克风输入 → 语音输出）

### 链路

```
浏览器麦克风
  → 前端降噪/归一化成 PCM16 16kHz mono
  → WebSocket /api/v1/live-chat/ws
  → AstrBot 拼成 WAV
  → SenseVoice STT (本地服务 8009)  → 文本
  → Ollama LLM (Qwen3.5-4B)        → 文字回复
  → VoxCPM2 (本地服务 8010)          → 48kHz 语音
  → WebSocket 回传 base64 WAV → 前端逐句播放
```

### 已验证（2026-10-25）

模拟麦克风帧走完整链路（`D:\dev	est-live-voice.py`）：

```
[STT] {'stt': 'sensevoice_local'}
[识别到的用户输入] 你好呀，今天是个美好的下午，阳光正好...
[流式文本] 哇，今天阳光这么好，确实很适合聊天呢！
[响应] UklGRiSxAwBXQVZFZm10IB...     <- WAV (RIFF) base64
[流式文本] 我过得还挺充实的，一直在思考怎么更好地帮助用户。
[响应] UklGRiRWBABXQVZFZm10IB...
...
[end]
```

**浏览器端**（`D:\dev\test-voice-chat-page.js`，Playwright + Chrome 假麦克风）：

```
[1] 页面加载 OK
[2] ws 已连接
[3] 麦克风已开始采集: 聆听中…
[4] 识别到的用户输入: "你好呀，今天过得怎么样？"
[5] 机器人回复文字: "嘿，今天过得挺充实的！"
[6] 页面上的音频播放器数量: 1
[7] metrics: wav_assemble_time=0.01 stt=sensevoice_local llm_total_time=0.86
              speak_to_first_frame=12.90
[9] JS 错误: 无
```

### 在 WebUI 里用

⚠️ **官方 WebUI 里没有 Live Mode 按钮**：
`ChatInput.vue` 声明了 `openLiveMode` 事件但没人监听，`LiveMode.vue` 从未被引用，
而 dashboard 直接伺服预编译的 `data/dist` —— 改 Vue 源码要整套重新 build。

所以走**独立语音页**：

```
http://127.0.0.1:6185/voice-chat.html
```

（源码在 `D:\dev\AstrBot\data\dist\voice-chat.html`，单文件，无构建步骤。）

用法：填用户名密码 → 点「连接」→ 点「🎤 开始说话」→ 说话 → 自动断句发送 →
机器人逐句回语音，页面直接内嵌播放器。

页面做的事：

| 环节 | 实现 |
|------|------|
| 采集 | `getUserMedia`（**AGC 关闭**，开启会把信号顶到削波）→ `AudioContext 16 kHz` → `ScriptProcessorNode` |
| 增益 | 采集后统一归一化到 0.9 满幅（不同麦克风电平差异大，统一后 ASR 更稳；放大上限 4 倍） |
| 回声 | 采集链必须经 **0 增益节点**连到 `destination`，否则麦克风声音会原样放出来 |
| VAD | **自适应**：跟踪环境噪声底，阈值 = max(0.002, 噪声底 × 2)；峰值超阈值 2 倍也算人声 |
| 结束条件 | 必须先检测到人声，静音 1200 ms 才算说完；最长录 15 s 强制发送 |
| 手动发送 | 录着的时候再点一次按钮 → 立刻发送（没检测到声音则取消） |
| 输入设备 | 顶部下拉框可切换麦克风（授权后才有设备名），选择记在 localStorage；设备插拔会自动刷新列表 |
| 状态显示 | 底部有输入电平条 + 麦克风设备名；麦克风被静音/断开会提示 |

> ⚠️ **阈值必须自适应**：真麦克风电平比假设备低得多，固定阈值 0.02 会永远够不到
> —— 表现就是「一直显示聆听中，说完也不发送」。
> ⚠️ **中文句中停顿比英文长**，静音阈值 900 ms 会在"你好呀，（停顿）今天怎么样"
> 的中间切断。实测用 1200 ms 才完整。
> ⚠️ 切片发送时**必须带 `byteOffset`/`byteLength`**：
> `new Uint8Array(slice.buffer)` 取的是整个底层 buffer 的开头，
> 每一片都会把整段音频重发一遍（后端会听到 2~3 倍重复）。

### 实测延迟（2026-10-25）

```
STT (SenseVoice)      0.4 s
LLM (Qwen3.5-4B)      0.8 s   ← 热态；冷启动（每次重载模型）要 3.9 s
TTS 首句 (VoxCPM2)    4 ~ 17 s ← RTF 1.76，正比于回复长度
─────────────────────────────
首帧语音            5.3 ~ 20 s
```

> LLM 冷启动每轮 3.6 s，所以 `OLLAMA_KEEP_ALIVE` 从 `0` 改成 `5m`（LLM 常驻显存）：
> 实测显存 13892 / 16311 MiB（余 2419 MiB），TTS 侧 RTF 不受影响（两边都 1.76）。
> 改回 `0` 只需改 `D:\dev\companion\config.json` 里 `ollama.env.OLLAMA_KEEP_ALIVE`。
>
> ⚠️ TTS 服务**跑久了会劣化**（RTF 从 1.76 掉到 4+）：`companionctl.bat restart vcpm`
> 即可恢复。服务里加了"显存不足就 empty_cache"的兜底，但碎片化严重时还是重启最省事。
>
> ⚠️ **启动必须预热**：CUDA kernel / 显存池要跑几次才进稳态，
> 不预热的话第一个真实请求要 **44 秒**（RTF 69），跑 3~5 次才降到 1.8。
> `voxcpm2_server.py` 的 `_warmup()` 在模型加载后连发 3 条短句（约 16 s）。
>
> ⚠️ **`OLLAMA_KEEP_ALIVE` 实测取 `5m` 比 `0` 好**（虽然 LLM 常驻会让 TTS 的 RTF
> 从 1.90 涨到 2~3.5）：
>
> | 配置 | LLM 耗时 | 首帧语音 |
> |---|---|---|
> | `0`（每轮重载模型） | 4.3 ~ 4.9 s | 13.6 ~ 18.0 s |
> | `5m`（常驻显存） | 0.4 ~ 0.7 s | **3.8 ~ 13.7 s** |
>
> 显存占用 13876 / 16311 MiB（余 2435 MiB）。改法：
> `D:\dev\companion\config.json` → `components.ollama.env.OLLAMA_KEEP_ALIVE`。

### 关键配置

```json
// cmd_config.json
"provider": [
  { "id": "sensevoice_local", "type": "sensevoice_local", "provider_type": "speech_to_text",
    "enable": true, "sensevoice_server_url": "http://127.0.0.1:8009" },
  { "id": "voxcpm2_local", "type": "voxcpm2_local", "provider_type": "text_to_speech",
    "enable": true, "voxcpm2_server_url": "http://127.0.0.1:8010",
    "voxcpm2_instruct": "一位温柔的年轻女性，声音轻柔舒缓，语气充满关心。" },
  { "id": "qwen3_tts_local", "type": "qwen3_tts", "provider_type": "text_to_speech",
    "enable": true, "qwen3_tts_server_url": "http://127.0.0.1:8008",
    "qwen3_tts_instruct": "一位温柔的年轻女性，声音轻柔舒缓，语速偏慢",
    "qwen3_tts_emotion": "caring" }
],
"provider_stt_settings": { "enable": true, "provider_id": "sensevoice_local" },
"provider_tts_settings": { "enable": true, "provider_id": "voxcpm2_local" }
```

> ⚠️ **两个 TTS 引擎不要同时跑**：VoxCPM2 ~5.7GB + Qwen3-TTS ~6.3GB + 桌面 ~4.4GB > 16GB。
> 切换引擎：`companionctl.bat stop tts && companionctl.bat start vcpm`，
> 然后在 `cmd_config.json` 里改 `provider_tts_settings.provider_id` 并重启 AstrBot。

> ⚠️ SenseVoice 的 **ONNX 模型文件必须完整** —— 之前有一次下载卡在 13%，
> 留下的文件头是 `{"Code":10990101`（ModelScope 的错误 JSON），加载时报
> `InvalidProtobuf ... Protobuf parsing failed`。用 `onnxruntime` 直接 load 一下就能验。

## 诊断插件

`D:\dev\AstrBot\data\plugins\companion_tts\` —— 提供：

- `/tts_test` 命令：在 WebUI 对话框里手动测 TTS
- **启动自检**：AstrBot 起来后自动跑一次，日志里给出结论

> ⚠️ 自检**不能**同步写在 plugin 的 `initialize()` 里 —— 实测 provider 的加载排在
> **所有 plugin 的 initialize 之后**，同步写会永远等不到 provider。
> 正确做法是 `asyncio.create_task()` 起后台任务，initialize 立即返回。

> ⚠️ Windows 控制台编码：AstrBot 日志里有 emoji，GBK 控制台会抛 `UnicodeEncodeError`
> 并吞掉后续日志。启动前设 `PYTHONIOENCODING=utf-8` 和 `PYTHONUTF8=1`。

## 显存现状（16 GB 卡）

**主模型用 4B**（当前配置）：

| 组件 | 显存 |
|------|------|
| 桌面常驻（Chrome / ToDesk / QQLive / wallpaper64 …） | ~4.4 GB |
| Ollama + `qwen3.5:4b-q4_K_M` | ~3.4 GB（含 KV cache）|
| Qwen3-TTS（`--n-gpu-layers 8`） | ~4.0 GB |
| **合计（实测峰值）** | **12189 MiB ✅ 余量 3862 MiB** |

→ 4B 方案**不需要关后台程序**就能跑语音模式。

**如果换回 9B**：

| 组件 | 显存 |
|------|------|
| 桌面常驻 | ~4.4 GB |
| Ollama + `qwen3.5:9b-q4_K_M` | ~7.8 GB |
| Qwen3-TTS | ~4.0 GB |
| **合计（实测峰值）** | **15404 MiB ❌ 余量仅 607 MiB** |

→ 9B 方案**必须先关掉 Chrome / ToDesk / QQLive**（腾 ~3 GB），否则 OOM。

## 4B vs 9B（本机实测，2026-10-25）

| 指标 | **4B Q4_K_M** | 9B Q4_K_M |
|---|---|---|
| LLM 热状态总延迟 | **0.34 s** | 1.70 s |
| LLM 生成速度 | **100.2 tok/s** | 56.5 tok/s |
| 端到端（含 TTS） | **24.2 s** | 61.1 s |
| 峰值显存 | **12189 MiB** ✅ | 15404 MiB ❌ |
| 磁盘 | 2.7 GB | 6.6 GB |
| 文本质量 | 够用（回复更简洁）| 更好 |

> 结论：**16 GB 卡上跑语音陪伴，4B 是更合适的主模型** —— 延迟快 2.5 倍、显存宽裕 3 GB、
> 而且不用动后台程序。9B 留给"纯文字对话"模式（那时显存不是问题）。

> ⚠️ 注意 Ollama 的 `keep_alive=5m`：两个模型都跑过时会**同时驻留**。
> 用 `ollama stop <model>` 手动卸载，或按需只启动一个。

## ⚠️ 显存竞争：LLM 和 TTS 不能同时驻留

16 GB 卡上，Ollama 的 LLM 和 TTS 服务会**互相踩显存**：
TTS 的请求会**卡死**（不是报错，是 CUDA 调用挂住，provider 120 秒超时返回空路径）。

实测过一次：LLM 3.1 GB + TTS 7.4 GB + 桌面 4.4 GB = 14.9 GB，
生成时 TTS 需要临时显存，**直接死锁**。

**解法：`OLLAMA_KEEP_ALIVE=0`** —— LLM 每个请求结束就立刻卸载，
这样 TTS 合成时显存是空的（实测余量 7.7 GB）。

> 代价：每轮对话 LLM 冷启动（4B 从磁盘读 2.7 GB，约 1-2 秒）。
> 换来的是 TTS 稳定不死锁。

> ❌ **不要用 `device_map="auto"` + `max_memory` 把 TTS 的部分层卸载到 CPU**：
> 实测混合设备会让生成**退化** —— 7 个字生成 43 秒音频的幻觉循环，RTF 3.96。
> 显存紧张要靠"让 LLM 卸载"解决，**TTS 必须全 GPU**。

## 已知问题

1. **首帧语音延迟 5~20 秒**：TTS 是最大头（RTF 1.76，正比于回复长度），
   其次是 LLM（热态 0.8 s / 冷态 3.9 s）。回复越短越快 —— 想要"秒回"就让人格
   提示词限制回复长度（1~2 句、30 字内）。
2. **HuggingFace 直连超时** —— 走 `hf-mirror.com`；Ollama 的 registry 也很慢，
   模型从 HF 镜像下 GGUF 再 `ollama create` 导入（见 README 的说明）。
3. **4B 模型偶尔答非所问** —— 实测出现过一轮吐 HTML/CSS 的回复。
   陪伴场景建议在人格提示词里锁定输出格式。
