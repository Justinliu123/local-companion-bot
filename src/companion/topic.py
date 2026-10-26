"""
话题切换检测
完整设计见 docs/companion-features.md §3
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class TopicConfig:
    embedding_model: str = "shibing624/text2vec-base-chinese-paraphrase"
    embedding_device: str = "cpu"
    new_topic_threshold: float = 0.45
    same_topic_threshold: float = 0.70
    transition_window: int = 3


class TopicTracker:
    """
    通过 sentence embedding 余弦相似度检测话题切换。
    """

    def __init__(self, config: dict):
        self.config = TopicConfig(**config)
        self._model = None
        self.history: list[tuple[int, np.ndarray]] = []
        self.current_topic_started_at: int = 0

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.config.embedding_model)
        return self._model

    def _embed(self, text: str) -> np.ndarray:
        model = self._ensure_model()
        return model.encode(text, normalize_embeddings=True)

    def _cosine(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))

    def on_new_message(self, turn_idx: int, text: str) -> dict:
        emb = self._embed(text)

        if not self.history:
            self.history = [(turn_idx, emb)]
            self.current_topic_started_at = turn_idx
            return {"is_new_topic": True, "similarity": 0.0}

        last_turn_idx, last_emb = self.history[-1]
        sim = self._cosine(emb, last_emb)

        if sim < self.config.new_topic_threshold:
            # 新话题
            self.history = [(turn_idx, emb)]
            self.current_topic_started_at = turn_idx
            return {"is_new_topic": True, "similarity": sim}

        self.history.append((turn_idx, emb))
        return {
            "is_new_topic": False,
            "similarity": sim,
            "in_transition": sim < self.config.same_topic_threshold,
        }