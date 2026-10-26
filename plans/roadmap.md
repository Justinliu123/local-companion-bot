# 阶段路线图

## Phase 0：文档与脚本准备 ✅ 当前阶段

- [x] 架构设计：分层方案与数据流
- [x] 显存 / 内存 / 磁盘账本
- [x] 服务开关策略（自动卸载 + 一键脚本）
- [x] 部署指南
- [x] 启动 / 关闭 / 服务化脚本
- [x] 配置示例
- [x] README 与项目结构
- [x] **模型选型 2026-10 全量复核**（含微调 / 特调模型调研）→ [[model-strategy.md]]

**当前交付物**：完整的设计文档 + 一套可运行的脚本，便于目标机器就绪后立即部署。

---

## Phase 1：目标机器环境验证

> 目标：到达目标机器后 30 分钟内确认整套技术栈可启动。

- [x] 确认硬件 —— 实测：RTX 5060 Ti **16 GB** / 32 GB **DDR5-6000** / C: 322 GB + D: 874 GB 空闲
  > ⚠️ 额外发现：桌面常驻程序占 **~4 GB 显存** → Ollama 实际可用只有 **~12 GB**，所有预算按 12 GB 算
- [x] Windows 11 (26200) + 驱动 610.88 / CUDA 13.3
- [x] `nvidia-smi` 正常显示 RTX 5060 Ti（compute capability 12.0）
- [x] Python 3.12 隔离环境（uv，`D:/dev/voxcpm-py`）；PowerShell 可用
- [ ] 安装 Ollama（**装 v0.40.10**，上游当前最新版；旧的"≥v0.31.2"已过时）并验证 `ollama --version`
- [ ] 配置环境变量（**必须显式设 num_ctx**）：
  - [ ] `OLLAMA_KEEP_ALIVE=5m`
  - [ ] `OLLAMA_CONTEXT_LENGTH=8192`
  - [ ] `OLLAMA_KV_CACHE_TYPE=q8_0`
  - [ ] `OLLAMA_FLASH_ATTENTION=1`
  - [ ] `OLLAMA_HOST=127.0.0.1:11434`（**不要** 0.0.0.0）
- [ ] 拉取模型：
  - [ ] `qwen3.5:9b-q4_K_M` (磁盘 ~6.6 GB / 显存 ~7.6 GB) ← 主对话
  - [ ] `qwen3.5:2b-q4_K_M` (磁盘 ~1.9 GB / 显存 ~2.3 GB) ← 提取器（冷路径）
  - [ ] `qwen3.5:9b-q8_0` (磁盘 ~10 GB) ← 可选，纯文字模式用（质量更好）
- [ ] 验证基础对话：`ollama run qwen3.5:9b-q4_K_M "你好"`
- [ ] **验证 `think: false` 生效**（顶层字段，不是 `options.think`）→ 响应应在 2-5 秒内
- [ ] 验证 `repeat_penalty: 1.0` 已设

**退出条件**：能在控制台与 9B 模型聊天、响应 < 5 秒（思考模式已关），且关闭对话后 5 分钟内显存归零。

---

## Phase 2：单组件 Smoke Test

> 逐个组件在目标机器上验证。

- [ ] **Ollama**
  - [ ] `POST /api/chat` 单轮调用（顶层 `think: false`）
  - [ ] 流式输出（`stream: true`）
  - [ ] 卸载验证（`nvidia-smi` 显存变化）
  - [ ] per-model keep_alive 验证：提取器请求带 `"keep_alive":"30s"`，30 秒后 `ollama ps` 里消失

- [ ] **ChromaDB**
  - [ ] 启动 server，访问 `/api/v1/heartbeat`
  - [ ] 写入测试向量，检索 top-1

- [ ] **Mem0**
  - [ ] 启动 server，访问 `/docs`
  - [ ] 写入一条记忆 → 检索 → 命中
  - [ ] 验证 LLM 提取器调用 2B 模型而非云端

