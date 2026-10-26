# CLAUDE.md

> 本文件是**部署机 agent 的自动入口**。在这个仓库里启动的 agent 会自动读到它。
> 目标：agent 不需要向人转述上下文，就能自己接着干。

---

## 一、这是什么

全本地、隐私优先的中文 AI 陪伴机器人。**所有推理都在本机，任何数据不出本机。**

```
用户语音/文字
  → AstrBot（编排中枢，:6185 WebUI）
      → Mem0（长期记忆，ChromaDB 向量库）
      → Ollama（对话 LLM）
      → TTS 服务（独立进程）
  → 语音输出
```

**三层服务结构**（服务可关是硬需求 —— 机器人跑在用户的日常电脑上）：

| 层 | 内容 | 策略 |
|---|------|------|
| L1 控制面 | AstrBot、Mem0 API、ChromaDB | 常驻，~400 MB RAM |
| L2 主 LLM | Ollama + Qwen3.5 | `OLLAMA_KEEP_ALIVE=5m` 自动卸载 |
| L2' 提取器 | Ollama + Qwen3.5-2B | 冷路径，独立 30 秒 keep_alive |
| L3 语音 | TTS 服务 + SenseVoice ASR | 60 秒闲置看门狗卸载 |

---

## 二、读哪几个文件（权威性排序）

| 文件 | 什么时候读 | 权威性 |
|------|-----------|--------|
| [docs/local-stack.md](docs/local-stack.md) | **先读这个** —— 本机实际跑的是什么 | 最高，实测记录 |
| [docs/model-strategy.md](docs/model-strategy.md) | 选模型 / 调参数 | 决策记录 |
| [docs/hardware-budget.md](docs/hardware-budget.md) | 显存吃紧时 | 账本 |
| [docs/avatar-integration.md](docs/avatar-integration.md) | 做形象层 | 设计 + **执行手册** |
| [plans/roadmap.md](plans/roadmap.md) | 排期 / 进度 | 阶段划分 |
| [docs/architecture.md](docs/architecture.md) | 改数据流 | 架构 |

> ⚠️ **文档里的数字分两种**：带「实测」标注的是真的；不带的是设计推算。
> 两者冲突时以「实测」为准，并顺手把设计文档改过来。

---

## 三、当前状态（2026-10-26）

| 组件 | 状态 | 位置 |
|------|------|------|
| Ollama v0.40.10 | ✅ 已装 | `D:\dev\ollama`（绿色版），模型在 `D:\dev\ollama-models` |
| AstrBot v4.29.3 | ✅ 已装 | `D:\dev\AstrBot`，venv `D:\dev\astrbot-venv` |
| SenseVoice ASR | ✅ 已装 | `D:\dev\sensevoice_server.py` :8009 |
| VoxCPM2 TTS | ✅ 已装（**主用**） | `D:\dev\voxcpm2_server.py` :8010 |
| Qwen3-TTS 1.7B | ✅ 已装（备选，唯一能控情绪） | `D:\dev\qwen3_tts_server.py` :8008 |
| Mem0 / ChromaDB | ⏳ 未接 | — |
| 形象层（桌宠） | ⏳ 设计完成，**未执行** | 见 [docs/avatar-integration.md](docs/avatar-integration.md) §10 执行手册 |

**控制台**：`cd D:\dev\companion && companionctl.bat status|start|stop|logs`

---

## 四、⚠️ 红线（违反就是事故）

1. **绝不把 `OLLAMA_HOST` 设成 `0.0.0.0`** —— Ollama **没有任何鉴权**，公网上已有 17.5 万个裸奔实例。只监听 `127.0.0.1`。
2. **绝不引入云端 API** —— Mem0 / embedding / LLM 全部指向本机 Ollama。
3. **声纹只存 embedding，绝不存原始音频** —— 注册完立刻删临时 wav。
4. **`.gitignore` 挡住的绝不提交** —— `data/`、`*.npy`、`config/*.env`、真实配置。
5. **两个 TTS 引擎不能同时跑** —— 5.7 + 6.3 GB + 桌面 4.4 GB > 16 GB。
6. **VoxCPM2 必须 `optimize=False`** —— 开 torch.compile 会出乱码且 RTF 从 1.76 劣化到 4.9。

---

## 五、显存约束（最容易踩的坑）

> **这台机器的桌面程序常驻占 ~4 GB 显存（Chrome / ToDesk / QQLive / wallpaper64 …），
> 所以 Ollama 实际可用只有 ~12 GB，不是 16 GB。所有预算按 12 GB 算。**

| 配置 | 峰值 | 结论 |
|------|------|------|
| 桌面常驻 + Ollama 4B + Qwen3-TTS | 12189 MiB ✅ 余 3862 | **语音模式用 4B** |
| 桌面常驻 + Ollama 9B + Qwen3-TTS | 15404 MiB ❌ 余 607 | **9B 留给纯文字模式** |

**9B 和 TTS 不能同时常驻** —— TTS 请求会**卡死**（不是报错，是 CUDA 挂住，provider 120 秒超时返回空路径）。

---

## 六、待确认项 —— 都有默认答案，别停下来问

> 完整表格见 [docs/avatar-integration.md](docs/avatar-integration.md) §12。
> **默认答案就是决定**，只有现场证据证伪了它，才需要找人。

| # | 确认项 | 默认答案 |
|---|--------|---------|
| 1 | 形象层走哪条路径 | **路径 A 先行**（复用 dsh-pet 桌宠），路径 B 后续 |
| 2 | 能不能用大肥鱼素材 | **能**（目前纯自用）；一旦要商用 → 立刻切路径 B 自制素材 |
| 3 | 桌宠端口 | **3080**（`dsh-pet-standalone` 默认） |
| 4 | 动画名怎么定 | **抄它实际的动画池**；找不到就填「待机」，**不要自己编名字** |
| 5 | 形象层失败怎么办 | **吞掉 + 连续 5 次自我关闭** —— 绝不影响对话 |
| 6 | `avatar:` 配置写哪 | `D:\dev\AstrBot\data\cmd_config.json`（**主配置不在仓库里**） |
| 7 | `config/avatar.example.yaml` 是什么 | **模板 + 档位表存档**，不是运行时读的文件 |

---

## 七、下一件该做的事

按顺序：

1. **形象层阶段一** —— [docs/avatar-integration.md](docs/avatar-integration.md) §10 执行手册（自包含，含每步的验收标准和失败处理）
2. **Mem0 接上** —— Phase 2，记忆是「陪伴感」的另一半
3. **语音端到端** —— Phase 3，注意首帧语音延迟 5-20 秒是 TTS 主导，要靠人格提示词限制回复长度

---

## 八、代码约定

- `src/companion/` 是**参考骨架**，说明模块间怎么协作；实际部署按目标机器的 Python 环境调整
- 新模块：纯标准库优先，不引新依赖；**外部调用失败必须吞掉**（表现层绝不能崩主链路）
- Windows 控制台是 **GBK** —— 设 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`；
  `.bat` 保持纯 ASCII；`.ps1` 存成 UTF-8 **带 BOM**
- 改完跑一遍 `python scripts/test-avatar.py` 确认没弄坏形象层
