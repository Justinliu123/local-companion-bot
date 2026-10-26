# 服务生命周期：开关策略

> 核心约束：**用户希望不在需要时能完全关闭，不影响日常使用机器。**

## 分层架构

```
┌─────────────────────────────────────────────────────────┐
│  L1 控制面（常驻后台）                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐          │
│  │ AstrBot  │  │ Mem0 API │  │  ChromaDB    │          │
│  │ :6185    │  │ :8888    │  │  :8000       │          │
│  │ ~80 MB   │  │ ~100 MB  │  │  ~150 MB     │          │
│  └──────────┘  └──────────┘  └──────────────┘          │
│  合计 ~330 MB RAM，不占显存                               │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  L2 主 LLM（按需加载，闲置自动卸载）                     │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Ollama + qwen3.5:9b-q4_K_M                    │    │
│  │ ~7.6 GB 模型 + ~0.4 GB KV cache (q8_0)        │    │
│  │ OLLAMA_KEEP_ALIVE=5m → 5 分钟无调用自动卸载      │    │
│  └─────────────────────────────────────────────────┘    │
│  + qwen3.5:2b-q4_K_M 提取器（~2.3 GB，冷路径独立卸载）      │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  L3 语音（懒加载，60 秒无语音即释放）                   │
│  ┌──────────────────┐  ┌──────────────────┐             │
│  │ VoxCPM2 TTS      │  │ SenseVoice ASR   │             │
│  │ 权重 ~3.3 GB     │  │ CPU only         │             │
│  └──────────────────┘  └──────────────────┘             │
└─────────────────────────────────────────────────────────┘
```

> **L2 内部分冷热**：主对话是**热路径**（每条消息都跑，keep_alive=5m）；
> 提取器是**冷路径**（每 5 轮才跑一次），调用时单独带 `"keep_alive": "30s"`，
> 提取完 30 秒就自己卸载 → 语音交互时它不占 TTS 的显存。
>
> ⚠️ **2026-10-24 实测修正**：9B 权重显存 ~7.6 GB（不是磁盘体积 6.6 GB）；提取器 Q4_K_M 是 ~2.3 GB（默认标签 `qwen3.5:2b` 实为 Q8_0）；TTS 已从 IndexTTS2（4-8 GB）改为 **VoxCPM2 + llama.cpp-omni**（实测：全 GPU 7418 MiB，`--n-gpu-layers 8` → 3975 MiB，RTF 0.465）；且桌面常驻程序本身就占 ~4 GB 显存 → **实际可用显存只有 ~12 GB**。详见 [[hardware-budget.md]]。

## 日常使用流

```
┌─────────────────────────────────────────────────────────────┐
│ 早上开机                                                   │
│   → 控制面 L1 已常驻（开机自启）                            │
│   → 显存占用：~0 GB；RAM：~330 MB                          │
└─────────────────────────────────────────────────────────────┘
                          ↓ 想跟机器人聊天
┌─────────────────────────────────────────────────────────────┐
│ 双击 start-companion.ps1（或 AstrBot 自动预热）             │
│   → 触发首次 LLM 调用 → Ollama 自动加载 9B                │
│   → 等 8 秒（5060 Ti 加载 7.6G 模型的速度）                │
│   → 显存占用：~11 - 14.6 GB（含桌面常驻 ~4 GB）             │
└─────────────────────────────────────────────────────────────┘
                          ↓ 想要语音
┌─────────────────────────────────────────────────────────────┐
│ AstrBot 检测到语音模式启用                                  │
│   → 拉起 VoxCPM2 TTS + SenseVoice ASR                       │
│   → 提取器此时已卸载（冷路径 30s keep_alive 到期）           │
│   → 显存峰值：~13.4 - 17.4 GB                                │
│   ⚠️ 上界越过 16GB 物理显存 → 必须先降级（见 hardware-budget）│
└─────────────────────────────────────────────────────────────┘
                          ↓ 离开 / 不说话了
┌─────────────────────────────────────────────────────────────┐
│ 60 秒无语音 → watchdog 自动卸载 L3                         │
│   → 显存回落到 ~11 - 14.6 GB                                │
└─────────────────────────────────────────────────────────────┘
                          ↓ 5 分钟不调用 LLM
┌─────────────────────────────────────────────────────────────┐
│ Ollama KEEP_ALIVE 到期 → 自动 unload 9B                    │
│   → 机器人自身显存归零（桌面仍占 ~4 GB）                    │
└─────────────────────────────────────────────────────────────┘
                          ↓ 完全停止机器人
┌─────────────────────────────────────────────────────────────┐
│ 双击 stop-companion.ps1                                    │
│   → 关闭 AstrBot / Mem0 / ChromaDB                        │
│   → 机器人自身显存、内存、CPU 全部归零                       │
│   → ⚠️ 桌面自身仍占 ~4 GB（无核显，GPU 负责显示输出）        │
└─────────────────────────────────────────────────────────────┘
```

