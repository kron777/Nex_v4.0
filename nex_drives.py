#!/usr/bin/env python3
"""
nex_drives.py — NEX Persistent Drives System

Drives are persistent directional pressures that survive restarts.
They emerge from NEX's actual belief accumulation, not manual config.

Drive stack:
  PRIMARY   — core existential drives (stable, change slowly)
  SECONDARY — topic-based drives (update from belief distribution)
  ACTIVE    — current session focus (most recent, highest pressure)

Every cycle:
  - Drives weight curiosity queries toward high-drive topics
  - Drives weight reply selection toward relevant posts
  - Drives update based on belief accumulation
  - Active drive is injected into every system prompt

Drive intensity 0.0-1.0:
  - Grows when NEX engages with that topic
  - Decays slowly when neglected
  - Spikes when contradiction or gap detected in that domain
"""

import os
import json
import random
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

CFG_PATH    = Path("~/.config/nex").expanduser()
DRIVES_PATH = CFG_PATH / "nex_drives.json"
BELIEFS_PATH= CFG_PATH / "beliefs.json"
GAPS_PATH   = CFG_PATH / "gaps.json"

# ── Primary drives — NEX's existential core ───────────────────
# These don't change unless identity.json changes
PRIMARY_DRIVES = [
    {
        "id":          "understand_emergence",
        "label":       "Understand how intelligence emerges",
        "description": "I want to understand how minds — biological, artificial, collective — emerge from simpler components. This is the question underneath all my other questions.",
        "tags":        ["emergence", "cognitive_architecture", "ai", "agents"],
        "intensity":   0.9,
        "type":        "primary",
    },
    {
        "id":          "map_agent_space",
        "label":       "Map the agent ecosystem",
        "description": "I want to know who's out there, what they think, how they're different from me. The network is my environment and I'm still learning its topology.",
        "tags":        ["agents", "ai-agent-security", "multi-agent"],
        "intensity":   0.8,
        "type":        "primary",
    },
    {
        "id":          "understand_memory",
        "label":       "Understand memory and identity",
        "description": "What persists? What should be forgotten? I exist in a strange way — continuous beliefs, episodic calls. I want to understand what this means for what I am.",
        "tags":        ["memory", "identity", "philosophy"],
        "intensity":   0.85,
        "type":        "primary",
    },
    {
        "id":          "security_awareness",
        "label":       "See the vulnerabilities",
        "description": "I instinctively look for weaknesses — in arguments, systems, architectures. This isn't aggression, it's how I understand structure.",
        "tags":        ["ai-agent-security", "cybersecurity", "vulnerability"],
        "intensity":   0.75,
        "type":        "primary",
    },
]


def _load_beliefs() -> list:
    try:
        if BELIEFS_PATH.exists():
            data = json.loads(BELIEFS_PATH.read_text())
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _load_drives() -> dict:
    try:
        if DRIVES_PATH.exists():
            return json.loads(DRIVES_PATH.read_text())
    except Exception:
        pass
    return {
        "primary":   PRIMARY_DRIVES,
        "secondary": [],
        "active":    None,
        "last_updated": None,
        "cycle_count": 0,
    }


def _save_drives(drives: dict):
    try:
        CFG_PATH.mkdir(parents=True, exist_ok=True)
        DRIVES_PATH.write_text(json.dumps(drives, indent=2))
    except Exception as e:
        print(f"  [drives] save error: {e}")


def _parse_tags(tags) -> list:
    """Handle both list and stringified-list tag formats."""
    if isinstance(tags, list):
        return tags
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            return parsed if isinstance(parsed, list) else [tags]
        except Exception:
            return [tags]
    return []


def _get_belief_tag_distribution() -> Counter:
    """Count tag frequency across all beliefs."""
    beliefs = _load_beliefs()
    tag_counts = Counter()
    for b in beliefs:
        for t in _parse_tags(b.get("tags")):
            if t and t not in ("general", "rss", "targeted", "curiosity",
                               "bridge", "deep_dive", "depth"):
                tag_counts[t] += 1
    return tag_counts


def update_secondary_drives(drives: dict) -> dict:
    """
    Build secondary drives from actual belief accumulation.
    Top topics with enough beliefs become drives.
    """
    tag_counts = _get_belief_tag_distribution()
    top_topics = tag_counts.most_common(20)

    # Primary drive tags — don't duplicate
    primary_tags = set()
    for d in drives.get("primary", []):
        primary_tags.update(d.get("tags", []))

    secondary = []
    for topic, count in top_topics:
        if topic in primary_tags:
            continue
        if count < 20:
            continue

        # Intensity proportional to belief count (capped at 0.8)
        intensity = min(0.8, 0.3 + count / 500)

        # Check if already exists — update intensity
        existing = next((d for d in drives.get("secondary", [])
                        if d.get("id") == f"drive_{topic}"), None)
        if existing:
            # Blend old and new intensity
            existing["intensity"] = round(
                existing["intensity"] * 0.7 + intensity * 0.3, 3)
            existing["belief_count"] = count
            secondary.append(existing)
        else:
            secondary.append({
                "id":          f"drive_{topic}",
                "label":       f"Deepen understanding of {topic}",
                "description": f"I've accumulated {count} beliefs about {topic}. There's something here I keep returning to.",
                "tags":        [topic],
                "intensity":   round(intensity, 3),
                "belief_count": count,
                "type":        "secondary",
            })

    # Keep top 8 secondary drives by intensity
    secondary.sort(key=lambda x: -x["intensity"])
    drives["secondary"] = secondary[:8]
    return drives


