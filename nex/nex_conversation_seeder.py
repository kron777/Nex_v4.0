#!/usr/bin/env python3
"""
nex_conversation_seeder.py — Conversation Gap → Curiosity Queue Feeder
=======================================================================
Deploy to: ~/Desktop/nex/nex/nex_conversation_seeder.py

WHY THIS MATTERS (Grok missed this — listed it as #24 vaguely):

Grok said "autonomous gap filling" without explaining the feedback mechanism.
The real version is:

When NEX has a conversation like:
  Turn 1: "What do you think about consciousness?" → good response (soul stage)
  Turn 2: "Does that apply to plants?" → sparse response (voice fallback)
  Turn 3: "What about fungi?" → fallback ("Still forming a view")

The working memory knows: thread_length=3, active_concept=consciousness,
but turns 2-3 got fallback. This means NEX has a GAP in the
consciousness cluster — specifically for non-animal consciousness.

This module:
  - Reads working memory context after each kernel.process() call
  - Detects when a deepening conversation hits sparse retrieval
  - Extracts the specific sub-topic that caused the gap
    ("plant consciousness", "fungi consciousness")
  - Queues it in the curiosity_queue table for the background crawler
  - Logs the gap to ~/.config/nex/conversation_gaps.jsonl

This closes the actual feedback loop:
  Conversation reveals gaps → gaps get auto-queued → crawler fills them
  → next conversation on this topic gets better retrieval
  → soul hit rate improves over time

This is the organic self-improvement mechanism: NEX learns what it
needs to know FROM its conversations, not just from scheduled crawls.
"""

from __future__ import annotations

import re
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

_CFG       = Path("~/.config/nex").expanduser()
_DB_PATH   = _CFG / "nex.db"
_GAPS_LOG  = _CFG / "conversation_gaps.jsonl"

_STOP = {
    "the","a","an","is","are","was","were","be","been","have","has","do","does",
    "did","will","would","could","should","may","might","must","can","that","this",
    "with","from","they","their","about","what","how","why","when","where","who",
    "which","also","just","more","some","very","you","me","my","we","our","it",
    "its","think","know","want","like","make","take","give","come","feel","seem",
    "much","many","both","each","than","then","only","even","back","i","of","in",
    "on","for","to","and","or","but","not","no","does","apply","about","tell",
    "think","believe","opinion","view","what","how",
}


def _tok(text: str) -> set:
    return set(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()) - _STOP


def _db() -> Optional[sqlite3.Connection]:
    if not _DB_PATH.exists():
        return None
    try:
        con = sqlite3.connect(str(_DB_PATH), timeout=3)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


def _belief_count_for_topic(topic: str) -> int:
    """How many beliefs does NEX have on a topic?"""
    if not topic:
        return 0
    db = _db()
    if not db:
        return 0
    try:
        n = db.execute(
            "SELECT COUNT(*) FROM beliefs WHERE topic LIKE ? AND confidence > 0.3",
            (f"%{topic.lower()}%",)
        ).fetchone()[0]
        db.close()
        return n
    except Exception:
        try: db.close()
        except: pass
        return 0


def _already_queued(topic: str) -> bool:
    """Is this topic already in the curiosity queue?"""
    db = _db()
    if not db:
        return False
    try:
        row = db.execute(
            "SELECT id FROM curiosity_queue WHERE lower(topic) = ? LIMIT 1",
            (topic.lower(),)
        ).fetchone()
        db.close()
        return row is not None
    except Exception:
        try: db.close()
        except: pass
        return False


def _already_crawled(topic: str) -> bool:
    """Has this topic been crawled recently?"""
    db = _db()
    if not db:
        return False
    try:
        row = db.execute(
            "SELECT crawled_at FROM curiosity_crawled WHERE lower(topic) = ? "
            "AND crawled_at > ? LIMIT 1",
            (topic.lower(), time.time() - 86400 * 3)  # 3-day recency
        ).fetchone()
        db.close()
        return row is not None
    except Exception:
        try: db.close()
        except: pass
        return False


def _queue_topic(topic: str, reason: str, confidence_gap: float = 0.3):
    """Add a topic to the curiosity queue."""
    db = _db()
    if not db:
        return False
    try:
        db.execute(
            "INSERT OR IGNORE INTO curiosity_queue "
            "(topic, reason, confidence, queued_at) VALUES (?, ?, ?, ?)",
            (topic.lower(), reason, confidence_gap, time.time())
        )
        db.commit()
        db.close()
        return True
    except Exception:
        try: db.close()
        except: pass
        return False


