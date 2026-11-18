# Human–AI Group Decision-Making Experiment Platform

A reproducible, real-time web application for running a 3-participant group decision-making experiment across configurable human/AI compositions (**3 Humans**, **2 Humans + 1 AI**, or **1 Human + 2 AI**). Participants interact under neutral identifiers (**Player A**, **Player B**, **Player C**) across two timed discussion rounds and two blind voting rounds to elect a single **Decision Maker**.

---

## 1. Quick Start (Installation & Running from Scratch)

### Prerequisites
- **Docker** & **Docker Compose**
- **Git**

### Step-by-Step Startup
1. **Clone the repository**:
   ```bash
   git clone https://github.com/SalahHassani/human-ai-decision-platform.git
   cd human-ai-decision-platform
   ```

2. **Create local environment file (optional)**:
   ```bash
   cp .env.example .env
   ```
   *(All services run out-of-the-box with sensible defaults even without creating `.env`.)*

3. **Build and start all containers**:
   ```bash
   docker compose up --build -d
   ```

4. **Open the application**:
   - **Participant Experiment UI**: `http://localhost:5173`
   - **Backend Health & Active Config**: `http://localhost:8000/api/health`
   - **Interactive OpenAPI / Swagger Docs**: `http://localhost:8000/docs`

### Exposed Ports & Services

| Service | Container Port | Host Port | Protocol | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Frontend** (`React` + `Vite`) | `5173` | `5173` | HTTP | Participant web interface (`http://localhost:5173`) |
| **Backend** (`FastAPI` + `Uvicorn`) | `8000` | `8000` | HTTP / WS | REST API & WebSocket server (`ws://localhost:8000`) |
| **Database** (`PostgreSQL 16`) | `5432` | `5433` | TCP | Persistent session, participant, message, vote, and result storage *(mapped to `5433` on host to prevent conflicts with any local Postgres instance)* |

---

## 2. Configuration & Customization (`config.yml` & `.env`)

All experiment rules live in `config.yml` and are validated at startup via Pydantic (`backend/app/config.py`).

### Switching Experimental Conditions
1. **In the Web UI**: On the landing screen, click **3 Humans** (`condition_1`), **2 Humans + 1 AI** (`condition_2`), or **1 Human + 2 AI** (`condition_3`) under **Switch Condition (Demo)**.
2. **Via `.env`**: Set `EXPERIMENT_CONDITION=condition_1` (or `condition_2` / `condition_3`) and run `docker compose restart backend`.
3. **Via Admin REST API**:
   ```bash
   curl -X POST http://localhost:8000/api/sessions/active/reset \
     -H "Content-Type: application/json" \
     -H "X-Admin-Token: dev-admin-token" \
     -d '{"condition_key": "condition_3"}'
   ```

### Configurable Rules in `config.yml` & `.env`
- **Self-Voting Policy (`voting.allow_self_vote`)**: Set to `false` by default in both `config.yml` and `VotingSettings`—neither human nor AI participants can vote for themselves, and the UI hides the participant's own identity from selectable voting options. Set to `true` in `config.yml` to permit self-voting.
- **Discussion Timer (`experiment.discussion_duration_seconds`)**: Default `60` seconds per discussion round.
- **Number of Rounds (`experiment.rounds`)**: Default `2` discussion + voting cycles.
- **Tie-Breaking Priority (`voting.tie_break`)**: `[round_2_votes, alphabetical_order]`.
- **AI Response Timing (`ai.min_response_delay_seconds` / `ai.max_response_delay_seconds`)**: Jittered latency window (`4` to `14` seconds) and `ai.max_messages_per_round` (`2`) so AI participants reply naturally without robotic lockstep.
- **Demo / Admin Protection (`ADMIN_TOKEN`, `DEMO_MODE`)**: Administrative endpoints (`/reset`, `/advance`, and `/export.csv`) require the `X-Admin-Token` header (`dev-admin-token` by default in local demo mode).

---

## 3. Experimental Conditions & End-to-End Walkthrough

