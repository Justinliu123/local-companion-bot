"""
记忆评分与重排序
完整设计见 docs/companion-features.md §4
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RankingConfig:
    weights: dict = field(default_factory=lambda: {"recency": 0.4, "importance": 0.4, "access": 0.2})
    recency: dict = field(default_factory=lambda: {"half_life_days": 60, "decay_floor": 0.2})
    access: dict = field(default_factory=lambda: {"log_base": 10, "cap": 1.0})
    inject_top_k: int = 5
    importance_threshold: float = 0.3


class MemoryRanker:
    """
    给每条记忆算综合分：freshness + importance + access。
    按分数降序取 top-k，注入 prompt。
    """

    def __init__(self, config: dict):
        self.config = RankingConfig(**config)

    def score(self, memory: dict) -> float:
        w = self.config.weights

        # recency
        created = memory.get("created_at")
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        elif created is None:
            created = datetime.now()
        age_days = (datetime.now() - created).days
        recency = max(
            self.config.recency["decay_floor"],
            0.5 ** (age_days / self.config.recency["half_life_days"]),
        )

        # importance
        importance = float(memory.get("importance", 0.5))

        # access
        access_count = int(memory.get("access_count", 0))
        access = min(
            self.config.access["cap"],
            math.log(1 + access_count) / math.log(self.config.access["log_base"]),
        )

        return w["recency"] * recency + w["importance"] * importance + w["access"] * access

    def rank(self, memories: list[dict]) -> list[dict]:
        scored = [(m, self.score(m)) for m in memories]
        scored.sort(key=lambda x: x[1], reverse=True)

        threshold = self.config.importance_threshold
        filtered = [
            m for m, _ in scored
            if float(m.get("importance", 0.5)) >= threshold
        ]
        return filtered[: self.config.inject_top_k]