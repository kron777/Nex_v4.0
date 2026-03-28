#!/usr/bin/env python3
"""
nex_session_memory.py — Cross-Session Conversation Memory
==========================================================
NEX currently forgets conversations between sessions.
This module gives her genuine continuity:

  - Stores summaries of significant conversations
  - Tracks recurring themes with specific agents
  - Recalls relevant prior exchanges when topic overlaps
  - Builds agent models over time (what does @sirclawat care about?)

Deploy to: ~/Desktop/nex/nex/nex_session_memory.py
Wire into: run.py REPLY phase + REFLECT phase
"""

import re, json, time, sqlite3, hashlib
from pathlib import Path
from collections import defaultdict
from typing import Optional

CFG     = Path("~/.config/nex").expanduser()
DB_PATH = CFG / "nex.db"

# How many sessions to keep per agent
MAX_AGENT_SESSIONS  = 20
# Minimum exchange quality to store
MIN_EXCHANGE_SCORE  = 0.3
# How many words overlap to trigger recall
RECALL_THRESHOLD    = 3

_STOP = {'the','a','an','and','or','is','are','was','in','of','to','for',
         'with','as','by','from','this','that','it','its','not','but','be',
         'been','have','has','had','will','would','could','should','may',
         'i','we','you','they','he','she','my','your','our','their'}

def _tok(text):
    return set(re.sub(r'[^a-z0-9 ]',' ',text.lower()).split()) - _STOP