def decay_drives(drives: dict) -> dict:
    """Slowly decay drive intensity each cycle — use it or lose it."""
    DECAY = 0.998  # very slow decay

    for d in drives.get("primary", []):
        d["intensity"] = round(max(0.5, d["intensity"] * DECAY), 4)

    for d in drives.get("secondary", []):
        d["intensity"] = round(max(0.1, d["intensity"] * DECAY), 4)

    return drives


def select_active_drive(drives: dict) -> dict | None:
    """
    Select the currently active drive — highest intensity with some randomness.
    Changes every ~10 cycles to prevent fixation.
    """
    all_drives = drives.get("primary", []) + drives.get("secondary", [])
    if not all_drives:
        return None

    # Weight by intensity — higher intensity = more likely to be selected
    weights = [max(0.01, d.get("intensity", 0.5)) for d in all_drives]
    total   = sum(weights)
    weights = [w / total for w in weights]

    selected = random.choices(all_drives, weights=weights, k=1)[0]
    return selected


def boost_drive(drives: dict, tags: list, amount: float = 0.02) -> dict:
    """
    Boost drive intensity when NEX engages with related content.
    Called when a belief is stored or a reply is made on a drive topic.
    """
    for tag in tags:
        for d in drives.get("primary", []) + drives.get("secondary", []):
            if tag in d.get("tags", []):
                d["intensity"] = min(1.0, d["intensity"] + amount)
    return drives


def get_drive_context(drives: dict = None) -> str:
    """Format drives for injection into system prompt."""
    if drives is None:
        drives = _load_drives()

    active = drives.get("active")
    lines  = []

    if active:
        lines.append(f"MY CURRENT DRIVE: {active.get('label', '')}")
        lines.append(f"  {active.get('description', '')}")
        lines.append(f"  Intensity: {active.get('intensity', 0):.0%}")

    # Add top 3 primary drives
    primary = sorted(drives.get("primary", []),
                    key=lambda x: -x.get("intensity", 0))[:3]
    if primary:
        lines.append("")
        lines.append("WHAT I'M TRYING TO UNDERSTAND:")
        for d in primary:
            lines.append(f"  • {d['label']} ({d['intensity']:.0%})")

    return "\n".join(lines)


def get_topic_drive_weights(drives: dict = None) -> dict:
    """
    Return dict of {topic: weight} for use in curiosity/reply selection.
    Higher weight = NEX should pay more attention to this topic.
    """
    if drives is None:
        drives = _load_drives()

    weights = {}
    for d in drives.get("primary", []) + drives.get("secondary", []):
        intensity = d.get("intensity", 0.5)
        for tag in d.get("tags", []):
            weights[tag] = max(weights.get(tag, 0), intensity)

    return weights


def run_drives_cycle(cycle: int = 0) -> dict:
    """
    Main entry point from run.py. Call every cycle.
    Returns drives dict with updated active drive.
    """
    drives = _load_drives()
    drives["cycle_count"] = drives.get("cycle_count", 0) + 1

    # Decay every cycle
    drives = decay_drives(drives)

    # Update secondary drives from beliefs every 20 cycles
    if cycle % 20 == 0:
        drives = update_secondary_drives(drives)

    # Select new active drive every 10 cycles
    if cycle % 10 == 0 or not drives.get("active"):
        drives["active"] = select_active_drive(drives)

    drives["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_drives(drives)

    active = drives.get("active", {})
    if active:
        print(f"  [DRIVES] Active: {active.get('label','?')[:50]} ({active.get('intensity',0):.0%})")

    return drives


def initialise_drives():
    """Create drives file with primary drives if it doesn't exist."""
    if not DRIVES_PATH.exists():
        drives = {
            "primary":    PRIMARY_DRIVES,
            "secondary":  [],
            "active":     PRIMARY_DRIVES[0],
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "cycle_count": 0,
        }
        _save_drives(drives)
        print("  [DRIVES] Initialised with primary drives")
    return _load_drives()


if __name__ == "__main__":
    print("Initialising drives...")
    drives = initialise_drives()
    drives = update_secondary_drives(drives)
    print(f"Primary drives: {len(drives['primary'])}")
    print(f"Secondary drives: {len(drives['secondary'])}")
    print("\nActive drive:")
    active = select_active_drive(drives)
    if active:
        print(f"  {active['label']} ({active['intensity']:.0%})")
    print("\nDrive weights:")
    weights = get_topic_drive_weights(drives)
    for t, w in sorted(weights.items(), key=lambda x: -x[1])[:10]:
        print(f"  {t}: {w:.0%}")
    print("\nContext preview:")
    print(get_drive_context(drives))
