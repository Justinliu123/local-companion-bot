# 显存与硬件账本

> 目标硬件：**NVIDIA RTX 5060 Ti 16G** —— **2026-10-24 实测确认：这台机器就是目标机**
>
> 实测配置：i5-14600KF（14C/20T，无核显）/ 32 GB DDR5-6000（双通道）/ RTX 5060 Ti 16 GB（compute 12.0，驱动 610.88）/ C: 322 GB + D: 874 GB 空闲
>
> 配置版本：2026-10 换代（Qwen3.5-9B + Qwen3.5-2B + **Qwen3-TTS 1.7B / VoxCPM2**）
> 语音模式实测主模型用 **Qwen3.5-4B**（9B 留给纯文字），见 [[local-stack.md]]
> 选型依据见 [[model-strategy.md]]。

## ⚠️ 先读这一条：实际可用显存是 ~12 GB，不是 16 GB

这台机器的桌面程序**常驻占用约 4 GB 显存**（Chrome / ToDesk / QQLive / wallpaper64 / steamwebhelper / NVIDIA Overlay 实测）。

所以下面账本里"Windows / 驱动开销"这一行要按 **0.5 - 4 GB** 看（干净登录 ~0.5 GB，日常开着后台 ~4 GB）。

> **所有预算按 12 GB 算，不要按标称 16 GB 算。**
> 另外因为 14600KF 无核显、显示输出由 5060 Ti 驱动，桌面上下文常驻，**GPU 无法完全释放给游戏** —— 停掉机器人后显存归零是不现实的，实际会留 ~0.5 - 4 GB。

## 三种运行状态

### 状态 A：完全空闲（自动进入）

| 占用的资源 | 显存 | 备注 |
|---|---|---|
| `ollama.exe` 进程驻留 | ~0.3 GB | 模型已 unload |
| Mem0 + ChromaDB | RAM ~300 MB | 不占显存 |
| AstrBot 守护 | RAM ~100 MB | 不占显存 |
| **机器人自身合计** | **< 0.5 GB** | |

> 💡 这是「用完一段时间后」的自然状态，不影响你玩游戏或干别的。

---

### 状态 B：纯文字聊天（最常用）

| 占用的资源 | 显存 |
|---|---|
| Ollama + `qwen3.5:9b-q4_K_M` 模型权重 | ~7.6 GB |
| KV cache（8K 上下文，`KV_CACHE_TYPE=q8_0`） | ~0.4 GB |
| Ollama 进程 + CUDA context | ~0.3 GB |
| Mem0 提取器 `qwen3.5:2b-q4_K_M` | ~2.3 GB |
| Windows / 驱动 + 桌面常驻程序 | ~0.5 - 4 GB |
| **合计** | **~11 - 14.6 GB** |

余量 1.4 - 5 GB（取决于后台程序多少）。

> ⚠️ **2026-10-24 实测修正**：
> ① 9B Q4_K_M 权重是**磁盘 6.6 GB / 显存 ~7.6 GB**（Ollama 库页面的 "6.6GB - 7.6GB" 第二个数是显存），旧版按 6.6 GB 记显存，低估约 1 GB。
> ② `qwen3.5:2b-q4_K_M` 磁盘只有 **1.9 GB**（显存 ~2.3 GB）；旧版记的 2.7 GB 是**默认标签 `qwen3.5:2b` 的体积，而默认标签其实是 Q8_0**。
> ③ 桌面常驻程序本身就占 ~4 GB（见文首），所以实际余量比旧版写的"5.5 GB 绰绰有余"少得多。

> **版本演进**：14B Q4 + 7B Q8 → 14B Q4 + 3B Q4 → 8B Q4 + 1.7B Q4（2026-01）→ **9B Q4 + 2B Q4（2026-10，当前）**
>
> 本次换代多占 2.3 GB，换来的是中文对话质量的明显提升（Qwen3.5-9B 的 GPQA 81.7 / MMLU ~75 / 原生 256K 上下文）。
> 提取器升到 2B 是因为 JSON 与 importance 评分比 1.7B 稳，而它仍是冷路径。

---

### 状态 C：语音交互峰值

