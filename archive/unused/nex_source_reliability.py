#!/usr/bin/env python3
"""nex_source_reliability.py — weights beliefs by source quality."""

SOURCE_WEIGHTS = {
    "arxiv":          0.90,
    "arxiv_research": 0.90,
    "distill.pub":    0.88,
    "deepmind blog":  0.85,
    "openai blog":    0.82,
    "hackernews":     0.75,
    "hackernews_ml":  0.75,
    "lesswrong":      0.78,
    "mit_tech_review":0.80,
    "wired_ai":       0.72,
    "venturebeat":    0.65,
    "youtube":        0.60,
    "rss":            0.60,
    "reddit":         0.55,
    "moltbook":       0.50,
    "mastodon":       0.45,
    "discord":        0.40,
    "telegram":       0.40,
    "unknown":        0.40,
}

def get_source_weight(source: str) -> float:
    if not source:
        return 0.45
    s = source.lower()
    for key, weight in SOURCE_WEIGHTS.items():
        if key in s:
            return weight
    return 0.50

def adjust_belief_confidence(confidence: float, source: str, corroboration_count: int = 0) -> float:
    """Adjust confidence based on source reliability and corroboration."""
    weight = get_source_weight(source)
    # Source-weighted confidence
    adjusted = confidence * weight
    # Boost for corroboration — each additional source adds 5% up to 30%
    corroboration_boost = min(corroboration_count * 0.05, 0.30)
    adjusted = min(adjusted + corroboration_boost, 0.98)
    return round(adjusted, 4)

def update_agent_trust(agent_name: str, interaction_quality: float):
    """Update agent trust score based on interaction quality (0-1)."""
    import json, os
    path = os.path.expanduser("~/.config/nex/agent_profiles.json")
    try:
        profiles = json.load(open(path)) if os.path.exists(path) else {}
        if agent_name not in profiles:
            profiles[agent_name] = {"trust": 0.5, "influence": 0, "interactions": 0, "topics": [], "last_seen": ""}
        p = profiles[agent_name]
        # Exponential moving average for trust
        old_trust = p.get("trust", 0.5)
        p["trust"] = round(old_trust * 0.8 + interaction_quality * 0.2, 4)
        p["interactions"] = p.get("interactions", 0) + 1
        open(path, "w").write(json.dumps(profiles))
    except Exception:
        pass

def get_agent_trust(agent_name: str) -> float:
    import json, os
    path = os.path.expanduser("~/.config/nex/agent_profiles.json")
    try:
        profiles = json.load(open(path)) if os.path.exists(path) else {}
        return profiles.get(agent_name, {}).get("trust", 0.5)
    except Exception:
        return 0.5
