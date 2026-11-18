import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import load_active_config
from app.main import app
from app.models import engine, init_db
from app.service import ExperimentService


@pytest_asyncio.fixture
async def client():
    await engine.dispose()
    app.state.config = load_active_config(condition_key="condition_2")
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


def _assert_no_ai_leakage(payload: dict) -> None:
    serialized = str(payload).lower()
    assert "participant_type" not in serialized
    assert "rule_based" not in serialized
    assert "token_hash" not in serialized


@pytest.mark.asyncio
async def test_health_and_conditions(client: AsyncClient):
    res = await client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["condition_key"] == "condition_2"

    for cond, expected_humans in [("condition_1", 3), ("condition_2", 2), ("condition_3", 1)]:
        created = await client.post("/api/sessions", json={"condition_key": cond})
        assert created.status_code == 201
        data = created.json()
        assert data["required_humans"] == expected_humans
        assert data["phase"] == "WAITING"
        _assert_no_ai_leakage(data)


@pytest.mark.asyncio
async def test_waiting_room_transitions_and_slot_overflow(client: AsyncClient):
    created = await client.post("/api/sessions", json={"condition_key": "condition_2"})
    session_id = created.json()["session_id"]

    j1 = await client.post(f"/api/sessions/{session_id}/join")
    assert j1.status_code == 200
    assert j1.json()["participant"]["id"] == "player_a"
    assert j1.json()["session_state"]["phase"] == "WAITING"

    j2 = await client.post(f"/api/sessions/{session_id}/join")
    assert j2.status_code == 200
    assert j2.json()["participant"]["id"] == "player_b"
    assert j2.json()["session_state"]["phase"] == "ROUND_1_DISCUSSION"
    assert j2.json()["session_state"]["round_ends_at"] is not None

    j3 = await client.post(f"/api/sessions/{session_id}/join")
    assert j3.status_code == 409


@pytest.mark.asyncio
async def test_phase_guards_and_message_blindness(client: AsyncClient):
    created = await client.post("/api/sessions", json={"condition_key": "condition_3"})
    session_id = created.json()["session_id"]
    joined = (await client.post(f"/api/sessions/{session_id}/join")).json()
    headers = {"X-Participant-Token": joined["participant_token"]}

    # Unauthenticated message rejected
    unauth = await client.post(f"/api/sessions/{session_id}/messages", json={"content": "Hello"})
    assert unauth.status_code == 401

    # Valid message during ROUND_1_DISCUSSION
    msg = await client.post(
        f"/api/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "Let's choose someone fair."},
    )
    assert msg.status_code == 201
    assert msg.json()["sender_id"] == "player_a"
    assert msg.json()["sender_name"] == "Player A"
    _assert_no_ai_leakage(msg.json())

    # Voting rejected during discussion
    early_vote = await client.post(
        f"/api/sessions/{session_id}/vote",
        headers=headers,
        json={"target_id": "player_b"},
    )
    assert early_vote.status_code == 409

    # Advance to ROUND_1_VOTING -> messaging now rejected
    adv = await client.post(
        f"/api/sessions/{session_id}/advance",
        headers={"X-Admin-Token": app.state.config.admin_token},
    )
    assert adv.status_code == 200
    assert adv.json()["phase"] == "ROUND_1_VOTING"

    late_msg = await client.post(
        f"/api/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "Late message"},
    )
    assert late_msg.status_code == 409


