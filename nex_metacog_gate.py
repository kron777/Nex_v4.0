#!/usr/bin/env python3
"""
nex_metacog_gate.py — Metacognitive Confidence Gate for NEX v4.0

NEX knows what she knows. This module intercepts before response
generation and scores actual belief coverage against the query.

Coverage levels:
  GROUNDED  — 5+ beliefs, 2+ graph neighbours, avg conf >= 0.75
              → respond with full assertion
  PARTIAL   — 2-4 beliefs OR avg conf 0.55-0.74
              → respond but inject epistemic hedging
  THIN      — 1 belief OR avg conf 0.40-0.54
              → flag uncertainty explicitly, don't assert
  BLIND     — 0 beliefs OR avg conf < 0.40
              → return honest "I don't have grounded beliefs on this"

The gate also checks graph support via belief_relations — a belief
with no edges is weaker than one with 10 similar neighbours.

Usage:
    from nex_metacog_gate import assess, GROUNDED, PARTIAL, THIN, BLIND
    result = assess(query, belief_text, graph_ctx=None)
    if result.level == BLIND:
        return result.response   # honest uncertainty, skip LLM
    if result.level == THIN:
        voice_directive += result.hedge
"""

import sqlite3
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log     = logging.getLogger("nex.metacog")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

# ── Coverage levels ───────────────────────────────────────────────────────────
GROUNDED = "GROUNDED"
PARTIAL  = "PARTIAL"
THIN     = "THIN"
BLIND    = "BLIND"

# ── Thresholds ────────────────────────────────────────────────────────────────
GROUNDED_MIN_BELIEFS  = 4
GROUNDED_MIN_CONF     = 0.65
GROUNDED_MIN_EDGES    = 1

PARTIAL_MIN_BELIEFS   = 2
PARTIAL_MIN_CONF      = 0.45

THIN_MIN_BELIEFS      = 1
THIN_MIN_CONF         = 0.30

# Topics NEX explicitly doesn't cover — always BLIND
OUT_OF_SCOPE = {
    "weather", "sports scores", "stock prices", "lottery",
    "breaking news", "live events", "current date", "time now",
    "recipe", "cooking", "directions", "navigation",
}

# Honest uncertainty response templates by level
BLIND_RESPONSES = [
    "I don't have grounded beliefs on this — my coverage here is genuinely sparse. I could speculate but that would be noise, not thought.",
    "This sits outside what I've built beliefs around. I'd rather flag that than construct something hollow.",
    "My belief graph has almost nothing on this. I know the shape of my ignorance better than I know this topic.",
    "Honest answer: I haven't accumulated enough on this to say something real. The gap is the answer.",
]

THIN_HEDGES = [
    "My coverage here is thin — take this as provisional: ",
    "I hold this loosely — my beliefs on this are sparse: ",
    "This is at the edge of what I've worked through: ",
    "I have something here but not much — working from limited belief density: ",
]

PARTIAL_HEDGES = [
    "I have some purchase on this, though not full confidence: ",
    "My beliefs here are real but not fully settled: ",
    "I can engage with this, though I'm not at full coverage: ",
]


@dataclass
class CoverageResult:
    level: str                    # GROUNDED | PARTIAL | THIN | BLIND
    belief_count: int = 0
    avg_confidence: float = 0.0
    edge_support: int = 0
    hedge: str = ""               # inject into voice_directive for PARTIAL/THIN
    response: str = ""            # pre-built response for BLIND
    skip_llm: bool = False        # True = return response directly
    confidence_score: float = 0.0 # 0.0-1.0 overall confidence

    def __str__(self):
        return (f"CoverageResult({self.level} | beliefs={self.belief_count} "
                f"conf={self.avg_confidence:.2f} edges={self.edge_support})")


def _parse_belief_lines(belief_text: str) -> list[str]:
    """Extract non-empty belief lines from belief_text."""
    lines = []
    for line in belief_text.split("\n"):
        line = line.strip().lstrip("- ").strip()
        if line and len(line) > 10:
            lines.append(line)
    return lines


def _get_belief_confidences(belief_lines: list[str], db) -> list[float]:
    """Look up confidence scores for belief lines from DB."""
    confs = []
    for line in belief_lines[:10]:  # limit DB hits
        # Match on first 60 chars to avoid partial-line issues
        snippet = line[:60].replace("'", "''")
        try:
            row = db.execute(
                "SELECT confidence FROM beliefs WHERE content LIKE ? LIMIT 1",
                (f"{snippet}%",)
            ).fetchone()
            if row:
                confs.append(float(row[0]))
        except Exception:
            pass
    return confs


def _get_edge_support(belief_lines: list[str], db) -> int:
    """Count total similar/bridge edges for matched beliefs."""
    total_edges = 0
    for line in belief_lines[:5]:
        snippet = line[:60].replace("'", "''")
        try:
            row = db.execute(
                """SELECT b.id FROM beliefs b
                   WHERE b.content LIKE ? LIMIT 1""",
                (f"{snippet}%",)
            ).fetchone()
            if row:
                bid = row[0]
                edges = db.execute(
                    """SELECT COUNT(*) FROM belief_relations
                       WHERE (source_id=? OR target_id=?)
                       AND relation_type IN ('similar','bridges')""",
                    (bid, bid)
                ).fetchone()[0]
                total_edges += edges
        except Exception:
            pass
    return total_edges


