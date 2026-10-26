"""SenseVoice 本地语音识别 —— AstrBot 的 STT provider。

和 TTS provider 一样：推理跑在**独立进程**（本地 ASR 服务，sherpa-onnx + SenseVoice ONNX），
AstrBot 只发 HTTP 请求。好处是 AstrBot 的 venv 不需要装 onnxruntime / sherpa-onnx，
而且 ASR 服务可以按需起停（CPU 推理，不占显存）。

配置项（在 AstrBot 面板里填）：
    sensevoice_server_url   默认 http://127.0.0.1:8009
    sensevoice_timeout      单次请求超时秒数，默认 30
    sensevoice_keep_emotion  是否返回情感标签，默认 True
"""

import base64
import os

import httpx

from astrbot.core import logger
from astrbot.core.provider.entities import ProviderType
from astrbot.core.provider.provider import STTProvider
from astrbot.core.provider.register import register_provider_adapter
from astrbot.core.utils.media_utils import MediaResolver


@register_provider_adapter(
    "sensevoice_local",
    "SenseVoice 本地 (sherpa-onnx)",
    provider_type=ProviderType.SPEECH_TO_TEXT,
)
class ProviderSenseVoiceLocal(STTProvider):
    def __init__(
        self,
        provider_config: dict,
        provider_settings: dict,
    ) -> None:
        super().__init__(provider_config, provider_settings)
        self.server_url = (
            provider_config.get("sensevoice_server_url")
            or "http://127.0.0.1:8009"
        ).rstrip("/")
        self.timeout = float(provider_config.get("sensevoice_timeout", 30) or 30)
        self.keep_emotion = bool(provider_config.get("sensevoice_keep_emotion", True))
        self.set_model("sensevoice")

    async def get_text(self, audio_url: str) -> str:
        """识别音频，返回文本。"""
        if not audio_url:
            return ""

        # 统一转成 16 kHz 单声道 WAV 再送服务（服务端也做一次兜底重采样）
        tmp_path = None
        try:
            async with MediaResolver(
                audio_url,
                media_type="audio",
                default_suffix=".wav",
            ).as_path(target_format="wav") as audio:
                tmp_path = audio.path
                with open(tmp_path, "rb") as f:
                    audio_b64 = base64.b64encode(f.read()).decode("ascii")
        except Exception as e:
            logger.error(f"[SenseVoice] 读取音频失败: {e}")
            return ""

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.server_url}/asr",
                    json={"audio_base64": audio_b64},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            logger.error(f"[SenseVoice] 请求失败: {e}")
            return ""
        except Exception as e:
            logger.error(f"[SenseVoice] 识别异常: {e}")
            return ""

        text = (data.get("text") or "").strip()
        emotion = data.get("emotion") or ""
        if self.keep_emotion and emotion:
            text = f"<|{emotion.upper()}|>{text}"
        logger.info(
            f"[SenseVoice] 识别完成 ({data.get('duration', 0):.1f}s 音频, "
            f"{data.get('elapsed', 0):.2f}s): {text[:80]}"
        )
        return text