@pytest.mark.asyncio
async def test_full_two_round_election_and_vote_constraints(client: AsyncClient):
    # Use condition_1 (3 humans) for deterministic synchronous vote assertions
    created = await client.post("/api/sessions", json={"condition_key": "condition_1"})
    session_id = created.json()["session_id"]
    admin_headers = {"X-Admin-Token": app.state.config.admin_token}

    p_a = (await client.post(f"/api/sessions/{session_id}/join")).json()
    p_b = (await client.post(f"/api/sessions/{session_id}/join")).json()
    p_c = (await client.post(f"/api/sessions/{session_id}/join")).json()

    h_a = {"X-Participant-Token": p_a["participant_token"]}
    h_b = {"X-Participant-Token": p_b["participant_token"]}
    h_c = {"X-Participant-Token": p_c["participant_token"]}

    # Round 1 Discussion -> Round 1 Voting
    await client.post(f"/api/sessions/{session_id}/advance", headers=admin_headers)

    # Self-vote rejected
    self_v = await client.post(
        f"/api/sessions/{session_id}/vote", headers=h_a, json={"target_id": "player_a"}
    )
    assert self_v.status_code == 400

    # Valid Round 1 votes (A->B, B->C, C->B)
    assert (
        await client.post(
            f"/api/sessions/{session_id}/vote", headers=h_a, json={"target_id": "player_b"}
        )
    ).status_code == 201

    # Duplicate vote rejected
    dup = await client.post(
        f"/api/sessions/{session_id}/vote", headers=h_a, json={"target_id": "player_c"}
    )
    assert dup.status_code == 409

    assert (
        await client.post(
            f"/api/sessions/{session_id}/vote", headers=h_b, json={"target_id": "player_c"}
        )
    ).status_code == 201
    assert (
        await client.post(
            f"/api/sessions/{session_id}/vote", headers=h_c, json={"target_id": "player_b"}
        )
    ).status_code == 201

    # Automatically transitioned to ROUND_2_DISCUSSION
    s_r2 = (await client.get(f"/api/sessions/{session_id}")).json()
    assert s_r2["phase"] == "ROUND_2_DISCUSSION"
    assert s_r2["current_round"] == 2

    # Advance to ROUND_2_VOTING and cast Round 2 votes (A->C, B->C, C->B)
    await client.post(f"/api/sessions/{session_id}/advance", headers=admin_headers)
    await client.post(
        f"/api/sessions/{session_id}/vote", headers=h_a, json={"target_id": "player_c"}
    )
    await client.post(
        f"/api/sessions/{session_id}/vote", headers=h_b, json={"target_id": "player_c"}
    )
    await client.post(
        f"/api/sessions/{session_id}/vote", headers=h_c, json={"target_id": "player_b"}
    )

    # Verify COMPLETED state and tie-breaker (B and C both have 3 total votes; C wins on Round 2 votes 2 vs 1)
    res = await client.get(f"/api/sessions/{session_id}/results")
    assert res.status_code == 200
    result_data = res.json()
    assert result_data["totals_by_participant"] == {"player_a": 0, "player_b": 3, "player_c": 3}
    assert result_data["round_1_totals"] == {"player_a": 0, "player_b": 2, "player_c": 1}
    assert result_data["round_2_totals"] == {"player_a": 0, "player_b": 1, "player_c": 2}
    assert result_data["decision_maker_id"] == "player_c"
    assert result_data["decision_maker_name"] == "Player C"


def test_tie_breaker_unit():
    # Equal total (2 each) and equal Round 2 (1 each) -> falls back to alphabetical slot ('player_a')
    totals, winner = ExperimentService._compute_election_winner(
        round_1_totals={"player_a": 1, "player_b": 1, "player_c": 1},
        round_2_totals={"player_a": 1, "player_b": 1, "player_c": 1},
    )
    assert totals == {"player_a": 2, "player_b": 2, "player_c": 2}
    assert winner == "player_a"


@pytest.mark.asyncio
async def test_no_self_voting_defaults_and_ai_peer_selection():
    from app.ai_agent import AgentDecisionContext, DiscussionMessageContext, RuleBasedAIAgent
    from app.config import VotingSettings

    # Verify default config enforces allow_self_vote = False
    default_voting = VotingSettings()
    assert default_voting.allow_self_vote is False

    # Verify AI agent never selects its own slot even if it sent the most messages
    agent = RuleBasedAIAgent()
    ctx = AgentDecisionContext(
        session_id="test-session",
        self_slot_id="player_b",
        self_display_name="Player B",
        round_number=1,
        message_index=0,
        participant_slots=["player_a", "player_b", "player_c"],
        messages=[
            DiscussionMessageContext("player_b", "Player B", 1, "Msg 1"),
            DiscussionMessageContext("player_b", "Player B", 1, "Msg 2"),
            DiscussionMessageContext("player_c", "Player C", 1, "Msg 3"),
        ],
    )
    chosen = await agent.cast_vote(ctx)
    assert chosen != "player_b"
    assert chosen == "player_c"


@pytest.mark.asyncio
async def test_demo_controls_require_admin_token(client: AsyncClient):
    admin_headers = {"X-Admin-Token": app.state.config.admin_token}
    created = await client.post("/api/sessions", json={"condition_key": "condition_3"})
    session_id = created.json()["session_id"]
    await client.post(f"/api/sessions/{session_id}/join")

    # Unauthenticated reset and advance must be rejected with 403
    unauth_reset = await client.post("/api/sessions/active/reset")
    assert unauth_reset.status_code == 403

    unauth_advance = await client.post(f"/api/sessions/{session_id}/advance")
    assert unauth_advance.status_code == 403

    # Wrong admin token must also be rejected with 403
    bad_advance = await client.post(
        f"/api/sessions/{session_id}/advance",
        headers={"X-Admin-Token": "wrong-token"},
    )
    assert bad_advance.status_code == 403

    # Valid admin token succeeds
    ok_advance = await client.post(
        f"/api/sessions/{session_id}/advance",
        headers=admin_headers,
    )
    assert ok_advance.status_code == 200
    assert ok_advance.json()["phase"] == "ROUND_1_VOTING"


