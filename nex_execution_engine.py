"""
nex_execution_engine.py — NEX v4.2→v5.0 Execution Engine
==========================================================
Completes the full loop: Signal → Filter → Decide → Execute → Learn → Adapt

Layers:
  1. Direction Resolver     — fixes TYPE:NONE permanently
  2. Decision Normalizer    — standardizes output shape
  3. Trade Gate             — final authority before execution
  4. Position Sizer         — dynamic sizing by edge
  5. Time Exit              — max hold enforcement
  6. Loss Cooldown          — post-loss pause
  7. Bad Signal Suppressor  — weight decay on losers
  8. Adaptive Threshold     — self-tuning edge floor
  9. Regime Detector        — FAST/SLOW market awareness
 10. Trade Frequency Control — throttle on overtrading
 11. No-Trade Tracker        — exploration vs exploitation
 12. Execution Logger        — full audit trail

Deploy: ~/Desktop/nex/nex_execution_engine.py

Wire into run.py (after _se tick block):
    from nex_execution_engine import get_execution_engine
    _ee = get_execution_engine()
    _ee.init()
    _ee.tick(cycle=cycle, signals=_se.get_top_signals(), log_fn=nex_log)
"""

from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

_CFG = Path.home() / ".config" / "nex"
_CFG.mkdir(parents=True, exist_ok=True)

_EXEC_LOG_PATH     = _CFG / "execution_log.json"
_EXEC_STATE_PATH   = _CFG / "execution_state.json"
_SIGNAL_STATS_PATH = _CFG / "signal_stats.json"

_G  = "\033[92m"; _Y = "\033[93m"; _R = "\033[91m"
_CY = "\033[96m"; _D = "\033[2m";  _RS = "\033[0m"

# ── Default thresholds (self-tuning at runtime) ───────────────
EDGE_THRESHOLD_DEFAULT  = 0.65
TRADE_GATE_CONF_MIN     = 0.75
MAX_HOLD_CYCLES         = 180
LOSS_COOLDOWN_CYCLES    = 3
MAX_TRADES_PER_MINUTE   = 5
NO_TRADE_EXPLORE_AFTER  = 10
EXPLORE_THRESHOLD_DROP  = 0.05
BAD_SIGNAL_WEIGHT_DECAY = 0.7


# =============================================================================
# 1. DIRECTION RESOLVER
# =============================================================================

def resolve_direction(signal: dict) -> Optional[str]:
    """
    Converts ambiguous/None direction into usable signal.
    Eliminates TYPE:NONE and dead-end decisions permanently.
    """
    d = signal.get("direction", "")
    if d and d not in ("", "NONE", "TYPE: NONE", "HOLD", "ACT"):
        return d

    tension    = float(signal.get("tension",    0.0))
    confidence = float(signal.get("confidence", 0.0))

    if tension > 0.7:
        return "FADE"
    elif confidence > 0.8:
        return "FOLLOW"
    elif confidence > 0.6 and tension > 0.5:
        return "FOLLOW"
    return None   # genuinely no direction — caller should SKIP


# =============================================================================
# 2. DECISION NORMALIZER
# =============================================================================

def normalize_decision(signal: dict, edge_threshold: float = EDGE_THRESHOLD_DEFAULT) -> dict:
    """
    Standardizes signal → decision shape.
    Removes inconsistent decision shapes across the system.
    """
    direction = resolve_direction(signal)

    if direction is None:
        return {
            "action":     "SKIP",
            "direction":  None,
            "edge":       0.0,
            "confidence": float(signal.get("confidence", 0.0)),
            "reason":     signal.get("reason", "")[:120],
            "id":         signal.get("id", 0),
            "topic":      signal.get("topic", "general"),
        }

    conf    = float(signal.get("confidence", 0.0))
    tension = float(signal.get("tension",    0.0))
    edge    = round(conf * tension, 4)

    # Fast path: bypass analysis for very high conviction
    bypass = edge > 0.85 and conf > 0.9

    return {
        "action":     "ACT" if (edge > edge_threshold or bypass) else "SKIP",
        "direction":  direction,
        "edge":       edge,
        "confidence": conf,
        "tension":    tension,
        "reason":     signal.get("reason", "")[:120],
        "id":         signal.get("id", 0),
        "topic":      signal.get("topic", "general"),
        "bypass":     bypass,
    }


