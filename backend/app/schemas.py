from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


SLOT_DISPLAY_NAMES = {
    "player_a": "Player A",
    "player_b": "Player B",
    "player_c": "Player C",
}


class TopicOptionPublic(BaseModel):
    id: str
    label: str


class TopicSummaryPublic(BaseModel):
    topic_id: str
    title: str
    description: str
    main_question: str
    options: list[TopicOptionPublic] = Field(default_factory=list)


class CreateSessionRequest(BaseModel):
    condition_key: Optional[str] = Field(
        default=None,
        description="Optional override for condition_1, condition_2, or condition_3.",
    )
    topic_id: Optional[str] = Field(
        default=None,
        description="Immutable scenario topic_id locked for the lifetime of this session.",
    )


class UpdateTopicRequest(BaseModel):
    topic_id: str


class ParticipantPublic(BaseModel):
    """Strict public representation of a participant. Never includes participant_type or personality."""

    id: str  # Neutral slot ID: player_a | player_b | player_c
    display_name: str  # Player A | Player B | Player C
    is_connected: bool


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)

    @field_validator("content")
    @classmethod
    def strip_and_require_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Message content cannot be empty or whitespace.")
        return cleaned


class MessagePublic(BaseModel):
    """Public message DTO using neutral slot identity only."""

    id: UUID
    sender_id: str  # player_a | player_b | player_c
    sender_name: str  # Player A | Player B | Player C
    round_number: int
    content: str
    created_at: datetime


class SubmitVoteRequest(BaseModel):
    target_id: Literal["player_a", "player_b", "player_c"]


class VoteStatusPublic(BaseModel):
    """Intermediate voting status: reveals who submitted, never whom they voted for."""

    round_number: int
    submitted_participant_ids: list[str]
    votes_received: int
    total_required: int = 3


class ExperimentResultPublic(BaseModel):
    session_id: UUID
    totals_by_participant: dict[str, int]
    round_1_totals: dict[str, int]
    round_2_totals: dict[str, int]
    decision_maker_id: str  # player_a | player_b | player_c
    decision_maker_name: str  # Player A | Player B | Player C
    completed_at: datetime


class SessionStateResponse(BaseModel):
    session_id: UUID
    condition_key: str
    selected_topic_id: str
    topic_locked: bool
    selected_topic: TopicSummaryPublic
    phase: str
    current_round: Optional[int] = None
    discussion_duration_seconds: int
    round_started_at: Optional[datetime] = None
    round_ends_at: Optional[datetime] = None
    participants: list[ParticipantPublic]
    required_humans: int
    joined_humans: int
    messages: list[MessagePublic] = Field(default_factory=list)
    vote_status: Optional[VoteStatusPublic] = None
    result: Optional[ExperimentResultPublic] = None


class JoinSessionResponse(BaseModel):
    session_id: UUID
    participant: ParticipantPublic
    participant_token: str
    session_state: SessionStateResponse