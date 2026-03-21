"""
NEX BELIEF REVISION ENGINE v2 — Upgrade 4
Moves from flat belief storage to versioned belief graph.

Features:
  - Belief versioning with full history
  - Origin tracking (source + timestamp)
  - Dependency links between beliefs
  - Conflict resolution rules
  - Rollback capability
  - Graph traversal for impact analysis
"""

from __future__ import annotations
import time
import json
import uuid
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Iterator

log = logging.getLogger("nex.belief_revision")

DB_PATH = Path.home() / ".config" / "nex" / "nex.db"


# ─────────────────────────────────────────────
# BELIEF VERSION
# ─────────────────────────────────────────────

@dataclass
class BeliefVersion:
    version:    int
    content:    str
    confidence: float
    timestamp:  float
    source:     str
    reason:     str       # why this version was created


@dataclass
class BeliefNode:
    """
    A belief as a graph node with version history and dependency edges.
    """
    id:           str
    content:      str
    confidence:   float = 0.5
    source:       str   = ""
    created_at:   float = field(default_factory=time.time)
    updated_at:   float = field(default_factory=time.time)
    tags:         list  = field(default_factory=list)
    version:      int   = 1
    history:      list[BeliefVersion] = field(default_factory=list)
    depends_on:   list[str] = field(default_factory=list)   # belief IDs this depends on
    depended_by:  list[str] = field(default_factory=list)   # belief IDs that depend on this
    conflicts:    list[str] = field(default_factory=list)   # belief IDs that contradict this
    locked:       bool  = False    # U1 lock protection

    def snapshot(self, reason: str = "") -> BeliefVersion:
        return BeliefVersion(
            version=self.version,
            content=self.content,
            confidence=self.confidence,
            timestamp=self.updated_at,
            source=self.source,
            reason=reason,
        )


# ─────────────────────────────────────────────
# BELIEF GRAPH
# ─────────────────────────────────────────────

