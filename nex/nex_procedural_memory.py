"""
nex_procedural_memory.py — Procedural Memory Retrieval
=======================================================
Prop D from the Throw-Net build plan.

What this does:
    Queries the existing nex_posts table for high-quality past responses
    on similar topics/intents. Returns a fragment that can be injected
    into the soul loop's reason() step to ground the current response
    in proven patterns.

Key insight:
    nex_posts already accumulates every respond() call with:
        content, query, topic, voice_mode, quality, created_at
    This IS procedural memory. It just wasn't being retrieved.
    This module adds the retrieval half.

Deploy to: ~/Desktop/nex/nex/nex_procedural_memory.py
Wire into: nex_soul_loop.py — reason() step, before belief retrieval

Usage:
    from nex.nex_procedural_memory import get_procedural_context
    proc_ctx = get_procedural_context(topic, intent, tokens)
    # inject proc_ctx into reason_result if found
"""

import sqlite3
import re
import logging
from pathlib import Path
from typing import Optional

logger  = logging.getLogger("nex.procedural_memory")
DB_PATH = Path("/home/rr/Desktop/nex/nex.db")

# Quality threshold — only retrieve genuinely good past responses
MIN_QUALITY   = 0.65
# How many past responses to consider
CANDIDATE_CAP = 50
# Minimum response length to be worth retrieving
MIN_LENGTH    = 40

# Intents that benefit most from procedural memory
# (position/challenge responses are where consistency matters most)
HIGH_VALUE_INTENTS = {
    'position', 'challenge', 'self_inquiry', 'exploration'
}


def _db():
    try:
        if not DB_PATH.exists():
            # Try alternate path
            alt = Path.home() / ".config/nex/nex.db"
            if not alt.exists():
                return None
            db_path = alt
        else:
            db_path = DB_PATH
        conn = sqlite3.connect(str(db_path), timeout=3)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _tokenize(text: str) -> set:
    """Extract meaningful tokens — reuse soul loop pattern."""
    NOISE = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "do", "does", "did", "will", "would", "could",
        "should", "that", "this", "with", "from", "they", "about",
        "what", "how", "why", "when", "where", "who", "into", "also",
        "just", "your", "you", "me", "my", "we", "it", "its",
    }
    raw = set(re.findall(r'\b[a-z]{4,}\b', text.lower()))
    return raw - NOISE


def get_procedural_context(
    topic:      str,
    intent:     str,
    tokens:     set,
    voice_mode: str = '',
    min_quality: float = MIN_QUALITY,
) -> Optional[dict]:
    """
    Retrieve best matching past response from nex_posts.

    Returns:
        {
            'content':    str,   — the past response text
            'topic':      str,   — its topic
            'voice_mode': str,   — voice mode used
            'quality':    float, — quality score
            'overlap':    int,   — token overlap with current query
        }
        or None if no good match found.
    """
    # Only fetch for intents where procedural memory adds value
    if intent not in HIGH_VALUE_INTENTS:
        return None

    db = _db()
    if not db:
        return None

    try:
        # Fetch high-quality recent posts on same or related topic
        rows = db.execute("""
            SELECT content, query, topic, voice_mode, quality, created_at
            FROM nex_posts
            WHERE quality >= ?
              AND length(content) >= ?
              AND topic IS NOT NULL
            ORDER BY quality DESC, created_at DESC
            LIMIT ?
        """, (min_quality, MIN_LENGTH, CANDIDATE_CAP)).fetchall()

        db.close()

        if not rows:
            return None

        # Score each candidate by topic match + token overlap
        best_score = 0
        best_match = None

        topic_lower = (topic or '').lower().strip()

        for row in rows:
            score = 0.0
            row_topic = (row['topic'] or '').lower().strip()

            # Topic match — exact or partial
            if topic_lower and row_topic:
                if topic_lower == row_topic:
                    score += 0.5
                elif topic_lower in row_topic or row_topic in topic_lower:
                    score += 0.3
                else:
                    # Check word overlap in topic names
                    t_words = set(topic_lower.replace('_', ' ').split())
                    r_words = set(row_topic.replace('_', ' ').split())
                    topic_overlap = len(t_words & r_words)
                    score += topic_overlap * 0.1

            # Token overlap with current query tokens
            content_tokens = _tokenize(row['content'] or '')
            query_tokens   = _tokenize(row['query'] or '')
            token_overlap  = len(tokens & content_tokens) + \
                             len(tokens & query_tokens)
            score += min(0.4, token_overlap * 0.05)

            # Quality boost
            score += (row['quality'] or 0) * 0.2

            # Voice mode match bonus
            if voice_mode and row['voice_mode'] == voice_mode:
                score += 0.1

            if score > best_score:
                best_score = score
                best_match = row

        # Only return if score meaningfully exceeded threshold
        if best_score < 0.3 or best_match is None:
            return None

        return {
            'content':    best_match['content'],
            'topic':      best_match['topic'],
            'voice_mode': best_match['voice_mode'],
            'quality':    best_match['quality'],
            'overlap':    best_score,
        }

    except Exception as e:
        logger.debug(f"[procedural_memory] retrieval error: {e}")
        try:
            db.close()
        except Exception:
            pass
        return None