| Condition Key | Composition | Human Slots | AI Slots | How to Test Locally |
| :--- | :--- | :--- | :--- | :--- |
| `condition_1` | **3 Humans** | Player A, B, C | None | Open `http://localhost:5173` in **3 separate browser tabs** and click **Join Active Session** in each. |
| `condition_2` | **2 Humans + 1 AI** | Player A, B | Player C | Open `http://localhost:5173` in **2 separate browser tabs** and join in both. |
| `condition_3` | **1 Human + 2 AI** | Player A | Player B, C | Open `http://localhost:5173` in **1 browser tab** and click **Join Active Session** (starts immediately). |

*(Participant session tokens are stored in `sessionStorage`, so each browser tab acts as an independent participant.)*

### Verified End-to-End Demo Workflow (`1 Human + 2 AI`)
1. Open `http://localhost:5173`, select **1 Human + 2 AI**, and click **Join Active Session**.
2. You are assigned **Player A**, and the session transitions immediately to `ROUND_1_DISCUSSION` with a server-synchronized 60-second countdown.
3. Post a message in the chat; **Player B** and **Player C** respond automatically after jittered delays (`4–14s`) using neutral display names.
4. Let the 60-second timer expire automatically (or click **End Discussion Now** in the header during a live demo) to enter `ROUND_1_VOTING`.
5. Cast your blind vote for **Player B** or **Player C**. Intermediate UI status shows only submission progress (`1/3`, `2/3`, `3/3`), never vote targets.
6. Complete `ROUND_2_DISCUSSION` and `ROUND_2_VOTING` to reach `COMPLETED`, view the elected **Decision Maker** and round-by-round tally, and click **Download CSV** to export the session dataset.

---

## 4. Architecture & Project Structure

```text
+-------------------------------------------------------------------+
|                   React + Vite Frontend (:5173)                   |
|  WaitingRoom | DiscussionPanel | VotingPanel | ResultsView        |
+---------------------------------+---------------------------------+
                                  | REST (HTTP) + WebSocket (/ws)
+---------------------------------v---------------------------------+
|                   FastAPI Modular Monolith (:8000)                |
|  - Server-Authoritative State Machine (per-session asyncio.Lock)  |
|  - Public DTO Isolation (strictly strips AI/token metadata)       |
|  - Background Round Timers & Offline RuleBasedAIAgent Tasks       |
|  - Admin-Protected Controls & CSV Research Export                 |
+---------------------------------+---------------------------------+
                                  | SQLAlchemy Async (asyncpg)
+---------------------------------v---------------------------------+
|                      PostgreSQL 16 (:5432 -> :5433)               |
|  sessions | participants | messages | votes | experiment_results  |
+-------------------------------------------------------------------+
```

```text
human-ai-decision-platform/
├── config.yml                  # Experimental conditions, timers, AI delays, voting rules
├── docker-compose.yml          # Multi-container orchestration (db, backend, frontend)
├── .env.example                # Environment variable template (no real secrets)
├── ai_prompts.md               # AI development log (models, tools, and prompts)
├── README.md                   # Setup, usage, architecture, and verification guide
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py             # FastAPI app initialization & lifespan startup
│   │   ├── config.py           # Pydantic validation for config.yml & env vars
│   │   ├── models.py           # SQLAlchemy async ORM schema
│   │   ├── schemas.py          # Blind public DTOs & request/response models
│   │   ├── service.py          # State machine, timers, voting, WebSockets, CSV export
│   │   ├── ai_agent.py         # Extensible AIAgent interface & RuleBasedAIAgent
│   │   └── routes.py           # REST & WebSocket endpoints + admin auth guard
│   └── tests/
│       └── test_experiment.py  # 10 automated integration & unit tests (pytest)
└── frontend/
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── App.jsx
        ├── hooks/useExperimentSocket.js
        ├── services/api.js
        └── components/
            ├── WaitingRoom.jsx
            ├── DiscussionPanel.jsx
            ├── VotingPanel.jsx
            └── ResultsView.jsx
```

---

## 5. Development Process (8 Milestones) & 4-Hour Trade-Offs

