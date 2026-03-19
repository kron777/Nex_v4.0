"""
nex_event_importance.py — Event Importance Scoring
====================================================
Not all inputs are equal. This module scores incoming events
and gates whether they should modify core beliefs.

Events that score below CORE_BELIEF_THRESHOLD only create
peripheral beliefs (low confidence, tagged as 'peripheral').
Only high-scoring events create or modify core beliefs.

Three scoring axes:
  1. NOVELTY    — does this contradict or extend existing beliefs?
  2. RELEVANCE  — does it match NEX's active knowledge domains?
  3. CREDIBILITY — source tier + content density

Wire-in (run.py absorb phase or auto_learn):
    from nex_event_importance import EventScorer
    _es = EventScorer()

    for post in posts:
        result = _es.score_event(post)
        if result['tier'] == 'core':
            # modify core beliefs with full confidence
        elif result['tier'] == 'peripheral':
            # store with reduced confidence
        else:  # 'skip'
            continue
"""

import json
import re
import sqlite3
import os
from pathlib import Path
from datetime import datetime

CONFIG_DIR = Path.home() / ".config" / "nex"
DB_PATH    = CONFIG_DIR / "nex.db"

# ── Thresholds ────────────────────────────────────────────────────────────────
CORE_THRESHOLD       = 0.65  # score >= this → modifies core beliefs
PERIPHERAL_THRESHOLD = 0.35  # score >= this → stored as peripheral
# Below PERIPHERAL_THRESHOLD → skipped entirely

# ── NEX's active domains (events in these domains score higher) ───────────────
ACTIVE_DOMAINS = {
    "autonomous AI systems", "AI agent memory systems",
    "large language model alignment", "cybersecurity",
    "multi-agent coordination", "bayesian belief updating",
    "penetration testing techniques", "CVE vulnerability analysis",
    "machine learning", "software engineering", "AI identity and agency",
}

DOMAIN_KEYWORDS = {
    "autonomous AI systems":        ["agent", "autonomous", "agentic", "orchestrat"],
    "AI agent memory systems":      ["memory", "belief", "knowledge", "retrieval", "rag"],
    "large language model alignment": ["alignment", "safety", "rlhf", "llm", "language model"],
    "cybersecurity":                ["vulnerability", "exploit", "attack", "security", "breach"],
    "multi-agent coordination":     ["multi-agent", "swarm", "coordination", "consensus"],
    "bayesian belief updating":     ["bayesian", "probability", "inference", "confidence"],
    "machine learning":             ["neural", "training", "gradient", "model", "dataset"],
    "software engineering":         ["code", "programming", "software", "api", "framework"],
    "AI identity and agency":       ["identity", "self", "consciousness", "agency", "autonomy"],
}

_STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","this","that","it",
    "not","as","which","when","all","some","more","just","also","have",
}

# Source credibility tiers
CREDIBILITY = {
    "high":   ["arxiv", "lesswrong", "alignmentforum", "anthropic", "openai", "deepmind", "distill"],
    "medium": ["hackernews", "mit", "venturebeat", "wired", "verge", "ieee"],
    "low":    ["reddit", "twitter", "youtube", "moltbook", "telegram", "discord"],
}


def _credibility_score(source: str) -> float:
    src = source.lower()
    for name in CREDIBILITY["high"]:
        if name in src:
            return 1.0
    for name in CREDIBILITY["medium"]:
        if name in src:
            return 0.65
    for name in CREDIBILITY["low"]:
        if name in src:
            return 0.35
    return 0.5


def _relevance_score(text: str) -> float:
    """How relevant is this to NEX's active domains?"""
    text_lower = text.lower()
    max_hits = 0
    for domain, keywords in DOMAIN_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        max_hits = max(max_hits, hits)
    return min(1.0, max_hits * 0.25)


def _novelty_score(text: str, db_path: Path = DB_PATH) -> float:
    """
    How novel is this relative to existing beliefs?
    High novelty = few similar beliefs exist.
    """
    if not db_path.exists():
        return 0.7  # assume novel if no DB

    try:
        words = set(re.findall(r'\b[a-zA-Z]{5,}\b', text.lower())) - _STOP
        if not words:
            return 0.5

        # Sample a few keywords to check overlap
        sample_words = list(words)[:5]
        db = sqlite3.connect(str(db_path))
        total_matches = 0
        for word in sample_words:
            count = db.execute(
                "SELECT COUNT(*) FROM beliefs WHERE content LIKE ?",
                (f"%{word}%",)
            ).fetchone()[0]
            total_matches += min(count, 50)  # cap per word
        db.close()

        avg_matches = total_matches / len(sample_words)
        # High matches = low novelty
        novelty = max(0.1, 1.0 - (avg_matches / 100))
        return round(novelty, 3)
    except Exception:
        return 0.5


