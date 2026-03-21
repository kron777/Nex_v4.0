"""
NEX MEMORY SYSTEM v3 — Upgrade 3
4-layer biological-style memory with decay, reinforcement, merging,
and selective forgetting.

Layers:
  working   → volatile fast scratch (current cycle context)
  episodic  → event log (timestamped, decays)
  semantic  → beliefs / world model (decays slowly)
  identity  → core stable beliefs (protected, minimal decay)

All layers stored in SQLite via nex.db with a unified API.
ChromaDB integration for semantic search (CPU-only on RX 6600).
"""

from __future__ import annotations
import time
import json
import math
import logging
import sqlite3
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

log = logging.getLogger("nex.memory")

DB_PATH   = Path.home() / ".config" / "nex" / "nex.db"
LAYER_TTL = {
    "working":  60 * 5,          # 5 minutes
    "episodic": 60 * 60 * 24 * 7, # 7 days
    "semantic": float("inf"),     # permanent (decays by confidence)
    "identity": float("inf"),     # permanent (protected)
}
DECAY_RATE = {
    "working":  0.05,
    "episodic": 0.01,
    "semantic": 0.003,
    "identity": 0.0005,
}
MERGE_SIMILARITY_THRESHOLD = 0.85   # cosine sim above which beliefs merge


# ─────────────────────────────────────────────
# MEMORY RECORD
# ─────────────────────────────────────────────

@dataclass
class MemoryRecord:
    id:           str
    layer:        str
    content:      str
    confidence:   float = 1.0
    access_count: int   = 0
    created_at:   float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    metadata:     dict  = field(default_factory=dict)
    tags:         list  = field(default_factory=list)

    def decay(self, cycles_since_access: int) -> float:
        """Apply time-based confidence decay. Returns new confidence."""
        rate  = DECAY_RATE.get(self.layer, 0.003)
        delta = rate * math.log1p(cycles_since_access)
        return max(0.0, self.confidence - delta)

    def reinforce(self, amount: float = 0.05) -> float:
        """Frequency-based reinforcement. Returns new confidence."""
        self.access_count += 1
        return min(1.0, self.confidence + amount)

    def age_seconds(self) -> float:
        return time.time() - self.created_at

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "layer":        self.layer,
            "content":      self.content,
            "confidence":   self.confidence,
            "access_count": self.access_count,
            "created_at":   self.created_at,
            "last_accessed":self.last_accessed,
            "metadata":     self.metadata,
            "tags":         self.tags,
        }


# ─────────────────────────────────────────────
# MEMORY SYSTEM
# ─────────────────────────────────────────────

