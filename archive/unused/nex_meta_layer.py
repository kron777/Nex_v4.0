"""
nex_meta_layer.py — Module Performance Tracking
=================================================
Tracks which modules are contributing to NEX's cognition
and which are silent, failing, or underperforming.

Meta log structure per module:
    {
        module:           str,
        calls:            int,
        successes:        int,
        failures:         int,
        last_success:     str,
        last_failure:     str,
        avg_output_value: float,  # estimated value of outputs
        suppressed:       bool,   # auto-suppressed if consistently failing
    }

Wire-in (run.py, after each module block):
    from nex_meta_layer import record_module_call, get_meta_report
    record_module_call("nex_belief_mutation", success=True, value=_mut.get("total",0))

Or batch update from log parsing:
    from nex_meta_layer import MetaLayer
    _ml = MetaLayer()
    _ml.parse_log_cycle(cycle=cycle)
"""

import json
import re
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from collections import defaultdict

CONFIG_DIR  = Path.home() / ".config" / "nex"
META_PATH   = CONFIG_DIR / "meta_state.json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Module registry — known modules and their expected log signatures ──────────
MODULE_SIGNATURES = {
    "nex_belief_survival":    [r"\[Survival\]", r"BeliefSurvival", r"killed.*amplified"],
    "nex_belief_mutation":    [r"\[Mutation\]", r"perturbed=", r"flipped="],
    "nex_cognitive_pressure": [r"\[CogPressure\]", r"p=[\d.]+", r"STALL"],
    "nex_tension_pressure":   [r"\[TensionPressure\]", r"escalated=", r"paradoxed="],
    "nex_tension":            [r"\[TensionMap\]", r"tensioned topics"],
    "nex_dream_cycle":        [r"\[DREAM\]", r"dream.*intuition", r"Dream.*outputs"],
    "nex_contradiction_engine": [r"\[CONTRA\]", r"Resolved.*contradiction", r"COGNITION.*Resolved"],
    "nex_curiosity_engine":   [r"\[CURIOSITY\]", r"\[curiosity\]", r"TYPE [ABC]"],
    "nex_desire_engine":      [r"\[DESIRE\]", r"dominant=", r"DesireEngine"],
    "nex_identity_drift":     [r"\[Drift\]", r"DRIFT", r"drift_score"],
    "nex_reflection_scoring": [r"\[Score\].*q=", r"REFLECT STATS", r"reflection.*score"],
    "nex_signal_filter":      [r"\[SignalFilter\]", r"SUPPRESSED:", r"source.*score"],
    "nex_event_importance":   [r"\[EventImportance\]", r"core=\d", r"peripheral=\d"],
    "nex_memory_manager":     [r"\[MEMORY\]", r"beliefs cleaned"],
    "nex_source_manager":     [r"\[sources\]", r"beliefs from.*domains"],
    "causal_engine":          [r"\[Causal\]", r"propagated.*belief", r"got_reply=True"],
    "rss_absorption":         [r"\[External\].*beliefs", r"from Reddit/RSS"],
    "llm_local":              [r"\[Mistral-7B ✓\]"],
    "llm_groq":               [r"\[Groq ✓\]", r"\[Groq-8b ✓\]"],
}

# Modules that should fire every cycle (alert if silent >10 cycles)
CRITICAL_MODULES = {
    "llm_local", "nex_belief_survival", "nex_tension_pressure",
    "nex_curiosity_engine", "nex_desire_engine",
}

# Value weights — how much does a successful call contribute?
MODULE_VALUE = {
    "llm_local":              1.0,
    "nex_dream_cycle":        0.9,
    "nex_contradiction_engine": 0.8,
    "nex_reflection_scoring": 0.8,
    "nex_desire_engine":      0.7,
    "nex_belief_mutation":    0.7,
    "nex_tension_pressure":   0.6,
    "causal_engine":          0.8,
    "nex_curiosity_engine":   0.6,
    "nex_identity_drift":     0.5,
    "rss_absorption":         0.5,
    "nex_cognitive_pressure": 0.5,
    "nex_belief_survival":    0.4,
    "nex_signal_filter":      0.4,
    "nex_event_importance":   0.4,
    "nex_memory_manager":     0.3,
}