- [ ] **AstrBot**
  - [ ] 启动 main.py，访问 WebUI
  - [ ] 配置连接到 Ollama → 浏览器对话成功
  - [ ] 配置连接到 Mem0 → 对话注入记忆

- [ ] **SenseVoice**（可选）
  - [ ] 加载模型，传入 wav → 文本输出
  - [ ] **读取情感标签**（`<|HAPPY|>` / `<|SAD|>` 等）→ 喂给情绪状态机
  - [ ] 中文识别率主观评估

- [ ] **TTS**（2026-10-24 已完成选型与部署，见 [[model-strategy.md]] §4.1）
  - [x] **VoxCPM2 官方 PyTorch 版** —— 部署完成，ASR 逐句校验内容完整（94-100%）
  - [x] **Qwen3-TTS 1.7B** —— 部署完成，`instruct` 可控音色+情绪（实测 4 种情绪，内容 100% 一致）
  - [x] **按句切分 + batch 流程** —— 实测 batch=4 → 显存 5.49 GB / RTF 1.64；全批 RTF 0.672
  - [x] **ASR 质检工具链** —— `D:/dev/verify-tts.py`（转写+逐句比对+尾部补转写+繁简归一）
  - [ ] ❌ **llama.cpp-omni 移植版已放弃** —— 中文严重退化（ASR 转写为 `What?`），不可用
  - [ ] 接入 AstrBot 的 TTS provider（`provider: qwen3-tts` 配置已写好）

**退出条件**：每个组件独立可运行，接口契约清晰。

---

## Phase 3：集成联调

- [ ] AstrBot ↔ Mem0 联调
  - [ ] 第一轮对话让机器人「记住」测试事实
  - [ ] 新对话中机器人主动提及
  - [ ] 验证记忆提取器的触发节奏

- [ ] 端到端文字模式
  - [ ] WebUI → LLM → 回复 完整路径
  - [ ] 测量首字延迟（< 1s 目标）
  - [ ] 测量端到端延迟（< 3s 目标）

- [ ] 端到端语音模式
  - [ ] 麦克风 → VAD → ASR → LLM → TTS → 扬声器 全路径
  - [ ] 测量首字延迟（< 2s 目标）
  - [ ] 打断语义：用户说"停"，机器人立即停
  - [ ] 长对话（30 轮以上）不爆显存
  - [ ] **确认语音峰值时提取器已卸载**（`ollama ps`）

- [ ] 异常路径
  - [ ] Ollama 崩溃后 AstrBot 自动重连
  - [ ] 显存压力时 watchdog 触发卸载

**退出条件**：能完成一次从问好到聊 10 分钟再说不聊了的完整体验，且中途没有崩溃。

---

## Phase 4：体验打磨

- [ ] 人格 prompt 调优（基于实际对话感受修改 system_prompt）
- [ ] 记忆提取 prompt 调优（让事实提取更精准）
- [ ] TTS 音色对比测试（多个中文女声候选）
- [ ] TTS 情感向量与情绪状态机的映射调优（`emotion_hints`）
- [ ] ASR 长句 / 方言 / 快速说话 鲁棒性
- [ ] 错别字 / 没听清时的处理策略
- [ ] **微调 bake-off**（见 [[model-strategy.md]] §6.5）：
  - [ ] 建 50-100 条真实对话 eval 集
  - [ ] 对比基座 vs `WSAI-Heart-Pro` vs `Pingo SFT`（中文陪伴向）
  - [ ] 比人格一致性 / 多轮漂移 / 拒答率 / 延迟

**退出条件**：能说"用起来挺自然"而不是"还行吧"。

---

## Phase 5：自动化（可选）

- [ ] 注册 Windows 服务（开机自启 + 崩溃自愈）
- [ ] 配置 NSSM 日志轮转
- [ ] 配置开机后自动预热（启动 5 秒后自动调一次 LLM）
- [ ] 桌面快捷方式（双击启动 / 关闭）
- [ ] **多 persona LoRA 库**（照 Pingo SFT 的"烘焙模式"思路，为每个 persona 训一份 adapter）
- [ ] **运行时可调人格参数**（照 TARS 思路：人格旋钮放 system prompt，训练时保留 sys/no-sys 混合）

