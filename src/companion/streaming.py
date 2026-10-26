"""
流式响应管线
完整设计见 docs/streaming-pipeline.md
"""
from __future__ import annotations
import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Optional, AsyncIterator, Callable, Awaitable


# ============================================================
# 规则常量
# ============================================================
INTERJECTIONS = {"嗯", "哦", "啊", "嗳", "嘿", "噢", "嗯嗯", "哦哦", "啊啊", "...", "…"}
STOP_PHRASES = {"别说了", "别说话", "安静", "够了", "停", "闭嘴", "不说了", "别烦我"}
SELF_TALK_STARTERS = ("我想想", "那个", "就是说", "怎么说呢", "其实", "可能")
END_PUNCTUATION = {"。", "！", "？", "!", "?", ".", "\n", "；", ";"}
QUESTION_HINTS = {"?", "？", "呢", "吗", "怎么", "为什么", "啥"}


# ============================================================
# 句子边界检测
# ============================================================
@dataclass
class BoundaryConfig:
    end_punctuation: set = field(default_factory=lambda: END_PUNCTUATION)
    min_chars: int = 3
    predict_silence_ms: int = 250


class SentenceBoundaryDetector:
    """
    判断 ASR 输出是否"足够完整"可以开始响应。
    返回 (is_complete, reason)。
    """

    def __init__(self, config: dict | None = None):
        self.config = BoundaryConfig(**(config or {}))

    def is_complete(self, text: str, last_vad_silence_ms: int) -> tuple[bool, str]:
        text = text.strip()
        if not text:
            return False, "empty"

        if any(text.endswith(p) for p in self.config.end_punctuation):
            return True, "punctuation"

        if last_vad_silence_ms >= self.config.predict_silence_ms:
            if len(text) < self.config.min_chars:
                return False, "too_short_after_silence"
            return True, "silence"

        return False, "still_speaking"


# ============================================================
# 应答决策门
# ============================================================
@dataclass
class GateConfig:
    quiet_after_stop_seconds: int = 60
    min_chars_default: int = 3


class ShouldRespondGate:
    """
    决定机器人是否应该对当前输入做出回应。
    """

    def __init__(self, config: dict | None = None):
        self.config = GateConfig(**(config or {}))
        self.quiet_until: float = 0

    def should_respond(self, text: str, audio_present: bool) -> tuple[bool, str]:
        now = time.time()

        # 全局静音期
        if now < self.quiet_until:
            return False, "global_quiet"

        if not audio_present and not text.strip():
            return False, "no_input"

        text_stripped = text.strip()

        # 1. 纯语气词
        if text_stripped in INTERJECTIONS:
            return False, "interjection"

        # 2. 用户明示停止
        for phrase in STOP_PHRASES:
            if phrase in text:
                self.quiet_until = now + self.config.quiet_after_stop_seconds
                return False, "user_stop"

        # 3. 自言自语开场
        if any(text_stripped.startswith(s) for s in SELF_TALK_STARTERS):
            return False, "self_talk_opener"

        # 4. 太短 + 没问号
        if len(text_stripped) < self.config.min_chars_default:
            has_question = any(h in text for h in QUESTION_HINTS)
            if not has_question:
                return False, "too_short"

        # 默认：回应
        return True, "default"


# ============================================================
# 流式会话编排
# ============================================================
@dataclass
class StreamingConfig:
    enabled: bool = True
    vad_min_silence_ms: int = 250
    predict_at_silence_ms: int = 200
    cancel_on_user_continue: bool = True
    cancel_grace_ms: int = 100

    interrupt:
        enabled: bool = True
        vad_threshold: float = 0.4
        min_user_speech_ms: int = 150