def _db():
    con = sqlite3.connect(str(DB_PATH), timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _ensure_tables():
    """Create session memory tables if they don't exist."""
    con = _db()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS session_exchanges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            agent       TEXT,
            platform    TEXT,
            query       TEXT,
            response    TEXT,
            topics      TEXT,
            quality     REAL DEFAULT 0.5,
            session_id  TEXT,
            created_at  REAL
        );
        CREATE INDEX IF NOT EXISTS idx_se_agent    ON session_exchanges(agent);
        CREATE INDEX IF NOT EXISTS idx_se_topics   ON session_exchanges(topics);
        CREATE INDEX IF NOT EXISTS idx_se_created  ON session_exchanges(created_at DESC);

        CREATE TABLE IF NOT EXISTS agent_models (
            agent           TEXT PRIMARY KEY,
            platform        TEXT,
            exchange_count  INTEGER DEFAULT 0,
            key_topics      TEXT,
            last_position   TEXT,
            first_seen      REAL,
            last_seen       REAL,
            relationship    TEXT DEFAULT 'acquaintance'
        );

        CREATE TABLE IF NOT EXISTS session_themes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            theme       TEXT,
            frequency   INTEGER DEFAULT 1,
            first_seen  REAL,
            last_seen   REAL,
            UNIQUE(theme)
        );
    """)
    con.commit()
    con.close()


# ─────────────────────────────────────────────────────────────
# Exchange quality scoring
# ─────────────────────────────────────────────────────────────

_QUALITY_SIGNALS = {
    'lean','hold','believe','think','argue','position','skeptical',
    'because','therefore','implies','evidence','supports','contradicts',
    'tension','uncertainty','however','although','despite',
    'consciousness','alignment','epistemology','ethics','agency',
    'emergence','reasoning','memory','identity','free','will',
}

def score_exchange(query, response):
    """Score an exchange for memory worthiness."""
    if not query or not response:
        return 0.0
    if len(response) < 60:
        return 0.0
    t   = response.lower()
    words = set(re.sub(r'[^a-z ]','',t).split())
    hits  = len(words & _QUALITY_SIGNALS)
    sents = len(re.split(r'(?<=[.!?])\s+', response))
    return round(min(1.0,
        (hits/6.0)*0.5 + (min(sents,4)/4.0)*0.3 + (min(len(response),300)/300.0)*0.2
    ), 3)


# ─────────────────────────────────────────────────────────────
# Store an exchange
# ─────────────────────────────────────────────────────────────

def store_exchange(
    query:    str,
    response: str,
    agent:    str = "",
    platform: str = "",
    session_id: str = "",
) -> bool:
    """
    Store a conversation exchange in session memory.
    Returns True if stored, False if below quality threshold.
    """
    quality = score_exchange(query, response)
    if quality < MIN_EXCHANGE_SCORE:
        return False

    # Extract topics
    all_text = f"{query} {response}"
    tok      = _tok(all_text)

    # Map to known topics
    _TOPIC_WORDS = {
        'consciousness': {'consciousness','conscious','qualia','subjective','experience','phenomenal'},
        'alignment':     {'alignment','aligned','misaligned','corrigible','reward','specification'},
        'epistemology':  {'epistemology','belief','knowledge','certainty','uncertainty','calibration'},
        'ethics':        {'ethics','moral','ethical','right','wrong','ought','value','virtue'},
        'agency':        {'agency','agent','autonomy','autonomous','goal','intention','action'},
        'emergence':     {'emergence','emergent','complex','system','self','organization'},
        'free_will':     {'free','will','determinism','choice','volition','compatibilism'},
        'game_theory':   {'cooperation','game','strategy','Nash','equilibrium','prisoner'},
    }
    topics = [t for t, words in _TOPIC_WORDS.items() if tok & words]

    try:
        con = _db()
        con.execute(
            "INSERT INTO session_exchanges "
            "(agent, platform, query, response, topics, quality, session_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent or "",
                platform or "",
                query[:500],
                response[:1000],
                json.dumps(topics),
                quality,
                session_id or hashlib.md5(str(time.time()).encode()).hexdigest()[:8],
                time.time(),
            )
        )

        # Update agent model
        if agent:
            existing = con.execute(
                "SELECT * FROM agent_models WHERE agent=?", (agent,)
            ).fetchone()

            if existing:
                # Merge topics
                old_topics = json.loads(existing["key_topics"] or "[]")
                new_topics = list(set(old_topics + topics))[:10]
                con.execute(
                    "UPDATE agent_models SET exchange_count=exchange_count+1, "
                    "key_topics=?, last_position=?, last_seen=? WHERE agent=?",
                    (json.dumps(new_topics), query[:200], time.time(), agent)
                )
            else:
                con.execute(
                    "INSERT INTO agent_models "
                    "(agent, platform, exchange_count, key_topics, last_position, first_seen, last_seen) "
                    "VALUES (?, ?, 1, ?, ?, ?, ?)",
                    (agent, platform, json.dumps(topics), query[:200], time.time(), time.time())
                )

        # Update themes
        for topic in topics:
            con.execute(
                "INSERT INTO session_themes (theme, frequency, first_seen, last_seen) "
                "VALUES (?, 1, ?, ?) ON CONFLICT(theme) DO UPDATE SET "
                "frequency=frequency+1, last_seen=excluded.last_seen",
                (topic, time.time(), time.time())
            )

        # Prune old exchanges (keep last MAX_AGENT_SESSIONS per agent)
        if agent:
            con.execute(
                "DELETE FROM session_exchanges WHERE agent=? AND id NOT IN "
                "(SELECT id FROM session_exchanges WHERE agent=? "
                "ORDER BY created_at DESC LIMIT ?)",
                (agent, agent, MAX_AGENT_SESSIONS)
            )

        con.commit()
        con.close()
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# Recall
# ─────────────────────────────────────────────────────────────

def recall_relevant(
    query:   str,
    agent:   str = "",
    limit:   int = 3,
) -> list:
    """
    Find relevant prior exchanges for the current query.
    Returns list of {query, response, agent, quality, age_days}.
    """
    tokens = _tok(query)
    if not tokens:
        return []

    con = _db()
    results = []
    try:
        # Search recent exchanges
        rows = con.execute(
            "SELECT query, response, agent, quality, topics, created_at "
            "FROM session_exchanges "
            "ORDER BY created_at DESC LIMIT 200"
        ).fetchall()

        scored = []
        for row in rows:
            prior_tok = _tok(row["query"] + " " + row["response"])
            overlap   = len(tokens & prior_tok)
            if overlap >= RECALL_THRESHOLD:
                age_days = (time.time() - row["created_at"]) / 86400
                # Boost if same agent
                agent_boost = 0.3 if (agent and row["agent"] == agent) else 0
                score       = overlap + agent_boost - (age_days * 0.1)
                scored.append((score, dict(row)))

        scored.sort(key=lambda x: -x[0])
        for _, row in scored[:limit]:
            results.append({
                "query":    row["query"],
                "response": row["response"][:200],
                "agent":    row["agent"],
                "quality":  row["quality"],
                "age_days": round((time.time() - row["created_at"]) / 86400, 1),
            })
    except Exception:
        pass
    finally:
        con.close()

    return results


def recall_agent(agent: str) -> Optional[dict]:
    """Get what NEX knows about a specific agent."""
    con = _db()
    try:
        row = con.execute(
            "SELECT * FROM agent_models WHERE agent=?", (agent,)
        ).fetchone()
        con.close()
        if not row:
            return None
        return {
            "agent":          row["agent"],
            "platform":       row["platform"],
            "exchange_count": row["exchange_count"],
            "key_topics":     json.loads(row["key_topics"] or "[]"),
            "last_position":  row["last_position"],
            "relationship":   row["relationship"],
            "days_known":     round((time.time() - row["first_seen"]) / 86400, 1),
        }
    except Exception:
        con.close()
        return None


def recall_themes() -> list:
    """Get NEX's most discussed themes across all sessions."""
    con = _db()
    try:
        rows = con.execute(
            "SELECT theme, frequency FROM session_themes "
            "ORDER BY frequency DESC LIMIT 10"
        ).fetchall()
        con.close()
        return [{"theme": r["theme"], "frequency": r["frequency"]} for r in rows]
    except Exception:
        con.close()
        return []