**退出条件**：下次重启电脑后机器人自动恢复在线。

---

## Phase 6：持续维护

- [ ] 月度：显存 / 内存使用报告（人工）
- [ ] 季度：**模型生态复核**（照 [[model-strategy.md]] §9 的清单）→ 半年一变，Qwen3 → Qwen3.5 → Qwen3.6/3.8 就是半年内的事
- [ ] 季度：Ollama 版本升级（≥ v0.31.2）
- [ ] 半年：声纹克隆训练（如果想要更独特的音色）
- [ ] 年度：硬件换代评估（5060 Ti 后续型号？→ 24 GB 机器可上 Qwen3.6-35B-A3B / EQ-v5）

---

## 已知风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| Qwen3.5 中文质量不及预期 | 中 | 高 | 降级 `qwen3.5:4b-q4_K_M`；对照上一代 `qwen3:8b`；纯文字模式可先试 `qwen3.5:9b-q8_0` |
| 语音模式显存 OOM | **高** | 中 | 本机桌面常驻占 ~4GB，实际可用仅 ~12GB。TTS 用 VoxCPM2 `--n-gpu-layers 8`（实测 3975MiB/RTF 0.465）+ 关后台程序（-3GB）→ 峰值 ~12.5GB。⚠️ 绝不要用 `--cpu`（RTF 劣化到 4.8）。见 hardware-budget.md |
| `think` 没关导致延迟爆炸 | **高** | **高** | 顶层 `think: false` + Modelfile `PARAMETER think false`；Phase 1 必验 |
| Ollama 默认 num_ctx 只有 4096 | **高** | 中 | 显式设 `OLLAMA_CONTEXT_LENGTH=8192` |
| Mem0 提取器过度调用导致卡顿 | 中 | 中 | 拉大 `EXTRACTION_INTERVAL_TURNS` |
| TTS 播报不自然 | 中 | 中 | IndexTTS2 → Qwen3-TTS → CosyVoice2 → Spark-TTS |
| TTS 情感不跟随情绪状态 | 中 | 中 | 检查 `emotion_hints` 映射；IndexTTS2 需确认情感向量轴序 |
| Ollama 无鉴权被公网扫描 | 低 | **高** | `OLLAMA_HOST` 锁 `127.0.0.1`，绝不用 0.0.0.0 |
| Ollama Windows 兼容性 bug | 低 | 中 | 备用 WSL2；保持 ≥ v0.31.2 |
| 5060 Ti 实际显存比预期少 | 低 | 高 | 启动脚本自动检测 + 降级策略（[[hardware-budget.md]]） |
| 开源模型迭代过快，配置过时 | **高** | 中 | 每季度按 [[model-strategy.md]] §9 复核 |

---

## 变更记录

- **2026-10-25**：完成 TTS 引擎选型与实测对比。选定 **Qwen3-TTS 1.7B 为主引擎**（唯一可控情绪，显存省 1.4 GB），
  **VoxCPM2 官方版备选**（48 kHz、整句 RTF 更低）。放弃 llama.cpp-omni 移植版（中文退化）。
  同步修正了 4 处显存账目偏差，并新增 ASR 质检工具链。Phase 1 的硬件/系统/Python 侧已就绪，
  **Ollama 与 LLM 侧仍未开始**。

- 2026-08-13: Phase 0 完成，文档与脚本首次落地
- 2026-10-22: **模型选型全量换代** —— Qwen3-8B+1.7B → Qwen3.5-9B+2B；CosyVoice → IndexTTS2；
  修正 `think` 位置 bug、补 `repeat_penalty`、加 KV cache q8_0 + Flash Attention；
  新增微调/特调模型专表与 bake-off 方法论