# =============================================================================
# 3. TRADE GATE (final authority)
# =============================================================================

def trade_gate(decision: dict, conf_min: float = TRADE_GATE_CONF_MIN,
               edge_min: float = EDGE_THRESHOLD_DEFAULT) -> bool:
    """
    Final yes/no before execution.
    Nothing passes without meeting ALL criteria.
    """
    if decision.get("action") == "SKIP":
        return False
    if decision.get("edge", 0.0) < edge_min:
        return False
    if decision.get("confidence", 0.0) < conf_min:
        return False
    if decision.get("direction") is None:
        return False
    return True


# =============================================================================
# 4. POSITION SIZER
# =============================================================================

def position_size(edge: float, base: float = 1.0) -> float:
    """
    Dynamic sizing by edge strength.
    Higher conviction = larger position.
    """
    if edge > 0.85:
        return round(base * 2.0, 3)
    elif edge > 0.75:
        return round(base * 1.5, 3)
    else:
        return round(base * 1.0, 3)


# =============================================================================
# 5. TIME EXIT
# =============================================================================

class TimeExitManager:
    """Tracks open positions and enforces max hold time."""

    def __init__(self, max_hold: int = MAX_HOLD_CYCLES):
        self.max_hold  = max_hold
        self._positions: dict[str, dict] = {}
        self.exits = 0

    def open(self, signal_id: str, direction: str, size: float, cycle: int):
        self._positions[str(signal_id)] = {
            "direction": direction,
            "size":      size,
            "opened_at": cycle,
            "ts":        datetime.now().isoformat(),
        }

    def check_exits(self, cycle: int) -> list[dict]:
        """Returns list of positions to close due to time exit."""
        to_close = []
        for sid, pos in list(self._positions.items()):
            age = cycle - pos["opened_at"]
            if age >= self.max_hold:
                to_close.append({"id": sid, **pos, "reason": "time_exit", "age": age})
                del self._positions[sid]
                self.exits += 1
        return to_close

    def close(self, signal_id: str):
        self._positions.pop(str(signal_id), None)

    def open_positions(self) -> dict:
        return dict(self._positions)

    def status(self) -> dict:
        return {"open": len(self._positions), "exits": self.exits}


# =============================================================================
# 6. LOSS COOLDOWN
# =============================================================================

class LossCooldown:
    """Pause after a loss to prevent revenge trading."""

    def __init__(self, cooldown: int = LOSS_COOLDOWN_CYCLES):
        self.cooldown         = cooldown
        self._remaining       = 0
        self.total_cooldowns  = 0

    def on_loss(self):
        self._remaining = self.cooldown
        self.total_cooldowns += 1

    def tick(self) -> bool:
        """Returns True if in cooldown (should skip trading)."""
        if self._remaining > 0:
            self._remaining -= 1
            return True
        return False

    def active(self) -> bool:
        return self._remaining > 0

    def status(self) -> dict:
        return {"remaining": self._remaining, "total": self.total_cooldowns}


# =============================================================================
# 7. BAD SIGNAL SUPPRESSOR
# =============================================================================

class BadSignalSuppressor:
    """Decay weight on signals with more losses than wins."""

    def __init__(self):
        self._weights: dict[str, float] = {}
        self._load()

    def _load(self):
        if _SIGNAL_STATS_PATH.exists():
            try:
                stats = json.loads(_SIGNAL_STATS_PATH.read_text())
                for sid, s in stats.items():
                    wins   = s.get("wins", 0)
                    losses = s.get("losses", 0)
                    if losses > wins and (wins + losses) >= 3:
                        self._weights[sid] = round(
                            self._weights.get(sid, 1.0) * BAD_SIGNAL_WEIGHT_DECAY, 3
                        )
            except Exception:
                pass

    def get_weight(self, signal_id: str) -> float:
        return self._weights.get(str(signal_id), 1.0)

    def apply(self, decision: dict) -> dict:
        """Multiply edge by suppression weight."""
        w = self.get_weight(str(decision.get("id", "")))
        if w < 1.0:
            decision = dict(decision)
            decision["edge"]     = round(decision.get("edge", 0.0) * w, 4)
            decision["suppressed"] = True
            decision["weight"]   = w
        return decision

    def refresh(self):
        """Reload weights from latest signal stats."""
        self._weights = {}
        self._load()

    def status(self) -> dict:
        suppressed = {k: v for k, v in self._weights.items() if v < 1.0}
        return {"suppressed_signals": len(suppressed), "weights": suppressed}


