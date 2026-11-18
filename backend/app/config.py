import os
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class ParticipantSlotConfig(BaseModel):
    id: Literal["player_a", "player_b", "player_c"]
    type: Literal["human", "ai"]
    provider: Optional[str] = "rule_based"
    model: Optional[str] = None

    @model_validator(mode="after")
    def validate_provider_for_type(self) -> "ParticipantSlotConfig":
        if self.type == "human":
            self.provider = None
            self.model = None
        elif not self.provider:
            self.provider = "rule_based"
        return self


class ConditionConfig(BaseModel):
    name: str
    participants: list[ParticipantSlotConfig]

    @model_validator(mode="after")
    def validate_three_unique_slots(self) -> "ConditionConfig":
        if len(self.participants) != 3:
            raise ValueError("Each condition must define exactly 3 participants.")
        slot_ids = [p.id for p in self.participants]
        if len(set(slot_ids)) != 3:
            raise ValueError("Participant slot IDs must be unique (player_a, player_b, player_c).")
        return self


class ExperimentSettings(BaseModel):
    rounds: int = Field(default=2, ge=2, le=2)
    discussion_duration_seconds: int = Field(default=60, gt=0)


class AISettings(BaseModel):
    min_response_delay_seconds: float = Field(default=4.0, ge=0.0)
    max_response_delay_seconds: float = Field(default=14.0, ge=0.0)
    max_messages_per_round: int = Field(default=2, ge=1, le=5)

    @model_validator(mode="after")
    def validate_delays(self) -> "AISettings":
        if self.min_response_delay_seconds > self.max_response_delay_seconds:
            raise ValueError("min_response_delay_seconds cannot exceed max_response_delay_seconds.")
        return self


class VotingSettings(BaseModel):
    allow_self_vote: bool = False
    tie_break: list[str] = ["round_2_votes", "alphabetical_order"]

class RootConfig(BaseModel):
    experiment: ExperimentSettings
    conditions: dict[str, ConditionConfig]
    ai: AISettings = Field(default_factory=AISettings)
    voting: VotingSettings = Field(default_factory=VotingSettings)


class ActiveExperimentConfig(BaseModel):
    condition_key: str
    condition: ConditionConfig
    experiment: ExperimentSettings
    ai: AISettings
    voting: VotingSettings
    admin_token: str = Field(default_factory=lambda: os.getenv("ADMIN_TOKEN", "dev-admin-token"))
    demo_mode: bool = Field(
        default_factory=lambda: os.getenv("DEMO_MODE", "true").strip().lower() in ("1", "true", "yes")
    )


def load_active_config(
    config_path: Optional[str] = None,
    condition_key: Optional[str] = None,
) -> ActiveExperimentConfig:
    path = Path(config_path or os.getenv("CONFIG_PATH", "config.yml"))
    if not path.exists():
        fallback = Path(__file__).resolve().parents[2] / "config.yml"
        if fallback.exists():
            path = fallback
        else:
            raise FileNotFoundError(f"Configuration file not found at: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f) or {}

    parsed = RootConfig.model_validate(raw_data)
    selected_key = condition_key or os.getenv("EXPERIMENT_CONDITION", "condition_2")

    if selected_key not in parsed.conditions:
        available = ", ".join(parsed.conditions.keys())
        raise ValueError(
            f"Invalid EXPERIMENT_CONDITION '{selected_key}'. Available conditions: {available}"
        )

    return ActiveExperimentConfig(
        condition_key=selected_key,
        condition=parsed.conditions[selected_key],
        experiment=parsed.experiment,
        ai=parsed.ai,
        voting=parsed.voting,
    )


    