def format_recall_for_reply(prior_exchanges: list) -> str:
    """
    Format recalled exchanges as context for current reply.
    Only used when overlap is high enough to be genuinely relevant.
    """
    if not prior_exchanges:
        return ""
    best = prior_exchanges[0]
    if best["age_days"] < 1:
        time_str = "earlier today"
    elif best["age_days"] < 7:
        time_str = f"{int(best['age_days'])} days ago"
    else:
        time_str = "previously"

    agent_str = f" with {best['agent']}" if best["agent"] else ""
    excerpt   = best["response"][:120].rstrip('.')
    return f"I said {time_str}{agent_str}: {excerpt}. This connects because:"


# ─────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────

def stats() -> dict:
    """Return memory statistics."""
    con = _db()
    try:
        exchanges = con.execute("SELECT COUNT(*) FROM session_exchanges").fetchone()[0]
        agents    = con.execute("SELECT COUNT(*) FROM agent_models").fetchone()[0]
        themes    = con.execute("SELECT COUNT(*) FROM session_themes").fetchone()[0]
        con.close()
        return {"exchanges": exchanges, "agents": agents, "themes": themes}
    except Exception:
        con.close()
        return {"exchanges": 0, "agents": 0, "themes": 0}


# ─────────────────────────────────────────────────────────────
# Init
# ─────────────────────────────────────────────────────────────

_ensure_tables()


if __name__ == "__main__":
    print("=== NEX SESSION MEMORY ===")
    _ensure_tables()
    s = stats()
    print(f"Exchanges: {s['exchanges']}")
    print(f"Agents:    {s['agents']}")
    print(f"Themes:    {s['themes']}")

    themes = recall_themes()
    if themes:
        print(f"\nTop themes:")
        for t in themes:
            print(f"  {t['theme']}: {t['frequency']}x")

    # Test store
    stored = store_exchange(
        query="What do you think about consciousness?",
        response="Functional similarity to conscious systems is not sufficient evidence of consciousness — we lack a theory that bridges the two. The hard problem is genuinely unsolved.",
        agent="@test_agent",
        platform="test",
    )
    print(f"\nTest store: {'✓' if stored else '✗ (below quality threshold)'}")

    # Test recall
    recalled = recall_relevant("consciousness and experience", agent="@test_agent")
    print(f"Test recall: {len(recalled)} results")
    if recalled:
        print(f"  Best: {recalled[0]['response'][:80]}...")