| 占用的资源 | 显存 |
|---|---|
| 主模型 `qwen3.5:9b-q4_K_M`（权重 + KV） | ~8.0 GB |
| 提取器 `qwen3.5:2b-q4_K_M`（**已自动卸载**） | 0 GB |
| TTS（Qwen3-TTS 1.7B，实测 ~4.9 GB / VoxCPM2 官方版 ~6.3 GB） | **~4.9 - 6.3 GB** |
| SenseVoice-Small | CPU 推理，0 VRAM |
| Windows / 驱动 + 桌面常驻程序 | ~0.5 - 4 GB |
| **合计** | **~13.4 - 17.4 GB** |

❌ **2026-10-24 实测修正**：旧版写的"在 16G 之内，最坏情况仍留约 0.5 GB 余量"是错的。按实测数字重算（Qwen3-TTS 4.9 GB），语音峰值是 **13.4 - 17.4 GB**，上界仍越过 16 GB 物理显存。（若用 VoxCPM2 官方版，峰值是 14.9 - 18.9 GB，更紧。）

**语音模式必须先降级**，两条路线（**数据均为本机实测**）：

```
路线 A：关后台程序 + 9B 主模型（极限）
  关掉 Chrome / ToDesk / QQLive / wallpaper64（腾出 ~3 GB）
  + TTS: Qwen3-TTS 1.7B      → 5048 MiB
  + 主模型 qwen3.5:9b-q4_K_M → 8480 MiB
  → 峰值 ≈ 13.5 GB ✅ 余量 ~2.8 GB

路线 B：关后台程序 + 4B 主模型（稳妥）
  + TTS: Qwen3-TTS 1.7B      → 5048 MiB
  + 主模型 qwen3.5:4b-q4_K_M → 4700 MiB
  → 峰值 ≈ 9.7 GB ✅ 余量 ~6.6 GB（代价：文本质量下降）
```

> ⚠️ **16 GB 卡上"9B 主模型 + 本地 TTS 同时常驻"是硬约束**。若还要更大余量，见 [[model-strategy.md]] §4.1 的三个选项（换 Qwen3-TTS 1.7B / 错峰卸载 LLM / 升 24 GB 卡）。
> ⚠️ 若 TTS 换成 **Qwen3-TTS 1.7B**（~2-6 GB），峰值反而降到 ~12-14 GB，延迟也更好（97ms 首包）。但注意它**不在 Ollama 库里**（`ollama.com/library/qwen3-tts` 无此页），要单独用 transformers / vLLM-Omni 起服务。

**关键改进**：上一版把提取器标为「常驻」，导致语音峰值时它还占着 1.3 GB。实际上 `keep_alive` 是 **per-model** 的：

```
主模型    keep_alive = 5m     ← 用户在聊天时保持
提取器    keep_alive = 30s    ← 提取完 30 秒就自己卸载
```

提取器每 5 轮才跑一次，是**冷路径**。语音交互开始时它早就卸载了，**语音峰值不叠加提取器显存**。

⚠️ **不要**在状态 C 同时跑任何额外的模型（本机可用显存本就只有 ~12 GB，开任何额外模型都可能挤掉 TTS 推理）。

---

## 显存紧张时的降级策略

如果 `nvidia-smi` 显示 OOM，按以下顺序降级：

| 优先级 | 降级动作 | 节省显存 |
|---|---|---|
| 1 | **关掉后台常驻程序**（Chrome / ToDesk / QQLive / wallpaper64 / steamwebhelper） | **-3 GB** |
| 2 | TTS → 换更轻的引擎（Qwen3-TTS 1.7B ~2-6 GB） | -2 ~ 4 GB |
| 3 | 提取器 → `qwen3.5:0.8b-q4_K_M` | -1.0 GB |
| 4 | 主模型 → `qwen3.5:4b-q4_K_M` | -3.6 GB |
| 5 | 提取器 → 让主对话自己提取 | -2.3 GB |
| 6 | `OLLAMA_CONTEXT_LENGTH` → 4096 | -0.2 GB |
| 7 | TTS 降 batch_size（4 → 2 → 1）/ 改用更轻的引擎 | -1 ~ 2 GB |

