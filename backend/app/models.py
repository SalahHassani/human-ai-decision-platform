import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import AsyncGenerator, Optional

from sqlalchemy import (
    UUID,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)

import sys
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.pool import NullPool

raw_database_url = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@db:5432/experiment_db",
)
if raw_database_url.startswith("postgres://"):
    DATABASE_URL = "postgresql+asyncpg://" + raw_database_url[len("postgres://") :]
elif raw_database_url.startswith("postgresql://"):
    DATABASE_URL = "postgresql+asyncpg://" + raw_database_url[len("postgresql://") :]
else:
    DATABASE_URL = raw_database_url

_engine_kwargs = {"echo": False, "future": True}
if "pytest" in sys.modules or os.getenv("TESTING") == "1":
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_discussion_context() -> dict:
    return {
        "introduced_arguments": [],
        "asked_questions": [],
        "participant_positions": {},
        "used_strategies": [],
    }


class ExperimentPhase(str, Enum):
    WAITING = "WAITING"
    ROUND_1_DISCUSSION = "ROUND_1_DISCUSSION"
    ROUND_1_VOTING = "ROUND_1_VOTING"
    ROUND_2_DISCUSSION = "ROUND_2_DISCUSSION"
    ROUND_2_VOTING = "ROUND_2_VOTING"
    COMPLETED = "COMPLETED"


class Base(DeclarativeBase):
    pass


class ExperimentSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    condition: Mapped[str] = mapped_column(String(64), nullable=False)
    phase: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ExperimentPhase.WAITING.value,
    )
    selected_topic_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="remote_work_policy",
    )
    topic_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discussion_context_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=default_discussion_context,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    round_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    round_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    participants: Mapped[list["Participant"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (
        UniqueConstraint("session_id", "slot_id", name="uq_participant_session_slot"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    slot_id: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Internal server-only fields (never exposed in public DTOs or WebSocket events)
    participant_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "human" | "ai"
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    personality: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    token_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["ExperimentSession"] = relationship(back_populates="participants")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_session_round_created", "session_id", "round_number", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional internal audit metadata for research logging (never exposed publicly)
    audit_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("session_id", "voter_id", "round_number", name="uq_vote_session_voter_round"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    voter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ExperimentResult(Base):
    __tablename__ = "results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    totals_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    round_1_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    round_2_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    decision_maker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            await conn.execute(
                text(
                    "ALTER TABLE sessions "
                    "ADD COLUMN IF NOT EXISTS selected_topic_id VARCHAR(64) NOT NULL DEFAULT 'remote_work_policy'"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE sessions "
                    "ADD COLUMN IF NOT EXISTS topic_locked BOOLEAN NOT NULL DEFAULT TRUE"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE sessions "
                    "ADD COLUMN IF NOT EXISTS discussion_context_json JSON NOT NULL DEFAULT '{}'::json"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE participants "
                    "ADD COLUMN IF NOT EXISTS personality VARCHAR(32)"
                )
            )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session