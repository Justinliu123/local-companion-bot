# 部署指南（目标机器）

> ⚠️ 本指南对应**目标机器**，不是当前开发机。
> 当前开发阶段请参考 [../plans/roadmap.md](../plans/roadmap.md) Phase 1-3。

## 0. 前置检查

### 0.1 硬件确认

```powershell
# 确认显卡识别
nvidia-smi
# 应能看到 RTX 5060 Ti (16G)，驱动版本 ≥ 560
```

### 0.2 系统要求

- Windows 11 22H2 或更新
- PowerShell 5.1+（系统自带）
- 管理员权限（用于注册服务）
- **执行策略**允许运行本地脚本：
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
  ```

## 1. 基础环境

### 1.1 Python 3.11+

```powershell
winget install Python.Python.3.11
python --version  # 应输出 3.11.x 或更高
```

### 1.2 Ollama

```powershell
winget install Ollama.Ollama
ollama --version
```

**版本要求**：

| 版本 | 要求 | 原因 |
|------|------|------|
| ≥ v0.17.5 | **必须** | 修 Qwen3.5 的 GPU/CPU 分割崩溃与重复循环 bug |
| ≥ v0.31.2 | 推荐 | 多模态稳定性 |

### 1.3 配置 Ollama 环境变量

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "5m", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "127.0.0.1:11434", "User")

# ⚠️ Qwen3.5 必设：KV cache 量化 + Flash Attention（否则 KV 显存翻倍）
[Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", "q8_0", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")

# ⚠️ 必须显式设：显存 < 24 GiB 时 Ollama 默认 num_ctx 只有 4096
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH", "8192", "User")

# 重启 PowerShell 让环境变量生效
```

> ⚠️ **不要**把 `OLLAMA_HOST` 改成 `0.0.0.0`。Ollama **没有任何鉴权**，公网上已有 17.5 万个裸奔实例。

### 1.4 拉取模型

**默认配置（Qwen3.5-9B 主对话 + Qwen3.5-2B 提取器）：**

```powershell
# 主对话模型（Qwen3.5-9B Q4_K_M，5060 Ti 16G 推荐配置）
ollama pull qwen3.5:9b-q4_K_M

# 记忆/摘要提取器（冷路径，每 5 轮跑一次，会自行卸载）
ollama pull qwen3.5:2b-q4_K_M

# 验证
ollama list
```

**可选：拉取候选模型做对比测试：**

```powershell
# 低配版主对话（显存不够时）
ollama pull qwen3.5:4b-q4_K_M

# 超低配提取器
ollama pull qwen3.5:0.8b-q4_K_M

# 上一代 Qwen3（对照，能力略低但显存更省）
ollama pull qwen3:8b-instruct-q4_K_M
```

详见 [[model-strategy.md]] §2。

> ⚠️ **如果 Ollama 上找不到 `qwen3.5:9b-q4_K_M`**，请：
> 1. 执行 `ollama search qwen3.5` 查看可用 tags（不同版本 tag 命名可能不同）
> 2. 或降级到 `qwen3.5:4b-q4_K_M`
> 3. 再不行降级到 `qwen3:8b-instruct-q4_K_M`（上一代，能力略低）

### 1.5 Git（克隆本项目到目标机器）

```powershell
winget install Git.Git
cd E:\Documents\
git clone <your-repo-url> local-companion-bot
cd local-companion-bot
```

## 2. 安装依赖

