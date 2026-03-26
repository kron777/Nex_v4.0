"""
nex_surprise_memory.py — Surprise-Gated Persistent Memory
==========================================================
Implements Titans-style (Google Research Dec 2025) test-time
memorization without retraining.

High-arousal or high-surprise events are written to a compact
secondary store that persists across sessions and influences
future synthesis — creating felt continuity of self.

Gate: event only stored if arousal > threshold OR salience > threshold.
"""
from __future__ import annotations
import json, time, os, threading, logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.surprise_memory")

_STORE_PATH    = Path.home() / ".config" / "nex" / "surprise_memory.json"
_MAX_MEMORIES  = 200
_AROUSAL_GATE  = 0.55    # minimum arousal to store
_SALIENCE_GATE = 0.60    # minimum salience to store
_DECAY_DAYS    = 14      # memories older than this get pruned


class SurpriseMemory:
    def __init__(self):
        self._lock = threading.Lock()
        self._memories: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _STORE_PATH.exists():
                self._memories = json.loads(_STORE_PATH.read_text())
        except Exception as e:
            log.warning(f"[SurpriseMem] load failed: {e}")
            self._memories = []

    def _save(self):
        try:
            _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _STORE_PATH.write_text(json.dumps(self._memories, indent=2))
        except Exception as e:
            log.warning(f"[SurpriseMem] save failed: {e}")

    def maybe_store(
        self,
        content: str,
        source: str = "",
        arousal: float = 0.0,
        salience: float = 0.0,
        tags: Optional[list[str]] = None,
    ) -> bool:
        """Store if arousal or salience clears the gate. Returns True if stored."""
        if arousal < _AROUSAL_GATE and salience < _SALIENCE_GATE:
            return False

        record = {
            "content":   content[:500],
            "source":    source,
            "arousal":   round(arousal, 3),
            "salience":  round(salience, 3),
            "tags":      tags or [],
            "timestamp": time.time(),
        }

        with self._lock:
            self._memories.append(record)
            # Prune oldest beyond cap
            if len(self._memories) > _MAX_MEMORIES:
                self._memories = self._memories[-_MAX_MEMORIES:]
            self._save()

        log.info(f"[SurpriseMem] stored: arousal={arousal:.2f} sal={salience:.2f} — {content[:60]}")
        return True

    def prune_old(self):
        cutoff = time.time() - _DECAY_DAYS * 86400
        with self._lock:
            before = len(self._memories)
            self._memories = [m for m in self._memories if m["timestamp"] > cutoff]
            pruned = before - len(self._memories)
            if pruned:
                self._save()
                log.info(f"[SurpriseMem] pruned {pruned} old memories")

    def retrieve_recent(self, n: int = 5) -> list[dict]:
        with self._lock:
            return sorted(self._memories, key=lambda m: m["timestamp"], reverse=True)[:n]

    def retrieve_by_tag(self, tag: str, n: int = 5) -> list[dict]:
        with self._lock:
            tagged = [m for m in self._memories if tag in m.get("tags", [])]
            return sorted(tagged, key=lambda m: m["timestamp"], reverse=True)[:n]

    def to_context_block(self, n: int = 3) -> str:
        recent = self.retrieve_recent(n)
        if not recent:
            return ""
        lines = ["── SURPRISE MEMORY (high-salience events) ──"]
        for m in recent:
            age_h = (time.time() - m["timestamp"]) / 3600
            lines.append(f"[{age_h:.1f}h ago | sal={m['salience']:.2f}] {m['content'][:100]}")
        lines.append("──")
        return "\n".join(lines)

    def count(self) -> int:
        with self._lock:
            return len(self._memories)


# ── Singleton ──────────────────────────────────────────────
_sm: Optional[SurpriseMemory] = None

def get_sm() -> SurpriseMemory:
    global _sm
    if _sm is None:
        _sm = SurpriseMemory()
    return _sm

def maybe_store(content: str, source: str = "", arousal: float = 0.0,
                salience: float = 0.0, tags: Optional[list[str]] = None) -> bool:
    return get_sm().maybe_store(content, source, arousal, salience, tags)

def to_context_block(n: int = 3) -> str:
    return get_sm().to_context_block(n)
