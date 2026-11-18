import asyncio
import csv
import hashlib
import io
import random
import secrets
from datetime import timedelta
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, WebSocket, status
from sqlalchemy import asc, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_agent import (
    AgentDecisionContext,
    DiscussionMessageContext,
    create_ai_agent,
)
from app.config import ActiveExperimentConfig, load_active_config
from app.models import (
    AsyncSessionLocal,
    ExperimentPhase,
    ExperimentResult,
    ExperimentSession,
    Message,
    Participant,
    Vote,
    utc_now,
)
from app.schemas import (
    ExperimentResultPublic,
    JoinSessionResponse,
    MessagePublic,
    ParticipantPublic,
    SLOT_DISPLAY_NAMES,
    SessionStateResponse,
    VoteStatusPublic,
)


VALID_TRANSITIONS: dict[str, set[str]] = {
    ExperimentPhase.WAITING.value: {ExperimentPhase.ROUND_1_DISCUSSION.value},
    ExperimentPhase.ROUND_1_DISCUSSION.value: {ExperimentPhase.ROUND_1_VOTING.value},
    ExperimentPhase.ROUND_1_VOTING.value: {ExperimentPhase.ROUND_2_DISCUSSION.value},
    ExperimentPhase.ROUND_2_DISCUSSION.value: {ExperimentPhase.ROUND_2_VOTING.value},
    ExperimentPhase.ROUND_2_VOTING.value: {ExperimentPhase.COMPLETED.value},
    ExperimentPhase.COMPLETED.value: set(),
}