# =============================================================================
# 8. ADAPTIVE THRESHOLD
# =============================================================================

class AdaptiveThreshold:
    """
    Self-tuning edge floor based on recent win rate.
    Win rate < 50% → raise threshold (be more selective)
    Win rate > 60% → lower threshold (take more signals)
    """

    def __init__(self, base: float = EDGE_THRESHOLD_DEFAULT):
        self.base      = base
        self.current   = base
        self.adjustments = 0
        self._load()

    def _load(self):
        if _EXEC_STATE_PATH.exists():
            try:
                data = json.loads(_EXEC_STATE_PATH.read_text())
                self.current = float(data.get("edge_threshold", self.base))
            except Exception:
                pass

    def _save(self):
        try:
            data = {}
            if _EXEC_STATE_PATH.exists():
                try:
                    data = json.loads(_EXEC_STATE_PATH.read_text())
                except Exception:
                    pass
            data["edge_threshold"] = round(self.current, 4)
            _EXEC_STATE_PATH.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def update(self, wins: int, losses: int):
        total = wins + losses
        if total < 5:
            return   # not enough data
        winrate = wins / total
        if winrate < 0.5:
            self.current = min(self.current + 0.05, 0.90)
            self.adjustments += 1
        elif winrate > 0.6:
            self.current = max(self.current - 0.02, 0.50)
            self.adjustments += 1
        self._save()

    def get(self) -> float:
        return self.current

    def status(self) -> dict:
        return {"current": round(self.current, 4),
                "base": self.base, "adjustments": self.adjustments}


# =============================================================================
# 9. REGIME DETECTOR
# =============================================================================

class RegimeDetector:
    """
    Detects FAST/SLOW market regime from signal volatility.
    Adjusts edge threshold per regime.
    """
    FAST_THRESHOLD = 0.70
    SLOW_THRESHOLD = 0.60
    WINDOW         = 20

    def __init__(self):
        self._edge_history: deque = deque(maxlen=self.WINDOW)
        self.regime    = "SLOW"
        self.volatility = 0.0

    def update(self, edges: list[float]):
        for e in edges:
            self._edge_history.append(e)
        if len(self._edge_history) < 5:
            return
        vals = list(self._edge_history)
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        self.volatility = round(variance ** 0.5, 4)
        self.regime = "FAST" if self.volatility > 0.15 else "SLOW"

    def threshold(self) -> float:
        return self.FAST_THRESHOLD if self.regime == "FAST" else self.SLOW_THRESHOLD

    def status(self) -> dict:
        return {"regime": self.regime, "volatility": self.volatility,
                "threshold": self.threshold()}


# =============================================================================
# 10. TRADE FREQUENCY CONTROLLER
# =============================================================================

class TradeFrequencyController:
    """Throttle if too many trades fired in recent window."""

    def __init__(self, max_per_window: int = MAX_TRADES_PER_MINUTE,
                 window_cycles: int = 5):
        self.max_per_window = max_per_window
        self.window_cycles  = window_cycles
        self._recent: deque = deque(maxlen=window_cycles)
        self.throttled = 0

    def record_trade(self):
        self._recent.append(time.time())

    def throttled_now(self) -> bool:
        cutoff = time.time() - (self.window_cycles * 120)
        recent = [t for t in self._recent if t > cutoff]
        if len(recent) >= self.max_per_window:
            self.throttled += 1
            return True
        return False

    def status(self) -> dict:
        return {"recent_trades": len(self._recent), "throttled": self.throttled}


# =============================================================================
# 11. NO-TRADE TRACKER (exploration vs exploitation)
# =============================================================================

class NoTradeTracker:
    """
    If too many consecutive SKIPs → lower threshold slightly to explore.
    Prevents the system from freezing under overly strict filters.
    """

    def __init__(self, explore_after: int = NO_TRADE_EXPLORE_AFTER,
                 drop: float = EXPLORE_THRESHOLD_DROP):
        self.explore_after = explore_after
        self.drop          = drop
        self._count        = 0
        self.explorations  = 0

    def on_skip(self):
        self._count += 1

    def on_trade(self):
        self._count = 0

    def should_explore(self) -> bool:
        return self._count >= self.explore_after

    def exploration_bonus(self) -> float:
        """Returns threshold reduction if exploring."""
        if self.should_explore():
            self.explorations += 1
            return self.drop
        return 0.0

    def status(self) -> dict:
        return {"skip_count": self._count, "explorations": self.explorations,
                "exploring": self.should_explore()}


