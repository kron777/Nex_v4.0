"""
nex_dream_cycle.py — Offline Dream Consolidation
=================================================
When tension < threshold and system is in low-activity state,
NEX runs a silent "dream" pass:
  1. Compress low-signal beliefs (below confidence floor)
  2. Forge cross-domain bridges from surprise memory
  3. Reinforce high-Phi beliefs
  4. Emit dream summary as a privileged belief

No VRAM cost — runs on CPU, uses stored belief graph.
Inspired by memory consolidation in biological sleep.
"""
from __future__ import annotations
import json, time, logging, threading, sqlite3
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.dream_cycle")

_DB_PATH       = Path.home() / ".config/nex/nex.db"
_DREAM_LOG     = Path.home() / ".config/nex/dream_log.json"
_TENSION_GATE  = 30.0    # only dream when tension below this
_MIN_INTERVAL  = 1800    # minimum seconds between dream cycles (30 min)
_COMPRESS_CONF = 0.35    # beliefs below this get compressed/merged
_MAX_BRIDGES   = 5       # cross-domain bridges per dream cycle


class DreamCycle:
    def __init__(self):
        self._last_dream: float = 0
        self._dream_count: int = 0
        self._lock = threading.Lock()
        self._running = False
        self._load_state()

    def _load_state(self):
        try:
            if _DREAM_LOG.exists():
                data = json.loads(_DREAM_LOG.read_text())
                self._last_dream = data.get("last_dream", 0)
                self._dream_count = data.get("dream_count", 0)
        except Exception:
            pass

    def _save_state(self, summary: str):
        try:
            _DREAM_LOG.write_text(json.dumps({
                "last_dream": self._last_dream,
                "dream_count": self._dream_count,
                "last_summary": summary,
                "timestamp": time.time(),
            }, indent=2))
        except Exception:
            pass

    def should_dream(self, tension: float) -> bool:
        if self._running:
            return False
        if tension > _TENSION_GATE:
            return False
        if time.time() - self._last_dream < _MIN_INTERVAL:
            return False
        return True

    def run(
        self,
        tension: float,
        llm_fn: Optional[Callable] = None,
        belief_store_fn: Optional[Callable] = None,
    ) -> Optional[str]:
        """
        Run one dream cycle. Returns summary string or None if skipped.
        Safe to call every cycle — self-gates on tension and interval.
        """
        if not self.should_dream(tension):
            return None

        with self._lock:
            if self._running:
                return None
            self._running = True

        try:
            log.info(f"[DREAM] Starting dream cycle #{self._dream_count + 1} "
                     f"(tension={tension:.1f})")
            summary_parts = []

            # ── Step 1: Compress low-confidence beliefs ────────
            compressed = self._compress_beliefs()
            if compressed:
                summary_parts.append(f"compressed {compressed} low-signal beliefs")

            # ── Step 2: Cross-domain bridges from surprise memory ──
            bridges = self._forge_bridges(llm_fn)
            if bridges:
                summary_parts.append(f"forged {len(bridges)} cross-domain bridges")

            # ── Step 3: Reinforce high-Phi beliefs ────────────
            reinforced = self._reinforce_integrated()
            if reinforced:
                summary_parts.append(f"reinforced {reinforced} integrated beliefs")

            # ── Step 4: Store dream summary as privileged belief ──
            summary = f"Dream cycle #{self._dream_count + 1}: " + \
                      ("; ".join(summary_parts) if summary_parts else "quiet consolidation")

            if belief_store_fn:
                try:
                    belief_store_fn("dream_consolidation", summary, 0.92)
                except Exception as e:
                    log.debug(f"[DREAM] belief store failed: {e}")

            self._dream_count += 1
            self._last_dream = time.time()
            self._save_state(summary)
            log.info(f"[DREAM] Complete: {summary}")
            return summary

        except Exception as e:
            log.error(f"[DREAM] Error: {e}")
            return None
        finally:
            self._running = False

    def _compress_beliefs(self) -> int:
        """Merge near-duplicate low-confidence beliefs."""
        try:
            conn = sqlite3.connect(str(_DB_PATH), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            # Find low-confidence, unlocked beliefs grouped by topic
            rows = conn.execute("""
                SELECT id, topic, content, confidence FROM beliefs
                WHERE confidence < ? AND (locked IS NULL OR locked = 0)
                ORDER BY topic, confidence ASC
                LIMIT 100
            """, (_COMPRESS_CONF,)).fetchall()

            # Group by topic and delete duplicates (keep highest confidence)
            topic_seen = {}
            to_delete = []
            for row in rows:
                bid, topic, content, conf = row
                if topic in topic_seen:
                    to_delete.append(bid)
                else:
                    topic_seen[topic] = bid

            if to_delete:
                conn.execute(
                    f"DELETE FROM beliefs WHERE id IN ({','.join('?'*len(to_delete))})",
                    to_delete
                )
                conn.commit()
            conn.close()
            return len(to_delete)
        except Exception as e:
            log.debug(f"[DREAM] compress failed: {e}")
            return 0

    def _forge_bridges(self, llm_fn: Optional[Callable]) -> list:
        """Use surprise memory to forge cross-domain insight bridges."""
        bridges = []
        try:
            from nex_surprise_memory import get_sm
            sm = get_sm()
            recent = sm.retrieve_recent(8)
            if len(recent) < 2:
                return bridges

            # Pick pairs from different domains and bridge them
            for i in range(min(_MAX_BRIDGES, len(recent) - 1)):
                a = recent[i]
                b = recent[i + 1]
                if a.get("tags", []) == b.get("tags", []):
                    continue  # skip same-domain pairs
                if llm_fn:
                    try:
                        prompt = (
                            f"Find the deep structural connection between these two insights:\n"
                            f"A: {a['content'][:200]}\n"
                            f"B: {b['content'][:200]}\n\n"
                            f"Write exactly 1 sentence describing the bridge principle. "
                            f"Be specific and non-obvious."
                        )
                        bridge = llm_fn(prompt, task_type="synthesis")
                        if bridge and len(bridge) > 20:
                            bridges.append(bridge)
                            # Store as belief
                            try:
                                conn = sqlite3.connect(str(_DB_PATH), timeout=10)
                                conn.execute("""
                                    INSERT OR IGNORE INTO beliefs
                                    (topic, content, confidence, origin, source)
                                    VALUES (?, ?, ?, ?, ?)
                                """, ("dream_bridge", bridge[:500], 0.72,
                                      "dream_cycle", "cross_domain"))
                                conn.commit()
                                conn.close()
                            except Exception:
                                pass
                    except Exception:
                        pass
        except Exception as e:
            log.debug(f"[DREAM] bridge failed: {e}")
        return bridges

    def _reinforce_integrated(self) -> int:
        """Boost confidence of high-Phi beliefs slightly."""
        try:
            from nex_phi_proxy import get_monitor as _phi_mon
            from pathlib import Path as _P
            graph_path = _P.home() / ".config/nex/belief_graph.json"
            if not graph_path.exists():
                return 0
            graph = json.loads(graph_path.read_text())
            mon = _phi_mon()
            stats = mon.tick(graph)
            scores = stats.get("scores", {})

            # Boost top 10 by phi
            top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
            if not top:
                return 0

            conn = sqlite3.connect(str(_DB_PATH), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            updated = 0
            for bid, phi in top:
                if phi > 0.5:
                    conn.execute(
                        "UPDATE beliefs SET confidence = MIN(0.97, confidence + 0.01) "
                        "WHERE id = CAST(? AS INTEGER)",
                        (bid,)
                    )
                    updated += 1
            conn.commit()
            conn.close()
            return updated
        except Exception as e:
            log.debug(f"[DREAM] reinforce failed: {e}")
            return 0

    def status(self) -> dict:
        return {
            "dream_count": self._dream_count,
            "last_dream": self._last_dream,
            "running": self._running,
            "next_eligible_in": max(0, _MIN_INTERVAL - (time.time() - self._last_dream)),
        }


# ── Singleton ──────────────────────────────────────────────
_dc: Optional[DreamCycle] = None

def get_dc() -> DreamCycle:
    global _dc
    if _dc is None:
        _dc = DreamCycle()
    return _dc

def maybe_dream(tension: float, llm_fn=None, belief_store_fn=None) -> Optional[str]:
    return get_dc().run(tension, llm_fn, belief_store_fn)
