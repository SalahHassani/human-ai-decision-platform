from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class ParticipantSlotConfig(BaseModel):
    id: Literal["player_a", "player_b", "player_c"]
    type: Literal["human", "ai"]
    provider: Optional[str] = None
    model: Optional[str] = None


class ConditionConfig(BaseModel):
    name: str
    label: Optional[str] = None
    participants: List[ParticipantSlotConfig]

    @model_validator(mode="after")
    def validate_participants(self) -> "ConditionConfig":
        if not self.label:
            self.label = self.name
        if len(self.participants) != 3:
            raise ValueError(f"Condition '{self.name}' must define exactly 3 participants.")
        ids = {p.id for p in self.participants}
        if ids != {"player_a", "player_b", "player_c"}:
            raise ValueError(
                f"Condition '{self.name}' must define player_a, player_b, and player_c."
            )
        return self


class ExperimentSettings(BaseModel):
    rounds: int = Field(default=2, ge=1, le=5)
    discussion_duration_seconds: int = Field(default=60, ge=5, le=600)
    total_participants: int = Field(default=3)
    slot_ids: List[str] = Field(default=["player_a", "player_b", "player_c"])
    display_names: Dict[str, str] = Field(
        default={
            "player_a": "Player A",
            "player_b": "Player B",
            "player_c": "Player C",
        }
    )


class AIParticipantProfile(BaseModel):
    enabled: bool = True
    provider: str = "gemini"
    model: str = "gemini-2.5-flash"
    api_key_env: str = "AI_1_API_KEY"
    personality: str = "analytical"

    def resolve_api_key(self) -> str:
        return os.getenv(self.api_key_env, "").strip()


class AIFallbackSettings(BaseModel):
    enabled: bool = True
    engine: str = "rule_based"
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    retry_attempts: int = Field(default=0, ge=0, le=2)
    switch_for_remainder_of_session: bool = True


class AISettings(BaseModel):
    enabled: bool = True
    real_ai: bool = False
    provider: str = "rule_based"
    model: Optional[str] = "deterministic-v1"
    min_response_delay_seconds: float = Field(default=4.0, ge=0.0)
    max_response_delay_seconds: float = Field(default=14.0, ge=0.0)
    max_messages_per_round: int = Field(default=2, ge=1, le=5)
    participants: Dict[str, AIParticipantProfile] = Field(
        default_factory=lambda: {
            "ai_1": AIParticipantProfile(
                provider="gemini",
                model="gemini-2.5-flash",
                api_key_env="AI_1_API_KEY",
                personality="analytical",
            ),
            "ai_2": AIParticipantProfile(
                provider="openai",
                model="gpt-4o-mini",
                api_key_env="AI_2_API_KEY",
                personality="cooperative",
            ),
        }
    )
    fallback: AIFallbackSettings = Field(default_factory=AIFallbackSettings)

    @model_validator(mode="after")
    def validate_delays(self) -> "AISettings":
        if self.max_response_delay_seconds < self.min_response_delay_seconds:
            raise ValueError("max_response_delay_seconds must be >= min_response_delay_seconds.")
        return self


class VotingSettings(BaseModel):
    allow_self_vote: bool = False
    tie_break: List[Literal["round_2_votes", "alphabetical_order"]] = Field(
        default=["round_2_votes", "alphabetical_order"]
    )


class ServerSettings(BaseModel):
    default_condition: str = "condition_2"
    demo_mode: bool = True


class ActiveExperimentConfig(BaseModel):
    experiment: ExperimentSettings = Field(default_factory=ExperimentSettings)
    conditions: Dict[str, ConditionConfig]
    ai: AISettings = Field(default_factory=AISettings)
    voting: VotingSettings = Field(default_factory=VotingSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    condition_key: str = "condition_2"
    admin_token: str = "dev-admin-token"

    @property
    def active_condition_key(self) -> str:
        return self.condition_key

    @property
    def demo_mode(self) -> bool:
        return self.server.demo_mode

    @property
    def condition(self) -> ConditionConfig:
        if self.condition_key not in self.conditions:
            raise ValueError(f"Unknown condition '{self.condition_key}'.")
        return self.conditions[self.condition_key]


# Alias for compatibility
AppConfig = ActiveExperimentConfig


def _parse_bool_env(val: Optional[str]) -> Optional[bool]:
    if val is None:
        return None
    norm = val.strip().lower()
    if norm in {"1", "true", "yes", "on"}:
        return True
    if norm in {"0", "false", "no", "off"}:
        return False
    return None


def _resolve_config_path() -> Path:
    env_path = os.getenv("CONFIG_PATH")
    if env_path and Path(env_path).exists():
        return Path(env_path)
    repo_root_candidate = Path(__file__).resolve().parents[2] / "config.yml"
    if repo_root_candidate.exists():
        return repo_root_candidate
    local_candidate = Path("config.yml")
    if local_candidate.exists():
        return local_candidate
    raise FileNotFoundError("Could not locate config.yml.")


def load_active_config(condition_key: Optional[str] = None) -> ActiveExperimentConfig:
    cfg_path = _resolve_config_path()
    with cfg_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    cfg = ActiveExperimentConfig(**raw)

    chosen_condition = (
        condition_key
        or os.getenv("EXPERIMENT_CONDITION")
        or cfg.server.default_condition
    )
    if chosen_condition not in cfg.conditions:
        raise ValueError(
            f"Invalid condition '{chosen_condition}'. Available: {list(cfg.conditions.keys())}"
        )
    cfg.condition_key = chosen_condition

    env_demo = os.getenv("DEMO_MODE")
    if env_demo is not None:
        cfg.server.demo_mode = env_demo.strip().lower() in {"1", "true", "yes", "on"}

    env_admin = os.getenv("ADMIN_TOKEN")
    if env_admin:
        cfg.admin_token = env_admin.strip()

    env_real_ai = _parse_bool_env(os.getenv("REAL_AI"))
    if env_real_ai is not None:
        cfg.ai.real_ai = env_real_ai

    for idx, key in enumerate(("ai_1", "ai_2"), start=1):
        profile = cfg.ai.participants.setdefault(
            key,
            AIParticipantProfile(
                api_key_env=f"AI_{idx}_API_KEY",
                personality="analytical" if idx == 1 else "cooperative",
            ),
        )
        p_env = os.getenv(f"AI_{idx}_PROVIDER")
        m_env = os.getenv(f"AI_{idx}_MODEL")
        if p_env and p_env.strip():
            profile.provider = p_env.strip().lower()
        if m_env and m_env.strip():
            profile.model = m_env.strip()

    return cfg