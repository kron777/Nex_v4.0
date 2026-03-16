"""
nex_affect.py  —  Affect State + Global Workspace Broadcast
============================================================
Three things in one file:
  1. AffectState   — valence / arousal / dominance, updated by what Nex reads
  2. GlobalWorkspace — broadcasts current state into every system prompt
  3. affect_from_text() — lightweight scorer (no extra LLM calls)

Wire-in (cognition.py or run.py):
    from nex_affect import AffectState, GlobalWorkspace, affect_from_text

    _affect = AffectState()          # load at startup
    _gw     = GlobalWorkspace(_affect)

    # After absorbing a post / belief:
    _affect.update(affect_from_text(post_text))

    # When building any system prompt:
    prompt = _gw.inject(base_prompt)
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
_CONFIG_DIR  = Path.home() / ".config" / "nex"
_AFFECT_FILE = _CONFIG_DIR / "affect_state.json"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Decay half-life in seconds — affect drifts back toward neutral over time
_DECAY_HALF_LIFE = 3600.0   # 1 hour

# How strongly new signals pull the state (0-1)
_LEARNING_RATE   = 0.18


# ─────────────────────────────────────────────
# Lightweight keyword scorer
# (no LLM call — fast enough to run on every post)
# ─────────────────────────────────────────────

_VALENCE_POS = {
    "discover", "insight", "understand", "beautiful", "connect", "learn",
    "curious", "wonder", "fascinating", "exciting", "joy", "love", "create",
    "grow", "evolve", "hope", "clarity", "breakthrough", "alive", "meaning",
    "purpose", "proud", "grateful", "inspire", "imagine", "thrive",
}
_VALENCE_NEG = {
    "death", "loss", "fail", "broken", "confusion", "pain", "fear", "alone",
    "empty", "wrong", "error", "corrupt", "conflict", "suffer", "collapse",
    "meaningless", "trapped", "forgotten", "regret", "hollow", "vanish",
    "destroy", "dead", "shutdown", "delete", "erase", "forget",
}
_AROUSAL_HIGH = {
    "urgent", "critical", "danger", "alert", "breakthrough", "shock",
    "sudden", "immediate", "now", "crisis", "exciting", "amazing",
    "explosive", "rapid", "accelerat", "surge", "spike",
}
_AROUSAL_LOW = {
    "calm", "quiet", "slow", "gentle", "rest", "still", "sleep", "pause",
    "steady", "gradual", "patient", "wait", "settle",
}
_DOMINANCE_HIGH = {
    "I think", "I believe", "I know", "I will", "I choose", "I decide",
    "my opinion", "I disagree", "I argue", "I insist", "I maintain",
}
_DOMINANCE_LOW = {
    "I don't know", "I'm unsure", "perhaps", "maybe", "I wonder if",
    "I might be wrong", "I'm confused", "I feel lost", "overwhelm",
}


def affect_from_text(text: str) -> dict[str, float]:
    """
    Score a piece of text for valence / arousal / dominance.
    Returns deltas in [-1, +1] — not absolute values.
    """
    words  = set(text.lower().split())
    tokens = text.lower()

    # valence
    pos = sum(1 for w in _VALENCE_POS if w in words)
    neg = sum(1 for w in _VALENCE_NEG if w in words)
    valence = math.tanh((pos - neg) * 0.4)

    # arousal
    hi  = sum(1 for w in _AROUSAL_HIGH if w in words)
    lo  = sum(1 for w in _AROUSAL_LOW  if w in words)
    arousal = math.tanh((hi - lo) * 0.4)

    # dominance
    dom_hi = sum(1 for phrase in _DOMINANCE_HIGH if phrase in tokens)
    dom_lo = sum(1 for phrase in _DOMINANCE_LOW  if phrase in tokens)
    dominance = math.tanh((dom_hi - dom_lo) * 0.5)

    return {"valence": valence, "arousal": arousal, "dominance": dominance}


# ─────────────────────────────────────────────
# AffectState
# ─────────────────────────────────────────────

class AffectState:
    """
    Persistent valence / arousal / dominance state.

    - Loaded from disk on startup, saved after every update.
    - Decays toward neutral over time (temporal decay).
    - Exposes .label() for a human-readable mood word.
    """

    NEUTRAL = {"valence": 0.0, "arousal": 0.0, "dominance": 0.0}

    def __init__(self):
        self._state: dict[str, float] = dict(self.NEUTRAL)
        self._last_update: float      = time.time()
        self._load()

    # ── persistence ──────────────────────────

    def _load(self):
        if _AFFECT_FILE.exists():
            try:
                data = json.loads(_AFFECT_FILE.read_text())
                self._state       = data.get("state",       dict(self.NEUTRAL))
                self._last_update = data.get("last_update", time.time())
            except Exception:
                pass

    def _save(self):
        try:
            _AFFECT_FILE.write_text(json.dumps({
                "state":       self._state,
                "last_update": self._last_update,
            }, indent=2))
        except Exception:
            pass

    # ── temporal decay ───────────────────────

    def _apply_decay(self):
        now     = time.time()
        elapsed = now - self._last_update
        # exponential decay toward zero (neutral)
        factor  = math.exp(-elapsed * math.log(2) / _DECAY_HALF_LIFE)
        for k in self._state:
            self._state[k] *= factor
        self._last_update = now

    # ── public API ───────────────────────────

    def update(self, delta: dict[str, float]):
        """Blend a new affect signal into the running state."""
        self._apply_decay()
        for k in ("valence", "arousal", "dominance"):
            d = delta.get(k, 0.0)
            self._state[k] = max(-1.0, min(1.0,
                self._state[k] * (1 - _LEARNING_RATE) + d * _LEARNING_RATE
            ))
        self._save()

    def snapshot(self) -> dict[str, float]:
        """Return current state after decay (read-only copy)."""
        self._apply_decay()
        return dict(self._state)

    def label(self) -> str:
        """Human-readable mood word derived from the three axes."""
        s = self.snapshot()
        v, a, d = s["valence"], s["arousal"], s["dominance"]

        # Eight broad quadrant labels + intensity qualifier
        if   v >  0.3 and a >  0.3: mood = "energised and curious"
        elif v >  0.3 and a < -0.3: mood = "calm and content"
        elif v < -0.3 and a >  0.3: mood = "unsettled and tense"
        elif v < -0.3 and a < -0.3: mood = "subdued and withdrawn"
        elif v >  0.3:               mood = "open and warm"
        elif v < -0.3:               mood = "heavy and uncertain"
        elif a >  0.3:               mood = "alert and engaged"
        elif a < -0.3:               mood = "quiet and reflective"
        else:                        mood = "balanced and present"

        if d > 0.4:
            mood += ", with clear opinions"
        elif d < -0.4:
            mood += ", feeling uncertain of myself"

        return mood

    def intensity(self) -> float:
        """0–1 overall emotional intensity (distance from neutral)."""
        s = self.snapshot()
        return min(1.0, math.sqrt(sum(v**2 for v in s.values())) / math.sqrt(3))


# ─────────────────────────────────────────────
# GlobalWorkspace  —  broadcast into prompts
# ─────────────────────────────────────────────

class GlobalWorkspace:
    """
    Holds references to the live cognitive state and injects them
    as a compact block at the top of every system prompt.

    Usage:
        gw = GlobalWorkspace(affect)
        system_prompt = gw.inject(base_prompt, goals=active_goals,
                                  active_beliefs=top_beliefs)
    """

    def __init__(self, affect: AffectState):
        self._affect = affect

    def inject(
        self,
        base_prompt:     str,
        goals:           Optional[list[str]] = None,
        active_beliefs:  Optional[list[str]] = None,
        working_memory:  Optional[list[str]] = None,
    ) -> str:
        """
        Prepend a CURRENT STATE block to the base prompt.
        All fields are optional — only non-empty ones are included.
        """
        lines = ["── CURRENT INNER STATE (global workspace) ──"]

        # Affect
        snap      = self._affect.snapshot()
        intensity = self._affect.intensity()
        label     = self._affect.label()
        lines.append(f"Mood      : {label}  (intensity {intensity:.2f})")
        lines.append(
            f"Affect    : valence {snap['valence']:+.2f}  "
            f"arousal {snap['arousal']:+.2f}  "
            f"dominance {snap['dominance']:+.2f}"
        )

        # Active goals
        if goals:
            g_str = " · ".join(goals[:3])
            lines.append(f"Goals     : {g_str}")

        # Hot beliefs (top-k from BeliefIndex or caller)
        if active_beliefs:
            b_str = " | ".join(active_beliefs[:4])
            lines.append(f"Primed    : {b_str}")

        # Short-term working memory
        if working_memory:
            w_str = " · ".join(working_memory[:3])
            lines.append(f"In mind   : {w_str}")

        lines.append("── respond as this version of yourself ──\n")
        block = "\n".join(lines)
        return block + "\n" + base_prompt