AISpec = tuple[UUID, str, str, Optional[str], Optional[str]]


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
    """Core session lifecycle, slot assignment, token auth, messaging, AI tasks, voting, and state machine."""

    _session_locks: dict[UUID, asyncio.Lock] = {}
    _timer_tasks: dict[UUID, asyncio.Task] = {}
    _ai_tasks: dict[UUID, list[asyncio.Task]] = {}

    @classmethod
    def get_session_lock(cls, session_id: UUID) -> asyncio.Lock:
        if session_id not in cls._session_locks:
            cls._session_locks[session_id] = asyncio.Lock()
        return cls._session_locks[session_id]

    @staticmethod
    def _extract_ai_specs(session: ExperimentSession) -> list[AISpec]:
        return [
            (p.id, p.slot_id, p.display_name, p.provider, p.model)
            for p in session.participants
            if p.participant_type == "ai"
        ]

    @classmethod
    def cancel_timer(cls, session_id: UUID) -> None:
        task = cls._timer_tasks.pop(session_id, None)
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()

    @classmethod
    def cancel_ai_tasks(cls, session_id: UUID) -> None:
        tasks = cls._ai_tasks.pop(session_id, [])
        current = asyncio.current_task()
        for task in tasks:
            if not task.done() and task is not current:
                task.cancel()

    @classmethod
    def cancel_all_tasks(cls) -> None:
        for sid in list(cls._timer_tasks.keys()):
            cls.cancel_timer(sid)
        for sid in list(cls._ai_tasks.keys()):
            cls.cancel_ai_tasks(sid)

    @classmethod
    def schedule_discussion_timer(
        cls,
        session_id: UUID,
        expected_phase: str,
        duration_seconds: float,
    ) -> None:
        cls.cancel_timer(session_id)

        async def _timer_worker() -> None:
            try:
                await asyncio.sleep(duration_seconds)
                await cls.advance_discussion_if_active(session_id, expected_phase)
            except asyncio.CancelledError:
                pass

        cls._timer_tasks[session_id] = asyncio.create_task(_timer_worker())

    @classmethod
    def schedule_ai_discussion_tasks(
        cls,
        session_id: UUID,
        expected_phase: str,
        round_number: int,
        ai_specs: list[AISpec],
        cfg: ActiveExperimentConfig,
    ) -> None:
        cls.cancel_ai_tasks(session_id)
        if not ai_specs:
            return

        tasks: list[asyncio.Task] = []
        min_delay = cfg.ai.min_response_delay_seconds
        max_delay = cfg.ai.max_response_delay_seconds
        max_msgs = cfg.ai.max_messages_per_round
        duration = cfg.experiment.discussion_duration_seconds

        for participant_id, slot_id, display_name, provider, model in ai_specs:
            agent = create_ai_agent(provider=provider, model=model)

            async def _ai_speaker_worker(
                p_id: UUID = participant_id,
                s_id: str = slot_id,
                d_name: str = display_name,
                ai_impl=agent,
            ) -> None:
                try:
                    cumulative_delay = 0.0
                    for msg_idx in range(max_msgs):
                        delay = random.uniform(min_delay, max_delay)
                        if msg_idx > 0:
                            delay = max(delay, duration * 0.35)
                        cumulative_delay += delay
                        if cumulative_delay >= max(1.0, duration - 2.0):
                            break

                        await asyncio.sleep(delay)

                        async with AsyncSessionLocal() as db:
                            session = await cls.get_session(db, session_id)
                            if session.phase != expected_phase:
                                return

                            public_msgs = await cls.list_public_messages(db, session)
                            ctx = AgentDecisionContext(
                                session_id=str(session_id),
                                self_slot_id=s_id,
                                self_display_name=d_name,
                                round_number=round_number,
                                message_index=msg_idx,
                                participant_slots=sorted(p.slot_id for p in session.participants),
                                messages=[
                                    DiscussionMessageContext(
                                        sender_id=m.sender_id,
                                        sender_name=m.sender_name,
                                        round_number=m.round_number,
                                        content=m.content,
                                    )
                                    for m in public_msgs
                                ],
                            )
                            reply_text = await ai_impl.generate_response(ctx)
                            audit = {
                                "provider": ai_impl.provider,
                                "model": ai_impl.model,
                                "delay_seconds": round(delay, 2),
                                "message_index": msg_idx,
                            }
                            await cls.add_message(
                                db=db,
                                session_id=session_id,
                                participant_id=p_id,
                                content=reply_text,
                                audit_metadata=audit,
                            )
                except asyncio.CancelledError:
                    pass
                except HTTPException:
                    pass

            tasks.append(asyncio.create_task(_ai_speaker_worker()))

        cls._ai_tasks[session_id] = tasks

    @classmethod
    def schedule_ai_voting_tasks(
        cls,
        session_id: UUID,
        expected_phase: str,
        round_number: int,
        ai_specs: list[AISpec],
    ) -> None:
        cls.cancel_ai_tasks(session_id)
        if not ai_specs:
            return

        tasks: list[asyncio.Task] = []
        for participant_id, slot_id, display_name, provider, model in ai_specs:
            agent = create_ai_agent(provider=provider, model=model)

            async def _ai_voter_worker(
                p_id: UUID = participant_id,
                s_id: str = slot_id,
                d_name: str = display_name,
                ai_impl=agent,
            ) -> None:
                try:
                    await asyncio.sleep(random.uniform(1.0, 2.5))
                    async with AsyncSessionLocal() as db:
                        session = await cls.get_session(db, session_id)
                        if session.phase != expected_phase:
                            return

                        public_msgs = await cls.list_public_messages(db, session)
                        ctx = AgentDecisionContext(
                            session_id=str(session_id),
                            self_slot_id=s_id,
                            self_display_name=d_name,
                            round_number=round_number,
                            message_index=0,
                            participant_slots=sorted(p.slot_id for p in session.participants),
                            messages=[
                                DiscussionMessageContext(
                                    sender_id=m.sender_id,
                                    sender_name=m.sender_name,
                                    round_number=m.round_number,
                                    content=m.content,
                                )
                                for m in public_msgs
                            ],
                        )
                        target_slot = await ai_impl.cast_vote(ctx)
                        await cls.submit_vote(
                            db=db,
                            session_id=session_id,
                            voter_id=p_id,
                            target_slot_id=target_slot,
                        )
                except asyncio.CancelledError:
                    pass
                except HTTPException:
                    pass

            tasks.append(asyncio.create_task(_ai_voter_worker()))

        cls._ai_tasks[session_id] = tasks


    @classmethod
    async def export_session_csv(cls, db: AsyncSession, session_id: UUID) -> str:
        sess_res = await db.execute(
            select(ExperimentSession).where(ExperimentSession.id == session_id)
        )
        session = sess_res.scalar_one_or_none()
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found.",
            )
        if session.phase != "COMPLETED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="CSV export is only available for completed sessions.",
            )

        result_res = await db.execute(
            select(ExperimentResult).where(ExperimentResult.session_id == session_id)
        )
        exp_result = result_res.scalar_one_or_none()
        if not exp_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Experiment results not found for session.",
            )

        slot_by_id = {p.id: p.slot_id for p in session.participants}
        winner_slot = slot_by_id.get(exp_result.decision_maker_id, "")
        totals = exp_result.totals_json or {}

        msg_res = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.round_number.asc(), Message.created_at.asc(), Message.id.asc())
        )
        messages = list(msg_res.scalars().all())

        vote_res = await db.execute(
            select(Vote)
            .where(Vote.session_id == session_id)
            .order_by(Vote.round_number.asc(), Vote.created_at.asc(), Vote.id.asc())
        )
        votes = list(vote_res.scalars().all())

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "session_id",
                "condition_key",
                "record_type",
                "round_number",
                "actor_id",
                "target_id",
                "message_content",
                "timestamp_utc",
                "player_a_total_votes",
                "player_b_total_votes",
                "player_c_total_votes",
                "decision_maker_id",
            ]
        )

        for m in messages:
            writer.writerow(
                [
                    str(session.id),
                    session.condition,
                    "message",
                    m.round_number,
                    slot_by_id.get(m.participant_id, ""),
                    "",
                    m.content,
                    m.created_at.isoformat() if m.created_at else "",
                    totals.get("player_a", 0),
                    totals.get("player_b", 0),
                    totals.get("player_c", 0),
                    winner_slot,
                ]
            )

        for v in votes:
            writer.writerow(
                [
                    str(session.id),
                    session.condition,
                    "vote",
                    v.round_number,
                    slot_by_id.get(v.voter_id, ""),
                    slot_by_id.get(v.target_id, ""),
                    "",
                    v.created_at.isoformat() if v.created_at else "",
                    totals.get("player_a", 0),
                    totals.get("player_b", 0),
                    totals.get("player_c", 0),
                    winner_slot,
                ]
            )

        return output.getvalue()

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
    async def get_vote_status(
        cls,
        db: AsyncSession,
        session: ExperimentSession,
        round_number: int,
    ) -> VoteStatusPublic:
        participant_by_id = {p.id: p for p in session.participants}
        result = await db.execute(
            select(Vote).where(
                Vote.session_id == session.id,
                Vote.round_number == round_number,
            )
        )
        votes = result.scalars().all()
        submitted_slots = sorted(
            participant_by_id[v.voter_id].slot_id
            for v in votes
            if v.voter_id in participant_by_id
        )
        return VoteStatusPublic(
            round_number=round_number,
            submitted_participant_ids=submitted_slots,
            votes_received=len(submitted_slots),
            total_required=3,
        )

    @classmethod
    async def get_public_result(
        cls,
        db: AsyncSession,
        session: ExperimentSession,
    ) -> Optional[ExperimentResultPublic]:
        result = await db.execute(
            select(ExperimentResult).where(ExperimentResult.session_id == session.id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        winner = next(
            (p for p in session.participants if p.id == record.decision_maker_id),
            None,
        )
        winner_slot = winner.slot_id if winner else "player_a"
        winner_name = winner.display_name if winner else SLOT_DISPLAY_NAMES[winner_slot]
        return ExperimentResultPublic(
            session_id=session.id,
            totals_by_participant=record.totals_json,
            round_1_totals=record.round_1_json,
            round_2_totals=record.round_2_json,
            decision_maker_id=winner_slot,
            decision_maker_name=winner_name,
            completed_at=record.completed_at,
        )

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

        vote_status: Optional[VoteStatusPublic] = None
        if session.phase in (
            ExperimentPhase.ROUND_1_VOTING.value,
            ExperimentPhase.ROUND_2_VOTING.value,
        ):
            r_no = 1 if session.phase == ExperimentPhase.ROUND_1_VOTING.value else 2
            vote_status = await cls.get_vote_status(db, session, r_no)

        final_result: Optional[ExperimentResultPublic] = None
        if session.phase == ExperimentPhase.COMPLETED.value:
            final_result = await cls.get_public_result(db, session)

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
            vote_status=vote_status,
            result=final_result,
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
            select(ExperimentSession)
            .where(ExperimentSession.id == session_id)
            .execution_options(populate_existing=True)
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
        ai_specs: list[AISpec] = []

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
                ai_specs = cls._extract_ai_specs(session)

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
            cls.schedule_ai_discussion_tasks(
                session.id,
                ExperimentPhase.ROUND_1_DISCUSSION.value,
                round_number=1,
                ai_specs=ai_specs,
                cfg=cfg,
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
        ai_specs: list[AISpec] = []
        voting_round: int = 1

        async with lock:
            async with AsyncSessionLocal() as db:
                session = await cls.get_session(db, session_id)
                if expected_phase and session.phase != expected_phase:
                    return None

                if session.phase == ExperimentPhase.ROUND_1_DISCUSSION.value:
                    next_phase = ExperimentPhase.ROUND_1_VOTING.value
                    voting_round = 1
                elif session.phase == ExperimentPhase.ROUND_2_DISCUSSION.value:
                    next_phase = ExperimentPhase.ROUND_2_VOTING.value
                    voting_round = 2
                else:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cannot advance discussion from phase '{session.phase}'.",
                    )

                cfg = load_active_config(condition_key=session.condition)
                cls.cancel_timer(session_id)
                cls.cancel_ai_tasks(session_id)
                cls._apply_transition(
                    session,
                    next_phase,
                    cfg.experiment.discussion_duration_seconds,
                )
                ai_specs = cls._extract_ai_specs(session)
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
            cls.schedule_ai_voting_tasks(
                session_id=session_id,
                expected_phase=state.phase,
                round_number=voting_round,
                ai_specs=ai_specs,
            )
        return state

    @classmethod
    def _compute_election_winner(
        cls,
        round_1_totals: dict[str, int],
        round_2_totals: dict[str, int],
    ) -> tuple[dict[str, int], str]:
        slots = ["player_a", "player_b", "player_c"]
        combined = {
            slot: round_1_totals.get(slot, 0) + round_2_totals.get(slot, 0)
            for slot in slots
        }
        winner_slot = sorted(
            slots,
            key=lambda s: (-combined[s], -round_2_totals.get(s, 0), s),
        )[0]
        return combined, winner_slot

    @classmethod
    async def submit_vote(
        cls,
        db: AsyncSession,
        session_id: UUID,
        voter_id: UUID,
        target_slot_id: str,
    ) -> VoteStatusPublic:
        lock = cls.get_session_lock(session_id)
        transitioned_to_round_2 = False
        completed_result: Optional[ExperimentResultPublic] = None
        next_state: Optional[SessionStateResponse] = None
        ai_specs: list[AISpec] = []
        duration = 60
        cfg: Optional[ActiveExperimentConfig] = None

        async with lock:
            session = await cls.get_session(db, session_id)
            round_number = cls.ensure_voting_phase(session)
            cfg = load_active_config(condition_key=session.condition)
            duration = cfg.experiment.discussion_duration_seconds

            voter = next((p for p in session.participants if p.id == voter_id), None)
            if not voter:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Voter does not belong to this session.",
                )

            target = next((p for p in session.participants if p.slot_id == target_slot_id), None)
            if not target:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid vote target '{target_slot_id}'.",
                )

            if not cfg.voting.allow_self_vote and voter.id == target.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Self-voting is disabled for this experiment.",
                )

            existing = await db.execute(
                select(Vote).where(
                    Vote.session_id == session.id,
                    Vote.voter_id == voter.id,
                    Vote.round_number == round_number,
                )
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="You have already submitted a vote for this round.",
                )

            vote = Vote(
                session_id=session.id,
                voter_id=voter.id,
                target_id=target.id,
                round_number=round_number,
                created_at=utc_now(),
            )
            db.add(vote)
            try:
                await db.flush()
            except IntegrityError as exc:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Duplicate vote rejected.",
                ) from exc

            vote_status = await cls.get_vote_status(db, session, round_number)

            if vote_status.votes_received == 3:
                cls.cancel_ai_tasks(session_id)
                if round_number == 1:
                    cls._apply_transition(
                        session,
                        ExperimentPhase.ROUND_2_DISCUSSION.value,
                        duration,
                    )
                    transitioned_to_round_2 = True
                    ai_specs = cls._extract_ai_specs(session)
                else:
                    all_votes_res = await db.execute(
                        select(Vote).where(Vote.session_id == session.id)
                    )
                    all_votes = all_votes_res.scalars().all()
                    slot_by_id = {p.id: p.slot_id for p in session.participants}

                    r1_totals = {"player_a": 0, "player_b": 0, "player_c": 0}
                    r2_totals = {"player_a": 0, "player_b": 0, "player_c": 0}
                    for v in all_votes:
                        t_slot = slot_by_id.get(v.target_id)
                        if t_slot:
                            if v.round_number == 1:
                                r1_totals[t_slot] += 1
                            elif v.round_number == 2:
                                r2_totals[t_slot] += 1

                    combined, winner_slot = cls._compute_election_winner(r1_totals, r2_totals)
                    winner_participant = next(
                        p for p in session.participants if p.slot_id == winner_slot
                    )
                    cls._apply_transition(
                        session,
                        ExperimentPhase.COMPLETED.value,
                        duration,
                    )
                    result_row = ExperimentResult(
                        session_id=session.id,
                        totals_json=combined,
                        round_1_json=r1_totals,
                        round_2_json=r2_totals,
                        decision_maker_id=winner_participant.id,
                        completed_at=session.completed_at or utc_now(),
                    )
                    db.add(result_row)
                    await db.flush()
                    completed_result = ExperimentResultPublic(
                        session_id=session.id,
                        totals_by_participant=combined,
                        round_1_totals=r1_totals,
                        round_2_totals=r2_totals,
                        decision_maker_id=winner_slot,
                        decision_maker_name=winner_participant.display_name,
                        completed_at=result_row.completed_at,
                    )

            await db.commit()
            await db.refresh(session)
            if transitioned_to_round_2 or completed_result is not None:
                next_state = await cls.build_session_state(db, session, cfg)

        await ws_manager.broadcast_to_session(
            session_id,
            "vote_status",
            vote_status.model_dump(mode="json"),
        )

        if transitioned_to_round_2 and next_state is not None and cfg is not None:
            cls.schedule_discussion_timer(
                session_id,
                ExperimentPhase.ROUND_2_DISCUSSION.value,
                duration,
            )
            cls.schedule_ai_discussion_tasks(
                session_id,
                ExperimentPhase.ROUND_2_DISCUSSION.value,
                round_number=2,
                ai_specs=ai_specs,
                cfg=cfg,
            )
            await ws_manager.broadcast_to_session(
                session_id,
                "phase_changed",
                {
                    "phase": next_state.phase,
                    "current_round": next_state.current_round,
                    "round_ends_at": (
                        next_state.round_ends_at.isoformat() if next_state.round_ends_at else None
                    ),
                },
            )

        if completed_result is not None:
            await ws_manager.broadcast_to_session(
                session_id,
                "experiment_completed",
                completed_result.model_dump(mode="json"),
            )

        return vote_status

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


                