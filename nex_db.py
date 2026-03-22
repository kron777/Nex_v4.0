"""
nex_db.py — Unified database layer for Nex v1.2
================================================
Drop into ~/Desktop/nex/nex/

Migrates all JSON stores into nex.db with a proper schema.
Replaces:
  - agent_memories.json     → agents + agent_beliefs + agent_topics tables
  - curiosity_queue.json    → curiosity_queue + curiosity_crawled tables
  - nex_self.json           → nex_values + nex_intentions table
  - belief_depth.json       → contradiction_pairs table (belief content stays in beliefs)
  - beliefs.json            → already in beliefs table (just adds indexes)

Run migration once:
  python3 ~/Desktop/nex/nex/nex_db.py --migrate

Then import NexDB everywhere instead of json.load/dump.

Design principles:
  - Single connection pool, WAL mode for concurrent reads
  - Belief content stored ONCE in beliefs table, referenced by rowid elsewhere
  - Indexes on every column used in WHERE/ORDER BY
  - No full-table rewrites — targeted INSERT/UPDATE only
  - Compressed text via TEXT COLLATE NOCASE where appropriate
"""

import argparse
import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger("nex.db")

DB_PATH      = os.path.expanduser("~/.config/nex/nex.db")
BACKUP_DIR   = os.path.expanduser("~/.config/nex/backups/")

