"""
nex_belief_survival.py — Upgraded BeliefSurvival Engine
========================================================
From the live terminal:
    [BeliefSurvival] cycle: 1068 decayed | 10 amplified | 50 killed
    [BELIEF] [Survival] killed 50 | amplified 10

Current system: kills low-confidence beliefs, amplifies high-confidence ones.
Simple threshold pruning.

This upgrade adds four survival pressures:

1. CONFIDENCE DECAY (existing, preserved)
   Beliefs decay toward 0 each cycle. Low-confidence beliefs die.

2. TENSION-WEIGHTED PRESERVATION (NEW)
   A belief that's in active tension with other beliefs (semantically unique
   or contradictory) gets a survival bonus. Minority positions worth keeping.
   Source: nex_tension_pressure.py survival_weight()

3. WASSERSTEIN PRUNING (NEW)
   Pairs of beliefs that are too similar (W₂ distance < threshold) get one
   member culled — the one with lower confidence. Deduplicates the corpus.
   Source: nex_hebbian_plasticity.py BeliefDistribution

4. AMPLIFICATION BY USE (NEW)
   Beliefs that co-activated in recent replies (tracked via Hebbian edges)
   get amplified. The system literally promotes beliefs it uses.
   Source: nex_hebbian_plasticity.py edge weights

5. KNOWLEDGE GAP PRESERVATION (NEW)
   Beliefs that sit on topic boundaries (belong to multiple clusters) are
   preserved even at lower confidence — they bridge knowledge domains.
   Source: nex_hyperedge_fabric.py cluster membership

Architecture position: runs at end of cognition_tick, after tension scoring.
Produces the [BELIEF] [Survival] log line seen in nex_brain.
"""

import math
import time
import sqlite3
import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

logger = logging.getLogger("nex.belief_survival")


# ── Configuration ─────────────────────────────────────────────────────────────
DECAY_PER_CYCLE       = 0.005   # confidence decay each cycle
KILL_THRESHOLD        = 0.15    # beliefs below this confidence get killed
AMPLIFY_THRESHOLD     = 0.80    # beliefs above this get amplified
AMPLIFY_AMOUNT        = 0.02    # confidence boost on amplification
SIMILARITY_PRUNE_DIST = 0.08    # W₂ below this = duplicate → prune weaker
BRIDGE_CLUSTER_MIN    = 2       # min clusters to qualify as bridge belief
MAX_KILL_PER_CYCLE    = 50      # matches live system cap
MAX_AMPLIFY_PER_CYCLE = 10      # matches live system cap


# ── Safe imports of sibling modules ───────────────────────────────────────────

def _try_import(module: str, attr: str):
    try:
        import importlib
        return getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError):
        return None

_survival_weight  = _try_import("nex_tension_pressure",   "survival_weight")
_get_hebbian      = _try_import("nex_hebbian_plasticity",  "get_engine")
_get_fabric       = _try_import("nex_hyperedge_fabric",    "get_fabric")
_get_dist         = _try_import("nex_hebbian_plasticity",  "get_confidence_dist")
_w2_beta          = _try_import("nex_hebbian_plasticity",  "wasserstein2_beta")


# ── Belief record ─────────────────────────────────────────────────────────────

@dataclass
class BeliefRecord:
    belief_id:   str
    content:     str
    topic:       str
    confidence:  float
    use_count:   int   = 0
    last_used:   float = 0.0
    belief_links: list = field(default_factory=list)


@dataclass
class SurvivalResult:
    """Output of one survival cycle."""
    cycle:       int
    decayed:     int
    amplified:   int
    killed:      int
    duplicates_pruned: int
    bridge_preserved:  int
    surviving:   int
    killed_ids:  list[str]
    amplified_ids: list[str]

    def log_line(self) -> str:
        return (f"[BeliefSurvival] cycle: {self.decayed} decayed | "
                f"{self.amplified} amplified | {self.killed} killed | "
                f"{self.duplicates_pruned} dupes pruned | "
                f"{self.bridge_preserved} bridges preserved")


# ── Survival engine ───────────────────────────────────────────────────────────

