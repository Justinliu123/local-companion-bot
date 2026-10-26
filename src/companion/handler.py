"""
主消息处理入口
组合：声纹识别 + 语音情感 + 情绪状态机 + 话题检测 + 记忆排序 + LLM 生成 + 多人格
完整设计见 docs/companion-features.md §5、docs/voice-biometrics.md §6、docs/persona-system.md
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

import numpy as np

from .emotion import EmotionStateMachine
from .topic import TopicTracker
from .memory_rank import MemoryRanker
from .proactive import ProactiveScheduler
from .voice_bio import SpeakerIdentifier, VoiceEmotionDetector
from .persona import PersonaManager, Persona


class CompanionHandler:
    def __init__(self, config: dict, mem0_client, llm_client, user_id: str = "default_user"):
        self.config = config
        self.mem0 = mem0_client
        self.llm = llm_client
        self.default_user_id = user_id

        self.emotion = EmotionStateMachine(config.get("emotion", {}))
        self.topic = TopicTracker(config.get("context", {}).get("topic_detection", {}))
        self.ranker = MemoryRanker(config.get("memory", {}).get("ranking", {}))

        # 人格管理（必须）
        personas_cfg = config.get("personas", [])
        if not personas_cfg:
            # 兼容旧配置：使用 llm.system_prompt 作为默认人格
            personas_cfg = [{
                "id": "default",
                "name": "助手",
                "description": "默认助手",
                "system_prompt": config["llm"]["system_prompt"],
                "is_default": True,
                "tts": {"speaker_id": config.get("voice", {}).get("tts", {}).get("speaker_id", "default")},
            }]
        self.persona_manager = PersonaManager(
            personas_cfg,
            switching_config=config.get("persona_switching", {}),
        )

        # 声纹与语音情感（可选启用）
        voice_cfg = config.get("voice", {})
        self.speaker_id: Optional[SpeakerIdentifier] = None
        self.emotion_detector: Optional[VoiceEmotionDetector] = None
        self.default_user = voice_cfg.get("voiceprint", {}).get("default_user", user_id)

        if voice_cfg.get("voiceprint", {}).get("enabled"):
            self.speaker_id = SpeakerIdentifier(
                voice_cfg["voiceprint"],
                users_config=voice_cfg["voiceprint"].get("users"),
            )
        if voice_cfg.get("voice_emotion", {}).get("enabled"):
            self.emotion_detector = VoiceEmotionDetector(voice_cfg["voice_emotion"])

        # 按用户分组的短期历史
        self.history_by_user: dict[str, list[dict]] = {}
        self.turn_idx = 0
        self._pending_persona_switch: Optional[tuple[Persona, Persona]] = None

    async def handle(self, user_msg: str, audio: np.ndarray | None = None,
                     sample_rate: int = 16000) -> str:
        self.turn_idx += 1

        # ---- 1. 声纹识别（可选）----
        user_id = self.default_user_id
        if audio is not None and self.speaker_id is not None:
            identified, conf = self.speaker_id.identify(audio, sample_rate, self.default_user)
            user_id = identified
            # 声纹触发人格切换
            persona_cfg = next(
                (u for u in self.config.get("voice", {}).get("voiceprint", {}).get("users", [])
                 if u.get("id") == user_id),
                None,
            )
            if persona_cfg and self.persona_manager.voiceprint_auto_switch:
                self.persona_manager.on_user_identified(user_id)

        # ---- 2. 检查手动人格切换命令 ----
        persona = self.persona_manager.get_active(user_id)
        target = self.persona_manager.try_match_command(user_msg)
        if target == "listening_mode":
            # 特殊：临时切到 listening 情绪（不是真换人格）
            self.emotion.transition("...")
        elif target and target != persona.id:
            old, persona = self.persona_manager.switch(user_id, target)
            self._pending_persona_switch = (old, persona)

        # ---- 3. 语音情感识别（可选）----
        if audio is not None and self.emotion_detector is not None:
            emo = self.emotion_detector.detect(audio, sample_rate)
            self.emotion.set_voice_signal(emo["emotion"], emo["confidence"])

        # ---- 4. 情绪状态机（融合文本 + 语音）----
        emotion_state = self.emotion.transition(user_msg)
        style_hint = self.emotion.current_style_hint()

        # ---- 5. 话题检测 ----
        topic_info = self.topic.on_new_message(self.turn_idx, user_msg)

        # ---- 6. 短期上下文窗口（按用户分组）----
        user_history = self.history_by_user.setdefault(user_id, [])
        if topic_info["is_new_topic"]:
            effective_history = user_history[-3:]
        else:
            effective_history = user_history[-20:]

        # ---- 7. 长期记忆检索 + 排序（按 user_id 隔离）----
        # Mem0 的 user_id 进一步按 persona 隔离
        memory_user_id = f"{user_id}:{persona.id}" if self.persona_manager else user_id
        candidates = await self.mem0.search(memory_user_id, user_msg, top_k=20)
        ranked = self.ranker.rank(candidates)

        # 新话题时过滤旧话题记忆
        if topic_info["is_new_topic"]:
            cutoff = datetime.now().timestamp() - 6 * 3600
            ranked = [
                m for m in ranked
                if datetime.fromisoformat(m["created_at"]).timestamp() > cutoff
                or float(m.get("importance", 0.5)) >= 0.8
            ]

        # ---- 8. prompt 拼装（使用当前人格的 system_prompt）----
        prompt = self._build_prompt(
            persona=persona,
            emotion_state=emotion_state,
            style_hint=style_hint,
            memories=ranked,
            history=effective_history,
            user_msg=user_msg,
            user_id=user_id,
        )

        # ---- 9. LLM 生成 ----
        reply = await self.llm.generate(prompt)

        # ---- 10. 处理人格切换的问候（如果刚切换过）----
        if self._pending_persona_switch:
            _, new = self._pending_persona_switch
            reply = f"{new.greeting}\n\n{reply}"
            self._pending_persona_switch = None

        # ---- 11. 更新短期历史 ----
        user_history.append({"role": "user", "content": user_msg})
        user_history.append({"role": "assistant", "content": reply})

        if len(user_history) > 40:
            self.history_by_user[user_id] = await self._summarize_history(user_history)

        return reply

    def _build_prompt(self, persona: Persona, emotion_state: str, style_hint: str,
                      memories, history, user_msg: str, user_id: str) -> str:
        mem_text = "\n".join(f"- {m['fact']}" for m in memories) or "（无相关记忆）"

        system = f"""{persona.system_prompt}

[当前对话用户] {user_id}
[当前人格] {persona.name}
[当前情绪模式] {emotion_state}
[风格指引] {style_hint}

[相关长期记忆]
{mem_text}"""

        history_text = "\n".join(
            f"{msg['role']}: {msg['content']}" for msg in history
        )

        return f"""<|system|>
{system}

<|对话历史|>
{history_text}

<|用户最新输入|>
{user_msg}
"""

    def get_tts_speaker_id(self, user_id: str) -> str:
        """供 TTS 模块调用，获取当前用户当前人格的音色"""
        persona = self.persona_manager.get_active(user_id)
        return persona.tts.speaker_id

    async def _summarize_history(self, history: list[dict]) -> list[dict]:
        # 占位：实际实现调用小模型压缩
        return history[-20:]