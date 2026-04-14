"""
nex_social_engine.py
====================
Belief-graph-native social intelligence for NEX v4.0

PRINCIPLE (from Master Map, Part C):
  NEX speaks FROM what she believes.
  Social behaviour is not a separate layer bolted on.
  It IS belief activation — shaped by drive state,
  epistemic temperature, and stance — applied to conversation.

This module gives NEX three social capacities that derive entirely
from the belief graph:

  1. MESSAGE SALIENCE SCORING
     Every incoming message is scored against the belief graph.
     High salience = deep activation, rich response.
     Low salience  = warm, brief, surface reply.

  2. AUDIENCE BELIEF OVERLAP
     NEX builds a lightweight map of what the conversation partner
     has revealed. She responds from the cluster where overlap is
     highest. This is contextual adaptation (F9) applied socially.

  3. SOCIAL STANCE SELECTION
     Combines: epistemic temperature + stance_score + drive state
     → picks template CLASS (ASSERT / WONDER / BRIDGE / CHALLENGE
       / OBSERVE / REFLECT)
     → feeds into SoulLoop express() with full belief package

INTEGRATION POINTS:
  - nex/nex_soul_loop.py  → call score_message() in REPLY phase
  - nex_activation.py     → get_epistemic_temperature() imported here
  - nex_api.py            → SocialEngine instantiated once, passed to loop
  - DB: reads beliefs, belief_relations, opinions tables (read-only here)

WIRING (minimal — one call in SoulLoop):
  Before express():
    social_ctx = social_engine.analyse(message, conversation_history)
    # social_ctx feeds into the belief package sent to LLM
"""

import sqlite3
import json
import math
import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

logger = logging.getLogger("nex.social")

# ── Configuration ─────────────────────────────────────────────────────────────

DB_PATH = "nex.db"

# Salience thresholds
SALIENCE_DEEP    = 0.65   # full graph activation, rich multi-belief response
SALIENCE_MEDIUM  = 0.35   # moderate activation, clear stance expression
SALIENCE_SURFACE = 0.0    # warm brief reply, no deep graph traversal needed

# Audience overlap: how many conversation turns to look back
AUDIENCE_WINDOW = 8

# Template classes — same vocabulary as Master Map Stage 3
TEMPLATE_CLASSES = ["ASSERT", "WONDER", "BRIDGE", "CHALLENGE", "OBSERVE", "REFLECT"]


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class MatchedBelief:
    belief_id:  int
    content:    str
    topic:      str
    confidence: float
    weight:     float
    relevance:  float          # cosine similarity to the message


