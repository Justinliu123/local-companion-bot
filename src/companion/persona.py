"""
多人格系统
完整设计见 docs/persona-system.md
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PersonaTTSConfig:
    speaker_id: str = "default"
    speed: float = 1.0
    pitch: float = 1.0


@dataclass
class PersonaProactiveConfig:
    enabled: bool = True
    morning_greet: bool = False
    weekend_care: bool = False


@dataclass
class Persona:
    """单个人格定义"""
    id: str
    name: str
    description: str
    system_prompt: str
    traits: list[str] = field(default_factory=list)
    greeting: str = "你好。"
    farewell: str = "再见。"
    avatar: Optional[str] = None
    tts: PersonaTTSConfig = field(default_factory=PersonaTTSConfig)
    proactive: PersonaProactiveConfig = field(default_factory=PersonaProactiveConfig)
    is_default: bool = False

    @classmethod
    def from_config(cls, cfg: dict) -> "Persona":
        return cls(
            id=cfg["id"],
            name=cfg["name"],
            description=cfg.get("description", ""),
            system_prompt=cfg["system_prompt"],
            traits=cfg.get("traits", []),
            greeting=cfg.get("greeting", "你好。"),
            farewell=cfg.get("farewell", "再见。"),
            avatar=cfg.get("avatar"),
            tts=PersonaTTSConfig(**cfg.get("tts", {})),
            proactive=PersonaProactiveConfig(**cfg.get("proactive", {})),
            is_default=cfg.get("is_default", False),
        )


class PersonaManager:
    """
    管理多个人格，处理切换逻辑。
    支持：
      - 手动命令切换
      - 声纹识别自动加载
      - 时间表自动切换（外部 cron 调用）
    """

    def __init__(self, personas_config: list[dict], switching_config: dict | None = None):
        self.personas: dict[str, Persona] = {
            p["id"]: Persona.from_config(p) for p in personas_config
        }
        if not self.personas:
            raise ValueError("personas config is empty")

        # 默认人格
        defaults = [p for p in self.personas.values() if p.is_default]
        self.default_persona_id = (
            defaults[0].id if defaults else next(iter(self.personas.keys()))
        )

        # 切换配置
        switching = switching_config or {}
        self.manual_commands: dict[str, str] = switching.get("manual_commands", {})
        self.voiceprint_auto_switch = switching.get("voiceprint_auto_switch", True)

        # 每个用户当前激活的人格
        self.active_by_user: dict[str, str] = {}

    # ---- 查询 ----

    def get_active(self, user_id: str) -> Persona:
        persona_id = self.active_by_user.get(user_id, self.default_persona_id)
        return self.personas[persona_id]

    def get_default(self) -> Persona:
        return self.personas[self.default_persona_id]

    def list_personas(self) -> list[Persona]:
        return list(self.personas.values())

    def get_user_persona_id(self, user_id: str) -> str:
        return self.active_by_user.get(user_id, self.default_persona_id)

    # ---- 切换 ----

    def switch(self, user_id: str, persona_id: str) -> tuple[Persona, Persona]:
        """
        切换用户到指定人格。
        返回 (old_persona, new_persona)，供调用方播报切换问候。
        """
        if persona_id not in self.personas:
            raise ValueError(f"Unknown persona: {persona_id}")

        old = self.get_active(user_id)
        self.active_by_user[user_id] = persona_id
        return old, self.personas[persona_id]

    def switch_to_default(self, user_id: str) -> tuple[Persona, Persona]:
        return self.switch(user_id, self.default_persona_id)

    # ---- 声纹联动 ----

    def on_user_identified(self, user_id: str, persona_id: Optional[str] = None) -> Persona:
        """
        声纹识别到用户时调用。
        - 如果已知该用户当前人格 → 不变
        - 如果传入 persona_id → 切换（声纹绑定特定人格）
        - 否则 → 用默认
        """
        if user_id in self.active_by_user and not persona_id:
            return self.get_active(user_id)

        target = persona_id or self.default_persona_id
        self.active_by_user[user_id] = target
        return self.personas[target]

    # ---- 命令匹配 ----

    def try_match_command(self, text: str) -> Optional[str]:
        """
        检查用户输入是否包含人格切换命令。
        返回目标 persona_id 或 None。
        """
        for cmd, persona_id in self.manual_commands.items():
            if cmd in text:
                if persona_id in self.personas or persona_id == "listening_mode":
                    return persona_id
        return None

    # ---- 维护 ----

    def clear_user(self, user_id: str):
        """用户离开时清空状态"""
        self.active_by_user.pop(user_id, None)