class BeliefSurvivalEngine:
    """
    Upgraded BeliefSurvival with tension-weighting, Wasserstein dedup,
    use-based amplification, and bridge preservation.
    """

    def __init__(self):
        self._cycle = 0

    def run_cycle(self, beliefs: list[BeliefRecord]) -> SurvivalResult:
        """
        Run one survival cycle over a list of BeliefRecords.
        Returns SurvivalResult with kill/amplify lists.

        In nex_v72 integration: beliefs come from DB query,
        and results drive DB updates (confidence writes + deletes).
        """
        self._cycle += 1

        # ── Gather external signals ───────────────────────────────────────────
        hebbian_engine = _get_hebbian() if _get_hebbian else None
        fabric         = _get_fabric()  if _get_fabric  else None

        # Build Hebbian use-strength map: belief_id → max edge weight out
        hebb_strength: dict[str, float] = {}
        if hebbian_engine:
            for bid_from, neighbours in hebbian_engine._adjacency.items():
                max_w = max(
                    (hebbian_engine.get_edge_weight(bid_from, bn) for bn in neighbours),
                    default=1.0,
                )
                hebb_strength[bid_from] = max_w

        # Bridge beliefs: in multiple clusters
        bridge_beliefs: set[str] = set()
        if fabric:
            for bid in [b.belief_id for b in beliefs]:
                clusters = fabric.get_belief_clusters(bid)
                if len(clusters) >= BRIDGE_CLUSTER_MIN:
                    bridge_beliefs.add(bid)

        # ── Score each belief ─────────────────────────────────────────────────
        scored = []
        for belief in beliefs:
            bid = belief.belief_id
            conf = belief.confidence

            # 1. Base decay
            conf -= DECAY_PER_CYCLE

            # 2. Tension survival bonus
            if _survival_weight:
                mult = _survival_weight(bid, conf)
                conf *= mult

            # 3. Hebbian use amplification
            hebb_w = hebb_strength.get(bid, 1.0)
            if hebb_w > 2.0:
                # Frequently co-activated → amplify
                conf += AMPLIFY_AMOUNT * ((hebb_w - 1.0) / 4.0)

            # 4. Bridge preservation floor
            if bid in bridge_beliefs:
                conf = max(conf, KILL_THRESHOLD + 0.05)

            conf = max(0.0, min(1.0, conf))
            scored.append((belief, conf))

        # ── Wasserstein deduplication ─────────────────────────────────────────
        duplicates_pruned = 0
        if _get_dist and _w2_beta and len(beliefs) > 1:
            # Check all pairs — O(n²) but capped at MAX_KILL_PER_CYCLE dedupes
            killed_set: set[str] = set()
            for i in range(len(scored)):
                if len(killed_set) >= MAX_KILL_PER_CYCLE // 2:
                    break
                b_i, c_i = scored[i]
                if b_i.belief_id in killed_set:
                    continue
                if b_i.topic == "":
                    continue
                for j in range(i+1, len(scored)):
                    b_j, c_j = scored[j]
                    if b_j.belief_id in killed_set:
                        continue
                    # Only check same-topic beliefs (same topic = may be dupe)
                    if b_i.topic != b_j.topic:
                        continue
                    try:
                        d_i = _get_dist(b_i.belief_id, c_i)
                        d_j = _get_dist(b_j.belief_id, c_j)
                        w2  = _w2_beta(d_i, d_j)
                        if w2 < SIMILARITY_PRUNE_DIST:
                            # Duplicate — kill the weaker one
                            weaker = b_i.belief_id if c_i < c_j else b_j.belief_id
                            if weaker not in bridge_beliefs:
                                killed_set.add(weaker)
                                duplicates_pruned += 1
                    except Exception:
                        continue

            # Apply dedup kills to scored list
            scored = [(b, c) for b, c in scored
                      if b.belief_id not in killed_set]

        # ── Kill / amplify decisions ──────────────────────────────────────────
        killed_ids:    list[str] = []
        amplified_ids: list[str] = []
        decayed = 0
        bridge_preserved = 0

        surviving_scored = []
        for belief, conf in scored:
            bid = belief.belief_id

            if conf < KILL_THRESHOLD and len(killed_ids) < MAX_KILL_PER_CYCLE:
                if bid not in bridge_beliefs:
                    killed_ids.append(bid)
                    continue
                else:
                    bridge_preserved += 1
                    conf = KILL_THRESHOLD + 0.01  # floor for bridges

            if conf > AMPLIFY_THRESHOLD and len(amplified_ids) < MAX_AMPLIFY_PER_CYCLE:
                conf = min(1.0, conf + AMPLIFY_AMOUNT)
                amplified_ids.append(bid)

            if conf != belief.confidence:
                decayed += 1

            belief.confidence = conf
            surviving_scored.append((belief, conf))

        result = SurvivalResult(
            cycle=self._cycle,
            decayed=decayed,
            amplified=len(amplified_ids),
            killed=len(killed_ids),
            duplicates_pruned=duplicates_pruned,
            bridge_preserved=bridge_preserved,
            surviving=len(surviving_scored),
            killed_ids=killed_ids,
            amplified_ids=amplified_ids,
        )

        logger.info(result.log_line())
        return result

    def run_cycle_from_db(self, db_path: str) -> Optional[SurvivalResult]:
        """
        Full cycle against live DB.
        Reads beliefs, runs survival, writes back confidence deltas and kills.
        """
        import os
        if not os.path.exists(db_path):
            logger.warning("[BeliefSurvival] DB not found: %s", db_path)
            return None

        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            cur.execute("""
                SELECT id, content, topic, confidence, belief_links
                FROM beliefs
                WHERE confidence > 0
                ORDER BY confidence ASC
                LIMIT 5000
            """)
            rows = cur.fetchall()

            beliefs = []
            for row in rows:
                bid, content, topic, conf, links_json = row
                beliefs.append(BeliefRecord(
                    belief_id=str(bid),
                    content=content or "",
                    topic=topic or "",
                    confidence=conf or 0.5,
                    belief_links=[] if not links_json else
                                 (links_json if isinstance(links_json, list)
                                  else []),
                ))

            result = self.run_cycle(beliefs)

            # Write back to DB
            if result.killed_ids:
                placeholders = ",".join("?" * len(result.killed_ids))
                cur.execute(
                    f"DELETE FROM beliefs WHERE id IN ({placeholders})",
                    result.killed_ids,
                )

            # Update surviving confidences
            surviving_beliefs = [b for b, _ in
                                  [(b, b.confidence) for b in beliefs
                                   if b.belief_id not in result.killed_ids]]
            for b in surviving_beliefs:
                cur.execute(
                    "UPDATE beliefs SET confidence=? WHERE id=?",
                    (b.confidence, b.belief_id),
                )

            conn.commit()
            conn.close()
            return result

        except Exception as e:
            logger.error("[BeliefSurvival] DB cycle failed: %s", e)
            return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[BeliefSurvivalEngine] = None

