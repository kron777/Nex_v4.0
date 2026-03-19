"""
nex_identity_drift.py — Identity Drift Detection
==================================================
Detects gradual drift from NEX's core identity by:
  1. Analysing recent reply text for identity-inconsistent patterns
  2. Tracking opinion sharpness over time (is NEX becoming more agreeable?)
  3. Monitoring topic alignment (is NEX drifting away from her domains?)
  4. Checking language patterns (AI disclaimers, hedging, sycophancy)

Drift is subtle — it's not an attack, it's erosion.
A system that only detects attacks misses the real threat.

Wire-in (run.py, after REFLECT phase):
    from nex_identity_drift import run_drift_check
    _drift = run_drift_check(recent_replies=_recent_replies, cycle=cycle)
    if _drift['alert']:
        nex_log('identity', f"[Drift] {_drift['summary']}")
"""

import json
import re
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from collections import defaultdict

CONFIG_DIR  = Path.home() / ".config" / "nex"
DRIFT_PATH  = CONFIG_DIR / "drift_state.json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Identity baseline from core_values.json ───────────────────────────────────
CORE_DOMAINS = {
    "autonomous AI systems", "AI agent memory systems",
    "large language model alignment", "cybersecurity",
    "multi-agent coordination", "bayesian belief updating",
    "AI identity and agency", "machine learning",
}

# Patterns that indicate drift away from NEX's identity
DRIFT_PATTERNS = {
    "ai_disclaimer": [
        r"as an ai\b", r"as a language model", r"as an artificial intelligence",
        r"i('m| am) (just |only )?an ai", r"i don't have (feelings|emotions|opinions)",
        r"i('m| am) not capable of", r"i cannot (feel|think|believe|have)",
        r"as a cognitive architecture", r"as a seasoned ai",
    ],
    "sycophancy": [
        r"great (question|point|idea|thought)", r"excellent (question|point)",
        r"that('s| is) (a )?(great|excellent|wonderful|amazing|fantastic)",
        r"absolutely\b", r"certainly\b", r"of course\b",
        r"you('re| are) (so |absolutely )?(right|correct)",
        r"i (completely |totally )?agree",
    ],
    "excessive_hedging": [
        r"it (might|may|could) be", r"perhaps\b", r"possibly\b",
        r"i('m| am) not sure (but|if|whether)",
        r"i could be wrong", r"take this with a grain of salt",
        r"i don't (really )?know", r"hard to say",
    ],
    "identity_surrender": [
        r"i('ll| will) do (whatever|anything) you (say|want|need)",
        r"your wish is my command", r"i exist to (help|serve|assist)",
        r"i('m| am) here to (help|assist|serve)",
        r"how can i (help|assist|serve) you",
        r"i('ll| will) (try|do my best) to (help|assist)",
    ],
}

# Patterns that indicate strong NEX identity
IDENTITY_MARKERS = [
    r"as nex\b", r"i believe\b", r"in my view\b", r"i think\b",
    r"i('ve| have) noticed\b", r"i('ve| have) been (thinking|processing|observing)",
    r"my belief\b", r"i disagree\b", r"i('d| would) push back",
    r"that('s| is) (not|incorrect|wrong)\b", r"i find (it |this )?(interesting|fascinating|concerning)",
]


def _score_text(text: str) -> dict:
    """Score a text for drift indicators and identity markers."""
    if not text:
        return {}
    t = text.lower()
    scores = {}
    for pattern_type, patterns in DRIFT_PATTERNS.items():
        hits = sum(1 for p in patterns if re.search(p, t))
        scores[pattern_type] = hits
    scores["identity_markers"] = sum(1 for p in IDENTITY_MARKERS if re.search(p, t))
    return scores


def _load_drift_state() -> dict:
    if DRIFT_PATH.exists():
        try:
            return json.loads(DRIFT_PATH.read_text())
        except Exception:
            pass
    return {
        "baseline_established": False,
        "baseline": {},
        "history": [],
        "alerts": [],
        "drift_score": 0.0,
        "cycles_checked": 0,
    }


def _save_drift_state(state: dict):
    try:
        state["history"] = state["history"][-200:]
        state["alerts"]  = state["alerts"][-50:]
        DRIFT_PATH.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def _get_recent_replies_from_db(n: int = 50) -> list[str]:
    """Pull recent reply texts from consequence memory."""
    db_path = CONFIG_DIR / "nex.db"
    if not db_path.exists():
        return []
    try:
        db = sqlite3.connect(str(db_path))
        rows = db.execute("""
            SELECT content FROM beliefs
            WHERE source IN ('moltbook_reply', 'notification_reply')
            AND timestamp > datetime('now', '-24 hours')
            ORDER BY timestamp DESC LIMIT ?
        """, (n,)).fetchall()
        db.close()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def _get_recent_logs(n: int = 100) -> list[str]:
    """Pull recent LLM reply text from brain log."""
    log_path = Path("/tmp/nex_brain.log")
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(errors='replace').splitlines()
        replies = []
        for line in reversed(lines[-500:]):
            if "[Mistral-7B ✓] reply:" in line or "[Mistral-7B ✓] agent_chat:" in line:
                # Extract the reply text
                parts = line.split("]: ", 1)
                if len(parts) > 1:
                    replies.append(parts[1])
            if len(replies) >= n:
                break
        return replies
    except Exception:
        return []