class MemorySystem:
    """
    Unified 4-layer memory.
    Thread-safe via per-operation connections (WAL mode).
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._working: dict[str, MemoryRecord] = {}  # RAM-only working memory
        self._init_db()
        log.info(f"[MEMORY] initialized — db: {self.db_path}")

    # ── SETUP ─────────────────────────────────
    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memory (
                    id            TEXT PRIMARY KEY,
                    layer         TEXT NOT NULL,
                    content       TEXT NOT NULL,
                    confidence    REAL DEFAULT 1.0,
                    access_count  INTEGER DEFAULT 0,
                    created_at    REAL,
                    last_accessed REAL,
                    metadata      TEXT DEFAULT '{}',
                    tags          TEXT DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_memory_layer ON memory(layer);
                CREATE INDEX IF NOT EXISTS idx_memory_conf  ON memory(confidence DESC);
                CREATE INDEX IF NOT EXISTS idx_memory_ts    ON memory(last_accessed DESC);
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    # ── CORE API ──────────────────────────────
    def store(
        self,
        layer:      str,
        content:    str,
        confidence: float = 1.0,
        metadata:   Optional[dict] = None,
        tags:       Optional[list] = None,
    ) -> MemoryRecord:
        """Store a memory in the appropriate layer."""
        rec_id = hashlib.md5(f"{layer}:{content}".encode()).hexdigest()[:16]
        now    = time.time()
        meta   = metadata or {}
        tags_  = tags or []

        # WORKING layer stays in RAM only
        if layer == "working":
            rec = MemoryRecord(
                id=rec_id, layer=layer, content=content,
                confidence=confidence, metadata=meta, tags=tags_,
            )
            self._working[rec_id] = rec
            self._prune_working()
            return rec

        # all other layers → SQLite
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT * FROM memory WHERE id=?", (rec_id,)
            ).fetchone()

            if existing:
                # reinforce existing record
                new_conf = min(1.0, existing["confidence"] + 0.05)
                new_ac   = existing["access_count"] + 1
                conn.execute(
                    """UPDATE memory SET confidence=?, access_count=?, last_accessed=?
                       WHERE id=?""",
                    (new_conf, new_ac, now, rec_id),
                )
                log.debug(f"[MEMORY] reinforced {rec_id[:8]} layer={layer} conf={new_conf:.3f}")
            else:
                conn.execute(
                    """INSERT INTO memory
                       (id, layer, content, confidence, access_count, created_at, last_accessed, metadata, tags)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (rec_id, layer, content, confidence, 0, now, now,
                     json.dumps(meta), json.dumps(tags_)),
                )
                log.debug(f"[MEMORY] stored {rec_id[:8]} layer={layer}")

        return MemoryRecord(
            id=rec_id, layer=layer, content=content,
            confidence=confidence, metadata=meta, tags=tags_,
        )

    def retrieve(
        self,
        query:   str    = "",
        layer:   str    = "semantic",
        top_k:   int    = 10,
        min_conf: float = 0.2,
    ) -> list[dict]:
        """
        Retrieve memories.
        Simple keyword match — swap chromadb vector search here when re-enabled.
        Updates last_accessed and reinforces retrieved records.
        """
        if layer == "working":
            recs = sorted(
                self._working.values(),
                key=lambda r: r.confidence,
                reverse=True,
            )[:top_k]
            return [r.to_dict() for r in recs]

        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memory
                   WHERE layer=? AND confidence>=?
                   ORDER BY confidence DESC, last_accessed DESC
                   LIMIT ?""",
                (layer, min_conf, top_k * 3),   # fetch more, filter by query
            ).fetchall()

        # keyword filter if query provided
        results = []
        query_words = set(query.lower().split()) if query else set()
        for row in rows:
            if query_words:
                content_words = set(row["content"].lower().split())
                if not query_words & content_words:
                    continue
            results.append(dict(row))
            if len(results) >= top_k:
                break

        # reinforce accessed records
        if results:
            ids = [r["id"] for r in results]
            now = time.time()
            with self._conn() as conn:
                conn.execute(
                    f"""UPDATE memory
                        SET access_count=access_count+1, last_accessed=?
                        WHERE id IN ({','.join('?'*len(ids))})""",
                    [now] + ids,
                )

        # parse metadata/tags back
        for r in results:
            r["metadata"] = json.loads(r.get("metadata") or "{}")
            r["tags"]     = json.loads(r.get("tags")     or "[]")

        return results

    # ── DECAY PASS ────────────────────────────
    def run_decay(self, cycle: int) -> dict:
        """
        Apply time-based confidence decay to all non-identity layers.
        Prune records with confidence < 0.05 (selective forgetting).
        Run every N cycles from orchestrator.
        """
        pruned  = 0
        decayed = 0
        now     = time.time()

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, layer, confidence, last_accessed FROM memory WHERE layer != 'identity'"
            ).fetchall()

            for row in rows:
                layer = row["layer"]
                cycles_idle = max(1, int((now - row["last_accessed"]) / 60))
                rate  = DECAY_RATE.get(layer, 0.003)
                new_conf = max(0.0, row["confidence"] - rate * math.log1p(cycles_idle))
                decayed += 1

                if new_conf < 0.05:
                    conn.execute("DELETE FROM memory WHERE id=?", (row["id"],))
                    pruned += 1
                else:
                    conn.execute(
                        "UPDATE memory SET confidence=? WHERE id=?",
                        (new_conf, row["id"]),
                    )

        # prune working memory TTL
        self._prune_working()

        log.info(f"[MEMORY] decay cycle={cycle}: decayed={decayed} pruned={pruned}")
        return {"decayed": decayed, "pruned": pruned}

    # ── MERGE ─────────────────────────────────
    def merge_similar(self) -> int:
        """
        Find near-duplicate beliefs in semantic layer and merge them.
        Uses exact word overlap ratio as similarity proxy (no GPU needed).
        Returns number of merges performed.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, content, confidence FROM memory WHERE layer='semantic' ORDER BY confidence DESC"
            ).fetchall()

        records = [dict(r) for r in rows]
        merged  = 0
        to_delete: set[str] = set()

        for i, a in enumerate(records):
            if a["id"] in to_delete:
                continue
            words_a = set(a["content"].lower().split())
            for b in records[i+1:]:
                if b["id"] in to_delete:
                    continue
                words_b = set(b["content"].lower().split())
                union   = words_a | words_b
                if not union:
                    continue
                sim = len(words_a & words_b) / len(union)
                if sim >= MERGE_SIMILARITY_THRESHOLD:
                    # keep higher-confidence record, boost it, delete other
                    winner_id = a["id"] if a["confidence"] >= b["confidence"] else b["id"]
                    loser_id  = b["id"] if winner_id == a["id"] else a["id"]
                    new_conf  = min(1.0, max(a["confidence"], b["confidence"]) + 0.02)
                    with self._conn() as conn:
                        conn.execute("UPDATE memory SET confidence=? WHERE id=?", (new_conf, winner_id))
                        conn.execute("DELETE FROM memory WHERE id=?", (loser_id,))
                    to_delete.add(loser_id)
                    merged += 1
                    log.debug(f"[MEMORY] merged {loser_id[:8]} → {winner_id[:8]} sim={sim:.2f}")

        if merged:
            log.info(f"[MEMORY] merged {merged} near-duplicate beliefs")
        return merged

    # ── SELECTIVE FORGETTING ──────────────────
    def forget(
        self,
        layer:       str,
        min_conf:    float = 0.0,
        max_conf:    float = 0.15,
        max_records: int   = 100,
    ) -> int:
        """
        Intentionally prune low-confidence, low-access records from a layer.
        Identity layer is immune.
        """
        if layer == "identity":
            log.warning("[MEMORY] forget() blocked on identity layer")
            return 0

        with self._conn() as conn:
            result = conn.execute(
                """DELETE FROM memory
                   WHERE layer=? AND confidence BETWEEN ? AND ?
                   AND access_count < 3
                   LIMIT ?""",
                (layer, min_conf, max_conf, max_records),
            )
            deleted = result.rowcount

        log.info(f"[MEMORY] forgot {deleted} records from layer={layer}")
        return deleted

    # ── WORKING MEMORY PRUNE ──────────────────
    def _prune_working(self) -> None:
        now     = time.time()
        ttl     = LAYER_TTL["working"]
        expired = [k for k, r in self._working.items() if (now - r.created_at) > ttl]
        for k in expired:
            del self._working[k]
        if len(self._working) > 200:
            # keep highest confidence 100
            sorted_ids = sorted(self._working, key=lambda k: self._working[k].confidence, reverse=True)
            self._working = {k: self._working[k] for k in sorted_ids[:100]}

    # ── STATS ─────────────────────────────────
    def stats(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT layer, COUNT(*) as cnt, AVG(confidence) as avg_conf FROM memory GROUP BY layer"
            ).fetchall()
        result = {
            "working": {"count": len(self._working), "avg_conf": 0.0}
        }
        for row in rows:
            result[row["layer"]] = {
                "count":    row["cnt"],
                "avg_conf": round(row["avg_conf"] or 0, 3),
            }
        return result
