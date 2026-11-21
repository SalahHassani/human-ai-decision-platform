from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from app.topic_loader import (
    GlobalAIConfig,
    TopicArgument,
    TopicCompromise,
    TopicLoader,
    TopicQuestion,
    TopicScenario,
    get_ai_config,
)


PERSONALITY_ORDER = ["analytical", "cooperative", "critical"]


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
    topic: Optional[TopicScenario] = None
    personality: str = "analytical"
    discussion_context: dict = field(default_factory=dict)


@dataclass
class GeneratedTurnOutcome:
    content: str
    strategy: str
    personality: str
    argument_id: Optional[str] = None
    question_id: Optional[str] = None
    compromise_id: Optional[str] = None
    stance_option: Optional[str] = None


class AIAgent(ABC):
    """Common interface for AI experiment participants. Never selects or switches topics."""

    def __init__(
        self,
        provider: str = "rule_based",
        model: Optional[str] = "deterministic-v1",
        personality: str = "analytical",
    ) -> None:
        self.provider = provider
        self.model = model
        self.personality = personality

    @abstractmethod
    async def generate_response(self, context: AgentDecisionContext) -> str:
        """Generate a topic-locked, context-aware discussion contribution."""

    @abstractmethod
    async def cast_vote(self, context: AgentDecisionContext) -> str:
        """Choose one participant slot ID ('player_a', 'player_b', or 'player_c') to vote for."""


