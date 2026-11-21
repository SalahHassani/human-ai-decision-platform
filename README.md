# Human–AI Group Decision-Making Experiment Platform

A reproducible, real-time web application for running a 3-participant group decision-making experiment across configurable human/AI compositions (**3 Humans**, **2 Humans + 1 AI**, or **1 Human + 2 AI**) and **10 structured workplace decision scenarios**. Participants interact under neutral identifiers (**Player A**, **Player B**, **Player C**) around a single **immutably locked discussion topic** across two timed discussion rounds and two blind voting rounds to elect a single **Decision Maker**.

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
   - **Available Discussion Topics**: `http://localhost:8000/api/topics`
   - **Interactive OpenAPI / Swagger Docs**: `http://localhost:8000/docs`

### Exposed Ports & Services

| Service | Container Port | Host Port | Protocol | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Frontend** (`React` + `Vite`) | `5173` | `5173` | HTTP | Participant web interface (`http://localhost:5173`) |
| **Backend** (`FastAPI` + `Uvicorn`) | `8000` | `8000` | HTTP / WS | REST API & WebSocket server (`ws://localhost:8000`) |
| **Database** (`PostgreSQL 16`) | `5432` | `5433` | TCP | Persistent session, locked topic, participant, message, vote, and result storage *(mapped to `5433` on host to prevent conflicts with any local Postgres instance)* |

---

## 2. Configuration, Scenarios & Topic Locking (`config.yml`, `config/ai_config.json` & `.env`)

Experiment rules live in `config.yml` (validated via Pydantic in `backend/app/config.py`), while all scenario definitions, AI personalities, strategies, and validation rules live in `config/ai_config.json` (validated via `backend/app/topic_loader.py`).

### Single Shared Topic & Immutable Topic Locking
- **10 Built-in Decision Scenarios (`config/ai_config.json`)**: Includes `remote_work_policy`, `meeting_scheduling`, `project_deadline`, `budget_allocation`, `team_leadership`, `hiring_decision`, `product_launch`, `workplace_conflict`, `technology_selection`, and `sustainability_decision`.
- **Immutable Session Lock**: When a session is created (`POST /api/sessions` or `POST /api/sessions/active/reset`), `selected_topic_id` and `topic_locked = true` are persisted on the session record.
- **Strict Enforcement**:
  - Attempting to alter a session's topic via `PATCH /api/sessions/{session_id}/topic` is rejected with **`409 Conflict`**.
  - Unknown or invalid `topic_id` values raise an explicit error (**`400 Bad Request`**) with **zero silent fallback** to another topic.
  - AI agents have no topic-selection or topic-switching methods and always read the session's locked topic.

### Switching Conditions & Locked Discussion Topics
1. **In the Web UI**: On the landing screen under **New Session Setup**, select any scenario from the **Select Discussion Topic** dropdown and click **Start with Topic**, or click **3 Humans** (`condition_1`), **2 Humans + 1 AI** (`condition_2`), or **1 Human + 2 AI** (`condition_3`) under **Switch Condition**.
2. **Via `.env`**: Set `EXPERIMENT_CONDITION=condition_1` (or `condition_2` / `condition_3`) and run `docker compose restart backend`.
3. **Via Admin REST API**:
   ```bash
   curl -X POST http://localhost:8000/api/sessions/active/reset \
     -H "Content-Type: application/json" \
     -H "X-Admin-Token: dev-admin-token" \
     -d '{"condition_key": "condition_3", "topic_id": "meeting_scheduling"}'
   ```

### Configurable Rules in `config.yml` & `config/ai_config.json`
- **Self-Voting Policy (`voting.allow_self_vote`)**: Set to `false` by default in both `config.yml` and `VotingSettings`—neither human nor AI participants can vote for themselves, and the UI hides the participant's own identity from selectable voting options.
- **Discussion Timer (`experiment.discussion_duration_seconds` / `discussion.discussion_duration_seconds`)**: Default `60` seconds per discussion round.
- **Number of Rounds (`experiment.rounds` / `discussion.rounds`)**: Default `2` discussion + voting cycles.
- **Tie-Breaking Priority (`voting.tie_break`)**: `[round_2_votes, alphabetical_order]`.
- **AI Response Timing & Word Bounds**: Jittered latency window (`4` to `14` seconds), `max_messages_per_round` (`2`), and strict word-count bounds (`12` to `75` words) validated before every AI message is persisted.
- **Demo / Admin Protection (`ADMIN_TOKEN`, `DEMO_MODE`)**: Administrative endpoints (`/reset`, `/advance`, and `/export.csv`) require the `X-Admin-Token` header (`dev-admin-token` by default in local demo mode).

---

## 3. Experimental Conditions & End-to-End Walkthrough

