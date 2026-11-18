from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ActiveExperimentConfig, load_active_config
from app.models import AsyncSessionLocal, Participant, get_db
from app.schemas import (
    CreateSessionRequest,
    JoinSessionResponse,
    MessagePublic,
    ParticipantPublic,
    SendMessageRequest,
    SessionStateResponse,
)
from app.service import ExperimentService, ws_manager

router = APIRouter(tags=["experiment"])


def get_active_config(request: Request) -> ActiveExperimentConfig:
    return request.app.state.config


async def get_current_participant(
    session_id: UUID,
    x_participant_token: Optional[str] = Header(default=None, alias="X-Participant-Token"),
    db: AsyncSession = Depends(get_db),
) -> Participant:
    return await ExperimentService.authenticate_token(db, session_id, x_participant_token or "")


@router.post("/api/sessions", response_model=SessionStateResponse, status_code=201)
async def create_session(
    payload: Optional[CreateSessionRequest] = None,
    db: AsyncSession = Depends(get_db),
    cfg: ActiveExperimentConfig = Depends(get_active_config),
):
    condition_override = payload.condition_key if payload else None
    session = await ExperimentService.create_session(db, cfg, condition_key=condition_override)
    session_cfg = load_active_config(condition_key=session.condition)
    return await ExperimentService.build_session_state(db, session, session_cfg)


@router.get("/api/sessions/active", response_model=SessionStateResponse)
async def get_active_session(
    db: AsyncSession = Depends(get_db),
    cfg: ActiveExperimentConfig = Depends(get_active_config),
):
    session = await ExperimentService.get_or_create_active_session(db, cfg)
    session_cfg = load_active_config(condition_key=session.condition)
    return await ExperimentService.build_session_state(db, session, session_cfg)


@router.post("/api/sessions/active/reset", response_model=SessionStateResponse)
async def reset_active_session(
    payload: Optional[CreateSessionRequest] = None,
    db: AsyncSession = Depends(get_db),
    cfg: ActiveExperimentConfig = Depends(get_active_config),
):
    condition_override = payload.condition_key if payload else None
    session = await ExperimentService.create_session(db, cfg, condition_key=condition_override)
    session_cfg = load_active_config(condition_key=session.condition)
    return await ExperimentService.build_session_state(db, session, session_cfg)


@router.get("/api/sessions/{session_id}", response_model=SessionStateResponse)
async def get_session_state(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    session = await ExperimentService.get_session(db, session_id)
    session_cfg = load_active_config(condition_key=session.condition)
    return await ExperimentService.build_session_state(db, session, session_cfg)


@router.get("/api/sessions/{session_id}/participants", response_model=list[ParticipantPublic])
async def get_session_participants(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    session = await ExperimentService.get_session(db, session_id)
    session_cfg = load_active_config(condition_key=session.condition)
    state = await ExperimentService.build_session_state(db, session, session_cfg)
    return state.participants


@router.post("/api/sessions/{session_id}/join", response_model=JoinSessionResponse)
async def join_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    cfg: ActiveExperimentConfig = Depends(get_active_config),
):
    return await ExperimentService.join_session(db, session_id, cfg)


@router.post("/api/sessions/{session_id}/messages", response_model=MessagePublic, status_code=201)
async def post_message(
    session_id: UUID,
    payload: SendMessageRequest,
    participant: Participant = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
):
    return await ExperimentService.add_message(
        db=db,
        session_id=session_id,
        participant_id=participant.id,
        content=payload.content,
    )


@router.get("/api/sessions/{session_id}/messages", response_model=list[MessagePublic])
async def list_messages(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    session = await ExperimentService.get_session(db, session_id)
    return await ExperimentService.list_public_messages(db, session)


@router.post("/api/sessions/{session_id}/advance", response_model=SessionStateResponse)
async def advance_discussion_phase(session_id: UUID):
    """Demo/testing helper to expire an active discussion timer immediately."""
    return await ExperimentService.advance_discussion_if_active(session_id)


@router.websocket("/ws/sessions/{session_id}")
async def session_websocket(
    websocket: WebSocket,
    session_id: UUID,
    token: str = Query(default=""),
):
    async with AsyncSessionLocal() as db:
        try:
            participant = await ExperimentService.authenticate_token(db, session_id, token)
        except HTTPException:
            await websocket.close(code=1008)
            return

    await ws_manager.connect(session_id, websocket)
    await ExperimentService.set_participant_connection(session_id, participant.id, True)

    try:
        while True:
            # Keep connection alive; commands use REST endpoints
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(session_id, websocket)
        await ExperimentService.set_participant_connection(session_id, participant.id, False)