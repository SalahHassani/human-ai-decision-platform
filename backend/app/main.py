from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ActiveExperimentConfig, load_active_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.config = load_active_config()
    yield


app = FastAPI(
    title="Human-AI Decision Experiment Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
@app.get("/api/health")
async def health_check():
    cfg: ActiveExperimentConfig = app.state.config
    human_slots = sum(1 for p in cfg.condition.participants if p.type == "human")
    ai_slots = sum(1 for p in cfg.condition.participants if p.type == "ai")
    return {
        "status": "ok",
        "condition_key": cfg.condition_key,
        "condition_name": cfg.condition.name,
        "human_slots": human_slots,
        "ai_slots": ai_slots,
        "rounds": cfg.experiment.rounds,
        "discussion_duration_seconds": cfg.experiment.discussion_duration_seconds,
    }