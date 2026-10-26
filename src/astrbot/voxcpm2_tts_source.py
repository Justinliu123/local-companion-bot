"""VoxCPM2 本地语音合成 —— AstrBot 的 TTS provider（备选引擎）。

和 Qwen3-TTS provider 同构：推理跑在**独立进程**（本地服务），AstrBot 只发 HTTP 请求。

选它的理由（2026-10-25 本机实测）：
  - RTF ~1.76（Qwen3-TTS 是 ~4.1），快 2 倍以上
  - 输出 **48 kHz**（Qwen3-TTS 是 24 kHz）
  - 括号语法的 Voice Design 有效：描述会改变语速与强度
    （实测同一句话，"温柔关心" 3.6 字/秒 / RMS 0.060，
      "愤怒激动" 6.2 字/秒 / RMS 0.153）
  - 显存 ~5.7 GB

⚠️ **TTS 服务必须关掉 torch.compile**（`VoxCPM2.from_pretrained(..., optimize=False)`）：
  句长变化触发 dynamic shape 重编译，实测 5 次里 3 次输出乱码（幻觉成日文/英文），
  RTF 还从 1.76 涨到 4.9。关掉后 6/6 正确、RTF 1.76。
  `D:\dev\voxcpm2_server.py` 默认就是关的（要开得显式加 `--compile`）。

⚠️ 两个 TTS 引擎不要同时加载模型：
  VoxCPM2 ~5.7GB + Qwen3-TTS ~6.3GB + 桌面 ~4.4GB > 16GB，会 OOM。
  两个 provider 都注册好，按需在面板里切换当前使用哪个。

配置项（在 AstrBot 面板里填）：
    voxcpm2_server_url   默认 http://127.0.0.1:8010
    voxcpm2_timeout      单次请求超时秒数，默认 120
    voxcpm2_instruct     音色描述，如"一位温柔的年轻女性，声音轻柔舒缓"
    voxcpm2_voice        克隆音色的名字（参考音频放在服务端的 D:/dev/voices/<名字>.wav）
    voxcpm2_reference_wav_path  直接给参考音频路径（优先于 voice）
    voxcpm2_prompt_text  参考音频的准确文字稿（给了相似度更高）
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


@register_provider_adapter(
    "voxcpm2_local",
    "VoxCPM2 本地 (48kHz)",
    provider_type=ProviderType.TEXT_TO_SPEECH,
)
class ProviderVoxCPM2Local(TTSProvider):
    def __init__(
        self,
        provider_config: dict,
        provider_settings: dict,
    ) -> None:
        super().__init__(provider_config, provider_settings)
        self.server_url = (
            provider_config.get("voxcpm2_server_url") or "http://127.0.0.1:8010"
        ).rstrip("/")
        self.timeout = float(provider_config.get("voxcpm2_timeout", 120) or 120)
        self.instruct = provider_config.get("voxcpm2_instruct", "") or ""
        # 克隆音色：voice 是 D:\dev\voices\<名字>.wav 的名字（服务端按名字找参考音频）
        self.voice = provider_config.get("voxcpm2_voice", "") or ""
        self.reference_wav_path = provider_config.get("voxcpm2_reference_wav_path", "") or ""
        self.prompt_text = provider_config.get("voxcpm2_prompt_text", "") or ""
        self.set_model("voxcpm2")
        self._alive_cache = None
        self._alive_at = 0.0

    async def _service_alive(self) -> bool:
        """探测 TTS 服务是否在线（服务没起时不必刷一堆错误）。"""
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
        """合成语音，返回 WAV 文件路径（AstrBot 的接口约定）。"""
        if not text or not text.strip():
            return ""
        if not await self._service_alive():
            logger.warning(
                f"[VoxCPM2] 服务不可达 ({self.server_url}) —— "
                f"用 companionctl.bat start vcpm 启动"
            )
            return ""

        try:
            body = {"text": text, "instruct": self.instruct}
            if self.voice:
                body["voice"] = self.voice
            if self.reference_wav_path:
                body["reference_wav_path"] = self.reference_wav_path
            if self.prompt_text:
                body["prompt_text"] = self.prompt_text
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.server_url}/tts",
                    json=body,
                )
                resp.raise_for_status()
                audio_bytes = resp.content
                dur = resp.headers.get("X-Duration", "")
                rtf = resp.headers.get("X-RTF", "")
        except httpx.HTTPError as e:
            logger.error(f"[VoxCPM2] 请求失败: {e}")
            return ""
        except Exception as e:
            logger.error(f"[VoxCPM2] 合成异常: {e}")
            return ""

        temp_dir = get_astrbot_temp_path()
        os.makedirs(temp_dir, exist_ok=True)
        out_path = os.path.join(temp_dir, f"voxcpm2_{generate_timestamp_id()}.wav")
        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        logger.info(
            f"[VoxCPM2] 合成完成 ({dur}s, RTF {rtf}) -> {os.path.basename(out_path)}"
        )
        return out_path
