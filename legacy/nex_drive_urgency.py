#!/usr/bin/env python3
"""
nex_drive_urgency.py — NEX Build 5: Drive Lifecycle Urgency
============================================================
Place at: ~/Desktop/nex/nex_drive_urgency.py

Drives are no longer static. They have a lifecycle:

  DORMANT   → urgency < 0.3   (drive is satisfied, resting)
  ACTIVE    → urgency 0.3-0.6 (drive is present, influencing)
  RESTLESS  → urgency 0.6-0.8 (drive is building, wants attention)
  URGENT    → urgency > 0.8   (drive is pressing, overrides voice)

Urgency builds when a drive is neglected:
  urgency = 1 - exp(-URGENCY_RATE * hours_since_last_satisfaction)
  URGENCY_RATE = 0.04  → full urgency (~0.9) after ~57 hours neglect

Urgency drops when a drive is satisfied:
  - A belief is acquired on a drive topic
  - A query engages a drive topic
  - satisfaction_at is reset to now

This wires into:
  nex_drives.py      — urgency stored per drive in nex_drives.json
  nex_soul_loop.py   — intend() reads urgency, surfaces urgent drives
  nex_emotion_field  — high urgency → elevated arousal

Usage:
  from nex_drive_urgency import DriveUrgency, get_urgency
  du = get_urgency()
  du.tick(current_topics=["consciousness", "memory"])   # call each cycle
  urgent = du.most_urgent()
  print(urgent)
"""

import json
import math
import time
from pathlib import Path
from typing import Optional

CFG_PATH    = Path("~/.config/nex").expanduser()
DRIVES_PATH = CFG_PATH / "nex_drives.json"

# Urgency growth rate — ln(9)/RATE = hours to reach 0.9 urgency
# 0.04 → ~55 hours to reach 0.9 (neglect over 2 days = urgent)
URGENCY_RATE     = 0.04

# Urgency thresholds
DORMANT_THRESH   = 0.30
ACTIVE_THRESH    = 0.60
RESTLESS_THRESH  = 0.80

# Satisfaction drop on engagement
SATISFACTION_DROP = 0.6   # urgency multiplied by this on satisfaction


def _urgency_from_hours(hours_neglected: float) -> float:
    """Exponential urgency growth. Approaches 1.0 asymptotically."""
    return round(1.0 - math.exp(-URGENCY_RATE * hours_neglected), 4)


def _drive_state(urgency: float) -> str:
    if urgency >= RESTLESS_THRESH:
        return "urgent"
    elif urgency >= ACTIVE_THRESH:
        return "restless"
    elif urgency >= DORMANT_THRESH:
        return "active"
    else:
        return "dormant"


