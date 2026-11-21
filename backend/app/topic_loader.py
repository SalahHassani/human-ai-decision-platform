from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class TopicLoadError(ValueError):
    """Raised when a requested discussion topic does not exist or cannot be loaded."""


class EngineSettings(BaseModel):
    type: str = "rule_based"
    enabled: bool = True
    version: str = "1.0.0"

    @field_validator("type")
    @classmethod
    def must_be_rule_based(cls, v: str) -> str:
        if v != "rule_based":
            raise ValueError("Only 'rule_based' engine type is permitted in this phase.")
        return v


class SessionLockSettings(BaseModel):
    enforce_topic_lock: bool = True
    one_topic_per_session: bool = True
    topic_immutable_after_selection: bool = True
    shared_topic_between_participants: bool = True
    allow_ai_topic_selection: bool = False
    allow_topic_fallback: bool = False
    allow_cross_topic_content: bool = False


class DiscussionEngineSettings(BaseModel):
    rounds: int = Field(default=2, ge=1)
    discussion_duration_seconds: int = Field(default=60, ge=5)
    max_messages_per_ai_per_round: int = Field(default=2, ge=1, le=5)
    min_response_words: int = Field(default=12, ge=4)
    max_response_words: int = Field(default=75, ge=20)
    context_aware: bool = True
    avoid_repeated_questions: bool = True
    avoid_duplicate_arguments: bool = True
    allow_agreement: bool = True
    allow_disagreement: bool = True
    allow_follow_up_questions: bool = True
    allow_compromise: bool = True
    allow_argument_development: bool = True
    reference_previous_round: bool = True


class ArgumentSelectionSettings(BaseModel):
    use_stable_argument_ids: bool = True
    prevent_duplicate_introductions: bool = True
    allow_discussion_of_existing_arguments: bool = True
    allow_agreement_with_existing_arguments: bool = True
    allow_disagreement_with_existing_arguments: bool = True
    prefer_unused_arguments: bool = True
    check_topic_relevance: bool = True


class QuestionSelectionSettings(BaseModel):
    use_stable_question_ids: bool = True
    prevent_duplicate_questions: bool = True
    prevent_repeating_main_question: bool = True
    allow_answering_existing_questions: bool = True


class PersonalityProfile(BaseModel):
    description: str
    preferred_strategies: List[str] = Field(min_length=1)
    argument_preferences: List[str] = Field(default_factory=list)
    communication_style: List[str] = Field(default_factory=list)


class RoundBehaviorConfig(BaseModel):
    name: str
    objective: str
    preferred_strategies: List[str] = Field(default_factory=list)
    must_reference_previous_round: bool = False
    avoid: List[str] = Field(default_factory=list)


class ValidationSettings(BaseModel):
    validate_topic_id: bool = True
    validate_argument_ids: bool = True
    validate_question_ids: bool = True
    validate_response_length: bool = True
    validate_topic_relevance: bool = True
    reject_cross_topic_content: bool = True
    reject_invalid_strategy: bool = True


class TopicOption(BaseModel):
    id: str
    label: str


class TopicArgument(BaseModel):
    argument_id: str
    category: str
    idea: str
    related_options: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    variations: List[str] = Field(min_length=1)


class TopicQuestion(BaseModel):
    question_id: str
    category: str
    text: str


class TopicCompromise(BaseModel):
    compromise_id: str
    idea: str
    variations: List[str] = Field(min_length=1)


class TopicRoundPlan(BaseModel):
    objective: str
    preferred_argument_categories: List[str] = Field(default_factory=list)
    strategies: List[str] = Field(default_factory=list)


class TopicScenario(BaseModel):
    topic_id: str
    title: str
    description: str
    main_question: str
    options: List[TopicOption] = Field(min_length=2)
    arguments: List[TopicArgument] = Field(min_length=1)
    questions: List[TopicQuestion] = Field(min_length=1)
    compromises: List[TopicCompromise] = Field(default_factory=list)
    round_1: TopicRoundPlan
    round_2: TopicRoundPlan


class GlobalAIConfig(BaseModel):
    engine: EngineSettings = Field(default_factory=EngineSettings)
    session: SessionLockSettings = Field(default_factory=SessionLockSettings)
    discussion: DiscussionEngineSettings = Field(default_factory=DiscussionEngineSettings)
    argument_selection: ArgumentSelectionSettings = Field(default_factory=ArgumentSelectionSettings)
    question_selection: QuestionSelectionSettings = Field(default_factory=QuestionSelectionSettings)
    personalities: Dict[str, PersonalityProfile]
    round_behavior: Dict[str, RoundBehaviorConfig]
    strategies: Dict[str, str]
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    topics: Dict[str, TopicScenario] = Field(min_length=1)

    @field_validator("topics")
    @classmethod
    def check_topic_id_alignment(cls, topics: Dict[str, TopicScenario]) -> Dict[str, TopicScenario]:
        for key, scenario in topics.items():
            if key != scenario.topic_id:
                raise ValueError(
                    f"Topic map key '{key}' does not match scenario.topic_id '{scenario.topic_id}'."
                )
        return topics


def _resolve_ai_config_path() -> Path:
    env_path = os.getenv("AI_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    candidates = [
        Path("/app/config/ai_config.json"),
        Path(__file__).resolve().parents[2] / "config" / "ai_config.json",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


@lru_cache(maxsize=1)
def get_ai_config() -> GlobalAIConfig:
    config_path = _resolve_ai_config_path()
    if not config_path.exists():
        raise TopicLoadError(f"AI configuration file not found at '{config_path}'.")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return GlobalAIConfig.model_validate(raw)


class TopicLoader:
    """Strict, deterministic topic loader with zero fallback or random topic selection."""

    DEFAULT_TOPIC_ID = "remote_work_policy"

    @classmethod
    def list_topics(cls) -> List[TopicScenario]:
        cfg = get_ai_config()
        return list(cfg.topics.values())

    @classmethod
    def validate_topic_id(cls, topic_id: Optional[str]) -> str:
        if not topic_id or not isinstance(topic_id, str):
            raise TopicLoadError("A valid selected_topic_id is required.")
        cfg = get_ai_config()
        if topic_id not in cfg.topics:
            raise TopicLoadError(
                f"Unknown or invalid topic_id '{topic_id}'. Topic fallback is disabled."
            )
        return topic_id

    @classmethod
    def load_topic(cls, topic_id: Optional[str]) -> TopicScenario:
        """Load the exact scenario matching topic_id. Never falls back to another topic."""
        valid_id = cls.validate_topic_id(topic_id)
        cfg = get_ai_config()
        return cfg.topics[valid_id]