# =============================================================================
# 12. EXECUTION LOGGER
# =============================================================================

class ExecutionLogger:
    """Full audit trail of all decisions, trades, exits."""

    def __init__(self):
        self._log: list[dict] = []
        self._load()

    def _load(self):
        if _EXEC_LOG_PATH.exists():
            try:
                self._log = json.loads(_EXEC_LOG_PATH.read_text())[-500:]
            except Exception:
                self._log = []

    def _save(self):
        try:
            _EXEC_LOG_PATH.write_text(json.dumps(self._log[-500:], indent=2))
        except Exception:
            pass

    def log(self, event: str, data: dict):
        self._log.append({
            "ts":    datetime.now().isoformat(),
            "event": event,
            **data,
        })
        if len(self._log) % 10 == 0:
            self._save()

    def recent(self, n=10) -> list[dict]:
        return self._log[-n:]

    def status(self) -> dict:
        total  = len(self._log)
        trades = sum(1 for e in self._log if e.get("event") == "trade")
        skips  = sum(1 for e in self._log if e.get("event") == "skip")
        return {"total_events": total, "trades": trades, "skips": skips}


# =============================================================================
# MASTER — EXECUTION ENGINE
# =============================================================================

class ExecutionEngine:
    """
    Full execution loop: Signal → Normalize → Gate → Size → Execute → Log → Learn
    Single tick() call per cycle.
    """

    def __init__(self):
        self.time_exit   = TimeExitManager()
        self.cooldown    = LossCooldown()
        self.suppressor  = BadSignalSuppressor()
        self.threshold   = AdaptiveThreshold()
        self.regime      = RegimeDetector()
        self.freq_ctrl   = TradeFrequencyController()
        self.no_trade    = NoTradeTracker()
        self.logger      = ExecutionLogger()
        self._initialised = False
        self._cycle_trades: list[dict] = []

    def init(self):
        if self._initialised:
            return
        self._initialised = True
        print(f"  {_CY}[ExecutionEngine] v5.0 — initialised{_RS}")
        print(f"  {_D}[EE] gate · sizer · time_exit · cooldown · "
              f"suppressor · threshold · regime · freq · no_trade{_RS}")

    def tick(self, cycle: int, signals: list[dict] = None,
             log_fn=None) -> dict:
        results = {"trades": [], "skips": 0, "exits": []}
        if not signals:
            return results

        # Update regime from signal edges
        edges = [float(s.get("edge", s.get("confidence", 0.5) * 0.5))
                 for s in signals]
        self.regime.update(edges)

        # Regime-adjusted threshold
        base_threshold = self.regime.threshold()
        # Adaptive self-tuning on top
        threshold = self.threshold.get()
        # Exploration bonus if system has been skipping too long
        threshold -= self.no_trade.exploration_bonus()
        threshold  = max(0.50, min(threshold, 0.90))

        # Check time exits first
        exits = self.time_exit.check_exits(cycle)
        for ex in exits:
            results["exits"].append(ex)
            self.logger.log("time_exit", ex)
            if log_fn:
                log_fn("execution", f"[EE] TIME EXIT: {ex['id']} "
                       f"age={ex['age']} dir={ex['direction']}")

        # Cooldown tick
        in_cooldown = self.cooldown.tick()

        for raw_signal in signals:
            # Normalize decision
            decision = normalize_decision(raw_signal, edge_threshold=threshold)

            # Apply bad signal suppression
            decision = self.suppressor.apply(decision)

            # Skip checks
            if decision["action"] == "SKIP":
                self.no_trade.on_skip()
                results["skips"] += 1
                self.logger.log("skip", {
                    "id":     decision.get("id"),
                    "edge":   decision.get("edge"),
                    "reason": "low_edge",
                })
                continue

            if in_cooldown:
                self.no_trade.on_skip()
                results["skips"] += 1
                self.logger.log("skip", {"id": decision.get("id"), "reason": "cooldown"})
                continue

            if self.freq_ctrl.throttled_now():
                self.no_trade.on_skip()
                results["skips"] += 1
                self.logger.log("skip", {"id": decision.get("id"), "reason": "throttled"})
                continue

            # Final trade gate
            if not trade_gate(decision, edge_min=threshold):
                self.no_trade.on_skip()
                results["skips"] += 1
                self.logger.log("skip", {
                    "id":     decision.get("id"),
                    "edge":   decision.get("edge"),
                    "reason": "gate_rejected",
                })
                continue

            # Size the position
            size = position_size(decision["edge"])

            # Open position
            sid = str(decision.get("id", f"s{cycle}"))
            self.time_exit.open(sid, decision["direction"], size, cycle)
            self.freq_ctrl.record_trade()
            self.no_trade.on_trade()

            trade = {
                "id":        sid,
                "direction": decision["direction"],
                "edge":      decision["edge"],
                "confidence":decision["confidence"],
                "size":      size,
                "topic":     decision.get("topic", "general"),
                "reason":    decision.get("reason", "")[:80],
                "cycle":     cycle,
                "bypass":    decision.get("bypass", False),
            }
            results["trades"].append(trade)
            self.logger.log("trade", trade)

            msg = (f"[EE] TRADE: {decision['direction']} "
                   f"edge={decision['edge']:.3f} size={size} "
                   f"topic={decision.get('topic','?')[:20]}")
            print(f"  {_G}{msg}{_RS}")
            if log_fn:
                log_fn("execution", msg)

        self._cycle_trades = results["trades"]
        return results

    def on_outcome(self, signal_id: str, win: bool, pnl: float = 0.0,
                   log_fn=None):
        """Call after a trade resolves with outcome."""
        # Close position
        self.time_exit.close(signal_id)

        # Cooldown on loss
        if not win:
            self.cooldown.on_loss()

        # Update adaptive threshold
        stats = self._get_stats()
        self.threshold.update(stats["wins"], stats["losses"])

        # Refresh suppressor weights
        self.suppressor.refresh()

        # Log
        self.logger.log("outcome", {
            "id":  signal_id,
            "win": win,
            "pnl": pnl,
        })
        if log_fn:
            result = "WIN" if win else "LOSS"
            log_fn("execution", f"[EE] OUTCOME {result} id={signal_id} pnl={pnl:+.4f}")

    def _get_stats(self) -> dict:
        try:
            data = json.loads(_SIGNAL_STATS_PATH.read_text())
            wins   = sum(s.get("wins",   0) for s in data.values())
            losses = sum(s.get("losses", 0) for s in data.values())
            return {"wins": wins, "losses": losses}
        except Exception:
            return {"wins": 0, "losses": 0}

    def get_cycle_trades(self) -> list[dict]:
        return self._cycle_trades

    def status(self) -> dict:
        return {
            "threshold":  self.threshold.status(),
            "regime":     self.regime.status(),
            "cooldown":   self.cooldown.status(),
            "time_exit":  self.time_exit.status(),
            "freq_ctrl":  self.freq_ctrl.status(),
            "no_trade":   self.no_trade.status(),
            "suppressor": self.suppressor.status(),
            "log":        self.logger.status(),
        }


# ── Singleton ─────────────────────────────────────────────────
_instance: Optional[ExecutionEngine] = None

def get_execution_engine() -> ExecutionEngine:
    global _instance
    if _instance is None:
        _instance = ExecutionEngine()
    return _instance


if __name__ == "__main__":
    print("Testing ExecutionEngine...\n")
    ee = ExecutionEngine()
    ee.init()

    signals = [
        {"id": 1, "confidence": 0.9, "tension": 0.85, "direction": "FOLLOW",
         "reason": "strong AI cluster", "topic": "ai"},
        {"id": 2, "confidence": 0.5, "tension": 0.3, "direction": "",
         "reason": "weak signal", "topic": "general"},
        {"id": 3, "confidence": 0.8, "tension": 0.9, "direction": "FADE",
         "reason": "contradiction tension", "topic": "crypto"},
    ]

    result = ee.tick(cycle=1, signals=signals)
    print(f"Trades: {result['trades']}")
    print(f"Skips:  {result['skips']}")
    print(f"Status: {ee.status()}")