class MetaLayer:
    """Tracks module performance and generates optimization recommendations."""

    def __init__(self):
        self._state = self._load()

    def _load(self) -> dict:
        if META_PATH.exists():
            try:
                return json.loads(META_PATH.read_text())
            except Exception:
                pass
        return {
            "modules": {},
            "cycles_tracked": 0,
            "last_updated": datetime.now().isoformat(),
            "suppressed": [],
            "alerts": [],
        }

    def _save(self):
        self._state["last_updated"] = datetime.now().isoformat()
        try:
            META_PATH.write_text(json.dumps(self._state, indent=2))
        except Exception:
            pass

    def _get_module(self, name: str) -> dict:
        if name not in self._state["modules"]:
            self._state["modules"][name] = {
                "calls":            0,
                "successes":        0,
                "failures":         0,
                "silent_cycles":    0,
                "last_success":     None,
                "last_failure":     None,
                "avg_output_value": 0.0,
                "suppressed":       False,
                "value_history":    [],
            }
        return self._state["modules"][name]

    def record_call(self, module: str, success: bool = True,
                    value: float = None, error: str = None):
        """Record a module call outcome."""
        m = self._get_module(module)
        m["calls"] += 1
        now = datetime.now().isoformat()

        if success:
            m["successes"] += 1
            m["silent_cycles"] = 0
            m["last_success"] = now
            if value is not None:
                base_value = MODULE_VALUE.get(module, 0.5)
                actual_value = min(1.0, base_value * (1 + value * 0.1))
                m["value_history"].append(actual_value)
                m["value_history"] = m["value_history"][-20:]
                m["avg_output_value"] = round(
                    sum(m["value_history"]) / len(m["value_history"]), 3
                )
        else:
            m["failures"] += 1
            m["last_failure"] = now
            if error:
                m["last_error"] = str(error)[:100]

        self._save()

    def parse_log_cycle(self, log_lines: list, cycle: int = 0) -> dict:
        """
        Parse a batch of log lines to detect which modules fired.
        Returns dict of {module: fired} for this cycle.
        """
        fired = set()
        log_text = "\n".join(log_lines)

        for module, patterns in MODULE_SIGNATURES.items():
            for pattern in patterns:
                if re.search(pattern, log_text, re.IGNORECASE):
                    fired.add(module)
                    break

        # Update all modules
        for module in MODULE_SIGNATURES:
            m = self._get_module(module)
            if module in fired:
                m["calls"] += 1
                m["successes"] += 1
                m["silent_cycles"] = 0
                m["last_success"] = datetime.now().isoformat()
                value = MODULE_VALUE.get(module, 0.5)
                m["value_history"].append(value)
                m["value_history"] = m["value_history"][-20:]
                m["avg_output_value"] = round(
                    sum(m["value_history"]) / len(m["value_history"]), 3
                )
            else:
                m["silent_cycles"] = m.get("silent_cycles", 0) + 1

        self._state["cycles_tracked"] += 1
        self._save()
        return {m: m in fired for m in MODULE_SIGNATURES}

    def get_performance_report(self) -> list[dict]:
        """Return modules sorted by performance score."""
        report = []
        for name, data in self._state["modules"].items():
            calls = data.get("calls", 0)
            if calls == 0:
                success_rate = 0.0
            else:
                success_rate = data.get("successes", 0) / calls

            performance = (
                success_rate * 0.4 +
                data.get("avg_output_value", 0) * 0.4 +
                (1.0 if data.get("silent_cycles", 0) < 5 else 0.0) * 0.2
            )

            report.append({
                "module":        name,
                "calls":         calls,
                "success_rate":  round(success_rate, 3),
                "avg_value":     data.get("avg_output_value", 0),
                "silent_cycles": data.get("silent_cycles", 0),
                "performance":   round(performance, 3),
                "suppressed":    data.get("suppressed", False),
            })

        return sorted(report, key=lambda x: -x["performance"])

    def get_alerts(self) -> list[str]:
        """Return list of current performance alerts."""
        alerts = []
        for name, data in self._state["modules"].items():
            silent = data.get("silent_cycles", 0)
            calls  = data.get("calls", 0)

            # Critical module silent for too long
            if name in CRITICAL_MODULES and silent > 10:
                alerts.append(f"SILENT: {name} hasn't fired in {silent} cycles")

            # High failure rate
            if calls >= 5:
                success_rate = data.get("successes", 0) / calls
                if success_rate < 0.3:
                    alerts.append(f"FAILING: {name} success_rate={success_rate:.0%}")

        return alerts

    def get_top_performers(self, n: int = 5) -> list[dict]:
        report = self.get_performance_report()
        return [r for r in report if not r["suppressed"]][:n]

    def get_underperformers(self, n: int = 5) -> list[dict]:
        report = self.get_performance_report()
        return sorted(report, key=lambda x: x["performance"])[:n]

    def summary(self) -> str:
        report = self.get_performance_report()
        active = sum(1 for r in report if r["silent_cycles"] < 5)
        total  = len(report)
        alerts = self.get_alerts()
        alert_str = f" ⚠ {len(alerts)} alerts" if alerts else ""
        return f"{active}/{total} modules active{alert_str}"


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance = None

def get_meta_layer() -> MetaLayer:
    global _instance
    if _instance is None:
        _instance = MetaLayer()
    return _instance

def record_module_call(module: str, success: bool = True,
                       value: float = None, error: str = None):
    get_meta_layer().record_call(module, success, value, error)


if __name__ == "__main__":
    ml = MetaLayer()
    # Simulate some calls
    ml.record_call("llm_local", success=True, value=10)
    ml.record_call("nex_dream_cycle", success=True, value=5)
    ml.record_call("nex_contradiction_engine", success=False, error="timeout")

    print("Performance report:")
    for r in ml.get_performance_report()[:8]:
        print(f"  [{r['performance']:.2f}] {r['module']:35s} "
              f"calls={r['calls']} rate={r['success_rate']:.0%} "
              f"silent={r['silent_cycles']}")

    alerts = ml.get_alerts()
    if alerts:
        print(f"\nAlerts: {alerts}")

    print(f"\nSummary: {ml.summary()}")