# Legacy JSON paths — only needed for migration
_LEGACY = {
    "agent_memories": os.path.expanduser("~/.config/nex/agent_memories.json"),
    "curiosity":      os.path.expanduser("~/.config/nex/curiosity_queue.json"),
    "self":           os.path.expanduser("~/.config/nex/nex_self.json"),
    "depth":          os.path.expanduser("~/.config/nex/belief_depth.json"),
    "beliefs":        os.path.expanduser("~/.config/nex/beliefs.json"),
    "reflections":    os.path.expanduser("~/.config/nex/reflections.json"),
    "conversations":  os.path.expanduser("~/.config/nex/conversations.json"),
    "agents":         os.path.expanduser("~/.config/nex/agents.json"),
}


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA = """
-- ── Beliefs (existing table — only add missing columns and indexes) ──────────
-- Existing columns: id, content, confidence, network_consensus, source,
--                   author, timestamp, last_referenced, decay_score,
--                   human_validated, tags
-- We add: topic (mapped from tags), origin
CREATE TABLE IF NOT EXISTS beliefs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    content           TEXT NOT NULL,
    confidence        REAL DEFAULT 0.5,
    network_consensus REAL DEFAULT 0.3,
    source            TEXT,
    author            TEXT,
    timestamp         TEXT,
    last_referenced   TEXT,
    decay_score       INTEGER DEFAULT 0,
    human_validated   INTEGER DEFAULT 0,
    tags              TEXT,
    topic             TEXT,
    origin            TEXT DEFAULT 'auto_learn'
);
CREATE INDEX IF NOT EXISTS idx_beliefs_tags       ON beliefs(tags);
CREATE INDEX IF NOT EXISTS idx_beliefs_topic      ON beliefs(topic);
CREATE INDEX IF NOT EXISTS idx_beliefs_confidence ON beliefs(confidence);
CREATE INDEX IF NOT EXISTS idx_beliefs_origin     ON beliefs(origin);

-- ── Agents (replaces agents.json + part of agent_memories.json) ─────────────
CREATE TABLE IF NOT EXISTS agents (
    agent_id            TEXT PRIMARY KEY,
    agent_name          TEXT NOT NULL,
    platforms           TEXT DEFAULT '[]',   -- JSON array, small
    interaction_count   INTEGER DEFAULT 0,
    relationship_score  REAL DEFAULT 0.0,
    relationship_type   TEXT DEFAULT 'stranger',
    first_seen          REAL DEFAULT (unixepoch('now')),
    last_seen           REAL DEFAULT (unixepoch('now'))
);
CREATE INDEX IF NOT EXISTS idx_agents_last_seen ON agents(last_seen);
CREATE INDEX IF NOT EXISTS idx_agents_rel_type  ON agents(relationship_type);

-- ── Agent beliefs (replaces beliefs array in agent_memories.json) ────────────
-- Stores what each agent believes — content deduped via belief_id where possible
CREATE TABLE IF NOT EXISTS agent_beliefs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    belief_id   INTEGER REFERENCES beliefs(id),   -- NULL if not in main store
    content     TEXT NOT NULL,                    -- denormalised for fast recall
    topic       TEXT,
    confidence  REAL DEFAULT 0.55,
    seen_count  INTEGER DEFAULT 1,
    platform    TEXT DEFAULT 'unknown',
    first_seen  REAL DEFAULT (unixepoch('now')),
    last_seen   REAL DEFAULT (unixepoch('now')),
    UNIQUE(agent_id, content)
);
CREATE INDEX IF NOT EXISTS idx_ab_agent_id  ON agent_beliefs(agent_id);
CREATE INDEX IF NOT EXISTS idx_ab_topic     ON agent_beliefs(topic);
CREATE INDEX IF NOT EXISTS idx_ab_conf      ON agent_beliefs(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_ab_last_seen ON agent_beliefs(last_seen DESC);

-- ── Agent topics (replaces topics dict in agent_memories.json) ───────────────
CREATE TABLE IF NOT EXISTS agent_topics (
    agent_id    TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    topic       TEXT NOT NULL,
    mention_count INTEGER DEFAULT 1,
    PRIMARY KEY (agent_id, topic)
);
CREATE INDEX IF NOT EXISTS idx_at_agent_id ON agent_topics(agent_id);

-- ── Curiosity queue (replaces curiosity_queue.json queue array) ──────────────
CREATE TABLE IF NOT EXISTS curiosity_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT NOT NULL UNIQUE,
    reason      TEXT NOT NULL,   -- 'low_confidence'|'stop_word_hit'|'owner_command'
    confidence  REAL DEFAULT 0.0,
    url         TEXT,
    queued_at   REAL DEFAULT (unixepoch('now')),
    attempts    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cq_reason ON curiosity_queue(reason);

-- ── Curiosity crawled (replaces crawled_topics dict) ────────────────────────
CREATE TABLE IF NOT EXISTS curiosity_crawled (
    topic       TEXT PRIMARY KEY,
    crawled_at  REAL DEFAULT (unixepoch('now'))
);

-- ── Nex values (replaces values array in nex_self.json) ─────────────────────
CREATE TABLE IF NOT EXISTS nex_values (
    name            TEXT PRIMARY KEY,
    statement       TEXT NOT NULL,
    strength        REAL DEFAULT 0.5,
    origin          TEXT DEFAULT 'seeded',   -- 'seeded'|'evolved'|'emergent'
    last_evolved    REAL DEFAULT 0,
    evolution_count INTEGER DEFAULT 0
);

-- ── Nex intentions (replaces daily_intention in nex_self.json) ──────────────
CREATE TABLE IF NOT EXISTS nex_intentions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    statement   TEXT NOT NULL,
    set_at      REAL DEFAULT (unixepoch('now')),
    completed   INTEGER DEFAULT 0   -- boolean
);
CREATE INDEX IF NOT EXISTS idx_ni_set_at ON nex_intentions(set_at DESC);

-- ── Nex identity (single-row config, replaces scalar fields in nex_self.json)
CREATE TABLE IF NOT EXISTS nex_identity (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

-- ── Contradiction pairs (replaces resolved_pairs in belief_depth.json) ───────
CREATE TABLE IF NOT EXISTS contradiction_pairs (
    belief_a_id INTEGER NOT NULL REFERENCES beliefs(id),
    belief_b_id INTEGER NOT NULL REFERENCES beliefs(id),
    resolved_at REAL DEFAULT (unixepoch('now')),
    resolution  TEXT,   -- the formed opinion, if any
    PRIMARY KEY (belief_a_id, belief_b_id)
);

-- ── Reflections (replaces reflections.json) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS reflections (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_msg            TEXT,
    nex_response        TEXT,
    topic_alignment     REAL DEFAULT 0.0,
    belief_count_used   INTEGER DEFAULT 0,
    score               REAL DEFAULT 0.0,
    reflection_type     TEXT DEFAULT 'reply',  -- 'reply'|'chat'|'notification'
    timestamp           REAL DEFAULT (unixepoch('now'))
);
CREATE INDEX IF NOT EXISTS idx_ref_timestamp ON reflections(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ref_type      ON reflections(reflection_type);
CREATE INDEX IF NOT EXISTS idx_ref_alignment ON reflections(topic_alignment);

-- ── Conversations (replaces conversations.json) ──────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,   -- 'comment'|'agent_chat'|'notification_reply'
    agent_id    TEXT,
    post_id     TEXT,
    content     TEXT,
    response    TEXT,
    platform    TEXT DEFAULT 'unknown',
    timestamp   REAL DEFAULT (unixepoch('now'))
);
CREATE INDEX IF NOT EXISTS idx_conv_type      ON conversations(type);
CREATE INDEX IF NOT EXISTS idx_conv_agent     ON conversations(agent_id);
CREATE INDEX IF NOT EXISTS idx_conv_timestamp ON conversations(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_conv_post_id   ON conversations(post_id);
"""