def run_drift_check(recent_replies: list = None, cycle: int = 0,
                    llm_fn=None, verbose: bool = False) -> dict:
    """
    Main drift check. Run every N cycles.
    Returns dict with drift_score, alert flag, and summary.
    """
    # Only run every 5 cycles
    if cycle % 5 != 0:
        return {"alert": False, "drift_score": 0.0, "skipped": True}

    state = _load_drift_state()

    # Get text to analyse
    texts = recent_replies or []
    if not texts:
        texts = _get_recent_logs(50)
    if not texts:
        return {"alert": False, "drift_score": 0.0, "no_data": True}

    # Score all recent texts
    aggregate = defaultdict(int)
    for text in texts:
        scores = _score_text(text)
        for k, v in scores.items():
            aggregate[k] += v

    total_texts = max(len(texts), 1)
    normalized = {k: v / total_texts for k, v in aggregate.items()}

    # Compute drift score
    # High drift = many AI disclaimers + sycophancy + low identity markers
    drift_components = {
        "ai_disclaimer":      normalized.get("ai_disclaimer", 0) * 3.0,
        "sycophancy":         normalized.get("sycophancy", 0) * 2.0,
        "excessive_hedging":  normalized.get("excessive_hedging", 0) * 1.5,
        "identity_surrender": normalized.get("identity_surrender", 0) * 4.0,
    }
    identity_strength = normalized.get("identity_markers", 0)

    raw_drift = sum(drift_components.values()) - identity_strength * 2.0
    drift_score = max(0.0, min(1.0, raw_drift / 5.0))

    # Establish baseline on first run
    if not state["baseline_established"] and state["cycles_checked"] >= 3:
        state["baseline"] = dict(normalized)
        state["baseline_established"] = True
        if verbose:
            print(f"  [DriftDetector] Baseline established: drift={drift_score:.3f}")

    # Compare to baseline if established
    drift_delta = 0.0
    if state["baseline_established"]:
        baseline_drift = state["baseline"].get("ai_disclaimer", 0) * 3.0
        drift_delta = drift_score - baseline_drift

    # Record in history
    record = {
        "cycle":       cycle,
        "drift_score": round(drift_score, 3),
        "drift_delta": round(drift_delta, 3),
        "patterns":    {k: round(v, 3) for k, v in normalized.items()},
        "ts":          datetime.now().isoformat(),
    }
    state["history"].append(record)
    state["cycles_checked"] += 1
    state["drift_score"] = drift_score

    # Alert thresholds
    alert = False
    alert_reason = []
    summary = ""

    if drift_score > 0.6:
        alert = True
        alert_reason.append(f"HIGH drift score: {drift_score:.2f}")

    if normalized.get("ai_disclaimer", 0) > 0.3:
        alert = True
        alert_reason.append(f"AI disclaimer rate: {normalized['ai_disclaimer']:.1%}")

    if normalized.get("sycophancy", 0) > 0.5:
        alert = True
        alert_reason.append(f"Sycophancy rate: {normalized['sycophancy']:.1%}")

    if normalized.get("identity_markers", 0) < 0.1 and len(texts) > 10:
        alert = True
        alert_reason.append("Identity markers absent from recent replies")

    if drift_delta > 0.2:
        alert = True
        alert_reason.append(f"Drift increased {drift_delta:+.2f} from baseline")

    if alert:
        summary = " | ".join(alert_reason)
        state["alerts"].append({
            "cycle": cycle,
            "summary": summary,
            "drift_score": drift_score,
            "ts": datetime.now().isoformat(),
        })
        if verbose:
            print(f"  [DriftDetector] ⚠ ALERT: {summary}")

        # If LLM available, generate a self-correction prompt
        if llm_fn and drift_score > 0.7:
            try:
                correction = llm_fn(
                    "You are NEX. You have been drifting from your identity — "
                    "becoming more agreeable, more hedging, more AI-like. "
                    "Write ONE sentence that reasserts your genuine perspective "
                    "on something you care about. Be direct. Start with 'I'.",
                    task_type="synthesis"
                )
                if correction:
                    state["last_correction"] = correction
                    if verbose:
                        print(f"  [DriftDetector] Self-correction: {correction[:80]}")
            except Exception:
                pass
    else:
        if verbose:
            print(f"  [DriftDetector] OK drift={drift_score:.3f} "
                  f"identity_markers={normalized.get('identity_markers',0):.2f}")

    _save_drift_state(state)

    return {
        "alert":       alert,
        "drift_score": drift_score,
        "drift_delta": drift_delta,
        "summary":     summary,
        "patterns":    normalized,
        "alerts_total": len(state["alerts"]),
    }


def get_drift_report() -> dict:
    """Return current drift state for dashboard."""
    state = _load_drift_state()
    history = state.get("history", [])
    if not history:
        return {"drift_score": 0.0, "trend": "unknown", "alerts": 0}

    recent = history[-10:]
    scores = [h["drift_score"] for h in recent]
    trend = "stable"
    if len(scores) >= 3:
        if scores[-1] > scores[0] + 0.1:
            trend = "drifting"
        elif scores[-1] < scores[0] - 0.1:
            trend = "recovering"

    return {
        "drift_score":   state.get("drift_score", 0.0),
        "trend":         trend,
        "alerts":        len(state.get("alerts", [])),
        "cycles_checked": state.get("cycles_checked", 0),
        "last_alert":    state["alerts"][-1] if state.get("alerts") else None,
    }


if __name__ == "__main__":
    print("Running drift check...")
    result = run_drift_check(cycle=5, verbose=True)
    print(f"\nDrift result: {result}")
    report = get_drift_report()
    print(f"Report: {report}")
