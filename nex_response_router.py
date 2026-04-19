"""
nex_response_router.py — Phase 2A tiered response router.

Formalizes the implicit PATH 1 / PATH 2 split in nex/nex_respond_v2.py into
three explicit tiers:

  Tier 0 — pure-Python composer (nex_tier0_composer.compose_tier0)
  Tier 1 — light LLM call (short prompt, low temperature, capped tokens)
  Tier 2 — full LLM call (current PATH 2 — structured prompt + retrieval)

The router takes features from RouteInput, evaluates routing rules from the
design sketch Section 3, returns a RouteDecision. For Tier 0 the composed
text is attached; for Tier 1/2 the caller invokes the LLM with the config
suggested by the decision.

Flag-gated via NEX_ROUTER env var — wiring lives in generate_reply. When the
flag is unset this module is dormant.

See NEX_RESPONSE_ROUTER_SKETCH.md for the design rationale.
"""

from __future__ import annotations
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

EXPERIMENTS_DB = Path(os.path.expanduser("~/Desktop/nex/nex_experiments.db"))

# Synthesis-requiring query markers (push to Tier 2 regardless of belief quality)
_SYNTHESIS_MARKERS = re.compile(
    r"\b(why|how come|what if|reflect on|describe the position|"
    r"synthesi[sz]e|reconcile|contradict|step outside)\b",
    re.IGNORECASE,
)

# Hard-override sources (always Tier 2)
_TIER2_SOURCES = {"r6_probe", "probe", "fountain", "strike"}


@dataclass
class BeliefHit:
    content: str
    confidence: float = 0.5
    topic: Optional[str] = None
    tfidf_score: float = 0.0


@dataclass
class RouteInput:
    query: str
    beliefs: List[BeliefHit]
    intent: str = "general"
    source: str = "live"
    history_hint: Optional[str] = None


@dataclass
class RouteDecision:
    tier: int
    reason: str
    score_dict: dict = field(default_factory=dict)
    composed_text: Optional[str] = None
    llm_config: Optional[dict] = None


# ── Feature extraction ───────────────────────────────────────────────────

def extract_features(ri: RouteInput) -> dict:
    """F1-F10 from sketch Section 3. Cheap, microsecond-scale."""
    beliefs = ri.beliefs or []
    n = len(beliefs)
    confs = [max(0.0, min(1.0, b.confidence)) for b in beliefs if b.content]
    scores = [max(0.0, b.tfidf_score) for b in beliefs if b.content]

    # F8 — synthesis markers
    marker = ""
    m = _SYNTHESIS_MARKERS.search(ri.query or "")
    if m:
        marker = m.group(0).lower()

    return {
        "n_beliefs":              n,
        "mean_confidence":        (sum(confs) / len(confs)) if confs else 0.0,
        "min_confidence":         min(confs) if confs else 0.0,
        "tfidf_top_score":        max(scores) if scores else 0.0,
        "contradiction_present":  False,   # reserved — needs belief_edges lookup
        "query_length_words":     len((ri.query or "").split()),
        "intent":                 ri.intent or "general",
        "query_marker":           marker,
        "source":                 ri.source or "live",
        "history_present":        bool(ri.history_hint),
    }


# ── Decision rules ───────────────────────────────────────────────────────

def decide(features: dict, source: str) -> Tuple[int, str]:
    """
    Return (tier, reason). Order matters:
      1. Hard overrides (source, contradictions, synthesis markers) → Tier 2
      2. Tier 0 eligibility (enough high-confidence beliefs, short query)
      3. Tier 1 fallback (retrievable content but not Tier 0 eligible)
      4. Tier 2 last-resort
    """
    # 1. Hard overrides
    if source in _TIER2_SOURCES:
        return 2, f"source_override({source})"
    if features.get("contradiction_present"):
        return 2, "contradiction_present"
    if features.get("query_marker"):
        return 2, f"synthesis_marker({features['query_marker']})"

    # 2. Tier 0 eligibility
    #    tfidf_top_score threshold tuned down from 0.40 → 0.15 after Task 3
    #    historical-data sweep: at 0.40 only 13.9% of queries reached Tier 0
    #    because corpus-size-diluted cosine scores rarely exceed 0.4 even for
    #    real matches. 0.15 puts ~57% into Tier 0, hitting the 50-70% target.
    if (features["n_beliefs"] >= 2
            and features["mean_confidence"] >= 0.75
            and features["tfidf_top_score"] >= 0.15
            and features["query_length_words"] <= 20):
        return 0, "tier0_eligible"

    # 3. Tier 1 default for retrievable-but-not-tier0
    if features["n_beliefs"] >= 1 and features["mean_confidence"] >= 0.5:
        return 1, "tier1_retrievable"

    # 4. Last resort
    return 2, "tier2_fallback_no_retrieval"