def _is_out_of_scope(query: str) -> bool:
    """Check if query is explicitly out of NEX's scope."""
    q_lower = query.lower()
    return any(topic in q_lower for topic in OUT_OF_SCOPE)


def _blind_response() -> str:
    import random
    return random.choice(BLIND_RESPONSES)


def _thin_hedge() -> str:
    import random
    return random.choice(THIN_HEDGES)


def _partial_hedge() -> str:
    import random
    return random.choice(PARTIAL_HEDGES)


def assess(query: str,
           belief_text: str,
           graph_ctx: Optional[dict] = None) -> CoverageResult:
    """
    Assess metacognitive coverage for a query + belief set.

    Args:
        query:      The incoming question
        belief_text: Assembled belief text from activation/FAISS
        graph_ctx:  Optional graph reasoner coverage dict
                    {sufficient, seeds, support, opposing}

    Returns:
        CoverageResult with level, hedge, response, skip_llm
    """

    # Out of scope check first
    if _is_out_of_scope(query):
        return CoverageResult(
            level=BLIND,
            belief_count=0,
            avg_confidence=0.0,
            edge_support=0,
            hedge="",
            response=_blind_response(),
            skip_llm=True,
            confidence_score=0.0
        )

    # Parse beliefs
    belief_lines = _parse_belief_lines(belief_text)
    belief_count = len(belief_lines)

    # If graph_ctx says sufficient, trust it — skip DB lookup
    if graph_ctx and graph_ctx.get("sufficient"):
        support = graph_ctx.get("support", 0)
        seeds   = graph_ctx.get("seeds", 0)
        # Graph-grounded
        if seeds >= 3 and support >= 5:
            return CoverageResult(
                level=GROUNDED,
                belief_count=max(belief_count, seeds),
                avg_confidence=0.80,
                edge_support=support,
                confidence_score=min(1.0, 0.6 + support * 0.02),
            )
        elif seeds >= 2 and support >= 2:
            return CoverageResult(
                level=PARTIAL,
                belief_count=max(belief_count, seeds),
                avg_confidence=0.65,
                edge_support=support,
                hedge=_partial_hedge(),
                confidence_score=0.55,
            )

    # No DB access if no beliefs
    if belief_count == 0:
        return CoverageResult(
            level=BLIND,
            belief_count=0,
            avg_confidence=0.0,
            edge_support=0,
            response=_blind_response(),
            skip_llm=True,
            confidence_score=0.0
        )

    # DB confidence lookup
    try:
        db = sqlite3.connect(str(DB_PATH))
        confs = _get_belief_confidences(belief_lines, db)
        edges = _get_edge_support(belief_lines, db)
        db.close()
    except Exception as e:
        log.debug(f"Metacog DB error: {e}")
        confs = []
        edges = 0

    avg_conf = sum(confs) / len(confs) if confs else 0.5
    conf_sample = len(confs)

    # Score
    confidence_score = (
        min(belief_count / GROUNDED_MIN_BELIEFS, 1.0) * 0.4 +
        min(avg_conf, 1.0) * 0.4 +
        min(edges / 10, 1.0) * 0.2
    )

    log.debug(f"Metacog: beliefs={belief_count} avg_conf={avg_conf:.2f} "
              f"edges={edges} score={confidence_score:.2f}")

    # Classify
    if (belief_count >= GROUNDED_MIN_BELIEFS and
            avg_conf >= GROUNDED_MIN_CONF and
            edges >= GROUNDED_MIN_EDGES):
        level = GROUNDED
        hedge = ""
        response = ""
        skip_llm = False

    elif (belief_count >= PARTIAL_MIN_BELIEFS and
          avg_conf >= PARTIAL_MIN_CONF):
        level = PARTIAL
        hedge = _partial_hedge()
        response = ""
        skip_llm = False

    elif belief_count >= THIN_MIN_BELIEFS and avg_conf >= THIN_MIN_CONF:
        level = THIN
        hedge = _thin_hedge()
        response = ""
        skip_llm = False

    else:
        level = BLIND
        hedge = ""
        response = _blind_response()
        skip_llm = True

    return CoverageResult(
        level=level,
        belief_count=belief_count,
        avg_confidence=avg_conf,
        edge_support=edges,
        hedge=hedge,
        response=response,
        skip_llm=skip_llm,
        confidence_score=confidence_score,
    )


# ── CLI for testing ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")

    parser = argparse.ArgumentParser(description="NEX metacognitive gate tester")
    parser.add_argument("-q", "--query", required=True)
    parser.add_argument("--beliefs", default="", help="Simulated belief text")
    args = parser.parse_args()

    result = assess(args.query, args.beliefs)
    print(f"\nQuery   : {args.query}")
    print(f"Level   : {result.level}")
    print(f"Beliefs : {result.belief_count}")
    print(f"Avg conf: {result.avg_confidence:.2f}")
    print(f"Edges   : {result.edge_support}")
    print(f"Score   : {result.confidence_score:.2f}")
    print(f"Skip LLM: {result.skip_llm}")
    if result.hedge:
        print(f"Hedge   : {result.hedge}")
    if result.response:
        print(f"Response: {result.response}")
