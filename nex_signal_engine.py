"""
nex_signal_engine.py — NEX v4.1 Signal Engine
===============================================
Decision layer, fast-path mode, top-signal extraction,
low-value filter, confidence drift, outcome tracker.

Deploy: ~/Desktop/nex/nex_signal_engine.py

Wire into run.py:
    from nex_signal_engine import get_signal_engine
    _se = get_signal_engine()
    _se.init()

    # Gate low-value signals before processing:
    if _se.should_process(confidence=c, tension=t):
        ...

    # After cognition cycle, extract top signals:
    _se.tick(cycle=cycle, beliefs=belief_list, log_fn=nex_log)

    # Record outcome after a reply/trade/action:
    _se.record_outcome(signal_id=sid, win=True, pnl=0.0)
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

_CFG  = Path.home() / ".config" / "nex"
_DB   = _CFG / "nex.db"
_CFG.mkdir(parents=True, exist_ok=True)

_STATS_PATH   = _CFG / "signal_stats.json"
_SIGNALS_PATH = _CFG / "top_signals.json"

_G  = "\033[92m"; _Y = "\033[93m"; _CY = "\033[96m"
_D  = "\033[2m";  _RS = "\033[0m"

# ── Config ────────────────────────────────────────────────────
FAST_MODE               = False   # set True for trading / low-latency mode
EDGE_THRESHOLD          = 0.6     # min edge to act (confidence * tension)
LOW_VALUE_CONF_FLOOR    = 0.4     # skip if conf < this AND tension < this
LOW_VALUE_TENSION_FLOOR = 0.4
TOP_N_SIGNALS           = 3       # extract top N per cycle
CONFIDENCE_DRIFT_RATE   = 0.98    # passive decay multiplier per cycle
CONFIDENCE_USE_BOOST    = 0.05    # boost on successful use
DRIFT_INTERVAL          = 5       # apply drift every N cycles


# =============================================================================
# 1. DECISION LAYER
# =============================================================================

def build_decision(signal: dict) -> dict:
    """
    Convert a signal dict into a clear action decision.
    Kills hesitation — forces clarity.

    signal keys: confidence, tension, direction, reason
    Returns: action, confidence, tension, edge, reason
    """
    conf      = float(signal.get("confidence", 0.0))
    tension   = float(signal.get("tension",    0.0))
    direction = signal.get("direction", "HOLD")
    reason    = signal.get("reason", "")[:120]

    edge = round(conf * tension, 4)

    action = direction if edge > EDGE_THRESHOLD else "SKIP"

    return {
        "action":     action,
        "confidence": conf,
        "tension":    tension,
        "edge":       edge,
        "reason":     reason,
        "ts":         datetime.now().isoformat(),
    }


# =============================================================================
# 2. LOW-VALUE FILTER
# =============================================================================

def should_process(confidence: float, tension: float) -> bool:
    """
    Returns False if signal is too weak to be worth processing.
    Gate this before any heavy cognition operation.
    """
    if confidence < LOW_VALUE_CONF_FLOOR and tension < LOW_VALUE_TENSION_FLOOR:
        return False
    return True


# =============================================================================
# 3. TOP-SIGNAL EXTRACTION
# =============================================================================

def extract_top_signals(signals: list[dict], n: int = TOP_N_SIGNALS) -> list[dict]:
    """
    From a list of signal dicts, return top N by edge score.
    Discard the rest — forces selectivity.
    """
    scored = []
    for s in signals:
        if "edge" not in s:
            s = build_decision(s)
        scored.append(s)
    scored.sort(key=lambda x: x.get("edge", 0.0), reverse=True)
    return scored[:n]


def beliefs_to_signals(beliefs: list[dict]) -> list[dict]:
    """
    Convert belief dicts into signal format for decision processing.
    Uses confidence as signal confidence, topic tension as tension proxy.
    """
    signals = []
    for b in beliefs:
        conf    = float(b.get("confidence", 0.5))
        # Use decay_score as inverse tension proxy, tags for direction
        tags    = b.get("tags", "")
        tension = 0.5
        if isinstance(tags, str):
            if "contradiction" in tags or "tension" in tags:
                tension = 0.8
            elif "synthesis" in tags or "insight" in tags:
                tension = 0.7
            elif "dream" in tags:
                tension = 0.6

        direction = "ACT"
        if "antithesis" in (b.get("content") or "").lower():
            direction = "REVIEW"
        elif conf < 0.4:
            direction = "SKIP"

        signals.append({
            "id":         b.get("id", 0),
            "confidence": conf,
            "tension":    tension,
            "direction":  direction,
            "reason":     (b.get("content") or "")[:120],
            "topic":      b.get("topic", "general"),
        })
    return signals


# =============================================================================
# 4. CONFIDENCE DRIFT
# =============================================================================

class ConfidenceDrift:
    """
    Slow passive decay on all beliefs each N cycles.
    Boost on successful use.
    Prevents stale beliefs dominating.
    """

    def tick(self, cycle: int, log_fn=None) -> dict:
        if cycle % DRIFT_INTERVAL != 0:
            return {}
        if not _DB.exists():
            return {}
        try:
            db = sqlite3.connect(str(_DB))
            # Passive decay — multiply confidence by drift rate
            db.execute("""
                UPDATE beliefs
                SET confidence = MAX(confidence * ?, 0.05)
                WHERE human_validated = 0
                  AND confidence > 0.05
                  AND (origin NOT IN ('identity_core','dream_inversion') OR origin IS NULL)
            """, (CONFIDENCE_DRIFT_RATE,))
            decayed = db.execute("SELECT changes()").fetchone()[0]
            db.commit()
            db.close()
            if decayed > 0 and log_fn:
                log_fn("drift", f"[ConfidenceDrift] decayed {decayed} beliefs ×{CONFIDENCE_DRIFT_RATE}")
            return {"decayed": decayed}
        except Exception as e:
            print(f"  [ConfidenceDrift] error: {e}")
            return {}

    def boost(self, belief_id: int = None, content: str = None):
        """Call after a belief is used successfully."""
        if not _DB.exists():
            return
        try:
            db = sqlite3.connect(str(_DB))
            if belief_id is not None:
                db.execute("""
                    UPDATE beliefs
                    SET confidence = MIN(confidence + ?, 0.97)
                    WHERE id = ?
                """, (CONFIDENCE_USE_BOOST, belief_id))
            elif content:
                db.execute("""
                    UPDATE beliefs
                    SET confidence = MIN(confidence + ?, 0.97)
                    WHERE content = ?
                """, (CONFIDENCE_USE_BOOST, content.strip()))
            db.commit()
            db.close()
        except Exception:
            pass


# =============================================================================
# 5. OUTCOME TRACKER
# =============================================================================

class OutcomeTracker:
    """
    Lightweight win/loss/pnl tracker per signal.
    Persists to JSON. Builds real edge over time.
    """

    def __init__(self):
        self._stats: dict[str, dict] = {}
        self._load()

    def _load(self):
        if _STATS_PATH.exists():
            try:
                self._stats = json.loads(_STATS_PATH.read_text())
            except Exception:
                self._stats = {}

    def _save(self):
        try:
            _STATS_PATH.write_text(json.dumps(self._stats, indent=2))
        except Exception:
            pass

    def record(self, signal_id: str, win: bool, pnl: float = 0.0):
        sid = str(signal_id)
        if sid not in self._stats:
            self._stats[sid] = {"wins": 0, "losses": 0, "pnl": 0.0}
        if win:
            self._stats[sid]["wins"] += 1
        else:
            self._stats[sid]["losses"] += 1
        self._stats[sid]["pnl"] = round(self._stats[sid]["pnl"] + pnl, 4)
        self._save()

    def win_rate(self, signal_id: str) -> float:
        s = self._stats.get(str(signal_id), {})
        total = s.get("wins", 0) + s.get("losses", 0)
        return s["wins"] / total if total > 0 else 0.0

    def top_signals(self, n=5) -> list[dict]:
        ranked = []
        for sid, s in self._stats.items():
            total = s["wins"] + s["losses"]
            if total == 0:
                continue
            ranked.append({
                "id":       sid,
                "wins":     s["wins"],
                "losses":   s["losses"],
                "pnl":      s["pnl"],
                "win_rate": round(s["wins"] / total, 3),
                "total":    total,
            })
        ranked.sort(key=lambda x: (x["pnl"], x["win_rate"]), reverse=True)
        return ranked[:n]

    def status(self) -> dict:
        total_signals = len(self._stats)
        total_wins    = sum(s["wins"]   for s in self._stats.values())
        total_losses  = sum(s["losses"] for s in self._stats.values())
        total_pnl     = sum(s["pnl"]    for s in self._stats.values())
        total_trades  = total_wins + total_losses
        return {
            "signals_tracked": total_signals,
            "total_trades":    total_trades,
            "win_rate":        round(total_wins / total_trades, 3) if total_trades else 0.0,
            "total_pnl":       round(total_pnl, 4),
            "top":             self.top_signals(3),
        }


# =============================================================================
# 6. FAST-PATH MODE GATE
# =============================================================================

def fast_mode_active() -> bool:
    return FAST_MODE

def set_fast_mode(enabled: bool):
    global FAST_MODE
    FAST_MODE = enabled
    print(f"  {_Y}[SignalEngine] FAST_MODE={'ON' if enabled else 'OFF'}{_RS}")


# =============================================================================
# MASTER — SIGNAL ENGINE
# =============================================================================

class SignalEngine:

    def __init__(self):
        self.drift   = ConfidenceDrift()
        self.tracker = OutcomeTracker()
        self._last_top_signals: list[dict] = []
        self._cycle_signals:    list[dict] = []
        self._initialised = False

    def init(self):
        if self._initialised:
            return
        self._initialised = True
        print(f"  {_CY}[SignalEngine] v4.1 — initialised{_RS}")
        mode = "FAST" if FAST_MODE else "NORMAL"
        print(f"  {_D}[SignalEngine] mode={mode} edge_threshold={EDGE_THRESHOLD} "
              f"top_n={TOP_N_SIGNALS}{_RS}")

    def tick(self, cycle: int, beliefs: list[dict] = None,
             log_fn=None) -> dict:
        results = {}

        # 1. Confidence drift
        results["drift"] = self.drift.tick(cycle=cycle, log_fn=log_fn)

        # 2. Build + filter signals from beliefs
        if beliefs:
            raw_signals = beliefs_to_signals(beliefs)

            # Apply low-value filter
            filtered = [
                s for s in raw_signals
                if should_process(s["confidence"], s["tension"])
            ]

            # Fast mode: skip deep processing flag
            if FAST_MODE:
                filtered = [s for s in filtered if s["confidence"] >= 0.5]

            # Build decisions
            decisions = [build_decision(s) for s in filtered]

            # Extract top signals
            self._last_top_signals = extract_top_signals(decisions, n=TOP_N_SIGNALS)
            self._cycle_signals    = decisions
            results["top_signals"] = len(self._last_top_signals)
            results["filtered_out"] = len(raw_signals) - len(filtered)

            # Persist top signals
            try:
                _SIGNALS_PATH.write_text(json.dumps(
                    self._last_top_signals, indent=2))
            except Exception:
                pass

            # Log top signal if it has real edge
            if self._last_top_signals:
                top = self._last_top_signals[0]
                if top["edge"] > EDGE_THRESHOLD and log_fn:
                    log_fn("signal", f"[Signal] TOP: {top['action']} "
                           f"edge={top['edge']:.3f} conf={top['confidence']:.2f} "
                           f"→ {top['reason'][:60]}")

        return results

    # ── External hooks ────────────────────────────────────────

    def should_process(self, confidence: float, tension: float) -> bool:
        return should_process(confidence, tension)

    def build_decision(self, signal: dict) -> dict:
        return build_decision(signal)

    def record_outcome(self, signal_id, win: bool, pnl: float = 0.0):
        self.tracker.record(signal_id, win, pnl)
        if win:
            # Boost the belief that generated this signal
            try:
                sid = int(signal_id)
                self.drift.boost(belief_id=sid)
            except Exception:
                pass

    def get_top_signals(self) -> list[dict]:
        return self._last_top_signals

    def skip_deep_dive(self) -> bool:
        """Returns True if deep dive should be skipped (fast mode or low energy)."""
        return FAST_MODE

    def status(self) -> dict:
        return {
            "fast_mode":    FAST_MODE,
            "top_signals":  self._last_top_signals[:3],
            "outcome":      self.tracker.status(),
        }


# ── Singleton ─────────────────────────────────────────────────
_instance: Optional[SignalEngine] = None

def get_signal_engine() -> SignalEngine:
    global _instance
    if _instance is None:
        _instance = SignalEngine()
    return _instance


# =============================================================================
# RUN.PY PATCH NOTES
# Handled by run_py_se_wire.py — see below
# =============================================================================

if __name__ == "__main__":
    print("Testing SignalEngine...\n")
    se = SignalEngine()
    se.init()

    # Test decision layer
    sig = {"confidence": 0.8, "tension": 0.9, "direction": "BUY", "reason": "strong AI belief cluster"}
    print(f"Decision: {build_decision(sig)}\n")

    # Test low-value filter
    print(f"should_process(0.3, 0.3): {should_process(0.3, 0.3)}")
    print(f"should_process(0.7, 0.5): {should_process(0.7, 0.5)}\n")

    # Test outcome tracker
    se.record_outcome("test_1", win=True, pnl=0.05)
    se.record_outcome("test_1", win=False, pnl=-0.02)
    print(f"Outcome stats: {se.tracker.status()}\n")

    print(f"Status: {se.status()}")