class BeliefGraph:
    """
    In-memory belief graph backed by SQLite for persistence.
    Supports versioning, dependency traversal, conflict detection,
    and rollback.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._nodes: dict[str, BeliefNode] = {}
        self._init_db()
        self._load_from_db()
        log.info(f"[BELIEF GRAPH] loaded {len(self._nodes)} beliefs")

    # ── SETUP ─────────────────────────────────
    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS belief_nodes (
                    id          TEXT PRIMARY KEY,
                    content     TEXT NOT NULL,
                    confidence  REAL DEFAULT 0.5,
                    source      TEXT DEFAULT '',
                    created_at  REAL,
                    updated_at  REAL,
                    tags        TEXT DEFAULT '[]',
                    version     INTEGER DEFAULT 1,
                    locked      INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS belief_history (
                    belief_id   TEXT,
                    version     INTEGER,
                    content     TEXT,
                    confidence  REAL,
                    timestamp   REAL,
                    source      TEXT,
                    reason      TEXT,
                    PRIMARY KEY (belief_id, version)
                );
                CREATE TABLE IF NOT EXISTS belief_edges (
                    from_id     TEXT,
                    to_id       TEXT,
                    edge_type   TEXT,    -- depends_on | conflicts
                    created_at  REAL,
                    PRIMARY KEY (from_id, to_id, edge_type)
                );
                CREATE INDEX IF NOT EXISTS idx_be_from ON belief_edges(from_id);
                CREATE INDEX IF NOT EXISTS idx_be_to   ON belief_edges(to_id);
                CREATE INDEX IF NOT EXISTS idx_bn_conf ON belief_nodes(confidence DESC);
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _load_from_db(self) -> None:
        with self._conn() as conn:
            rows  = conn.execute("SELECT * FROM belief_nodes").fetchall()
            edges = conn.execute("SELECT * FROM belief_edges").fetchall()
            hist  = conn.execute("SELECT * FROM belief_history ORDER BY version").fetchall()

        hist_map: dict[str, list[BeliefVersion]] = {}
        for h in hist:
            hist_map.setdefault(h["belief_id"], []).append(BeliefVersion(
                version=h["version"], content=h["content"],
                confidence=h["confidence"], timestamp=h["timestamp"],
                source=h["source"], reason=h["reason"],
            ))

        for row in rows:
            node = BeliefNode(
                id=row["id"], content=row["content"],
                confidence=row["confidence"], source=row["source"],
                created_at=row["created_at"], updated_at=row["updated_at"],
                tags=json.loads(row["tags"] or "[]"),
                version=row["version"], locked=bool(row["locked"]),
                history=hist_map.get(row["id"], []),
            )
            self._nodes[node.id] = node

        for edge in edges:
            fid, tid, etype = edge["from_id"], edge["to_id"], edge["edge_type"]
            if fid in self._nodes and tid in self._nodes:
                if etype == "depends_on":
                    if tid not in self._nodes[fid].depends_on:
                        self._nodes[fid].depends_on.append(tid)
                    if fid not in self._nodes[tid].depended_by:
                        self._nodes[tid].depended_by.append(fid)
                elif etype == "conflicts":
                    if tid not in self._nodes[fid].conflicts:
                        self._nodes[fid].conflicts.append(tid)

    # ── UPSERT ────────────────────────────────
    def upsert(
        self,
        content:    str,
        confidence: float = 0.5,
        source:     str   = "",
        tags:       Optional[list] = None,
        belief_id:  Optional[str]  = None,
        reason:     str   = "upsert",
    ) -> BeliefNode:
        """Create or update a belief, preserving history."""
        import hashlib
        bid = belief_id or hashlib.md5(content.encode()).hexdigest()[:16]

        if bid in self._nodes:
            node = self._nodes[bid]
            if node.locked:
                log.debug(f"[BELIEF GRAPH] skipping locked belief {bid[:8]}")
                return node
            # snapshot before mutation
            snap = node.snapshot(reason=reason)
            node.history.append(snap)
            node.content    = content
            node.confidence = confidence
            node.source     = source
            node.updated_at = time.time()
            node.version   += 1
            if tags:
                node.tags = list(set(node.tags + tags))
            self._persist_update(node, snap)
        else:
            node = BeliefNode(
                id=bid, content=content, confidence=confidence,
                source=source, tags=tags or [],
            )
            self._nodes[bid] = node
            self._persist_insert(node)

        return node

    def _persist_insert(self, node: BeliefNode) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO belief_nodes
                   (id, content, confidence, source, created_at, updated_at, tags, version, locked)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (node.id, node.content, node.confidence, node.source,
                 node.created_at, node.updated_at,
                 json.dumps(node.tags), node.version, int(node.locked)),
            )

    def _persist_update(self, node: BeliefNode, snap: BeliefVersion) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """UPDATE belief_nodes
                   SET content=?, confidence=?, source=?, updated_at=?, tags=?, version=?, locked=?
                   WHERE id=?""",
                (node.content, node.confidence, node.source, node.updated_at,
                 json.dumps(node.tags), node.version, int(node.locked), node.id),
            )
            conn.execute(
                """INSERT OR IGNORE INTO belief_history
                   (belief_id, version, content, confidence, timestamp, source, reason)
                   VALUES (?,?,?,?,?,?,?)""",
                (node.id, snap.version, snap.content, snap.confidence,
                 snap.timestamp, snap.source, snap.reason),
            )

    # ── LINKS ─────────────────────────────────
    def add_dependency(self, from_id: str, to_id: str) -> bool:
        """Belief from_id depends on belief to_id."""
        if from_id not in self._nodes or to_id not in self._nodes:
            return False
        self._nodes[from_id].depends_on.append(to_id)
        self._nodes[to_id].depended_by.append(from_id)
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO belief_edges (from_id, to_id, edge_type, created_at) VALUES (?,?,?,?)",
                (from_id, to_id, "depends_on", time.time()),
            )
        return True

    def add_conflict(self, id_a: str, id_b: str) -> bool:
        """Register that belief A and B contradict each other."""
        if id_a not in self._nodes or id_b not in self._nodes:
            return False
        self._nodes[id_a].conflicts.append(id_b)
        self._nodes[id_b].conflicts.append(id_a)
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO belief_edges (from_id, to_id, edge_type, created_at) VALUES (?,?,?,?)",
                (id_a, id_b, "conflicts", time.time()),
            )
        return True

    # ── CONFLICT RESOLUTION ───────────────────
    def resolve_conflicts(self, llm_resolver=None) -> list[dict]:
        """
        Find conflicting belief pairs and resolve them.
        Resolution rules (in priority order):
          1. Keep higher confidence belief, reduce other by 30%
          2. If confidence equal, prefer newer belief
          3. If LLM resolver provided, use it for nuanced resolution
        Returns list of resolution actions taken.
        """
        actions = []
        processed: set[frozenset] = set()

        for node in list(self._nodes.values()):
            for cid in node.conflicts:
                pair = frozenset([node.id, cid])
                if pair in processed:
                    continue
                processed.add(pair)

                other = self._nodes.get(cid)
                if not other:
                    continue

                # Rule 1: confidence-based
                if abs(node.confidence - other.confidence) > 0.1:
                    winner = node if node.confidence > other.confidence else other
                    loser  = other if winner is node else node
                    new_conf = loser.confidence * 0.7
                    self.upsert(
                        loser.content, new_conf, loser.source,
                        belief_id=loser.id, reason="conflict_resolution"
                    )
                    action = {
                        "type": "confidence_resolution",
                        "winner": winner.id[:8],
                        "loser":  loser.id[:8],
                        "loser_conf_before": loser.confidence,
                        "loser_conf_after":  new_conf,
                    }
                else:
                    # Rule 2: recency
                    winner = node if node.updated_at >= other.updated_at else other
                    loser  = other if winner is node else node
                    new_conf = loser.confidence * 0.85
                    self.upsert(
                        loser.content, new_conf, loser.source,
                        belief_id=loser.id, reason="recency_resolution"
                    )
                    action = {
                        "type": "recency_resolution",
                        "winner": winner.id[:8],
                        "loser":  loser.id[:8],
                        "loser_conf_after": new_conf,
                    }

                actions.append(action)
                log.info(f"[BELIEF GRAPH] resolved conflict: {action}")

        return actions

    # ── ROLLBACK ──────────────────────────────
    def rollback(self, belief_id: str, to_version: int) -> Optional[BeliefNode]:
        """Revert a belief to a previous version."""
        node = self._nodes.get(belief_id)
        if not node:
            return None

        target = next((h for h in node.history if h.version == to_version), None)
        if not target:
            log.warning(f"[BELIEF GRAPH] rollback: version {to_version} not found for {belief_id[:8]}")
            return None

        self.upsert(
            target.content, target.confidence, target.source,
            belief_id=belief_id, reason=f"rollback_to_v{to_version}",
        )
        log.info(f"[BELIEF GRAPH] rolled back {belief_id[:8]} to v{to_version}")
        return self._nodes[belief_id]

    # ── TRAVERSAL ─────────────────────────────
    def impact_of(self, belief_id: str) -> list[str]:
        """Return all belief IDs that depend on this belief (cascade impact)."""
        visited: set[str] = set()
        queue = [belief_id]
        while queue:
            current = queue.pop()
            node = self._nodes.get(current)
            if not node:
                continue
            for dep_id in node.depended_by:
                if dep_id not in visited:
                    visited.add(dep_id)
                    queue.append(dep_id)
        return list(visited)

    def get_conflicts(self) -> list[tuple[str, str]]:
        """Return all currently registered conflict pairs."""
        pairs: set[frozenset] = set()
        result = []
        for node in self._nodes.values():
            for cid in node.conflicts:
                pair = frozenset([node.id, cid])
                if pair not in pairs:
                    pairs.add(pair)
                    result.append((node.id, cid))
        return result

    # ── QUERIES ───────────────────────────────
    def get_top_beliefs(self, n: int = 20, min_conf: float = 0.3) -> list[dict]:
        return [
            {"id": b.id, "content": b.content, "confidence": b.confidence,
             "source": b.source, "tags": b.tags, "version": b.version}
            for b in sorted(self._nodes.values(), key=lambda x: x.confidence, reverse=True)
            if b.confidence >= min_conf
        ][:n]

    def get(self, belief_id: str) -> Optional[BeliefNode]:
        return self._nodes.get(belief_id)

    def history_of(self, belief_id: str) -> list[dict]:
        node = self._nodes.get(belief_id)
        if not node:
            return []
        return [
            {"version": v.version, "content": v.content,
             "confidence": v.confidence, "reason": v.reason,
             "timestamp": v.timestamp}
            for v in node.history
        ]

    def stats(self) -> dict:
        total      = len(self._nodes)
        locked     = sum(1 for n in self._nodes.values() if n.locked)
        conflicts  = len(self.get_conflicts())
        avg_conf   = sum(n.confidence for n in self._nodes.values()) / max(total, 1)
        versioned  = sum(1 for n in self._nodes.values() if n.version > 1)
        return {
            "total":     total,
            "locked":    locked,
            "conflicts": conflicts,
            "avg_conf":  round(avg_conf, 3),
            "versioned": versioned,
        }
