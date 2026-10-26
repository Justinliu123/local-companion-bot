# 模型选型策略（2026-10 换代版）

> 本文档回答三个问题：**用什么模型？为什么？微调/特调模型要不要用？**
>
> 涉及组件：Ollama / Qwen3.5-9B（主对话）/ Qwen3.5-2B（提取）/ Mem0 / AstrBot 摘要 / TTS / ASR
>
> 相关文档：[[architecture.md]] / [[hardware-budget.md]] / [[voice-biometrics.md]]
>
> **上次全量调研：2026-10-22**。开源自 2026 年初的迭代非常快，本文 §0 之后的所有数字都在该日期复核过。
>
> **2026-10-24 补充：在目标机（RTX 5060 Ti 16G / i5-14600KF / 32 GB DDR5）上实测复核了显存账本，修正 4 处偏差 —— 见 §0.5。** 涉及显存数字的段落（§1、§2、§6.2）与 TTS 段落（§4.1）均已同步。

---

## 0. 2026-10 换代结论（先看这里）

### 0.1 一句话

> **主对话换成 Qwen3.5-9B，提取器换成 Qwen3.5-2B，TTS 从 CosyVoice 换成 VoxCPM2（首选）/ IndexTTS2 / Qwen3-TTS。**
> 显存比上一版多约 2 GB，但通过"提取器冷路径自动卸载"抵消；TTS 选轻量方案后，语音峰值也能塞进本机实际可用的 ~12 GB。

### 0.2 选型表

| 位置 | 旧（2026-01） | **新（2026-10）** | 显存 | 理由 |
|------|--------------|-----------------|------|------|
| 主对话 | `qwen3:8b-instruct-q4_K_M` | **`qwen3.5:9b-q4_K_M`** | 7.6 GB | 同尺寸中文 EQ / 推理全面领先；原生多模态；256K ctx |
| 提取 / 摘要 | `qwen3:1.7b-instruct-q4_K_M` | **`qwen3.5:2b-q4_K_M`** | 2.3 GB | JSON / importance 评分比 1.7B 稳；冷路径可独立卸载 |
| TTS | CosyVoice 300M | **Qwen3-TTS 1.7B**（本机首选，可控情绪）<br>VoxCPM2 官方版（48kHz / 整句更快）<br>IndexTTS2（24G+ 才值得） | 4.9-6.3 GB | Qwen3-TTS 的 instruct 可同时控音色+情绪 |
| ASR | SenseVoice-Small | **SenseVoice-Small**（不变） | CPU, 0 VRAM | 保持；它自带情感标签，见 §4.3 |
| 语音情感 | emotion2vec_base | **SenseVoice 情感标签**（首选）<br>emotion2vec_base（需 7 类细粒度时保留） | CPU, 0 VRAM | 省掉一个独立模型依赖 |
| 声纹 | Resemblyzer | **Resemblyzer**（不变） | CPU, 0 VRAM | 保持 |

> 显存列均为**驻留显存**（不是磁盘体积）。两者差别见 §0.5 第 ①② 条。

### 0.3 三个"变"的依据

**① 为什么 Qwen3.5-9B 比 Qwen3-8B 值**

Qwen3.5 系列（2026-03 发布）是当前 16 GB 显存下**唯一同时满足"中文强 + 参数够 + 装得下"**的选项：

| 基准 | Qwen3.5-9B | 对照 |
|------|-----------|------|
| GPQA Diamond | 81.7 | 超过 gpt-oss-120B |
| MMLU | ~75 | Llama3.1-8B 68 |
| MMLU-Pro | ~45 | — |
| HumanEval | ~72 | — |
| GSM8K / MATH | ~80 / ~48 | — |
| IFEval | ~75 | — |
| 原生上下文 | 256K | Llama3.1 的 2× |
| 多模态 | 原生（图像同一 latent space，无需 vision adapter） | 基座是纯文本 |

Qwen3.5 采用混合线性 + 全注意力架构，权重膨胀比 Qwen3 更省，所以 9B 的 Q4 只比 8B 多 2 GB。

**② 为什么提取器是 2B 而不是 1.7B / 4B**

- 1.7B → 2B 只多 0.4 GB（在 2B 与 4B 之间是最优性价比点）
- 4B 的 importance 评分精度提升有限，但显存 +0.7 GB，且语音峰值时可能挤掉 TTS
- **关键前提**：提取器是**冷路径**（每 5 轮才跑一次），给它单独设 `keep_alive`，语音交互时它已自动卸载（详见 §1.3 与 [[service-lifecycle.md]]）

**③ 为什么 TTS 要换**

2026 年新出的 Qwen3-TTS / IndexTTS2 / VoxCPM2 已经不在 CosyVoice 同一水平线：

> "2026年Qwen3-TTS、IndexTTS2这些新模型出来之后，CosyVoice在情绪控制、中文停顿自然度、长文本稳定性这几个维度上已经不在同一水平线上了。如果是从零开始选，花时间专门去折腾CosyVoice性价比不高。"

本项目是**情绪陪伴**场景，恰好最看重情绪控制 —— 这正是 IndexTTS2 的强项。

> ⚠️ **2026-10-24 复核后的修订**：本机首选改为 **Qwen3-TTS 1.7B**，其次 **VoxCPM2 官方 PyTorch 版** —— 见 §0.5 与 §4.1。
> 原因：① IndexTTS2 FP16 占 4-8 GB，加上桌面常驻的 ~4 GB 会直接 OOM；② 本机实测发现 **llama.cpp-omni 移植版中文严重退化不可用**；③ 官方版实测可用，但 **Qwen3-TTS 是唯一能同时控音色+情绪的**（陪伴场景关键），且显存省 1.4 GB。
> **若将来升到 24 GB 卡，IndexTTS2 的情绪/音色解耦才重新值得优先**。

### 0.4 什么情况下不要升级

| 情况 | 建议 |
|------|------|
| 显存只有 8 GB | 保持 `qwen3.5:4b-q4_K_M` 主对话 + `qwen3.5:0.8b-q4_K_M` 提取器 |
| 目标机器还没到 | **不用现在改任何配置**，本文档只是决策记录 |
| 已有稳定对话历史、模型已调好 | 不必为了 benchmark 换，见 §6.5 的 bake-off 方法论 |

### 0.5 2026-10-24 目标机实测复核（4 处偏差修正）

> 在目标机上（RTX 5060 Ti 16G / i5-14600KF / 32 GB DDR5-6000）实测了 Ollama 上真实的标签体积与显存占用，**主选型结论不变**，但账目有 4 处偏差。

**① 9B Q4_K_M 的显存被低估约 1 GB**

`qwen3.5:9b-q4_K_M` 的**磁盘体积是 6.6 GB，但驻留显存约 7.6 GB**（Ollama 库页面写的 "6.6GB - 7.6GB" 第二个数是显存占用）。本文档旧版按 6.6 GB 记入显存账。

**② `qwen3.5:2b` 的默认标签是 Q8_0，不是 Q4_K_M**

| 标签 | 量化 | 磁盘 | 驻留显存 |
|------|------|------|------|
| `qwen3.5:2b`（**默认**） | Q8_0 | 2.7 GB | ~3.1 GB |
| `qwen3.5:2b-q4_K_M` | Q4_K_M | **1.9 GB** | ~2.3 GB |
| `qwen3.5:9b`（默认） | Q4_K_M | 6.6 GB | ~7.6 GB |
| `qwen3.5:9b-q8_0` | Q8_0 | 10 GB | ~11 GB |

配置里写的是显式的 `qwen3.5:2b-q4_K_M`（1.9 GB），实际比文档记的 2.7 GB **更省** —— 但文档的磁盘/显存表按 2.7 GB 记账，两处混记。

**③ 语音峰值上界越过 16 GB 物理显存（最严重）**

按实测数字重算（Qwen3-TTS 4.9 GB），语音峰值是 **~13.4 - 17.4 GB**，上界仍越过 16 GB 物理上限 —— 必然 OOM。旧版"最坏情况仍留约 0.5 GB 余量"不成立。详见 §1.3。

