#!/usr/bin/env python
"""把本地 TTS 支持打进 AstrBot（可重放，幂等）。

AstrBot 升级会丢这些改动，重跑本脚本即可重新应用。

共 4 处改动：

1. **provider 源文件** —— `src/astrbot/qwen3_tts_source.py`
   → `astrbot/core/provider/sources/qwen3_tts_source.py`
   （装饰器会把它注册进 provider_cls_map）

2. **manager.py 加 provider 分支** —— AstrBot 的 provider 类型是**硬编码 match**
   （`dynamic_import_provider`），没有 fallback 到 `provider_cls_map`，
   所以不加这个 case 模块永远不会被 import。

3. **request_flags.py：enable_streaming 默认改 False** —— 这是 TTS 能不能生效的
   关键。webchat 默认注入 `enable_streaming=True`，会覆盖
   `provider_settings.streaming_response`；流式模式下 agent 结果类型是
   STREAMING_FINISH，`result_decorate` stage 会在 TTS 分支之前
   `if is_stream: return` 直接跳过 → 本地 TTS provider 永远不被调用。
   关掉后走缓冲路径，结果类型是 LLM_RESULT → 原生 TTS 逻辑正常生效。

4. **live_chat_service.py：透传 action_type** —— 让客户端可以显式请求
   Live 模式（走 run_live_agent，边生成边按句合成 TTS）。

用法:
    python scripts/patch-astrbot-qwen3tts.py [--astrbot D:/dev/AstrBot]
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
PROVIDER_SRC = HERE.parent / "src" / "astrbot" / "qwen3_tts_source.py"
STT_SRC = HERE.parent / "src" / "astrbot" / "sensevoice_stt_source.py"
VCPM_SRC = HERE.parent / "src" / "astrbot" / "voxcpm2_tts_source.py"

MANAGER_ANCHOR = '''            case "tei_rerank":
                from .sources.tei_rerank_source import (
                    TEIRerankProvider as TEIRerankProvider,
                )
'''
MANAGER_CASE = '''            case "qwen3_tts":
                # 本地 Qwen3-TTS（见 scripts/patch-astrbot-qwen3tts.py）
                from .sources.qwen3_tts_source import (
                    ProviderQwen3TTS as ProviderQwen3TTS,
                )
            case "voxcpm2_local":
                # 本地 VoxCPM2（48kHz，见 scripts/patch-astrbot-qwen3tts.py）
                from .sources.voxcpm2_tts_source import (
                    ProviderVoxCPM2Local as ProviderVoxCPM2Local,
                )
'''

STT_ANCHOR = '''            case "sensevoice_stt_selfhost":
                from .sources.sensevoice_selfhosted_source import (
                    ProviderSenseVoiceSTTSelfHost as ProviderSenseVoiceSTTSelfHost,
                )
'''
STT_CASE = '''            case "sensevoice_local":
                # 本地 SenseVoice（独立 ASR 服务，见 scripts/patch-astrbot-qwen3tts.py）
                from .sources.sensevoice_stt_source import (
                    ProviderSenseVoiceLocal as ProviderSenseVoiceLocal,
                )
'''

FLAGS_OLD = '''    resolved[key] = value if isinstance(value, bool) else default
    return resolved'''
FLAGS_NEW = '''    resolved[key] = value if isinstance(value, bool) else default
    # enable_streaming 强制关闭（忽略前端传的 flags）。
    # 前端 Chat.vue / StandaloneChat.vue 硬编码 `enableStreaming = ref(true)`，
    # 而 flags 的优先级高于服务端默认值，所以只改默认值根本没用。
    # 关流式的原因：流式模式下消息由 respond stage 通过 async_stream 直接推给
    # 平台适配器（绕过 chain 处理），TTS 补出来的音频赶不上发送 —— 实测
    # respond stage 先 "Prepare to send"（空链），TTS 随后才跑，音频丢了。
    resolved["enable_streaming"] = False
    return resolved'''

LIVE_ANCHOR = '''                        "message_id": message_id,
                        "llm_checkpoint_id": llm_checkpoint_id,
                    },'''
LIVE_NEW = '''                        "message_id": message_id,
                        "llm_checkpoint_id": llm_checkpoint_id,
                        # action_type="live" 让 webchat adapter 走 run_live_agent，
                        # 由它自己按句分块合成 TTS。不传就是普通文字聊天。
                        "action_type": message.get("action_type"),
                    },'''

RECORD_ANCHOR = '''                        "type": "record",
                        "data": data,
                        "streaming": streaming,'''
RECORD_NEW = '''                        "type": "record",
                        "data": data,
                        # 必须带 stored_filename —— 前端 partUrl() 依次尝试
                        # embedded_url -> embedded_file.url -> attachment_id ->
                        # stored_filename/filename，缺了它就拿不到可播放 URL，
                        # 音频附件渲染不出来（只有文字）。
                        "stored_filename": filename,
                        "streaming": streaming,'''


def patch_file(path, anchor, new, marker, label):
    if not path.exists():
        print(f"  跳过 {label}（文件不存在: {path}）")
        return
    s = path.read_text(encoding="utf-8")
    if marker in s:
        print(f"  [OK] {label} 已是目标状态")
        return
    if anchor not in s:
        print(f"  [X] {label} 找不到锚点，请手动处理: {path}")
        return
    path.write_text(s.replace(anchor, new, 1), encoding="utf-8")
    print(f"  [OK] {label} 已打补丁")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--astrbot", default="D:/dev/AstrBot")
    args = ap.parse_args()
    root = pathlib.Path(args.astrbot)

    mgr = root / "astrbot" / "core" / "provider" / "manager.py"
    flags = root / "astrbot" / "core" / "platform" / "sources" / "webchat" / "request_flags.py"
    live = root / "astrbot" / "dashboard" / "services" / "live_chat_service.py"
    event = root / "astrbot" / "core" / "platform" / "sources" / "webchat" / "webchat_event.py"
    dst = root / "astrbot" / "core" / "provider" / "sources" / "qwen3_tts_source.py"
    stt_dst = root / "astrbot" / "core" / "provider" / "sources" / "sensevoice_stt_source.py"

    if not mgr.exists():
        print(f"找不到 {mgr}，用 --astrbot 指定 AstrBot 源码目录")
        return 1

    print(f"[1/8] provider 源文件")
    if not PROVIDER_SRC.exists():
        print(f"  [X] 找不到 {PROVIDER_SRC}")
        return 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(PROVIDER_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  [OK] -> {dst}")

    print(f"[2/8] manager.py provider 分支 (TTS)")
    patch_file(mgr, MANAGER_ANCHOR, MANAGER_ANCHOR + MANAGER_CASE,
               'case "qwen3_tts":', "manager.py")

    print(f"[3/8] manager.py provider 分支 (STT)")
    patch_file(mgr, STT_ANCHOR, STT_ANCHOR + STT_CASE,
               'case "sensevoice_local":', "manager.py (STT)")

    print(f"[4/8] STT provider 源文件")
    if not STT_SRC.exists():
        print(f"  [X] 找不到 {STT_SRC}")
        return 1
    stt_dst.parent.mkdir(parents=True, exist_ok=True)
    stt_dst.write_text(STT_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  [OK] -> {stt_dst}")

    print(f"[5/8] VoxCPM2 TTS provider 源文件")
    if not VCPM_SRC.exists():
        print(f"  [X] 找不到 {VCPM_SRC}")
        return 1
    vcpm_dst = root / "astrbot" / "core" / "provider" / "sources" / "voxcpm2_tts_source.py"
    vcpm_dst.parent.mkdir(parents=True, exist_ok=True)
    vcpm_dst.write_text(VCPM_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  [OK] -> {vcpm_dst}")

    print(f"[6/8] request_flags.py 强制关闭流式")
    patch_file(flags, FLAGS_OLD, FLAGS_NEW, 'resolved["enable_streaming"] = False', "request_flags.py")

    print(f"[7/8] live_chat_service.py action_type 透传")
    patch_file(live, LIVE_ANCHOR, LIVE_NEW, '"action_type": message.get("action_type"),', "live_chat_service.py")

    print(f"[8/8] webchat_event.py record 部件带 stored_filename")
    patch_file(event, RECORD_ANCHOR, RECORD_NEW, '"stored_filename": filename,', "webchat_event.py")

    print("\n完成。重启 AstrBot 后生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
