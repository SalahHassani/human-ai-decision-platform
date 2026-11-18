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
    adv = await client.post(f"/api/sessions/{session_id}/advance")
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

    p_a = (await client.post(f"/api/sessions/{session_id}/join")).json()
    p_b = (await client.post(f"/api/sessions/{session_id}/join")).json()
    p_c = (await client.post(f"/api/sessions/{session_id}/join")).json()

    h_a = {"X-Participant-Token": p_a["participant_token"]}
    h_b = {"X-Participant-Token": p_b["participant_token"]}
    h_c = {"X-Participant-Token": p_c["participant_token"]}

    # Round 1 Discussion -> Round 1 Voting
    await client.post(f"/api/sessions/{session_id}/advance")

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
    await client.post(f"/api/sessions/{session_id}/advance")
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