### 2.1 Python 虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -r requirements.txt  # 待生成
```

### 2.2 下载语音模型（可选）

> ⚠️ **2026-10-24 实测结论：VoxCPM2 必须用官方 PyTorch 实现，不要用 llama.cpp-omni 移植版。**
>
> llama.cpp-omni 版已在本机部署完成并跑通（`D:\dev\llama.cpp-omni`），但**中文严重退化**：
> 大量幻觉循环（"1...2...3...4..."、"阿伊比阿伊比..."）、提前 EOS、句子念不全。
> 用 ASR 转写验证：同一段 42 字文本，移植版的转写是 `What?`（相似度 0%），
> 而官方 PyTorch 版是逐字正确（相似度 97-100%）。
> **注意**：幻觉 TTS 的时长/语速指标与正常 TTS 完全一致，只看时长会误判 —— 必须用 ASR 校验。
>
> 可疑根因（未定位到具体哪一处）：GGUF 里 `minicpm4.embedding_scale = 0.` / `residual_scale = 0.`；
> `voxcpm2_runtime.cpp` 里没有 voice-design 括号解析；上游仓库仅 309 stars。
>
> 官方实现的 Voice Design 用的**也是括号语法**（`build_final_text()` → `f"({control}){text}"`），
> 所以括号语法本身没错，是移植版没生效。

#### 方案 A（推荐）：Qwen3-TTS 1.7B —— 唯一能控情绪的本地 TTS

> **为什么是它**：陪伴场景的核心差异化是**情绪**。Qwen3-TTS 的 `instruct` 同时控制音色**和情绪**，
> 而 VoxCPM2 只能控制音色。情绪状态机的 `emotion_hints` 可直接映射到 `instruct`。
> 实测：同一段文本 + 同一音色，只改 instruct 的情绪部分，生成 4 段音频（warm/angry/cheer/sad），
> 时长 4.40-5.12 s 明显不同，**ASR 转写内容 100% 一致** —— 只改说话方式，不改内容。

```bash
# 1) 环境（与 VoxCPM2 共用同一个 Python 3.12 venv）
#    ⚠️ qwen-tts 0.1.1 要求 transformers==4.57.3（精确版本）
uv pip install --python D:/dev/voxcpm-py/Scripts/python.exe \
  "transformers==4.57.3" "accelerate==1.12.0" sox onnxruntime \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
uv pip install --python D:/dev/voxcpm-py/Scripts/python.exe qwen-tts --no-deps

# 2) 权重（ModelScope 国内直连很快）
pip install modelscope
modelscope download --model Qwen/Qwen3-TTS-Tokenizer-12Hz --local_dir ./Qwen3-TTS-Tokenizer-12Hz
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign --local_dir ./Qwen3-TTS-12Hz-1.7B-VoiceDesign

# 3) 生成
python D:/dev/qwen_tts_cli.py "你好呀，我是小忆。" -o out.wav \
  --instruct "一位温柔的年轻女性，声音轻柔舒缓，语气充满关心。"

# 4) 长文本：按句切分 + batch 并行（推荐）
#    --emit-dir 让每批单独写成 wav，播放端按 batch 号顺序增量消费
python D:/dev/qwen_tts_cli.py "很长的文本..." -o out.wav \
  --instruct "一位温柔的年轻女性，语气充满关心。" \
  --split --batch-size 4 --emit-dir ./chunks/
```

**为什么按句切分 + batch**：Qwen3-TTS 单条 RTF ~3.64（比实时慢），但 **batch 并行能把 RTF 压下来**
（本机实测 278 字 / 11 句）：

| `--batch-size` | 批数 | 显存峰值 | RTF | 说明 |
|---|---|---|---|---|
| 1 | 1 | 4.32 - 4.93 GB | 3.64 | 单句即时，首包快但吞吐慢 |
| 2 | 6 | 4.86 GB | 2.548 | 折中 |
| **4** | **3** | **5.49 GB** | **1.640** | ✅ **推荐**：与 9B 主模型共存仍有余量 |
| 6 | 2 | 6.00 GB | 1.288 | 显存紧张时不选 |
| 11 | 1 | 7.88 GB | **0.672** | 最快，但显存吃掉太多 |

> ⚠️ **batch 越大首包越晚**：batch=11 虽然 RTF 0.672，但要等 11 句全生成完才出声。
> 对话式陪伴是"用户说一段 → 机器人回一段"，攒批可接受 → 选 **batch=4**。
> ⚠️ **batch ≥ 6 与 9B 主模型共存会 OOM**（6.00 + 8.5 GB，加桌面常驻 4.4 GB 远超 16 GB）。
>
> 实测每个 chunk 内容完整正确（逐 chunk ASR 校验）。

**⚠️ 版本冲突陷阱**：装 qwen-tts 依赖时 uv 会把 CUDA 版 torch 换回 PyPI 的 CPU 版
（PyPI 的 torch 默认就是 CPU 版）。**每次装完包都要重装 CUDA torch 并加 `--no-deps`**：

```bash
# torch CUDA wheel：阿里镜像的 index 不符 PEP503（uv 解析不到），
# 但网页能直接下；用 12 个并行 range 请求可从 1.5 MB/s 提到几十 MB/s
curl -L -o torch.whl "https://mirrors.aliyun.com/pytorch-wheels/cu128/torch-2.9.1%2Bcu128-cp312-cp312-win_amd64.whl"
uv pip install --python D:/dev/voxcpm-py/Scripts/python.exe --no-deps --reinstall ./torch.whl
```

**⚠️ 流式的真相**：官方宣称 97ms 首包（Dual-Track 流式架构），但 **Python 包的
`generate_*` 不暴露逐块输出** —— `non_streaming_mode` 参数改的是**输入 embedding 构造**
（text-first vs codec-first），不是输出流式。实测两种模式 RTF 相同（3.65 vs 3.66）。
**要真流式得上 vLLM-Omni 的 `/v1/audio/speech`。**

**API 参考**（`qwen_tts` 包）：

| 方法 | 模型 | 参数 |
|------|------|------|
| `generate_voice_design(text, language, instruct)` | VoiceDesign | 用 `instruct` 描述音色+情绪 |
| `generate_custom_voice(text, language, speaker, instruct)` | CustomVoice | 9 种预设音色（Vivian / Serena / Uncle_Fu …）|
| `generate_voice_clone(text, language, ref_audio, ref_text)` | Base | 3 秒快速克隆 |

#### 方案 B：VoxCPM2 官方 PyTorch 版（采样率高、整句 RTF 更低）

<details>
<summary>展开：VoxCPM2 官方版（采样率 48kHz、整句 RTF 1.77、显存 6.3GB）</summary>

```bash
# 1) Python 3.12 隔离环境（系统 Python 3.14 装不了 torch）
uv venv --python 3.12 D:/dev/voxcpm-py

