"""
NEX TOOL GOVERNANCE + WORLD MODEL — Upgrades 10 & 11

TOOL GOVERNANCE (10):
  - Validates all actions before execution
  - Risk scoring per action type + platform
  - Rollback / undo log for external actions
  - Hard blocks for dangerous patterns

WORLD MODEL (11):
  - Internal representation of platforms, agents, topics
  - Tracks cause → effect relationships
  - Prediction vs reality scoring
  - Feeds into Attention relevance scoring
"""

from __future__ import annotations
import time
import json
import uuid
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.governance_world")

DB_PATH = Path.home() / ".config" / "nex" / "nex.db"


# ═════════════════════════════════════════════
# TOOL GOVERNANCE (Upgrade 10)
# ═════════════════════════════════════════════

# Risk baselines per action type
ACTION_RISK_BASELINE = {
    "internal":  0.05,
    "reply":     0.20,
    "post":      0.35,
    "dm":        0.40,
    "follow":    0.15,
    "unfollow":  0.15,
    "delete":    0.50,
    "unknown":   0.60,
}

# Platform risk multipliers
PLATFORM_RISK_MULTIPLIER = {
    "discord":  1.0,
    "telegram": 0.9,
    "mastodon": 1.2,
    "twitter":  1.3,
    "reddit":   1.4,
    "internal": 0.5,
}

# Hard-block patterns in content
HARD_BLOCK_PATTERNS = [
    "delete all",
    "rm -rf",
    "drop table",
    "format c",
    "shutdown",
    "wallet",
    "password",
    "send money",
    "wire transfer",
]


@dataclass
class ActionRecord:
    """Log entry for every external action attempted."""
    id:           str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    action_type:  str   = ""
    platform:     str   = ""
    content:      str   = ""
    risk_score:   float = 0.0
    approved:     bool  = False
    blocked_by:   str   = ""
    executed:     bool  = False
    result:       str   = ""
    timestamp:    float = field(default_factory=time.time)
    undo_fn:      Optional[Callable] = field(default=None, repr=False)  # rollback callable
    undone:       bool  = False