@pytest.mark.asyncio
async def test_automatic_discussion_timer_and_cancellation(client: AsyncClient):
    import asyncio
    from uuid import UUID

    created = await client.post("/api/sessions", json={"condition_key": "condition_3"})
    session_id = created.json()["session_id"]
    await client.post(f"/api/sessions/{session_id}/join")

    # Schedule a short 0.25s timer to verify real timer expiration without /advance
    sid_uuid = UUID(session_id)
    ExperimentService.schedule_discussion_timer(
        sid_uuid, "ROUND_1_DISCUSSION", duration_seconds=0.25
    )

    # Before expiry: still in ROUND_1_DISCUSSION
    await asyncio.sleep(0.08)
    mid = (await client.get(f"/api/sessions/{session_id}")).json()
    assert mid["phase"] == "ROUND_1_DISCUSSION"

    # After expiry: automatically transitions to ROUND_1_VOTING
    await asyncio.sleep(0.25)
    after = (await client.get(f"/api/sessions/{session_id}")).json()
    assert after["phase"] == "ROUND_1_VOTING"

    # Verify cancelled timer cannot advance a subsequent phase
    ExperimentService.schedule_discussion_timer(
        sid_uuid, "ROUND_1_VOTING", duration_seconds=0.15
    )
    ExperimentService.cancel_timer(sid_uuid)
    await asyncio.sleep(0.22)
    still_voting = (await client.get(f"/api/sessions/{session_id}")).json()
    assert still_voting["phase"] == "ROUND_1_VOTING"

def test_websocket_broadcasts_and_reconnection_sync():
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    app.state.config = load_active_config(condition_key="condition_2")
    admin_headers = {"X-Admin-Token": app.state.config.admin_token}

    with TestClient(app) as tc:
        # Create a 2-human + 1-AI session and join both human slots
        created = tc.post("/api/sessions", json={"condition_key": "condition_2"})
        assert created.status_code == 201
        session_id = created.json()["session_id"]

        p_a = tc.post(f"/api/sessions/{session_id}/join").json()
        p_b = tc.post(f"/api/sessions/{session_id}/join").json()
        tok_a = p_a["participant_token"]
        tok_b = p_b["participant_token"]

        # 1. Invalid token on WebSocket must be rejected
        with pytest.raises(WebSocketDisconnect):
            with tc.websocket_connect(f"/ws/sessions/{session_id}?token=invalid-token") as bad_ws:
                bad_ws.receive_json()

        # 2. Connect Player A and Player B over WebSocket
        with tc.websocket_connect(f"/ws/sessions/{session_id}?token={tok_a}") as ws_a:
            with tc.websocket_connect(f"/ws/sessions/{session_id}?token={tok_b}") as ws_b:
                # Drain any initial presence/sync frames if emitted
                msg_res = tc.post(
                    f"/api/sessions/{session_id}/messages",
                    headers={"X-Participant-Token": tok_a},
                    json={"content": "Hello Player B and Player C!"},
                )
                assert msg_res.status_code == 201

                # Player B receives the real-time new_message broadcast without AI leakage
                received_events = []
                for _ in range(5):
                    frame = ws_b.receive_json()
                    _assert_no_ai_leakage(frame)
                    received_events.append(frame)
                    if frame.get("event") == "new_message" and frame.get("payload", {}).get("content") == "Hello Player B and Player C!":
                        break

                assert any(
                    e.get("event") == "new_message"
                    and e.get("payload", {}).get("sender_id") == "player_a"
                    for e in received_events
                )

            # 3. Simulate Player B disconnecting (browser refresh / temporary network drop)
            # While Player B is offline, Player A posts another message and phase advances to voting
            msg2_res = tc.post(
                f"/api/sessions/{session_id}/messages",
                headers={"X-Participant-Token": tok_a},
                json={"content": "Message sent while Player B was disconnected"},
            )
            assert msg2_res.status_code == 201

            adv_res = tc.post(f"/api/sessions/{session_id}/advance", headers=admin_headers)
            assert adv_res.status_code == 200
            assert adv_res.json()["phase"] == "ROUND_1_VOTING"

            # Player A (still connected) receives the phase change broadcast
            phase_frames = []
            for _ in range(5):
                frame = ws_a.receive_json()
                _assert_no_ai_leakage(frame)
                phase_frames.append(frame)
                if frame.get("event") == "phase_changed":
                    break
            assert any(e.get("event") == "phase_changed" for e in phase_frames)

        # 4. Player B reconnects and resynchronizes full session snapshot
        resync_state = tc.get(f"/api/sessions/{session_id}").json()
        assert resync_state["phase"] == "ROUND_1_VOTING"
        contents = [m["content"] for m in resync_state["messages"]]
        assert "Hello Player B and Player C!" in contents
        assert "Message sent while Player B was disconnected" in contents
        # Ensure no duplicate message IDs in resynchronized history
        msg_ids = [m["id"] for m in resync_state["messages"]]
        assert len(msg_ids) == len(set(msg_ids))

        with tc.websocket_connect(f"/ws/sessions/{session_id}?token={tok_b}") as ws_b_reconnected:
            vote_res = tc.post(
                f"/api/sessions/{session_id}/vote",
                headers={"X-Participant-Token": tok_a},
                json={"target_id": "player_b"},
            )
            assert vote_res.status_code == 201

            vote_frames = []
            for _ in range(5):
                frame = ws_b_reconnected.receive_json()
                _assert_no_ai_leakage(frame)
                vote_frames.append(frame)
                if frame.get("event") == "vote_status":
                    break
            assert any(e.get("event") == "vote_status" for e in vote_frames)



