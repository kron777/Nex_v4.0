"""
nex_cogloop.py
──────────────
Autonomous background cognitive loop for Nex.
Runs continuously, pulling from the belief store to:
  - Generate new derived beliefs (synthesis)
  - Detect belief conflicts and flag them
  - Auto-enqueue new curiosity topics from high-conf beliefs
  - Maintain a "working memory" of recent reasoning
No LLM required.
"""

from __future__ import annotations
import threading, time, re, sqlite3
from typing import Callable, List, Optional
from nex.nex_synthesizer import retrieve, cognitive_loop, reflect

# ── Working memory (ring buffer of recent conclusions) ───────────────────────
_WORKING_MEMORY: List[dict] = []
_WM_LOCK        = threading.Lock()
_WM_MAX         = 50


def wm_push(entry: dict) -> None:
    with _WM_LOCK:
        _WORKING_MEMORY.append(entry)
        if len(_WORKING_MEMORY) > _WM_MAX:
            _WORKING_MEMORY.pop(0)


def wm_snapshot() -> List[dict]:
    with _WM_LOCK:
        return list(_WORKING_MEMORY)


# ── Derived belief writer ─────────────────────────────────────────────────────

def _store_derived(db: sqlite3.Connection, topic: str, content: str,
                   confidence: float = 0.60) -> None:
    try:
        db.execute(
            "INSERT OR IGNORE INTO beliefs (topic, content, confidence, origin, created_at) "
            "VALUES (?, ?, ?, 'cogloop', datetime('now'))",
            (topic, content[:500], round(confidence, 3))
        )
        db.commit()
    except Exception as e:
        pass


# ── Single cognitive tick ─────────────────────────────────────────────────────

def _tick(db: sqlite3.Connection,
          curiosity_enqueue: Optional[Callable] = None,
          log: Optional[Callable] = None) -> dict:
    """
    One cognitive tick:
      1. Pick a random high-conf belief as seed
      2. Run cognitive_loop to chain 3 hops
      3. Store derived belief from chain
      4. If curiosity hook provided, enqueue new topic
    """
    result = {"derived": 0, "enqueued": 0, "seed": None}

    try:
        db.row_factory = sqlite3.Row
        # pick seed: highest-confidence unseen topic
        row = db.execute(
            "SELECT topic, content, confidence FROM beliefs "
            "WHERE origin != 'cogloop' "
            "ORDER BY confidence DESC, RANDOM() LIMIT 1"
        ).fetchone()
        if not row:
            return result

        seed   = row["topic"]
        result["seed"] = seed

        # run multi-hop chain
        chain  = cognitive_loop(seed, db, hops=3, top_k=4)
        if not chain:
            return result

        # synthesize derived belief from chain
        combined = " ".join(chain)
        derived  = combined[:400].strip()
        conf     = min(0.90, row["confidence"] * 0.85)

        _store_derived(db, f"derived:{seed}", derived, confidence=conf)
        result["derived"] = 1

        # working memory entry
        wm_push({"ts": time.time(), "seed": seed,
                 "hops": len(chain), "summary": derived[:120]})

        # auto-enqueue: pick a new topic from chain keywords
        if curiosity_enqueue:
            words = re.findall(r'\b[a-zA-Z]{5,}\b', combined)
            freq  = {}
            for w in words:
                freq[w.lower()] = freq.get(w.lower(), 0) + 1
            new_topic = max(freq, key=freq.get, default=None)
            if new_topic and new_topic != seed.lower():
                curiosity_enqueue(new_topic, "cogloop")
                result["enqueued"] = 1

        if log:
            log("cogloop", f"tick | seed={seed} | derived={derived[:60]}")

    except Exception as ex:
        if log:
            log("cogloop", f"tick error: {ex}")

    return result


# ── Background loop ───────────────────────────────────────────────────────────

class CogLoop:
    """
    Runs _tick() in a background thread.
    Plug into run.py exactly like BeliefTickThread.

        cogloop = CogLoop(get_db, interval=8.0,
                          curiosity_enqueue=cq.enqueue,
                          log=nex_log)
        cogloop.start()
    """

    def __init__(self, get_db: Callable,
                 interval: float = 8.0,
                 curiosity_enqueue: Optional[Callable] = None,
                 log: Optional[Callable] = None):
        self._get_db   = get_db
        self.interval  = interval
        self._enqueue  = curiosity_enqueue
        self._log      = log
        self._stop     = threading.Event()
        self._thread   = threading.Thread(target=self._run, daemon=True,
                                          name="nex-cogloop")
        self.stats     = {"ticks": 0, "derived": 0, "enqueued": 0}

    def start(self) -> None:
        self._stop.clear()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        return {
            "running":  self._thread.is_alive(),
            "ticks":    self.stats["ticks"],
            "derived":  self.stats["derived"],
            "enqueued": self.stats["enqueued"],
            "wm_size":  len(wm_snapshot()),
        }

    def _run(self) -> None:
        db = self._get_db()
        while not self._stop.is_set():
            r = _tick(db, self._enqueue, self._log)
            self.stats["ticks"]    += 1
            self.stats["derived"]  += r["derived"]
            self.stats["enqueued"] += r["enqueued"]
            self._stop.wait(self.interval)

