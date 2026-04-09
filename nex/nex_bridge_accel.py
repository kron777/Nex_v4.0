"""
nex_bridge_accel.py — Cross-Domain Bridge Accelerator
======================================================
Finds belief pairs from different topic clusters that have
weak or no connections and uses the LLM to forge strong bridges.

Unlike the dream cycle's basic bridge forging, this is targeted:
  - Uses resonance data to find high-potential cross-domain pairs
  - Scores bridges by novelty (not just coherence)
  - Stores bridges as high-confidence beliefs AND as graph edges
  - Tracks which bridges were most generative over time

Runs during COGNITION or dream cycle, max 3 bridges per run.
"""
from __future__ import annotations
import json, time, logging, sqlite3, threading
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.bridge_accel")

_DB_PATH      = Path.home() / ".config/nex/nex.db"
_BRIDGE_LOG   = Path.home() / ".config/nex/bridge_log.json"
_MIN_INTERVAL = 600    # 10 min between bridge runs
_MAX_BRIDGES  = 3      # per run
_MAX_LOG      = 200


class BridgeAccelerator:
    def __init__(self):
        self._lock = threading.Lock()
        self._last_run: float = 0
        self._bridges: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _BRIDGE_LOG.exists():
                self._bridges = json.loads(_BRIDGE_LOG.read_text())
        except Exception:
            self._bridges = []

    def _save(self):
        try:
            _BRIDGE_LOG.write_text(
                json.dumps(self._bridges[-_MAX_LOG:], indent=2)
            )
        except Exception:
            pass

    def _get_topic_pairs(self) -> list[tuple[str, str, str, str]]:
        """Get pairs of beliefs from different topics for bridging."""
        try:
            conn = sqlite3.connect(str(_DB_PATH), timeout=10)
            conn.row_factory = sqlite3.Row
            # Get top beliefs from 2 different domains
            rows = conn.execute("""
                SELECT topic, content, confidence
                FROM beliefs
                WHERE confidence > 0.65 AND topic IS NOT NULL
                  AND (loop_flag IS NULL OR loop_flag = 0)
                ORDER BY confidence DESC LIMIT 100
            """).fetchall()
            conn.close()

            by_topic: dict[str, list] = {}
            for r in rows:
                by_topic.setdefault(r["topic"], []).append(r["content"])

            topics = list(by_topic.keys())
            pairs = []
            for i in range(len(topics)):
                for j in range(i + 1, len(topics)):
                    if topics[i] != topics[j]:
                        pairs.append((
                            topics[i],
                            by_topic[topics[i]][0][:200],
                            topics[j],
                            by_topic[topics[j]][0][:200],
                        ))
            # Prioritize topic pairs not yet bridged
            bridged_pairs = {
                (b["topic_a"], b["topic_b"]) for b in self._bridges
            }
            novel = [p for p in pairs
                     if (p[0], p[2]) not in bridged_pairs
                     and (p[2], p[0]) not in bridged_pairs]
            return novel[:10] if novel else pairs[:5]
        except Exception:
            return []

    def run(self, llm_fn: Callable, cycle: int = 0) -> list[dict]:
        """
        Forge cross-domain bridges. Returns list of new bridges.
        """
        now = time.time()
        if now - self._last_run < _MIN_INTERVAL:
            return []
        self._last_run = now

        pairs = self._get_topic_pairs()
        if not pairs:
            return []

        new_bridges = []
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")

        for topic_a, content_a, topic_b, content_b in pairs[:_MAX_BRIDGES]:
            try:
                prompt = (
                    f"Find a non-obvious structural connection between:\n"
                    f"Field 1 ({topic_a}): {content_a}\n"
                    f"Field 2 ({topic_b}): {content_b}\n\n"
                    f"Write exactly 1 sentence describing the deep structural principle "
                    f"that underlies both. Must be specific and non-trivial. "
                    f"Do NOT use: 'different domain', 'Domain A', 'Domain B', 'bridge:', '↔'. "
                    f"Start with 'The underlying principle is...' or similar."
                )
                bridge_text = llm_fn(prompt, task_type="synthesis")
                if not bridge_text or len(bridge_text) < 20:
                    continue

                # Score novelty — penalize generic phrases
                generic = ["both", "similarly", "in common", "share", "relate"]
                novelty = 1.0 - sum(0.1 for w in generic if w in bridge_text.lower())
                novelty = max(0.3, novelty)

                bridge = {
                    "topic_a": topic_a,
                    "topic_b": topic_b,
                    "bridge": bridge_text[:400],
                    "novelty": round(novelty, 3),
                    "cycle": cycle,
                    "timestamp": time.time(),
                }
                new_bridges.append(bridge)

                # Reject bridge text that contains contamination phrases
                _bad = ["different domain", "Domain A", "Domain B", "bridge:",
                        "↔", "none of these resolve", "synthesized around"]
                if any(b in bridge_text for b in _bad):
                    log.debug(f"[BRIDGE] rejected contaminated output: {bridge_text[:60]}")
                    continue

                # Store as belief — clean topic, no ↔
                conf = min(0.82, 0.65 + novelty * 0.2)
                _clean_topic = f"{topic_a}+{topic_b}"[:60]
                conn.execute("""
                    INSERT OR IGNORE INTO beliefs
                    (topic, content, confidence, origin, source)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    _clean_topic,
                    bridge_text[:500],
                    conf,
                    "bridge_accelerator",
                    f"{topic_a}+{topic_b}",
                ))
                log.info(f"[BRIDGE] {topic_a} ↔ {topic_b}: {bridge_text[:60]}")

            except Exception as e:
                log.debug(f"[BRIDGE] failed: {e}")

        conn.commit()
        conn.close()

        with self._lock:
            self._bridges.extend(new_bridges)
            self._save()

        return new_bridges

    def recent_bridges(self, n: int = 5) -> list[dict]:
        with self._lock:
            return list(self._bridges[-n:])

    def top_bridges_by_novelty(self, n: int = 5) -> list[dict]:
        with self._lock:
            return sorted(self._bridges, key=lambda b: b["novelty"],
                          reverse=True)[:n]


# ── Singleton ──────────────────────────────────────────────
_ba: Optional[BridgeAccelerator] = None

def get_ba() -> BridgeAccelerator:
    global _ba
    if _ba is None:
        _ba = BridgeAccelerator()
    return _ba

def run(llm_fn: Callable, cycle: int = 0) -> list:
    return get_ba().run(llm_fn, cycle)
