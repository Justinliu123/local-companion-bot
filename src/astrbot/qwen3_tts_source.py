"""Qwen3-TTS 1.7B（本地）—— AstrBot 的 TTS provider。

设计要点：
  - 推理跑在**独立进程**（`D:/dev/qwen3_tts_server.py`，FastAPI），AstrBot 只发 HTTP 请求。
    理由：torch + qwen-tts 装在专用 venv（D:/dev/voxcpm-py），不污染 AstrBot 环境；
    模型常驻显存可按需启停（见 docs/service-lifecycle.md 的 L3 懒加载分层）。
  - AstrBot 自己会按句切分、逐句调用 `get_audio`（见 core/astr_agent_run_util.py），
    所以本 provider 收到的是**单句**，不需要再切分。
  - `instruct` 同时控制音色与情绪 —— 情绪状态机的 `emotion_hints` 可直接映射。

配置项（在 AstrBot 面板里填）：
    qwen3_tts_server_url   默认 http://127.0.0.1:8008
    qwen3_tts_instruct     音色描述，如"一位温柔的年轻女性，声音轻柔舒缓"
    qwen3_tts_emotion      当前情绪（neutral/caring/listening/playful/serious/tired）
    qwen3_tts_language     默认 Chinese
    qwen3_tts_timeout      单次请求超时秒数，默认 120
    qwen3_tts_batch_size   服务端 batch 大小，默认 4
"""

import os
import time

import httpx

from astrbot.core import logger
from astrbot.core.provider.entities import ProviderType
from astrbot.core.provider.provider import TTSProvider
from astrbot.core.provider.register import register_provider_adapter
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path
from astrbot.core.utils.datetime_utils import generate_timestamp_id

# 与 config/astrbot.example.yaml 的 emotion_instruct 保持一致
EMOTION_INSTRUCT = {
    "neutral": "语气自然平和。",
    "caring": "语气充满关心和怜惜，语速放慢。",
    "listening": "语气轻声，几乎没有起伏，像在安静地听。",
    "playful": "语气轻快俏皮，带点笑意。",
    "serious": "语气沉稳认真，不开玩笑。",
    "tired": "语气很轻很慢，像快睡着了。",
}


@register_provider_adapter(
    "qwen3_tts",
    "Qwen3-TTS 1.7B (本地)",
    provider_type=ProviderType.TEXT_TO_SPEECH,
)
class ProviderQwen3TTS(TTSProvider):
    def __init__(
        self,
        provider_config: dict,
        provider_settings: dict,
    ) -> None:
        super().__init__(provider_config, provider_settings)

        self.server_url = (
            provider_config.get("qwen3_tts_server_url")
            or "http://127.0.0.1:8008"
        ).rstrip("/")
        self.instruct = provider_config.get("qwen3_tts_instruct", "") or ""
        self.emotion = provider_config.get("qwen3_tts_emotion", "") or ""
        self.language = provider_config.get("qwen3_tts_language", "Chinese") or "Chinese"
        self.timeout = float(provider_config.get("qwen3_tts_timeout", 120) or 120)
        self.batch_size = int(provider_config.get("qwen3_tts_batch_size", 4) or 4)
        self.speaker = provider_config.get("qwen3_tts_speaker", "") or ""

        self.set_model("qwen3_tts")
        self._alive_cache = None
        self._alive_at = 0.0

    def _build_instruct(self) -> str:
        """音色描述 + 当前情绪。"""
        instruct = self.instruct
        if self.emotion and self.emotion in EMOTION_INSTRUCT:
            instruct = f"{instruct}{EMOTION_INSTRUCT[self.emotion]}".strip()
        return instruct

    async def _service_alive(self) -> bool:
        """探测 TTS 服务是否在线（避免服务没起时刷一堆错误）。"""
        if self._alive_cache is not None and time.time() - self._alive_at < 30:
            return self._alive_cache
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{self.server_url}/health")
                self._alive_cache = r.status_code == 200
        except Exception:
            self._alive_cache = False
        self._alive_at = time.time()
        return self._alive_cache

    async def get_audio(self, text: str) -> str:
        """调用本地 TTS 服务，返回 WAV 文件路径（AstrBot 的接口约定）。"""
        if not text or not text.strip():
            return ""

        if not await self._service_alive():
            logger.warning(
                f"[Qwen3-TTS] 服务不可达 ({self.server_url}) —— "
                f"用 companionctl.bat start tts 启动"
            )
            return ""

        payload = {
            "text": text,
            "instruct": self._build_instruct(),
            "language": self.language,
            "batch_size": self.batch_size,
            # AstrBot 已按句切分，单句不需要服务端再切
            "split": False,
        }
        if self.speaker:
            payload["speaker"] = self.speaker

        temp_dir = get_astrbot_temp_path()
        os.makedirs(temp_dir, exist_ok=True)
        out_path = os.path.join(temp_dir, f"qwen3_tts_{generate_timestamp_id()}.wav")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.server_url}/tts", json=payload)
                resp.raise_for_status()
                with open(out_path, "wb") as f:
                    f.write(resp.content)
        except httpx.HTTPError as e:
            logger.error(f"[Qwen3-TTS] 请求失败: {e}")
            return ""
        except Exception as e:
            logger.error(f"[Qwen3-TTS] 生成音频异常: {e}")
            return ""

        dur = resp.headers.get("X-Duration", "")
        rtf = resp.headers.get("X-RTF", "")
        logger.info(
            f"[Qwen3-TTS] 生成完成 {dur}s (RTF {rtf}) -> {os.path.basename(out_path)}"
        )
        return out_path