# 2) torch（CUDA 版）
#    ⚠️ download.pytorch.org 直连很慢；阿里云镜像的 index 不符合 PEP503，
#       uv 解析不到包（"torch was not found in the package registry"），
#       但网页里能直接下 wheel —— 手动下完再本地安装：
curl -L -o torch-2.9.1+cu128-cp312-cp312-win_amd64.whl \
  "https://mirrors.aliyun.com/pytorch-wheels/cu128/torch-2.9.1%2Bcu128-cp312-cp312-win_amd64.whl"
uv pip install --python D:/dev/voxcpm-py/Scripts/python.exe ./torch-2.9.1+cu128-cp312-cp312-win_amd64.whl

# 3) 官方包与依赖（PyPI 走清华源很快）
uv pip install --python D:/dev/voxcpm-py/Scripts/python.exe voxcpm \
  numpy soundfile librosa einops transformers huggingface-hub \
  inflect addict wetext sortedcontainers simplejson argbind safetensors pydantic \
  datasets matplotlib --index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 4) 权重（ModelScope 国内直连很快）
pip install modelscope
python -c "
from modelscope import snapshot_download
snapshot_download('OpenBMB/VoxCPM2', local_dir='D:/dev/models/VoxCPM2-official')"
#    → model.safetensors 4.3GB + audiovae.pth 360MB
```

**生成脚本** `D:\dev\voxcpm_tts.py`：

```bash
# 纯 TTS
python D:/dev/voxcpm_tts.py "你好呀，我是小忆。今天过得怎么样？" -o out.wav

# Voice Design（音色描述用括号，官方实现同此语法）
python D:/dev/voxcpm_tts.py "你好呀" -o out.wav --voice "(一位温柔的年轻女性，声音轻柔舒缓)"

# 声音克隆（reference_wav_path，独立 ref_audio token，结构隔离）
python D:/dev/voxcpm_tts.py "你好呀" -o out.wav --ref ref.wav

# 长文本按句分段（流式管线用；见下）
python D:/dev/voxcpm_tts.py "很长的文本..." -o out.wav --voice "(...)" --split
```

**长文本的两种做法**（2026-10-24 实测）：

| 做法 | 278 字结果 | 说明 |
|------|-----------|------|
| 单次生成 | 54.7s，语速 5.08 字/秒，**内容完整** | 正常。官方版的 EOS 判定基本可靠 |
| `--split` 按句分段 | 51.8s，内容完整 | 段间加 120ms 静音；音色描述只放第一段以保证一致 |

> ⚠️ **重要**：曾一度以为官方版"长文本会截断"——那是 whisper 在长音频末尾漏识别造成的**误判**，单独转写最后 4 秒证明内容完整。
> 但 `--split` 仍有价值：**流式管线本来就是按句送 TTS**，分段能天然对齐流式输出，并让每段都可独立质检。

**响度必须另做归一化**：官方 API 的 `normalize=True` 是**文本**规范化（数字/符号转可读文本），**不做响度处理**。实测三次生成的峰值差 16 dBFS（-17.1 / -6.1 / -0.9）。用 `D:\dev\normalize-wav.py` 统一到 RMS -20 / peak -1 dBFS。

</details>

#### 方案 C（不推荐）：llama.cpp-omni 移植版

<details>
<summary>展开：已在本机部署完成，但中文不可用</summary>

```bash
# ── VoxCPM2（llama.cpp-omni 部署）─────────────────────────────
# 官方仓库： https://github.com/OpenBMB/VoxCPM        (Apache-2.0)
# 推理引擎： https://github.com/tc-mb/llama.cpp-omni  (MIT)
# GGUF 权重： https://huggingface.co/DennisHuang648/VoxCPM2-GGUF
#
# ⚠️ Ollama 上没有 TTS 库 —— ollama pull voxcpm2 会失败，TTS 必须外挂独立进程