# ── Router entry ────────────────────────────────────────────────────────

def route(ri: RouteInput) -> RouteDecision:
    features = extract_features(ri)
    tier, reason = decide(features, ri.source)
    if tier == 0:
        # Lazy import to keep router standalone-testable
        from nex_tier0_composer import compose_tier0
        composed = compose_tier0(ri.beliefs, ri.query, ri.intent)
        return RouteDecision(
            tier=0, reason=reason, score_dict=features,
            composed_text=composed,
        )
    if tier == 1:
        return RouteDecision(
            tier=1, reason=reason, score_dict=features,
            llm_config={"max_tokens": 150, "temperature": 0.2},
        )
    return RouteDecision(
        tier=2, reason=reason, score_dict=features,
        llm_config={"max_tokens": 350, "temperature": 0.3},
    )


# ── Instrumentation ──────────────────────────────────────────────────────

def _connect(timeout: int = 60) -> sqlite3.Connection:
    conn = sqlite3.connect(str(EXPERIMENTS_DB), timeout=timeout)
    conn.execute("PRAGMA busy_timeout=300000")
    return conn


def ensure_table() -> None:
    conn = _connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS route_decisions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT NOT NULL,
                query           TEXT NOT NULL,
                query_clean     TEXT,
                intent          TEXT,
                source          TEXT,
                tier            INTEGER NOT NULL,
                reason          TEXT NOT NULL,
                features_json   TEXT NOT NULL,
                response_text   TEXT,
                latency_ms      INTEGER
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_route_tier ON route_decisions(tier, timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_route_source ON route_decisions(source, timestamp)")
        conn.commit()
    finally:
        conn.close()


def log_decision(ri: RouteInput, decision: RouteDecision,
                 response: str, latency_ms: int) -> None:
    """Safe — never raises. Instrumentation must not crash the reply path."""
    try:
        ensure_table()
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO route_decisions "
                "(timestamp, query, query_clean, intent, source, tier, reason, "
                "features_json, response_text, latency_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(),
                    (ri.query or "")[:4000],
                    (ri.query or "").strip()[:2000],
                    ri.intent or "general",
                    ri.source or "live",
                    decision.tier,
                    decision.reason,
                    json.dumps(decision.score_dict, default=str),
                    (response or "")[:4000],
                    int(latency_ms or 0),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


# ── Self-test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Quick smoke test with synthetic beliefs
    hits = [
        BeliefHit("Beliefs shape identity over time.", confidence=0.85, tfidf_score=0.6, topic="self"),
        BeliefHit("Truth is correspondence with reality.", confidence=0.8, tfidf_score=0.5, topic="philosophy"),
    ]
    cases = [
        ("What do you think?", "general", "live"),
        ("Why do beliefs change?", "general", "live"),
        ("What is the position from which you observe yourself?", "general", "live"),
        ("Tell me about beliefs.", "factual", "live"),
        ("What is it like to be you reflecting on being you?", "general", "probe"),
        ("What do you think?", "general", "fountain"),
    ]
    for q, intent, src in cases:
        ri = RouteInput(query=q, beliefs=hits, intent=intent, source=src)
        d = route(ri)
        print(f"  [tier {d.tier}] reason={d.reason!r:45s}  q={q[:50]!r}")
    print("\nself-test complete.")