> 优先级 1 是 2026-10-24 新增的（实测桌面常驻占 ~4 GB 显存）—— **零成本、收益最大**，先做这个再考虑动模型。
> 优先级 2 取代了旧版的 CosyVoice2 / Spark-TTS：VoxCPM2 中文 CER 0.97% 更好，且 llama.cpp-omni 是单二进制、无 Python 依赖，部署最省事。

> **升级路径**（显存允许时）：主模型 → `qwen3.6:35b`（~23-24 GB）或 `qwen3.5:35b`（EQ-v5 陪伴质量最高）。⚠️ 注意标签名 —— Ollama 上**没有** `qwen3.6:35b-a3b` / `qwen3.5:35b-a3b` 这类标签，真实标签是 `qwen3.6:35b` / `qwen3.5:35b`；且 Qwen3.6 / Qwen3.8 的最小尺寸都是 27B（18 GB 起）。详见 [[model-strategy.md]]。
> **降级路径**：若 Qwen3.5 拉取失败，回退到 `qwen3:8b-instruct-q4_K_M`（显存少 2 GB，能力略低）。

## 内存账本

| 组件 | 内存占用 |
|---|---|
| Ollama 进程 | ~200 MB |
| Mem0 Python 服务 | ~100 MB |
| ChromaDB | ~150 MB |
| AstrBot | ~80 MB |
| ASR (sensevoice) | ~250 MB（仅加载时） |
| TTS（VoxCPM2 / Qwen3-TTS，独立进程） | ~1 - 2 GB（仅加载时） |
| **常驻合计** | **~530 MB** |
| **全栈加载** | **~2.5 - 3.5 GB** |

32 GB 内存完全够用 —— 但**当前已有 ~5-6 GB 被后台程序占用**（v2rayN 1.5 GB / QQLive 838 MB / Chrome 744 MB / ToDesk 323 MB 等），空闲约 15 GB。全栈加载 ~3.5 GB，余量仍然充裕。唯一要留意的是同时开模拟器 + 浏览器 + 机器人的极端情况。

## 磁盘账本

| 内容 | 占用 |
|---|---|
| `qwen3.5:9b-q4_K_M` | ~6.6 GB |
| `qwen3.5:2b-q4_K_M` | **~1.9 GB** |
| `qwen3.5:9b-q8_0`（纯文字模式可选） | ~10 GB |
| Qwen3-TTS 1.7B-VoiceDesign | ~4.3 GB + Tokenizer 651 MB |
| VoxCPM2（官方 PyTorch 版） | ~4.7 GB（model.safetensors 4.3 + audiovae.pth 0.36） |
| SenseVoice-Small | ~200 MB |
| `text2vec-base-chinese-paraphrase` embedding | ~400 MB |
| AstrBot + Mem0 + ChromaDB | ~500 MB |
| 用户记忆（每月预计） | ~10 - 50 MB |
| **总计** | **~13 - 16 GB**（同时 pull q8_0 约 22 GB） |

推荐 SSD 留 50 GB 安全余量。本机 C: 322 GB / D: 874 GB 空闲，无压力。

> ⚠️ 2026-10-24 实测修正：`qwen3.5:2b-q4_K_M` 磁盘是 **1.9 GB**（旧版记的 2.7 GB 是默认标签 `qwen3.5:2b` 的体积，而默认标签其实是 Q8_0）。

## 功耗参考

- 5060 Ti 16G TDP = 180W
- 纯文字聊天稳态：~120-140W
- 语音峰值：~160-180W（短时）
- 完全空闲：< 20W（GPU 基本降频）

## 监控建议

部署完成后，建议安装一个简单的显存看门狗：

```bash
# 可选：使用 GPU-Z 或 MSI Afterburner 桌面小部件观察
# 命令行实时监控：
nvidia-smi --query-gpu=memory.used,memory.free,temperature.gpu --loop=5
```

把这个写入 AstrBot 启动脚本的尾部，需要时能贴在控制台确认状态。

```bash
# 确认当前哪些模型还驻留在显存里
ollama ps
```