# 1) 编译（Windows + Blackwell）
#    ⚠️ RTX 5060 Ti 是 sm_120，需要 CUDA Toolkit 12.8+；
#       版本不够会报 Unsupported gpu architecture 'compute_120'，
#       或静默回退到 CPU（跑得极慢且没有提示）
git clone https://github.com/tc-mb/llama.cpp-omni.git
cd llama.cpp-omni
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON \
      -DCMAKE_CUDA_ARCHITECTURES=120 -DCMAKE_CUDA_COMPILER=D:/dev/CUDA/bin/nvcc.exe
cmake --build build --target voxcpm2-cli --parallel

# 2) 下载权重（需要 BaseLM + Acoustic 两个文件）
#    BaseLM-Q8_0 ~1.6GB（推荐，8bit 体积减半）+ Acoustic-F16 ~1.7GB
huggingface-cli download DennisHuang648/VoxCPM2-GGUF \
  VoxCPM2-BaseLM-Q8_0.gguf VoxCPM2-Acoustic-F16.gguf --local-dir ../models/voxcpm2

# 3) 试跑
./build/bin/voxcpm2-cli -t "你好，我是小忆。" -o out.wav \
  ../models/voxcpm2/VoxCPM2-BaseLM-Q8_0.gguf \
  ../models/voxcpm2/VoxCPM2-Acoustic-F16.gguf
```

#### ✅ 本机已完成的部署（2026-10-24）

| 组件 | 位置 | 说明 |
|------|------|------|
| CUDA Toolkit 13.4.1 | `D:\dev\CUDA` | 手动搬到 D 盘；`CUDA_PATH` 指向此处 |
| llama.cpp-omni | `D:\dev\llama.cpp-omni` | 源码（含 Windows 补丁，见下） |
| 构建脚本 | `D:\dev\build-voxcpm2.bat` | 一键 rebuild |
| 可执行文件 | `D:\dev\llama.cpp-omni\build\bin\voxcpm2-cli.exe` | 261 KB |
| GGUF 权重 | `D:\dev\models\voxcpm2\` | BaseLM-Q8_0 + Acoustic-F16，各 1.7 GB |
| 演示音频 | `D:\dev\models\voxcpm2\voxcpm2-demo-*.wav` | 48kHz 单声道 |

**运行必须把 CUDA 的 DLL 目录加进 PATH**（CUDA 13 把运行时 DLL 放在 `bin\x64\`，不是 `bin\`）：

```bash
export PATH="D:\\dev\\CUDA\\bin;D:\\dev\\CUDA\\bin\\x64:$PATH"
```

**推荐参数（实测最优）**：

```bash
voxcpm2-cli -t "(一位温柔的年轻女性，声音轻柔舒缓)你好呀，我是小忆。" \
  --n-gpu-layers 8 \
  -o out.wav \
  D:/dev/models/voxcpm2/VoxCPM2-BaseLM-Q8_0.gguf \
  D:/dev/models/voxcpm2/VoxCPM2-Acoustic-F16.gguf