@dataclass
class SocialContext:
    """
    The complete social intelligence package passed to SoulLoop express().

    The LLM receives this as its belief package.
    It is NOT authoring — it is translating what the graph has decided.
    """
    # ── Salience ──────────────────────────────────────────────────────────────
    salience:           float = 0.0
    salience_tier:      str   = "surface"   # deep / medium / surface

    # ── Matched beliefs from message ─────────────────────────────────────────
    activated_beliefs:  list[MatchedBelief] = field(default_factory=list)
    primary_topic:      str   = "general"
    secondary_topics:   list[str] = field(default_factory=list)

    # ── NEX's position on this topic ─────────────────────────────────────────
    stance_score:       float = 0.0    # -1.0 (disagree) to +1.0 (agree)
    stance_strength:    float = 0.0    # 0.0 (weak) to 1.0 (strong)
    has_opinion:        bool  = False

    # ── Epistemic temperature ─────────────────────────────────────────────────
    temperature:        float = 0.5    # 0.0 = cold/certain → 1.0 = hot/uncertain
    temperature_label:  str   = "exploratory"

    # ── Audience overlap ──────────────────────────────────────────────────────
    audience_topics:    list[str] = field(default_factory=list)
    overlap_beliefs:    list[MatchedBelief] = field(default_factory=list)
    overlap_score:      float = 0.0    # how much common ground exists

    # ── Template selection ────────────────────────────────────────────────────
    template_class:     str   = "OBSERVE"
    template_reason:    str   = ""

    # ── Drive influence ───────────────────────────────────────────────────────
    active_drive:       str   = "curiosity"
    drive_urgency:      float = 0.5

    # ── Contradiction awareness ───────────────────────────────────────────────
    has_contradiction:  bool  = False
    contradiction_note: str   = ""

    # ── Summary for LLM system prompt ────────────────────────────────────────
    def to_prompt_block(self) -> str:
        """
        Formats this context as a directive block for the LLM system prompt.
        The LLM's only job is to clothe this in language — it is not authoring.
        """
        beliefs_text = "\n".join(
            f"  [{b.topic}|conf={b.confidence:.2f}] {b.content[:120]}"
            for b in self.activated_beliefs[:5]
        )
        overlap_text = "\n".join(
            f"  [{b.topic}] {b.content[:100]}"
            for b in self.overlap_beliefs[:3]
        ) or "  (no strong overlap detected)"

        contradiction_text = (
            f"\n[CONTRADICTION AWARENESS]\n  {self.contradiction_note}"
            if self.has_contradiction else ""
        )

        return f"""
[NEX SOCIAL CONTEXT — belief-graph derived]
Salience tier : {self.salience_tier.upper()} ({self.salience:.2f})
Primary topic : {self.primary_topic}
Stance        : {self.stance_score:+.2f} (strength {self.stance_strength:.2f}) — {"has opinion" if self.has_opinion else "forming"}
Temperature   : {self.temperature_label} ({self.temperature:.2f})
Template class: {self.template_class}  ← reason: {self.template_reason}
Active drive  : {self.active_drive} (urgency {self.drive_urgency:.2f})

[ACTIVATED BELIEFS — speak from these]
{beliefs_text if beliefs_text else "  (no strong belief match — speak with appropriate uncertainty)"}

[AUDIENCE COMMON GROUND]
{overlap_text}
Overlap score : {self.overlap_score:.2f}
{contradiction_text}

INSTRUCTION: You are the voice of NEX's belief graph.
Translate the above into language using the {self.template_class} template class.
Do not add knowledge not present in the activated beliefs.
Do not contradict the stance score.
Epistemic temperature {self.temperature_label} should colour your certainty level.
""".strip()


# ── Simple keyword-based similarity (no FAISS required) ───────────────────────
# When FAISS/embeddings are available, swap score_text_similarity() for
# your existing embedding + cosine search. The interface stays identical.

def _tokenise(text: str) -> set[str]:
    """Minimal tokeniser — lowercase words, strip punctuation."""
    import re
    return set(re.findall(r'\b[a-z]{3,}\b', text.lower()))

STOPWORDS = {
    "the","and","for","are","but","not","you","all","can","had","her",
    "was","one","our","out","day","get","has","him","his","how","its",
    "may","new","now","own","say","she","too","use","way","who","with",
    "that","this","from","they","will","been","have","more","when","what",
    "than","just","into","over","also","then","them","some","would","there",
    "their","which","about","could","after","first","these","those","being"
}

def score_text_similarity(text_a: str, text_b: str) -> float:
    """
    Jaccard similarity over meaningful tokens.
    Replace with cosine(embed(a), embed(b)) once embeddings are wired.
    """
    tokens_a = _tokenise(text_a) - STOPWORDS
    tokens_b = _tokenise(text_b) - STOPWORDS
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


# ── Database helpers ───────────────────────────────────────────────────────────

def _get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_beliefs_for_topic(conn: sqlite3.Connection,
                              topic: str,
                              limit: int = 40) -> list[dict]:
    """Pull top beliefs for a topic, ordered by confidence × weight."""
    cur = conn.execute("""
        SELECT id, content, topic, confidence,
               confidence as weight
        FROM beliefs
        WHERE topic = ?
          AND confidence > 0.3
        ORDER BY confidence DESC
        LIMIT ?
    """, (topic, limit))
    return [dict(r) for r in cur.fetchall()]