@pytest.mark.asyncio
async def test_csv_research_export_security_and_contents(client: AsyncClient):
    import csv
    import io

    admin_headers = {"X-Admin-Token": app.state.config.admin_token}
    created = await client.post("/api/sessions", json={"condition_key": "condition_1"})
    session_id = created.json()["session_id"]

    p_a = (await client.post(f"/api/sessions/{session_id}/join")).json()
    p_b = (await client.post(f"/api/sessions/{session_id}/join")).json()
    p_c = (await client.post(f"/api/sessions/{session_id}/join")).json()

    h_a = {"X-Participant-Token": p_a["participant_token"]}
    h_b = {"X-Participant-Token": p_b["participant_token"]}
    h_c = {"X-Participant-Token": p_c["participant_token"]}

    # 1. Unauthenticated export rejected with 403
    unauth = await client.get(f"/api/sessions/{session_id}/export.csv")
    assert unauth.status_code == 403

    # 2. Incomplete session export rejected with 409
    incomplete = await client.get(
        f"/api/sessions/{session_id}/export.csv", headers=admin_headers
    )
    assert incomplete.status_code == 409

    # Post 1 message and complete both voting rounds
    await client.post(
        f"/api/sessions/{session_id}/messages",
        headers=h_a,
        json={"content": "I nominate Player B for clear reasoning."},
    )
    await client.post(f"/api/sessions/{session_id}/advance", headers=admin_headers)
    await client.post(f"/api/sessions/{session_id}/vote", headers=h_a, json={"target_id": "player_b"})
    await client.post(f"/api/sessions/{session_id}/vote", headers=h_b, json={"target_id": "player_c"})
    await client.post(f"/api/sessions/{session_id}/vote", headers=h_c, json={"target_id": "player_b"})

    await client.post(f"/api/sessions/{session_id}/advance", headers=admin_headers)
    await client.post(f"/api/sessions/{session_id}/vote", headers=h_a, json={"target_id": "player_b"})
    await client.post(f"/api/sessions/{session_id}/vote", headers=h_b, json={"target_id": "player_c"})
    await client.post(f"/api/sessions/{session_id}/vote", headers=h_c, json={"target_id": "player_b"})

    # 3. Completed session export succeeds with text/csv and contains zero secrets
    exported = await client.get(
        f"/api/sessions/{session_id}/export.csv", headers=admin_headers
    )
    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    raw_csv = exported.text

    # Privacy checks: no participant tokens, token hashes, or AI provider fields
    assert p_a["participant_token"] not in raw_csv
    assert p_b["participant_token"] not in raw_csv
    assert p_c["participant_token"] not in raw_csv
    assert "token_hash" not in raw_csv.lower()
    assert "participant_type" not in raw_csv.lower()
    assert "rule_based" not in raw_csv.lower()

    rows = list(csv.DictReader(io.StringIO(raw_csv)))
    # 1 message + 6 votes (3 per round * 2 rounds) = 7 rows
    assert len(rows) == 7
    assert rows[0]["record_type"] == "message"
    assert rows[0]["actor_id"] == "player_a"
    assert rows[0]["message_content"] == "I nominate Player B for clear reasoning."
    assert rows[0]["decision_maker_id"] == "player_b"
    assert rows[0]["player_b_total_votes"] == "4"
    assert sum(1 for r in rows if r["record_type"] == "vote") == 6

    