| Condition Key | Composition | Human Slots | AI Slots & Personalities | How to Test Locally |
| :--- | :--- | :--- | :--- | :--- |
| `condition_1` | **3 Humans** | Player A, B, C | None | Open `http://localhost:5173` in **3 separate browser tabs** and click **Join Active Session** in each. |
| `condition_2` | **2 Humans + 1 AI** | Player A, B | Player C (`analytical`) | Open `http://localhost:5173` in **2 separate browser tabs** and join in both. |
| `condition_3` | **1 Human + 2 AI** | Player A | Player B (`analytical`), Player C (`cooperative`) | Open `http://localhost:5173` in **1 browser tab** and click **Join Active Session** (starts immediately). |

*(Participant session tokens are stored in `sessionStorage`, so each browser tab acts as an independent participant.)*

### Verified End-to-End Demo Workflow (`1 Human + 2 AI`)
1. Open `http://localhost:5173`, choose a discussion topic (e.g., **Meeting Scheduling** or **Remote Work Policy**), click **Start with Topic**, select **1 Human + 2 AI**, and click **Join Active Session**.
2. You are assigned **Player A**, and the session transitions immediately to `ROUND_1_DISCUSSION` with the locked topic banner and a server-synchronized 60-second countdown.
3. Post a message in the chat; **Player B** and **Player C** respond automatically after jittered delays (`4–14s`) using neutral display names, distinct conversational personalities, and non-duplicate topic arguments/questions.
4. Let the 60-second timer expire automatically (or click **End Discussion Now** in the header during a live demo) to enter `ROUND_1_VOTING`.
5. Cast your blind vote for **Player B** or **Player C**. Intermediate UI status shows only submission progress (`1/3`, `2/3`, `3/3`), never vote targets.
6. Complete `ROUND_2_DISCUSSION` (where AI agents synthesize and reference Round 1 points) and `ROUND_2_VOTING` to reach `COMPLETED`, view the elected **Decision Maker** and round-by-round tally, and click **Download CSV** to export the session dataset (including `selected_topic_id`).

---

## 4. Architecture & Project Structure

```text
+-------------------------------------------------------------------+
|                   React + Vite Frontend (:5173)                   |
|  Lobby (Topic/Condition) | WaitingRoom | ChatRoom | Voting | Res  |
+---------------------------------+---------------------------------+
                                  | REST (HTTP) + WebSocket (/ws)
+---------------------------------v---------------------------------+
|                   FastAPI Modular Monolith (:8000)                |
|  - Server-Authoritative State Machine (per-session asyncio.Lock)  |
|  - Immutable Topic Loader & Cross-Topic Isolation Guard           |
|  - Public DTO Isolation (strips AI type, personality & tokens)    |
|  - Background Round Timers & 17-Strategy RuleBasedAIAgent Tasks   |
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
├── config.yml                      # Experimental conditions, timers, AI delays, voting rules
├── config/
│   └── ai_config.json              # 10 scenarios, 3 personalities, 17 strategies, validation rules
├── docker-compose.yml              # Multi-container orchestration (db, backend, frontend)
├── .env.example                    # Environment variable template (no real secrets)
├── ai_prompts.md                   # AI development log (models, tools, and prompts)
├── README.md                       # Setup, usage, architecture, and verification guide
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                 # FastAPI app initialization & lifespan startup
│   │   ├── config.py               # Pydantic validation for config.yml & env vars
│   │   ├── topic_loader.py         # Strict scenario loader & AI config validation (no fallback)
│   │   ├── models.py               # SQLAlchemy async ORM schema (with locked topic & context)
│   │   ├── schemas.py              # Blind public DTOs & request/response models
│   │   ├── service.py              # State machine, topic lock, timers, voting, WS, CSV export
│   │   ├── ai_agent.py             # Extensible AIAgent & 17-strategy humanized RuleBasedAIAgent
│   │   └── routes.py               # REST & WebSocket endpoints + admin auth guard
│   └── tests/
│       ├── test_experiment.py      # 10 core state machine, WebSocket, timer & CSV tests
│       └── test_topic_selection.py # 12 topic locking, isolation, personality & strategy tests
└── frontend/
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── App.jsx
        ├── hooks/useExperimentSocket.js
        ├── services/api.js
        └── components/
            ├── WaitingRoom.jsx
            ├── ChatRoom.jsx
            ├── VotingPanel.jsx
            └── ResultsView.jsx
```

---

## 5. Development Process & Key Design Decisions