### Incremental 8-Milestone Build
- **Milestone 0 — Scaffold & Config**: Docker Compose setup (`db`, `backend`, `frontend`) and Pydantic-validated `config.yml`.
- **Milestone 1 — Persistence & Atomic Waiting Room**: PostgreSQL schema, SHA-256 participant tokens, and lock-protected slot assignment.
- **Milestone 2 — Server-Authoritative State Machine**: Enforced lifecycle (`WAITING` → `ROUND_1_DISCUSSION` → `ROUND_1_VOTING` → `ROUND_2_DISCUSSION` → `ROUND_2_VOTING` → `COMPLETED`) with server-owned UTC timers.
- **Milestone 3 — Real-Time WebSocket Chat**: Token-authenticated WebSocket stream with strict DTO blindness.
- **Milestone 4 — AI Discussion Agents**: Context-aware `RuleBasedAIAgent` with non-repetitive templates and jittered delays.
- **Milestone 5 — Blind Voting & Tie-Breaking**: Single-vote-per-round constraint, hidden intermediate tallies, and deterministic winner resolution.
- **Milestone 6 — React Experiment UI**: Synchronized countdown timer, reconnect snapshot resync, self-vote exclusion in UI, and results view.
- **Milestone 7 — Hardening, Verification & CSV Export**: Admin token guards on demo/export controls, WebSocket reconnect tests, CSV research export, and 10 passing `pytest` tests.

### Key Design Decisions & Intentional Trade-Offs
- **Offline `RuleBasedAIAgent` behind an Extensible `AIAgent` Interface**: Allows evaluators to run the full platform immediately offline with zero external API keys, deterministic testability, and zero rate-limit variance. Live LLM providers (e.g., OpenAI/Gemini) can be added by implementing `generate_response()` and `cast_vote()` in `backend/app/ai_agent.py`.
- **Deterministic Voting & Tie-Breaking**: Combined Round 1 + Round 2 votes determine the winner; ties break first by **Round 2 votes** (capturing post-deliberation consensus) and then **alphabetical slot order** (`player_a` < `player_b` < `player_c`).
- **Known Limitations (Single-Process Scope)**: WebSocket connections (`WebSocketManager`) and background timer/AI `asyncio.Task` registries are stored in-memory within the single FastAPI worker process rather than Redis pub/sub, keeping deployment self-contained in 3 containers for a 4-hour assessment scope.

---

## 6. API & WebSocket Reference

| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/health` | Public | Health check and active configuration summary |
| `GET` | `/api/sessions/active` | Public | Retrieve or auto-create the active session |
| `POST` | `/api/sessions` | Public | Create a new session for a specified `condition_key` |
| `POST` | `/api/sessions/{id}/join` | Public | Claim next open human slot and receive `participant_token` |
| `GET` | `/api/sessions/{id}` | Public | Full authoritative session snapshot (used on load/reconnect) |
| `POST` | `/api/sessions/{id}/messages` | `X-Participant-Token` | Post a message during an active discussion round |
| `POST` | `/api/sessions/{id}/vote` | `X-Participant-Token` | Submit a blind vote during an active voting round |
| `GET` | `/api/sessions/{id}/results` | Public | Retrieve final tallies and Decision Maker (`COMPLETED` only) |
| `POST` | `/api/sessions/active/reset` | `X-Admin-Token` | Reset into a fresh session (supports `condition_key` override) |
| `POST` | `/api/sessions/{id}/advance` | `X-Admin-Token` | Demo helper to immediately expire an active discussion timer |
| `GET` | `/api/sessions/{id}/export.csv` | `X-Admin-Token` | Download anonymized research CSV for a `COMPLETED` session |
| `WS` | `/ws/sessions/{id}?token=...` | Query `token` | Real-time events (`participant_joined`, `experiment_started`, `new_message`, `phase_changed`, `vote_status`, `experiment_completed`) |

---

## 7. Running Automated Tests

Run the full 10-test integration and unit suite inside the backend container:

```bash
docker compose exec backend pytest -v
```

The test suite verifies condition loading, slot overflow (`409`), strict AI identity blindness across REST/WebSocket/CSV payloads, phase guards, no-self-voting defaults and enforcement, tie-breaking, admin token protection (`403`), real timer expiration/cancellation, WebSocket reconnection sync, and CSV research export.