# Human–AI Group Decision-Making Experiment Platform

A lightweight, real-time web application for running a 3-participant group decision-making experiment across configurable human/AI compositions (**3 Humans**, **2 Humans + 1 AI**, or **1 Human + 2 AI**). Participants interact under neutral identifiers (**Player A**, **Player B**, **Player C**) across two timed discussion rounds and two blind voting rounds to elect a single **Decision Maker**.

---

## 1. Quick Start 

### Prerequisites
- **Docker** & **Docker Compose** 
- **Git**

### Installation & Startup
1. **Clone the repository**:
   ```bash
   git clone <your-repo-url>
   cd human-ai-decision-platform
   ```

2. **Create environment configuration (optional)**:
   ```bash
   cp .env.example .env
   ```
   *(Default settings work out-of-the-box without editing `.env`.)*

3. **Build and launch all services**:
   ```bash
   docker compose up --build -d
   ```

4. **Verify services are running**:
   - **Frontend Experiment UI**: `http://localhost:5173`
   - **Backend Health & Active Config**: `http://localhost:8000/api/health`
   - **Interactive OpenAPI / Swagger Docs**: `http://localhost:8000/docs`

### Exposed Ports & Services

| Service | Container Port | Host Port | Purpose |
| :--- | :--- | :--- | :--- |
| **Frontend** (`React` + `Vite`) | `5173` | `5173` | Participant web interface (`http://localhost:5173`) |
| **Backend** (`FastAPI` + `Uvicorn`) | `8000` | `8000` | REST API & WebSocket server (`ws://localhost:8000`) |
| **Database** (`PostgreSQL 16`) | `5432` | `5433` | Persistent session, participant, message, vote, and result storage *(mapped to `5433` on host to avoid colliding with any local Postgres instance)* |

---

## 2. How to Use & Test the Experiment

### Single-Browser Demo (`1 Human + 2 AI`)
1. Open `http://localhost:5173`.
2. Under **Switch Condition (Demo)** on the join screen, select **1 Human + 2 AI** (`condition_3`).
3. Click **Join Active Session**. You are assigned **Player A**, and the experiment immediately starts **Round 1 of 2 — Group Discussion**.
4. Send a message in the chat; **Player B** and **Player C** (AI participants) respond automatically with jittered delays (`4–14s`) without revealing their AI identity.
5. Wait for the 60-second timer to expire (or click **End Discussion Now** in the header to skip the timer during a demo).
6. Cast your vote in **Round 1**, complete **Round 2 Discussion & Voting**, and view the elected **Decision Maker** and round-by-round vote breakdown.

### Multi-Human Testing (`2 Humans + 1 AI` or `3 Humans`)
- Participant session tokens are stored in `sessionStorage` (isolated per browser tab).
- To simulate multiple human participants on one machine:
  1. Select **2 Humans + 1 AI** (`condition_2`) or **3 Humans** (`condition_1`).
  2. Open `http://localhost:5173` in **2 or 3 separate browser tabs**.
  3. Click **Join Active Session** in each tab. The Waiting Room updates live and transitions all tabs simultaneously into Round 1 once all required human slots are filled.

---

## 3. Configuration (`config.yml` & `.env`)

All experiment parameters live in `config.yml` and are validated at startup via Pydantic (`backend/app/config.py`).

### Switching Experiment Conditions
You can switch between the three built-in conditions in three ways:
1. **In the UI**: Click **3 Humans**, **2 Humans + 1 AI**, or **1 Human + 2 AI** on the landing screen (or click **Reset Session** anytime).
2. **Via `.env`**: Set `EXPERIMENT_CONDITION=condition_1` (or `condition_2` / `condition_3`) and restart the backend (`docker compose restart backend`).
3. **Via REST API**:
   ```bash
   curl -X POST http://localhost:8000/api/sessions/active/reset \
     -H "Content-Type: application/json" \
     -d '{"condition_key": "condition_3"}'
   ```

