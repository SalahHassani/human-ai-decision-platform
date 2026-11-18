from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


SLOT_DISPLAY_NAMES = {
    "player_a": "Player A",
    "player_b": "Player B",
    "player_c": "Player C",
}


class CreateSessionRequest(BaseModel):
    condition_key: Optional[str] = Field(
        default=None,
        description="Optional override for condition_1, condition_2, or condition_3.",
    )


class ParticipantPublic(BaseModel):
    """Strict public representation of a participant. Never includes participant_type."""

    id: str  # Neutral slot ID: player_a | player_b | player_c
    display_name: str  # Player A | Player B | Player C
    is_connected: bool


class SessionStateResponse(BaseModel):
    session_id: UUID
    condition_key: str
    phase: str
    current_round: Optional[int] = None
    discussion_duration_seconds: int
    round_started_at: Optional[datetime] = None
    round_ends_at: Optional[datetime] = None
    participants: list[ParticipantPublic]
    required_humans: int
    joined_humans: int


class JoinSessionResponse(BaseModel):
    session_id: UUID
    participant: ParticipantPublic
    participant_token: str
    session_state: SessionStateResponse