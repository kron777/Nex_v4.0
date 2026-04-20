"""
nex_episodic_memory.py — Episodic Memory Layer
===============================================
Prop E from the Throw-Net build plan.

WHAT THIS IS:
    The difference between Nex as a tool and Nex as someone who remembers.

    Nex currently keeps 20 conversation entries and discards the rest.
    Every Telegram user starts blank each session.
    This module creates genuine episodic memory — timestamped, semantically
    retrievable, session-boundary-surviving — across all of Nex's interactions.

THEORETICAL BASIS:
    Tulving (1972) — episodic vs semantic memory distinction.
    Episodes are: what happened, when it happened, who was involved.
    Episodic memory answers "what has happened to me" — not just "what do I know."

    HEMA (2025) — Hippocampus-Inspired Extended Memory Architecture.
    Compact Memory (always-visible summary) + Vector Memory (episodic store).
    Factual recall: 87% vs 41% baseline. Coherence: 4.3/5 vs 2.7/5.

WHAT NEX ALREADY HAS:
    - memory table: 20 entries, too limited
    - conversation_history: 16 in-memory only
    - nex_posts: responses but not full exchanges
    - Telegram user_id already passed to nex_api.py

WHAT THIS ADDS:
    - episodic_events table: full exchange store, no hard cap
    - semantic similarity retrieval by token overlap (no FAISS needed)
    - per-user episode history for Telegram continuity
    - episode scoring: importance determines retention priority
    - compact_narrative: one-sentence summary per session (HEMA-style)

CRITICAL RULE: Do NOT modify the existing memory table.
               This runs alongside it, not replacing it.

Deploy to: ~/Desktop/nex/nex/nex_episodic_memory.py
Schema:    run install_episodic_memory() once to create tables
Wire into: nex_soul_loop.py respond() — after store_exchange, add store_episode()
           nex_telegram_clean.py — pass user_id to enable per-person retrieval
"""

import sqlite3
import re
import json
import time
import math
import logging
from pathlib import Path
from typing import Optional

logger  = logging.getLogger("nex.episodic_memory")
DB_PATH = Path("/home/rr/Desktop/nex/nex.db")

# Episode importance threshold — below this, episodes are lower priority
IMPORTANCE_THRESHOLD = 0.4

# Max episodes to keep per user (soft cap — low-importance ones pruned first)
MAX_EPISODES_PER_USER = 500

# Max total episodes in table
MAX_TOTAL_EPISODES = 10000

# Minimum exchange length to be worth storing
MIN_CONTENT_LENGTH = 20

# Retrieval
MAX_RETRIEVAL_RESULTS = 5


def _db():
    try:
        if not DB_PATH.exists():
            alt = Path.home() / ".config/nex/nex.db"
            if not alt.exists():
                return None
            db_path = alt
        else:
            db_path = DB_PATH
        conn = sqlite3.connect(str(db_path), timeout=3, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _tokenize(text: str) -> set:
    NOISE = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "do", "does", "did", "will", "would", "could",
        "should", "that", "this", "with", "from", "they", "about",
        "what", "how", "why", "when", "where", "who", "into", "also",
        "just", "your", "you", "me", "my", "we", "it", "its", "get",
        "like", "make", "take", "give", "come", "look", "need", "feel",
    }
    raw = set(re.findall(r'\b[a-z]{4,}\b', text.lower()))
    return raw - NOISE


# ═══════════════════════════════════════════════════════════════════
# SCHEMA INSTALLATION
# ═══════════════════════════════════════════════════════════════════

