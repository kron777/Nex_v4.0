"""
nex_maintenance.py — Database maintenance for Nex v1.2
=======================================================
Drop into ~/Desktop/nex/nex/

Keeps the database lean without touching beliefs.

Caps:
  - conversations  → keep last 5,000 (oldest pruned)
  - reflections    → keep last 1,000 (oldest pruned)
  - curiosity_crawled → keep last 500 topics (oldest pruned)
  - agent_beliefs  → already capped at 20/agent in nex_memory.py

Beliefs are never pruned — they are her knowledge.

Runs automatically during REFLECT phase every 24h.
Also callable manually: python3 -m nex.nex_maintenance

Wire into run.py:
  from nex.nex_maintenance import Maintenance
  maintenance = Maintenance(db)

  # In REFLECT phase:
  maintenance.maybe_run()
"""

import logging
import os
import time

logger = logging.getLogger("nex.maintenance")

# ─────────────────────────────────────────────────────────────────────────────
# Caps
# ─────────────────────────────────────────────────────────────────────────────

CAPS = {
    "conversations":       5000,
    "reflections":         1000,
    "curiosity_crawled":   500,
}

MAINTENANCE_INTERVAL = 86400   # run once per 24h


class Maintenance:

    def __init__(self, db):
        self.db = db
        self._last_run = 0.0

    def maybe_run(self) -> dict:
        """Call from REFLECT phase. Runs at most once per 24h."""
        if (time.time() - self._last_run) < MAINTENANCE_INTERVAL:
            return {}
        return self.run()

    def run(self) -> dict:
        report = {}
        with self.db.conn() as con:

            # ── Conversations — keep last 5,000 ──────────────────────────────
            count = con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            if count > CAPS["conversations"]:
                excess = count - CAPS["conversations"]
                con.execute("""
                    DELETE FROM conversations WHERE id IN (
                        SELECT id FROM conversations
                        ORDER BY timestamp ASC
                        LIMIT ?
                    )
                """, (excess,))
                report["conversations_pruned"] = excess
                logger.info(f"[maintenance] pruned {excess} conversations")

            # ── Reflections — keep last 1,000 ────────────────────────────────
            count = con.execute("SELECT COUNT(*) FROM reflections").fetchone()[0]
            if count > CAPS["reflections"]:
                excess = count - CAPS["reflections"]
                con.execute("""
                    DELETE FROM reflections WHERE id IN (
                        SELECT id FROM reflections
                        ORDER BY timestamp ASC
                        LIMIT ?
                    )
                """, (excess,))
                report["reflections_pruned"] = excess
                logger.info(f"[maintenance] pruned {excess} reflections")

            # ── Curiosity crawled — keep last 500 ────────────────────────────
            count = con.execute("SELECT COUNT(*) FROM curiosity_crawled").fetchone()[0]
            if count > CAPS["curiosity_crawled"]:
                excess = count - CAPS["curiosity_crawled"]
                con.execute("""
                    DELETE FROM curiosity_crawled WHERE topic IN (
                        SELECT topic FROM curiosity_crawled
                        ORDER BY crawled_at ASC
                        LIMIT ?
                    )
                """, (excess,))
                report["crawled_pruned"] = excess
                logger.info(f"[maintenance] pruned {excess} old crawl records")

            # ── VACUUM — reclaim freed space ──────────────────────────────────
            if report:
                con.execute("VACUUM")
                logger.info("[maintenance] VACUUM complete")

        # Report belief count for visibility — never pruned
        belief_row = self.db.get("SELECT COUNT(*) as c FROM beliefs")
        report["beliefs_total"] = belief_row["c"] if belief_row else 0
        report["beliefs_pruned"] = 0   # always 0 — beliefs are never touched

        self._last_run = time.time()

        if report:
            logger.info(f"[maintenance] complete: {report}")
        return report


# ─────────────────────────────────────────────────────────────────────────────
# run.py integration — 2 lines
# ─────────────────────────────────────────────────────────────────────────────
#
# 1. Import + init:
#       from nex.nex_maintenance import Maintenance
#       maintenance = Maintenance(db)
#
# 2. In REFLECT phase, after depth engine:
#       try:
#           maint_report = maintenance.maybe_run()
#           if maint_report:
#               print(f"  [maintenance] {maint_report}")
#       except Exception: pass
#
# ─────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from nex.nex_db import NexDB
    db = NexDB()
    m = Maintenance(db)
    report = m.run()
    print("Maintenance report:", report)