class RuleBasedAIAgent(AIAgent):
    """Topic-locked, personality-driven, natural conversational rule-based agent."""

    def __init__(
        self,
        provider: str = "rule_based",
        model: Optional[str] = "deterministic-v1",
        personality: str = "analytical",
    ) -> None:
        super().__init__(provider=provider, model=model, personality=personality)
        self.last_outcome: Optional[GeneratedTurnOutcome] = None

    @staticmethod
    def _stable_index(seed: str, length: int) -> int:
        if length <= 1:
            return 0
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % length

    @staticmethod
    def _ensure_topic(context: AgentDecisionContext) -> TopicScenario:
        if context.topic is not None:
            return TopicLoader.load_topic(context.topic.topic_id)
        raise ValueError("AgentDecisionContext must provide a locked TopicScenario.")

    def _pick_variation(self, items: list[str], seed: str) -> str:
        return items[self._stable_index(seed, len(items))]

    @staticmethod
    def _lowercase_first(text: str) -> str:
        if not text:
            return text
        if text.startswith("I ") or text.startswith("I'"):
            return text
        return text[0].lower() + text[1:]

    @staticmethod
    def _uppercase_first(text: str) -> str:
        if not text:
            return text
        return text[0].upper() + text[1:]

    def _select_unused_argument(
        self,
        topic: TopicScenario,
        introduced_ids: set[str],
        preferred_categories: list[str],
        personality_prefs: list[str],
        seed: str,
    ) -> Optional[TopicArgument]:
        unused = [a for a in topic.arguments if a.argument_id not in introduced_ids]
        if not unused:
            return None

        def score(arg: TopicArgument) -> tuple[int, int, int]:
            cat_match = 1 if (not preferred_categories or arg.category in preferred_categories) else 0
            kw_overlap = len(set(arg.keywords) & set(personality_prefs))
            tie = self._stable_index(f"{seed}:{arg.argument_id}", 1000)
            return (-cat_match, -kw_overlap, tie)

        return sorted(unused, key=score)[0]

    def _select_existing_argument(
        self,
        topic: TopicScenario,
        introduced_ids: list[str],
        seed: str,
    ) -> Optional[TopicArgument]:
        by_id = {a.argument_id: a for a in topic.arguments}
        existing = [by_id[aid] for aid in introduced_ids if aid in by_id]
        if not existing:
            return None
        return existing[self._stable_index(seed, len(existing))]

    def _select_unused_question(
        self,
        topic: TopicScenario,
        asked_ids: set[str],
        seed: str,
    ) -> Optional[TopicQuestion]:
        main_norm = topic.main_question.strip().lower()
        unused = [
            q
            for q in topic.questions
            if q.question_id not in asked_ids and q.text.strip().lower() != main_norm
        ]
        if not unused:
            return None
        return unused[self._stable_index(seed, len(unused))]

    def _select_compromise(self, topic: TopicScenario, seed: str) -> Optional[TopicCompromise]:
        if not topic.compromises:
            return None
        return topic.compromises[self._stable_index(seed, len(topic.compromises))]

    def _choose_strategy(
        self,
        cfg: GlobalAIConfig,
        topic: TopicScenario,
        context: AgentDecisionContext,
        personality_name: str,
        introduced_args: list[str],
        asked_questions: list[str],
        others_msgs: list[DiscussionMessageContext],
        round_1_msgs: list[DiscussionMessageContext],
    ) -> str:
        p_cfg = cfg.personalities.get(personality_name) or cfg.personalities["analytical"]
        round_key = f"round_{context.round_number}"
        r_cfg = cfg.round_behavior.get(round_key) or cfg.round_behavior["round_1"]
        topic_r2 = topic.round_2.strategies if context.round_number == 2 else []

        unused_args = [a for a in topic.arguments if a.argument_id not in set(introduced_args)]
        unused_qs = [q for q in topic.questions if q.question_id not in set(asked_questions)]

        ordered_candidates: list[str] = []
        for s in p_cfg.preferred_strategies + topic_r2 + r_cfg.preferred_strategies:
            if s in cfg.strategies and s not in ordered_candidates:
                ordered_candidates.append(s)

        if context.round_number == 1:
            r1_allowed = set(r_cfg.preferred_strategies) | set(p_cfg.preferred_strategies)
            ordered_candidates = [s for s in ordered_candidates if s in r1_allowed]
            if not introduced_args and unused_args:
                return "introduce_argument"
            if context.message_index == 0 and len(introduced_args) < 2 and unused_args:
                if personality_name == "critical" and unused_qs and len(others_msgs) > 0:
                    return "ask_question"
                return "introduce_argument"
        else:
            r2_allowed = set(r_cfg.preferred_strategies) | set(p_cfg.preferred_strategies) | set(topic_r2)
            ordered_candidates = [s for s in ordered_candidates if s in r2_allowed]
            if context.message_index == 1 and personality_name == "cooperative":
                return "seek_compromise"
            if context.message_index == 1 and personality_name == "analytical":
                return "evaluate_feasibility"
            if context.message_index == 1 and personality_name == "critical":
                return "identify_tradeoff"

        feasible: list[str] = []
        for s in ordered_candidates:
            if s == "introduce_argument" and not unused_args:
                continue
            if s == "ask_question" and not unused_qs:
                continue
            if s in {
                "agree",
                "disagree",
                "add_evidence",
                "build_on_idea",
                "challenge_assumption",
                "address_concern",
            } and not (introduced_args or others_msgs or round_1_msgs):
                continue
            feasible.append(s)

        if not feasible:
            return "introduce_argument" if unused_args else "summarize_position"

        seed = f"{context.session_id}:{context.self_slot_id}:r{context.round_number}:m{context.message_index}"
        return feasible[self._stable_index(seed, len(feasible))]

    def _render_strategy_message(
        self,
        cfg: GlobalAIConfig,
        topic: TopicScenario,
        context: AgentDecisionContext,
        personality_name: str,
        strategy: str,
        introduced_args: list[str],
        asked_questions: list[str],
        others_msgs: list[DiscussionMessageContext],
        round_1_msgs: list[DiscussionMessageContext],
    ) -> GeneratedTurnOutcome:
        p_cfg = cfg.personalities.get(personality_name) or cfg.personalities["analytical"]
        seed = f"{context.session_id}:{context.self_slot_id}:r{context.round_number}:m{context.message_index}:{strategy}"
        introduced_set = set(introduced_args)
        asked_set = set(asked_questions)

        pref_cats = (
            topic.round_1.preferred_argument_categories
            if context.round_number == 1
            else topic.round_2.preferred_argument_categories
        )
        unused_arg = self._select_unused_argument(
            topic, introduced_set, pref_cats, p_cfg.argument_preferences, seed
        )
        existing_arg = self._select_existing_argument(topic, introduced_args, seed)
        unused_q = self._select_unused_question(topic, asked_set, seed)
        compromise = self._select_compromise(topic, seed)

        peer_ref = (
            others_msgs[-1].sender_name
            if others_msgs
            else (round_1_msgs[-1].sender_name if round_1_msgs else None)
        )
        has_r1 = context.round_number == 2 and bool(round_1_msgs)

        opt_labels = [o.label.lower() for o in topic.options]
        opt_a = opt_labels[0] if len(opt_labels) > 0 else "the first option"
        opt_b = opt_labels[1] if len(opt_labels) > 1 else "the second option"
        opt_c = opt_labels[2] if len(opt_labels) > 2 else "a balanced approach"

        arg_id: Optional[str] = None
        q_id: Optional[str] = None
        c_id: Optional[str] = None
        stance: Optional[str] = None

        if strategy == "introduce_argument" and unused_arg:
            arg_id = unused_arg.argument_id
            stance = unused_arg.related_options[0] if unused_arg.related_options else None
            var = self._pick_variation(unused_arg.variations, seed)
            if has_r1 and peer_ref:
                openers = [
                    f"Going back to what {peer_ref} brought up earlier, {self._lowercase_first(var)}",
                    f"Another angle worth adding after {peer_ref}'s point: {self._lowercase_first(var)}",
                ]
            else:
                openers = [
                    f"Honestly, {self._lowercase_first(var)}",
                    f"One thing I'd point out here is that {self._lowercase_first(var)}",
                    f"The way I see it, {self._lowercase_first(var)}",
                ]
            text = self._pick_variation(openers, f"{seed}:op")

        elif strategy == "ask_question" and unused_q:
            q_id = unused_q.question_id
            if peer_ref:
                openers = [
                    f"That's a fair point from {peer_ref}, though it makes me wonder: {self._lowercase_first(unused_q.text)}",
                    f"Before we lock anything in after {peer_ref}'s comment — {self._lowercase_first(unused_q.text)}",
                ]
            else:
                openers = [
                    f"Quick question for everyone before we jump ahead: {self._lowercase_first(unused_q.text)}",
                    f"Something I keep coming back to here: {self._lowercase_first(unused_q.text)}",
                ]
            text = self._pick_variation(openers, f"{seed}:q")

        elif strategy == "agree":
            target_arg = existing_arg or unused_arg
            who = peer_ref or "that point"
            if target_arg:
                if target_arg.argument_id not in introduced_set:
                    arg_id = target_arg.argument_id
                stance = target_arg.related_options[0] if target_arg.related_options else None
                var = self._pick_variation(target_arg.variations, seed)
                if has_r1 and peer_ref:
                    text = f"I still agree with what {peer_ref} said earlier. {var}"
                else:
                    text = f"I'm with {who} on this — {self._lowercase_first(var)}"
            else:
                text = f"I'm with {who} on this; keeping things practical for everyone should be our top priority."

        elif strategy == "disagree":
            contrast_arg = unused_arg or existing_arg
            who = peer_ref or "that view"
            if contrast_arg:
                if contrast_arg.argument_id not in introduced_set:
                    arg_id = contrast_arg.argument_id
                stance = contrast_arg.related_options[0] if contrast_arg.related_options else None
                var = self._pick_variation(contrast_arg.variations, seed)
                if has_r1 and peer_ref:
                    text = f"I see why {peer_ref} leaned that way earlier, but I'm not fully convinced. {var}"
                else:
                    text = f"I see where {who} is coming from, though I worry we're overlooking something. {var}"
            else:
                text = f"I'm not sure I agree with {who} — going strictly with {opt_a} could backfire once real constraints hit."

        elif strategy == "add_evidence":
            target_arg = unused_arg or existing_arg
            if target_arg:
                if target_arg.argument_id not in introduced_set:
                    arg_id = target_arg.argument_id
                stance = target_arg.related_options[0] if target_arg.related_options else None
                var = self._pick_variation(target_arg.variations, seed)
                if has_r1 and peer_ref:
                    text = f"Adding to {peer_ref}'s point from earlier, {self._lowercase_first(var)}"
                else:
                    text = f"In practice, {self._lowercase_first(var)}"
            else:
                text = f"Looking at day-to-day execution, {opt_a} and {opt_b} behave very differently once workloads pick up."

        elif strategy == "identify_concern":
            concerns = [
                a for a in topic.arguments if a.category == "concern" and a.argument_id not in introduced_set
            ]
            chosen = concerns[0] if concerns else (unused_arg or existing_arg)
            if chosen:
                if chosen.argument_id not in introduced_set:
                    arg_id = chosen.argument_id
                stance = chosen.related_options[0] if chosen.related_options else None
                var = self._pick_variation(chosen.variations, seed)
                if has_r1 and peer_ref:
                    text = f"One catch with what {peer_ref} raised earlier: {self._lowercase_first(var)}"
                else:
                    text = f"My main worry here is that {self._lowercase_first(var)}"
            else:
                text = f"My main worry is whether {opt_a} still holds up once everyone's schedules get busy."

        elif strategy == "suggest_alternative":
            alts = [
                a
                for a in topic.arguments
                if a.category in {"alternative", "compromise"} and a.argument_id not in introduced_set
            ]
            chosen = alts[0] if alts else (unused_arg or existing_arg)
            if chosen:
                if chosen.argument_id not in introduced_set:
                    arg_id = chosen.argument_id
                stance = chosen.related_options[0] if chosen.related_options else None
                var = self._pick_variation(chosen.variations, seed)
                text = f"Instead of forcing a choice between {opt_a} and {opt_b}, {self._lowercase_first(var)}"
            else:
                text = f"Another route would be {opt_c}, which avoids the downsides of going all-in on {opt_a}."

        elif strategy == "build_on_idea":
            target_arg = unused_arg or existing_arg
            who = peer_ref or "that"
            if target_arg:
                if target_arg.argument_id not in introduced_set:
                    arg_id = target_arg.argument_id
                stance = target_arg.related_options[0] if target_arg.related_options else None
                var = self._pick_variation(target_arg.variations, seed)
                text = f"Piggybacking on {who}'s point — {self._lowercase_first(var)}"
            else:
                text = f"Piggybacking on {who}'s idea, setting clear expectations around {opt_c} would make it easy to follow."

        elif strategy == "evaluate_consequence":
            target_arg = unused_arg or existing_arg
            if target_arg and target_arg.argument_id not in introduced_set:
                arg_id = target_arg.argument_id
            detail = self._pick_variation(target_arg.variations, seed) if target_arg else ""
            lead = f"Thinking through what {peer_ref} said earlier, " if (has_r1 and peer_ref) else "If we play this out, "
            text = f"{lead}choosing {opt_a} over {opt_b} changes how the whole team operates. {detail}".strip()

        elif strategy == "challenge_assumption":
            lead = f"Pushing back slightly on {peer_ref}'s earlier point — " if (has_r1 and peer_ref) else "I'm not sure we should assume "
            if has_r1 and peer_ref:
                text = (
                    f"{lead}are we sure {opt_a} works equally well for everyone, or are we overlooking edge cases?"
                )
            else:
                text = (
                    f"I'm not sure we should assume {opt_a} works equally well for everyone without testing how it handles edge cases."
                )

        elif strategy == "compare_alternatives":
            lead = f"Comparing the options {peer_ref} brought up earlier: " if (has_r1 and peer_ref) else "When you put them side by side, "
            text = (
                f"{lead}{opt_a} gives us simplicity right away, while {opt_c} holds up much better when priorities shift."
            )

        elif strategy == "identify_tradeoff":
            lead = "Looking at both sides we heard earlier, " if has_r1 else "To me, "
            text = (
                f"{lead}the real tradeoff comes down to predictability versus flexibility: "
                f"going with {opt_a} means giving up what {opt_b} offers."
            )

        elif strategy == "develop_proposal":
            if compromise:
                c_id = compromise.compromise_id
                var = self._pick_variation(compromise.variations, seed)
                lead = (
                    f"Turning what {peer_ref} raised earlier into a concrete plan — "
                    if (has_r1 and peer_ref)
                    else "If we want something concrete to try, "
                )
                text = f"{lead}{self._lowercase_first(var)}"
            else:
                text = f"If we want a concrete plan, we could start with {opt_c} and review how it's working after a few weeks."

        elif strategy == "address_concern":
            if compromise:
                c_id = compromise.compromise_id
                var = self._pick_variation(compromise.variations, seed)
                lead = (
                    f"To solve the issue {peer_ref} flagged earlier, "
                    if (has_r1 and peer_ref)
                    else "To avoid the main pitfall here, "
                )
                text = f"{lead}{self._lowercase_first(var)}"
            else:
                text = f"To avoid the downsides of {opt_a}, we can set clear ground rules upfront so nobody gets left out."

        elif strategy == "seek_compromise":
            if compromise:
                c_id = compromise.compromise_id
                var = self._pick_variation(compromise.variations, seed)
                lead = (
                    "To meet in the middle after our earlier points, "
                    if has_r1
                    else "If we want something that works for both sides, "
                )
                text = f"{lead}{self._lowercase_first(var)}"
            else:
                text = f"Meeting in the middle with {opt_c} seems like the fairest way to bridge {opt_a} and {opt_b}."

        elif strategy == "evaluate_feasibility":
            lead = f"Weighing what {peer_ref} mentioned earlier, " if (has_r1 and peer_ref) else "Realistically, "
            text = (
                f"{lead}{opt_c} is the easiest option to actually pull off without creating extra friction for the team."
            )

        else:  # summarize_position
            lead = "Pulling together what we've discussed so far, " if has_r1 else "Overall, "
            text = (
                f"{lead}{opt_c} gives us the upside of {opt_a} while avoiding most of the headaches of {opt_b}."
            )

        cleaned = self._enforce_word_bounds(text, cfg, topic)
        return GeneratedTurnOutcome(
            content=cleaned,
            strategy=strategy,
            personality=personality_name,
            argument_id=arg_id,
            question_id=q_id,
            compromise_id=c_id,
            stance_option=stance,
        )

    @staticmethod
    def _enforce_word_bounds(text: str, cfg: GlobalAIConfig, topic: TopicScenario) -> str:
        words = text.split()
        min_w = cfg.discussion.min_response_words
        max_w = cfg.discussion.max_response_words

        if len(words) < min_w:
            padding = "That feels like the most practical way forward for the whole team."
            words = (f"{text} {padding}").split()

        if len(words) > max_w:
            trimmed = " ".join(words[:max_w]).rstrip(",;:")
            if not trimmed.endswith((".", "!", "?")):
                trimmed += "."
            return trimmed

        return " ".join(words)

    def _validate_response(
        self,
        cfg: GlobalAIConfig,
        topic: TopicScenario,
        outcome: GeneratedTurnOutcome,
    ) -> None:
        if cfg.validation.reject_invalid_strategy and outcome.strategy not in cfg.strategies:
            raise ValueError(f"Invalid AI strategy '{outcome.strategy}'.")

        word_count = len(outcome.content.split())
        if cfg.validation.validate_response_length:
            if (
                word_count < cfg.discussion.min_response_words
                or word_count > cfg.discussion.max_response_words
            ):
                raise ValueError(
                    f"AI response length ({word_count} words) outside configured bounds "
                    f"[{cfg.discussion.min_response_words}, {cfg.discussion.max_response_words}]."
                )

        if cfg.validation.reject_cross_topic_content:
            lower_text = outcome.content.lower()
            for other_id, other_topic in cfg.topics.items():
                if other_id == topic.topic_id:
                    continue
                other_title = other_topic.title.lower()
                if other_title != topic.title.lower() and other_title in lower_text:
                    raise ValueError(
                        f"Cross-topic contamination detected: '{other_title}' found inside '{topic.topic_id}'."
                    )

    def generate_turn_with_state(self, context: AgentDecisionContext) -> GeneratedTurnOutcome:
        cfg = get_ai_config()
        topic = self._ensure_topic(context)
        personality_name = (
            context.personality
            if context.personality in cfg.personalities
            else self.personality
        )
        if personality_name not in cfg.personalities:
            personality_name = "analytical"

        d_ctx = context.discussion_context or {}
        introduced_args = list(d_ctx.get("introduced_arguments", []))
        asked_questions = list(d_ctx.get("asked_questions", []))

        round_msgs = [m for m in context.messages if m.round_number == context.round_number]
        others_msgs = [m for m in round_msgs if m.sender_id != context.self_slot_id]
        round_1_msgs = [m for m in context.messages if m.round_number == 1]

        strategy = self._choose_strategy(
            cfg=cfg,
            topic=topic,
            context=context,
            personality_name=personality_name,
            introduced_args=introduced_args,
            asked_questions=asked_questions,
            others_msgs=others_msgs,
            round_1_msgs=round_1_msgs,
        )
        outcome = self._render_strategy_message(
            cfg=cfg,
            topic=topic,
            context=context,
            personality_name=personality_name,
            strategy=strategy,
            introduced_args=introduced_args,
            asked_questions=asked_questions,
            others_msgs=others_msgs,
            round_1_msgs=round_1_msgs,
        )
        self._validate_response(cfg, topic, outcome)
        self.last_outcome = outcome
        return outcome

    async def generate_response(self, context: AgentDecisionContext) -> str:
        outcome = self.generate_turn_with_state(context)
        return outcome.content

    async def cast_vote(self, context: AgentDecisionContext) -> str:
        """
        Deterministic documented voting heuristic (self-voting disallowed):
        - Filter out the agent's own slot so it only evaluates peers.
        - Rank remaining candidates by message count across the experiment so far,
          breaking ties deterministically by slot order ('player_a' < 'player_b' < 'player_c').
        """
        eligible_slots = [
            slot for slot in context.participant_slots if slot != context.self_slot_id
        ]
        counts: dict[str, int] = {slot: 0 for slot in eligible_slots}
        for msg in context.messages:
            if msg.sender_id in counts:
                counts[msg.sender_id] += 1

        ranked = sorted(eligible_slots, key=lambda s: (-counts.get(s, 0), s))
        return ranked[0]


def create_ai_agent(
    provider: Optional[str] = "rule_based",
    model: Optional[str] = None,
    personality: Optional[str] = "analytical",
) -> AIAgent:
    normalized = (provider or "rule_based").lower()
    if normalized == "rule_based":
        return RuleBasedAIAgent(
            provider="rule_based",
            model=model or "deterministic-v1",
            personality=personality or "analytical",
        )
    raise ValueError(
        f"AI provider '{provider}' is not enabled in this offline assessment build. "
        "Use 'rule_based' in config.yml."
    )