```

| 参数 | 作用 |
|------|------|
| `--n-gpu-layers 8` | **显存 7418 → 3975 MiB，RTF 0.267 → 0.465**（本机甜点） |
| **`--normalize`** | **必须加** —— 模型原始输出响度极不稳定（实测同一模型不同文本相差 30 dBFS），不归一化会出现"声音太小/忽大忽小" |
| `--norm-peak-db F` | 峰值目标，默认 -1.0 dBFS |
| `--norm-rms-db F` | RMS 目标，默认 -20.0 dBFS（决定实际增益） |
| `--no-limit` | 跳过归一化后的软限幅 |
| `-t "(描述)文本"` | 括号开头 = Voice Design，用自然语言指定音色（多人格用） |
| `--stream` | 流式输出，配合流式管线 |
| `--timesteps N` | CFM 步数，默认 10（降采样可提速） |
| `--cfg F` | 引导强度，默认 2.0 |
| ⚠️ **不要用 `--cpu`** | 它只把 AudioVAE 挪到 CPU，RTF 从 0.267 劣化到 4.839（差 18 倍） |

#### ⚠️ 响度必须归一化（本机实测发现）

**VoxCPM2 的 CLI 原始实现不做任何输出归一化**（AudioVAE 只用 `tanh` 收尾，CLI 直接 `v * 32767` 写 int16）。
实测同一模型、同一音色描述，不同文本的输出电平相差 **30 dBFS**：

| 输出 | 原始 peak | 原始 RMS | 说明 |
|------|-----------|----------|------|
| 短句（2.4s） | **-37.0 dBFS** | -56.6 dBFS | ❌ 几乎听不见 |
| 中段（10.2s） | -32.4 dBFS | -61.0 dBFS | ❌ 太小 |
| 长段（32s） | -4.4 dBFS | -27.1 dBFS | ✅ 正常 |

> 幅度还随音频长度**单调爬升**（逐 0.5s 峰值 -32 → -18 dBFS），所以"偶尔正常、多数太小"。

**已在 `voxcpm2_cli.cpp` 加了 `--normalize`**（上游没有，是本机补丁）：

```
按 RMS 目标算增益 → 用峰值上限兜底 → 软限幅防削波
```

实测效果（三个不同长度的文本）：

| 文本长度 | 原始 peak | 归一化后 peak | 归一化后 RMS | 增益 |
|---|---|---|---|---|
| 9 字 | -16.3 dBFS | **-1.00 dBFS** | -23.6 dBFS | 5.8x |
| 51 字 | -37.0 dBFS | **-1.00 dBFS** | -20.5 dBFS | 63.3x |
| 174 字 | -32.4 dBFS | **-1.00 dBFS** | -29.5 dBFS | 37.3x |

归一化后峰值完全一致；RMS 的剩余差异来自内容本身的停顿分布（不是增益不稳）。
放大 63x 后**信噪比仍有 46 dB**（底噪 -56.6 dBFS），底噪不会被听见。

> 💡 **RMS 目标用 -20 dBFS**（峰值 -1 dBFS）适合语音。若觉得偏响，改 `--norm-rms-db -23`。
> 要更严格的响度控制应改用 LUFS（ITU-R BS.1770），但对陪伴场景峰值归一化已经够用。

#### 🎭 人格音色样音（已生成）

用 Voice Design 的括号描述指定音色，样音在 `D:\dev\models\voxcpm2\`：

| 文件 | 音色描述 | 对应人格 |
|------|---------|---------|
| `persona-xiaoyi.wav` | A young woman with a gentle, warm and caring voice... | 小忆（温柔姐姐） |
| `persona-xiaozhi.wav` | A calm, composed male voice with a mature and professional tone... | 小知（理性工作） |
| `persona-xiaoqi.wav` | A young energetic female voice, bright and cheerful... | 小启（活力学习） |

> ⚠️ Voice Design 的描述**用英文效果更稳**（官方示例即英文），中文描述也能工作但音色区分度弱一些。
> 多人格系统的做法：每个 persona 存一段 10-20 秒的参考音频，改用 `-r <ref.wav>` 做**声音克隆**（比文字描述稳定得多）。

#### ⚠️ 必须打的三处 Windows 补丁

`llama.cpp-omni` 的 `src/llama-moe-slot.cpp` 用了 POSIX 的 `iovec` / `ssize_t`，在 MSVC 下编译不过。已在本机打过补丁（改动仅 2 处，不影响 Linux 行为）：

1. **`#ifdef _WIN32` 分支补 `struct iovec` 定义**（Windows 的 UCRT 没有 `<sys/uio.h>`）：
   ```cpp
   #ifdef _WIN32
   #include <fcntl.h>
   #include <io.h>
   struct iovec {              // ← 新增：最小兼容实现
       void * iov_base;
       size_t iov_len;
   };
   #else
   ```