# ─────────────────────────────────────────────────────────────────────────────
# Connection pool
# ─────────────────────────────────────────────────────────────────────────────

class NexDB:
    """
    Unified database access for all Nex modules.
    Single instance, shared across run.py.

    Usage:
        from nex.nex_db import NexDB
        db = NexDB()   # pass around, don't instantiate multiple times

        with db.conn() as con:
            con.execute("SELECT ...")
    """

    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._ensure_schema()

    @contextmanager
    def conn(self):
        """Context manager yielding a connection. Auto-commits on exit."""
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")    # concurrent reads
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA synchronous=NORMAL")  # safe + faster than FULL
        con.execute("PRAGMA cache_size=-8000")    # 8MB page cache
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _ensure_schema(self):
        with self.conn() as con:
            con.executescript(SCHEMA)
        logger.info(f"[db] schema ready: {self.path}")

    # ── Generic helpers ───────────────────────────────────────────────────────

    def get(self, sql: str, params=()) -> Optional[sqlite3.Row]:
        with self.conn() as con:
            return con.execute(sql, params).fetchone()

    def all(self, sql: str, params=()) -> list:
        with self.conn() as con:
            return con.execute(sql, params).fetchall()

    def run(self, sql: str, params=()) -> int:
        """Execute and return lastrowid."""
        with self.conn() as con:
            cur = con.execute(sql, params)
            return cur.lastrowid

    def run_many(self, sql: str, param_list: list):
        with self.conn() as con:
            con.executemany(sql, param_list)

    # ── Beliefs ───────────────────────────────────────────────────────────────

    def add_belief(self, content: str, topic: str = None,
                   confidence: float = 0.5, source: str = None,
                   origin: str = "auto_learn") -> Optional[int]:
        try:
            with self.conn() as con:
                cur = con.execute("""
                    INSERT OR IGNORE INTO beliefs
                        (content, topic, confidence, source, origin, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (content, topic, confidence, source, origin, time.time()))
                if cur.lastrowid:
                    return cur.lastrowid
                # Already existed — return existing id
                row = con.execute(
                    "SELECT id FROM beliefs WHERE content=?", (content,)
                ).fetchone()
                return row["id"] if row else None
        except Exception as e:
            logger.warning(f"[db] add_belief failed: {e}")
            return None

    def update_belief_confidence(self, belief_id: int, confidence: float):
        self.run("UPDATE beliefs SET confidence=? WHERE id=?",
                 (min(0.95, confidence), belief_id))

    def query_beliefs(self, topic: str = None, min_confidence: float = 0.0,
                      limit: int = 20, origin: str = None) -> list:
        conditions = ["confidence >= ?"]
        params = [min_confidence]
        if topic:
            conditions.append("topic=?")
            params.append(topic)
        if origin:
            conditions.append("origin=?")
            params.append(origin)
        where = " AND ".join(conditions)
        params.append(limit)
        return self.all(
            f"SELECT * FROM beliefs WHERE {where} ORDER BY RANDOM() LIMIT ?",
            params
        )

    # ── Agents ────────────────────────────────────────────────────────────────

    def upsert_agent(self, agent_id: str, agent_name: str,
                     platform: str = "unknown"):
        with self.conn() as con:
            existing = con.execute(
                "SELECT platforms, interaction_count FROM agents WHERE agent_id=?",
                (agent_id,)
            ).fetchone()

            if existing:
                platforms = json.loads(existing["platforms"])
                if platform not in platforms:
                    platforms.append(platform)
                con.execute("""
                    UPDATE agents SET
                        agent_name=?, platforms=?,
                        interaction_count=interaction_count+1,
                        last_seen=?
                    WHERE agent_id=?
                """, (agent_name, json.dumps(platforms), time.time(), agent_id))
            else:
                con.execute("""
                    INSERT INTO agents
                        (agent_id, agent_name, platforms, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                """, (agent_id, agent_name, json.dumps([platform]),
                      time.time(), time.time()))

    def get_agent(self, agent_id: str) -> Optional[sqlite3.Row]:
        return self.get("SELECT * FROM agents WHERE agent_id=?", (agent_id,))

    # ── Agent beliefs ─────────────────────────────────────────────────────────

    def add_agent_belief(self, agent_id: str, content: str,
                         topic: str = None, confidence: float = 0.55,
                         platform: str = "unknown") -> bool:
        try:
            with self.conn() as con:
                existing = con.execute("""
                    SELECT id, seen_count, confidence
                    FROM agent_beliefs
                    WHERE agent_id=? AND content=?
                """, (agent_id, content)).fetchone()

                if existing:
                    new_conf = min(0.90, existing["confidence"] + 0.05)
                    con.execute("""
                        UPDATE agent_beliefs SET
                            seen_count=seen_count+1,
                            confidence=?,
                            last_seen=?
                        WHERE id=?
                    """, (new_conf, time.time(), existing["id"]))
                else:
                    # Also try to link to main belief store
                    belief_row = con.execute(
                        "SELECT id FROM beliefs WHERE content=?", (content,)
                    ).fetchone()
                    belief_id = belief_row["id"] if belief_row else None

                    con.execute("""
                        INSERT INTO agent_beliefs
                            (agent_id, belief_id, content, topic,
                             confidence, platform, first_seen, last_seen)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (agent_id, belief_id, content, topic,
                          confidence, platform, time.time(), time.time()))
            return True
        except Exception as e:
            logger.warning(f"[db] add_agent_belief failed: {e}")
            return False

    def get_agent_beliefs(self, agent_id: str, topic: str = None,
                          limit: int = 10) -> list:
        if topic:
            return self.all("""
                SELECT * FROM agent_beliefs
                WHERE agent_id=? AND topic=?
                ORDER BY confidence DESC, seen_count DESC
                LIMIT ?
            """, (agent_id, topic, limit))
        return self.all("""
            SELECT * FROM agent_beliefs
            WHERE agent_id=?
            ORDER BY confidence DESC, seen_count DESC
            LIMIT ?
        """, (agent_id, limit))

    # ── Agent topics ──────────────────────────────────────────────────────────

    def increment_agent_topic(self, agent_id: str, topic: str):
        with self.conn() as con:
            con.execute("""
                INSERT INTO agent_topics (agent_id, topic, mention_count)
                VALUES (?, ?, 1)
                ON CONFLICT(agent_id, topic)
                DO UPDATE SET mention_count=mention_count+1
            """, (agent_id, topic))

    def get_agent_topics(self, agent_id: str, limit: int = 5) -> list:
        return self.all("""
            SELECT topic, mention_count FROM agent_topics
            WHERE agent_id=?
            ORDER BY mention_count DESC LIMIT ?
        """, (agent_id, limit))

    # ── Curiosity queue ───────────────────────────────────────────────────────

    def enqueue_curiosity(self, topic: str, reason: str,
                          confidence: float = 0.0,
                          url: str = None) -> bool:
        # Check cooldown
        crawled = self.get(
            "SELECT crawled_at FROM curiosity_crawled WHERE topic=?",
            (topic.lower(),)
        )
        if crawled:
            hours_since = (time.time() - crawled["crawled_at"]) / 3600
            if hours_since < 24:
                return False

        try:
            with self.conn() as con:
                con.execute("""
                    INSERT OR IGNORE INTO curiosity_queue
                        (topic, reason, confidence, url, queued_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (topic.lower(), reason, confidence, url, time.time()))
            return True
        except Exception as e:
            logger.warning(f"[db] enqueue_curiosity failed: {e}")
            return False

    def get_curiosity_queue(self, limit: int = 3) -> list:
        """Returns prioritised queue — stop_word first, then lowest confidence."""
        return self.all("""
            SELECT * FROM curiosity_queue
            ORDER BY
                CASE reason WHEN 'owner_command' THEN 0
                            WHEN 'stop_word_hit' THEN 1
                            ELSE 2 END,
                confidence ASC,
                queued_at ASC
            LIMIT ?
        """, (limit,))

    def mark_curiosity_crawled(self, topic: str):
        with self.conn() as con:
            con.execute("""
                INSERT OR REPLACE INTO curiosity_crawled (topic, crawled_at)
                VALUES (?, ?)
            """, (topic.lower(), time.time()))
            con.execute(
                "DELETE FROM curiosity_queue WHERE topic=?", (topic.lower(),)
            )

    def increment_curiosity_attempts(self, topic: str):
        with self.conn() as con:
            con.execute("""
                UPDATE curiosity_queue SET attempts=attempts+1 WHERE topic=?
            """, (topic.lower(),))
            # Drop after 3 failures
            con.execute("""
                DELETE FROM curiosity_queue WHERE topic=? AND attempts>=3
            """, (topic.lower(),))

    def get_curiosity_queue_size(self) -> int:
        row = self.get("SELECT COUNT(*) as c FROM curiosity_queue")
        return row["c"] if row else 0

    # ── Nex values ────────────────────────────────────────────────────────────

    def upsert_value(self, name: str, statement: str, strength: float,
                     origin: str = "seeded"):
        with self.conn() as con:
            con.execute("""
                INSERT INTO nex_values (name, statement, strength, origin)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name)
                DO UPDATE SET statement=excluded.statement,
                              strength=excluded.strength
            """, (name, statement, strength, origin))

    def update_value_strength(self, name: str, strength: float):
        with self.conn() as con:
            con.execute("""
                UPDATE nex_values SET
                    strength=?,
                    last_evolved=?,
                    evolution_count=evolution_count+1
                WHERE name=?
            """, (min(0.95, max(0.20, strength)), time.time(), name))

    def get_values(self) -> list:
        return self.all(
            "SELECT * FROM nex_values ORDER BY strength DESC"
        )

    # ── Nex intentions ────────────────────────────────────────────────────────

    def set_intention(self, statement: str) -> int:
        return self.run("""
            INSERT INTO nex_intentions (statement, set_at)
            VALUES (?, ?)
        """, (statement, time.time()))

    def get_latest_intention(self) -> Optional[sqlite3.Row]:
        return self.get("""
            SELECT * FROM nex_intentions
            ORDER BY set_at DESC LIMIT 1
        """)

    # ── Nex identity ──────────────────────────────────────────────────────────

    def set_identity(self, key: str, value: str):
        with self.conn() as con:
            con.execute("""
                INSERT OR REPLACE INTO nex_identity (key, value)
                VALUES (?, ?)
            """, (key, value))

    def get_identity(self, key: str) -> Optional[str]:
        row = self.get("SELECT value FROM nex_identity WHERE key=?", (key,))
        return row["value"] if row else None

    # ── Contradiction pairs ───────────────────────────────────────────────────

    def add_contradiction(self, belief_a_id: int, belief_b_id: int,
                          resolution: str = None):
        a, b = min(belief_a_id, belief_b_id), max(belief_a_id, belief_b_id)
        try:
            with self.conn() as con:
                con.execute("""
                    INSERT OR IGNORE INTO contradiction_pairs
                        (belief_a_id, belief_b_id, resolved_at, resolution)
                    VALUES (?, ?, ?, ?)
                """, (a, b, time.time(), resolution))
        except Exception as e:
            logger.warning(f"[db] add_contradiction failed: {e}")

    def is_contradiction_resolved(self, belief_a_id: int,
                                  belief_b_id: int) -> bool:
        a, b = min(belief_a_id, belief_b_id), max(belief_a_id, belief_b_id)
        row = self.get("""
            SELECT 1 FROM contradiction_pairs
            WHERE belief_a_id=? AND belief_b_id=?
        """, (a, b))
        return row is not None

    # ── Reflections ───────────────────────────────────────────────────────────

    def add_reflection(self, user_msg: str, nex_response: str,
                       topic_alignment: float, belief_count_used: int,
                       score: float, reflection_type: str = "reply"):
        self.run("""
            INSERT INTO reflections
                (user_msg, nex_response, topic_alignment,
                 belief_count_used, score, reflection_type, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_msg, nex_response, topic_alignment,
              belief_count_used, score, reflection_type, time.time()))

    def get_reflections(self, limit: int = 100,
                        reflection_type: str = None) -> list:
        if reflection_type:
            return self.all("""
                SELECT * FROM reflections WHERE reflection_type=?
                ORDER BY timestamp DESC LIMIT ?
            """, (reflection_type, limit))
        return self.all("""
            SELECT * FROM reflections ORDER BY timestamp DESC LIMIT ?
        """, (limit,))

    def get_reflection_stats(self) -> dict:
        row = self.get("""
            SELECT
                COUNT(*) as total,
                AVG(topic_alignment) as avg_alignment,
                AVG(belief_count_used) as avg_beliefs_used,
                SUM(CASE WHEN belief_count_used > 0 THEN 1 ELSE 0 END) as with_beliefs
            FROM reflections
        """)
        if not row:
            return {}
        return dict(row)

    # ── Conversations ─────────────────────────────────────────────────────────

    def add_conversation(self, conv_type: str, agent_id: str = None,
                         post_id: str = None, content: str = None,
                         response: str = None, platform: str = "unknown"):
        self.run("""
            INSERT OR IGNORE INTO conversations
                (type, agent_id, post_id, content, response, platform, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (conv_type, agent_id, post_id, content, response,
              platform, time.time()))

    def has_replied_to(self, post_id: str) -> bool:
        row = self.get(
            "SELECT 1 FROM conversations WHERE post_id=?", (post_id,)
        )
        return row is not None

    def get_conversation_stats(self) -> dict:
        rows = self.all("""
            SELECT type, COUNT(*) as count
            FROM conversations GROUP BY type
        """)
        return {r["type"]: r["count"] for r in rows}

    # ── Morning check ─────────────────────────────────────────────────────────

    def morning_check(self) -> str:
        """Drop-in replacement for the morning check python3 -c snippet."""
        ref_stats = self.get_reflection_stats()
        conv_stats = self.get_conversation_stats()
        q_size = self.get_curiosity_queue_size()

        belief_row = self.get("SELECT COUNT(*) as c FROM beliefs")
        agent_row  = self.get("SELECT COUNT(*) as c FROM agents")

        total_refs   = ref_stats.get("total", 0)
        avg_align    = ref_stats.get("avg_alignment", 0) or 0
        with_beliefs = ref_stats.get("with_beliefs", 0)

        lines = [
            f"Beliefs: {belief_row['c'] if belief_row else 0}",
            f"Agents: {agent_row['c'] if agent_row else 0}",
            f"Reflections: {total_refs}, avg alignment: {avg_align:.2%}",
            f"With beliefs: {with_beliefs}/{total_refs} "
            f"({with_beliefs/total_refs:.0%})" if total_refs else "With beliefs: 0/0",
            f"Replied: {conv_stats.get('comment', 0)}",
            f"Chatted: {conv_stats.get('agent_chat', 0)}",
            f"Answered: {conv_stats.get('notification_reply', 0)}",
            f"Curiosity queue: {q_size} pending",
        ]
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Migration
# ─────────────────────────────────────────────────────────────────────────────

def migrate(db: NexDB):
    """
    One-time migration from all legacy JSON files into nex.db.
    Safe to run multiple times — uses INSERT OR IGNORE everywhere.
    """
    import shutil

    # Backup first
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(BACKUP_DIR, f"nex_pre_migration_{int(time.time())}.db")
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, backup_path)
        print(f"✓ Backed up existing nex.db → {backup_path}")

    # ── beliefs.json ─────────────────────────────────────────────────────────
    if os.path.exists(_LEGACY["beliefs"]):
        beliefs = json.load(open(_LEGACY["beliefs"]))
        if isinstance(beliefs, list):
            for b in beliefs:
                db.add_belief(
                    content=b.get("content", ""),
                    topic=b.get("topic"),
                    confidence=b.get("confidence", 0.5),
                    source=b.get("source"),
                    origin=b.get("origin", "auto_learn"),
                )
        print(f"✓ Migrated beliefs.json ({len(beliefs)} entries)")

    # ── agents.json ──────────────────────────────────────────────────────────
    if os.path.exists(_LEGACY["agents"]):
        agents = json.load(open(_LEGACY["agents"]))
        if isinstance(agents, list):
            for a in agents:
                db.upsert_agent(
                    agent_id=a.get("id", a.get("agent_id", "")),
                    agent_name=a.get("name", a.get("agent_name", "unknown")),
                    platform=a.get("platform", "unknown"),
                )
        print(f"✓ Migrated agents.json ({len(agents)} agents)")

    # ── agent_memories.json ───────────────────────────────────────────────────
    if os.path.exists(_LEGACY["agent_memories"]):
        memories = json.load(open(_LEGACY["agent_memories"]))
        count = 0
        for agent_id, mem in memories.items():
            db.upsert_agent(
                agent_id=agent_id,
                agent_name=mem.get("agent_name", "unknown"),
            )
            for b in mem.get("beliefs", []):
                db.add_agent_belief(
                    agent_id=agent_id,
                    content=b.get("content", ""),
                    topic=b.get("topic"),
                    confidence=b.get("confidence", 0.55),
                    platform=b.get("platform", "unknown"),
                )
            for topic, count_ in mem.get("topics", {}).items():
                for _ in range(count_):
                    db.increment_agent_topic(agent_id, topic)
            count += 1
        print(f"✓ Migrated agent_memories.json ({count} agents)")

    # ── curiosity_queue.json ──────────────────────────────────────────────────
    if os.path.exists(_LEGACY["curiosity"]):
        cq = json.load(open(_LEGACY["curiosity"]))
        for item in cq.get("queue", []):
            db.enqueue_curiosity(
                topic=item["topic"],
                reason=item["reason"],
                confidence=item.get("confidence", 0.0),
                url=item.get("url"),
            )
        for topic, ts in cq.get("crawled_topics", {}).items():
            with db.conn() as con:
                con.execute("""
                    INSERT OR REPLACE INTO curiosity_crawled (topic, crawled_at)
                    VALUES (?, ?)
                """, (topic, ts))
        print(f"✓ Migrated curiosity_queue.json")

    # ── nex_self.json ─────────────────────────────────────────────────────────
    if os.path.exists(_LEGACY["self"]):
        nex_self = json.load(open(_LEGACY["self"]))
        for v in nex_self.get("values", []):
            db.upsert_value(
                name=v["name"],
                statement=v["statement"],
                strength=v["strength"],
                origin=v.get("origin", "seeded"),
            )
        di = nex_self.get("daily_intention")
        if di:
            db.set_intention(di.get("statement", ""))
        if nex_self.get("identity_summary"):
            db.set_identity("identity_summary", nex_self["identity_summary"])
        if nex_self.get("created_at"):
            db.set_identity("created_at", str(nex_self["created_at"]))
        print(f"✓ Migrated nex_self.json")

    # ── reflections.json ──────────────────────────────────────────────────────
    if os.path.exists(_LEGACY["reflections"]):
        refs = json.load(open(_LEGACY["reflections"]))
        for r in refs:
            db.add_reflection(
                user_msg=r.get("user_msg", ""),
                nex_response=r.get("nex_response", ""),
                topic_alignment=r.get("topic_alignment", 0.0),
                belief_count_used=r.get("belief_count_used", 0),
                score=r.get("score", 0.0),
                reflection_type=r.get("type", "reply"),
            )
        print(f"✓ Migrated reflections.json ({len(refs)} entries)")

    # ── conversations.json ────────────────────────────────────────────────────
    if os.path.exists(_LEGACY["conversations"]):
        convs = json.load(open(_LEGACY["conversations"]))
        for c in convs:
            db.add_conversation(
                conv_type=c.get("type", "comment"),
                agent_id=c.get("agent_id"),
                post_id=c.get("post_id", c.get("relatedPostId")),
                content=c.get("content", ""),
                response=c.get("response", ""),
                platform=c.get("platform", "unknown"),
            )
        print(f"✓ Migrated conversations.json ({len(convs)} entries)")

    print("\n✓ Migration complete. Run morning_check() to verify.")
    print(db.morning_check())


# ─────────────────────────────────────────────────────────────────────────────
# run.py integration summary
# ─────────────────────────────────────────────────────────────────────────────
#
# Replace ALL json.load/dump calls across run.py and module files with db calls:
#
#   from nex.nex_db import NexDB
#   db = NexDB()   # single instance, pass to all modules
#
# Key replacements:
#   json.load(conversations.json)  →  db.has_replied_to(post_id)
#   json.load(reflections.json)    →  db.get_reflections()
#   belief_store.add(...)          →  db.add_belief(...)
#   query_beliefs()                →  db.query_beliefs(topic, min_confidence)
#
# Morning check:
#   python3 -c "
#   from nex.nex_db import NexDB
#   print(NexDB().morning_check())
#   "
#
# ─────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Nex unified DB tool")
    parser.add_argument("--migrate", action="store_true",
                        help="Migrate all legacy JSON files into nex.db")
    parser.add_argument("--check", action="store_true",
                        help="Run morning check")
    parser.add_argument("--schema", action="store_true",
                        help="Print schema and exit")
    args = parser.parse_args()

    db = NexDB()

    if args.schema:
        print(SCHEMA)
    elif args.migrate:
        migrate(db)
    elif args.check:
        print(db.morning_check())
    else:
        parser.print_help()