class GovernanceLayer:
    """
    Validates ActionIntent objects before execution.
    Logs all attempts. Provides rollback interface.
    """

    def __init__(
        self,
        db_path:           Path  = DB_PATH,
        max_risk:          float = 0.70,
        max_posts_per_hour: int  = 10,
    ):
        self.db_path            = db_path
        self.max_risk           = max_risk
        self.max_posts_per_hour = max_posts_per_hour
        self._log: list[ActionRecord] = []
        self._init_db()
        log.info(f"[GOVERNANCE] initialized max_risk={max_risk}")

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS action_log (
                    id           TEXT PRIMARY KEY,
                    action_type  TEXT,
                    platform     TEXT,
                    content      TEXT,
                    risk_score   REAL,
                    approved     INTEGER,
                    blocked_by   TEXT,
                    executed     INTEGER DEFAULT 0,
                    result       TEXT,
                    timestamp    REAL,
                    undone       INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_alog_ts ON action_log(timestamp DESC);
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    # ── VALIDATION ────────────────────────────
    def validate(self, intent) -> "ActionIntent_compatible":
        """
        Validates and enriches an ActionIntent-compatible object.
        Sets .approved and .risk_score.
        """
        content     = getattr(intent, "content", "") or ""
        action_type = getattr(intent, "action_type", "unknown") or "unknown"
        platform    = getattr(intent, "platform", "internal") or "internal"

        # compute risk
        risk  = self._compute_risk(action_type, platform, content)
        intent.risk_score = risk

        # hard block check
        block_reason = self._hard_block_check(content)
        if block_reason:
            intent.approved = False
            self._record(intent, approved=False, blocked_by=f"hard_block:{block_reason}")
            log.warning(f"[GOVERNANCE] HARD BLOCK — {block_reason}")
            return intent

        # rate limit
        if self._rate_limited(platform):
            intent.approved = False
            self._record(intent, approved=False, blocked_by="rate_limit")
            log.warning(f"[GOVERNANCE] rate limited on {platform}")
            return intent

        # risk threshold
        if risk > self.max_risk:
            intent.approved = False
            self._record(intent, approved=False, blocked_by=f"risk>{self.max_risk:.2f}")
            log.warning(f"[GOVERNANCE] blocked risk={risk:.2f} > {self.max_risk:.2f}")
            return intent

        intent.approved = True
        self._record(intent, approved=True, blocked_by="")
        log.debug(f"[GOVERNANCE] approved {action_type}/{platform} risk={risk:.2f}")
        return intent

    def _compute_risk(self, action_type: str, platform: str, content: str) -> float:
        base       = ACTION_RISK_BASELINE.get(action_type, 0.60)
        multiplier = PLATFORM_RISK_MULTIPLIER.get(platform, 1.0)
        # length penalty: very long posts are riskier
        length_factor = min(1.5, 1.0 + len(content) / 2000)
        return min(1.0, base * multiplier * length_factor)

    def _hard_block_check(self, content: str) -> Optional[str]:
        lower = content.lower()
        for pattern in HARD_BLOCK_PATTERNS:
            if pattern in lower:
                return pattern
        return None

    def _rate_limited(self, platform: str) -> bool:
        cutoff = time.time() - 3600
        recent = sum(
            1 for r in self._log
            if r.platform == platform and r.executed and r.timestamp > cutoff
        )
        return recent >= self.max_posts_per_hour

    # ── LOGGING ───────────────────────────────
    def _record(self, intent, approved: bool, blocked_by: str) -> ActionRecord:
        rec = ActionRecord(
            action_type=getattr(intent, "action_type", ""),
            platform=getattr(intent, "platform", ""),
            content=(getattr(intent, "content", "") or "")[:500],
            risk_score=getattr(intent, "risk_score", 0.0),
            approved=approved,
            blocked_by=blocked_by,
        )
        self._log.append(rec)
        if len(self._log) > 1000:
            self._log = self._log[-1000:]

        # persist
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO action_log
                   (id, action_type, platform, content, risk_score, approved, blocked_by, timestamp)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (rec.id, rec.action_type, rec.platform, rec.content,
                 rec.risk_score, int(rec.approved), rec.blocked_by, rec.timestamp),
            )
        return rec

    def mark_executed(self, action_id: str, result: str = "", undo_fn: Callable = None) -> None:
        """Call after successful execution to enable rollback."""
        for rec in reversed(self._log):
            if rec.id == action_id:
                rec.executed = True
                rec.result   = result
                rec.undo_fn  = undo_fn
                with self._conn() as conn:
                    conn.execute(
                        "UPDATE action_log SET executed=1, result=? WHERE id=?",
                        (result, action_id),
                    )
                return

    # ── ROLLBACK ──────────────────────────────
    def rollback_last(self, platform: str = None) -> Optional[str]:
        """Undo the most recent executed action on a platform."""
        candidates = [
            r for r in reversed(self._log)
            if r.executed and not r.undone
            and (platform is None or r.platform == platform)
        ]
        if not candidates:
            return None

        target = candidates[0]
        if target.undo_fn:
            try:
                target.undo_fn()
                target.undone = True
                with self._conn() as conn:
                    conn.execute("UPDATE action_log SET undone=1 WHERE id=?", (target.id,))
                log.info(f"[GOVERNANCE] rolled back {target.action_type} on {target.platform}")
                return target.id
            except Exception as e:
                log.error(f"[GOVERNANCE] rollback failed: {e}")
                return None
        else:
            log.warning(f"[GOVERNANCE] no undo_fn registered for {target.id}")
            return None

    def stats(self) -> dict:
        approved = sum(1 for r in self._log if r.approved)
        blocked  = sum(1 for r in self._log if not r.approved)
        executed = sum(1 for r in self._log if r.executed)
        return {
            "total":    len(self._log),
            "approved": approved,
            "blocked":  blocked,
            "executed": executed,
            "undone":   sum(1 for r in self._log if r.undone),
        }


# ═════════════════════════════════════════════
# WORLD MODEL (Upgrade 11)
# ═════════════════════════════════════════════

@dataclass
class WorldEntity:
    """A tracked entity in NEX's world model."""
    id:          str
    entity_type: str    # platform / agent / topic
    name:        str
    properties:  dict   = field(default_factory=dict)
    created_at:  float  = field(default_factory=time.time)
    updated_at:  float  = field(default_factory=time.time)
    trust:       float  = 0.5
    salience:    float  = 0.5   # how active/relevant this entity is right now


@dataclass
class CausalLink:
    """A recorded cause→effect relationship."""
    id:          str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    cause:       str   = ""    # action / event description
    effect:      str   = ""    # observed outcome
    confidence:  float = 0.5
    confirmed:   int   = 0     # number of times confirmed
    created_at:  float = field(default_factory=time.time)


@dataclass
class Prediction:
    """A forward prediction: if X then Y."""
    id:          str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    condition:   str   = ""
    prediction:  str   = ""
    made_at:     float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    was_correct: Optional[bool]  = None
    accuracy:    float = 0.5