**④ 桌面常驻程序已占约 4 GB 显存**

这台机器的 Chrome / ToDesk / QQLive / wallpaper64 / steamwebhelper / NVIDIA Overlay 常驻占用 **~4 GB 显存**，所以 **Ollama 实际可用显存是 ~12 GB，不是 16 GB**。所有预算都要按 12 GB 算，不能按标称 16 GB。

**另外两条生态事实（影响 TTS 选型）**：

- **Ollama 上没有 TTS 库**：`qwen3-tts` / `index-tts` / `voxcpm` / `fish-speech` / `chatterbox` 在 `ollama.com/library` **均无对应页面**。Ollama v0.40.9 新增的原生语音生成（Phonon）**仅支持 Apple Silicon**，Windows + Blackwell 用不了 → **TTS 必须外挂独立进程**，见 §4.1。
- **Ollama 版本**：实测上游最新为 **v0.40.10（2026-10-23 发布）**，本文档旧版的版本要求已过时，见 §5。

---

## 1. 显存账本（RTX 5060 Ti 16G）

### 1.1 状态 A：完全空闲

| 资源 | 显存 | 备注 |
|------|------|------|
| `ollama.exe` 进程驻留 | ~0.3 GB | 模型已 unload |
| Mem0 + ChromaDB | RAM ~300 MB | 不占显存 |
| AstrBot 守护 | RAM ~100 MB | 不占显存 |
| **显存合计** | **< 0.5 GB** | |

### 1.2 状态 B：纯文字聊天

| 资源 | 显存 |
|------|------|
| Ollama + `qwen3.5:9b-q4_K_M` 权重 | ~7.6 GB |
| KV cache（8K ctx，`KV_CACHE_TYPE=q8_0`） | ~0.4 GB |
| Ollama 进程 + CUDA context | ~0.3 GB |
| 提取器 `qwen3.5:2b-q4_K_M` | ~2.3 GB |
| Windows / 驱动 + 桌面常驻程序 | ~0.5 - 4 GB |
| **合计** | **~11 - 14.6 GB** |

余量 1.4 - 5 GB（取决于开了多少后台程序）。

> ⚠️ 2026-10-24 实测修正（详见 §0.5 ①②④）：9B Q4_K_M 权重按 **7.6 GB** 记（不是磁盘体积 6.6 GB）；提取器 `qwen3.5:2b-q4_K_M` 实际只有 **1.9 GB 磁盘 / 2.3 GB 显存**；最后一行是这台机器的**真实常态** —— 桌面常驻程序（Chrome / ToDesk / QQLive / wallpaper64 / steamwebhelper / NVIDIA Overlay）常驻占 **~4 GB 显存**，干净登录才只有 ~0.5 GB。
>
> **所以 Ollama 实际可用显存是 ~12 GB，不是 16 GB。**

> 对比上一版（Qwen3-8B + 1.7B = ~8.2 GB）：**多约 2.3 GB**。换来的是中文对话质量的明显提升，这是本项目最核心的体验指标，值得。

> 💡 **纯文字模式可以用 `qwen3.5:9b-q8_0`（~11 GB 显存）** —— 后台程序关干净时总占用约 13.7 GB，装得下。Q8 量化对中文生成质量的提升明显，还能实质缓解 §5 坑 3/4 说的重复循环（Ollama 静默忽略 `repeat_penalty`，Q4 下只能靠量化兜底）。代价：与提取器同驻时总量逼近物理上限，**语音模式必须切回 Q4**。两个标签可同时 pull（磁盘共 16.6 GB），靠改 `llm.model` 切换。

### 1.3 状态 C：语音交互峰值（关键改进）

| 资源 | 显存 |
|------|------|
| 主模型 `qwen3.5:9b-q4_K_M`（权重 + KV） | ~8.0 GB |
| 提取器（**已被独立 keep_alive 卸载**） | 0 GB |
| TTS（Qwen3-TTS 1.7B，实测） | **~4.9 GB** |
| SenseVoice-Small | CPU 推理，0 VRAM |
| Windows / 驱动 + 桌面常驻程序 | ~0.5 - 4 GB |
| **合计** | **~13.4 - 17.4 GB** |

❌ **2026-10-24 实测修正**：按本机实测（Qwen3-TTS 4.9 GB），语音峰值是 **13.4 - 17.4 GB**，
上界仍越过 16 GB 物理显存 —— **必然 OOM，除非先降级**（用 VoxCPM2 官方版则是 14.9 - 18.9 GB，更紧）。

**两条可行路线（数据均为本机实测）**：

```
路线 A：关后台程序 + 9B 主模型（极限）
  关掉 Chrome / ToDesk / QQLive / wallpaper64（腾出 ~3 GB）
  + TTS: Qwen3-TTS 1.7B      → 5048 MiB
  + 主模型 qwen3.5:9b-q4_K_M → 8480 MiB
  → 峰值 ≈ 13.5 GB ✅（余量 ~2.8 GB）

路线 B：关后台程序 + 4B 主模型（稳妥）
  + TTS: Qwen3-TTS 1.7B      → 5048 MiB
  + 主模型 qwen3.5:4b-q4_K_M → 4700 MiB
  → 峰值 ≈ 9.7 GB ✅（余量 ~6.6 GB）（代价：文本质量下降）
```

> ⚠️ **16 GB 卡上"9B 主模型 + 本地 TTS 同时常驻"是硬约束**。若还要更大余量，见 §4.1 的三个选项
> （换 Qwen3-TTS 1.7B / 错峰卸载 LLM / 升 24 GB 卡）。

> 若 TTS 换成 **Qwen3-TTS 1.7B**（~2-6 GB），峰值反而降到 ~12-14 GB，延迟也更好（97ms 首包）。但注意它**不在 Ollama 库里**，要单独用 transformers / vLLM-Omni 起服务，见 §4.1。

**改进点**：上一版把提取器标为"常驻"，导致语音峰值时它还占着 1.3 GB。实际上 `keep_alive` 是 **per-model** 的，可以给提取器单独设一个更短的存活时间：

```
主模型    keep_alive = 5m     ← 用户在聊天时保持
提取器    keep_alive = 30s    ← 提取完 30 秒就自己卸载
```

语音交互时提取器早就卸载了，语音峰值**不叠加**提取器显存。

### 1.4 磁盘账本

| 内容 | 占用 |
|------|------|
| `qwen3.5:9b-q4_K_M` | ~6.6 GB |
| `qwen3.5:2b-q4_K_M` | ~1.9 GB |
| `qwen3.5:0.8b-q4_K_M`（降级备选） | ~1.2 GB |
| `qwen3.5:9b-q8_0`（纯文字模式可选） | ~10 GB |
| IndexTTS2 | ~2 - 4 GB |
| VoxCPM2（llama.cpp-omni 推荐路线） | ~3.3 GB（权重）+ AudioVAE 另计 |
| SenseVoice-Small | ~200 MB |
| `text2vec-base-chinese-paraphrase` embedding | ~400 MB |
| AstrBot + Mem0 + ChromaDB | ~500 MB |
| 用户记忆（每月预计） | ~10 - 50 MB |
| **总计** | **~13 - 16 GB**（含 q8_0 约 22 GB） |

SSD 留 50 GB 安全余量。

> ⚠️ 2026-10-24 实测修正：`qwen3.5:2b-q4_K_M` 的磁盘体积是 **1.9 GB**，不是 2.7 GB（旧版把默认标签 `qwen3.5:2b` 的体积当成了 Q4_K_M，而默认标签其实是 Q8_0）。见 §0.5 ②。

### 1.5 降级阶梯（OOM 时按序执行）

