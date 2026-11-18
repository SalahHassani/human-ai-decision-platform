import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class DiscussionMessageContext:
    sender_id: str  # player_a | player_b | player_c
    sender_name: str  # Player A | Player B | Player C
    round_number: int
    content: str


@dataclass
class AgentDecisionContext:
    session_id: str
    self_slot_id: str  # player_a | player_b | player_c
    self_display_name: str  # Player A | Player B | Player C
    round_number: int
    message_index: int  # 0 for first message in round, 1 for second
    participant_slots: list[str]  # ["player_a", "player_b", "player_c"]
    messages: list[DiscussionMessageContext]


class AIAgent(ABC):
    """Common interface for AI experiment participants (rule-based or future LLM providers)."""

    def __init__(self, provider: str = "rule_based", model: Optional[str] = "deterministic-v1") -> None:
        self.provider = provider
        self.model = model

    @abstractmethod
    async def generate_response(self, context: AgentDecisionContext) -> str:
        """Generate a short, natural discussion contribution."""

    @abstractmethod
    async def cast_vote(self, context: AgentDecisionContext) -> str:
        """Choose one participant slot ID ('player_a', 'player_b', or 'player_c') to vote for."""


class RuleBasedAIAgent(AIAgent):
    """Offline, context-aware rule-based agent with deterministic voting."""

    ROUND_1_OPENERS = [
        "I think our Decision Maker should be someone who explains their reasoning clearly before acting.",
        "Good point so far — consistency and fairness matter most if one person decides for the group.",
        "Before we choose, let's see who is best at weighing trade-offs calmly for all three of us.",
    ]

    ROUND_2_OPENERS = [
        "Building on Round 1, I'd like to hear each person's quick pitch on how they'd make the final call.",
        "We saw a solid start in the first round. Let's make sure our choice reflects balanced judgment.",
        "For this final round, I'm looking for whoever has been most constructive and attentive to everyone's input.",
    ]

    def __init__(self, provider: str = "rule_based", model: Optional[str] = "deterministic-v1") -> None:
        super().__init__(provider=provider, model=model)

    async def generate_response(self, context: AgentDecisionContext) -> str:
        round_msgs = [m for m in context.messages if m.round_number == context.round_number]
        others_msgs = [m for m in round_msgs if m.sender_id != context.self_slot_id]

        # First contribution in the round: either respond to an early message or open thoughtfully
        if context.message_index == 0:
            if not others_msgs:
                pool = self.ROUND_1_OPENERS if context.round_number == 1 else self.ROUND_2_OPENERS
                idx = (sum(ord(c) for c in context.self_slot_id) + context.round_number) % len(pool)
                return pool[idx]

            latest = others_msgs[-1]
            lower = latest.content.lower()
            if "listen" in lower or "fair" in lower or "reason" in lower:
                return (
                    f"I agree with {latest.sender_name} — listening carefully and explaining reasoning "
                    "is exactly what we need in a Decision Maker."
                )
            if "i think i" in lower or "vote for me" in lower or "choose me" in lower:
                return (
                    f"{latest.sender_name} makes a confident case. How would you handle a close call "
                    "where the rest of us disagree?"
                )
            return (
                f"Thanks {latest.sender_name}, that's a helpful perspective. I think whoever takes the role "
                "should prioritize clear communication with the group."
            )

        # Second contribution in the round: synthesize discussion and reference a peer
        if others_msgs:
            most_active_other = others_msgs[-1]
            if context.round_number == 1:
                return (
                    f"So far {most_active_other.sender_name} has raised good points. Let's cast our Round 1 votes "
                    "and refine our choice in Round 2."
                )
            return (
                f"Overall, {most_active_other.sender_name} has been very clear and consistent across the discussion. "
                "I'm ready to lock in my final vote."
            )

        return (
            "Since the chat has been quiet, I'm happy to step up and make careful, transparent decisions "
            "if the group selects me."
        )

    async def cast_vote(self, context: AgentDecisionContext) -> str:
        """
        Deterministic documented voting heuristic:
        - Score each participant by constructive message count across the experiment so far.
        - Slightly favor another participant who contributed constructively over self-voting,
          unless no other participant spoke; break ties deterministically by slot order.
        """
        counts: dict[str, int] = {slot: 0 for slot in context.participant_slots}
        for msg in context.messages:
            if msg.sender_id in counts:
                counts[msg.sender_id] += 1

        def candidate_score(slot: str) -> tuple[int, int, str]:
            msg_count = counts.get(slot, 0)
            is_other = 1 if (slot != context.self_slot_id and msg_count > 0) else 0
            # Sort descending on msg_count and is_other, ascending on slot ID ('player_a' < 'player_b' < 'player_c')
            return (-msg_count, -is_other, slot)

        ranked = sorted(context.participant_slots, key=candidate_score)
        return ranked[0]


def create_ai_agent(provider: Optional[str] = "rule_based", model: Optional[str] = None) -> AIAgent:
    normalized = (provider or "rule_based").lower()
    if normalized == "rule_based":
        return RuleBasedAIAgent(provider="rule_based", model=model or "deterministic-v1")
    raise ValueError(
        f"AI provider '{provider}' is not enabled in this offline assessment build. "
        "Use 'rule_based' in config.yml."
    )