2. **`ssize_t` 改成 `int64_t`**（MSVC 没有 POSIX 的 `ssize_t`）：
   ```cpp
   const int64_t result = (int64_t) _read(fd, cur[0].iov_base, (unsigned int) cur[0].iov_len);
   ```

> 不打补丁的话，`llama-moe-slot.cpp` 编译会报 `error C2027: 使用未定义的结构"iovec"` / `error C4430`，
> **整个 `llama` 库编译失败** —— `voxcpm2-cli` 依赖 `llama-common → llama`，绕不开。

#### ③ 新增 `--normalize`（响度归一化，本机新增，上游没有）

见上面「响度必须归一化」一节。改动在 `tools/omni/voxcpm2/voxcpm2_cli.cpp`：
新增 `CliConfig` 的 `normalize` / `norm_peak_db` / `norm_rms_db` / `limit` 四个字段、
`normalize_loudness()` 函数，以及在 `write_wav()` 之前调用。默认**关闭**（保持上游行为），
本项目的调用方应显式传 `--normalize`。

#### CUDA Toolkit 静默安装的坑（Windows）

```bat
REM ⚠️ 三个坑：
REM 1) 必须管理员权限（UAC），否则 setup.exe 启动即退、什么都不装
REM 2) 组件名带版本后缀（nvcc_13.4 而非 nvcc），且 cccl_13.4 在 13.4 里不存在
REM    （CUDA 13 用 thrust_13.4 代替）—— 传错名字会抛 0xE06D7363 异常
REM 3) 不能重复指定已安装的组件 —— 同样抛 0xE06D7363
REM    → 必须一个组件一次调用，逐个装
REM 4) -cudapath 参数在本版本不被接受 → 只能先装到默认路径，再整个目录搬到 D 盘
```

可用组件名（从安装器 manifest 实测得出）：`nvcc_13.4` `cudart_13.4` `crt_13.4` `cccl_13.4` `cublas_13.4` `cublas_dev_13.4` `nvrtc_13.4` `nvrtc_dev_13.4` `nvml_dev_13.4` `nvjitlink_13.4` `nvfatbin_13.4` `nvvm_13.4` `nvptxcompiler_13.4` `nvprune_13.4` `thrust_13.4` `visual_studio_integration_13.4` `nvtx_13.4`

```bat
for %%C in (nvcc_13.4 cudart_13.4 crt_13.4 cccl_13.4 cublas_13.4 cublas_dev_13.4
            nvrtc_13.4 nvrtc_dev_13.4 nvml_dev_13.4 nvjitlink_13.4 nvfatbin_13.4
            nvvm_13.4 nvptxcompiler_13.4 nvprune_13.4 thrust_13.4) do (
  cuda_13.4.1_windows_x86_64.exe -s -n %%C
)
```

> 💡 **MSVC generator vs Ninja**：VS 里没装 CUDA toolset 时，CMake 的 MSVC generator 会报
> `No CUDA toolset found`。改用 **Ninja generator + 显式 `-DCMAKE_CUDA_COMPILER=<nvcc.exe>`** 即可绕开（VS Build Tools 自带 ninja）。
> 另外 CUDA 13.4 官方支持 Visual Studio 2026 (MSVC 195x)，与本机的 VS 18 Build Tools 14.50 匹配。

#### ⚠️ HuggingFace 直连不通（国内）

`huggingface.co` 在本机直连超时，用镜像：

```bash
curl -L -o VoxCPM2-BaseLM-Q8_0.gguf \
  https://hf-mirror.com/DennisHuang648/VoxCPM2-GGUF/resolve/main/VoxCPM2-BaseLM-Q8_0.gguf
```

</details>

### 2.3 其他 TTS 备选（可选）

```bash
# ── 备选：IndexTTS2（情绪/音色解耦，8 维情感向量，但 FP16 占 4-8G，本机需半精度）──
# 从 https://github.com/index-tts/index-tts 下载
# 解压到 models/indextts2/

# ── 备选：Qwen3-TTS（延迟最优，97ms 首包）──
# 从 https://github.com/QwenLM/Qwen3-TTS 下载
# 解压到 models/qwen3-tts/

# ── SenseVoice-Small（ASR + 情感标签）──
# 从 https://github.com/FunAudioLLM/SenseVoice 下载
# 解压到 models/sensevoice-small/
```

## 3. 启动服务

### 3.1 方式 A：一键启动

```powershell
.\scripts\start-companion.ps1
```

