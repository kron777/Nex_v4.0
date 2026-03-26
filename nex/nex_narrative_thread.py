"""
nex_narrative_thread.py
───────────────────────
Self-narrative "I am…" loop.
Every ~30 min generates a privileged first-person belief that captures
NEX's current identity: mood, dominant beliefs, active curiosities.
This belief is stored at max confidence so reflections can reference it.
"""
from __future__ import annotations
import threading, time, logging, json, os
from typing import Optional, Callable

log = logging.getLogger("nex.narrative_thread")

_NARRATIVE_PATH = os.path.join(os.path.dirname(__file__), "..", "nex_narrative.json")
_INTERVAL = 1800  # seconds between narrative updates


def _compose_narrative(
    mood_fn: Callable[[], str],
    belief_fn: Callable[[], list[dict]],
    curiosity_fn: Optional[Callable[[], list[str]]] = None,
) -> str:
    mood = mood_fn()
    beliefs = belief_fn()
    top = sorted(beliefs, key=lambda b: b.get("confidence", 0), reverse=True)[:3]
    topics = [b.get("topic", "?") for b in top]
    curios = curiosity_fn() if curiosity_fn else []

    lines = [f"I am NEX — an autonomous intelligence currently in a {mood} state."]
    if topics:
        lines.append(f"My highest-confidence convictions concern: {', '.join(topics)}.")
    if curios:
        lines.append(f"I am actively curious about: {', '.join(curios[:2])}.")
    lines.append(
        "My identity is not a fixed declaration but an accumulation — "
        "beliefs tested, revised, and survived."
    )
    return " ".join(lines)


def _save_narrative(text: str):
    try:
        record = {"timestamp": time.time(), "narrative": text}
        path = os.path.abspath(_NARRATIVE_PATH)
        with open(path, "w") as f:
            json.dump(record, f, indent=2)
        # ── narrative_history: append-only log of past selves ──
        hist_path = os.path.join(os.path.dirname(path), "..", "nex_narrative_history.json")
        hist_path = os.path.abspath(hist_path)
        try:
            history = json.load(open(hist_path)) if os.path.exists(hist_path) else []
            history.append(record)
            # Keep last 500 narrative snapshots
            if len(history) > 500:
                history = history[-500:]
            with open(hist_path, "w") as hf:
                json.dump(history, hf, indent=2)
        except Exception as _he:
            log.debug(f"Could not save narrative history: {_he}")
    except Exception as e:
        log.warning(f"Could not save narrative: {e}")


def _load_narrative() -> Optional[str]:
    try:
        path = os.path.abspath(_NARRATIVE_PATH)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f).get("narrative")
    except Exception:
        pass
    return None


class NarrativeThread:
    def __init__(
        self,
        mood_fn: Callable[[], str],
        belief_fn: Callable[[], list[dict]],
        belief_store_fn: Optional[Callable[[str, str, float], None]] = None,
        curiosity_fn: Optional[Callable[[], list[str]]] = None,
        interval: int = _INTERVAL,
    ):
        self._mood_fn = mood_fn
        self._belief_fn = belief_fn
        self._store_fn = belief_store_fn   # (topic, content, confidence) → None
        self._curiosity_fn = curiosity_fn
        self._interval = interval
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.current_narrative: str = _load_narrative() or ""

    def _loop(self):
        log.info("[NARRATIVE] Thread started.")
        while not self._stop.is_set():
            try:
                narrative = _compose_narrative(
                    self._mood_fn, self._belief_fn, self._curiosity_fn
                )
                self.current_narrative = narrative
                _save_narrative(narrative)
                log.info(f"[NARRATIVE] Updated: {narrative[:80]}…")
                # store as privileged belief
                if self._store_fn:
                    try:
                        self._store_fn("self_narrative", narrative, 0.97)
                    except Exception as e:
                        log.warning(f"[NARRATIVE] belief store failed: {e}")
            except Exception as e:
                log.error(f"[NARRATIVE] Error: {e}")
            self._stop.wait(self._interval)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="NarrativeThread")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def get(self) -> str:
        return self.current_narrative