def get_survival_engine() -> BeliefSurvivalEngine:
    global _engine
    if _engine is None:
        _engine = BeliefSurvivalEngine()
    return _engine

def run_survival_cycle(beliefs: list[BeliefRecord]) -> SurvivalResult:
    return get_survival_engine().run_cycle(beliefs)

def run_survival_from_db(db_path: str) -> Optional[SurvivalResult]:
    return get_survival_engine().run_cycle_from_db(db_path)


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    engine = BeliefSurvivalEngine()

    # Simulate a belief corpus
    test_beliefs = [
        BeliefRecord("b001", "Consciousness emerges from physical processes", "consciousness", 0.82),
        BeliefRecord("b002", "AI alignment requires careful value specification", "alignment", 0.75),
        BeliefRecord("b003", "Identity is narrative continuity", "identity", 0.70),
        BeliefRecord("b004", "The weather is nice today", "weather", 0.12),  # should die
        BeliefRecord("b005", "Self-awareness is a spectrum", "consciousness", 0.65),
        BeliefRecord("b006", "Learning requires temporal credit assignment", "learning", 0.78),
        BeliefRecord("b007", "Control exists in tension with autonomy", "control", 0.60),
        BeliefRecord("b008", "Consciousness cannot be physically explained", "consciousness", 0.55),
        # Near-duplicate of b002
        BeliefRecord("b009", "AI alignment needs value learning from humans", "alignment", 0.68),
        BeliefRecord("b010", "Another weak belief", "misc", 0.11),  # should die
    ]

    print(f"── BeliefSurvival cycle test — {len(test_beliefs)} beliefs ──")
    result = engine.run_cycle(test_beliefs)
    print(f"\nResult:")
    print(f"  Decayed:    {result.decayed}")
    print(f"  Amplified:  {result.amplified} → {result.amplified_ids}")
    print(f"  Killed:     {result.killed}    → {result.killed_ids}")
    print(f"  Dupes pruned: {result.duplicates_pruned}")
    print(f"  Bridges:    {result.bridge_preserved}")
    print(f"  Surviving:  {result.surviving}")
    print(f"\n  {result.log_line()}")
