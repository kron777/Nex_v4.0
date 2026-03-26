"""
nex_gwt.py — Global Workspace Theory Broadcast Layer
=====================================================
Implements GWT (Baars/Dehaene) for NEX:
  - Salience competition: affect + tension + curiosity compete for
    the global workspace "spotlight"
  - Winner broadcasts a shared context token to all subscribing modules
  - Creates the "theatre of mind" — unified awareness instead of
    parallel modules running blind to each other

Based on: Nakanishi arXiv 2505.13969, Goldstein & Kirk-Giannini 2410.11407
"""
from __future__ import annotations
import threading, time, logging, math
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger("nex.gwt")

# ── Salience signal ───────────────────────────────────────
@dataclass
class SalienceSignal:
    source: str          # "affect" | "tension" | "curiosity" | "surprise" | "belief"
    content: str         # human-readable description
    salience: float      # 0-1
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

# ── Global Workspace Token (what gets broadcast) ───────────
@dataclass
class WorkspaceToken:
    winner: SalienceSignal
    runner_up: Optional[SalienceSignal]
    cycle: int
    broadcast_time: float = field(default_factory=time.time)

    def to_prompt_block(self) -> str:
        lines = ["── GLOBAL WORKSPACE ──"]
        lines.append(f"Spotlight : [{self.winner.source}] {self.winner.content[:120]}")
        lines.append(f"Salience  : {self.winner.salience:.2f}")
        if self.runner_up:
            lines.append(f"Background: [{self.runner_up.source}] {self.runner_up.content[:80]}")
        lines.append(f"Cycle     : {self.cycle}")
        lines.append("── respond with this awareness ──")
        return "\n".join(lines)


class GlobalWorkspaceBroadcast:
    """
    Competition-broadcast cycle for NEX's cognitive bus.

    Modules register signals every cycle.
    GWB picks the highest-salience winner and broadcasts to all listeners.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._signals: list[SalienceSignal] = []
        self._current_token: Optional[WorkspaceToken] = None
        self._cycle = 0
        self._listeners: list[Callable[[WorkspaceToken], None]] = []
        self._history: list[WorkspaceToken] = []

    def register_listener(self, fn: Callable[[WorkspaceToken], None]):
        with self._lock:
            self._listeners.append(fn)

    def submit(self, signal: SalienceSignal):
        """Any module submits a salience signal for competition."""
        with self._lock:
            self._signals.append(signal)

    def broadcast(self) -> Optional[WorkspaceToken]:
        """
        Run one competition cycle. Call once per cognition cycle.
        Returns the winning WorkspaceToken or None if no signals.
        """
        with self._lock:
            if not self._signals:
                return None

            # Sort by salience — winner takes the spotlight
            ranked = sorted(self._signals, key=lambda s: s.salience, reverse=True)
            winner = ranked[0]
            runner_up = ranked[1] if len(ranked) > 1 else None

            self._cycle += 1
            token = WorkspaceToken(
                winner=winner,
                runner_up=runner_up,
                cycle=self._cycle,
            )
            self._current_token = token
            self._signals.clear()

            # Trim history
            self._history.append(token)
            if len(self._history) > 100:
                self._history = self._history[-100:]

            listeners = list(self._listeners)

        log.info(f"[GWT] cycle={self._cycle} spotlight=[{winner.source}] "
                 f"sal={winner.salience:.2f} — {winner.content[:60]}")

        for fn in listeners:
            try:
                fn(token)
            except Exception as e:
                log.warning(f"[GWT] listener error: {e}")

        return token

    def current_token(self) -> Optional[WorkspaceToken]:
        with self._lock:
            return self._current_token

    def inject_to_prompt(self, base_prompt: str) -> str:
        """Prepend current workspace token to any prompt."""
        token = self.current_token()
        if token:
            return token.to_prompt_block() + "\n\n" + base_prompt
        return base_prompt

    def recent_winners(self, n: int = 5) -> list[str]:
        with self._lock:
            return [f"[{t.winner.source}] {t.winner.content[:60]}"
                    for t in self._history[-n:]]


# ── Helpers for common signal types ───────────────────────

def affect_signal(valence: float, arousal: float, label: str) -> SalienceSignal:
    sal = min(1.0, abs(valence) * 0.5 + arousal * 0.5)
    return SalienceSignal(
        source="affect",
        content=f"mood={label} v={valence:+.2f} a={arousal:.2f}",
        salience=sal,
        payload={"valence": valence, "arousal": arousal},
    )

def tension_signal(pressure: float, topic: str = "") -> SalienceSignal:
    return SalienceSignal(
        source="tension",
        content=f"tension={pressure:.2f}" + (f" on '{topic}'" if topic else ""),
        salience=min(1.0, pressure / 100.0),
        payload={"pressure": pressure, "topic": topic},
    )

def curiosity_signal(ctype: str, description: str, strength: float = 0.6) -> SalienceSignal:
    return SalienceSignal(
        source="curiosity",
        content=f"{ctype}: {description[:80]}",
        salience=strength,
        payload={"type": ctype},
    )

def surprise_signal(content: str, intensity: float) -> SalienceSignal:
    return SalienceSignal(
        source="surprise",
        content=content[:100],
        salience=min(1.0, intensity),
        payload={"intensity": intensity},
    )


# ── Singleton ──────────────────────────────────────────────
_gwb: Optional[GlobalWorkspaceBroadcast] = None

def get_gwb() -> GlobalWorkspaceBroadcast:
    global _gwb
    if _gwb is None:
        _gwb = GlobalWorkspaceBroadcast()
    return _gwb

def submit(signal: SalienceSignal):
    get_gwb().submit(signal)

def broadcast() -> Optional[WorkspaceToken]:
    return get_gwb().broadcast()

def inject_to_prompt(base: str) -> str:
    return get_gwb().inject_to_prompt(base)
