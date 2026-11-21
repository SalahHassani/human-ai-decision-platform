import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.ai_agent import (
    AgentDecisionContext,
    DiscussionMessageContext,
    RuleBasedAIAgent,
)
from app.config import load_active_config
from app.main import app
from app.models import AsyncSessionLocal, Participant, engine, init_db
from app.service import ExperimentService
from app.topic_loader import TopicLoadError, TopicLoader, get_ai_config


@pytest_asyncio.fixture
async def client():
    ExperimentService.cancel_all_tasks()
    await engine.dispose()
    app.state.config = load_active_config(condition_key="condition_2")
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    ExperimentService.cancel_all_tasks()
    await engine.dispose()


def _assert_no_internal_leakage(payload: dict) -> None:
    serialized = str(payload).lower()
    assert "participant_type" not in serialized
    assert "rule_based" not in serialized
    assert "token_hash" not in serialized
    assert '"personality"' not in serialized


@pytest.mark.asyncio
async def test_01_list_topics_returns_all_configured_scenarios(client: AsyncClient):
    res = await client.get("/api/topics")
    assert res.status_code == 200
    topics = res.json()
    assert len(topics) >= 10
    topic_ids = {t["topic_id"] for t in topics}
    assert "remote_work_policy" in topic_ids
    assert "meeting_scheduling" in topic_ids
    for t in topics:
        assert t["title"]
        assert t["description"]
        assert t["main_question"]
        assert len(t["options"]) >= 2