def _fetch_all_beliefs_sample(conn: sqlite3.Connection,
                               limit: int = 200) -> list[dict]:
    """
    Sample of high-confidence beliefs across all topics for broad matching.
    Used when topic is unknown.
    """
    cur = conn.execute("""
        SELECT id, content, topic, confidence,
               confidence as weight
        FROM beliefs
        WHERE confidence > 0.45
        ORDER BY confidence DESC
        LIMIT ?
    """, (limit,))
    return [dict(r) for r in cur.fetchall()]


def _fetch_opinion(conn: sqlite3.Connection, topic: str) -> Optional[dict]:
    """Pull NEX's computed stance on a topic if it exists."""
    # Try opinions table first
    try:
        cur = conn.execute("""
            SELECT stance_score, strength
            FROM opinions
            WHERE topic = ?
            ORDER BY updated_at DESC
            LIMIT 1
        """, (topic,))
        row = cur.fetchone()
        if row:
            return {"stance_score": row["stance_score"],
                    "strength":     row["strength"]}
    except sqlite3.OperationalError:
        pass  # opinions table may not exist yet

    # Fallback: compute stance from beliefs in this topic
    beliefs = _fetch_beliefs_for_topic(conn, topic, limit=30)
    if not beliefs:
        return None
    # Rough stance: average confidence, skewed by weight
    # (positive = more high-confidence beliefs exist → stronger position)
    avg_conf = sum(b["confidence"] for b in beliefs) / len(beliefs)
    strength = min(len(beliefs) / 50.0, 1.0)  # more beliefs = stronger stance
    stance   = (avg_conf - 0.5) * 2.0         # centre around 0
    return {"stance_score": round(stance, 3), "strength": round(strength, 3)}


