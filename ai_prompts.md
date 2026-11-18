# AI Usage Log (`ai_prompts.md`)

## 1. Models, Agents & Tools Used
- **Primary AI Assistant (Architecture, Code Generation, Test Suite, Code Review & Documentation):**
  - **Interface:** Google Gemini (Web Assistant)
  - **Model:** Gemini 2.5 Pro / Gemini (Web Chat Interface)
- **Local Development Environment & Verification Tools:**
  - **IDE / Editor:** Visual Studio Code (Windows)
  - **Container & Test Execution:** Docker Desktop (`docker compose`), Python 3.12 (`pytest`), PostgreSQL 16, Node.js 20 / Vite

---

## 2. Development Workflow & Key Prompts

The application was developed iteratively across 8 structured milestones (Milestones 0–7) followed by a final hardening and verification pass. Every AI-generated module was reviewed, tested locally inside Docker containers, and adjusted as needed.

### Prompt 1 — Architecture & Milestone Plan
> *"Design a lightweight, research-ready Human-AI group decision-making experiment platform using FastAPI, React (Vite), PostgreSQL, and Docker Compose within a 4-hour assessment scope. Break the build into clear incremental milestones covering 3 experimental conditions (3 Humans, 2 Humans + 1 AI, 1 Human + 2 AI), strict neutral participant identities (Player A, Player B, Player C), two timed discussion rounds, two blind voting rounds, deterministic tie-breaking, and real-time WebSocket synchronization."*

- **Outcome:** Established the modular monolith architecture, `config.yml` schema, PostgreSQL data model (`sessions`, `participants`, `messages`, `votes`, `experiment_results`), server-authoritative phase state machine, and 8-milestone execution plan.

### Prompt 2 — Backend Core, State Machine & WebSockets (Milestones 0–3)
> *"Implement the FastAPI backend with Pydantic config validation, SQLAlchemy async models, atomic slot assignment on `/join`, SHA-256 hashed participant tokens, server-authoritative phase transitions guarded by per-session `asyncio.Lock`, and an authenticated WebSocket endpoint `/ws/sessions/{session_id}` that never leaks AI identity fields."*

- **Outcome & Review Modifications:** Generated `backend/app/config.py`, `backend/app/models.py`, `backend/app/schemas.py`, `backend/app/service.py`, `backend/app/routes.py`, and `backend/app/main.py`. Verified that `ParticipantPublic` and `MessagePublic` strip all internal `participant_type`, `provider`, `model`, and `token_hash` attributes.

### Prompt 3 — Offline Rule-Based AI Agents & Blind Voting (Milestones 4–5)
> *"Implement an extensible `AIAgent` interface with an offline `RuleBasedAIAgent` that replies with jittered delays (`4–14s`) without revealing its AI nature, plus blind voting across Rounds 1 and 2 with deterministic tie-breaking (combined total votes, then Round 2 votes, then alphabetical slot order)."*

- **Outcome & Review Modifications:** Created `backend/app/ai_agent.py` and voting/election logic in `backend/app/service.py`. Removed unreachable dead code inside `RuleBasedAIAgent.cast_vote()` during code review.

### Prompt 4 — React Experiment UI (Milestone 6)
> *"Build a clean React + Vite frontend with a Waiting Room, live countdown timer synchronized to server `round_ends_at`, real-time WebSocket chat with automatic snapshot resynchronization on reconnect, blind voting panel, and final Decision Maker results table."*

- **Outcome & Review Modifications:** Created `frontend/src/App.jsx`, `frontend/src/hooks/useExperimentSocket.js`, `frontend/src/services/api.js`, and UI components (`WaitingRoom.jsx`, `DiscussionPanel.jsx`, `VotingPanel.jsx`, `ResultsView.jsx`). Updated `VotingPanel.jsx` to hide the participant's own identity from selectable voting options.

### Prompt 5 — Hardening, Security, WebSocket Tests & Research CSV Export (Final Refinement)
> *"Implement the final refinement plan one task at a time: (1) set `VotingSettings.allow_self_vote` default to `False` and clean up dead code; (2) verify automatic discussion timer expiry/cancellation and protect `/reset` and `/advance` with `X-Admin-Token`; (3) add WebSocket broadcast and reconnection sync tests; (4) add an admin-protected CSV research export endpoint for completed sessions; (5) finalize `ai_prompts.md` and `README.md`."*

- **Outcome & Review Modifications:**
  - Updated `VotingSettings.allow_self_vote` default to `False` in `backend/app/config.py`.
  - Added `require_admin_access` (`X-Admin-Token`) to `POST /api/sessions/active/reset`, `POST /api/sessions/{session_id}/advance`, and `GET /api/sessions/{session_id}/export.csv`.
  - Expanded `backend/tests/test_experiment.py` from 5 to 10 automated `pytest` cases covering timers, admin authorization, WebSocket broadcasts/reconnection, and CSV research export privacy.

  