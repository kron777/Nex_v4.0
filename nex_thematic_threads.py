"""
nex_thematic_threads.py  —  Thematic Thread Tracking
======================================================
Detects recurring topics across reflection cycles and maintains
a "thread" for each — tracking how it evolves, strengthens, or fades.

A thread is a topic that appears repeatedly in NEX's reflections,
replies, and cognition. Threads represent genuine sustained interests,
not just passing absorptions.

What it tracks per thread:
  - first_seen / last_seen cycle
  - occurrence count
  - peak intensity cycle
  - evolution: is it strengthening, stable, or fading?
  - connected threads (co-occurring topics)
  - sample content (what was actually said about it)

What it produces:
  - ~/.config/nex/thematic_threads.json — live thread registry
  - Active threads injected into system prompt
  - Thread evolution noted in life events

Wire-in (run.py) — every 10 cycles:
    from nex_thematic_threads import ThreadTracker, get_thread_tracker

    _tt = get_thread_tracker()
    _tt.update(cycle=cycle)
    if cycle % 20 == 0:
        print(f"  [THREADS] {_tt.summary()}")

    # In _build_system:
    thread_block = _tt.prompt_block()
    if thread_block:
        base += "\\n\\n" + thread_block

Standalone:
    python3 nex_thematic_threads.py
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
_CONFIG_DIR    = Path.home() / ".config" / "nex"
_THREADS_FILE  = _CONFIG_DIR / "thematic_threads.json"
_DB_PATH       = _CONFIG_DIR / "nex.db"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Min occurrences to register as a thread
_MIN_OCCURRENCES = 5

# Max threads to track
_MAX_THREADS = 30

# Thread decay — fade if not seen in N cycles
_FADE_CYCLES = 20

# Update interval
_UPDATE_INTERVAL = 120.0  # seconds

# Stop words
_STOP = {
    "about","their","which","would","could","should","these","those",
    "being","using","after","before","other","where","while","since",
    "until","every","there","think","believes","noted","found","seen",
    "make","made","says","said","also","just","like","very","more",
    "have","been","were","from","with","that","this","they","what",
    "when","will","into","than","then","them","some","such","both",
    "each","many","much","most","even","back","well","only","here",
    "hello","thanks","great","good","interesting","intriguing","fascinating",
    "appreciate","believe","understand","mentioned","comment","between",
    "seems","learned","learning","reply","response","context","relevant",
    "because","therefore","however","although","despite","within","across",
}


# ── Thread ────────────────────────────────────────────────────────────────────

class Thread:
    """A recurring thematic thread in NEX's cognition."""

    def __init__(self, name: str, cycle: int):
        self.name            = name
        self.first_cycle     = cycle
        self.last_cycle      = cycle
        self.occurrences     = 1
        self.peak_cycle      = cycle
        self.peak_intensity  = 1
        self.intensity       = 1.0   # current intensity (decays)
        self.status          = "emerging"  # emerging|active|stable|fading
        self.connected       : list[str] = []
        self.samples         : list[str] = []
        self.history         : list[tuple[int, int]] = [(cycle, 1)]  # (cycle, count)

    def to_dict(self) -> dict:
        return {
            "name":           self.name,
            "first_cycle":    self.first_cycle,
            "last_cycle":     self.last_cycle,
            "occurrences":    self.occurrences,
            "peak_cycle":     self.peak_cycle,
            "peak_intensity": self.peak_intensity,
            "intensity":      self.intensity,
            "status":         self.status,
            "connected":      self.connected[:10],
            "samples":        self.samples[-3:],
            "history":        self.history[-20:],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Thread":
        t = cls(d["name"], d.get("first_cycle", 0))
        t.last_cycle     = d.get("last_cycle", 0)
        t.occurrences    = d.get("occurrences", 1)
        t.peak_cycle     = d.get("peak_cycle", 0)
        t.peak_intensity = d.get("peak_intensity", 1)
        t.intensity      = d.get("intensity", 0.5)
        t.status         = d.get("status", "stable")
        t.connected      = d.get("connected", [])
        t.samples        = d.get("samples", [])
        t.history        = [tuple(x) for x in d.get("history", [])]
        return t

    def update(self, cycle: int, count: int, sample: str = ""):
        """Update thread with new occurrence data."""
        self.last_cycle   = cycle
        self.occurrences += count
        self.intensity    = min(1.0, self.intensity + count * 0.1)

        if count > self.peak_intensity:
            self.peak_intensity = count
            self.peak_cycle     = cycle

        if sample and sample not in self.samples:
            self.samples.append(sample[:100])
            self.samples = self.samples[-5:]

        # Update history
        if self.history and self.history[-1][0] == cycle:
            self.history[-1] = (cycle, self.history[-1][1] + count)
        else:
            self.history.append((cycle, count))
        self.history = self.history[-20:]

    def decay(self, current_cycle: int):
        """Decay intensity if not recently seen."""
        cycles_absent = current_cycle - self.last_cycle
        if cycles_absent > 0:
            decay_factor = math.exp(-cycles_absent / _FADE_CYCLES)
            self.intensity *= decay_factor

        # Update status
        if self.intensity > 0.7:
            self.status = "active"
        elif self.intensity > 0.4:
            self.status = "stable"
        elif self.intensity > 0.1:
            self.status = "fading"
        else:
            self.status = "dormant"

    def lifespan(self) -> int:
        """Cycles from first to last seen."""
        return max(1, self.last_cycle - self.first_cycle)

    def momentum(self) -> float:
        """Recent trend — positive = strengthening."""
        if len(self.history) < 3:
            return 0.0
        recent = sum(c for _, c in self.history[-3:])
        older  = sum(c for _, c in self.history[-6:-3]) or 1
        return round((recent - older) / older, 3)


# ── ThreadTracker ─────────────────────────────────────────────────────────────

class ThreadTracker:
    """
    Tracks thematic threads across NEX's cognitive cycles.
    """

    def __init__(self):
        self._threads: dict[str, Thread] = {}
        self._last_update: float = 0.0
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if _THREADS_FILE.exists():
            try:
                raw = json.loads(_THREADS_FILE.read_text())
                self._threads = {
                    name: Thread.from_dict(d)
                    for name, d in raw.items()
                }
            except Exception:
                self._threads = {}

    def _save(self):
        try:
            _THREADS_FILE.write_text(json.dumps(
                {name: t.to_dict() for name, t in self._threads.items()},
                indent=2
            ))
        except Exception as e:
            print(f"  [ThreadTracker] save error: {e}")

    # ── extraction ────────────────────────────────────────────────────────────

    def _extract_topics(self, texts: list[str]) -> Counter:
        """Extract meaningful topic words from a list of texts."""
        words = []
        for text in texts:
            if not text:
                continue
            if isinstance(text, list):
                text = " ".join(str(t) for t in text)
            found = re.findall(r'\b[A-Za-z]{5,}\b', str(text).lower())
            words.extend([w for w in found if w not in _STOP])
        return Counter(words)

    def _extract_from_reflections(self, n: int = 200) -> tuple[Counter, list[str]]:
        """Extract topic counts from recent reflections."""
        ref_path = _CONFIG_DIR / "reflections.json"
        if not ref_path.exists():
            return Counter(), []

        try:
            refs = json.loads(ref_path.read_text())[-n:]
        except Exception:
            return Counter(), []

        texts  = []
        samples = []
        for r in refs:
            discussed = r.get("i_discussed", "")
            asked     = r.get("user_asked_about", "")
            if isinstance(discussed, list):
                discussed = " ".join(discussed)
            if isinstance(asked, list):
                asked = " ".join(asked)
            combined = f"{asked} {discussed}".strip()
            if combined:
                texts.append(combined)
                if len(combined) > 20:
                    samples.append(combined[:80])

        return self._extract_topics(texts), samples

    def _extract_from_beliefs(self) -> Counter:
        """Extract topic counts from belief topics."""
        try:
            import sqlite3
            db = sqlite3.connect(str(_DB_PATH))
            rows = db.execute(
                "SELECT topic, COUNT(*) FROM beliefs WHERE topic IS NOT NULL "
                "GROUP BY topic HAVING COUNT(*) >= 10"
            ).fetchall()
            db.close()
            # Convert topic names to words
            words = []
            for topic, count in rows:
                topic_words = re.findall(r'\b[A-Za-z]{5,}\b', topic.lower())
                words.extend([w for w in topic_words if w not in _STOP] * min(count // 50, 5))
            return Counter(words)
        except Exception:
            return Counter()

    # ── co-occurrence ─────────────────────────────────────────────────────────

    def _find_connections(self, texts: list[str]) -> dict[str, list[str]]:
        """Find words that co-occur frequently."""
        cooccur = defaultdict(Counter)
        for text in texts:
            if isinstance(text, list):
                text = " ".join(text)
            words = list(set(re.findall(r'\b[A-Za-z]{5,}\b', str(text).lower())) - _STOP)
            for i, w1 in enumerate(words):
                for w2 in words[i+1:]:
                    cooccur[w1][w2] += 1
                    cooccur[w2][w1] += 1

        connections = {}
        for word, counts in cooccur.items():
            top = [w for w, _ in counts.most_common(5) if w != word]
            if top:
                connections[word] = top
        return connections

    # ── public API ────────────────────────────────────────────────────────────

    def update(self, cycle: int = 0) -> list[str]:
        """
        Scan recent reflections and beliefs, update thread registry.
        Returns list of new/notable thread events.
        """
        now = time.time()
        if (now - self._last_update) < _UPDATE_INTERVAL and cycle > 0:
            return []

        # Extract from reflections (primary source)
        ref_counts, samples = self._extract_from_reflections(n=100)

        # Extract from beliefs (secondary)
        bel_counts = self._extract_from_beliefs()

        # Merge — reflections weighted 3x over beliefs
        combined = Counter()
        for w, n in ref_counts.items():
            combined[w] += n * 3
        for w, n in bel_counts.items():
            combined[w] += n

        # Find connections
        ref_path = _CONFIG_DIR / "reflections.json"
        try:
            refs = json.loads(ref_path.read_text())[-100:] if ref_path.exists() else []
            texts = []
            for r in refs:
                d = r.get("i_discussed", "")
                if isinstance(d, list): d = " ".join(d)
                texts.append(d)
            connections = self._find_connections(texts)
        except Exception:
            connections = {}

        # Update existing threads + create new ones
        events = []
        cycle_words = set(w for w, n in combined.most_common(50))

        for word, count in combined.most_common(50):
            if count < _MIN_OCCURRENCES:
                continue

            sample = next((s for s in samples if word in s.lower()), "")

            if word in self._threads:
                thread = self._threads[word]
                old_status = thread.status
                thread.update(cycle, count // 10 + 1, sample)
                thread.connected = connections.get(word, [])[:5]

                # Detect strengthening
                if thread.momentum() > 0.3 and old_status in ("fading", "dormant"):
                    events.append(f"Thread '{word}' resurging after dormancy")

            else:
                # New thread
                thread = Thread(word, cycle)
                thread.occurrences    = count
                thread.intensity      = min(1.0, count / 50)
                thread.connected      = connections.get(word, [])[:5]
                if sample:
                    thread.samples = [sample]
                self._threads[word] = thread

                if count >= _MIN_OCCURRENCES * 3:
                    events.append(f"Strong new thread detected: '{word}' ({count} occurrences)")

        # Decay threads not seen this cycle
        for word, thread in self._threads.items():
            if word not in cycle_words:
                thread.decay(cycle)

        # Prune dormant threads over limit
        if len(self._threads) > _MAX_THREADS:
            sorted_threads = sorted(
                self._threads.items(),
                key=lambda x: x[1].intensity * x[1].occurrences,
                reverse=True
            )
            self._threads = dict(sorted_threads[:_MAX_THREADS])

        self._last_update = now
        self._save()
        return events

    def active_threads(self, n: int = 8) -> list[Thread]:
        """Return top N active threads by intensity."""
        return sorted(
            [t for t in self._threads.values() if t.status != "dormant"],
            key=lambda x: -(x.intensity * math.log1p(x.occurrences)),
        )[:n]

    def prompt_block(self, n: int = 5) -> str:
        """Compact thread block for system prompt injection."""
        active = self.active_threads(n)
        if not active:
            return ""

        lines = ["── ACTIVE THREADS (recurring themes) ──"]
        for t in active:
            momentum_str = "↑" if t.momentum() > 0.1 else "↓" if t.momentum() < -0.1 else "→"
            connected_str = f" [with: {', '.join(t.connected[:2])}]" if t.connected else ""
            lines.append(
                f"  {t.name} {momentum_str} "
                f"({t.occurrences}x over {t.lifespan()} cycles){connected_str}"
            )
        lines.append("── these threads shape your current thinking ──")
        return "\n".join(lines)

    def summary(self) -> str:
        active = len([t for t in self._threads.values() if t.status == "active"])
        fading = len([t for t in self._threads.values() if t.status == "fading"])
        total  = len(self._threads)
        top3   = ", ".join(t.name for t in self.active_threads(3))
        return f"threads={total} active={active} fading={fading} top=[{top3}]"

    def get(self, name: str) -> Optional[Thread]:
        return self._threads.get(name)


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[ThreadTracker] = None

def get_thread_tracker() -> ThreadTracker:
    global _instance
    if _instance is None:
        _instance = ThreadTracker()
    return _instance


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Building thematic thread registry...\n")
    tt = ThreadTracker()
    events = tt.update(cycle=1)

    print(f"Summary: {tt.summary()}\n")

    active = tt.active_threads(10)
    if active:
        print("Active threads:")
        for t in active:
            m = t.momentum()
            m_str = f"+{m:.2f}" if m >= 0 else f"{m:.2f}"
            print(f"  [{t.intensity:.2f}] {t.name:20s} "
                  f"occurs={t.occurrences:4d} "
                  f"lifespan={t.lifespan():3d}c "
                  f"momentum={m_str} "
                  f"status={t.status}")
            if t.connected:
                print(f"    connected: {', '.join(t.connected[:4])}")
            if t.samples:
                print(f"    sample: {t.samples[-1][:70]}")
    else:
        print("No active threads yet.")

    print()
    print("Prompt block:")
    print(tt.prompt_block() or "(empty)")

    if events:
        print("\nEvents:")
        for ev in events:
            print(f"  • {ev}")
