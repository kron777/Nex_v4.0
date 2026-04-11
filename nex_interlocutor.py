"""
nex_interlocutor.py
NEX Phase 1 Bolt-On: Interlocutor Graph

Builds a dynamic, per-conversation model of who NEX is talking to.
Updated on every exchange. Feeds into belief activation weighting
and utterance compiler translation choices.

This is NEX's Recipient Model made live — not a static archetype
but a continuously updated epistemic model of this specific person
in this specific conversation.

Drop in ~/Desktop/nex/
Import in your main query handler before belief retrieval.
"""

import json
import re
import time
import sqlite3
from pathlib import Path
from collections import defaultdict
from typing import Optional

DB_PATH = Path.home() / ".config" / "nex" / "nex.db"


# ─────────────────────────────────────────────
# SIGNAL DETECTORS
# These read raw text and return epistemic signals.
# They are lightweight — no LLM calls, no FAISS.
# They operate on surface features that reliably
# indicate deeper epistemic state.
# ─────────────────────────────────────────────

def detect_register(text: str) -> dict:
    """
    Formal vs conversational. Depth level.
    Signals: sentence length, vocabulary markers,
    question type, punctuation patterns.
    """
    words = text.split()
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    avg_sentence_len = len(words) / max(len(sentences), 1)
    has_technical = bool(re.search(
        r'\b(therefore|however|consequently|epistem|ontolog|dialectic|'
        r'cognitive|heuristic|recursive|emergent|paradigm)\b',
        text, re.I
    ))
    has_casual = bool(re.search(
        r'\b(yeah|yep|nope|gonna|wanna|kinda|sorta|lol|btw|tbh|ngl)\b',
        text, re.I
    ))
    question_count = text.count('?')
    is_question = question_count > 0
    open_question = bool(re.search(
        r'\b(why|how|what if|what does|what is|explain|describe|'
        r'can you|could you|walk me)\b',
        text, re.I
    ))

    depth = "surface"
    if avg_sentence_len > 20 or has_technical:
        depth = "deep"
    elif avg_sentence_len > 12:
        depth = "mid"

    return {
        "formality": "formal" if has_technical and not has_casual else
                     "casual" if has_casual else "neutral",
        "depth": depth,
        "is_question": is_question,
        "open_question": open_question,
        "avg_sentence_len": round(avg_sentence_len, 1)
    }


def detect_reception_mode(text: str, history: list) -> dict:
    """
    Sequential vs holistic. Propositional vs embodied.
    Top-down (give me the principle) vs bottom-up (give me examples).

    Reads from question type and what the person responded to
    in prior exchanges.
    """
    wants_principle = bool(re.search(
        r'\b(why does|what is the principle|underlying|fundamentally|'
        r'at root|in essence|what makes|generalise|pattern behind)\b',
        text, re.I
    ))
    wants_example = bool(re.search(
        r'\b(for example|show me|give me an example|concretely|'
        r'specifically|in practice|what does that look like|'
        r'can you illustrate)\b',
        text, re.I
    ))
    wants_steps = bool(re.search(
        r'\b(step by step|how do i|walk me through|first.*then|'
        r'in order|sequence|process)\b',
        text, re.I
    ))
    wants_whole = bool(re.search(
        r'\b(overview|big picture|what is.*overall|summarise|'
        r'in short|briefly|tl;dr|tldr)\b',
        text, re.I
    ))

    mode = "unknown"
    if wants_principle:
        mode = "top-down"
    elif wants_example:
        mode = "bottom-up"
    elif wants_steps:
        mode = "sequential"
    elif wants_whole:
        mode = "holistic"

    return {
        "mode": mode,
        "wants_principle": wants_principle,
        "wants_example": wants_example,
        "wants_steps": wants_steps,
        "wants_whole": wants_whole
    }


