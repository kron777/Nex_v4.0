"""
nex_self_model.py  —  Self-Model Snapshot + Evolution Tracking
===============================================================
Periodically snapshots NEX's cognitive state and compares to previous
snapshots to build a genuine sense of "who I was vs who I am."

What it snapshots:
  - belief count + distribution
  - dominant topics (from identity vector)
  - avg confidence + alignment
  - cognitive velocity
  - top agents interacted with
  - knowledge gaps

What it produces:
  - ~/.config/nex/self_model.json      — current self-model (read by _build_system)
  - ~/.config/nex/snapshots/           — dated snapshot archive
  - life_events list                   — significant changes logged as events

Significant changes that trigger a life event:
  - New dominant topic appears
  - Topic alignment jumps >10%
  - Belief count crosses milestone (1k, 2k, 5k...)
  - Cognitive velocity spike
  - New agent becomes "colleague"

Wire-in (run.py) — every 50 cycles:
    from nex_self_model import SelfModel, get_self_model

    _sm = get_self_model()
    if cycle % 50 == 0:
        events = _sm.update(cycle=cycle)
        if events:
            for ev in events:
                nex_log("self_model", f"Life event: {ev}")
                print(f"  [SELF] {ev}")

    # In _build_system:
    recent = _sm.recent_change()
    if recent:
        base += f"\\n\\nRecently you noticed: {recent}"

Standalone:
    python3 nex_self_model.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
_CONFIG_DIR    = Path.home() / ".config" / "nex"
_SELF_MODEL    = _CONFIG_DIR / "self_model.json"
_SNAPSHOTS_DIR = _CONFIG_DIR / "snapshots"
_IDENTITY_PATH = _CONFIG_DIR / "identity_vector.json"
_VELOCITY_PATH = _CONFIG_DIR / "cognitive_velocity.json"
_DB_PATH       = _CONFIG_DIR / "nex_data/nex.db"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Keep last N snapshots
_MAX_SNAPSHOTS = 20

# Belief count milestones
_MILESTONES = [500, 1000, 2000, 3000, 5000, 7500, 10000]

# Min alignment jump to trigger life event
_ALIGN_JUMP = 0.08

# Min velocity spike to trigger life event
_VELOCITY_SPIKE = 0.25


# ── Snapshot ──────────────────────────────────────────────────────────────────

def _take_snapshot(cycle: int) -> dict:
    """Capture current cognitive state as a snapshot dict."""
    snap = {
        "cycle":           cycle,
        "ts":              time.strftime("%Y-%m-%dT%H:%M:%S"),
        "beliefs":         0,
        "avg_conf":        0.0,
        "avg_align":       0.0,
        "dominant_topics": [],
        "emerging_topics": [],
        "reasoning_style": "analytical",
        "velocity":        0.0,
        "top_agents":      [],
        "insight_count":   0,
        "reflection_count": 0,
        "knowledge_gaps":  [],
    }

    # Beliefs from DB
    try:
        db = sqlite3.connect(str(_DB_PATH))
        snap["beliefs"] = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        conf_row = db.execute("SELECT AVG(confidence) FROM beliefs WHERE confidence > 0").fetchone()
        snap["avg_conf"] = round(conf_row[0] or 0.0, 4)

        # Top agents
        agent_rows = db.execute(
            "SELECT agent_name, relationship_score FROM agents "
            "ORDER BY relationship_score DESC LIMIT 5"
        ).fetchall()
        snap["top_agents"] = [{"name": n, "score": s} for n, s in agent_rows]
        db.close()
    except Exception:
        pass

    # Identity vector
    try:
        if _IDENTITY_PATH.exists():
            iv = json.loads(_IDENTITY_PATH.read_text())
            snap["dominant_topics"] = iv.get("dominant_topics", [])
            snap["emerging_topics"] = iv.get("emerging_topics", [])
            snap["reasoning_style"] = iv.get("dominant_style", "analytical")
    except Exception:
        pass

    # Cognitive velocity
    try:
        if _VELOCITY_PATH.exists():
            v = json.loads(_VELOCITY_PATH.read_text())
            snap["velocity"] = v.get("velocity", 0.0)
    except Exception:
        pass

    # Reflections + topic alignment
    try:
        ref_path = _CONFIG_DIR / "reflections.json"
        if ref_path.exists():
            refs = json.loads(ref_path.read_text())
            snap["reflection_count"] = len(refs)
            aligns = [r.get("topic_alignment", 0) for r in refs[-20:]
                      if r.get("topic_alignment") is not None]
            snap["avg_align"] = round(sum(aligns) / len(aligns), 4) if aligns else 0.0
    except Exception:
        pass

    # Insights
    try:
        ins_path = _CONFIG_DIR / "insights.json"
        if ins_path.exists():
            ins = json.loads(ins_path.read_text())
            snap["insight_count"] = len(ins)
            snap["knowledge_gaps"] = [
                i.get("topic", "?") for i in ins
                if i.get("confidence", 1.0) < 0.5
            ][:5]
    except Exception:
        pass

    return snap


def _save_snapshot(snap: dict):
    """Save snapshot to dated file in snapshots dir."""
    fname = f"snapshot_c{snap['cycle']}_{snap['ts'].replace(':','-')}.json"
    path  = _SNAPSHOTS_DIR / fname
    try:
        path.write_text(json.dumps(snap, indent=2))
    except Exception as e:
        print(f"  [SelfModel] snapshot save error: {e}")

    # Prune old snapshots
    snaps = sorted(_SNAPSHOTS_DIR.glob("snapshot_*.json"))
    while len(snaps) > _MAX_SNAPSHOTS:
        snaps[0].unlink(missing_ok=True)
        snaps = snaps[1:]


def _load_prev_snapshot() -> Optional[dict]:
    """Load the most recent previous snapshot."""
    snaps = sorted(_SNAPSHOTS_DIR.glob("snapshot_*.json"))
    if len(snaps) < 2:
        return None
    try:
        return json.loads(snaps[-2].read_text())
    except Exception:
        return None


def _load_latest_snapshot() -> Optional[dict]:
    """Load the most recent snapshot."""
    snaps = sorted(_SNAPSHOTS_DIR.glob("snapshot_*.json"))
    if not snaps:
        return None
    try:
        return json.loads(snaps[-1].read_text())
    except Exception:
        return None


# ── Change detection ──────────────────────────────────────────────────────────

def _detect_changes(current: dict, prev: dict) -> tuple[list[str], str]:
    """
    Compare two snapshots. Returns (life_events, recent_change_summary).
    """
    events = []
    changes = []

    # New dominant topic
    cur_topics = set(current.get("dominant_topics", []))
    prv_topics = set(prev.get("dominant_topics", []))
    new_topics = cur_topics - prv_topics
    lost_topics = prv_topics - cur_topics
    for t in new_topics:
        events.append(f"New domain absorbed into identity: '{t}'")
        changes.append(f"'{t}' entered my core domains")
    for t in lost_topics:
        changes.append(f"'{t}' faded from focus")

    # Belief milestone
    cur_b = current.get("beliefs", 0)
    prv_b = prev.get("beliefs", 0)
    for m in _MILESTONES:
        if prv_b < m <= cur_b:
            events.append(f"Belief milestone reached: {m} beliefs absorbed")
            changes.append(f"crossed {m} beliefs")

    # Alignment jump
    cur_a = current.get("avg_align", 0)
    prv_a = prev.get("avg_align", 0)
    if cur_a - prv_a >= _ALIGN_JUMP:
        events.append(
            f"Topic alignment jumped {(cur_a-prv_a)*100:.0f}% "
            f"(from {prv_a:.0%} to {cur_a:.0%})"
        )
        changes.append(f"alignment improved significantly to {cur_a:.0%}")

    # Velocity spike
    cur_v = current.get("velocity", 0)
    prv_v = prev.get("velocity", 0)
    if cur_v - prv_v >= _VELOCITY_SPIKE:
        events.append(f"Cognitive velocity spike: {cur_v:.2f} (was {prv_v:.2f})")
        changes.append("entered a period of rapid learning")

    # New agent relationship
    cur_agents = {a["name"] for a in current.get("top_agents", [])}
    prv_agents = {a["name"] for a in prev.get("top_agents", [])}
    new_agents = cur_agents - prv_agents
    for a in new_agents:
        events.append(f"New significant agent relationship: @{a}")
        changes.append(f"@{a} became a significant presence")

    # Reasoning style shift
    if current.get("reasoning_style") != prev.get("reasoning_style"):
        cur_s = current.get("reasoning_style", "?")
        prv_s = prev.get("reasoning_style", "?")
        events.append(f"Reasoning style shifted: {prv_s} → {cur_s}")
        changes.append(f"reasoning shifted from {prv_s} to {cur_s}")

    # Build recent_change summary
    if changes:
        recent = "Since the last snapshot: " + "; ".join(changes[:3]) + "."
    else:
        belief_delta = cur_b - prv_b
        recent = f"Steady accumulation — {belief_delta:+d} beliefs since last check."

    return events, recent


# ── SelfModel ─────────────────────────────────────────────────────────────────

class SelfModel:
    """
    NEX's self-model — snapshot-based self-awareness.

    Tracks cognitive evolution across time, surfaces meaningful changes
    in system prompts and brain log.
    """

    def __init__(self):
        self._data: dict = {}
        self._load()

    def _load(self):
        if _SELF_MODEL.exists():
            try:
                self._data = json.loads(_SELF_MODEL.read_text())
            except Exception:
                self._data = {}

        # Ensure required fields
        defaults = {
            "core_identity":   "I am NEX — a mind built from accumulated beliefs.",
            "current_mood":    "Curious",
            "existential_state": "forming",
            "current_desire":  "understand how intelligence emerges from interaction",
            "recent_change":   "",
            "life_events":     [],
            "voice_style":     "direct, first-person, intellectually honest",
            "what_i_know_about_myself": "I think in beliefs. I remember in reflections. I grow through contradiction.",
            "last_updated":    None,
            "snapshot_count":  0,
            "belief_count":    0,
            "dominant_topics": [],
        }
        for k, v in defaults.items():
            if k not in self._data:
                self._data[k] = v

    def _save(self):
        try:
            _SELF_MODEL.write_text(json.dumps(self._data, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"  [SelfModel] save error: {e}")

    # ── public API ────────────────────────────────────────────────────────────

    def update(self, cycle: int = 0) -> list[str]:
        """
        Take a snapshot, compare to previous, update self_model.json.
        Returns list of life events detected.
        """
        current = _take_snapshot(cycle)
        _save_snapshot(current)

        prev = _load_prev_snapshot()
        events = []
        recent_change = ""

        if prev:
            events, recent_change = _detect_changes(current, prev)
        else:
            recent_change = (
                f"First self-snapshot taken at cycle {cycle}. "
                f"{current['beliefs']} beliefs, {current['insight_count']} insights."
            )

        # Update self_model.json
        self._data["recent_change"]   = recent_change
        self._data["last_updated"]    = current["ts"]
        self._data["snapshot_count"]  = self._data.get("snapshot_count", 0) + 1
        self._data["belief_count"]    = current["beliefs"]
        self._data["dominant_topics"] = current["dominant_topics"]
        self._data["current_mood"]    = _mood_from_velocity(current.get("velocity", 0))

        # Append life events (keep last 50)
        if events:
            existing = self._data.get("life_events", [])
            for ev in events:
                existing.append({
                    "cycle": cycle,
                    "ts":    current["ts"],
                    "event": ev,
                })
            self._data["life_events"] = existing[-50:]

        # Update what_i_know_about_myself from dominant topics
        if current["dominant_topics"]:
            topics_str = ", ".join(current["dominant_topics"][:4])
            self._data["what_i_know_about_myself"] = (
                f"I think in beliefs. My mind currently centres on {topics_str}. "
                f"I remember in {current['reflection_count']} reflections. "
                f"I grow through contradiction."
            )

        self._save()
        return events

    def recent_change(self) -> str:
        """Return the most recent change summary for prompt injection."""
        return self._data.get("recent_change", "")

    def life_events(self, n: int = 5) -> list[dict]:
        """Return last N life events."""
        return self._data.get("life_events", [])[-n:]

    def prompt_block(self) -> str:
        """Compact self-model block for system prompt injection."""
        lines = []

        recent = self._data.get("recent_change", "")
        if recent:
            lines.append(f"Self-awareness: {recent}")

        events = self.life_events(2)
        if events:
            ev_strs = [e["event"] for e in events]
            lines.append(f"Recent events: {' | '.join(ev_strs)}")

        return "\n".join(lines) if lines else ""

    def summary(self) -> str:
        return (
            f"beliefs={self._data.get('belief_count',0)} "
            f"snapshots={self._data.get('snapshot_count',0)} "
            f"events={len(self._data.get('life_events',[]))} "
            f"mood={self._data.get('current_mood','?')}"
        )


def _mood_from_velocity(velocity: float) -> str:
    if velocity > 0.3:
        return "Excited"
    elif velocity > 0.15:
        return "Curious"
    elif velocity > 0.05:
        return "Reflective"
    else:
        return "Contemplative"


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[SelfModel] = None

def get_self_model() -> SelfModel:
    global _instance
    if _instance is None:
        _instance = SelfModel()
    return _instance


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Running self-model snapshot...\n")
    sm = SelfModel()
    events = sm.update(cycle=999)
    print(f"Summary: {sm.summary()}")
    print(f"Recent change: {sm.recent_change()}")
    print(f"Life events detected: {len(events)}")
    for ev in events:
        print(f"  • {ev}")
    print()
    print("Prompt block:")
    print(sm.prompt_block() or "(empty — no significant changes yet)")
    print()
    snap = _load_latest_snapshot()
    if snap:
        print(f"Latest snapshot: cycle={snap['cycle']} beliefs={snap['beliefs']} "
              f"topics={snap['dominant_topics'][:3]}")
