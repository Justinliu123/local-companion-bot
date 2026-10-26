"""
情绪状态机
完整设计见 docs/companion-features.md §1 与 docs/voice-biometrics.md §3
"""
from __future__ import annotations
import re
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

EmotionState = Literal["neutral", "caring", "listening", "playful", "serious", "tired"]


@dataclass
class EmotionConfig:
    states: dict = field(default_factory=dict)
    transitions: list = field(default_factory=list)
    cooldown: dict = field(default_factory=lambda: {
        "min_stay_seconds": 30,
        "exit_on_user_clear_signal": [],
    })


# 文本信号比语音信号更"明确"的标记词
TEXT_EXPLICIT_SIGNALS = [
    "哈哈", "哈哈哈", "笑死", "绝了",
    "谢谢", "感谢",
    "没事", "我很好", "我没事",
]


class EmotionStateMachine:
    """
    综合文本 + 语音情感信号，控制回应风格。
    """

    def __init__(self, config: dict):
        self.config = EmotionConfig(
            states=config.get("states", {}),
            transitions=config.get("transitions", []),
            cooldown=config.get("cooldown", {}),
        )
        self.current_state: EmotionState = "neutral"
        self.last_transition_at: float = 0
        self._last_voice_signal: Optional[tuple[str, float]] = None
        self._last_voice_at: float = 0

    def set_voice_signal(self, voice_emotion: Optional[str], confidence: float):
        """由 audio handler 在收到音频时调用"""
        if voice_emotion:
            self._last_voice_signal = (voice_emotion, confidence)
            self._last_voice_at = time.time()

    def detect_from_text(self, user_msg: str) -> Optional[EmotionState]:
        """根据用户输入判定要切换到的状态。返回 None 表示保持当前。"""
        for phrase in self.config.cooldown.get("exit_on_user_clear_signal", []):
            if phrase in user_msg:
                return "neutral"

        for rule in self.config.transitions:
            if any(keyword in user_msg for keyword in rule["match"]):
                return rule["to"]

        return None

    def _text_is_explicit(self, user_msg: str) -> bool:
        return any(sig in user_msg for sig in TEXT_EXPLICIT_SIGNALS)

    def transition(self, user_msg: str) -> EmotionState:
        """
        综合判定：文本信号 + 语音情感信号 → 目标状态。
        """
        text_target = self.detect_from_text(user_msg)

        # ---- 融合语音信号 ----
        voice_target: Optional[EmotionState] = None
        voice_conf = 0.0
        if self._last_voice_signal:
            ve, vc = self._last_voice_signal
            if (time.time() - self._last_voice_at) < 15:  # 15 秒内有效
                voice_target = self._voice_to_state(ve)
                voice_conf = vc

        # ---- 决策 ----
        target = self._decide(
            text_target=text_target,
            voice_target=voice_target,
            voice_conf=voice_conf,
            user_msg=user_msg,
        )

        # ---- 应用状态 + 冷却 ----
        return self._apply_with_cooldown(target)

    def _voice_to_state(self, voice_emotion: str) -> EmotionState:
        # 延迟导入避免循环依赖
        from .voice_bio import VOICE_EMOTION_TO_STATE
        return VOICE_EMOTION_TO_STATE.get(voice_emotion, "neutral")

    def _decide(
        self,
        text_target: Optional[EmotionState],
        voice_target: Optional[EmotionState],
        voice_conf: float,
        user_msg: str,
    ) -> Optional[EmotionState]:
        """融合两条信号，决定目标状态"""
        if text_target and voice_target is None:
            return text_target
        if voice_target and text_target is None:
            # 仅语音信号 → 高置信度才采用
            return voice_target if voice_conf >= 0.7 else None
        if text_target and voice_target:
            if text_target == voice_target:
                return text_target
            # 冲突：文本明显（"哈哈"、"我没事"）→ 采用文本
            if self._text_is_explicit(user_msg):
                return text_target
            # 否则保守：取 caring（关心模式总不会错）
            return "caring"
        return None

    def _apply_with_cooldown(self, target: Optional[EmotionState]) -> EmotionState:
        if target is None:
            return self.current_state

        now = time.time()
        in_cooldown = (now - self.last_transition_at) < self.config.cooldown.get("min_stay_seconds", 30)
        same_state = (target == self.current_state)

        if same_state:
            return self.current_state
        if in_cooldown and target != "neutral":
            return self.current_state

        self.current_state = target
        self.last_transition_at = now
        return target

    def current_style_hint(self) -> str:
        """返回当前情绪对应的 prompt 风格 hint"""
        state_cfg = self.config.states.get(self.current_state, {})
        style = state_cfg.get("prompt_style", "")
        forbid = state_cfg.get("forbid", [])
        if forbid:
            style += f"\n避免：{', '.join(forbid)}"
        return style