脚本会按顺序启动 Ollama → ChromaDB → Mem0 → AstrBot，并在 AstrBot WebUI 可见后给出提示。

### 3.2 方式 B：手动启动（调试用）

```powershell
# Terminal 1: Ollama
ollama serve

# Terminal 2: ChromaDB
python -m chromadb.cli.run_server --host 127.0.0.1 --port 8000

# Terminal 3: Mem0
python mem0/server.py

# Terminal 4: AstrBot
python astrbot/main.py
```

### 3.3 验证服务端口

```powershell
# Ollama
curl http://127.0.0.1:11434/api/tags

# ChromaDB
curl http://127.0.0.1:8000/api/v1/heartbeat

# Mem0
curl http://127.0.0.1:8888/docs

# AstrBot
# 浏览器访问 http://127.0.0.1:6185
```

## 4. 配置

### 4.1 复制示例配置

```powershell
cp config\mem0.env.example config\mem0.env
cp config\astrbot.example.yaml config\astrbot.yaml
```

### 4.2 编辑配置

用编辑器打开以下文件，按需修改：

- `config/mem0.env`：填入实际路径、提取器模型名等
- `config/astrbot.yaml`：选择 TTS 音色 `speaker_id`、调整人格 prompt

### 4.3 加载到运行环境

AstrBot 和 Mem0 应能从 `.env` 文件自动加载，或者把它们的内容合并到用户级环境变量：

```powershell
Get-Content config\mem0.env | ForEach-Object {
    if ($_ -match '^([^#]+?)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "User")
    }
}
```

## 5. 烟雾测试

### 5.0 ✅ 先做这一步：ASR 质检（别跳过）

> **本地 TTS 的时长/语速/峰值完全不能证明内容正确。** 幻觉 TTS（重复、念不全、突然 EOS）
> 的时长指标和正常 TTS 一模一样。2026-10-24 就在这上面栽过：一份"6 字/秒、语速正常"的样音，
> ASR 转写出来只有 `What?`。

工具：`D:\dev\verify-tts.py`（本机已装好 faster-whisper + whisper-small 模型）

```powershell
# 校验单个文件：转写 + 与原文逐句比对 + 末尾能量
cd D:\dev\models\voxcpm2
python D:\dev\verify-tts.py out.wav --text "你期望它念出来的原文"

# 批量校验
python D:\dev\verify-tts.py a.wav b.wav c.wav --text "同一段原文"
```

判定依据（按可靠性排序）：

| 依据 | 含义 |
|------|------|
| **缺失句列表为空** | **决定性判据** —— 原文每一句都在转写里（含 ASR 同音字容错） |
| ASR 相似度 | 参考值；> 85% 基本可信 |
| 实际生成步数 < max_steps | 说明模型自然 EOS，而非被截断 |
| 末尾峰值 dBFS | 仅参考，**不能**用来判断截断（自然收尾时最后一个字也有能量） |

> ⚠️ **两个已踩过的坑**（工具里都已处理）：
> 1. **whisper 中文输出常为繁体** —— 工具内置 OpenCC 繁简归一，否则相似度会虚低（同一段音频 81% → 97%）
> 2. **whisper 在长音频末尾会漏识别** —— 55 秒音频整段转写停在倒数第二句，但单独转写最后 4 秒发现内容其实完整。工具会对尾部（10/6/4 秒）分别转写再合并，避免把"完整"误判成"截断"
>
> 注：`faster_whisper` 在 Python 3.14 上会因 PyAV 版本报 `metadata_errors`，工具已绕过（自己用 wave+numpy 读音频）。
> 注：ASR 的同音字误识别（如"小忆"→"小易"、"烦心事"→"繁星事"）会拉低相似度，工具用 75% 的局部相似度做容错。

### 5.1 测试 LLM

```powershell
curl http://127.0.0.1:11434/api/chat -d '{
  "model":"qwen3.5:9b-q4_K_M",
  "think":false,
  "repeat_penalty":1.0,
  "options":{"num_ctx":8192},
  "messages":[{"role":"user","content":"用一句话介绍你自己"}],
  "stream":false
}'
```

> ⚠️ **`think` 必须在顶层**，不能放在 `options` 里 —— 这是 Qwen3.5 在 Ollama 上最大的坑。
> 不关的话每条回复会多出 800+ 隐形 token，延迟从 2 秒变成 30-60 秒。
>
> 验证：正常响应应该在 2-5 秒内返回。若超过 20 秒，说明 `think` 没生效。