| 优先级 | 动作 | 节省 |
|-------|------|------|
| 1 | **关掉后台常驻程序**（Chrome / ToDesk / QQLive / wallpaper64 / steamwebhelper） | **-3 GB** |
| 2 | TTS → **llama.cpp-omni + VoxCPM2 `--n-gpu-layers 8`**（实测 3975 MiB / RTF 0.465） | -3.4 GB |
| 3 | 提取器 → `qwen3.5:0.8b-q4_K_M` | -1.0 GB |
| 4 | 主模型 → `qwen3.5:4b-q4_K_M` | -3.6 GB |
| 5 | 提取器 → 主对话自提取 | -2.3 GB |
| 6 | `OLLAMA_CONTEXT_LENGTH` → 4096 | -0.2 GB |
| 7 | IndexTTS2 半精度 / 降低采样步数 | -2 ~ 4 GB |

> 优先级 1 是 2026-10-24 新增的（实测发现桌面常驻占 ~4 GB 显存，见 §0.5 ④）—— **零成本、收益最大**，先做这个再考虑动模型。
> 优先级 2 取代了旧版的 CosyVoice2 / Spark-TTS：VoxCPM2 中文 CER 0.97% 更好，且 llama.cpp-omni 是单二进制、无 Python 依赖，部署最省事。⚠️ 其驻留显存是**估算值**，部署后用 `nvidia-smi` 实测校正；官方只给了 PyTorch 实现的 ~8 GB（RTX 4090）。

---

## 2. 基础模型候选（2026-10 调研）

### 2.1 装得下 16 GB 的

| 模型 | 参数量 | 架构 | Q4 磁盘 / 显存 | 中文 | 适配度 |
|------|--------|------|---------|------|--------|
| **Qwen3.5-9B** | 9.7B | dense | 6.6 / **7.6 GB** | 强 | ★★★★★ **主对话首选** |
| Qwen3.5-4B | 4B | dense | 3.3 / 4.0 GB | 强 | ★★★★☆ 提取器 / 低配主模型 |
| Qwen3.5-2B | 2B | dense | **1.9** / 2.3 GB | 强 | ★★★★☆ 提取器首选 |
| Qwen3.5-0.8B | 0.8B | dense | 1.2 / 1.3 GB | 中 | ★★★☆☆ 超低配 |
| gpt-oss 20B | 21B (4 active) | MoE 32 专家 | 14 GB | 弱 | ⚠️ 中文弱，显存紧 |
| Gemma 4 12B | 12B | dense | 7.7 / 8.0 GB | 中 | ★★☆☆☆ 英文强，中文一般 |
| Gemma 4 26B-A4B | 26B (4 active) | MoE | 16 - 19 GB | 中 | ⚠️ 勉强，中文一般 |
| LFM2.5-8B-A1B | 8.5B (1B active) | MoE | 9.5 GB | 未知 | ★★☆☆☆ 新架构，生态不熟 |

> 2026-10-24 实测复核（Ollama 真实标签体积）：Qwen3.5-4B / 2B / 0.8B 分别对应 `qwen3.5:4b-q4_K_M` / `qwen3.5:2b-q4_K_M` / `qwen3.5:0.8b-q4_K_M`。**注意 `qwen3.5:2b` 默认标签是 Q8_0（磁盘 2.7 GB），不是 Q4_K_M** —— 要显式写 `:q4_K_M` 才拿到 1.9 GB。
> `-mlx` / `-nvfp4` / `-mxfp8` 标签都是 macOS (MLX) 专用，**Windows + CUDA 用不了**，Windows 上可选的只有 `q4_K_M` / `q8_0` / `bf16`。

### 2.2 装不下 16 GB 的（24 GB+ 才有意义）

| 模型 | 参数量 | Q4 磁盘 / 显存 | 中文 | 备注 |
|------|--------|---------|------|------|
| Qwen3.6-27B | 27B | 18 / 19 GB | 强 | 16G 卡装不下，纯 CPU 或部分卸载会很慢 |
| Qwen3.6-35B | 35B (MoE) | 23 / 24 GB | 强 | 24G 卡的甜点，Ollama 标签 `qwen3.6:35b` |
| Qwen3.8-27B | 27B | 18 GB | 强 | dense，24G 勉强，Ollama 标签 `qwen3.8:27b` |
| Qwen3.5-35B | 35B (MoE) | 22 GB | 强 | EQ-v5 微调版基座，见 §3.3 |
| GLM-4.7-Flash | 30B (3B active) | 19 GB | 强 | ❌ 16G 装不下 |
| gpt-oss 120B | 120B | 65 GB | 弱 | ❌ |

> ⚠️ 2026-10-24 实测复核：Ollama 上**没有** `qwen3.6:35b-a3b` / `qwen3.5:35b-a3b` 这类标签 —— 真实标签是 `qwen3.6:35b`、`qwen3.6:27b`、`qwen3.8:27b`、`qwen3.5:35b`，且 **Qwen3.6 / Qwen3.8 的最小尺寸都是 27B（18 GB 起），16 GB 卡一律装不下**。这从供给侧确认了 Qwen3.5-9B 在本机上的不可替代性。

### 2.3 Qwen3.5 vs 上一代 Qwen3

| 维度 | Qwen3-8B | Qwen3.5-9B |
|------|----------|-----------|
| 中文理解 | 优秀 | **更强** |
| 情商 / 共情 | 良好 | **明显提升** |
| 指令遵循 | 优秀 | 更稳定 |
| 原生上下文 | 32K | **256K** |
| 多模态 | 需 vision adapter | **原生** |
| 思考模式 | 可选 | 可选（**Ollama 默认强制开，必须显式关**，见 §5） |
| Q4 显存 | ~4.5 GB | **~7.6 GB** |
| Ollama 生态 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐（生态仍薄，坑见 §5） |

### 2.4 换代的两个代价

1. **Ollama 生态比 Qwen3 薄** —— Qwen3.5 有 5 个已知坑，必须按 §5 配好，否则会出现"每句话慢 30 秒"这类症状
2. **显存多 2.3 GB** —— 可接受，但换 TTS 时要一起算账

---

## 3. 微调 / 特调模型专表

> 2026-10-22 补充调研。以下按"与本项目的相关度"排序。

### 3.1 ★★★★★ 最贴合：中文情感陪伴 / 人格陪伴

| 模型 | 基座 | 规模 | 语言 | 许可 | 核心特点 | 适配度 |
|------|------|------|------|------|---------|--------|
| **Pingo SFT (Qwen3.5-4B LoRA v6)**<br>`spvjig/pingo-qwen3.5-4b-lora-v6` | Qwen3.5-4B | 4B | **中文** | Apache 2.0 | 用**真实产品脱敏对话**做 QLoRA SFT；**双模式**：保真模式（人设卡+世界观+护栏全在 system prompt）/ **烘焙模式（人设、世界观、护栏全部训进权重，推理只需薄 system）**；护栏拒答样本 ~8%；支持 OpenAI 兼容 tool_calls | ★★★★★ **直接命中我们的"多人格系统"** |
| **WSAI-Heart-Pro**<br>`wangshenai/WSAI-Heart-Pro` | Qwen3.5-2B-Base | 2B (~4.2 GB) | **中文** | **CC BY-NC-SA 4.0** | 全精度 LoRA，16 层训练，约 5 天；心理支持对话 / 情感陪伴 / 情绪疏导；保留基座 VLM 能力；作者是中学生，预算极低 | ★★★★★ **最贴合"情感陪伴"语义** |
| **lianren-4b**<br>`weitusi/lianren-4b` | Qwen3.5-4B | 4B | **中文** | Apache 2.0 | **纯权重手术，不训练不微调**：往第 15 层注意力输出投影的 bias 注入一个情绪向量，逐 token 无条件叠进残差流 —— 换任何 system prompt、换任何话题它都在；6GB 3060 实测；作者自述"不需要冷静克制的助手场景" | ★★★★ **方法论价值极高**（见 §3.6） |
| **TARS**<br>`bochen2079/tars-qwen3.5-9b` | Qwen3.5-9B | 9B | 英文 | Apache 2.0 | QLoRA → SFT → DPO；768 条 SFT + 98 对偏好对；**人格参数在 system prompt 里运行时可调**（幽默度 60% vs 100% 有可观测的语域偏移）；**保留 70/30 的 system/no-system 混合训练**；DPO 失败可退化为 SFT-only | ★★★★★ **我们的"可切换人格"应该照这个思路做** |