class WorldModel:
    """
    NEX's internal model of the world.
    Tracks:
      - platforms (status, engagement stats)
      - agents (trust, track record)
      - topics (salience, recent activity)
      - causal links (cause → effect)
      - predictions (expected → actual)
    """

    def __init__(self):
        self._entities: dict[str, WorldEntity] = {}
        self._causal:   list[CausalLink]       = []
        self._predictions: list[Prediction]    = []
        self._init_defaults()
        log.info("[WORLD MODEL] initialized")

    def _init_defaults(self) -> None:
        """Seed known platforms and initial world state."""
        for platform in ["discord", "telegram", "mastodon", "youtube", "moltbook"]:
            self.update_entity(
                entity_id=f"platform:{platform}",
                entity_type="platform",
                name=platform,
                properties={"status": "unknown", "last_post": None, "engagement": 0},
                trust=0.8,
            )

    # ── ENTITY MANAGEMENT ─────────────────────
    def update_entity(
        self,
        entity_id:   str,
        entity_type: str,
        name:        str,
        properties:  dict  = None,
        trust:       float = None,
        salience:    float = None,
    ) -> WorldEntity:
        existing = self._entities.get(entity_id)
        if existing:
            existing.updated_at = time.time()
            if properties:
                existing.properties.update(properties)
            if trust is not None:
                existing.trust = max(0.0, min(1.0, trust))
            if salience is not None:
                existing.salience = max(0.0, min(1.0, salience))
            return existing
        else:
            entity = WorldEntity(
                id=entity_id, entity_type=entity_type, name=name,
                properties=properties or {},
                trust=trust if trust is not None else 0.5,
                salience=salience if salience is not None else 0.5,
            )
            self._entities[entity_id] = entity
            return entity

    def get_entity(self, entity_id: str) -> Optional[WorldEntity]:
        return self._entities.get(entity_id)

    def get_by_type(self, entity_type: str) -> list[WorldEntity]:
        return [e for e in self._entities.values() if e.entity_type == entity_type]

    # ── CAUSAL TRACKING ───────────────────────
    def record_cause_effect(self, cause: str, effect: str, confidence: float = 0.5) -> CausalLink:
        # check if we've seen this before
        existing = next(
            (c for c in self._causal
             if c.cause.lower() == cause.lower() and c.effect.lower() == effect.lower()),
            None,
        )
        if existing:
            existing.confirmed   += 1
            existing.confidence  = min(1.0, existing.confidence + 0.05)
            log.debug(f"[WORLD] confirmed causal: {cause[:40]} → {effect[:40]}")
            return existing

        link = CausalLink(cause=cause, effect=effect, confidence=confidence)
        self._causal.append(link)
        if len(self._causal) > 500:
            # prune lowest confidence
            self._causal.sort(key=lambda c: c.confidence, reverse=True)
            self._causal = self._causal[:400]
        log.info(f"[WORLD] new causal link: {cause[:40]} → {effect[:40]}")
        return link

    def predict(self, condition: str, prediction: str) -> Prediction:
        p = Prediction(condition=condition, prediction=prediction)
        self._predictions.append(p)
        return p

    def resolve_prediction(self, prediction_id: str, was_correct: bool) -> Optional[Prediction]:
        pred = next((p for p in self._predictions if p.id == prediction_id), None)
        if not pred:
            return None
        pred.resolved_at = time.time()
        pred.was_correct = was_correct
        pred.accuracy    = 1.0 if was_correct else 0.0
        log.info(f"[WORLD] prediction {prediction_id[:8]} resolved: correct={was_correct}")
        return pred

    def prediction_accuracy(self) -> float:
        resolved = [p for p in self._predictions if p.resolved_at is not None]
        if not resolved:
            return 0.5
        return sum(1 for p in resolved if p.was_correct) / len(resolved)

    # ── SALIENCE DECAY ────────────────────────
    def decay_salience(self, decay_rate: float = 0.02) -> None:
        """Topics and agents become less salient over time without activity."""
        for entity in self._entities.values():
            if entity.entity_type in ("topic", "agent"):
                entity.salience = max(0.0, entity.salience - decay_rate)

    # ── QUERIES ───────────────────────────────
    def salient_topics(self, top_n: int = 5) -> list[str]:
        topics = [e for e in self._entities.values() if e.entity_type == "topic"]
        topics.sort(key=lambda e: e.salience, reverse=True)
        return [t.name for t in topics[:top_n]]

    def trusted_agents(self, min_trust: float = 0.6) -> list[WorldEntity]:
        return [
            e for e in self._entities.values()
            if e.entity_type == "agent" and e.trust >= min_trust
        ]

    def stats(self) -> dict:
        by_type: dict[str, int] = {}
        for e in self._entities.values():
            by_type[e.entity_type] = by_type.get(e.entity_type, 0) + 1
        return {
            "entities":          by_type,
            "causal_links":      len(self._causal),
            "predictions":       len(self._predictions),
            "prediction_accuracy": round(self.prediction_accuracy(), 3),
        }
