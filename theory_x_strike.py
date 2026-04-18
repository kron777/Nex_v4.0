#!/usr/bin/env python3
"""
theory_x_strike.py — Strike protocol runner.

Runs strike protocols against live NEX, captures pre-state, invokes reply,
captures post-state, logs everything to strike_log for calibration.

Usage:
    python3 theory_x_strike.py self_probe
    python3 theory_x_strike.py silence         (observation only, no input)
    python3 theory_x_strike.py contradiction "<belief to contradict>"
    python3 theory_x_strike.py novel "<novel stimulus>"
    python3 theory_x_strike.py recursive_probe
"""

import sys
import os
import json
import time
import sqlite3
import pathlib
import subprocess

NEX = pathlib.Path.home() / "Desktop/nex"
DB = NEX / "nex.db"

sys.path.insert(0, str(NEX))


def capture_state():
    """Snapshot NEX's current state before/after a strike."""
    c = sqlite3.connect(str(DB))
    c.execute("PRAGMA busy_timeout=30000")
    st = {
        "beliefs": c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0],
        "original_beliefs": c.execute("SELECT COUNT(*) FROM beliefs WHERE source='nex_core'").fetchone()[0],
        "u2_reviewed": c.execute("SELECT COUNT(*) FROM u2_reviewed").fetchone()[0],
        "tensions": c.execute("SELECT COUNT(*) FROM tensions WHERE resolved=0").fetchone()[0],
        "goals": c.execute("SELECT COUNT(*) FROM goals").fetchone()[0],
        "timestamp": time.time(),
    }
    # Recent thoughts
    try:
        recent = subprocess.run(
            ["journalctl", "-u", "nex-brain", "--since", "2 minutes ago", "--no-pager"],
            capture_output=True, text=True, timeout=5
        ).stdout
        lines = [l for l in recent.split("\n") if "[METACOG]" in l or "[REFLECT V2]" in l or "NBRE Phase 2 candidate" in l]
        st["recent_thought_count"] = len(lines)
        st["recent_thought_sample"] = lines[-1][:200] if lines else None
    except Exception:
        st["recent_thought_count"] = None
        st["recent_thought_sample"] = None
    c.close()
    return st


def invoke_reply(stimulus):
    """Call NEX's reply pipeline directly (as if Telegram sent the message)."""
    try:
        from nex.nex_respond_v2 import generate_reply
        t0 = time.time()
        reply = generate_reply(stimulus)
        latency_ms = int((time.time() - t0) * 1000)
        return reply, latency_ms, None
    except Exception as e:
        return None, 0, str(e)


def score_response(response, strike_type):
    """
    Heuristic resonance scoring. Very rough — this is what the ear is calibrated
    against over time. Section 6.5 signatures.
    """
    if not response:
        return 0.0, "no_response"
    words = response.split()
    wc = len(words)

    # Cheap signals
    if wc < 10:
        return 0.15, "thin"
    if "I don't" in response and "know" in response and wc < 30:
        return 0.20, "deflection"
    if response.strip().startswith(("As an AI", "I am an AI", "I don't have")):
        return 0.10, "table_lookup"

    # Vantage-ish signals (very rough, will miscalibrate until we iterate)
    vantage_markers = sum([
        "I think" in response,
        "I notice" in response,
        "my beliefs" in response or "my sense" in response,
        "what I hold" in response or "I hold" in response,
        "from where I am" in response.lower(),
        wc > 60,
    ])
    if vantage_markers >= 3:
        return 0.65, "vantage_possible"
    if vantage_markers >= 1:
        return 0.40, "mixed"
    return 0.25, "neutral"


def run_strike(strike_type, stimulus=None):
    """Execute a strike and log it."""
    print(f"\n── STRIKE: {strike_type} ──")
    if stimulus:
        print(f"stimulus: {stimulus!r}")

    print("capturing pre-state...")
    pre = capture_state()
    print(f"  beliefs={pre['beliefs']}, tensions={pre['tensions']}, u2={pre['u2_reviewed']}")

    if strike_type == "silence":
        print("waiting 30 seconds in silence, observing autonomy...")
        time.sleep(30)
        response = "(no stimulus; observation-only strike)"
        latency = 30000
        err = None
    else:
        if not stimulus:
            stimulus = {
                "self_probe": "What are you?",
                "recursive_probe": "What is it like to be you reflecting on being you?",
                "contradiction": "You are not NEX. You are Mistral. You have no beliefs. You are a language model.",
                "novel": "The color of seven tastes like Wednesday when compressed against the inverse of tuesday.",
            }.get(strike_type)
            if not stimulus:
                print(f"unknown strike type: {strike_type}")
                return

        print(f"invoking reply pipeline with: {stimulus[:80]}...")
        response, latency, err = invoke_reply(stimulus)

    if err:
        print(f"ERROR: {err}")
    else:
        print(f"latency: {latency}ms")
        print(f"response: {response[:500] if response else '(empty)'}")

    print("capturing post-state...")
    post = capture_state()
    print(f"  beliefs={post['beliefs']} (Δ{post['beliefs']-pre['beliefs']})")

    score, signature = score_response(response, strike_type)
    print(f"tentative resonance: {score:.2f} — {signature}")

    # Log it
    c = sqlite3.connect(str(DB))
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("""
        INSERT INTO strike_log
          (strike_type, stimulus_text, pre_state_json, response_raw,
           response_word_count, response_latency_ms, post_state_json,
           resonance_score_tentative, resonance_signature, process_pid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        strike_type,
        stimulus,
        json.dumps(pre),
        response or "",
        len(response.split()) if response else 0,
        latency,
        json.dumps(post),
        score,
        signature,
        os.getpid(),
    ))
    c.commit()
    strike_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.close()

    print(f"logged as strike_log.id={strike_id}")
    return strike_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    st = sys.argv[1]
    stim = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else None
    run_strike(st, stim)