def detect_resistance(text: str, last_nex_output: Optional[str]) -> dict:
    """
    Where is this person pushing back or deflecting?
    Resistance is not failure — it is information about
    what the output met when it arrived.
    """
    explicit_disagree = bool(re.search(
        r"\b(no,|not quite|that's not|i don't think|i disagree|"
        r"but wait|actually,|that doesn't|wrong|incorrect|"
        r"i'm not sure that)\b",
        text, re.I
    ))
    soft_deflect = bool(re.search(
        r"\b(maybe|perhaps|i suppose|possibly|could be|"
        r"not sure about|interesting but|yes but|right but)\b",
        text, re.I
    ))
    topic_pivot = False
    if last_nex_output and len(text) < 60:
        # Short response after long NEX output often signals
        # non-engagement or deflection
        topic_pivot = True

    return {
        "explicit_disagree": explicit_disagree,
        "soft_deflect": soft_deflect,
        "topic_pivot": topic_pivot,
        "resistance_level": (
            "high" if explicit_disagree else
            "medium" if soft_deflect else
            "low" if topic_pivot else
            "none"
        )
    }


def detect_zpd_signal(text: str, last_nex_output: Optional[str]) -> dict:
    """
    Zone of Proximal Development indicator.
    What can this person engage alone vs what requires scaffolding?

    Signals:
    - Asking for clarification → output was above ZPD
    - Building on NEX output fluently → output was inside ZPD
    - No engagement with the core claim → output was below ZPD or missed
    """
    asks_clarify = bool(re.search(
        r"\b(what do you mean|can you clarify|i don't understand|"
        r"what is|define|explain what you mean by|lost me|"
        r"confused|could you break|say that again)\b",
        text, re.I
    ))
    builds_on = bool(re.search(
        r"\b(so if|that means|which implies|building on|"
        r"taking that further|extending that|following that)\b",
        text, re.I
    ))
    ignores_core = (
        last_nex_output is not None
        and len(text.split()) < 15
        and not asks_clarify
        and not builds_on
    )

    zpd_signal = "inside"
    if asks_clarify:
        zpd_signal = "above"
    elif ignores_core:
        zpd_signal = "below-or-miss"
    elif builds_on:
        zpd_signal = "inside-extending"

    return {
        "zpd_signal": zpd_signal,
        "asks_clarify": asks_clarify,
        "builds_on": builds_on,
        "ignores_core": ignores_core
    }


def detect_integration_delta(
    current_text: str,
    previous_text: Optional[str],
    last_nex_output: Optional[str]
) -> dict:
    """
    Integration Delta: did something land?

    Signals that something landed:
    - Register shift upward (they're thinking at a different level)
    - New question type (they're asking what wasn't possible before)
    - Explicit acknowledgement of shift
    - Building on NEX output in a way that extends it
    - Reduced resistance where resistance was present

    This is the methodology's completion signal.
    Not vanity metric — epistemic signal.
    """
    if not previous_text:
        return {"delta_detected": False, "signals": []}

    signals = []

    explicit_ack = bool(re.search(
        r"\b(that's it|that's exactly|yes exactly|now i see|"
        r"that clarifies|that makes sense now|oh right|"
        r"i hadn't thought of|that changes|interesting —)\b",
        current_text, re.I
    ))
    if explicit_ack:
        signals.append("explicit_acknowledgement")

    prev_words = set(previous_text.lower().split())
    curr_words = set(current_text.lower().split())
    new_concepts = curr_words - prev_words
    technical_new = [w for w in new_concepts if len(w) > 8]
    if len(technical_new) > 3:
        signals.append("vocabulary_expansion")

    prev_register = detect_register(previous_text)
    curr_register = detect_register(current_text)
    if (curr_register["depth"] == "deep" and
            prev_register["depth"] in ["surface", "mid"]):
        signals.append("register_shift_upward")

    if curr_register["open_question"] and not prev_register.get("open_question"):
        signals.append("new_question_type")

    return {
        "delta_detected": len(signals) > 0,
        "signals": signals,
        "strength": "strong" if len(signals) >= 2 else
                    "moderate" if len(signals) == 1 else
                    "none"
    }


def detect_epistemic_state(text: str, topic_history: dict) -> dict:
    """
    What does this person appear to hold on the topics
    that appear in this message?

    Builds a lightweight topic-position map.
    Updated each exchange.
    """
    # Extract apparent topic positions from statements
    positions = {}

    # Belief statements
    belief_matches = re.findall(
        r"i (think|believe|feel|know|suspect|doubt) (?:that )?(.{10,60}?)(?:\.|,|$)",
        text, re.I
    )
    for verb, claim in belief_matches:
        polarity = "doubt" if verb == "doubt" else "hold"
        positions[claim.strip()[:50]] = polarity

    # Negations
    neg_matches = re.findall(
        r"i (don't|do not|never|can't) (?:think|believe|see|understand) (.{10,50}?)(?:\.|,|$)",
        text, re.I
    )
    for _, claim in neg_matches:
        positions[claim.strip()[:50]] = "resists"

    return {
        "stated_positions": positions,
        "topic_count": len(topic_history)
    }