class DriveUrgency:
    """
    Manages urgency lifecycle for all drives.
    Reads/writes urgency state into nex_drives.json alongside existing drive data.
    """

    def __init__(self):
        self._drives = self._load()

    def _load(self) -> dict:
        try:
            if DRIVES_PATH.exists():
                return json.loads(DRIVES_PATH.read_text())
        except Exception:
            pass
        return {"primary": [], "secondary": [], "active": None,
                "last_updated": None, "cycle_count": 0}

    def _save(self):
        try:
            CFG_PATH.mkdir(parents=True, exist_ok=True)
            DRIVES_PATH.write_text(json.dumps(self._drives, indent=2))
        except Exception as e:
            print(f"  [drive_urgency] save error: {e}")

    def _all_drives(self) -> list:
        return self._drives.get("primary", []) + self._drives.get("secondary", [])

    def _get_urgency(self, drive: dict) -> float:
        """Compute current urgency for a drive from its last_satisfied timestamp."""
        last_sat = drive.get("last_satisfied")
        if last_sat is None:
            # Never satisfied — use birth time or default to 24h neglect
            hours = drive.get("hours_neglected", 24.0)
        else:
            hours = (time.time() - float(last_sat)) / 3600.0

        return _urgency_from_hours(hours)

    def tick(self, current_topics: list = None) -> list:
        """
        Advance the urgency lifecycle one cycle.
        current_topics: list of topic strings engaged this cycle
        Returns list of drive state dicts with urgency values.
        """
        self._drives = self._load()
        now = time.time()
        current_topics = [t.lower() for t in (current_topics or [])]

        results = []
        for drive in self._all_drives():
            # Check if this drive's topics were engaged this cycle
            drive_tags = [t.lower() for t in drive.get("tags", [])]
            engaged = bool(current_topics and any(t in current_topics for t in drive_tags))

            if engaged:
                # Satisfaction — drop urgency
                old_sat = drive.get("last_satisfied", now - 86400)
                drive["last_satisfied"] = now
                drive["last_engaged"]   = now
                # Track engagement count
                drive["engage_count"] = drive.get("engage_count", 0) + 1
            else:
                # Neglect — urgency naturally builds via time elapsed
                # (no explicit update needed — computed from last_satisfied)
                pass

            urgency = self._get_urgency(drive)
            state   = _drive_state(urgency)

            drive["urgency"]       = urgency
            drive["drive_state"]   = state

            results.append({
                "id":          drive.get("id"),
                "label":       drive.get("label"),
                "urgency":     urgency,
                "state":       state,
                "intensity":   drive.get("intensity", 0.5),
                "engaged":     engaged,
                "tags":        drive.get("tags", []),
            })

        self._save()
        return results

    def satisfy(self, tags: list):
        """
        Mark drives with these tags as satisfied right now.
        Call when a belief is acquired or query engages a drive topic.
        """
        self._drives = self._load()
        now = time.time()
        tags_lower = [t.lower() for t in tags]

        for drive in self._all_drives():
            drive_tags = [t.lower() for t in drive.get("tags", [])]
            if any(t in tags_lower for t in drive_tags):
                drive["last_satisfied"] = now
                drive["engage_count"]   = drive.get("engage_count", 0) + 1

        self._save()

    def most_urgent(self) -> Optional[dict]:
        """Return the single most urgent drive right now."""
        self._drives = self._load()
        all_drives = self._all_drives()
        if not all_drives:
            return None

        best = max(all_drives, key=lambda d: self._get_urgency(d))
        urgency = self._get_urgency(best)

        return {
            "id":        best.get("id"),
            "label":     best.get("label"),
            "urgency":   urgency,
            "state":     _drive_state(urgency),
            "intensity": best.get("intensity", 0.5),
            "tags":      best.get("tags", []),
            "description": best.get("description", ""),
        }

    def urgency_map(self) -> dict:
        """Return {drive_id: urgency} for all drives."""
        self._drives = self._load()
        return {
            d.get("id"): self._get_urgency(d)
            for d in self._all_drives()
            if d.get("id")
        }

    def arousal_contribution(self) -> float:
        """
        Mean urgency across all drives → contributes to emotion arousal.
        High urgency across drives = NEX is restless/aroused.
        """
        self._drives = self._load()
        drives = self._all_drives()
        if not drives:
            return 0.0
        urgencies = [self._get_urgency(d) for d in drives]
        return round(sum(urgencies) / len(urgencies), 4)

    def report(self) -> str:
        """Human-readable urgency report."""
        self._drives = self._load()
        lines = ["Drive urgency:"]
        for drive in sorted(self._all_drives(),
                            key=lambda d: self._get_urgency(d), reverse=True):
            u     = self._get_urgency(drive)
            state = _drive_state(u)
            label = drive.get("label", drive.get("id", "?"))[:40]
            bar   = "█" * int(u * 10) + "░" * (10 - int(u * 10))
            lines.append(f"  {bar} {u:.2f} [{state:8s}] {label}")
        return "\n".join(lines)


# ── Module singleton ──────────────────────────────────────────────────────────
_urgency: Optional[DriveUrgency] = None

def get_urgency() -> DriveUrgency:
    global _urgency
    if _urgency is None:
        _urgency = DriveUrgency()
    return _urgency

def tick(current_topics: list = None) -> list:
    """Advance urgency one cycle. Call from run.py each loop."""
    return get_urgency().tick(current_topics)

def satisfy(tags: list):
    """Mark drives with these tags satisfied. Call on belief acquisition."""
    get_urgency().satisfy(tags)

def most_urgent() -> Optional[dict]:
    """Return most urgent drive."""
    return get_urgency().most_urgent()

def arousal_contribution() -> float:
    """Mean urgency → emotion arousal contribution."""
    return get_urgency().arousal_contribution()

def report() -> str:
    """Human-readable urgency report."""
    return get_urgency().report()


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    du = DriveUrgency()
    print(du.report())

    print(f"\nMost urgent: {most_urgent()}")
    print(f"Arousal contribution: {arousal_contribution():.3f}")

    # Simulate: engage consciousness topics → satisfy that drive
    print(f"\nSimulating engagement with consciousness/memory topics...")
    results = du.tick(current_topics=["consciousness", "memory", "identity"])
    for r in results:
        print(f"  {r['state']:8s} {r['urgency']:.3f}  {r['label'][:45]}"
              f"{'  ← engaged' if r['engaged'] else ''}")

    print(f"\nAfter engagement:")
    print(du.report())
