import asyncio
import hashlib
import secrets
from datetime import timedelta
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, WebSocket, status
from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ActiveExperimentConfig, load_active_config
from app.models import (
    AsyncSessionLocal,
    ExperimentPhase,
    ExperimentSession,
    Message,
    Participant,
    utc_now,
)
from app.schemas import (
    JoinSessionResponse,
    MessagePublic,
    ParticipantPublic,
    SLOT_DISPLAY_NAMES,
    SessionStateResponse,
)


VALID_TRANSITIONS: dict[str, set[str]] = {
    ExperimentPhase.WAITING.value: {ExperimentPhase.ROUND_1_DISCUSSION.value},
    ExperimentPhase.ROUND_1_DISCUSSION.value: {ExperimentPhase.ROUND_1_VOTING.value},
    ExperimentPhase.ROUND_1_VOTING.value: {ExperimentPhase.ROUND_2_DISCUSSION.value},
    ExperimentPhase.ROUND_2_DISCUSSION.value: {ExperimentPhase.ROUND_2_VOTING.value},
    ExperimentPhase.ROUND_2_VOTING.value: {ExperimentPhase.COMPLETED.value},
    ExperimentPhase.COMPLETED.value: set(),
}


class WebSocketManager:
    """In-process WebSocket registry scoped by session_id."""

    def __init__(self) -> None:
        self._connections: dict[UUID, set[WebSocket]] = {}

    async def connect(self, session_id: UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(session_id, set()).add(websocket)

    def disconnect(self, session_id: UUID, websocket: WebSocket) -> None:
        sockets = self._connections.get(session_id)
        if sockets:
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(session_id, None)

    async def broadcast_to_session(self, session_id: UUID, event_type: str, payload: dict) -> None:
        sockets = list(self._connections.get(session_id, set()))
        if not sockets:
            return
        envelope = {"event": event_type, "payload": payload}
        stale: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(envelope)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(session_id, ws)


ws_manager = WebSocketManager()


class ExperimentService:
    """Core session lifecycle, slot assignment, token auth, messaging, timers, and state machine."""

    _session_locks: dict[UUID, asyncio.Lock] = {}
    _timer_tasks: dict[UUID, asyncio.Task] = {}

    @classmethod
    def get_session_lock(cls, session_id: UUID) -> asyncio.Lock:
        if session_id not in cls._session_locks:
            cls._session_locks[session_id] = asyncio.Lock()
        return cls._session_locks[session_id]

    @classmethod
    def cancel_timer(cls, session_id: UUID) -> None:
        task = cls._timer_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()

    @classmethod
    def schedule_discussion_timer(
        cls,
        session_id: UUID,
        expected_phase: str,
        duration_seconds: int,
    ) -> None:
        cls.cancel_timer(session_id)

        async def _timer_worker() -> None:
            try:
                await asyncio.sleep(duration_seconds)
                await cls.advance_discussion_if_active(session_id, expected_phase)
            except asyncio.CancelledError:
                pass

        cls._timer_tasks[session_id] = asyncio.create_task(_timer_worker())

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

    @staticmethod
    def _to_public_message(msg: Message, participant: Participant) -> MessagePublic:
        return MessagePublic(
            id=msg.id,
            sender_id=participant.slot_id,
            sender_name=participant.display_name,
            round_number=msg.round_number,
            content=msg.content,
            created_at=msg.created_at,
        )

    @classmethod
    def ensure_discussion_phase(cls, session: ExperimentSession) -> int:
        if session.phase == ExperimentPhase.ROUND_1_DISCUSSION.value:
            return 1
        if session.phase == ExperimentPhase.ROUND_2_DISCUSSION.value:
            return 2
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Discussion messages are not accepted during phase '{session.phase}'.",
        )

    @classmethod
    def ensure_voting_phase(cls, session: ExperimentSession) -> int:
        if session.phase == ExperimentPhase.ROUND_1_VOTING.value:
            return 1
        if session.phase == ExperimentPhase.ROUND_2_VOTING.value:
            return 2
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Votes are not accepted during phase '{session.phase}'.",
        )

    @classmethod
    def _apply_transition(
        cls,
        session: ExperimentSession,
        target_phase: str,
        duration_seconds: int,
    ) -> None:
        allowed = VALID_TRANSITIONS.get(session.phase, set())
        if target_phase not in allowed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Invalid phase transition from '{session.phase}' to '{target_phase}'.",
            )
        now = utc_now()
        session.phase = target_phase

        if target_phase in (
            ExperimentPhase.ROUND_1_DISCUSSION.value,
            ExperimentPhase.ROUND_2_DISCUSSION.value,
        ):
            if session.started_at is None:
                session.started_at = now
            session.round_started_at = now
            session.round_ends_at = now + timedelta(seconds=duration_seconds)
        elif target_phase in (
            ExperimentPhase.ROUND_1_VOTING.value,
            ExperimentPhase.ROUND_2_VOTING.value,
        ):
            session.round_started_at = None
            session.round_ends_at = None
        elif target_phase == ExperimentPhase.COMPLETED.value:
            session.round_started_at = None
            session.round_ends_at = None
            session.completed_at = now

    @classmethod
    async def list_public_messages(
        cls,
        db: AsyncSession,
        session: ExperimentSession,
    ) -> list[MessagePublic]:
        participant_by_id = {p.id: p for p in session.participants}
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session.id)
            .order_by(asc(Message.created_at))
        )
        messages = result.scalars().all()
        return [
            cls._to_public_message(m, participant_by_id[m.participant_id])
            for m in messages
            if m.participant_id in participant_by_id
        ]

    @classmethod
    async def build_session_state(
        cls,
        db: AsyncSession,
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
        messages = await cls.list_public_messages(db, session)
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
            messages=messages,
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
                is_connected=is_ai,
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
        started_round_1 = False
        duration = 60

        async with lock:
            session = await cls.get_session(db, session_id)
            cfg = load_active_config(condition_key=session.condition)
            duration = cfg.experiment.discussion_duration_seconds

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

            remaining_open = [
                p
                for p in ordered
                if p.participant_type == "human" and p.token_hash is None
            ]
            if not remaining_open:
                cls._apply_transition(
                    session,
                    ExperimentPhase.ROUND_1_DISCUSSION.value,
                    duration,
                )
                started_round_1 = True

            await db.commit()
            await db.refresh(session)
            state = await cls.build_session_state(db, session, cfg)
            public_assigned = cls._to_public_participant(assigned)

        await ws_manager.broadcast_to_session(
            session.id,
            "participant_joined",
            public_assigned.model_dump(mode="json"),
        )

        if started_round_1:
            cls.schedule_discussion_timer(
                session.id,
                ExperimentPhase.ROUND_1_DISCUSSION.value,
                duration,
            )
            await ws_manager.broadcast_to_session(
                session.id,
                "experiment_started",
                {
                    "phase": state.phase,
                    "current_round": state.current_round,
                    "round_ends_at": state.round_ends_at.isoformat() if state.round_ends_at else None,
                },
            )

        return JoinSessionResponse(
            session_id=session.id,
            participant=public_assigned,
            participant_token=raw_token,
            session_state=state,
        )

    @classmethod
    async def add_message(
        cls,
        db: AsyncSession,
        session_id: UUID,
        participant_id: UUID,
        content: str,
        audit_metadata: Optional[dict] = None,
    ) -> MessagePublic:
        lock = cls.get_session_lock(session_id)
        async with lock:
            session = await cls.get_session(db, session_id)
            round_number = cls.ensure_discussion_phase(session)

            sender = next((p for p in session.participants if p.id == participant_id), None)
            if not sender:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Participant does not belong to this session.",
                )

            msg = Message(
                session_id=session.id,
                participant_id=sender.id,
                round_number=round_number,
                content=content,
                audit_metadata=audit_metadata,
                created_at=utc_now(),
            )
            db.add(msg)
            await db.commit()
            await db.refresh(msg)
            public_msg = cls._to_public_message(msg, sender)

        await ws_manager.broadcast_to_session(
            session_id,
            "new_message",
            public_msg.model_dump(mode="json"),
        )
        return public_msg

    @classmethod
    async def advance_discussion_if_active(
        cls,
        session_id: UUID,
        expected_phase: Optional[str] = None,
    ) -> Optional[SessionStateResponse]:
        lock = cls.get_session_lock(session_id)
        state: Optional[SessionStateResponse] = None

        async with lock:
            async with AsyncSessionLocal() as db:
                session = await cls.get_session(db, session_id)
                if expected_phase and session.phase != expected_phase:
                    return None

                if session.phase == ExperimentPhase.ROUND_1_DISCUSSION.value:
                    next_phase = ExperimentPhase.ROUND_1_VOTING.value
                elif session.phase == ExperimentPhase.ROUND_2_DISCUSSION.value:
                    next_phase = ExperimentPhase.ROUND_2_VOTING.value
                else:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cannot advance discussion from phase '{session.phase}'.",
                    )

                cfg = load_active_config(condition_key=session.condition)
                cls.cancel_timer(session_id)
                cls._apply_transition(
                    session,
                    next_phase,
                    cfg.experiment.discussion_duration_seconds,
                )
                await db.commit()
                await db.refresh(session)
                state = await cls.build_session_state(db, session, cfg)

        if state is not None:
            await ws_manager.broadcast_to_session(
                session_id,
                "phase_changed",
                {
                    "phase": state.phase,
                    "current_round": state.current_round,
                    "round_ends_at": state.round_ends_at.isoformat() if state.round_ends_at else None,
                },
            )
        return state

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

    @classmethod
    async def set_participant_connection(
        cls,
        session_id: UUID,
        participant_id: UUID,
        is_connected: bool,
    ) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.session_id == session_id,
                    Participant.id == participant_id,
                )
            )
            participant = result.scalar_one_or_none()
            if participant:
                participant.is_connected = is_connected
                await db.commit()