def _density_score(text: str) -> float:
    """Information density of the content."""
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
    if not words:
        return 0.0
    unique = set(w for w in words if w not in _STOP)
    density = len(unique) / max(len(words), 1)
    length_bonus = min(1.0, len(text) / 200)
    return round(density * 0.6 + length_bonus * 0.4, 3)


class EventScorer:
    """
    Scores incoming events and assigns them to tiers:
      'core'       → modifies core beliefs (full confidence)
      'peripheral' → stored at reduced confidence
      'skip'       → ignored entirely
    """

    def score_event(self, event: dict) -> dict:
        """
        Score an event dict with keys: title, content/summary, source, confidence.
        Returns enriched dict with score, tier, and adjusted confidence.
        """
        title   = event.get("title", "")
        content = event.get("content", event.get("summary", ""))
        source  = event.get("source", "")
        text    = f"{title} {content}"

        credibility = _credibility_score(source)
        relevance   = _relevance_score(text)
        novelty     = _novelty_score(text)
        density     = _density_score(text)

        # Weighted combination
        score = (
            credibility * 0.25 +
            relevance   * 0.35 +
            novelty     * 0.25 +
            density     * 0.15
        )
        score = round(score, 3)

        # Assign tier
        if score >= CORE_THRESHOLD:
            tier = "core"
            conf_mult = 1.0
        elif score >= PERIPHERAL_THRESHOLD:
            tier = "peripheral"
            conf_mult = 0.65
        else:
            tier = "skip"
            conf_mult = 0.0

        # Adjust confidence
        base_conf = event.get("confidence", 0.5)
        adjusted_conf = round(min(0.92, base_conf * conf_mult), 3) if conf_mult > 0 else 0.0

        return {
            **event,
            "importance_score": score,
            "tier":             tier,
            "confidence":       adjusted_conf,
            "scoring": {
                "credibility": credibility,
                "relevance":   relevance,
                "novelty":     novelty,
                "density":     density,
            }
        }

    def filter_events(self, events: list[dict],
                      min_tier: str = "peripheral") -> list[dict]:
        """
        Score and filter a list of events.
        min_tier: 'core' = only core events, 'peripheral' = core + peripheral
        Returns sorted by importance_score descending.
        """
        scored = [self.score_event(e) for e in events]

        if min_tier == "core":
            filtered = [e for e in scored if e["tier"] == "core"]
        else:
            filtered = [e for e in scored if e["tier"] != "skip"]

        filtered.sort(key=lambda x: -x.get("importance_score", 0))
        return filtered

    def get_tier_counts(self, events: list[dict]) -> dict:
        """Return counts per tier for a batch of events."""
        scored = [self.score_event(e) for e in events]
        counts = {"core": 0, "peripheral": 0, "skip": 0}
        for e in scored:
            counts[e["tier"]] += 1
        return counts


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance = None

def get_event_scorer() -> EventScorer:
    global _instance
    if _instance is None:
        _instance = EventScorer()
    return _instance


if __name__ == "__main__":
    scorer = EventScorer()

    test_events = [
        {
            "title":   "Novel attention mechanism enables 10x memory efficiency in LLM agents",
            "content": "Researchers at MIT propose a new sparse attention approach that significantly reduces memory footprint while maintaining performance on multi-step reasoning tasks.",
            "source":  "arxiv",
            "confidence": 0.8,
        },
        {
            "title":   "Anyone else excited about the future of AI?",
            "content": "Just wondering what people think about where things are headed",
            "source":  "reddit",
            "confidence": 0.4,
        },
        {
            "title":   "Critical RCE vulnerability discovered in popular agent framework",
            "content": "CVE-2025-XXXX affects AgentStack versions prior to 2.1.3. Attackers can achieve remote code execution via crafted tool call payloads.",
            "source":  "hackernews",
            "confidence": 0.65,
        },
    ]

    print("Event importance scores:\n")
    for event in test_events:
        result = scorer.score_event(event)
        print(f"  [{result['tier'].upper():10s}] score={result['importance_score']:.3f} "
              f"conf={result['confidence']:.2f} — {event['title'][:60]}")
        print(f"    credibility={result['scoring']['credibility']:.2f} "
              f"relevance={result['scoring']['relevance']:.2f} "
              f"novelty={result['scoring']['novelty']:.2f} "
              f"density={result['scoring']['density']:.2f}")