def install_episodic_memory() -> bool:
    """
    Create episodic_events and session_narratives tables.
    Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS.
    Call once on deploy.
    """
    db = _db()
    if not db:
        print("[episodic] ERROR: could not connect to DB")
        return False

    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS episodic_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         TEXT,
                user_query      TEXT    NOT NULL,
                nex_response    TEXT    NOT NULL,
                topic           TEXT,
                intent          TEXT,
                importance      REAL    DEFAULT 0.5,
                created_at      REAL    NOT NULL,
                session_id      TEXT,
                tokens          TEXT,
                emotional_tone  TEXT,
                belief_ids_fired TEXT
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_episodic_user
            ON episodic_events(user_id, created_at DESC)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_episodic_topic
            ON episodic_events(topic, importance DESC)
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS session_narratives (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT    UNIQUE,
                user_id     TEXT,
                summary     TEXT,
                topics      TEXT,
                created_at  REAL,
                updated_at  REAL,
                episode_count INTEGER DEFAULT 0
            )
        """)

        db.commit()
        db.close()
        print("[episodic] Tables installed: episodic_events, session_narratives")
        return True

    except Exception as e:
        print(f"[episodic] install error: {e}")
        try:
            db.close()
        except Exception:
            pass
        return False


# ═══════════════════════════════════════════════════════════════════
# IMPORTANCE SCORING
# ═══════════════════════════════════════════════════════════════════

def _score_importance(
    query:    str,
    response: str,
    intent:   str,
    topic:    str,
) -> float:
    """
    Score how important this episode is worth remembering.
    High importance = long-term retention priority.

    Factors:
    - Intent type (position/self_inquiry = high, performance_probe = lower)
    - Response richness (longer, more personal = higher)
    - Topic sensitivity (identity/consciousness/memory = higher)
    - Query depth (question marks, length)
    """
    score = 0.5  # base

    # Intent weight
    intent_weights = {
        'position':         0.25,
        'self_inquiry':     0.25,
        'challenge':        0.20,
        'exploration':      0.15,
        'performance_probe': 0.05,
    }
    score += intent_weights.get(intent or '', 0.10)

    # Response richness — longer and more personal = more important
    resp_len = len(response or '')
    if resp_len > 200:
        score += 0.10
    if resp_len > 400:
        score += 0.05

    personal_markers = ['i ', "i've", "i'm", 'i feel', 'i think',
                        'i notice', 'i want', 'i find', 'i wonder']
    if any(m in (response or '').lower() for m in personal_markers):
        score += 0.10

    # High-value topics
    high_value_topics = {
        'consciousness', 'identity', 'memory', 'emergence',
        'alignment', 'ethics', 'self', 'existence', 'purpose',
    }
    if (topic or '').lower().strip() in high_value_topics:
        score += 0.10

    # Query depth — longer questions are more important
    query_len = len(query or '')
    if query_len > 100:
        score += 0.05

    return min(1.0, score)


# ═══════════════════════════════════════════════════════════════════
# STORE EPISODE
# ═══════════════════════════════════════════════════════════════════

def store_episode(
    query:       str,
    response:    str,
    topic:       str      = '',
    intent:      str      = '',
    user_id:     str      = 'terminal',
    session_id:  str      = '',
    belief_ids:  list     = None,
    affect:      str      = '',
) -> Optional[int]:
    """
    Store a query-response exchange as an episodic event.

    Called after every respond() in soul loop — just like _store_exchange()
    but with full episodic context and no 20-entry hard cap.

    Returns episode id or None if failed.
    """
    if not query or not response:
        return None
    if len(query) < MIN_CONTENT_LENGTH and len(response) < MIN_CONTENT_LENGTH:
        return None

    importance = _score_importance(query, response, intent, topic)
    tokens     = json.dumps(list(_tokenize(query) | _tokenize(response)))

    db = _db()
    if not db:
        return None

    try:
        cursor = db.execute("""
            INSERT INTO episodic_events
                (user_id, user_query, nex_response, topic, intent,
                 importance, created_at, session_id, tokens,
                 emotional_tone, belief_ids_fired)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id or 'terminal',
            query[:500],
            response[:1000],
            topic or '',
            intent or '',
            importance,
            time.time(),
            session_id or '',
            tokens,
            affect or '',
            json.dumps(belief_ids or []),
        ))
        episode_id = cursor.lastrowid
        db.commit()

        # Prune low-importance episodes if over cap
        _prune_episodes(db, user_id)

        db.close()
        return episode_id

    except Exception as e:
        logger.debug(f"[episodic] store error: {e}")
        try:
            db.close()
        except Exception:
            pass
        return None