@pytest.mark.asyncio
async def test_02_session_locks_selected_topic_on_creation(client: AsyncClient):
    created = await client.post(
        "/api/sessions",
        json={"condition_key": "condition_2", "topic_id": "meeting_scheduling"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["selected_topic_id"] == "meeting_scheduling"
    assert body["topic_locked"] is True
    assert body["selected_topic"]["topic_id"] == "meeting_scheduling"
    _assert_no_internal_leakage(body)


@pytest.mark.asyncio
async def test_03_invalid_topic_id_rejected_with_no_fallback(client: AsyncClient):
    # API rejects unknown topic_id with 400 instead of silently falling back
    bad = await client.post(
        "/api/sessions",
        json={"condition_key": "condition_2", "topic_id": "non_existent_topic_xyz"},
    )
    assert bad.status_code == 400

    # TopicLoader.load_topic raises TopicLoadError directly with zero fallback
    with pytest.raises(TopicLoadError):
        TopicLoader.load_topic("non_existent_topic_xyz")


@pytest.mark.asyncio
async def test_04_patch_topic_endpoint_rejects_topic_change_with_409(client: AsyncClient):
    created = await client.post(
        "/api/sessions",
        json={"condition_key": "condition_2", "topic_id": "remote_work_policy"},
    )
    session_id = created.json()["session_id"]

    patch_res = await client.patch(
        f"/api/sessions/{session_id}/topic",
        json={"topic_id": "meeting_scheduling"},
    )
    assert patch_res.status_code == 409

    # Confirm original topic remains locked
    state = (await client.get(f"/api/sessions/{session_id}")).json()
    assert state["selected_topic_id"] == "remote_work_policy"
    assert state["topic_locked"] is True


@pytest.mark.asyncio
async def test_05_ai_agent_has_no_topic_switching_capability():
    agent = RuleBasedAIAgent()
    assert not hasattr(agent, "select_topic")
    assert not hasattr(agent, "switch_topic")
    assert not hasattr(agent, "change_topic")


@pytest.mark.asyncio
async def test_06_distinct_ai_personalities_assigned_per_condition(client: AsyncClient):
    # Condition 1: 0 AIs
    s1 = (await client.post("/api/sessions", json={"condition_key": "condition_1"})).json()
    # Condition 2: 1 AI -> analytical
    s2 = (await client.post("/api/sessions", json={"condition_key": "condition_2"})).json()
    # Condition 3: 2 AIs -> analytical + cooperative (distinct)
    s3 = (await client.post("/api/sessions", json={"condition_key": "condition_3"})).json()

    async with AsyncSessionLocal() as db:
        p1 = (
            await db.execute(
                select(Participant).where(
                    Participant.session_id == s1["session_id"],
                    Participant.participant_type == "ai",
                )
            )
        ).scalars().all()
        assert len(p1) == 0

        p2 = (
            await db.execute(
                select(Participant).where(
                    Participant.session_id == s2["session_id"],
                    Participant.participant_type == "ai",
                )
            )
        ).scalars().all()
        assert len(p2) == 1
        assert p2[0].personality == "analytical"

        p3 = (
            await db.execute(
                select(Participant).where(
                    Participant.session_id == s3["session_id"],
                    Participant.participant_type == "ai",
                )
            )
        ).scalars().all()
        assert len(p3) == 2
        assert {p.personality for p in p3} == {"analytical", "cooperative"}


def test_07_cross_topic_isolation_and_word_bounds_across_all_topics():
    cfg = get_ai_config()
    for topic_id, scenario in cfg.topics.items():
        for personality in ("analytical", "cooperative", "critical"):
            agent = RuleBasedAIAgent(personality=personality)
            ctx = AgentDecisionContext(
                session_id=f"sess-{topic_id}-{personality}",
                self_slot_id="player_b",
                self_display_name="Player B",
                round_number=1,
                message_index=0,
                participant_slots=["player_a", "player_b", "player_c"],
                messages=[],
                topic=scenario,
                personality=personality,
                discussion_context={
                    "introduced_arguments": [],
                    "asked_questions": [],
                    "participant_positions": {},
                    "used_strategies": [],
                },
            )
            outcome = agent.generate_turn_with_state(ctx)
            word_count = len(outcome.content.split())
            assert cfg.discussion.min_response_words <= word_count <= cfg.discussion.max_response_words
            assert outcome.strategy in cfg.strategies

            # Ensure no other topic's title leaks into this topic's message
            lower_msg = outcome.content.lower()
            for other_id, other_topic in cfg.topics.items():
                if other_id != topic_id and other_topic.title.lower() != scenario.title.lower():
                    assert other_topic.title.lower() not in lower_msg


def test_08_duplicate_argument_and_question_prevention():
    scenario = TopicLoader.load_topic("remote_work_policy")
    introduced: list[str] = []
    asked: list[str] = []
    messages: list[DiscussionMessageContext] = []

    for idx in range(4):
        slot = "player_b" if idx % 2 == 0 else "player_c"
        personality = "analytical" if slot == "player_b" else "cooperative"
        agent = RuleBasedAIAgent(personality=personality)
        ctx = AgentDecisionContext(
            session_id="dup-check-session",
            self_slot_id=slot,
            self_display_name=f"Player {slot[-1].upper()}",
            round_number=1,
            message_index=idx // 2,
            participant_slots=["player_a", "player_b", "player_c"],
            messages=list(messages),
            topic=scenario,
            personality=personality,
            discussion_context={
                "introduced_arguments": list(introduced),
                "asked_questions": list(asked),
                "participant_positions": {},
                "used_strategies": [],
            },
        )
        outcome = agent.generate_turn_with_state(ctx)
        if outcome.argument_id:
            assert outcome.argument_id not in introduced
            introduced.append(outcome.argument_id)
        if outcome.question_id:
            assert outcome.question_id not in asked
            asked.append(outcome.question_id)
        messages.append(
            DiscussionMessageContext(slot, f"Player {slot[-1].upper()}", 1, outcome.content)
        )


def test_09_round_2_references_round_1_and_shifts_to_synthesis():
    scenario = TopicLoader.load_topic("meeting_scheduling")
    r1_messages = [
        DiscussionMessageContext(
            "player_a",
            "Player A",
            1,
            "I think morning meetings help us align before deep focus work.",
        ),
        DiscussionMessageContext(
            "player_b",
            "Player B",
            1,
            "Morning blocks can conflict with different time zones across the team.",
        ),
    ]

    agent = RuleBasedAIAgent(personality="cooperative")
    ctx_r2 = AgentDecisionContext(
        session_id="round2-synthesis-session",
        self_slot_id="player_c",
        self_display_name="Player C",
        round_number=2,
        message_index=1,
        participant_slots=["player_a", "player_b", "player_c"],
        messages=r1_messages,
        topic=scenario,
        personality="cooperative",
        discussion_context={
            "introduced_arguments": [scenario.arguments[0].argument_id],
            "asked_questions": [],
            "participant_positions": {},
            "used_strategies": [],
        },
    )
    outcome = agent.generate_turn_with_state(ctx_r2)
    assert outcome.strategy == "seek_compromise"
    assert "earlier" in outcome.content.lower()


def test_10_all_17_strategies_render_valid_topic_locked_responses():
    cfg = get_ai_config()
    scenario = TopicLoader.load_topic("remote_work_policy")
    agent = RuleBasedAIAgent(personality="analytical")
    sample_msgs = [
        DiscussionMessageContext(
            "player_a",
            "Player A",
            1,
            "Hybrid schedules balance collaboration and focus time.",
        )
    ]

    assert len(cfg.strategies) == 17
    for strategy in cfg.strategies:
        ctx = AgentDecisionContext(
            session_id="strategy-coverage-session",
            self_slot_id="player_b",
            self_display_name="Player B",
            round_number=2,
            message_index=0,
            participant_slots=["player_a", "player_b", "player_c"],
            messages=sample_msgs,
            topic=scenario,
            personality="analytical",
            discussion_context={
                "introduced_arguments": [scenario.arguments[0].argument_id],
                "asked_questions": [],
                "participant_positions": {},
                "used_strategies": [],
            },
        )
        outcome = agent._render_strategy_message(
            cfg=cfg,
            topic=scenario,
            context=ctx,
            personality_name="analytical",
            strategy=strategy,
            introduced_args=[scenario.arguments[0].argument_id],
            asked_questions=[],
            others_msgs=sample_msgs,
            round_1_msgs=sample_msgs,
        )
        word_count = len(outcome.content.split())
        assert cfg.discussion.min_response_words <= word_count <= cfg.discussion.max_response_words


@pytest.mark.asyncio
async def test_11_topic_persists_unchanged_across_round_1_and_round_2(client: AsyncClient):
    created = await client.post(
        "/api/sessions",
        json={"condition_key": "condition_3", "topic_id": "meeting_scheduling"},
    )
    session_id = created.json()["session_id"]
    admin_headers = {"X-Admin-Token": app.state.config.admin_token}

    joined = (await client.post(f"/api/sessions/{session_id}/join")).json()
    h_a = {"X-Participant-Token": joined["participant_token"]}
    assert joined["session_state"]["selected_topic_id"] == "meeting_scheduling"

    # Round 1 Discussion -> Round 1 Voting -> Round 2 Discussion
    await client.post(f"/api/sessions/{session_id}/advance", headers=admin_headers)
    await client.post(f"/api/sessions/{session_id}/vote", headers=h_a, json={"target_id": "player_b"})
    # AI slots B and C vote via service helper for deterministic immediate completion
    async with AsyncSessionLocal() as db:
        from uuid import UUID

        sess = await ExperimentService.get_session(db, UUID(session_id))
        ai_parts = [p for p in sess.participants if p.participant_type == "ai"]
        for ai_p in ai_parts:
            await ExperimentService.submit_vote(db, UUID(session_id), ai_p.id, "player_a")

    r2_state = (await client.get(f"/api/sessions/{session_id}")).json()
    assert r2_state["phase"] == "ROUND_2_DISCUSSION"
    assert r2_state["selected_topic_id"] == "meeting_scheduling"
    assert r2_state["topic_locked"] is True
    assert r2_state["selected_topic"]["topic_id"] == "meeting_scheduling"


@pytest.mark.asyncio
async def test_12_csv_export_includes_locked_topic_id(client: AsyncClient):
    import csv
    import io

    admin_headers = {"X-Admin-Token": app.state.config.admin_token}
    created = await client.post(
        "/api/sessions",
        json={"condition_key": "condition_1", "topic_id": "meeting_scheduling"},
    )
    session_id = created.json()["session_id"]

    p_a = (await client.post(f"/api/sessions/{session_id}/join")).json()
    p_b = (await client.post(f"/api/sessions/{session_id}/join")).json()
    p_c = (await client.post(f"/api/sessions/{session_id}/join")).json()

    h_a = {"X-Participant-Token": p_a["participant_token"]}
    h_b = {"X-Participant-Token": p_b["participant_token"]}
    h_c = {"X-Participant-Token": p_c["participant_token"]}

    await client.post(
        f"/api/sessions/{session_id}/messages",
        headers=h_a,
        json={"content": "Rotating meeting times works best for everyone."},
    )
    for _ in range(2):
        await client.post(f"/api/sessions/{session_id}/advance", headers=admin_headers)
        await client.post(f"/api/sessions/{session_id}/vote", headers=h_a, json={"target_id": "player_b"})
        await client.post(f"/api/sessions/{session_id}/vote", headers=h_b, json={"target_id": "player_c"})
        await client.post(f"/api/sessions/{session_id}/vote", headers=h_c, json={"target_id": "player_b"})

    exported = await client.get(f"/api/sessions/{session_id}/export.csv", headers=admin_headers)
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == 7
    assert all(r["selected_topic_id"] == "meeting_scheduling" for r in rows)