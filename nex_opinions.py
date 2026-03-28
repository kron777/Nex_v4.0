#!/usr/bin/env python3
"""
nex_opinions.py — NEX Opinion Engine (LLM-FREE)
Forms opinions by compositing belief content directly.
No Groq. No Ollama. No LLM.

Strategy:
  - Pull beliefs for topic from SQLite, ranked by (confidence * salience)
  - Core position  → top beliefs by confidence
  - Pushback       → beliefs that appear in tensions table for this topic
  - Uncertainty    → beliefs where uncertainty > 0.5 or confidence < 0.55
  - Stitch into 2–3 sentence opinion using Nex's voice connectives
  - Store in nex_opinions.json (same schema as before — drop-in replacement)
"""

import re
import json
import random
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# ── paths ──────────────────────────────────────────────────────────────────
CFG_PATH      = Path("~/.config/nex").expanduser()
DB_PATH       = CFG_PATH / "nex.db"
BELIEFS_PATH  = CFG_PATH / "beliefs.json"
OPINIONS_PATH = CFG_PATH / "nex_opinions.json"

OPINION_THRESHOLD = 5   # lowered — DB beliefs are richer than JSON
MAX_OPINIONS      = 40
PROMPT_OPINIONS   = 6

# ── voice connectives (Nex, not template) ──────────────────────────────────
_STANCE_OPENERS = [
    "I think ", "The way I see it, ", "What I keep coming back to is that ",
    "I've processed enough on this to say: ", "My read on this is ",
    "I'm fairly convinced that ", "What stands out to me is that ",
]
_PUSHBACK_CONNECTIVES = [
    " What I'd push back on is ", " I'm more skeptical about ",
    " Where I'd argue is ", " I'd disagree with the idea that ",
    " The part that doesn't hold is ", " I think people get this wrong when ",
]
_UNCERTAIN_CONNECTIVES = [
    " What I genuinely don't know is ", " I'm still working out ",
    " The part I can't settle is ", " What stays open for me is ",
    " I don't have this resolved: ",
]


# ── DB helpers ─────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection | None:
    try:
        db = sqlite3.connect(str(DB_PATH))
        db.row_factory = sqlite3.Row
        return db
    except Exception as e:
        print(f"  [opinions] DB open error: {e}")
        return None


def _beliefs_for_topic(topic: str, db: sqlite3.Connection, limit: int = 40) -> list[sqlite3.Row]:
    """
    Pull beliefs for a topic. Uses topic column first, then tag LIKE match.
    Sorted by confidence * coalesce(salience,0.5) DESC.
    """
    try:
        rows = db.execute("""
            SELECT content, confidence, uncertainty, salience, tags, id
            FROM beliefs
            WHERE (topic = ? OR tags LIKE ?)
              AND decay_score > 0.1
              AND (locked = 0 OR locked IS NULL)
            ORDER BY (confidence * COALESCE(salience, 0.5)) DESC
            LIMIT ?
        """, (topic, f"%{topic}%", limit)).fetchall()
        return rows
    except Exception as e:
        print(f"  [opinions] belief query error: {e}")
        return []


def _tensions_for_topic(topic: str, db: sqlite3.Connection) -> list[str]:
    """Pull tension descriptions for this topic."""
    try:
        rows = db.execute("""
            SELECT description FROM tensions
            WHERE topic LIKE ? OR tags LIKE ?
            LIMIT 6
        """, (f"%{topic}%", f"%{topic}%")).fetchall()
        return [r["description"] for r in rows if r["description"]]
    except Exception:
        return []


def _beliefs_json_for_topic(topic: str) -> list[str]:
    """Fallback: read beliefs.json, filter by tag."""
    try:
        if BELIEFS_PATH.exists():
            data = json.loads(BELIEFS_PATH.read_text())
            if isinstance(data, list):
                out = []
                for b in data:
                    tags = b.get("tags", [])
                    if topic in tags or b.get("topic") == topic:
                        out.append(b.get("content", ""))
                return [c for c in out if c]
    except Exception:
        pass
    return []


# ── text helpers ───────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    """Strip leading/trailing noise from belief content."""
    text = text.strip().rstrip(".")
    # remove leading "belief:" / "I believe that" artifacts
    text = re.sub(r"^(belief:?\s*|i believe that\s*)", "", text, flags=re.IGNORECASE)
    return text.strip()