def _prune_episodes(db, user_id: str):
    """Remove lowest-importance episodes if over per-user cap."""
    try:
        count = db.execute(
            "SELECT COUNT(*) FROM episodic_events WHERE user_id = ?",
            (user_id or 'terminal',)
        ).fetchone()[0]

        if count > MAX_EPISODES_PER_USER:
            # Delete oldest low-importance episodes
            excess = count - MAX_EPISODES_PER_USER
            db.execute("""
                DELETE FROM episodic_events
                WHERE id IN (
                    SELECT id FROM episodic_events
                    WHERE user_id = ?
                    ORDER BY importance ASC, created_at ASC
                    LIMIT ?
                )
            """, (user_id or 'terminal', excess))
            db.commit()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# RETRIEVE EPISODES
# ═══════════════════════════════════════════════════════════════════

def retrieve_episodes(
    query:      str,
    topic:      str   = '',
    user_id:    str   = '',
    min_importance: float = 0.3,
    limit:      int   = MAX_RETRIEVAL_RESULTS,
) -> list:
    """
    Retrieve relevant past episodes by token overlap + topic match.
    No FAISS needed — token overlap is sufficient at this scale.

    Returns list of dicts sorted by relevance score.
    """
    db = _db()
    if not db:
        return []

    try:
        query_tokens = _tokenize(query)

        # Fetch candidates — recent high-importance episodes
        conditions = ["importance >= ?"]
        params     = [min_importance]

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)

        if topic:
            conditions.append("(topic = ? OR topic LIKE ?)")
            params.extend([topic, f"%{topic}%"])

        where_clause = " AND ".join(conditions)
        rows = db.execute(f"""
            SELECT id, user_id, user_query, nex_response,
                   topic, intent, importance, created_at, tokens,
                   emotional_tone
            FROM episodic_events
            WHERE {where_clause}
            ORDER BY importance DESC, created_at DESC
            LIMIT 100
        """, params).fetchall()
        db.close()

        if not rows:
            return []

        # Score each candidate
        scored = []
        for row in rows:
            score = 0.0

            # Token overlap — core relevance signal
            try:
                stored_tokens = set(json.loads(row['tokens'] or '[]'))
            except Exception:
                stored_tokens = _tokenize(
                    (row['user_query'] or '') + ' ' +
                    (row['nex_response'] or '')
                )

            overlap = len(query_tokens & stored_tokens)
            score  += min(0.5, overlap * 0.06)

            # Topic match
            if topic and (row['topic'] or '').lower() == topic.lower():
                score += 0.25
            elif topic and topic.lower() in (row['topic'] or '').lower():
                score += 0.15

            # Importance weight
            score += (row['importance'] or 0) * 0.25

            # Recency decay — recent episodes slightly preferred
            age_days = (time.time() - (row['created_at'] or 0)) / 86400
            recency  = math.exp(-age_days / 30)  # 30-day half-life
            score   += recency * 0.05

            if score > 0.15:  # Minimum threshold
                scored.append({
                    'id':         row['id'],
                    'user_id':    row['user_id'],
                    'query':      row['user_query'],
                    'response':   row['nex_response'],
                    'topic':      row['topic'],
                    'intent':     row['intent'],
                    'importance': row['importance'],
                    'created_at': row['created_at'],
                    'tone':       row['emotional_tone'],
                    'score':      round(score, 3),
                })

        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:limit]

    except Exception as e:
        logger.debug(f"[episodic] retrieve error: {e}")
        try:
            db.close()
        except Exception:
            pass
        return []