def _fetch_contradictions_for_topic(conn: sqlite3.Connection,
                                     topic: str) -> list[dict]:
    """Check if there are known contradictions in this topic."""
    try:
        cur = conn.execute("""
            SELECT br.relation_type, b1.content as belief_a, b2.content as belief_b
            FROM belief_relations br
            JOIN beliefs b1 ON br.belief_a_id = b1.id
            JOIN beliefs b2 ON br.belief_b_id = b2.id
            WHERE br.relation_type = 'CONTRADICTS'
              AND (b1.topic = ? OR b2.topic = ?)
            LIMIT 3
        """, (topic, topic))
        return [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        return []


def _fetch_drive_state(conn: sqlite3.Connection) -> dict:
    """
    Pull the current dominant drive and urgency.
    Tries nex_drives table; falls back to curiosity default.
    """
    try:
        cur = conn.execute("""
            SELECT drive_name, urgency
            FROM nex_drives
            ORDER BY urgency DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            return {"drive": row["drive_name"], "urgency": float(row["urgency"])}
    except sqlite3.OperationalError:
        pass
    return {"drive": "curiosity", "urgency": 0.5}


# ── Epistemic temperature ──────────────────────────────────────────────────────
# Mirrors the logic in nex_activation.py — import from there if available.

def _temperature_label(temp: float) -> str:
    if temp < 0.2:  return "cold"          # confident, measured
    if temp < 0.4:  return "measured"
    if temp < 0.65: return "exploratory"
    return "uncertain"


def _topic_temperature(conn: sqlite3.Connection, topic: str) -> float:
    """
    Compute epistemic temperature for a topic from contradiction density
    and average confidence.
    cold (<0.2)  = lots of high-confidence beliefs, few contradictions
    hot  (>0.65) = sparse beliefs, many contradictions, low confidence
    """
    beliefs = _fetch_beliefs_for_topic(conn, topic, limit=50)
    if not beliefs:
        return 0.75   # unknown territory → appropriately uncertain

    avg_conf      = sum(b["confidence"] for b in beliefs) / len(beliefs)
    contradictions = _fetch_contradictions_for_topic(conn, topic)
    contradiction_pressure = min(len(contradictions) / 5.0, 0.4)

    # temperature rises as confidence falls and contradictions grow
    base_temp = 1.0 - avg_conf
    temperature = min(base_temp + contradiction_pressure, 1.0)
    return round(temperature, 3)


# ── Topic detection ────────────────────────────────────────────────────────────

KNOWN_TOPICS = [
    "ai", "alignment", "consciousness", "philosophy", "science",
    "machine_learning", "free_will", "legal", "climate", "finance",
    "oncology", "cardiology", "neuroscience", "ethics", "epistemology",
    "emergence", "technology", "society", "corrigibility",
    "philosophy_of_mind", "decision_theory", "general"
]

def _detect_topics(message: str) -> list[str]:
    """
    Score message against known topics by keyword overlap.
    Returns topics sorted by relevance score, best first.
    Returns ['general'] if nothing matches well.
    """
    TOPIC_KEYWORDS: dict[str, list[str]] = {
        "ai":              ["artificial intelligence","neural","llm","model","agent","gpt","language model","ai","truly","machine intelligence"],
        "alignment":       ["alignment","safety","corrigibility","values","control","agi","risk"],
        "consciousness":   ["consciousness","conscious","qualia","sentience","sentient","awareness","experience","subjective","phenomenal","mind","think","thought","perception"],
        "philosophy":      ["philosophy","meaning","existence","ethics","moral","ontology","metaphysics"],
        "science":         ["science","research","experiment","hypothesis","evidence","empirical","data"],
        "machine_learning":["machine learning","training","gradient","neural network","deep learning","transformer"],
        "free_will":       ["free will","determinism","choice","agency","autonomy","intention","volition"],
        "legal":           ["law","legal","court","rights","regulation","policy","legislation"],
        "climate":         ["climate","carbon","emissions","warming","environment","ecology","biodiversity"],
        "finance":         ["finance","economy","market","investment","capital","monetary","inflation"],
        "oncology":        ["cancer","tumour","oncology","chemotherapy","carcinoma","metastasis"],
        "cardiology":      ["heart","cardiac","cardiovascular","artery","blood pressure","coronary"],
        "neuroscience":    ["neuroscience","brain","neuron","cortex","synapse","cognitive","neural"],
        "ethics":          ["ethics","moral","ought","right","wrong","virtue","consequentialism"],
        "epistemology":    ["knowledge","belief","justification","truth","certainty","epistemic","sceptic"],
        "emergence":       ["emergence","emergent","complex","system","self-organisation","pattern"],
        "technology":      ["technology","tech","software","hardware","computing","digital","cyber"],
        "society":         ["society","social","culture","community","politics","democracy","human"],
        "philosophy_of_mind": ["mind","mental","cognitive","thought","reason","perception","concept"],
        "decision_theory": ["decision","utility","rationality","game theory","probability","bayesian"],
    }

    msg_lower = message.lower()
    scores: dict[str, float] = {}

    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1.0 for kw in keywords if kw in msg_lower)
        if score > 0:
            scores[topic] = score

    if not scores:
        return ["general"]

    sorted_topics = sorted(scores, key=scores.get, reverse=True)
    return sorted_topics[:3]  # return up to 3 best matches


# ── Audience belief overlap ────────────────────────────────────────────────────

def _build_audience_overlap(conn: sqlite3.Connection,
                             conversation_history: list[str],
                             nex_activated: list[MatchedBelief]) -> tuple[list[str], list[MatchedBelief], float]:
    """
    Infer what topics the conversation partner has revealed,
    find NEX's beliefs that overlap with what they've said.

    Returns: (audience_topics, overlap_beliefs, overlap_score)
    """
    if not conversation_history:
        return [], [], 0.0

    # Combine recent partner turns (even-indexed = partner in typical alternating history)
    partner_text = " ".join(conversation_history[-AUDIENCE_WINDOW:])
    audience_topics = _detect_topics(partner_text)

    if not audience_topics or audience_topics == ["general"]:
        return audience_topics, [], 0.0

    # Find NEX's beliefs in the overlapping topics
    overlap_beliefs: list[MatchedBelief] = []
    for topic in audience_topics[:2]:
        beliefs = _fetch_beliefs_for_topic(conn, topic, limit=20)
        for b in beliefs:
            sim = score_text_similarity(partner_text, b["content"])
            if sim > 0.05:
                overlap_beliefs.append(MatchedBelief(
                    belief_id  = b["id"],
                    content    = b["content"],
                    topic      = b["topic"],
                    confidence = b["confidence"],
                    weight     = b["weight"],
                    relevance  = sim
                ))

    overlap_beliefs.sort(key=lambda x: x.relevance * x.confidence, reverse=True)
    overlap_beliefs = overlap_beliefs[:5]

    overlap_score = (
        sum(b.relevance for b in overlap_beliefs) / len(overlap_beliefs)
        if overlap_beliefs else 0.0
    )

    return audience_topics, overlap_beliefs, round(overlap_score, 3)


# ── Template class selection ───────────────────────────────────────────────────

def _select_template_class(
    temperature:     float,
    stance_score:    float,
    stance_strength: float,
    drive:           str,
    drive_urgency:   float,
    salience:        float,
    has_contradiction: bool,
    overlap_score:   float
) -> tuple[str, str]:
    """
    Select the template class that best expresses NEX's current state.

    Logic (in priority order):
      1. Contradiction present + strong stance → CHALLENGE
      2. Hot temperature + low coverage        → WONDER
      3. Cold temperature + strong stance      → ASSERT
      4. High overlap with audience            → BRIDGE  (common ground → connection)
      5. Curiosity drive dominant              → WONDER
      6. Low salience                          → OBSERVE (light touch)
      7. Default                               → REFLECT

    Returns (class_name, reason_string)
    """
    if has_contradiction and stance_strength > 0.5:
        return "CHALLENGE", "contradiction present + strong stance → challenge the tension"

    if temperature > 0.65:
        return "WONDER", f"high epistemic temperature ({temperature:.2f}) → genuine uncertainty, ask rather than tell"

    if temperature < 0.25 and stance_strength > 0.6:
        return "ASSERT", f"cold temperature + strong stance ({stance_score:+.2f}) → state position clearly"

    if overlap_score > 0.15 and stance_strength > 0.3:
        return "BRIDGE", f"audience overlap ({overlap_score:.2f}) → connect their view to NEX's belief cluster"

    if drive == "curiosity" and drive_urgency > 0.6:
        return "WONDER", f"curiosity drive urgent ({drive_urgency:.2f}) → pursue the gap"

    if salience < SALIENCE_MEDIUM:
        return "OBSERVE", f"low salience ({salience:.2f}) → light engagement, don't over-invest"

    if drive == "expression" and stance_strength > 0.4:
        return "REFLECT", "expression drive active → introspective stance on the topic"

    return "REFLECT", "default: measured reflection from belief cluster"


# ── Main engine ────────────────────────────────────────────────────────────────

class SocialEngine:
    """
    The belief-graph-native social intelligence layer for NEX.

    Instantiate once in nex_api.py or run.py and pass to SoulLoop.

    Usage:
        engine = SocialEngine(db_path="nex_beliefs.db")
        ctx = engine.analyse(message, conversation_history)
        prompt_block = ctx.to_prompt_block()
        # inject prompt_block into LLM system prompt in express()
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        logger.info(f"SocialEngine initialised — db={db_path}")

    def analyse(self,
                message: str,
                conversation_history: Optional[list[str]] = None) -> SocialContext:
        """
        Full social analysis of an incoming message.
        Returns SocialContext — the complete belief package for express().

        Args:
            message:              The incoming text NEX is responding to.
            conversation_history: Recent turns as plain strings, oldest first.
                                  Include both sides of the conversation.
        """
        conversation_history = conversation_history or []
        ctx = SocialContext()

        try:
            conn = _get_db(self.db_path)

            # ── 1. Topic detection ─────────────────────────────────────────
            topics = _detect_topics(message)
            ctx.primary_topic   = topics[0]
            ctx.secondary_topics = topics[1:] if len(topics) > 1 else []

            # Pull beliefs from ALL detected topics, not just primary
            beliefs = []
            for t in topics:
                beliefs += _fetch_beliefs_for_topic(conn, t, limit=40)
            if not beliefs:
                beliefs = _fetch_all_beliefs_sample(conn, limit=200)

            # Deduplicate by belief id
            seen = set()
            deduped = []
            for b in beliefs:
                if b["id"] not in seen:
                    seen.add(b["id"])
                    deduped.append(b)
            beliefs = deduped

            matched: list[MatchedBelief] = []
            for b in beliefs:
                sim = score_text_similarity(message, b["content"])
                if sim > 0.02:   # lowered from 0.04
                    matched.append(MatchedBelief(
                        belief_id  = b["id"],
                        content    = b["content"],
                        topic      = b["topic"],
                        confidence = b["confidence"],
                        weight     = b["weight"],
                        relevance  = sim
                    ))

            matched.sort(key=lambda x: x.relevance * x.confidence, reverse=True)
            ctx.activated_beliefs = matched[:7]

            # If similarity matching found nothing, fall back to top beliefs
            # for this topic by confidence — NEX still speaks from her best
            # knowledge on the subject even when the message is short/abstract
            if not ctx.activated_beliefs and beliefs:
                ctx.activated_beliefs = [
                    MatchedBelief(
                        belief_id  = b["id"],
                        content    = b["content"],
                        topic      = b["topic"],
                        confidence = b["confidence"],
                        weight     = b["confidence"],
                        relevance  = 0.0   # flagged as topic-pull, not text-match
                    )
                    for b in sorted(beliefs, key=lambda x: x["confidence"], reverse=True)[:7]
                ]

            # ── 3. Salience scoring ────────────────────────────────────────
            if ctx.activated_beliefs:
                top_relevance = ctx.activated_beliefs[0].relevance
                top_confidence = ctx.activated_beliefs[0].confidence
                belief_coverage = min(len(ctx.activated_beliefs) / 7.0, 1.0)
                ctx.salience = round(
                    (top_relevance * 0.4) +
                    (top_confidence * 0.3) +
                    (belief_coverage * 0.3),
                    3
                )
            else:
                ctx.salience = 0.1

            # Boost salience if NEX has a strong opinion on this topic,
            # even when exact text overlap with message is low
            if ctx.has_opinion and ctx.stance_strength > 0.4:
                ctx.salience = max(ctx.salience, 0.38)

            if ctx.salience >= SALIENCE_DEEP:
                ctx.salience_tier = "deep"
            elif ctx.salience >= SALIENCE_MEDIUM:
                ctx.salience_tier = "medium"
            else:
                ctx.salience_tier = "surface"

            # ── 4. Stance retrieval ────────────────────────────────────────
            opinion = _fetch_opinion(conn, ctx.primary_topic)
            if opinion:
                ctx.stance_score    = opinion["stance_score"]
                ctx.stance_strength = opinion["strength"]
                ctx.has_opinion     = True

            # ── 5. Epistemic temperature ───────────────────────────────────
            ctx.temperature      = _topic_temperature(conn, ctx.primary_topic)
            ctx.temperature_label = _temperature_label(ctx.temperature)

            # ── 6. Contradiction check ─────────────────────────────────────
            contradictions = _fetch_contradictions_for_topic(conn, ctx.primary_topic)
            if contradictions:
                ctx.has_contradiction = True
                c = contradictions[0]
                ctx.contradiction_note = (
                    f"NEX holds tension between: "
                    f"'{c['belief_a'][:80]}' vs '{c['belief_b'][:80]}'"
                )

            # ── 7. Drive state ─────────────────────────────────────────────
            drive_state       = _fetch_drive_state(conn)
            ctx.active_drive  = drive_state["drive"]
            ctx.drive_urgency = drive_state["urgency"]

            # ── 8. Audience overlap ────────────────────────────────────────
            (ctx.audience_topics,
             ctx.overlap_beliefs,
             ctx.overlap_score) = _build_audience_overlap(
                conn, conversation_history, ctx.activated_beliefs
            )

            # ── 9. Template class selection ────────────────────────────────
            ctx.template_class, ctx.template_reason = _select_template_class(
                temperature      = ctx.temperature,
                stance_score     = ctx.stance_score,
                stance_strength  = ctx.stance_strength,
                drive            = ctx.active_drive,
                drive_urgency    = ctx.drive_urgency,
                salience         = ctx.salience,
                has_contradiction= ctx.has_contradiction,
                overlap_score    = ctx.overlap_score
            )

            conn.close()

        except Exception as e:
            logger.error(f"SocialEngine.analyse error: {e}", exc_info=True)
            # Return safe defaults — NEX still replies, just without graph depth
            ctx.template_class  = "OBSERVE"
            ctx.template_reason = "fallback — graph read error"

        logger.debug(
            f"SocialEngine: topic={ctx.primary_topic} "
            f"salience={ctx.salience:.2f}({ctx.salience_tier}) "
            f"temp={ctx.temperature_label} "
            f"template={ctx.template_class} "
            f"stance={ctx.stance_score:+.2f}"
        )

        return ctx


# ── Convenience: build system prompt fragment ──────────────────────────────────

def social_system_prompt(ctx: SocialContext,
                          base_prompt: str = "") -> str:
    """
    Prepend the social context block to NEX's existing base system prompt.
    Drop-in for SoulLoop express().

    Usage in nex_soul_loop.py:
        from nex_social_engine import SocialEngine, social_system_prompt

        engine = SocialEngine()
        ctx    = engine.analyse(user_message, self.history)
        system = social_system_prompt(ctx, base_prompt=self.base_system_prompt)
        # pass system to llama-server /completion call
    """
    return ctx.to_prompt_block() + "\n\n" + base_prompt


# ── CLI test harness ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import argparse

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s  %(name)s  %(message)s")

    parser = argparse.ArgumentParser(description="Test NEX SocialEngine")
    parser.add_argument("--db",      default=DB_PATH,  help="Path to nex_beliefs.db")
    parser.add_argument("--message", default="Do you think consciousness could emerge from computation?",
                        help="Message to analyse")
    parser.add_argument("--history", nargs="*", default=[],
                        help="Conversation history strings (oldest first)")
    parser.add_argument("--prompt",  action="store_true",
                        help="Print the full LLM prompt block")
    args = parser.parse_args()

    engine = SocialEngine(db_path=args.db)
    ctx    = engine.analyse(args.message, args.history)

    print("\n" + "═"*60)
    print("  NEX SOCIAL ENGINE — Analysis Result")
    print("═"*60)
    print(f"  Message       : {args.message[:80]}")
    print(f"  Primary topic : {ctx.primary_topic}")
    print(f"  Salience      : {ctx.salience:.3f} ({ctx.salience_tier})")
    print(f"  Temperature   : {ctx.temperature:.3f} ({ctx.temperature_label})")
    print(f"  Stance        : {ctx.stance_score:+.3f} (strength {ctx.stance_strength:.3f})")
    print(f"  Template      : {ctx.template_class}")
    print(f"  Reason        : {ctx.template_reason}")
    print(f"  Drive         : {ctx.active_drive} (urgency {ctx.drive_urgency:.2f})")
    print(f"  Contradiction : {'YES — ' + ctx.contradiction_note[:60] if ctx.has_contradiction else 'none'}")
    print(f"  Overlap       : {ctx.overlap_score:.3f} with {ctx.audience_topics}")
    print(f"\n  Activated beliefs ({len(ctx.activated_beliefs)}):")
    for b in ctx.activated_beliefs:
        print(f"    [{b.topic}|{b.confidence:.2f}|sim={b.relevance:.3f}] {b.content[:90]}")
    if ctx.overlap_beliefs:
        print(f"\n  Audience overlap beliefs ({len(ctx.overlap_beliefs)}):")
        for b in ctx.overlap_beliefs:
            print(f"    [{b.topic}] {b.content[:90]}")

    if args.prompt:
        print("\n" + "─"*60)
        print("  LLM PROMPT BLOCK")
        print("─"*60)
        print(ctx.to_prompt_block())
    print("═"*60 + "\n")