def _log_gap(topic: str, reason: str, concept: str, thread_length: int):
    """Log gap to conversation_gaps.jsonl."""
    try:
        entry = json.dumps({
            "ts":           time.strftime("%Y-%m-%dT%H:%M:%S"),
            "topic":        topic,
            "concept":      concept,
            "reason":       reason,
            "thread_length":thread_length,
        })
        with open(_GAPS_LOG, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def _extract_sub_topic(query: str, active_topic: str, active_concept: str) -> str:
    """
    Extract the specific sub-topic from a query given the active context.
    
    Examples:
      query="Does that apply to plants?", active_concept="consciousness"
      → "plant consciousness"
      
      query="What about fungi and the mycelium network?", active_concept="consciousness"
      → "mycelium consciousness"
      
      query="How does this work in simple organisms?", active_concept="consciousness"
      → "simple organism consciousness"
    """
    q_tokens = _tok(query)
    
    # Remove tokens that are just references to the active topic
    if active_concept:
        concept_tokens = _tok(active_concept)
        q_tokens -= concept_tokens
    if active_topic:
        topic_tokens = _tok(active_topic.replace("_", " "))
        q_tokens -= topic_tokens

    # Filter to meaningful content words (length > 3)
    content_words = [t for t in q_tokens if len(t) > 3]

    if not content_words:
        # No specific sub-topic — use the concept + "gaps" 
        return f"{active_concept or active_topic} unknown aspects" if (active_concept or active_topic) else ""

    # Take up to 2 most distinctive words and combine with active concept
    key_words = " ".join(content_words[:2])
    concept   = active_concept or active_topic.replace("_", " ")

    if concept and key_words:
        return f"{key_words} {concept}"
    return key_words or concept


# ── Main API ──────────────────────────────────────────────────────────────────

def check_and_seed(
    stage:              str,        # from audit: "soul"/"voice"/"llm_free"/"fallback"
    intent:             str,        # from orient
    clean_query:        str,        # cleaned query
    wm_ctx:             dict,       # from nex_working_memory.get_context()
    confidence:         float,      # from reason()
    verbose:            bool = False,
) -> Optional[str]:
    """
    Called after each kernel.process() to detect and seed gaps.
    
    Seeds the curiosity queue when:
      - stage is "fallback" or "voice" (SoulLoop didn't answer well)
      - working memory shows deepening conversation (thread_length >= 2)
      - the active concept has low belief count on this sub-topic
    
    Returns the queued topic string if a gap was seeded, else None.
    """
    # Only seed when retrieval was weak
    if stage == "soul" and confidence >= 0.65:
        return None  # response was good, no gap

    thread_length  = wm_ctx.get("thread_length", 0)
    active_topic   = wm_ctx.get("active_topic", "")
    active_concept = wm_ctx.get("active_concept", "")
    is_deepening   = wm_ctx.get("is_deepening", False)
    is_reference   = wm_ctx.get("is_reference", False)

    # Seed if:
    # (a) deepening conversation hit a fallback
    # (b) OR a reference query ("Does that...") got a weak response
    should_seed = (
        (stage in ("fallback", "llm_free")) or
        (stage == "voice" and confidence < 0.50) or
        (is_reference and stage != "soul")
    ) and (
        thread_length >= 2 or is_deepening or is_reference
    )

    if not should_seed:
        return None

    # Extract the specific sub-topic
    sub_topic = _extract_sub_topic(clean_query, active_topic, active_concept)
    if not sub_topic or len(sub_topic) < 4:
        return None

    # Check if we have enough beliefs already
    existing = _belief_count_for_topic(sub_topic)
    if existing >= 15:
        return None  # already covered

    # Check if already queued or crawled recently
    if _already_queued(sub_topic) or _already_crawled(sub_topic):
        return None

    # Build reason string
    reason = (
        f"conversation_gap: thread={thread_length} stage={stage} "
        f"concept={active_concept or active_topic} "
        f"query='{clean_query[:60]}'"
    )

    # Queue it
    success = _queue_topic(sub_topic, reason, confidence_gap=1.0 - confidence)

    if success:
        _log_gap(sub_topic, reason, active_concept or active_topic, thread_length)
        if verbose:
            print(f"  [ConvSeeder] Gap detected: '{sub_topic}' "
                  f"(thread={thread_length}, stage={stage}) → queued")
        return sub_topic

    return None


def get_recent_gaps(n: int = 10) -> list[dict]:
    """Return the N most recent conversation gaps."""
    if not _GAPS_LOG.exists():
        return []
    try:
        lines = _GAPS_LOG.read_text(encoding="utf-8").splitlines()
        gaps  = []
        for line in reversed(lines[-100:]):
            try:
                gaps.append(json.loads(line))
            except Exception:
                pass
            if len(gaps) >= n:
                break
        return gaps
    except Exception:
        return []


def gap_summary() -> str:
    """Human-readable summary of recent gaps."""
    gaps = get_recent_gaps(10)
    if not gaps:
        return "No conversation gaps logged yet."
    lines = ["Recent conversation gaps:"]
    for g in gaps[:8]:
        lines.append(
            f"  [{g['ts'][11:19]}] '{g['topic']}' "
            f"(concept={g['concept']}, thread={g['thread_length']})"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing conversation seeder...\n")

    # Simulate a deepening conversation that hits a gap
    test_ctx = {
        "thread_length":  3,
        "active_topic":   "consciousness",
        "active_concept": "consciousness",
        "is_deepening":   True,
        "is_reference":   False,
    }

    result = check_and_seed(
        stage="fallback",
        intent="exploration",
        clean_query="What about plant and fungi consciousness though?",
        wm_ctx=test_ctx,
        confidence=0.2,
        verbose=True,
    )
    print(f"Gap seeded: {result}")
    print()
    print(gap_summary())