### Incremental Build Milestones
- **Milestone 0 — Scaffold & Config**: Docker Compose setup (`db`, `backend`, `frontend`) and Pydantic-validated `config.yml`.
- **Milestone 1 — Persistence & Atomic Waiting Room**: PostgreSQL schema, SHA-256 participant tokens, and lock-protected slot assignment.
- **Milestone 2 — Server-Authoritative State Machine**: Enforced lifecycle (`WAITING` → `ROUND_1_DISCUSSION` → `ROUND_1_VOTING` → `ROUND_2_DISCUSSION` → `ROUND_2_VOTING` → `COMPLETED`) with server-owned UTC timers.
- **Milestone 3 — Real-Time WebSocket Chat**: Token-authenticated WebSocket stream with strict DTO blindness.
- **Milestone 4 — Single-Topic Locking & Humanized 17-Strategy AI Engine**: Immutable scenario lock (`config/ai_config.json`), distinct AI personalities (`analytical`, `cooperative`, `critical`), shared session context tracking to prevent duplicate arguments/questions, and Round 2 synthesis referencing Round 1.
- **Milestone 5 — Blind Voting & Tie-Breaking**: Single-vote-per-round constraint, hidden intermediate tallies, and deterministic winner resolution.
- **Milestone 6 — React Experiment UI**: Lobby topic/condition setup, locked scenario display across all phases, synchronized countdown timer, reconnect snapshot resync, self-vote exclusion in UI, and results view.
- **Milestone 7 — Hardening, Verification & CSV Export**: Admin token guards on demo/export controls, WebSocket reconnect tests, topic-tagged CSV research export, and 22 passing `pytest` tests.

### Key Design Decisions & Intentional Trade-Offs
- **Offline `RuleBasedAIAgent` behind an Extensible `AIAgent` Interface**: Allows evaluators to run the full platform immediately offline with zero external API keys, deterministic testability, and zero rate-limit variance. Every AI message uses natural conversational phrasing across 17 strategies while enforcing word bounds (`12–75` words) and cross-topic isolation. Live LLM providers can be added by implementing `generate_response()` and `cast_vote()` in `backend/app/ai_agent.py`.
- **Immutable Topic Lock with Zero Fallback**: Prevents mid-session topic drift or cross-topic contamination; invalid topic IDs fail explicitly (`400`) and mid-session topic mutation requests are rejected (`409`).
- **Deterministic Voting & Tie-Breaking**: Combined Round 1 + Round 2 votes determine the winner; ties break first by **Round 2 votes** (capturing post-deliberation consensus) and then **alphabetical slot order** (`player_a` < `player_b` < `player_c`).
- **Known Limitations (Single-Process Scope)**: WebSocket connections (`WebSocketManager`) and background timer/AI `asyncio.Task` registries are stored in-memory within the single FastAPI worker process rather than Redis pub/sub, keeping deployment self-contained in 3 containers.

---

## 6. API & WebSocket Reference

| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/health` | Public | Health check and active configuration summary |
| `GET` | `/api/topics` | Public | List all 10 available decision scenarios and options |
| `GET` | `/api/sessions/active` | Public | Retrieve or auto-create the active session |
| `POST` | `/api/sessions` | Public | Create a new session with `condition_key` and locked `topic_id` |
| `PATCH` | `/api/sessions/{id}/topic` | Public | Enforces topic immutability (`409 Conflict` if changing locked topic) |
| `POST` | `/api/sessions/{id}/join` | Public | Claim next open human slot and receive `participant_token` |
| `GET` | `/api/sessions/{id}` | Public | Full authoritative session snapshot (used on load/reconnect) |
| `POST` | `/api/sessions/{id}/messages` | `X-Participant-Token` | Post a message during an active discussion round |
| `POST` | `/api/sessions/{id}/vote` | `X-Participant-Token` | Submit a blind vote during an active voting round |
| `GET` | `/api/sessions/{id}/results` | Public | Retrieve final tallies and Decision Maker (`COMPLETED` only) |
| `POST` | `/api/sessions/active/reset` | `X-Admin-Token` | Reset into a fresh session (supports `condition_key` & `topic_id`) |
| `POST` | `/api/sessions/{id}/advance` | `X-Admin-Token` | Demo helper to immediately expire an active discussion timer |
| `GET` | `/api/sessions/{id}/export.csv` | `X-Admin-Token` | Download anonymized research CSV (including `selected_topic_id`) for a `COMPLETED` session |
| `WS` | `/ws/sessions/{id}?token=...` | Query `token` | Real-time events (`participant_joined`, `experiment_started`, `new_message`, `phase_changed`, `vote_status`, `experiment_completed`) |

---

## 7. Running Automated Tests

Run the full **22-test** integration and unit suite inside the backend container:

```bash
docker compose exec backend pytest -v
```

- **`tests/test_experiment.py` (10 tests)**: Verifies condition loading, slot overflow (`409`), strict AI/personality blindness across REST/WebSocket/CSV payloads, phase guards, no-self-voting defaults and enforcement, tie-breaking, admin token protection (`403`), real timer expiration/cancellation, WebSocket reconnection sync, and CSV research export.
- **`tests/test_topic_selection.py` (12 tests)**: Verifies all 10 scenarios load cleanly, session topic locking (`409` on change), strict no-fallback rejection (`400` / `TopicLoadError`), distinct AI personality assignment per condition, cross-topic isolation across all 10 scenarios, duplicate argument/question prevention, Round 2 synthesis referencing Round 1, all 17 strategies, and `selected_topic_id` persistence in CSV exports.