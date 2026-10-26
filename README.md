# 本地陪伴机器人 (Local Companion Bot)

> 基于 **Mem0 + Ollama (Qwen3.5-9B + Qwen3.5-2B) + AstrBot** 的全本地、隐私优先的 AI 陪伴机器人方案。

## 目标

打造一个**真正懂你**的本地情感陪伴机器人，所有数据不出本机：

- 🧠 **长程记忆**：能记住你上周、上月、去年提过的事
- 💬 **自然对话**：Qwen3.5-9B 级别的中文情商（原生 256K 上下文 + 原生多模态）
- 🗣 **语音交互**：可选，全流程延迟 < 2s
- 🔌 **按需开关**：闲置自动释放显存，不影响机器日常使用

## 目标硬件

- **GPU**：NVIDIA RTX 5060 Ti 16G（也可适配 RTX 4070 / 4070 Ti 同档）
- **内存**：≥ 32 GB 推荐
- **系统**：Windows 11 22H2+（本指南）或 WSL2 / Ubuntu 22.04
- **存储**：SSD ≥ 200 GB 可用空间

> ✅ **2026-10-24 实测确认**：开发/目标机就是一台 i5-14600KF + RTX 5060 Ti 16GB + 32GB DDR5-6000 的 Windows 11 机器，选型与账本已按该配置实测复核（见 [docs/model-strategy.md](docs/model-strategy.md) §0.5）。
>
> ⚠️ **一个必须知道的约束**：这台机器的桌面程序（Chrome / ToDesk / QQLive / wallpaper64 等）常驻占用约 **4 GB 显存**，所以 Ollama 实际可用显存是 **~12 GB 而非 16 GB**。所有预算按 12 GB 算。

## 架构概览

```
            ┌──────────────────────────────────────────────────┐
            │                  AstrBot (调度中枢)                │
            │                                                  │
            │   短上下文  ──→  Mem0 检索注入 ──→  Ollama 推理   │
            └──────────────────────────────────────────────────┘
                       ↓ 写入                 ↓ 文本回复
                    ChromaDB               TTS (可选)
                                              ↓
                                          扬声器 / 文件
```

完整架构详见 [docs/architecture.md](docs/architecture.md)。

## 陪伴能力模块

为了让机器人像"伙伴"而非"工具"，除基础架构外还有 9 个核心模块：