### Customizable Parameters in `config.yml`
- **`experiment.discussion_duration_seconds`**: Length of each discussion round (default: `60`).
- **`experiment.rounds`**: Number of discussion + voting cycles (default: `2`).
- **`voting.allow_self_vote`**: Set to `false` by default (prevents participants and AI agents from voting for themselves); set to `true` to allow self-voting.
- **`voting.tie_break`**: Deterministic tie-breaking priority (`[round_2_votes, alphabetical_order]`).
- **`ai.min_response_delay_seconds` / `ai.max_response_delay_seconds`**: Jittered latency window for AI chat messages (`4` to `14` seconds by default) so AI agents do not reply in robotic lockstep.
- **`ai.max_messages_per_round`**: Upper cap on messages per AI participant per round (`2` by default).

---

## 4. Running Automated Tests

An automated `pytest` integration and unit test suite (`backend/tests/test_experiment.py`) verifies condition loading, slot overflow rejection, strict AI blindness, phase enforcement, self-vote/duplicate-vote guards, full 2-round completion, and tie-breaking:

```bash
docker compose exec backend pytest -v
```

---

## 5. Architecture, Key Decisions & 4-Hour Trade-Offs

### Development Process (8 Milestones: 0–7)
The system was built incrementally across 8 verified milestones—from architecture & Docker scaffold (**Milestone 0**), PostgreSQL schema & atomic slot joining (**Milestone 1**), server-authoritative phase state machine (**Milestone 2**), authenticated WebSocket chat (**Milestone 3**), AI discussion agents (**Milestone 4**), blind voting & tie-breaking (**Milestone 5**), React UI integration (**Milestone 6**), to automated `pytest` verification & documentation (**Milestone 7**).

### Key Design Decisions
- **Server-Authoritative State Machine**: Every phase transition (`WAITING` → `ROUND_1_DISCUSSION` → `ROUND_1_VOTING` → `ROUND_2_DISCUSSION` → `ROUND_2_VOTING` → `COMPLETED`) is guarded by a per-session `asyncio.Lock` and server-owned UTC timestamps (`round_ends_at`), preventing race conditions and client timer drift.
- **Zero AI Identity Leakage**: Internal columns (`participant_type`, `provider`, `model`, `token_hash`) are strictly isolated from public Pydantic DTOs. Clients only ever receive neutral slot IDs (`player_a`, `player_b`, `player_c`) and display names (`Player A`, `Player B`, `Player C`).
- **Reconnect Resynchronization**: WebSocket events push real-time updates (`new_message`, `vote_status`, `phase_changed`), while `GET /api/sessions/{session_id}` returns the full authoritative snapshot on page refresh or socket reconnect.
- **Extensible `AIAgent` Interface (`backend/app/ai_agent.py`)**: Abstracted behind `generate_response()` and `cast_vote()` so live LLM providers (e.g., OpenAI/Gemini) can be plugged in via `config.yml` without touching session or state-machine logic.

### Intentional Trade-Offs (4-Hour Scope)
- **Deterministic Offline AI Agent (`RuleBasedAIAgent`)**: Used a context-aware, non-repetitive rule-based agent with jittered delays instead of external LLM APIs so evaluators can run the platform offline immediately with zero API keys, zero network latency variance, and deterministic testability.
- **Single-Process In-Memory WebSocket Registry & Timers**: Scoped `WebSocketManager` and `asyncio` round timers in-process in FastAPI rather than introducing Redis pub/sub, keeping deployment self-contained in 3 containers (`frontend`, `backend`, `db`).
- **Lightweight Inline Styling**: Focused frontend effort on reliable state transitions, blind voting UX, and real-time synchronization rather than a heavy CSS framework.

---

## 6. Key API & WebSocket Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Service health and active `config.yml` summary |
| `GET` | `/api/sessions/active` | Fetch or auto-create the active experiment session |
| `POST` | `/api/sessions/active/reset` | Reset into a fresh session (optional `condition_key` body) |
| `POST` | `/api/sessions/{id}/join` | Claim next available human slot and receive participant token |
| `GET` | `/api/sessions/{id}` | Full public session state snapshot |
| `POST` | `/api/sessions/{id}/messages` | Post discussion message (`X-Participant-Token` header) |
| `POST` | `/api/sessions/{id}/vote` | Submit round vote (`X-Participant-Token` header) |
| `GET` | `/api/sessions/{id}/results` | Retrieve Round 1, Round 2, combined totals, and Decision Maker |
| `WS` | `/ws/sessions/{id}?token=...` | Authenticated real-time session event stream |