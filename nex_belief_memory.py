"""
nex_belief_memory.py — Tiered Belief Memory for NEX
Manages belief access at scale:
  - HOT tier:  top 2000 beliefs in RAM (instant access)
  - WARM tier: top 10000 beliefs in fast lookup (indexed)
  - COLD tier: full DB (millions of beliefs, query on demand)
  - CONTEXT tier: conversation-relevant beliefs (dynamic, per-session)
  
As belief count grows into millions, this ensures NEX always has
the most relevant beliefs in fast memory — not just the most recent.
"""

import sqlite3
import os
import time
import threading
import logging
import json
from collections import OrderedDict
from datetime import datetime

log = logging.getLogger("nex.belief_memory")
DB_PATH = os.path.join(os.path.dirname(__file__), "nex.db")

# ─────────────────────────────────────────────────────────
# LRU CACHE — fast fixed-size belief store
# ─────────────────────────────────────────────────────────

class LRUBeliefCache:
    """Fixed-size LRU cache for beliefs. O(1) get/set."""

    def __init__(self, capacity):
        self.capacity = capacity
        self._cache   = OrderedDict()
        self._lock    = threading.RLock()
        self._hits    = 0
        self._misses  = 0

    def get(self, key):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key]
            self._misses += 1
            return None

    def put(self, key, value):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self.capacity:
                    self._cache.popitem(last=False)
            self._cache[key] = value

    def values(self):
        with self._lock:
            return list(self._cache.values())

    def __len__(self):
        return len(self._cache)

    def hit_rate(self):
        total = self._hits + self._misses
        return round(self._hits / total, 3) if total > 0 else 0.0


# ─────────────────────────────────────────────────────────
# TIERED BELIEF MEMORY MANAGER
# ─────────────────────────────────────────────────────────