class StreamingSession:
    """
    编排一次流式对话会话。
    集成：
      - streaming ASR（外部提供，传入 audio chunk 流）
      - 句子边界检测
      - 应答决策门
      - LLM streaming（外部提供）
      - TTS streaming（外部提供）
      - 中途打断监听

    使用方法：
        session = StreamingSession(asr=..., llm=..., tts=..., audio_in=..., audio_out=...)
        await session.run()
    """

    def __init__(
        self,
        config: dict,
        asr_stream: Callable[[AsyncIterator[bytes]], AsyncIterator[str]],
        llm_stream: Callable[[str], AsyncIterator[str]],
        tts_stream: Callable[[str], AsyncIterator[bytes]],
        audio_in: AsyncIterator[bytes],    # 麦克风流
        audio_out: Callable[[bytes], Awaitable[None]],
        vad_callback: Optional[Callable[[bytes], tuple[bool, float]]] = None,
    ):
        self.config = StreamingConfig(**config)
        self.boundary = SentenceBoundaryDetector()
        self.gate = ShouldRespondGate()
        self.asr_stream = asr_stream
        self.llm_stream = llm_stream
        self.tts_stream = tts_stream
        self.audio_in = audio_in
        self.audio_out = audio_out
        self.vad_callback = vad_callback

        self._tts_task: Optional[asyncio.Task] = None
        self._llm_task: Optional[asyncio.Task] = None
        self._interrupted = False

    async def run(self):
        """主循环"""
        if not self.config.enabled:
            return await self._run_batch()

        asr_iter = self.asr_stream(self.audio_in)
        accumulated_text = ""
        last_silence_ms = 0

        async for partial_text in asr_iter:
            accumulated_text += partial_text

            # 1. 句子边界检测
            last_silence_ms = self._update_silence_ms()
            is_done, reason = self.boundary.is_complete(accumulated_text, last_silence_ms)
            if not is_done:
                continue

            # 2. 应答决策
            should, gate_reason = self.gate.should_respond(
                accumulated_text, audio_present=True
            )
            if not should:
                # 不回应：清空累积，继续监听
                accumulated_text = ""
                continue

            # 3. 启动流式 LLM + TTS
            await self._speak_streaming(accumulated_text)
            accumulated_text = ""

            # 4. 检查是否被打断
            if self._interrupted:
                self._interrupted = False
                continue

    async def _speak_streaming(self, text: str):
        """流式说话：LLM token → TTS chunk → speaker"""
        sentence_buffer = ""

        # 启动打断监听
        if self.config.interrupt.get("enabled", True):
            monitor_task = asyncio.create_task(self._monitor_interrupt())

        try:
            async for token in self.llm_stream(text):
                sentence_buffer += token

                # 按标点切句合成
                if any(sentence_buffer.endswith(p) for p in END_PUNCTUATION):
                    if sentence_buffer.strip():
                        async for audio_chunk in self.tts_stream(sentence_buffer):
                            if self._interrupted:
                                break
                            await self.audio_out(audio_chunk)
                        sentence_buffer = ""

            # 处理剩余 buffer
            if sentence_buffer.strip():
                async for audio_chunk in self.tts_stream(sentence_buffer):
                    if self._interrupted:
                        break
                    await self.audio_out(audio_chunk)
        finally:
            if 'monitor_task' in locals():
                monitor_task.cancel()

    async def _monitor_interrupt(self):
        """监听用户中途开始说话"""
        speech_ms = 0
        threshold = self.config.interrupt.get("vad_threshold", 0.4)
        min_ms = self.config.interrupt.get("min_user_speech_ms", 150)

        try:
            while True:
                chunk = await self.audio_in.__anext__()
                if self.vad_callback:
                    has_speech, prob = self.vad_callback(chunk)
                    if has_speech and prob >= threshold:
                        speech_ms += len(chunk) // 16  # 粗略按 16kHz 算 ms
                        if speech_ms >= min_ms:
                            self._interrupted = True
                            return
                    else:
                        speech_ms = max(0, speech_ms - 5)
                await asyncio.sleep(0.01)
        except (asyncio.CancelledError, StopAsyncIteration):
            return

    def _update_silence_ms(self) -> int:
        """外部实现：返回 VAD 检测到的静音时长 ms"""
        return 0  # 占位

    async def _run_batch(self):
        """退化路径：非流式"""
        pass


# ============================================================
# 标点切分（供 TTS streaming 使用）
# ============================================================
SENTENCE_SPLIT_PATTERN = re.compile(r"([。！？!?,；;])")


def split_by_punctuation(text: str) -> list[str]:
    """
    把文本按结束标点切分。
    "今天加班了，你吃饭了吗" → ["今天加班了，", "你吃饭了吗"]
    """
    parts = SENTENCE_SPLIT_PATTERN.split(text)
    sentences = []
    current = ""
    for p in parts:
        if not p:
            continue
        current += p
        if p in END_PUNCTUATION:
            sentences.append(current)
            current = ""
    if current.strip():
        sentences.append(current)
    return sentences