| 模块 | 作用 | 文档 |
|------|------|------|
| 情绪状态机 | 控制回应温度，避免用户难过时被强行安慰 | [§1](docs/companion-features.md#1-情绪状态机-emotion-state-machine) |
| 主动关怀调度 | 主动发问候/跟进，但有反骚扰机制 | [§2](docs/companion-features.md#2-主动关怀触发器-proactive-care-scheduler) |
| 话题切换检测 | 防止上下文断裂后接错话题 | [§3](docs/companion-features.md#3-话题切换检测-topic-switch-detection) |
| 记忆优先级衰减 | 长期使用后不"乱记"，重要的事留下 | [§4](docs/companion-features.md#4-记忆优先级与衰减-memory-ranking--decay) |
| 声纹识别 | 识别说话人，支持多用户独立记忆空间 | [voice-biometrics §2](docs/voice-biometrics.md#2-声纹识别speaker-identification) |
| 语音情感识别 | 从声调识别情绪，与文本情感融合 | [voice-biometrics §3](docs/voice-biometrics.md#3-语音情感识别voice-emotion-detection) |
| 流式响应管线 | 边听边说、停顿即回应、可被中途打断 | [streaming-pipeline](docs/streaming-pipeline.md) |
| 多人格系统 | 多种角色可切换，支持家人不同体验 | [persona-system](docs/persona-system.md) |
| **形象层（桌宠）** | 给机器人一个透明置顶的身体，跟随情绪/状态做动画 | [avatar-integration](docs/avatar-integration.md) |

参考实现位于 [`src/companion/`](src/companion/)，可按目标机器的依赖环境调整。

## 关于"为什么用两个模型而非一个"

设计采用 **Qwen3.5-9B 主对话 + Qwen3.5-2B 提取器** 的双模型方案，背后的取舍（并发 vs 简洁）见 [docs/model-strategy.md](docs/model-strategy.md)。

关键在于**提取器是冷路径**：它每 5 轮才跑一次，而 Ollama 的 `keep_alive` 是**按模型**生效的 —— 提取器请求带 `"keep_alive": "30s"` 就能让它自己卸载，**语音交互时它不占 TTS 的显存**。这正是 9B 主模型 + 语音栈能塞进 16GB 的原因。

如果显存紧张或想更简单，可以一键退化为**只用 9B** 的单模型方案（把 `mem0.env` 的 `LLM_MODEL` 指向主模型即可）。

> ⚠️ **Qwen3.5 在 Ollama 上有五个坑**（`think` 位置、`num_ctx` 默认 4096、`repeat_penalty` 被静默忽略、默认 1.1 损害质量、KV cache 翻倍）—— 配置模板里都已修正，详见 [docs/model-strategy.md](docs/model-strategy.md) §5。

### 微调 / 特调模型

调研了开源社区的中文陪伴向微调模型（Pingo SFT、WSAI-Heart-Pro、lianren-4b 等），结论是**当作增强而非替代**：Phase 1-4 用基座模型 + 好 prompt，Phase 4-5 做 bake-off 对比，Phase 5+ 再考虑自训。详见 [docs/model-strategy.md](docs/model-strategy.md) §3。

## 显存预算（RTX 5060 Ti 16G）

| 工作状态 | 显存占用 | 备注 |
|---------|---------|------|
| **完全空闲** | < 0.5 GB | Ollama 进程驻留，模型已卸载（桌面自身另占 ~4 GB） |
| **纯文字聊天** | ~11 - 14.6 GB | 主模型 9B Q4 (7.6) + 提取器 2B Q4 (2.3) + KV cache (0.4) + 桌面开销 (0.5-4) |
| **语音交互峰值** | ~13.4 - 17.4 GB | ⚠️ 上界越过 16GB，**必须先降级**：关后台程序 → ~13.5 GB（余量 2.8GB）|
| **打游戏（停机器人）** | 机器人自身 0 GB | `stop-companion.ps1` 释放模型；但桌面自身仍占 ~4 GB（无核显，GPU 负责显示输出） |

> ⚠️ 数字为 **2026-10-24 实测复核后的值**，与旧版的差异（9B 权重实为 7.6GB 而非 6.6GB、2B Q4_K_M 实为 1.9GB 而非 2.7GB、语音峰值上界越过物理显存）见 [docs/model-strategy.md](docs/model-strategy.md) §0.5 与 [docs/hardware-budget.md](docs/hardware-budget.md)。

详见 [docs/hardware-budget.md](docs/hardware-budget.md)。

## 服务分层（按需开关）

| 层级 | 内容 | 策略 |
|------|------|------|
| **L1 控制面** | AstrBot、Mem0 API、ChromaDB | 常驻，~400 MB RAM |
| **L2 主 LLM** | Ollama + Qwen3.5-9B | 闲置 5 分钟自动从显存卸载 |
| **L2' 提取器** | Ollama + Qwen3.5-2B | 冷路径，独立 30 秒 keep_alive（更早卸载） |
| **L3 语音** | Qwen3-TTS 1.7B（可控情绪）+ SenseVoice ASR | 60 秒无语音即释放 |

详见 [docs/service-lifecycle.md](docs/service-lifecycle.md)。

## 目录结构

```
local-companion-bot/
├── README.md                              ← 当前文件
├── CLAUDE.md                              ← 部署机 agent 的自动入口（红线 / 当前状态 / 待确认项）
├── docs/                                  ← 设计文档
│   ├── local-stack.md                     本机实际运行栈（组件位置/端口/启动顺序/验证脚本）
│   ├── architecture.md                    详细架构与数据流
│   ├── hardware-budget.md                 显存、内存、功耗账本
│   ├── service-lifecycle.md               服务的开关与分层策略
│   ├── companion-features.md              陪伴能力 4 大模块设计
│   ├── voice-biometrics.md                声纹 + 语音情感设计
│   ├── streaming-pipeline.md              流式响应管线（边听边说）
│   ├── persona-system.md                  多人格系统设计
│   ├── model-strategy.md                  模型选型与微调策略
│   ├── avatar-integration.md              形象层（桌宠）集成方案
│   └── deployment.md                      目标机器部署指南
├── scripts/                               ← 启动 / 关闭 / 服务化脚本
│   ├── start-companion.ps1                一键启动
│   ├── stop-companion.ps1                 一键关闭并释放显存
│   ├── install-windows-service.ps1        注册 Windows 服务（可选）
│   ├── uninstall-windows-service.ps1      卸载 Windows 服务
│   ├── patch-astrbot-qwen3tts.py          AstrBot TTS provider 补丁（可重放）
│   └── test-avatar.py                     形象层适配器冒烟测试
├── config/                                ← 配置示例（不要提交真实密钥）
│   ├── ollama.env.example                 Ollama 环境变量
│   ├── mem0.env.example                   Mem0 后端配置
│   └── avatar.example.yaml                形象层（桌宠）配置
├── plans/
│   └── roadmap.md                         阶段路线图
├── src/companion/                         ← 陪伴能力参考实现
│   ├── emotion.py                         情绪状态机（含语音融合）
│   ├── topic.py                           话题切换检测
│   ├── memory_rank.py                     记忆评分与衰减
│   ├── proactive.py                       主动关怀调度
│   ├── voice_bio.py                       声纹识别 + 语音情感
│   ├── persona.py                         多人格管理
│   ├── streaming.py                       流式响应管线
│   ├── avatar.py                          形象层（桌宠 dsh-pet）HTTP 适配
│   └── handler.py                         主消息处理（组合上面所有）
├── data/                                  运行时数据（gitignored，含声纹）
├── models/                                模型权重（gitignored）
├── logs/                                  日志输出（gitignored）
└── .gitignore
```

## 快速开始

> 🖥️ **本机已有可跑的实例**（2026-10-25 实测通过）：Ollama + AstrBot + Qwen3-TTS 都已装在 `D:\dev`。
> 启动顺序、端口、配置、验证脚本见 **[docs/local-stack.md](docs/local-stack.md)**。

```powershell
# 通用部署（换机器时用）
.\scripts\start-companion.ps1

# 文字聊天（最低占用）
# 浏览器打开 AstrBot WebUI: http://127.0.0.1:6185

# 不用时关闭，释放全部资源
.\scripts\stop-companion.ps1
```

完整步骤见 [docs/deployment.md](docs/deployment.md)。

## 当前状态

**Phase 1-2 进行中。** 本机已完成：

- ✅ 目标机环境验证（RTX 5060 Ti 16G / 32GB DDR5 / Ollama v0.40.10 跑在 `D:\dev`）
- ✅ TTS 引擎选型与实测（Qwen3-TTS 1.7B 主引擎 / VoxCPM2 备选，ASR 逐句校验内容完整）
- ✅ **TTS provider 已接进 AstrBot**（可重放 patch 脚本，端到端验证通过）
- ✅ 按句切分 + batch 流程（batch=4 → 显存 5.49 GB / RTF 1.64）
- 🔄 Ollama 模型拉取中，LLM 对话链路待接

详见 [docs/local-stack.md](docs/local-stack.md) 与 [plans/roadmap.md](plans/roadmap.md)。

## License

TBD