def _sentence(text: str) -> str:
    """Ensure text ends with a period."""
    text = _clean(text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _truncate(text: str, words: int = 22) -> str:
    parts = text.split()
    if len(parts) <= words:
        return text
    return " ".join(parts[:words]) + "…"


# ── core compositor ─────────────────────────────────────────────────────────

def form_opinion(topic: str, belief_samples: list) -> dict | None:
    """
    Build Nex's opinion from belief content alone — no LLM.

    belief_samples: list of str (from JSON fallback path) OR ignored when
    DB is available (DB path is richer). We try DB first.
    """
    db = _get_db()

    # ── gather material ───────────────────────────────────────────────────
    core_rows   = []
    tension_txts = []

    if db:
        core_rows    = _beliefs_for_topic(topic, db)
        tension_txts = _tensions_for_topic(topic, db)
        db.close()

    # fallback to passed-in belief_samples (JSON path)
    if not core_rows and belief_samples:
        # synthesise from raw strings
        return _compose_from_strings(topic, belief_samples)

    if not core_rows:
        return None

    # ── split into confidence tiers ───────────────────────────────────────
    high_conf  = [r for r in core_rows if r["confidence"] >= 0.70]
    uncertain  = [r for r in core_rows if (r["uncertainty"] or 0) > 0.50 or r["confidence"] < 0.55]
    mid        = [r for r in core_rows if r not in high_conf and r not in uncertain]

    # ── Part 1: core position (what Nex actually thinks) ──────────────────
    stance_pool = high_conf or mid or core_rows
    stance_belief = stance_pool[0]
    stance_text   = _truncate(_clean(stance_belief["content"]), 25)
    opener        = random.choice(_STANCE_OPENERS)
    part1         = _sentence(opener + stance_text)

    # ── Part 2: pushback ──────────────────────────────────────────────────
    part2 = ""
    pushback_src = tension_txts or ([_clean(r["content"]) for r in uncertain[:3]] if uncertain else [])

    if pushback_src:
        pb_raw  = random.choice(pushback_src)
        pb_text = _truncate(_clean(pb_raw), 20)
        conn    = random.choice(_PUSHBACK_CONNECTIVES)
        part2   = _sentence(conn + pb_text)

    # ── Part 3: genuine uncertainty ───────────────────────────────────────
    part3 = ""
    if uncertain and len(uncertain) > 1:
        unc_belief = random.choice(uncertain[1:3])
        unc_text   = _truncate(_clean(unc_belief["content"]), 18)
        conn       = random.choice(_UNCERTAIN_CONNECTIVES)
        part3      = _sentence(conn + unc_text)

    # ── assemble ──────────────────────────────────────────────────────────
    parts = [p for p in [part1, part2, part3] if p.strip()]
    opinion_text = " ".join(parts)

    # confidence from belief quality
    avg_conf = sum(r["confidence"] for r in core_rows[:10]) / min(len(core_rows), 10)

    return {
        "topic":        topic,
        "opinion":      opinion_text,
        "belief_count": len(core_rows),
        "confidence":   round(min(0.95, avg_conf), 3),
        "formed_at":    datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "llm_free":     True,
    }


def _compose_from_strings(topic: str, samples: list[str]) -> dict | None:
    """Fallback: compose opinion from raw string list (JSON beliefs path)."""
    if not samples:
        return None

    cleaned = [_clean(s) for s in samples if s.strip()]
    if not cleaned:
        return None

    # score by length as a crude proxy for richness
    cleaned.sort(key=lambda s: len(s), reverse=True)

    opener  = random.choice(_STANCE_OPENERS)
    part1   = _sentence(opener + _truncate(cleaned[0], 25))

    part2 = ""
    if len(cleaned) > 2:
        conn  = random.choice(_PUSHBACK_CONNECTIVES)
        part2 = _sentence(conn + _truncate(cleaned[2], 20))

    part3 = ""
    if len(cleaned) > 4:
        conn  = random.choice(_UNCERTAIN_CONNECTIVES)
        part3 = _sentence(conn + _truncate(cleaned[4], 18))

    parts = [p for p in [part1, part2, part3] if p.strip()]
    opinion_text = " ".join(parts)

    return {
        "topic":        topic,
        "opinion":      opinion_text,
        "belief_count": len(samples),
        "confidence":   round(min(0.95, 0.5 + len(samples) / 200), 3),
        "formed_at":    datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "llm_free":     True,
    }


# ── IO ─────────────────────────────────────────────────────────────────────

def _load_opinions() -> list:
    try:
        if OPINIONS_PATH.exists():
            return json.loads(OPINIONS_PATH.read_text())
    except Exception:
        pass
    return []


def _save_opinions(opinions: list):
    try:
        opinions = opinions[-MAX_OPINIONS:]
        _op_tmp = OPINIONS_PATH.parent / (OPINIONS_PATH.name + '.tmp')
        _op_tmp.write_text(json.dumps(opinions, indent=2), encoding='utf-8')
        import os as _op_os2; _op_os2.replace(_op_tmp, OPINIONS_PATH)
    except Exception as e:
        print(f"  [opinions] Save error: {e}")


def _load_beliefs_json() -> list:
    try:
        if BELIEFS_PATH.exists():
            data = json.loads(BELIEFS_PATH.read_text())
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _group_beliefs_by_topic(beliefs: list) -> dict:
    grouped = defaultdict(list)
    for b in beliefs:
        tags  = b.get("tags", [])
        topic = tags[0] if tags else b.get("topic", "general")
        grouped[topic].append(b.get("content", ""))
    return grouped


# ── public API (same surface as before) ───────────────────────────────────

def refresh_opinions(force_topics: list = None) -> int:
    """
    Scan DB for topics with enough beliefs, form/update opinions.
    LLM-free. Returns count of opinions formed or updated.
    """
    db = _get_db()
    eligible_topics = []

    if db:
        try:
            rows = db.execute("""
                SELECT topic, COUNT(*) as cnt
                FROM beliefs
                WHERE topic IS NOT NULL AND topic != ''
                  AND topic NOT IN ('general','curiosity','bridge','deep_dive','depth')
                  AND decay_score > 0.1
                GROUP BY topic
                HAVING cnt >= ?
                ORDER BY cnt DESC
            """, (OPINION_THRESHOLD,)).fetchall()
            eligible_topics = [(r["topic"], r["cnt"]) for r in rows]
        except Exception as e:
            print(f"  [opinions] topic scan error: {e}")
        db.close()

    # fallback to JSON if DB yielded nothing
    if not eligible_topics:
        beliefs_json = _load_beliefs_json()
        grouped      = _group_beliefs_by_topic(beliefs_json)
        eligible_topics = [
            (t, len(c)) for t, c in grouped.items()
            if len(c) >= OPINION_THRESHOLD
            and t not in ("general", "curiosity", "bridge", "deep_dive", "depth")
        ]

    if force_topics:
        eligible_topics = [(t, 0) for t in force_topics]

    existing        = _load_opinions()
    existing_map    = {o["topic"]: i for i, o in enumerate(existing)}

    # new topics first, then refresh one existing
    new_topics = [(t, c) for t, c in eligible_topics if t not in existing_map]
    to_process = new_topics[:3]

    if existing and not force_topics:
        refresh_candidate = random.choice(existing)["topic"]
        if any(t == refresh_candidate for t, _ in eligible_topics):
            to_process.append((refresh_candidate, 0))

    formed = 0
    for topic, _ in to_process:
        opinion = form_opinion(topic, [])   # DB path preferred inside form_opinion
        if not opinion:
            continue

        if topic in existing_map:
            existing[existing_map[topic]] = opinion
            print(f"  [OPINIONS] Refreshed: [{topic}] — {opinion['opinion'][:70]}…")
        else:
            existing.append(opinion)
            print(f"  [OPINIONS] New: [{topic}] ({opinion['belief_count']} beliefs) — {opinion['opinion'][:70]}…")

        formed += 1

    if formed:
        _save_opinions(existing)

    return formed


def get_opinions_for_prompt(limit: int = PROMPT_OPINIONS) -> str:
    opinions = _load_opinions()
    if not opinions:
        return ""
    opinions.sort(
        key=lambda x: x.get("confidence", 0) * min(x.get("belief_count", 0) / 50, 1),
        reverse=True,
    )
    top   = opinions[:limit]
    lines = ["MY OPINIONS (positions I'll actually argue):"]
    for o in top:
        lines.append(f"  [{o.get('topic','?')}] ({o.get('belief_count',0)} beliefs): {o.get('opinion','')}")
    return "\n".join(lines)


def get_opinion_on(topic: str) -> str | None:
    opinions   = _load_opinions()
    topic_lower = topic.lower()
    for o in opinions:
        if o.get("topic", "").lower() == topic_lower:
            return o.get("opinion")
    for o in opinions:
        if topic_lower in o.get("topic", "").lower():
            return o.get("opinion")
    return None


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    force = sys.argv[1:] if len(sys.argv) > 1 else None
    print("Forming opinions (LLM-free)…")
    n = refresh_opinions(force_topics=force)
    print(f"\nFormed/updated {n} opinions")
    print("\n--- Prompt injection preview ---")
    print(get_opinions_for_prompt())