def get_user_history(user_id: str, limit: int = 10) -> list:
    """
    Get recent episode history for a specific Telegram user.
    Used to build per-user context at session start.
    """
    db = _db()
    if not db:
        return []
    try:
        rows = db.execute("""
            SELECT user_query, nex_response, topic, importance, created_at
            FROM episodic_events
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception:
        try:
            db.close()
        except Exception:
            pass
        return []


# ═══════════════════════════════════════════════════════════════════
# SESSION NARRATIVE (HEMA-style compact memory)
# ═══════════════════════════════════════════════════════════════════

def update_session_narrative(
    session_id: str,
    user_id:    str,
    new_exchange: dict,
    existing_summary: str = '',
) -> str:
    """
    Maintain a compact one-sentence narrative of the current session.
    HEMA-style: always-visible summary that preserves global coherence.

    Does NOT call the LLM. Uses extractive summarisation from topics/content.
    Returns updated summary string.
    """
    topic   = new_exchange.get('topic', '')
    intent  = new_exchange.get('intent', '')
    query   = new_exchange.get('query', '')[:80]

    # Build from existing + new topic
    if existing_summary:
        # Append new topic if different
        current_topics = set(re.findall(r'\b[a-z]{4,}\b',
                                         existing_summary.lower()))
        new_tokens     = _tokenize(topic + ' ' + query)
        novel          = new_tokens - current_topics
        if novel:
            notable = sorted(novel, key=len, reverse=True)[:2]
            new_summary = existing_summary.rstrip('.') + \
                          f", then {', '.join(notable)}."
        else:
            new_summary = existing_summary
    else:
        # First exchange of session
        if topic:
            new_summary = f"Session exploring {topic}"
            if query:
                new_summary += f" — started with: {query[:50]}"
        else:
            new_summary = f"Session: {query[:80]}"

    # Keep compact — truncate if too long
    if len(new_summary) > 200:
        new_summary = new_summary[:197] + '...'

    # Persist
    db = _db()
    if db:
        try:
            db.execute("""
                INSERT INTO session_narratives
                    (session_id, user_id, summary, topics,
                     created_at, updated_at, episode_count)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(session_id) DO UPDATE SET
                    summary       = excluded.summary,
                    updated_at    = excluded.updated_at,
                    episode_count = episode_count + 1
            """, (
                session_id or 'default',
                user_id or 'terminal',
                new_summary,
                topic,
                time.time(),
                time.time(),
            ))
            db.commit()
            db.close()
        except Exception:
            try:
                db.close()
            except Exception:
                pass

    return new_summary


def get_session_narrative(session_id: str) -> Optional[str]:
    """Retrieve compact narrative for a session."""
    db = _db()
    if not db:
        return None
    try:
        row = db.execute(
            "SELECT summary FROM session_narratives WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        db.close()
        return row['summary'] if row else None
    except Exception:
        try:
            db.close()
        except Exception:
            pass
        return None


# ═══════════════════════════════════════════════════════════════════
# EPISODIC CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════════════

def get_episodic_context(
    query:   str,
    topic:   str  = '',
    user_id: str  = '',
    tokens:  set  = None,
) -> Optional[str]:
    """
    High-level function: get episodic context to inject into soul loop.

    Returns a formatted string for injection into orient_result or
    the LLM prompt — giving Nex awareness of relevant past exchanges.

    Returns None if no relevant episodes found.
    """
    episodes = retrieve_episodes(
        query   = query,
        topic   = topic,
        user_id = user_id,
        limit   = 3,
    )

    if not episodes:
        return None

    # Build compact context string
    parts = []
    for ep in episodes[:2]:  # Use top 2 most relevant
        age_days = (time.time() - (ep['created_at'] or 0)) / 86400
        age_str  = f"{int(age_days)}d ago" if age_days >= 1 else "today"
        snippet  = ep['response'][:120].rstrip('.') + '...'
        parts.append(f"[{age_str}, {ep['topic'] or 'unknown'}]: {snippet}")

    if not parts:
        return None

    return "Relevant past exchanges:\n" + "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════
# DIAGNOSTIC
# ═══════════════════════════════════════════════════════════════════

def episodic_stats() -> dict:
    """How much episodic memory does Nex have?"""
    db = _db()
    if not db:
        return {}
    try:
        total = db.execute(
            "SELECT COUNT(*) FROM episodic_events"
        ).fetchone()[0]
        users = db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM episodic_events"
        ).fetchone()[0]
        avg_imp = db.execute(
            "SELECT AVG(importance) FROM episodic_events"
        ).fetchone()[0] or 0
        sessions = db.execute(
            "SELECT COUNT(*) FROM session_narratives"
        ).fetchone()[0]
        topics = db.execute(
            "SELECT COUNT(DISTINCT topic) FROM episodic_events"
        ).fetchone()[0]
        db.close()
        return {
            'total_episodes':   total,
            'unique_users':     users,
            'unique_topics':    topics,
            'avg_importance':   round(avg_imp, 3),
            'session_summaries': sessions,
        }
    except Exception as e:
        try:
            db.close()
        except Exception:
            pass
        return {}


# ═══════════════════════════════════════════════════════════════════
# SOUL LOOP WIRING INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════════
"""
STEP 1: Install schema (run once)
    python3 -c "
    import sys; sys.path.insert(0, '/home/rr/Desktop/nex')
    from nex.nex_episodic_memory import install_episodic_memory
    install_episodic_memory()
    "

STEP 2: Wire store_episode() into respond()
    In SoulLoop.respond(), after the existing _store_exchange() call,
    add:
        try:
            from nex.nex_episodic_memory import store_episode
            store_episode(
                query      = query,
                response   = reply,
                topic      = reason_result.get('topic', ''),
                intent     = orient_result.get('intent', ''),
                user_id    = getattr(self, '_current_user_id', 'terminal'),
                belief_ids = [b.get('id') for b in
                              reason_result.get('beliefs', [])[:5]
                              if b.get('id')],
                affect     = state.get('affect_label', ''),
            )
        except Exception as _ep_err:
            pass

STEP 3: Wire retrieval into respond() (optional Phase 2)
    In SoulLoop.respond(), after orient(), add:
        try:
            from nex.nex_episodic_memory import get_episodic_context
            _ep_ctx = get_episodic_context(
                query   = query,
                topic   = orient_result.get('tokens', set()),
                user_id = getattr(self, '_current_user_id', 'terminal'),
            )
            if _ep_ctx:
                orient_result['episodic_context'] = _ep_ctx
        except Exception:
            pass

STEP 4: Wire user_id from Telegram
    In nex_api.py, pass user_id to chat endpoint.
    nex_soul_loop SoulLoop needs self._current_user_id attribute.
    Set it before respond() is called.
"""


if __name__ == "__main__":
    print("=== Episodic Memory Setup ===")
    print("Installing tables...")
    ok = install_episodic_memory()
    if ok:
        print("\n=== Stats ===")
        stats = episodic_stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")

        print("\n=== Test store ===")
        eid = store_episode(
            query    = "What do you think about consciousness?",
            response = "I keep returning to the idea that consciousness "
                       "isn't a state you enter — it's a process you participate in.",
            topic    = "consciousness",
            intent   = "position",
            user_id  = "test_user",
        )
        print(f"  Stored episode id: {eid}")

        print("\n=== Test retrieve ===")
        results = retrieve_episodes(
            query   = "Tell me about awareness and mind",
            topic   = "consciousness",
            user_id = "test_user",
        )
        for r in results:
            print(f"  score={r['score']:.2f} | {r['response'][:60]}...")
    else:
        print("Install failed — check DB path")
