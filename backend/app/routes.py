import secrets
from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ActiveExperimentConfig, load_active_config
from app.models import AsyncSessionLocal, Participant, get_db
from app.schemas import (
    CreateSessionRequest,
    ExperimentResultPublic,
    JoinSessionResponse,
    MessagePublic,
    ParticipantPublic,
    SendMessageRequest,
    SessionStateResponse,
    SubmitVoteRequest,
    VoteStatusPublic,
)
from app.service import ExperimentService, ws_manager

router = APIRouter(tags=["experiment"])


def get_active_config(request: Request) -> ActiveExperimentConfig:
    return request.app.state.config


def require_admin_access(
    request: Request,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> None:
    cfg: ActiveExperimentConfig = request.app.state.config
    if not cfg.demo_mode and not x_admin_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo controls are disabled in production mode.",
        )
    if not x_admin_token or not secrets.compare_digest(x_admin_token, cfg.admin_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Valid X-Admin-Token header is required for administrative controls.",
        )

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


# @router.post("/api/sessions/active/reset", response_model=SessionStateResponse)
# async def reset_active_session(
#     payload: Optional[CreateSessionRequest] = None,
#     db: AsyncSession = Depends(get_db),
#     cfg: ActiveExperimentConfig = Depends(get_active_config),
# ):
#     condition_override = payload.condition_key if payload else None
#     session = await ExperimentService.create_session(db, cfg, condition_key=condition_override)
#     session_cfg = load_active_config(condition_key=session.condition)
#     return await ExperimentService.build_session_state(db, session, session_cfg)


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


@router.post("/api/sessions/{session_id}/vote", response_model=VoteStatusPublic, status_code=201)
async def submit_vote(
    session_id: UUID,
    payload: SubmitVoteRequest,
    participant: Participant = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
):
    return await ExperimentService.submit_vote(
        db=db,
        session_id=session_id,
        voter_id=participant.id,
        target_slot_id=payload.target_id,
    )


@router.get("/api/sessions/{session_id}/results", response_model=ExperimentResultPublic)
async def get_results(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    session = await ExperimentService.get_session(db, session_id)
    result = await ExperimentService.get_public_result(db, session)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Experiment results are not available until Round 2 voting completes.",
        )
    return result


# @router.post("/api/sessions/{session_id}/advance", response_model=SessionStateResponse)
# async def advance_discussion_phase(session_id: UUID):
#     """Demo/testing helper to expire an active discussion timer immediately."""
#     return await ExperimentService.advance_discussion_if_active(session_id)


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
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(session_id, websocket)
        await ExperimentService.set_participant_connection(session_id, participant.id, False)


@router.post(
    "/api/sessions/active/reset",
    response_model=SessionStateResponse,
    dependencies=[Depends(require_admin_access)],
)
async def reset_active_session(
    payload: Optional[CreateSessionRequest] = None,
    db: AsyncSession = Depends(get_db),
    cfg: ActiveExperimentConfig = Depends(get_active_config),
):
    ExperimentService.cancel_all_tasks()
    condition_override = payload.condition_key if payload else None
    session = await ExperimentService.create_session(db, cfg, condition_key=condition_override)
    session_cfg = load_active_config(condition_key=session.condition)
    return await ExperimentService.build_session_state(db, session, session_cfg)

@router.post(
    "/api/sessions/{session_id}/advance",
    response_model=SessionStateResponse,
    dependencies=[Depends(require_admin_access)],
)
async def advance_discussion_phase(session_id: UUID):
    """Admin/demo helper to expire an active discussion timer immediately."""
    return await ExperimentService.advance_discussion_if_active(session_id)


@router.get(
    "/api/sessions/{session_id}/export.csv",
    dependencies=[Depends(require_admin_access)],
)
async def export_session_csv(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Admin-only CSV export of completed session messages, votes, and final outcome."""
    csv_text = await ExperimentService.export_session_csv(db, session_id)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="session_{session_id}_export.csv"'
        },
    )