**WSAI-Heart 家族对照**（同一作者的三个版本，可看出"训练充分度"的影响）：

| 版本 | 基座 | LoRA 层数 | 训练时长 | 作者结论 |
|------|------|-----------|---------|---------|
| WSAI-Heart | Qwen3.5-0.8B | 2 层 | 855 轮，纯 CPU，4-5 天 | LoRA 只训 2 层 → Loss 偏高、拟合不足、**泛化能力受限** |
| WSAI-Heart-Pro-Exp | Qwen3.5-2B-Base | 16 层 | 约 5 天 | 覆盖面大幅提升 |
| **WSAI-Heart-Pro** | Qwen3.5-2B-Base | 16 层 | 约 5 天 | 超参调优后稳定版 |

> **可迁移的教训**：LoRA 训练层数（覆盖深度）对效果的影响 ≫ 数据量。2 层 LoRA = 基本学不到东西。

### 3.2 ★★★☆☆ 角色扮演向

| 模型 | 基座 | 规模 | 语言 | 许可 | 特点 |
|------|------|------|------|------|------|
| **Silicon-Based-Girlfriend**<br>`RX5950XT` | Qwen3.5-4B | 4B (~4.2 GB Q8) | **繁中** | — | QLoRA r=32，985 条 ShareGPT 样本，`qwen3_5_nothink` 模板；台湾用语；含 NSFW 内容 |
| **Kurken-9B-Summer-Merged**<br>`AnSungJae3489` | Qwen3.5-9B 架构 | 9B | 日 / 英 | Apache 2.0 | 专精角色声音与对话风；7,700 条对话场景 (~844K tokens，**人类编剧写的**非 LLM 生成）；消费级 24GB 卡 1.2 小时训完（峰值 12.8GB），总预算 ~$61；QLoRA r=32, ~58M 参数 |
| **MiniFantasy / MiniFantasy-MTP**<br>`Nubinu`/`MuXodious` | Qwen3.5-4B | 4.5B | 英文 | — | LoRA r=16；多轮叙事节奏 + 情感共鸣；SillyTavern 角色卡格式 |
| **Sally-9B-GGUF**<br>`Juicesyo` | Qwen3.5-9B-Base | 9B | **中文** | Apache 2.0 | 中文角色扮演；Q4_K_M 5.63 GB；内容含成人向 |
| **nightmedia/Qwen3.5-9B-Holodeck-Lounge** | Qwen3.5-9B | 9B | 中 / 英 | Apache 2.0 | mergekit 合并十余个专化模型（agentic / coding / creative writing）；主打**多人格模拟** + 思考开关 |
| **kev-love-0.8b**<br>`xunshenwu` | Qwen3.5-0.8B-Base | 0.8B | 中文 | — | 恋爱军师向；RTX 5060 8GB 上训 1178 步 |

### 3.3 ★★★★☆ 质量最高但装不下：EQ / 反谄媚

| 模型 | 基座 | 规模 | 方法 | 结果 |
|------|------|------|------|------|
| **Qwen3.5-35B-A3B-EQ-v5**<br>`nivvis` | Qwen3.5-35B-A3B → heretic-v2 | 35B (3B active) | DPO + LoRA r=32 | **专治谄媚 / 过度顺从**；EQ-Bench 3 得分 **193.6** ≈ gemini-2.5-pro(193.7) > claude-opus-4(192.6)；定位"不谄媚地共情""温暖地设边界""听起来像人" |

> ❌ 21 GB Q4，16G 装不下。但**如果将来升级到 24 GB 机器，这是陪伴质量的天花板**。
> 它解决的问题正是陪伴机器人最常见的失败模式：什么都顺着她说。

### 3.4 ★★★☆☆ 特殊技术路线（方法论参考）

| 路线 | 模型 | 做法 | 意义 |
|------|------|------|------|
| **Split-FFN Slerp** | `h34v7/Qwen3.5-4B-Furry-RP-V1`、`Qwen3.5-9B-Furry-RP-Preview` | 先训 4B（FFN 中间维扩展 9216→9344），再把学到的 `down_proj` **球面线性插值**迁移到 9B 的 FFN（12288→12416），最后 500 步 NF4+LoRA 抛光 | **绕开 LoRA 的秩瓶颈**：只训 25M 参数就能注入领域知识；单张 4090 **2.5 小时**搞定（普通 LoRA 要 30+ 小时） |
| **权重手术** | `lianren-4b` | 往一层 bias 写一个向量 | 不训练、不微调，秒级完成情绪注入。**最适合快速试验"情绪偏置"** |
| **条件化人格（replay 数据）** | 某 yandere 对话 LoRA 研究 | 2,470 样本把 OOC 代词滑出率从 26% 降到 0%；混入基座 replay 数据 | 防止微调后人格**漂移**的经典做法 |
| **GRPO > SFT** | `InfoxmedModel/Qwen3.5-4B-chinesedoctor-grpo` | 用「评测同款 rubric grader」当奖励 + KL 锚定 base(β=0.04) | 5 个评测集 4 升 1 平，而 SFT 反而全线掉分 —— **当"评分不准"时，GRPO 比 SFT 更有效** |

### 3.5 ★★☆☆☆ 领域特调（与本项目无关，但说明生态活跃度）

| 模型 | 领域 | 方法 |
|------|------|------|
| `ShenRen1231/Qwen3.5-4B-DeepSeek-v4-Flash` | 推理增强 | CoT 蒸馏；LoRA r=160；MMLU-Pro 81.9% vs base 79.1% |
| `SingWahAI/Qwen3.5-0.8B-AIOPS` | 运维问答 | LoRA r=16，608 条样本，合并发布 |
| `DJLougen/hermes-qwen3.5-35b-a3b-GGUF` | Function Calling | Unsloth + TRL SFT，ChatML 模板 |
| `TuringEvo/Qwen3.5-2B-wz-lora` | 王者荣耀图文 | LoRA r=8，Swift 框架 |

### 3.6 "决策模型"（Decision Models）—— 2026-10 新类别

| 模型 | 提供方 | 许可 | 特点 |
|------|--------|------|------|
| **Cloudflare Clef / Clef-flash** | Cloudflare | Apache 2.0 | 返回**选择 / 概率 / 分数**，而不是文本 |
| **AWS Strands Decider 2B** | AWS | — | 同上，2B |

**对本项目的潜在用途**：替代 `ShouldRespondGate`（该不该回应）与情绪分类的规则实现。

**当前决策：不引入。** 理由：
- 规则版已经够用，且**零额外依赖**（多一个模型就多一份显存和延迟风险）
- 但如果未来出现"规则很难表达的判断"（比如"这句话该不该接"），这是最省事的解法，值得记在进阶清单里

### 3.7 微调模型到底要不要用？

**结论分三层**：

| 场景 | 决策 |
|------|------|
| **Phase 1-4（部署期）** | **不用**。先用 `qwen3.5:9b` 基座 + 好 prompt。微调模型是**增强**，不是替代 |
| **Phase 4-5（打磨期）** | **评估** WSAI-Heart-Pro / Pingo SFT 作为对照，看基座差在哪 |
| **Phase 5+（个性化期）** | **自己微调**。用 §6.5 的 bake-off 流程，训一个自己的陪伴 LoRA |

**为什么不建议直接用现成微调模型**（这是上一版文档的判断，现在依然成立）：

- 数据集小（几百到几万条），容易过拟合
- 风格单一，锁死成某个角色 —— **和我们要做的"可切换多人格"直接冲突**
- 通用能力退化
- 大量角色扮演模型擦边（NSFW 倾向）
- 没有系统化评测，自称 SOTA 的都不可信

**但 2026 年的新信息改变了两点**：

1. **Pingo SFT 的"烘焙模式"证明"把人格训进权重"是可行的** —— 我们的多人格系统可以照这个思路，为每个 persona 训一份 adapter，推理时按需加载
2. **TARS 证明"运行时可调人格"是可行的** —— 人格参数放在 system prompt 里训练，模型学会"服从这些旋钮"，这比烘焙更适合我们的多 persona 切换

**许可证注意**：WSAI-Heart 系列是 **CC BY-NC-SA 4.0**（非商业），自用没问题，但**不能用于任何商业场景**。Pingo SFT / TARS / lianren-4b / Kurken 是 Apache 2.0。

---

## 4. 语音栈选型（2026-10 调研）

### 4.1 TTS

| 模型 | 规模 | 显存 | 首包延迟 | 中文 WER/CER | 情感相似度 | 许可 | 适合本项目 |
|------|------|------|-----------|-------------|-----------|------|-----------|
| **VoxCPM2 官方版** | 2B | **5.7 GB**（实测） | — | **CER 0.97%** | SIM 85.4% | Apache-2.0 | ★★★★★ **本机首选**：RTF ~2.2（快 2 倍）、48 kHz、括号描述有效 |
| **Qwen3-TTS 1.7B**（VoiceDesign） | 1.7B | 6.3 GB（实测） | 官方称 97ms¹ | — | — | **Apache-2.0** | ★★★★☆ **instruct 语义更明确**（情绪控制），但慢一倍、24 kHz |
| **VoxCPM2（官方 PyTorch）** | 2B | **6.3 GB**（实测） | — | **CER 0.97%** | SIM 85.4% | Apache-2.0 | ★★★★☆ 采样率 48kHz + 整句 RTF 更低 |
| IndexTTS2 | — | ~4-8 GB | — | WER 2.12% | **0.872** | — | ★★★★☆ **情绪/音色解耦**（24G+ 才值得） |
| CosyVoice2-0.5B | 0.5B | ~4 GB | 150 ms | WER 2.43% | 0.831 | — | ★★★ 降级备选 |
| Spark-TTS 0.5B | 0.5B | ~1-2 GB | — | WER 2.87% | — | — | ★★★ 最轻 |
| F5-TTS 0.3B | 0.3B | ~3 GB | — | — | — | MIT | ★★ 安装最简 |
| Kokoro-82M | 82M | <2 GB | — | — | — | — | ★★ 最小 footprint |
| ~~CosyVoice 300M~~ | 0.3B | ~1.2 GB | — | — | — | — | ❌ **已落后，建议换** |
| ~~VoxCPM2（llama.cpp-omni）~~ | 2B | 7.4 GB | — | CER 0.97% | SIM 85.4% | Apache-2.0 | ❌ **中文严重退化，见下** |

> ¹ Qwen3-TTS 官方称 97ms 首包（Dual-Track 流式架构），但 **Python 包的 `generate_*` 不暴露逐块输出**（`non_streaming_mode` 参数改的是输入 embedding 构造，不是输出流式）。要用真流式得上 vLLM-Omni 的 `/v1/audio/speech`。

#### 本机实测对比（RTX 5060 Ti 16G，2026-10-24）

| 指标 | **Qwen3-TTS 1.7B** | **VoxCPM2 官方版** | 胜 |
|------|-------------------|-------------------|-----|
| 显存（单条生成） | **4.32 - 4.93 GB** | 6.30 GB | Qwen3-TTS（省 1.4 GB）|
| 显存（batch 3 条） | 6.41 GB | 未测 | — |
| RTF（单条稳态） | 3.64 - 3.71 | **1.77 - 1.78** | VoxCPM2（快 1 倍）|
| RTF（按句切分 + batch） | **0.67 - 2.55**（见下表）| 未测 | Qwen3-TTS |
| 输出采样率 | 24 kHz | **48 kHz** | VoxCPM2 |
| 音色控制 | `instruct` 指令 | 括号描述 `(描述)文本` | 都可以 |
| **情绪控制** | ✅ **同一音色可换情绪**（实测 4 种） | ❌ 无 | **Qwen3-TTS** |
| 响度均匀性 | 好（峰值差 3 dB）| 差（峰值差 16 dB）| Qwen3-TTS |
| 内容质量（ASR 逐句校验）| 94-100% | 94-100% | 平 |
| 权重 | 4.3 GB + tokenizer 651 MB | 4.7 GB | 平 |
| 许可 | Apache-2.0 | Apache-2.0 | 平 |

**Qwen3-TTS 的 batch 权衡**（278 字 / 11 句文本，本机实测）：

| `--batch-size` | 批数 | 显存峰值 | RTF | 适用 |
|---|---|---|---|---|
| 1（不切分） | 1 | 4.32 - 4.93 GB | 3.64 | 单句即时响应（首包快但吞吐慢）|
| 2 | 6 | 4.86 GB | 2.548 | 折中 |
| **4** | **3** | **5.49 GB** | **1.640** | ✅ **推荐**：与 9B 主模型共存仍有余量 |
| 6 | 2 | 6.00 GB | 1.288 | 显存紧张时不选 |
| 11（全批）| 1 | 7.88 GB | **0.672** | 最快，但显存吃掉太多 |

> ⚠️ **batch 越大首包越晚**：batch=11 虽然 RTF 0.672（比实时快），但要等 11 句全部生成完才出声。
> **陪伴场景的取舍**：对话式陪伴是"用户说一段 → 机器人回一段"，攒批可接受 → 选 **batch=4**（RTF 1.64、显存 5.49 GB）；
> 若做逐句应答式交互，选 batch=1/2 换首包延迟。
> ⚠️ **batch=6 及以上与 9B 主模型共存会 OOM**（6.00 + 8.5 GB = 14.5 GB，加桌面常驻 4.4 GB 远超 16 GB）。

**Qwen3-TTS 的情绪控制实测**：同一段文本 + 同一音色描述，只改 instruct 的情绪部分，生成 4 段音频（warm / angry / cheer / sad），时长 4.40-5.12 s 明显不同，**ASR 转写内容 100% 一致** —— 说明它只改说话方式，不改内容。

**VoxCPM2 的括号描述同样有效**（2026-10-25 实测，同一句"你今天过得怎么样？我有点担心你。"）：

| 描述 | 时长 | 语速 | 基频中位 | RMS |
|------|------|------|---------|-----|
| 中性（无描述）| 2.72 s | 5.9 字/秒 | 105.7 Hz | 0.1719 |
| 温柔关心 | 4.48 s | **3.6 字/秒** | 285.4 Hz | **0.0596** |
| 愤怒激动 | 2.56 s | **6.2 字/秒** | 242.8 Hz | **0.1526** |

语速与强度都跟着描述变（温柔更慢更轻，愤怒更快更响）→ **括号描述能表达情绪**，不只是音色。

> ⚠️ **两个 TTS 引擎不能同时加载模型**：VoxCPM2 ~5.7GB + Qwen3-TTS ~6.3GB + 桌面 ~4.4GB > 16GB，会 OOM。
> 两个 provider 都注册好（`voxcpm2_local` / `qwen3_tts_local`），按需在面板里切换当前用哪个，
> 切换时用 `companionctl.bat stop tts` / `start vcpm` 停/起对应的服务。

> 💡 **这对本项目特别重要**：情绪状态机（`emotion.py`）输出的 `emotion_hints` 可以直接映射到 Qwen3-TTS 的 `instruct`（"温柔关切，语速放慢一点" → `instruct="...语气充满关切，语速放慢"`），
> 而 VoxCPM2 只能控制音色、无法控制情绪。

**按句切分的实现**：`D:\dev\qwen_tts_cli.py --split --batch-size N --emit-dir <目录>`
—— 句内并行成批、批间流水；`--emit-dir` 会把每批单独写成 wav，播放端可按批号顺序增量消费。
实测每个 chunk 的内容都完整正确（逐 chunk ASR 校验）。

> ⚠️ **2026-10-24 实测复核（重要）**：
> - **Ollama 上没有 TTS 库**：`qwen3-tts` / `index-tts` / `voxcpm` / `fish-speech` / `chatterbox` 在 `ollama.com/library` 均无对应页面；Ollama v0.40.9 新增的原生语音生成（Phonon）**仅支持 Apple Silicon**，Windows + Blackwell 用不了 → **TTS 必须外挂独立进程**。
> - **llama.cpp-omni 移植版不可用**：虽然部署成功、显存/RTF 都不差，但**中文生成严重退化**——幻觉循环（"1...2...3...4..."）、提前 EOS、句子念不全。同一段 42 字文本，ASR 转写结果是 `What?`（相似度 0%），而官方 PyTorch 版逐字正确（相似度 97-100%）。
>   **注意：幻觉 TTS 的时长/语速/峰值指标与正常 TTS 完全一致**，只看时长会误判 —— 必须用 ASR 校验（见 [[deployment.md]] §5.0）。

> ⚠️ **2026-10-24 实测复核（重要）**：
> - **Ollama 上没有 TTS 库**：`qwen3-tts` / `index-tts` / `voxcpm` / `fish-speech` / `chatterbox` 在 `ollama.com/library` 均无对应页面；Ollama v0.40.9 新增的原生语音生成（Phonon）**仅支持 Apple Silicon**，Windows + Blackwell 用不了 → **TTS 必须外挂独立进程**。
> - **llama.cpp-omni 移植版不可用**：虽然部署成功、显存/RTF 都不差，但**中文生成严重退化**——幻觉循环（"1...2...3...4..."）、提前 EOS、句子念不全。同一段 42 字文本，ASR 转写结果是 `What?`（相似度 0%），而官方 PyTorch 版逐字正确（相似度 97-100%）。
>   **注意：幻觉 TTS 的时长/语速/峰值指标与正常 TTS 完全一致**，只看时长会误判 —— 必须用 ASR 校验（见 [[deployment.md]] §5.0）。
>
> 这一点直接决定了 TTS 选型的优先级：**部署形态越简单越好** —— 这就是本机把 VoxCPM2 排在 IndexTTS2 之前的原因。

**为什么本机首选 Qwen3-TTS 1.7B**（见下面的对比表）：

- **唯一能同时控制音色 + 情绪的本地 TTS** —— 陪伴场景的核心差异化。`instruct` 可直接接收情绪状态机的 `emotion_hints`
- **显存最省**：4.3-4.9 GB（比 VoxCPM2 省 1.4 GB），对 16 GB 卡至关重要
- **内容正确**：2026-10-24 用 ASR 转写逐句校验，三个 persona 样音相似度 **94% / 97% / 100%**，情绪样音 4 段内容 100% 一致
- **Apache-2.0**，可商用
- **代价**：单条 RTF 3.64（比 VoxCPM2 慢一倍）；输出 24 kHz；Python 包不暴露真流式

**VoxCPM2（官方 PyTorch 版）的相对优势**：采样率 48 kHz、整句 RTF 1.77（快一倍）、中文 CER 0.97%。
适合"音质/采样率优先"的场景，作为备选保留。

> ⚠️ **实测数据（RTX 5060 Ti 16G，本机）**：
> | 指标 | 值 |
> |------|-----|
> | 显存（torch `max_memory_allocated`） | **6.22 - 6.30 GB** |
> | RTF（稳态，第 2/3 次生成） | **1.77 - 1.78**（首轮 2.02，含预热） |
> | RTF（纯 CPU） | 12.0 - 13.2 |
> | 输出 | 48 kHz 单声道 |
> | 权重 | `model.safetensors` 4.3 GB + `audiovae.pth` 360 MB |
>
> ⚠️ **RTF 1.77 是比实时慢** —— 官方标注 RTX 4090 上约 0.3，本机慢约 6 倍（显卡差距 + Windows）。流式管线下首字延迟可接受，但不适合"整句合成完再播"。
> ⚠️ **输出响度不均匀**：三次生成的峰值差 16 dBFS（-17.1 / -6.1 / -0.9）。官方 API 的 `normalize=True` 是**文本**规范化（数字/符号转可读文本），**不做响度处理** —— 必须另做响度归一化（`D:\dev\normalize-wav.py`）。

#### ❌ 对照：llama.cpp-omni 移植版（本机已装，但不可用）

> 保留这份数据是因为它**看起来很美**——显存和 RTF 都比官方版好，但内容是垃圾。这正是"必须用 ASR 校验"的由来。

| 模式 | 显存增量 | RTF | ASR 内容校验 |
|------|---------|-----|------------|
| 全 GPU（`--n-gpu-layers 99`） | 7418 MiB | 0.267 | ❌ 42 字文本转写出 `What?`（相似度 0%） |
| `--n-gpu-layers 8` | 3975 MiB | 0.465 | ❌ 幻觉循环 `1...2...3...4...` |
| `--cpu` | 2676 MiB | 4.839 | ❌ AudioVAE 跑 CPU，RTF 恶化 18 倍 |

**结论**：移植版**不要用**。已装的 CUDA Toolkit 与 ggml-cuda bug 修复仍可复用，但 TTS 走官方 PyTorch。

**本机显存可行组合**（16311 MiB 总量 − 桌面 4396 MiB = 可用 ~11915 MiB）：

```
语音模式（LLM + TTS 同时驻留）
  TTS:  VoxCPM2 官方版            → 6430 MiB
  LLM:  qwen3.5:9b-q4_K_M        → 8480 MiB (权重 7770 + KV 410 + ollama 300)
  合计                            → 14910 MiB  ❌ 超 11915 约 3 GB
  → 必须关掉 Chrome / ToDesk / QQLive（腾 ~3 GB）→ ✅ 极限

纯文字模式（无 TTS）
  LLM:  qwen3.5:9b-q4_K_M        → 8480 MiB  ✅ 余量 ~3.4 GB

若语音模式还要更大余量：主模型降到 qwen3.5:4b-q4_K_M（~4700 MiB）
  TTS 6430 + LLM 4700 + 桌面 4396 = 15526 MiB  ✅（余量 ~785 MiB，仍紧）
```

> ⚠️ **16 GB 卡上"9B 主模型 + 本地 TTS 同时常驻"是硬约束**。若余量不够，可考虑：
> ① 换 **Qwen3-TTS 1.7B**（~2-6 GB，且 97ms 首包）
> ② 错峰：LLM 用 Ollama `keep_alive` 控制，语音合成时让 LLM 临时卸载（代价是每轮重载 ~8 秒）
> ③ 升到 24 GB 卡 → 可上 IndexTTS2 的情绪/音色解耦

**官方地址（已核实）**：

| 组件 | 地址 | 许可 |
|------|------|------|
| VoxCPM 官方仓库 | https://github.com/OpenBMB/VoxCPM | Apache-2.0 |
| llama.cpp-omni 推理引擎 | https://github.com/tc-mb/llama.cpp-omni | MIT |
| GGUF 权重 | https://huggingface.co/DennisHuang648/VoxCPM2-GGUF | Apache-2.0 |
| vLLM-Omni（生产部署） | https://github.com/vllm-project/vllm-omni | — |

> ⚠️ **Blackwell 构建门槛**：RTX 5060 Ti 是 compute capability 12.0 (sm_120)，llama.cpp 的 CUDA 后端**需要 CUDA Toolkit 12.8+**，否则要么编译失败（`Unsupported gpu architecture 'compute_120'`），要么静默回退到 CPU。编译时建议显式指定 `-DCMAKE_CUDA_ARCHITECTURES=120`。详见 [[deployment.md]]。

**为什么 IndexTTS2 仍值得作为第二选择**：

- **情绪与音色解耦**：可以给不同 persona 配不同音色，同时让所有 persona 共用一套情绪控制
- **8 维情感向量**：可以由上游情绪状态机（`caring` / `playful` / `tired`）直接驱动 —— 我们的情绪状态机输出的 `prompt_style` 可以直接映射成情感向量
- `use_emo_text` 用**微调过的 Qwen3** 从文本推断情绪，省一个额外模型
- ⚠️ 但它 FP16 占 4-8 GB，本机**必须半精度 + 降采样步数**，且要先关后台程序，否则 OOM（§1.3）

**为什么 Qwen3-TTS 是延迟最优解**：97 ms 首包，且支持用自然语言描述来调情绪（"温柔地""带点委屈地说"），对流式管线最友好。**如果我们的首字延迟压不住，先换它。**

### 4.2 ASR

| 模型 | 规模 | CER | 备注 |
|------|------|-----|------|
| **SenseVoice-Small** | 234M (226 MB) | ~3.5% | **自带情感 + 事件检测**；中英粤日韩；RTF 0.10 ✅ |
| FireRedASR2-LLM | 8.3B | 2.89% | 精度王者，需 GPU ❌ 装不下 |
| FireRedASR2-AED | 1.1B | 3.05% | 性价比最优，需 GPU |
| Qwen3-ASR-1.7B | 1.7B | 3.76% | 22 种方言，支持流式 |
| Fun-ASR-Nano | 800M | ~4.5% | 端侧成熟 |
| Whisper-Large-v3 | 1.55B | ~5% | 99 语种 |

**中文流式结论**：Paraformer 中文效果最佳（原生流式），SenseVoice 噪声鲁棒更强。

**本项目决策**：
- **流式输入** → Paraformer（`streaming.asr_provider: paraformer`，已配置）
- **最终转写 / 情感标签** → SenseVoice-Small（已配置）
- 两者可共存，SenseVoice 跑在 CPU，0 VRAM

### 4.3 语音情感的两种来源

| 方案 | 类别数 | 额外依赖 | 显存 | 评价 |
|------|-------|---------|------|------|
| **SenseVoice-Small 自带** | 粗（`<|HAPPY|>` / `<|SAD|>` / `<|ANGRY|>` 等） | 无 | 0 | ✅ **首选**，省一个模型 |
| emotion2vec_base | 7 类（angry/happy/neutral/sad/surprised/fear/disgust） | 有 | 0（CPU） | 需要细粒度时保留 |

**决策**：默认走 SenseVoice 自带情感标签；只有在验收测试发现分类粒度不够（例如无法区分"惊讶"与"害怕"）时，才启用 emotion2vec。两者不冲突，配置里留开关。

---

## 5. Ollama × Qwen3.5 踩坑清单（必读）

> 这五个坑不知道，会遇到"每句话慢 30 秒""对话重复""显存莫名爆"等症状。

### 坑 1：Ollama 对 Qwen3.5 **默认强制开 thinking**

- **症状**：每条回复多出 800+ 隐形 token，延迟从 2 秒变 30-60 秒
- **解法优先级**：
  1. Modelfile 里 `PARAMETER think false`（最稳）
  2. API 请求**顶层** `"think": false` —— ⚠️ **不是** `options.think`，那是错的
- **本项目已修正**：provider 配置里 `ollama_disable_thinking: true`（AstrBot 转成 `reasoning_effort=none` → Ollama 转成 `think=false`）
- 实际配置文件是部署机上的 `D:\dev\AstrBot\data\cmd_config.json`（不在本仓库）

### 坑 2：Ollama 按显存自动选 `num_ctx`

- **症状**：上下文莫名其妙只有 4K，机器人"忘了"刚说过的话
- **原因**：显存 < 24 GiB 时 Ollama 默认 `num_ctx=4096`
- **解法**：显式设置 `OLLAMA_CONTEXT_LENGTH=8192`（已配置）

### 坑 3：Ollama 对 Qwen3.5 **静默忽略** `repeat_penalty` / `frequency_penalty` / `presence_penalty`

- **解法**：不要指望用这些参数抑制重复。改用 `PARAMETER repeat_penalty 1.0` 走 Modelfile

### 坑 4：默认 `repeat_penalty=1.1` **损害 Qwen3.5 质量**

- **解法**：显式设 `repeat_penalty: 1.0`（**Qwen3 与 Qwen3.5 全系适用**）

### 坑 5：KV cache 显存翻倍

- **解法**：设 `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0`
- **效果**：8K 上下文的 KV 从 ~0.7 GB 降到 ~0.4 GB

### 版本要求

| Ollama 版本 | 要求 | 原因 |
|------------|------|------|
| ≥ v0.17.5 | 必须 | 修 Qwen3.5 GPU/CPU 分割崩溃与重复循环 bug |
| ≥ v0.31.2 | 推荐 | 多模态稳定性 |
| **v0.40.10**（2026-10-23 发布） | **本机直接装这个** | 上游当前最新版 |

> **2026-10-24 复核**：上游最新版是 **v0.40.10**，旧版写的"≥v0.31.2"已过时，装最新的即可。
> GPU 兼容性也已核对：Ollama 官方硬件支持列表里 **compute capability 12.0 = GeForce RTX 50xx（含 RTX 5060 Ti）**，要求驱动 ≥ 550 —— 本机驱动 610.88 / CUDA 13.3 ✅
> v0.40.9 新增的原生语音生成（Phonon）**仅支持 Apple Silicon**，本机用不到（见 §4.1）。

### 安全

> ⚠️ **Ollama 没有鉴权**。已发现公网上 17.5 万个裸奔实例。
> **切勿绑定 `0.0.0.0` 暴露公网。** 只监听 `127.0.0.1`。

---

## 6. 保留的原有论证

### 6.1 为什么 B（双模型）优于 A（单模型）：核心是**并发**

多任务一个模型有个隐藏代价：**单模型在同一时刻只能跑一件事**。

```
场景：用户在聊天时，机器人后台触发记忆提取。

A 方案（一个模型，NUM_PARALLEL=1）
  T+0s   用户发消息
  T+0s   主模型开始生成
  T+3s   生成完成（回复渲染）
  T+3s   触发记忆提取
  T+3s   主模型开始提取
  T+6s   提取完成
  → 用户下一条消息会撞上正在进行的提取 → 再次排队

B 方案（两个模型，各自独占 VRAM）
  T+0s   用户发消息
  T+0s   主模型开始生成   ┐ 同时进行
  T+3s   生成完成         │ 提取器触发 → 提取（2 秒）
  T+3s   用户看到回复     ┘ 提取完成
  → 用户下一条消息无需等待
```

**B 方案的"感知延迟"减半**，对陪伴机器人这种"必须感觉像活的"产品是关键。

### 6.2 方案账本（针对 RTX 5060 Ti 16G）

| 方案 | VRAM 峰值 | 提取延迟 | 并发 | 复杂度 | 语音栈兼容 |
|------|----------|---------|------|-------|-----------|
| A：只用 `qwen3.5:9b-q4_K_M` | ~8.3 GB | 3-6 秒 | ❌ 串行 | ⭐ 最简单 | ✅ |
| **B：`qwen3.5:9b` + `2b`**（**当前推荐**） | ~11 - 14.6 GB | 1-2 秒 | ✅ 真并行 | ⭐⭐ 中等 | ⚠️ 需先降级（§1.3） |
| C：`qwen3.5:4b-q4_K_M` 主 + `2b` 提取（低配版） | ~7.4 - 10.9 GB | 1-2 秒 | ✅ | ⭐⭐ | ✅ 更宽松 |
| D：`qwen3.6:35b` + `2b`（24G+ 升级） | ~26 GB | 1-2 秒 | ✅ | ⭐⭐ | ❌ 16G 装不下 |

> 数字为**机器人自身占用**，未含桌面常驻的 ~0.5 - 4 GB（§0.5 ④）。

### 6.3 什么时候该选 A

| 场景 | 为什么 |
|------|--------|
| 显存 ≤ 8 GB | 物理上装不下两个模型 |
| 提取频率极低 | 串行无影响 |
| 想要绝对简单 | 一个模型、一行配置 |
| 边缘设备 | 少一个组件少一份风险 |

```bash
# config/mem0.env.example
LLM_MODEL=qwen3.5:9b-q4_K_M   # 提取器与主对话共享
```

```yaml
# D:\dev\AstrBot\data\cmd_config.json（实际生效的配置）
summary_model: qwen3.5:9b-q4_K_M
```

架构不动，只是把提取器换成主模型自己提取自己，代价是提取期间聊天会排队。

### 6.4 升级路径

```powershell
# A → B
ollama pull qwen3.5:2b-q4_K_M
# 改 mem0.env: LLM_MODEL=qwen3.5:2b-q4_K_M
# 改 cmd_config.json: summary_model: qwen3.5:2b-q4_K_M

# B → C（显存不够时降级）
ollama pull qwen3.5:4b-q4_K_M
# 改 cmd_config.json: provider[].model: qwen3.5:4b-q4_K_M

# B → B'（纯文字模式换 Q8_0，质量更好；语音模式切回 B）
ollama pull qwen3.5:9b-q8_0
# 改 cmd_config.json: provider[].model: qwen3.5:9b-q8_0
```

> ⚠️ 标签别写错：`qwen3.5:2b` 的默认标签是 **Q8_0**，要省显存必须显式写 `qwen3.5:2b-q4_K_M`（1.9 GB）。
> `qwen3.6:35b-a3b` / `qwen3.5:35b-a3b` **不是合法标签**，真实标签是 `qwen3.6:35b` / `qwen3.5:35b`。

升级是**可逆的、向后兼容的**，随时可以切回。

### 6.5 微调 bake-off 方法论（Phase 5 用）

> 来源：Vincent Qiao（2026-09）总结的社区实践。

```
Day 1  选 2-3 个候选模型
       ↓
Day 1-2 建 50-100 条真实对话 eval 集
       覆盖：闲聊 / 情绪 / 情节推进 / 敏感边界
       ↓
Day 2-3 对每个候选跑同样的 LoRA-SFT
       ↓
Day 3  比对四个维度：
       ① 人格一致性（多轮后是否还是同一个人）
       ② 多轮漂移（第 10 轮 vs 第 1 轮的差异）
       ③ 拒答率（该拒的拒了吗，不该拒的拒了吗）
       ④ 延迟
       ↓
       选赢家，再投入数据管线
```

**关键点**：不要一开始就做全量训练。先用同一套 eval 集做小规模对比，成本可控。

### 6.6 选 LoRA 的判据

| 判据 | 说明 |
|------|------|
| 下载量 > 1k | 多人试过，至少没大问题 |
| 点赞数高 | 社区认可 |
| 作者有详细 README + 评测 | 不是随便丢个文件就跑 |
| 训练数据集有说明 | 数据来源透明 |
| **不是 NSFW 专属** | 你要的是陪伴 |
| **基座与你的主模型匹配** | ⚠️ LoRA 必须与基座严格一致 |
| **许可证允许你的用途** | CC BY-NC-SA 只能非商用 |

### 6.7 找微调模型的地方

| 平台 | URL | 适用 |
|------|-----|------|
| **ModelScope 魔搭** | modelscope.cn | **中文首选**，本项目相关的微调模型大多在这里 |
| HuggingFace | huggingface.co/models | 国际通用 |
| WiseModel | wisemodel.cn | 中文 LoRA |

**搜索关键词（2026-10 更新）**：

```
Qwen3.5 情感陪伴 LoRA
Qwen3.5 中文 roleplay LoRA
Qwen3.5 心理支持 微调
Qwen3.5 人格 persona SFT
Qwen3.5 EQ 去谄媚 DPO
```

> 旧关键词 `Qwen2.5 14B roleplay LoRA` 已过时（基座对不上）。

### 6.8 部署微调模型

```yaml
# D:\dev\AstrBot\data\cmd_config.json（实际生效的配置）
provider:
  - id: ollama_local_9b
    type: openai_chat_completion
    model: my-companion   # ← 换成你创建的 Ollama 模型名
```

```bash
# 创建带 LoRA 的 Ollama 模型
cat > Modelfile <<EOF
FROM qwen3.5:9b-q4_K_M
ADAPTER /path/to/your-lora.bin
PARAMETER think false
PARAMETER repeat_penalty 1.0
PARAMETER num_ctx 8192
EOF
ollama create my-companion -f Modelfile
```

**架构完全不动**，只换模型名。

---

## 7. 常见误区澄清

| 误区 | 真相 |
|------|------|
| "一个模型做所有事更'一致'" | 同系列模型共享词表和 tokenizer，一致性风险极低 |
| "小模型提取会漏关键信息" | 提取是受限任务（对话 → 结构化事实），对'理解力'要求不高 |
| "省一个模型省一半事" | 配置差异很小，磁盘差 2.7 GB 可忽略 |
| "两个模型一定更慢" | 两个**并发**比一个**串行两次**快 2 倍 |
| "显存永远要省着用" | 16G 留 5 GB 余量已足够；过度压缩牺牲体验 |
| "参数越大陪伴越好" | 陪伴质量更多取决于**人设 prompt + 情绪状态机 + 记忆**，不只参数量 |
| "必须用现成微调模型做陪伴" | 基座 + 好 prompt 在中文情感对话已领先；微调是**增强**不是替代 |
| "基座更新后要重新调所有 prompt" | 先做 bake-off（§6.5）量化差异再决定，不要凭感觉推翻 |

---

## 8. 决策时间线

```
Phase 0（2026-01 设计）  C：14B + 7B → 理论最优，17GB 装不下
       ↓ 验证硬件约束
Phase 0.5               B：14B + 3B → 仍偏大
       ↓ 显存纪律
Phase 0.6               B：8B + 1.7B → 落地配置
       ↓
Phase 0.7（2026-10 调研）B：Qwen3.5-9B + Qwen3.5-2B → 当前推荐
                        TTS：CosyVoice → IndexTTS2 / Qwen3-TTS
                        新增 §3 微调/特调模型专表
       ↓
Phase 0.8（2026-10-24 实测复核）主选型不变（Qwen3.5-9B 仍是本机唯一可行解）
                        修正 4 处偏差：9B 显存 7.6GB / 2B 默认是 Q8_0 /
                        语音峰值上界 ~20GB（必须先降级）/ 桌面常驻占 4GB
                        TTS 首选改为 llama.cpp-omni + VoxCPM2
                        见 §0.5
       ↓
Phase 1+（部署）  先用基座 + 好 prompt 跑通
       ↓
Phase 4（打磨）  bake-off 对比基座 vs WSAI-Heart-Pro vs Pingo SFT
       ↓
Phase 5+（个性化）自己训 LoRA（多人格 adapter 库）
       ↓
持续优化      按季度复核模型生态
```

---

## 9. 复核清单

> 开源生态半年一变（Qwen3 → Qwen3.5 → Qwen3.6/3.8 就是半年内的事）。**每季度按这份清单复核一次**：

- [x] Ollama 是否已支持最新 Qwen 系列，有无新踩坑 —— 2026-10-24 复核：支持，v0.40.10；`qwen3.5` / `qwen3.6` / `qwen3.8` 均在库，§5 五个坑仍然成立
- [ ] 有无新的中文情感陪伴微调模型发布（ModelScope / HF）
- [x] TTS 是否有比 IndexTTS2 更好的情绪控制方案 —— 2026-10-24 复核并实测：**Qwen3-TTS 1.7B** 的 `instruct` 可同时控音色+情绪（实测 4 种情绪，内容 100% 一致），显存 4.3-4.9GB，升为本机首选；VoxCPM2 官方版（48kHz / RTF 1.77）备选；llama.cpp-omni 移植版**中文退化不可用**。见 §4.1
- [ ] ASR 有无更低 CER 的轻量模型
- [x] 是否出现值得引入的"决策模型"场景 —— 2026-10-24：Ollama v0.40.9 已集成 vLLM Semantic Router 的 **d3** 决策模型（2B/4B/9B/27B），可作为 §3.6 的进阶选项，仍维持"暂不引入"
- [ ] 目标硬件有无变化（24 GB → 可考虑 `qwen3.6:35b` / EQ-v5）
