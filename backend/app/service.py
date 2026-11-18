import asyncio
import hashlib
import secrets
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ActiveExperimentConfig, load_active_config
from app.models import ExperimentPhase, ExperimentSession, Participant, utc_now
from app.schemas import (
    JoinSessionResponse,
    ParticipantPublic,
    SLOT_DISPLAY_NAMES,
    SessionStateResponse,
)


class ExperimentService:
    """Core session lifecycle, slot assignment, token auth, and state coordination."""

    _session_locks: dict[UUID, asyncio.Lock] = {}

    @classmethod
    def get_session_lock(cls, session_id: UUID) -> asyncio.Lock:
        if session_id not in cls._session_locks:
            cls._session_locks[session_id] = asyncio.Lock()
        return cls._session_locks[session_id]

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _current_round(phase: str) -> Optional[int]:
        if phase in (ExperimentPhase.ROUND_1_DISCUSSION.value, ExperimentPhase.ROUND_1_VOTING.value):
            return 1
        if phase in (ExperimentPhase.ROUND_2_DISCUSSION.value, ExperimentPhase.ROUND_2_VOTING.value):
            return 2
        return None

    @staticmethod
    def _to_public_participant(p: Participant) -> ParticipantPublic:
        return ParticipantPublic(
            id=p.slot_id,
            display_name=p.display_name,
            is_connected=p.is_connected,
        )

    @classmethod
    def build_session_state(
        cls,
        session: ExperimentSession,
        cfg: ActiveExperimentConfig,
    ) -> SessionStateResponse:
        ordered_participants = sorted(session.participants, key=lambda p: p.slot_id)
        required_humans = sum(1 for p in ordered_participants if p.participant_type == "human")
        joined_humans = sum(
            1
            for p in ordered_participants
            if p.participant_type == "human" and p.token_hash is not None
        )
        return SessionStateResponse(
            session_id=session.id,
            condition_key=session.condition,
            phase=session.phase,
            current_round=cls._current_round(session.phase),
            discussion_duration_seconds=cfg.experiment.discussion_duration_seconds,
            round_started_at=session.round_started_at,
            round_ends_at=session.round_ends_at,
            participants=[cls._to_public_participant(p) for p in ordered_participants],
            required_humans=required_humans,
            joined_humans=joined_humans,
        )

    @classmethod
    async def create_session(
        cls,
        db: AsyncSession,
        default_cfg: ActiveExperimentConfig,
        condition_key: Optional[str] = None,
    ) -> ExperimentSession:
        try:
            cfg = (
                load_active_config(condition_key=condition_key)
                if condition_key
                else default_cfg
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        now = utc_now()
        session = ExperimentSession(
            condition=cfg.condition_key,
            phase=ExperimentPhase.WAITING.value,
            created_at=now,
        )
        db.add(session)
        await db.flush()

        for slot in cfg.condition.participants:
            is_ai = slot.type == "ai"
            participant = Participant(
                session_id=session.id,
                slot_id=slot.id,
                display_name=SLOT_DISPLAY_NAMES[slot.id],
                participant_type=slot.type,
                provider=slot.provider if is_ai else None,
                model=slot.model if is_ai else None,
                token_hash=None,
                is_connected=is_ai,  # AI agents are always ready in the waiting room
                joined_at=now if is_ai else None,
            )
            db.add(participant)

        await db.commit()
        await db.refresh(session)
        return session

    @classmethod
    async def get_session(cls, db: AsyncSession, session_id: UUID) -> ExperimentSession:
        result = await db.execute(
            select(ExperimentSession).where(ExperimentSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
        return session

    @classmethod
    async def get_or_create_active_session(
        cls,
        db: AsyncSession,
        default_cfg: ActiveExperimentConfig,
    ) -> ExperimentSession:
        result = await db.execute(
            select(ExperimentSession).order_by(desc(ExperimentSession.created_at)).limit(1)
        )
        latest = result.scalar_one_or_none()
        if latest is not None:
            return latest
        return await cls.create_session(db, default_cfg)

    @classmethod
    async def join_session(
        cls,
        db: AsyncSession,
        session_id: UUID,
        default_cfg: ActiveExperimentConfig,
    ) -> JoinSessionResponse:
        lock = cls.get_session_lock(session_id)
        async with lock:
            session = await cls.get_session(db, session_id)
            cfg = load_active_config(condition_key=session.condition)

            if session.phase != ExperimentPhase.WAITING.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Experiment has already started; no new participants can join.",
                )

            ordered = sorted(session.participants, key=lambda p: p.slot_id)
            open_human_slots = [
                p
                for p in ordered
                if p.participant_type == "human" and p.token_hash is None
            ]

            if not open_human_slots:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="All human participant slots are already filled.",
                )

            assigned = open_human_slots[0]
            raw_token = secrets.token_urlsafe(32)
            now = utc_now()

            assigned.token_hash = cls.hash_token(raw_token)
            assigned.is_connected = True
            assigned.joined_at = now

            # Check waiting-room readiness: all human slots filled -> start Round 1
            remaining_open = [
                p
                for p in ordered
                if p.participant_type == "human" and p.token_hash is None
            ]
            if not remaining_open:
                session.phase = ExperimentPhase.ROUND_1_DISCUSSION.value
                session.started_at = now
                session.round_started_at = now

            await db.commit()
            await db.refresh(session)

            state = cls.build_session_state(session, cfg)
            return JoinSessionResponse(
                session_id=session.id,
                participant=cls._to_public_participant(assigned),
                participant_token=raw_token,
                session_state=state,
            )

    @classmethod
    async def authenticate_token(
        cls,
        db: AsyncSession,
        session_id: UUID,
        raw_token: str,
    ) -> Participant:
        if not raw_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing participant token.",
            )
        token_hash = cls.hash_token(raw_token)
        result = await db.execute(
            select(Participant).where(
                Participant.session_id == session_id,
                Participant.token_hash == token_hash,
            )
        )
        participant = result.scalar_one_or_none()
        if not participant:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid participant token for this session.",
            )
        return participant