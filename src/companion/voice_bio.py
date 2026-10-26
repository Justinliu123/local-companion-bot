"""
声纹识别与语音情感识别模块
完整设计见 docs/voice-biometrics.md
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


# ============================================================
# 声纹识别
# ============================================================
@dataclass
class VoiceprintConfig:
    storage: str = "./data/voiceprints/"
    model: str = "resemblyzer"      # 或 "3d_speaker"
    threshold: float = 0.75
    enrollment_samples: int = 3
    enrollment_min_duration_sec: float = 5.0


class SpeakerIdentifier:
    """
    声纹注册 + 识别。
    内部使用 Resemblyzer（轻量、API 简单）。
    """

    def __init__(self, config: dict, users_config: list[dict] | None = None):
        self.config = VoiceprintConfig(**config)
        self._encoder = None
        self._embeddings: dict[str, np.ndarray] = {}
        self._user_meta: dict[str, dict] = {}
        self._load_existing()
        if users_config:
            for u in users_config:
                self._user_meta[u["id"]] = u

    def _ensure_encoder(self):
        if self._encoder is None:
            from resemblyzer import VoiceEncoder
            self._encoder = VoiceEncoder()
        return self._encoder

    def _load_existing(self):
        storage = Path(self.config.storage)
        if not storage.exists():
            return
        for f in storage.glob("*.npy"):
            user_id = f.stem
            self._embeddings[user_id] = np.load(f)

    def _persist(self, user_id: str, embedding: np.ndarray):
        storage = Path(self.config.storage)
        storage.mkdir(parents=True, exist_ok=True)
        np.save(storage / f"{user_id}.npy", embedding)

    def enroll(self, user_id: str, audio_segments: list[np.ndarray],
               sample_rate: int = 16000) -> dict:
        """
        注册新用户的声纹。
        audio_segments: 多段同一人说话的音频。
        返回 {"ok": bool, "reason": "...", "samples_used": N}
        """
        encoder = self._ensure_encoder()
        valid_embeddings = []
        for audio in audio_segments:
            duration = len(audio) / sample_rate
            if duration < self.config.enrollment_min_duration_sec:
                continue
            emb = encoder.embed_utterance(audio)
            valid_embeddings.append(emb)

        if len(valid_embeddings) < self.config.enrollment_samples:
            return {
                "ok": False,
                "reason": (
                    f"只录到 {len(valid_embeddings)} 段有效音频，"
                    f"需要至少 {self.config.enrollment_samples} 段"
                ),
                "samples_used": len(valid_embeddings),
            }

        avg_embedding = np.mean(valid_embeddings, axis=0)
        avg_embedding = avg_embedding / np.linalg.norm(avg_embedding)

        self._embeddings[user_id] = avg_embedding
        self._persist(user_id, avg_embedding)
        return {"ok": True, "samples_used": len(valid_embeddings)}

    def identify(self, audio: np.ndarray, sample_rate: int = 16000,
                 default_user: str = "default_user") -> tuple[str, float]:
        """
        识别说话人。返回 (user_id, confidence)。
        未识别出时返回 (default_user, 0.0)。
        """
        if not self._embeddings:
            return default_user, 0.0

        encoder = self._ensure_encoder()
        emb = encoder.embed_utterance(audio)
        emb = emb / np.linalg.norm(emb)

        best_id = default_user
        best_sim = -1.0
        for user_id, ref_emb in self._embeddings.items():
            ref_norm = ref_emb / np.linalg.norm(ref_emb)
            sim = float(np.dot(emb, ref_norm))
            if sim > best_sim:
                best_sim = sim
                best_id = user_id

        if best_sim >= self.config.threshold:
            return best_id, best_sim
        return default_user, best_sim

    def delete(self, user_id: str) -> bool:
        """删除某用户的声纹，包括磁盘文件"""
        if user_id in self._embeddings:
            del self._embeddings[user_id]
            f = Path(self.config.storage) / f"{user_id}.npy"
            if f.exists():
                f.unlink()
            return True
        return False

    def list_users(self) -> list[str]:
        return list(self._embeddings.keys())


# ============================================================
# 语音情感识别
# ============================================================
@dataclass
class VoiceEmotionConfig:
    model: str = "iic/emotion2vec_base"
    device: str = "cpu"
    confidence_threshold: float = 0.5
    cache_seconds: float = 5.0


# emotion2vec_base 输出标签（7 类）
VOICE_EMOTION_LABELS = ["angry", "happy", "neutral", "sad", "surprised", "fear", "disgust"]
VOICE_EMOTION_LABELS_CN = {
    "angry": "生气",
    "happy": "开心",
    "neutral": "平静",
    "sad": "难过",
    "surprised": "惊讶",
    "fear": "害怕",
    "disgust": "厌恶",
}

# 语音情感 → 情绪状态机状态
VOICE_EMOTION_TO_STATE = {
    "angry": "caring",
    "happy": "playful",
    "neutral": "neutral",
    "sad": "caring",
    "surprised": "neutral",
    "fear": "caring",
    "disgust": "caring",
}


class VoiceEmotionDetector:
    """
    语音情感分类。
    使用 emotion2vec_base（ModelScope 出品，中文 SOTA）。
    """

    def __init__(self, config: dict):
        self.config = VoiceEmotionConfig(**config)
        self._model = None
        self._processor = None
        self._last_result: Optional[dict] = None
        self._last_at: float = 0

    def _ensure_model(self):
        if self._model is None:
            from transformers import AutoModelForAudioClassification, AutoFeatureExtractor
            self._model = AutoModelForAudioClassification.from_pretrained(self.config.model)
            self._processor = AutoFeatureExtractor.from_pretrained(self.config.model)
            if self.config.device == "cuda":
                self._model = self._model.cuda()
            self._model.eval()
        return self._model, self._processor

    def detect(self, audio: np.ndarray, sample_rate: int = 16000) -> dict:
        """
        检测音频情感。
        返回 {"emotion": str, "confidence": float, "all_scores": dict}
        """
        # 简易缓存：相同时间窗口内的重复调用直接返回上次结果
        now = time.time()
        if self._last_result and (now - self._last_at) < self.config.cache_seconds:
            return self._last_result

        model, processor = self._ensure_model()

        import torch
        max_len = 8 * sample_rate
        if len(audio) > max_len:
            audio = audio[:max_len]

        inputs = processor(
            audio,
            sampling_rate=sample_rate,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=max_len,
        )
        if self.config.device == "cuda":
            inputs = {k: v.cuda() for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)
        logits = outputs.logits[0]
        probs = torch.softmax(logits, dim=-1).cpu().numpy()

        all_scores = {
            VOICE_EMOTION_LABELS[i]: float(probs[i])
            for i in range(min(len(probs), len(VOICE_EMOTION_LABELS)))
        }
        top_idx = int(np.argmax(probs))
        top_emotion = VOICE_EMOTION_LABELS[top_idx]
        top_confidence = float(probs[top_idx])

        result = {
            "emotion": top_emotion,
            "emotion_cn": VOICE_EMOTION_LABELS_CN.get(top_emotion, top_emotion),
            "confidence": top_confidence,
            "all_scores": all_scores,
        }

        self._last_result = result
        self._last_at = now
        return result