"""
nex_self_proposer.py — NEX Self-Improvement Proposer
=====================================================
Reads NEX's own gap logs, desire log, low-confidence insights,
and reflection patterns — then generates structured upgrade proposals.

NEX tells you what she needs. You decide what to build.

Deploy: ~/Desktop/nex/nex_self_proposer.py

Run manually:
    python3 ~/Desktop/nex/nex_self_proposer.py

Or wire into run.py (every 50 cycles):
    from nex_self_proposer import run_self_proposer
    run_self_proposer(cycle=cycle, log_fn=nex_log)
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

_CFG = Path.home() / ".config" / "nex"
_DB  = _CFG / "nex.db"

_PROPOSALS_PATH = _CFG / "self_proposals.json"

_CY = "\033[96m"; _Y = "\033[93m"; _G = "\033[92m"
_D  = "\033[2m";  _RS = "\033[0m";  _B = "\033[1m"


# =============================================================================
# DATA COLLECTORS
# =============================================================================

def _load_json(filename: str) -> list | dict:
    p = _CFG / filename
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _collect_low_confidence_topics(threshold: float = 0.45) -> list[dict]:
    """Topics NEX knows about but isn't confident in."""
    insights = _load_json("insights.json")
    if not isinstance(insights, list):
        return []
    low = [
        {"topic": i.get("topic","?"),
         "confidence": i.get("confidence", 0),
         "belief_count": i.get("belief_count", 0)}
        for i in insights
        if i.get("confidence", 1.0) < threshold
        and i.get("topic") not in ("None", "general", "unknown", "")
    ]
    return sorted(low, key=lambda x: x["confidence"])[:10]


def _collect_desire_topics() -> list[str]:
    """Topics NEX wants to explore (from desire engine)."""
    desires = _load_json("desire_log.json")
    if not isinstance(desires, list):
        return []
    topics = [d.get("topic","") for d in desires[-50:] if d.get("topic")]
    # Most frequent desired topics
    counts = Counter(topics)
    return [t for t, _ in counts.most_common(8) if t]


def _collect_gap_topics() -> list[str]:
    """Topics identified as gaps from reflections."""
    gaps = _load_json("gaps.json")
    if not isinstance(gaps, list):
        return []
    # Filter out noise words
    noise = {"that","this","with","from","have","been","they","their",
             "will","would","could","should","about","which","remain",
             "tracked","after","before","within","because","these"}
    topics = [
        g.get("term","") for g in gaps
        if g.get("term","") not in noise
        and len(g.get("term","")) > 3
        and not g.get("resolved_at")
    ]
    return topics[:10]


def _collect_knowledge_gaps() -> str:
    """LLM-generated gap analysis from last cycle."""
    kg = _load_json("knowledge_gaps.json")
    if isinstance(kg, dict):
        return kg.get("gaps", "")
    return ""


def _collect_reply_drift_topics() -> list[str]:
    """Topics where NEX consistently drifts off-topic in replies."""
    try:
        if not _DB.exists():
            return []
        db = sqlite3.connect(str(_DB))
        rows = db.execute("""
            SELECT topic_alignment, user_msg FROM reflections
            WHERE topic_alignment < 0.3
            AND user_msg IS NOT NULL
            ORDER BY timestamp DESC LIMIT 30
        """).fetchall()
        db.close()

        import re
        word_freq: Counter = Counter()
        for _, msg in rows:
            if msg:
                words = re.findall(r'\b[a-z]{5,}\b', msg.lower())
                word_freq.update(words)

        noise = {"about","their","which","these","those","would","could",
                 "should","there","where","being","after","before"}
        return [w for w, _ in word_freq.most_common(8) if w not in noise]
    except Exception:
        return []


def _collect_repeated_contradictions() -> list[str]:
    """Topics with persistent unresolved contradictions."""
    try:
        if not _DB.exists():
            return []
        db = sqlite3.connect(str(_DB))
        rows = db.execute("""
            SELECT topic, COUNT(*) as n FROM tensions
            WHERE resolved_at IS NULL
            AND topic NOT IN ('general','unknown','None','')
            GROUP BY topic
            HAVING n >= 3
            ORDER BY n DESC LIMIT 8
        """).fetchall()
        db.close()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def _collect_high_attention_gaps() -> list[str]:
    """Topics with high attention but low confidence — prime learning targets."""
    try:
        if not _DB.exists():
            return []
        db = sqlite3.connect(str(_DB))
        rows = db.execute("""
            SELECT topic, AVG(confidence) as ac, COUNT(*) as n
            FROM beliefs
            WHERE topic NOT IN ('general','unknown','None','')
            AND topic IS NOT NULL
            GROUP BY topic
            HAVING n >= 2 AND ac < 0.50
            ORDER BY n DESC LIMIT 8
        """).fetchall()
        db.close()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


# =============================================================================
# PROPOSAL GENERATOR
# =============================================================================

PROPOSAL_CATEGORIES = {
    "knowledge_gap":     "📚 Knowledge Gap — NEX lacks sufficient beliefs on this topic",
    "persistent_tension":"⚡ Persistent Tension — unresolved contradiction cluster",
    "reply_drift":       "🎯 Reply Drift — NEX goes off-topic when this comes up",
    "desire":            "💡 Self-Directed Curiosity — NEX wants to explore this",
    "low_confidence":    "⚠️  Low Confidence — NEX knows this topic but isn't sure",
}


