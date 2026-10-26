# 架构详解

## 数据流

### 模式 A：文字聊天（默认）

```
用户消息
  │
  ▼
AstrBot 接收（Web / QQ / 微信 / CLI）
  │
  ├──→ 短期对话历史 (sqlite，滑动窗口 20 轮)
  │
  ├──→ Mem0 API ──→ top-k=5 相关长期记忆注入 prompt
  │       │
  │       └──→ (异步) 每 5 轮调用一次小型 LLM (qwen3.5:2b-q4_K_M，冷路径)
  │                提取本轮要点写入 ChromaDB
  │
  ▼
组装完整 prompt：
  [系统人格]
  [Mem0 注入的长期记忆]
  [最近 20 轮对话]
  [用户当前输入]

  ▼
Ollama /v1/chat/completions (qwen3.5:9b-q4_K_M, think=false, repeat_penalty=1.0)
  │
  ▼
流式 token 输出 → AstrBot → 用户界面
```

### 模式 B：语音交互

```
麦克风音频 (48 kHz mono)
  │
  ▼
Silero-VAD (5ms 延迟)
  │ 检测到人声段开始 → 缓存音频
  │ 检测到人声段结束（>500ms 静音） → 送入 ASR
  │
  ▼
SenseVoice-Small ASR (CPU 推理，~200MB)
  │ 中文识别率 SOTA；自带情感标签 → 情绪状态机
  ▼
进入文字聊天模式

LLM 输出文本
  │
  ▼ 边生成边送 (流式 TTS)
VoxCPM2 (GPU 推理，权重 ~3.3GB；llama.cpp-omni 部署)
  │ 文字描述生成音色；情绪由提示词驱动
  ▼
音频流 → 扬声器

VAD 同时监测：
  - 检测到用户插入 → 立即停止当前 TTS 输出
  - 重新进入录音状态
```

## 组件职责

### AstrBot（调度中枢）
- 接收外部消息（多端适配）
- 短期上下文管理（滑动窗口）
- 调用 LLM，组装 prompt
- 调用 TTS 流式输出
- **不持久化任何用户数据**

### Mem0（记忆引擎）
- **写入**：每 5-10 轮触发「提取器」，生成 `{fact, tags, importance}` 结构化记忆
- **检索**：每轮对话 embedding 当前 query，向量检索 top-k=5
- **存储**：ChromaDB 本地单文件，text2vec-base-chinese-paraphrase 向量化（CPU 即可）

### Ollama（本地推理）
- OpenAI 兼容 API: http://127.0.0.1:11434/v1
- 主模型：`qwen3.5:9b-q4_K_M` (~7.6G 显存 + ~0.4G KV cache，q8_0)
- 提取器：`qwen3.5:2b-q4_K_M` (~2.3G 显存，冷路径，keep_alive=30s 独立卸载)
- `OLLAMA_KEEP_ALIVE=5m` 自动卸载空闲模型
- **Qwen3.5 思考模式关闭**（顶层 `think: false`，不是 `options.think`）
- **`repeat_penalty: 1.0`**（Ollama 默认 1.1 会损害 Qwen3.5 质量）
- ⚠️ 必须 `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0`，否则 KV 显存翻倍

### ChromaDB（向量库）
- 内嵌模式运行，单文件持久化
- 默认端口 8000
- 提供 HTTP API

### TTS（语音合成）
- **两个独立服务**（不是 Ollama 模型）：VoxCPM2（:8010，主）/ Qwen3-TTS 1.7B（:8008，备）
- `instruct` 同时控制音色与情绪 → 情绪状态机的 `emotion_hints` 可直接映射
- 显存各 ~4-6 GB，**绝不能同时跑**（加上桌面常驻会超 16 GB）
- 降级链：VoxCPM2 → Qwen3-TTS 1.7B → IndexTTS2（半精度，24G+ 才值得）→ CosyVoice2-0.5B → Spark-TTS
- 实测细节（torch.compile 必须关、预热 44 秒、RTF 劣化要重启）见 [[local-stack.md]]

### SenseVoice-Small（语音识别）
- FunASR 出品
- 中文识别率 SOTA
- ~200M 参数，CPU 推理足够实时
- **自带情感 + 事件检测** → 可替代独立的 emotion2vec 依赖

## 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 主对话模型大小 | Qwen3.5-9B Q4_K_M | 16G 显存下中文质量最强的可装选项；原生 256K 上下文 + 原生多模态 |
| 记忆提取器大小 | Qwen3.5-2B Q4_K_M | 提取是受限任务（输出 JSON）；冷路径可独立卸载，不占 TTS 显存 |
| 提取器加载策略 | 冷路径，keep_alive=30s（单次请求覆盖） | 每 5 轮才跑一次；语音峰值时不叠加提取器显存 |
| TTS 输出方式 | 流式分块 | 首字延迟从 1.5s 降到 300ms |
| TTS 模型 | VoxCPM2（llama.cpp-omni） | 中文 CER 0.97%；权重仅 ~3.3GB（GGUF Q8_0），够本机塞下语音峰值；GGUF 单二进制、无 Python 依赖 |
| 语音情感来源 | 优先 SenseVoice 自带标签 | 省掉一个独立模型依赖；粒度不够时再切 emotion2vec |
| VAD 打断 | Silero + cosine 相似度 | 用户说错可立即打断重说 |
| 提取间隔 | 每 5 轮 | 平衡记忆新鲜度与 LLM 调用成本 |
| 默认端口 | 11434 / 8000 / 8888 / 6185 | 不冲突常用服务 |
| 静音超时卸载 | 60 秒 | 谈话间隙不等于会话结束 |

## 异常路径

### 显存 OOM
- **先关后台程序**（Chrome / ToDesk / QQLive 等，零成本 -3 GB —— 本机桌面常驻占 ~4 GB）
- **TTS 降级**：VoxCPM2 → Qwen3-TTS 1.7B → IndexTTS2（半精度）→ CosyVoice2-0.5B → Spark-TTS
- **主模型降级**：`qwen3.5:9b-q4_K_M` → `qwen3.5:4b-q4_K_M` → `qwen3.5:2b-q4_K_M`
- **提取器降级**：`qwen3.5:2b-q4_K_M` → `qwen3.5:0.8b-q4_K_M` → 主对话自提取
- AstrBot 启动时探测 `nvidia-smi` 的可用显存，自适应选择
- 完整阶梯见 [hardware-budget.md](hardware-budget.md)

### Ollama 进程崩溃
- AstrBot 检测 API 不可达 → 自动重试 + 提示用户重启 LLM

### Mem0 不可用
- AstrBot 自动降级为「无长期记忆模式」，本地短期 context 仍工作

### 声卡不可用
- 自动 fallback 到纯文字模式，启动日志会提示

## 不在本方案的扩展

- ❌ 多用户支持（单用户场景）
- ❌ 联网搜索（纯离线）
- ❌ 图像理解（暂不需要）
- ❌ Web 抓取 / 工具调用（可后续单独扩展）