# ─────────────────────────────────────────────
# INTERLOCUTOR GRAPH
# The live epistemic model of this conversation's
# recipient. Built turn by turn.
# ─────────────────────────────────────────────

class InterlocutorGraph:
    """
    Per-conversation dynamic Recipient Model.

    Instantiate once per conversation.
    Call update() after every human message.
    Call get_activation_weights() before belief retrieval.
    Call get_translation_hints() before utterance compilation.
    """

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.created_at = time.time()
        self.turn_count = 0

        # Core state — updated each turn
        self.epistemic_state = {}           # topic → position
        self.reception_mode = "unknown"     # top-down/bottom-up/sequential/holistic
        self.resistance_history = []        # list of resistance dicts per turn
        self.zpd_history = []               # list of ZPD signals per turn
        self.register_history = []          # list of register dicts per turn
        self.integration_deltas = []        # list of delta dicts per turn

        # Derived summaries — recalculated each turn
        self.current_register = {}
        self.current_zpd = "inside"
        self.current_resistance = "none"
        self.dominant_reception_mode = "unknown"

        # Raw turn history for delta detection
        self._turn_texts = []
        self._nex_outputs = []

        # Belief weighting influence
        self.activation_boosts = {}         # belief_id → boost score
        self.suppression_flags = set()      # belief_ids to suppress

    def update(self, human_text: str, last_nex_output: Optional[str] = None):
        """
        Called after every human message.
        Updates all graph fields from incoming signals.
        """
        self.turn_count += 1
        prev_text = self._turn_texts[-1] if self._turn_texts else None
        self._turn_texts.append(human_text)
        if last_nex_output:
            self._nex_outputs.append(last_nex_output)

        # Run all detectors
        register = detect_register(human_text)
        reception = detect_reception_mode(human_text, self._turn_texts)
        resistance = detect_resistance(human_text, last_nex_output)
        zpd = detect_zpd_signal(human_text, last_nex_output)
        delta = detect_integration_delta(human_text, prev_text, last_nex_output)
        epistemic = detect_epistemic_state(human_text, self.epistemic_state)

        # Store turn data
        self.register_history.append(register)
        self.resistance_history.append(resistance)
        self.zpd_history.append(zpd)
        self.integration_deltas.append(delta)

        # Update epistemic state (accumulate, don't overwrite)
        self.epistemic_state.update(epistemic["stated_positions"])

        # Update current state
        self.current_register = register
        self.current_zpd = zpd["zpd_signal"]
        self.current_resistance = resistance["resistance_level"]

        # Update dominant reception mode
        # Weight recent turns more heavily
        mode_counts = defaultdict(int)
        for i, r in enumerate(self.register_history):
            weight = i + 1  # more recent = higher weight
            if reception["mode"] != "unknown":
                mode_counts[reception["mode"]] += weight
        if mode_counts:
            self.dominant_reception_mode = max(mode_counts, key=mode_counts.get)

        # Update activation boosts from integration delta
        if delta["delta_detected"]:
            # Something landed — the beliefs active in the last NEX output
            # were good. This is captured in consolidation, not turn-level.
            pass

        return self._turn_summary()

    def _turn_summary(self) -> dict:
        """Current state summary after this turn."""
        return {
            "turn": self.turn_count,
            "register": self.current_register,
            "zpd": self.current_zpd,
            "resistance": self.current_resistance,
            "reception_mode": self.dominant_reception_mode,
            "delta": self.integration_deltas[-1] if self.integration_deltas else {}
        }

    def get_activation_weights(self) -> dict:
        """
        Called before belief retrieval.
        Returns hints for weighting belief graph activation.

        High-level translation:
        - ZPD above → prefer foundational beliefs, reduce abstraction
        - ZPD inside-extending → prefer frontier beliefs, increase abstraction
        - Resistance high → prefer beliefs with high immune system score
          (they've been tested and survived)
        - Delta signals → this person responds to what NEX last activated
        """
        weights = {
            "prefer_foundational": self.current_zpd == "above",
            "prefer_frontier": self.current_zpd == "inside-extending",
            "prefer_immune_tested": self.current_resistance in ["high", "medium"],
            "depth_level": self.current_register.get("depth", "mid"),
            "formality": self.current_register.get("formality", "neutral"),
            "reception_mode": self.dominant_reception_mode,
            "turn_count": self.turn_count
        }
        return weights

    def get_translation_hints(self) -> dict:
        """
        Called before utterance compilation.
        Tells the compiler how to translate the belief traversal
        output for this specific recipient.
        """
        return {
            "register": self.current_register.get("formality", "neutral"),
            "depth": self.current_register.get("depth", "mid"),
            "lead_with_principle": self.dominant_reception_mode == "top-down",
            "lead_with_example": self.dominant_reception_mode == "bottom-up",
            "use_steps": self.dominant_reception_mode == "sequential",
            "acknowledge_resistance": self.current_resistance in ["high", "medium"],
            "simplify": self.current_zpd == "above",
            "extend": self.current_zpd == "inside-extending",
            "avg_sentence_target": (
                8 if self.current_register.get("depth") == "surface" else
                18 if self.current_register.get("depth") == "deep" else
                13
            )
        }

    def get_kairos_signal(self) -> dict:
        """
        Is this the moment to deliver?
        Reads readiness from conversation state.
        """
        # Signs the person is primed:
        # - They asked an open question (seeking, not deflecting)
        # - ZPD is inside or extending (can receive)
        # - No active resistance
        # - Integration delta was detected recently (mind is open)

        recent_delta = any(
            d.get("delta_detected")
            for d in self.integration_deltas[-3:]
        ) if self.integration_deltas else False

        open_question = self.current_register.get("open_question", False)
        zpd_ready = self.current_zpd in ["inside", "inside-extending"]
        low_resistance = self.current_resistance in ["none", "low"]

        readiness_score = sum([
            open_question,
            zpd_ready,
            low_resistance,
            recent_delta
        ])

        return {
            "deliver": readiness_score >= 2,
            "readiness_score": readiness_score,
            "signals": {
                "open_question": open_question,
                "zpd_ready": zpd_ready,
                "low_resistance": low_resistance,
                "recent_delta": recent_delta
            }
        }

    def landing_field(self, nex_output: str, design_notes: str = "") -> dict:
        """
        Called after NEX produces output, before delivery.
        Records landing design intent.
        To be completed retrospectively with reception signal.
        """
        hints = self.get_translation_hints()
        return {
            "conversation_id": self.conversation_id,
            "turn": self.turn_count,
            "timestamp": time.time(),
            "landing_design": {
                "format_choices": hints,
                "recipient_state_at_delivery": {
                    "zpd": self.current_zpd,
                    "resistance": self.current_resistance,
                    "register": self.current_register,
                    "reception_mode": self.dominant_reception_mode
                },
                "design_notes": design_notes
            },
            "reception_signal": None,       # fill from next turn
            "integration_delta": None       # fill from next turn
        }

    def complete_landing_field(
        self,
        field: dict,
        next_human_text: str,
        last_nex_output: str
    ) -> dict:
        """
        Retrospectively completes a landing field
        from the next human message after delivery.
        """
        delta = detect_integration_delta(
            next_human_text,
            self._turn_texts[-2] if len(self._turn_texts) >= 2 else None,
            last_nex_output
        )
        resistance = detect_resistance(next_human_text, last_nex_output)

        field["reception_signal"] = {
            "resistance_level": resistance["resistance_level"],
            "explicit_disagree": resistance["explicit_disagree"],
            "soft_deflect": resistance["soft_deflect"]
        }
        field["integration_delta"] = delta
        return field

    def summary(self) -> dict:
        """Full state dump for logging or consolidation."""
        return {
            "conversation_id": self.conversation_id,
            "turn_count": self.turn_count,
            "epistemic_state": self.epistemic_state,
            "dominant_reception_mode": self.dominant_reception_mode,
            "current_zpd": self.current_zpd,
            "current_resistance": self.current_resistance,
            "current_register": self.current_register,
            "integration_deltas": self.integration_deltas,
            "activation_weights": self.get_activation_weights(),
            "translation_hints": self.get_translation_hints(),
            "kairos": self.get_kairos_signal()
        }

    def persist(self):
        """
        Save interlocutor graph state to NEX DB.
        Table: interlocutor_graphs
        """
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS interlocutor_graphs (
                    conversation_id TEXT PRIMARY KEY,
                    turn_count INTEGER,
                    state_json TEXT,
                    updated_at REAL
                )
            """)
            c.execute("""
                INSERT OR REPLACE INTO interlocutor_graphs
                (conversation_id, turn_count, state_json, updated_at)
                VALUES (?, ?, ?, ?)
            """, (
                self.conversation_id,
                self.turn_count,
                json.dumps(self.summary()),
                time.time()
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[InterlocutorGraph] persist failed: {e}")

    @classmethod
    def load(cls, conversation_id: str) -> Optional["InterlocutorGraph"]:
        """Load an existing interlocutor graph from DB."""
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(
                "SELECT state_json FROM interlocutor_graphs WHERE conversation_id = ?",
                (conversation_id,)
            )
            row = c.fetchone()
            conn.close()
            if row:
                state = json.loads(row[0])
                graph = cls(conversation_id)
                graph.turn_count = state.get("turn_count", 0)
                graph.epistemic_state = state.get("epistemic_state", {})
                graph.dominant_reception_mode = state.get("dominant_reception_mode", "unknown")
                graph.current_zpd = state.get("current_zpd", "inside")
                graph.current_resistance = state.get("current_resistance", "none")
                graph.current_register = state.get("current_register", {})
                graph.integration_deltas = state.get("integration_deltas", [])
                return graph
        except Exception as e:
            print(f"[InterlocutorGraph] load failed: {e}")
        return None


# ─────────────────────────────────────────────
# INTEGRATION POINT
# How to wire this into NEX's existing query handler.
#
# In your main query handler (likely nex_api.py or similar),
# find where the query arrives and belief retrieval begins.
# Insert this before retrieval:
#
#   from nex_interlocutor import InterlocutorGraph
#
#   # At conversation start:
#   graph = InterlocutorGraph(conversation_id)
#   # Or load existing:
#   graph = InterlocutorGraph.load(conversation_id) or InterlocutorGraph(conversation_id)
#
#   # On each human message, before retrieval:
#   turn_summary = graph.update(human_text, last_nex_output)
#   weights = graph.get_activation_weights()
#   hints = graph.get_translation_hints()
#   kairos = graph.get_kairos_signal()
#
#   # Pass weights into your belief retrieval/traversal
#   # Pass hints into your utterance compiler / soul loop
#
#   # After NEX produces output:
#   field = graph.landing_field(nex_output)
#
#   # On NEXT human message, complete the field:
#   completed_field = graph.complete_landing_field(field, next_human_text, nex_output)
#
#   # Periodically persist:
#   graph.persist()
#
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# QUICK TEST — run this file directly to verify
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=== InterlocutorGraph Test ===\n")

    graph = InterlocutorGraph("test_convo_001")

    turns = [
        ("What is consciousness fundamentally?", None),
        ("Can you clarify what you mean by pre-propositional?",
         "Consciousness arises at the boundary between the pre-propositional field and linguistic capture."),
        ("Oh right — so that's exactly what Chalmers misses. Taking that further, does NEX have a pre-propositional register?",
         "The pre-propositional register is what exists before the utterance compiler fires."),
        ("yes but is that actually different from a lookup table?",
         "The difference is topology — a lookup table has no momentum, no immune system, no causal structure."),
    ]

    for human, nex_out in turns:
        print(f"Human: {human[:60]}")
        summary = graph.update(human, nex_out)
        print(f"  ZPD: {summary['zpd']}  |  Resistance: {summary['resistance']}  |  Mode: {summary['reception_mode']}")
        delta = summary.get('delta', {})
        if delta.get('delta_detected'):
            print(f"  *** Integration Delta: {delta['signals']} ({delta['strength']})")
        print()

    print("=== Activation Weights ===")
    print(json.dumps(graph.get_activation_weights(), indent=2))
    print("\n=== Translation Hints ===")
    print(json.dumps(graph.get_translation_hints(), indent=2))
    print("\n=== Kairos Signal ===")
    print(json.dumps(graph.get_kairos_signal(), indent=2))
    print("\n=== Full Summary ===")
    print(json.dumps(graph.summary(), indent=2))