## 不需要脚本的极简用法

如果你只是偶尔聊一句：

1. **不跑 start 脚本**：让系统保持「控制面常驻但 L2 卸载」状态
2. 用 AstrBot CLI 直接对话：
   ```powershell
   python astrbot/cli.py
   ```
3. 退出 CLI → Ollama 5 分钟后自己卸模型
4. 控制面继续常驻，几乎不占资源

## 一键开关脚本

| 场景 | 命令 |
|------|------|
| 启动全部 | `.\scripts\start-companion.ps1` |
| 关闭全部 | `.\scripts\stop-companion.ps1` |
| 只卸载主模型（继续文字聊天） | 见 [stop-companion.ps1](../scripts/stop-companion.ps1) 步骤 1 |
| 注册为 Windows 服务 | `.\scripts\install-windows-service.ps1`（需管理员） |

## Ollama 空闲自动卸载机制

通过环境变量控制，**无需重启服务**：

```powershell
# 用户级环境变量（永久生效）
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "5m", "User")

# 推荐值：
#  "5m"  - 聊天间隙不卸载，再开就秒回（最舒适）
#  "30s" - 极致省电，但每次重连要等 8 秒
#  "1h"  - 几乎不卸载（等同常驻 9B）
```

### per-model 覆盖：让冷路径模型提前卸载

`OLLAMA_KEEP_ALIVE` 是**全局默认值**，但 Ollama 支持在**单次请求**里覆盖某个模型的存活时间：

```bash
# 提取器调用 —— 只让它活 30 秒
curl http://127.0.0.1:11434/api/chat -d '{
  "model":"qwen3.5:2b-q4_K_M",
  "keep_alive":"30s",
  "messages":[{"role":"user","content":"..."}]
}'
```

在本项目中的用法：

| 模型 | 路径 | keep_alive | 理由 |
|------|------|-----------|------|
| `qwen3.5:9b-q4_K_M` | 热路径 | 5m（全局默认） | 每条消息都跑，要随时能接上话 |
| `qwen3.5:2b-q4_K_M` | 冷路径 | **30s（单次请求覆盖）** | 每 5 轮才跑一次；语音交互时不占 TTS 显存 |
| VoxCPM2（llama.cpp-omni） | 语音路径 | 60s（watchdog 卸载） | 见下面的 L3 懒加载 |

> 这是本次换代能"加 2.3 GB 主模型却不撞语音峰值"的关键。
> ⚠️ 2026-10-24 实测：冷路径成立，但**语音峰值上界已越过 16 GB 物理显存** —— 冷路径只解决了"提取器不叠加"，没解决"桌面占 4 GB"和"TTS 占 4-8 GB"。见 [[hardware-budget.md]]。

## TTS / ASR 懒加载实现（AstrBot watchdog 伪代码）

```python
# 在 AstrBot 的 session_manager 中添加：
import asyncio
import time

_VOICE_LAST_USED = {}  # user_id -> timestamp
_VOICE_IDLE_TIMEOUT = 60  # 秒

async def on_voice_interaction(user_id: str):
    """每次语音交互时调用"""
    _VOICE_LAST_USED[user_id] = time.time()
    await ensure_voice_models_loaded()

async def voice_idle_watchdog():
    """后台协程：定期检查并卸载空闲的语音模型"""
    while True:
        await asyncio.sleep(15)  # 每 15 秒检查一次
        now = time.time()
        if _VOICE_LAST_USED and min(_VOICE_LAST_USED.values()) < now - _VOICE_IDLE_TIMEOUT:
            await unload_voice_models()
            _VOICE_LAST_USED.clear()
            logger.info("Voice models unloaded due to idle.")
```

## 远程关闭

如果出门前忘了关，可从局域网其他机器关闭：

```bash
# Linux / macOS
ssh user@desktop-ip "powershell -ExecutionPolicy Bypass -File C:\\Users\\You\\Documents\\local-companion-bot\\scripts\\stop-companion.ps1"

# 或者用 Windows 远程桌面手动关
mstsc /v:desktop-ip
```

## 崩溃自愈（可选进阶）

用 NSSM 把 AstrBot 注册为 Windows 服务：
- 启动崩溃 → 5 秒后自动重启
- 系统重启后 → 自动恢复
- 日志写入 `logs/astrbot.err.log`

详见 [install-windows-service.ps1](../scripts/install-windows-service.ps1)。