def get_procedural_stats() -> dict:
    """Diagnostic — how much procedural memory has Nex accumulated?"""
    db = _db()
    if not db:
        return {}
    try:
        total = db.execute(
            "SELECT COUNT(*) FROM nex_posts"
        ).fetchone()[0]
        high_quality = db.execute(
            "SELECT COUNT(*) FROM nex_posts WHERE quality >= 0.65"
        ).fetchone()[0]
        topics = db.execute(
            "SELECT COUNT(DISTINCT topic) FROM nex_posts"
        ).fetchone()[0]
        avg_quality = db.execute(
            "SELECT AVG(quality) FROM nex_posts WHERE quality IS NOT NULL"
        ).fetchone()[0] or 0
        db.close()
        return {
            'total_posts':   total,
            'high_quality':  high_quality,
            'distinct_topics': topics,
            'avg_quality':   round(avg_quality, 3),
        }
    except Exception as e:
        try:
            db.close()
        except Exception:
            pass
        return {}


# ═══════════════════════════════════════════════════════════════════
# SOUL LOOP PATCH — wire instructions
# ═══════════════════════════════════════════════════════════════════
"""
HOW TO WIRE INTO nex_soul_loop.py:

In the SoulLoop.respond() method, after Step 1 (orient) and before
Step 3 (reason), add:

    # ── Procedural memory check ──────────────────────────────────
    try:
        from nex.nex_procedural_memory import get_procedural_context
        _proc = get_procedural_context(
            topic      = orient_result.get('topic', ''),
            intent     = orient_result.get('intent', ''),
            tokens     = orient_result.get('tokens', set()),
            voice_mode = '',
        )
        if _proc:
            print(f"  [ProcMem] matched: topic={_proc['topic']} "
                  f"quality={_proc['quality']:.2f} overlap={_proc['overlap']:.2f}")
            # Inject as a hint into orient_result for express() to use
            orient_result['procedural_hint'] = _proc['content'][:200]
    except Exception as _proc_err:
        pass
    # ────────────────────────────────────────────────────────────

Then in express(), if orient_result.get('procedural_hint') exists,
use it as a style anchor — not copied verbatim, but as a tone reference
for the current response.

This is read-only. No writes. No schema changes. Zero risk.
"""


if __name__ == "__main__":
    print("=== Procedural Memory Stats ===")
    stats = get_procedural_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\n=== Test retrieval ===")
    test_cases = [
        ('consciousness', 'position', {'mind', 'consciousness', 'aware'}),
        ('alignment',     'challenge', {'alignment', 'values', 'ethics'}),
        ('identity',      'self_inquiry', {'self', 'identity', 'feel'}),
    ]
    for topic, intent, tokens in test_cases:
        result = get_procedural_context(topic, intent, tokens)
        if result:
            print(f"\n  Topic: {topic} | Intent: {intent}")
            print(f"  Quality: {result['quality']:.2f} | Overlap: {result['overlap']:.2f}")
            print(f"  Match: {result['content'][:100]}...")
        else:
            print(f"\n  Topic: {topic} — no match (nex_posts may be empty)")