class BeliefMemoryManager:
    """
    Three-tier belief memory:
    
    HOT  (2,000)  — highest confidence beliefs, always in RAM
    WARM (10,000) — broad coverage, loaded at startup  
    COLD (∞)      — full DB, queried on demand
    CONTEXT (500) — conversation-relevant, refreshed per exchange
    
    Designed to scale from 10k to 10M beliefs without code changes.
    """

    HOT_SIZE     = 2000
    WARM_SIZE    = 10000
    CONTEXT_SIZE = 500

    def __init__(self):
        self._hot     = LRUBeliefCache(self.HOT_SIZE)
        self._warm    = LRUBeliefCache(self.WARM_SIZE)
        self._context = LRUBeliefCache(self.CONTEXT_SIZE)
        self._lock    = threading.RLock()
        self._stats   = {
            "hot_loads":     0,
            "warm_loads":    0,
            "cold_queries":  0,
            "context_sets":  0,
            "total_beliefs": 0,
        }
        self._last_refresh = 0
        self._refresh_interval = 300  # refresh hot tier every 5 min
        log.info("  [BeliefMemory] 3-tier memory initialised (hot/warm/cold)")

    def load(self):
        """Initial load — populate hot and warm tiers from DB."""
        t0 = time.time()
        try:
            conn = sqlite3.connect(DB_PATH)

            # Count total
            total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
            self._stats["total_beliefs"] = total

            # HOT tier — highest confidence beliefs
            hot_rows = conn.execute(
                "SELECT id, content, topic, confidence, source FROM beliefs "
                "ORDER BY confidence DESC LIMIT ?",
                (self.HOT_SIZE,)
            ).fetchall()
            for row in hot_rows:
                self._hot.put(row[0], self._row_to_dict(row))
            self._stats["hot_loads"] = len(hot_rows)

            # WARM tier — broad topic coverage
            # Get top beliefs per topic to ensure breadth
            topics = conn.execute(
                "SELECT DISTINCT topic FROM beliefs"
            ).fetchall()
            warm_loaded = 0
            per_topic = max(5, self.WARM_SIZE // max(len(topics), 1))
            for (topic,) in topics:
                rows = conn.execute(
                    "SELECT id, content, topic, confidence, source FROM beliefs "
                    "WHERE topic=? ORDER BY confidence DESC LIMIT ?",
                    (topic, per_topic)
                ).fetchall()
                for row in rows:
                    self._warm.put(row[0], self._row_to_dict(row))
                    warm_loaded += 1
                    if warm_loaded >= self.WARM_SIZE:
                        break
                if warm_loaded >= self.WARM_SIZE:
                    break
            self._stats["warm_loads"] = warm_loaded

            conn.close()
            elapsed = round(time.time() - t0, 2)
            log.info(
                f"  [BeliefMemory] loaded — "
                f"total={total} hot={len(self._hot)} warm={len(self._warm)} | {elapsed}s"
            )

        except Exception as e:
            log.error(f"  [BeliefMemory] load error: {e}")

    def refresh_hot(self):
        """Refresh hot tier — call periodically as beliefs evolve."""
        if time.time() - self._last_refresh < self._refresh_interval:
            return
        self._last_refresh = time.time()
        try:
            conn = sqlite3.connect(DB_PATH)
            total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
            self._stats["total_beliefs"] = total
            rows = conn.execute(
                "SELECT id, content, topic, confidence, source FROM beliefs "
                "ORDER BY confidence DESC LIMIT ?",
                (self.HOT_SIZE,)
            ).fetchall()
            for row in rows:
                self._hot.put(row[0], self._row_to_dict(row))
            conn.close()
            log.info(f"  [BeliefMemory] hot tier refreshed — {total} total beliefs")
        except Exception as e:
            log.error(f"  [BeliefMemory] refresh error: {e}")

    def set_context(self, beliefs):
        """
        Set conversation context beliefs.
        Called at the start of each exchange with relevant beliefs.
        """
        self._context = LRUBeliefCache(self.CONTEXT_SIZE)
        for b in beliefs[:self.CONTEXT_SIZE]:
            self._context.put(b.get("id", id(b)), b)
        self._stats["context_sets"] += 1
        log.debug(f"  [BeliefMemory] context set — {len(beliefs)} beliefs")

    def get_context(self):
        """Return current conversation context beliefs."""
        return self._context.values()

    def get_hot(self):
        """Return all hot tier beliefs."""
        return self._hot.values()

    def get_warm(self):
        """Return all warm tier beliefs."""
        return self._warm.values()

    def query_cold(self, topic=None, keyword=None, n=50, min_confidence=0.5):
        """
        Query the full DB directly — cold tier.
        Use when hot/warm tiers don't have what's needed.
        """
        self._stats["cold_queries"] += 1
        try:
            conn = sqlite3.connect(DB_PATH)
            if topic and keyword:
                rows = conn.execute(
                    "SELECT id, content, topic, confidence, source FROM beliefs "
                    "WHERE topic=? AND content LIKE ? AND confidence>=? "
                    "ORDER BY confidence DESC LIMIT ?",
                    (topic, f"%{keyword}%", min_confidence, n)
                ).fetchall()
            elif topic:
                rows = conn.execute(
                    "SELECT id, content, topic, confidence, source FROM beliefs "
                    "WHERE topic=? AND confidence>=? ORDER BY confidence DESC LIMIT ?",
                    (topic, min_confidence, n)
                ).fetchall()
            elif keyword:
                rows = conn.execute(
                    "SELECT id, content, topic, confidence, source FROM beliefs "
                    "WHERE content LIKE ? AND confidence>=? ORDER BY confidence DESC LIMIT ?",
                    (f"%{keyword}%", min_confidence, n)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, content, topic, confidence, source FROM beliefs "
                    "WHERE confidence>=? ORDER BY confidence DESC LIMIT ?",
                    (min_confidence, n)
                ).fetchall()
            conn.close()
            results = [self._row_to_dict(r) for r in rows]
            # Promote to warm tier
            for b in results:
                self._warm.put(b["id"], b)
            return results
        except Exception as e:
            log.error(f"  [BeliefMemory] cold query error: {e}")
            return []

    def get_for_response(self, query_text=None, topic=None, n=60):
        """
        Smart belief retrieval for generating a response.
        Priority: context > hot (topic match) > warm (topic match) > cold
        """
        results = []
        seen_ids = set()

        def add(beliefs, limit):
            for b in beliefs:
                if len(results) >= limit:
                    break
                bid = b.get("id")
                if bid not in seen_ids:
                    results.append(b)
                    seen_ids.add(bid)

        # 1. Context beliefs (most relevant to current conversation)
        add(self.get_context(), n // 3)

        # 2. Hot beliefs filtered by topic
        if topic:
            hot_topic = [b for b in self.get_hot() if b.get("topic") == topic]
            add(hot_topic, n // 3)
        else:
            add(self.get_hot()[:n // 4], n // 4)

        # 3. Warm beliefs filtered by topic
        if topic and len(results) < n:
            warm_topic = [b for b in self.get_warm() if b.get("topic") == topic]
            add(warm_topic, n // 2)

        # 4. Cold query if still not enough
        if len(results) < n // 2 and topic:
            cold = self.query_cold(topic=topic, n=n - len(results))
            add(cold, n)

        return results[:n]

    def promote(self, belief_id, confidence_boost=0.05):
        """Promote a belief's confidence — called when belief is used successfully."""
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "UPDATE beliefs SET confidence = MIN(0.99, confidence + ?) WHERE id=?",
                (confidence_boost, belief_id)
            )
            conn.commit()
            conn.close()
            # Update in cache
            for cache in [self._hot, self._warm, self._context]:
                b = cache.get(belief_id)
                if b:
                    b["confidence"] = min(0.99, b["confidence"] + confidence_boost)
        except Exception as e:
            log.debug(f"  [BeliefMemory] promote error: {e}")

    def demote(self, belief_id, confidence_penalty=0.05):
        """Demote a belief's confidence — called when belief contradicted."""
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "UPDATE beliefs SET confidence = MAX(0.01, confidence - ?) WHERE id=?",
                (confidence_penalty, belief_id)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log.debug(f"  [BeliefMemory] demote error: {e}")

    def status(self):
        total = self._stats["total_beliefs"]
        return {
            "total_in_db":    total,
            "hot_tier":       len(self._hot),
            "warm_tier":      len(self._warm),
            "context_tier":   len(self._context),
            "hot_hit_rate":   self._hot.hit_rate(),
            "warm_hit_rate":  self._warm.hit_rate(),
            "cold_queries":   self._stats["cold_queries"],
            "context_sets":   self._stats["context_sets"],
            "coverage_pct":   round((self.HOT_SIZE + self.WARM_SIZE) / max(total, 1) * 100, 1),
        }

    def _row_to_dict(self, row):
        return {
            "id":         row[0],
            "content":    row[1],
            "topic":      row[2] or "general",
            "confidence": row[3] or 0.5,
            "source":     row[4] or "",
        }

    def report(self):
        s = self.status()
        log.info(
            f"  [BeliefMemory] total={s['total_in_db']} | "
            f"hot={s['hot_tier']} warm={s['warm_tier']} ctx={s['context_tier']} | "
            f"coverage={s['coverage_pct']}% | cold_queries={s['cold_queries']}"
        )
        return s


# ─────────────────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────────────────
_memory = None
_mem_lock = threading.Lock()

def get_memory():
    global _memory
    if _memory is None:
        with _mem_lock:
            if _memory is None:
                _memory = BeliefMemoryManager()
                _memory.load()
    return _memory