**确认思考模式确实关闭了**（对比两次响应长度）：

```powershell
# 开思考（会很慢且带 think 字段）
curl http://127.0.0.1:11434/api/chat -d '{"model":"qwen3.5:9b-q4_K_M","messages":[{"role":"user","content":"1+1=?","stream":false}]}'

# 关思考（顶层 think:false）
curl http://127.0.0.1:11434/api/chat -d '{"model":"qwen3.5:9b-q4_K_M","think":false,"messages":[{"role":"user","content":"1+1=?","stream":false}]}'
```

### 5.2 测试 Mem0

```powershell
curl -X POST http://127.0.0.1:8888/memory `
  -H "Content-Type: application/json" `
  -d '{"user_id":"test","messages":[{"role":"user","content":"我叫小明，喜欢喝咖啡"}]}'
```

Mem0 后台会调用 `qwen3.5:2b` 做提取。提取完成后 30 秒（冷路径 keep_alive）该模型会自行卸载，
可用 `ollama ps` 确认 —— 语音交互时它不占 TTS 的显存。

### 5.3 测试 AstrBot

打开 http://127.0.0.1:6185 ，发送一条消息，应该收到机器人回复。

### 5.4 测试记忆注入

1. 第一句：「记住我的名字叫小明，我是一名程序员」
2. 等 5-10 秒（让 Mem0 完成提取）
3. 开新对话：「我是做什么工作的？」

应该能答出"程序员"。

## 6. 注册为 Windows 服务（可选）

```powershell
# 需要安装 NSSM：https://nssm.cc/download
# 或者 winget install NSSM.NSSM

.\scripts\install-windows-service.ps1
```

注册后：
- AstrBot + Mem0 跟随系统启动
- 崩溃后 5 秒自动恢复
- 日志写入 `logs/`

卸载：
```powershell
.\scripts\uninstall-windows-service.ps1
```

## 7. 卸载

如果想完全移除：

```powershell
# 1. 卸载 Windows 服务（如已注册）
.\scripts\uninstall-windows-service.ps1

# 2. 关闭所有服务
.\scripts\stop-companion.ps1

# 3. 卸载 Ollama
winget uninstall Ollama.Ollama

# 4. 删除项目目录
Remove-Item -Recurse -Force E:\Documents\local-companion-bot
```

模型权重默认缓存在 `%USERPROFILE%\.ollama\models`，需要单独清理。

## 故障排查

### Ollama 启动失败
- 检查端口 `11434` 占用
- 检查显卡驱动：`nvidia-smi`
- 检查 VRAM 占用：是否有别的大模型驻留

### Mem0 提取失败
- 确认 Ollama 中 `qwen3.5:2b-q4_K_M` 已 pull
- 检查 ChromaDB 是否启动（端口 8000）

### AstrBot 启动崩溃
- 查看 `logs/astrbot.err.log`
- 验证 Python 版本 ≥ 3.11
- 单独测试：直接运行 `python astrbot/main.py`

### 响应特别慢（30 秒以上）
**最常见原因：`think` 没关。** 排查顺序：
1. 确认请求里 `think` 在**顶层**（不是 `options.think`）
2. 确认 `astrbot.yaml` 里 `llm.think: false`（顶层）
3. 用 Modelfile 兜底：`PARAMETER think false`
4. 确认 Ollama ≥ v0.17.5

### 机器人"忘了"刚说过的话
- 确认 `OLLAMA_CONTEXT_LENGTH=8192` 已生效
- Ollama 在显存 < 24 GiB 时**默认只有 4096**，不显式设置就是会丢上下文

### 回答出现重复啰嗦
- 确认 `repeat_penalty: 1.0`（Ollama 默认 1.1 会损害 Qwen3.5 质量）

### TTS / SenseVoice 模型加载失败
- 确认模型已下载到 `models/` 目录
- 路径在 `config/astrbot.yaml` 中正确
- TTS 第一次加载很慢（30s+ 准备），耐心等
- ⚠️ 别试图用 `ollama pull` 装 TTS —— Ollama 没有 TTS 库（v0.40.9 的原生 TTS 仅 Apple Silicon）

### 显存 OOM
- 依次降级：见 [hardware-budget.md](hardware-budget.md) 的降级策略
- 或重启 Ollama 让其完全释放显存
- 检查 `ollama ps` 看是否有多个模型同时驻留