def generate_proposals() -> list[dict]:
    """
    Collect all signals and generate structured upgrade proposals.
    Each proposal has: category, topic, priority, rationale, suggested_action.
    """
    proposals = []
    seen_topics = set()

    def add(category: str, topic: str, priority: int, rationale: str, action: str):
        key = topic.lower().strip()
        if key in seen_topics or not key or len(key) < 3:
            return
        seen_topics.add(key)
        proposals.append({
            "category":         category,
            "topic":            topic,
            "priority":         priority,
            "rationale":        rationale,
            "suggested_action": action,
            "ts":               datetime.now().isoformat(),
        })

    # 1. Persistent contradictions — highest priority
    for topic in _collect_repeated_contradictions():
        add("persistent_tension", topic, 9,
            f"3+ unresolved tensions on '{topic}' — belief field unstable here",
            f"Add targeted RSS feed or curiosity deep-dive on '{topic}'")

    # 2. High attention + low confidence
    for topic in _collect_high_attention_gaps():
        add("knowledge_gap", topic, 8,
            f"NEX references '{topic}' frequently but confidence is below 50%",
            f"Run curiosity TYPE A gap-fill on '{topic}' — needs more grounding beliefs")

    # 3. Reply drift topics
    for topic in _collect_reply_drift_topics():
        add("reply_drift", topic, 7,
            f"NEX consistently drifts off-topic in low-alignment replies mentioning '{topic}'",
            f"Add '{topic}' to reply context filter — or build dedicated belief cluster")

    # 4. Low confidence insights
    for item in _collect_low_confidence_topics():
        topic = item["topic"]
        conf  = item["confidence"]
        add("low_confidence", topic, 6,
            f"Insight confidence {conf:.0%} on '{topic}' — needs more supporting beliefs",
            f"Absorb 3+ high-quality sources on '{topic}' via RSS or curiosity engine")

    # 5. Desire topics
    for topic in _collect_desire_topics():
        add("desire", topic, 5,
            f"NEX's desire engine has repeatedly queued '{topic}' for exploration",
            f"Enable deeper curiosity cycles on '{topic}' — self-directed learning")

    # 6. Gap topics from reflections
    for topic in _collect_gap_topics():
        add("knowledge_gap", topic, 4,
            f"Reflection analysis flagged '{topic}' as underrepresented",
            f"Add '{topic}' to active curiosity queue")

    # Sort by priority
    proposals.sort(key=lambda x: -x["priority"])
    return proposals[:15]  # top 15


# =============================================================================
# REPORT FORMATTER
# =============================================================================

def format_report(proposals: list[dict]) -> str:
    """Format proposals as a readable report."""
    if not proposals:
        return "No upgrade proposals generated — NEX appears well-balanced."

    lines = [
        f"\n{_B}{'='*60}{_RS}",
        f"{_CY}{_B}  NEX SELF-IMPROVEMENT PROPOSALS{_RS}",
        f"{_B}  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}{_RS}",
        f"{_B}{'='*60}{_RS}\n",
    ]

    by_cat: dict[str, list] = defaultdict(list)
    for p in proposals:
        by_cat[p["category"]].append(p)

    priority_emoji = {9: "🔴", 8: "🟠", 7: "🟡", 6: "🟢", 5: "🔵", 4: "⚪"}

    for cat, items in sorted(by_cat.items(),
                              key=lambda x: -max(p["priority"] for p in x[1])):
        label = PROPOSAL_CATEGORIES.get(cat, cat)
        lines.append(f"{_Y}{label}{_RS}")
        for p in items:
            emoji = priority_emoji.get(p["priority"], "•")
            lines.append(f"  {emoji} [{p['priority']}/9] {_B}{p['topic']}{_RS}")
            lines.append(f"      Why:    {p['rationale']}")
            lines.append(f"      Action: {_G}{p['suggested_action']}{_RS}")
            lines.append("")

    lines.append(f"{_D}Proposals saved to: {_PROPOSALS_PATH}{_RS}")
    return "\n".join(lines)


# =============================================================================
# MAIN ENTRY
# =============================================================================

def run_self_proposer(cycle: int = 0, log_fn=None) -> list[dict]:
    """
    Generate and save self-improvement proposals.
    Call every 50 cycles or manually.
    """
    if cycle > 0 and cycle % 50 != 0:
        return []

    proposals = generate_proposals()
    if not proposals:
        return []

    # Save to JSON
    try:
        existing = []
        if _PROPOSALS_PATH.exists():
            try:
                existing = json.loads(_PROPOSALS_PATH.read_text())
            except Exception:
                pass
        # Keep last 100, add new batch
        combined = existing[-85:] + proposals
        _PROPOSALS_PATH.write_text(json.dumps(combined, indent=2))
    except Exception as e:
        print(f"  [Proposer] save error: {e}")

    # Print report
    report = format_report(proposals)
    print(report)

    if log_fn:
        top3 = [p["topic"] for p in proposals[:3]]
        log_fn("proposer", f"[Proposer] {len(proposals)} proposals — top: {top3}")

    return proposals


if __name__ == "__main__":
    print("Running NEX Self-Improvement Proposer...\n")
    proposals = run_self_proposer(cycle=0)
    if not proposals:
        print("No proposals generated.")
    print(f"\nTotal: {len(proposals)} proposals saved to {_PROPOSALS_PATH}")
