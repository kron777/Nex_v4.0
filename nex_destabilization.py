#!/usr/bin/env python3
"""
nex_destabilization.py
======================
AGI Bridge #2 — Belief Destabilization Engine

When a high-confidence held belief is directly contradicted by incoming
content, NEX should be *changed* by it — not just log and resolve.

Current behaviour: contradiction → logged → resolved → forgotten
Target behaviour:  contradiction → disturbance → held tension → surfaces in replies

This module:
  1. DETECT   — finds when new content contradicts held beliefs (conf > 0.65)
  2. DISTURB  — injects tension into the epistemic state (raises pressure, shifts tone)
  3. HOLD     — stores unresolved contradictions with a disturbance score
  4. SURFACE  — makes the disturbance visible in replies for N cycles

The key distinction: disturbance is NOT resolution. The tension stays alive
until NEX either encounters corroborating evidence or the disturbance decays
naturally. This is closer to how actual epistemic states work.

Integration:
  Call check_incoming(content) whenever new content is absorbed.
  Call get_disturbance_state() in soul_loop.consult_state() to inject.
  Call decay_disturbances() each cycle.
"""

import json
import re
import sqlite3
import time
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

DB_PATH    = Path("/home/rr/Desktop/nex/nex.db")
CFG        = Path.home() / ".config/nex"
STATE_PATH = CFG / "destabilization_state.json"
LOG_PATH   = Path("/home/rr/Desktop/nex/logs/destabilization.log")

# Confidence threshold — only high-confidence beliefs can be destabilized
DESTABILIZE_CONF_FLOOR = 0.65
# How many cycles disturbance persists before decaying
DISTURBANCE_LIFETIME   = 8
# Minimum overlap to consider a contradiction
MIN_CONTRADICTION_OVERLAP = 2
# Max simultaneous active disturbances
MAX_ACTIVE = 5

_STOP = {
    "the","a","an","is","are","was","were","be","to","of","in","on","at",
    "by","for","with","as","that","this","it","but","or","and","not","they",
    "have","has","will","can","would","could","should","may","might","what",
    "which","who","how","why","when","where","all","any","each","both","than",
    "then","been","only","even","very","just","more","most","some","such",
}

# Negation markers that signal contradiction
_NEGATION_MARKERS = {
    "not", "never", "no", "cannot", "can't", "won't", "doesn't", "don't",
    "isn't", "aren't", "wasn't", "weren't", "without", "contrary", "against",
    "refutes", "disproves", "contradicts", "denies", "rejects", "impossible",
    "false", "wrong", "incorrect", "mistaken", "flawed", "fails", "invalid",
}


def _log(msg: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _tokenize(text: str) -> set:
    return set(re.findall(r'\b[a-z]{4,}\b', text.lower())) - _STOP


def _load_state() -> Dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"disturbances": [], "total_detected": 0, "last_scan": 0}


def _save_state(state: Dict):
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, STATE_PATH)


def _load_high_conf_beliefs() -> List[Dict]:
    """Load beliefs that are stable enough to be destabilized."""
    if not DB_PATH.exists():
        return []
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=3)
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT id, content, confidence, topic
            FROM beliefs
            WHERE confidence >= ?
            AND content IS NOT NULL
            AND length(content) > 25
            AND source NOT IN ('bridge_detector','nex_reasoning','emergent_want')
            ORDER BY confidence DESC
            LIMIT 500
        """, (DESTABILIZE_CONF_FLOOR,)).fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception as e:
        _log(f"[load] error: {e}")
        return []


def _has_negation(text: str) -> bool:
    words = set(text.lower().split())
    return bool(words & _NEGATION_MARKERS)


def _contradiction_score(
    held: str,
    incoming: str
) -> Tuple[float, str]:
    """
    Score how much `incoming` contradicts `held`.
    Returns (score 0-1, contradiction_type).

    Types:
      direct    — incoming negates core tokens of held
      inverse   — incoming asserts opposite of held
      none      — no contradiction
    """
    held_tokens     = _tokenize(held)
    incoming_tokens = _tokenize(incoming)
    overlap         = held_tokens & incoming_tokens

    if len(overlap) < MIN_CONTRADICTION_OVERLAP:
        return 0.0, "none"

    # Check if incoming negates held
    if _has_negation(incoming):
        # Score = overlap density × negation presence
        density = len(overlap) / max(len(held_tokens), 1)
        score   = min(density * 2.0, 1.0)
        if score > 0.15:
            return round(score, 3), "direct"

    # Check inverse: if held says "X causes Y", does incoming say "X doesn't cause Y"
    # Simple heuristic: high overlap + negation anywhere near shared tokens
    incoming_words = incoming.lower().split()
    for i, word in enumerate(incoming_words):
        if word in _NEGATION_MARKERS:
            # Negation within 5 words of an overlap token
            window = set(incoming_words[max(0,i-5):i+6])
            if window & overlap:
                density = len(overlap) / max(len(held_tokens), 1)
                score   = min(density * 1.5, 1.0)
                if score > 0.12:
                    return round(score, 3), "inverse"

    return 0.0, "none"


def _build_disturbance(
    held_belief: Dict,
    incoming: str,
    score: float,
    contradiction_type: str,
) -> Dict:
    """Build a disturbance record."""
    return {
        "id":                  f"disturb_{int(time.time()*1000)}",
        "held_belief_id":      held_belief.get("id"),
        "held_content":        held_belief["content"][:200],
        "held_confidence":     held_belief["confidence"],
        "held_topic":          held_belief.get("topic", "unknown"),
        "incoming_content":    incoming[:200],
        "contradiction_score": score,
        "contradiction_type":  contradiction_type,
        "disturbance_level":   round(score * held_belief["confidence"], 3),
        "cycles_remaining":    DISTURBANCE_LIFETIME,
        "created_at":          time.time(),
        "resolved":            False,
        "surfaced_count":      0,
    }


def check_incoming(content: str, source: str = "") -> Optional[Dict]:
    """
    Main entry point. Call whenever new content is absorbed.
    Returns disturbance dict if destabilization occurred, else None.

    Usage in run.py ABSORB loop:
        from nex_destabilization import check_incoming
        disturbance = check_incoming(belief_content, source="moltbook")
        if disturbance:
            print(f"  [DISTURB] {disturbance['held_topic']}: {disturbance['disturbance_level']:.2f}")
    """
    if not content or len(content) < 20:
        return None

    state = _load_state()
    active = state.get("disturbances", [])

    # Don't pile on if already heavily disturbed
    if len([d for d in active if not d.get("resolved")]) >= MAX_ACTIVE:
        return None

    high_conf = _load_high_conf_beliefs()
    if not high_conf:
        return None

    best_score = 0.0
    best_belief = None
    best_type   = "none"

    for belief in high_conf:
        score, ctype = _contradiction_score(belief["content"], content)
        if score > best_score:
            best_score  = score
            best_belief = belief
            best_type   = ctype

    if best_score < 0.15 or not best_belief:
        return None

    disturbance = _build_disturbance(best_belief, content, best_score, best_type)
    state["disturbances"].append(disturbance)
    state["total_detected"] = state.get("total_detected", 0) + 1
    state["last_scan"] = time.time()
    _save_state(state)

    # Write to contradiction_memory table so soul_loop can see it
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=3)
        db.execute("""
            INSERT OR IGNORE INTO contradiction_memory
            (belief_a, belief_b, topic, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            best_belief["content"][:300],
            content[:300],
            best_belief.get("topic", "unknown"),
            time.time(),
        ))
        db.commit()
        db.close()
    except Exception as e:
        _log(f"[db] contradiction_memory write error: {e}")

    _log(
        f"[disturb] {best_type} contradiction detected | "
        f"topic={best_belief.get('topic')} | "
        f"score={best_score:.3f} | "
        f"level={disturbance['disturbance_level']:.3f}"
    )

    return disturbance


def get_disturbance_state() -> Dict:
    """
    Returns current disturbance state for injection into soul_loop.consult_state().
    Call this in consult_state() to inject disturbance into NEX's epistemic state.

    Returns:
        {
            active_count: int,
            max_level: float,        # 0-1, how disturbed she is
            dominant_topic: str,     # what's disturbing her most
            surface_text: str,       # ready-to-inject tension phrase
            pressure_boost: float,   # add to cognitive_pressure
        }
    """
    state = _load_state()
    active = [d for d in state.get("disturbances", []) if not d.get("resolved") and d.get("cycles_remaining", 0) > 0]

    if not active:
        return {
            "active_count":   0,
            "max_level":      0.0,
            "dominant_topic": "",
            "surface_text":   "",
            "pressure_boost": 0.0,
        }

    # Sort by disturbance level
    active.sort(key=lambda d: -d.get("disturbance_level", 0))
    dominant = active[0]

    max_level = dominant["disturbance_level"]
    topic     = dominant["held_topic"]

    # Build tension phrase for injection into replies
    held     = dominant["held_content"][:80]
    incoming = dominant["incoming_content"][:80]

    _SURFACE_FORMS = [
        f"I hold something that sits uneasily against what I've just encountered on {topic}.",
        f"There's a tension I haven't resolved: what I believed about {topic} doesn't sit cleanly with what I'm seeing.",
        f"Something I held with confidence on {topic} is now pulling against incoming signal.",
        f"I'm genuinely uncertain here — my position on {topic} is under pressure.",
    ]

    import random
    surface_text = random.choice(_SURFACE_FORMS)

    return {
        "active_count":   len(active),
        "max_level":      round(max_level, 3),
        "dominant_topic": topic,
        "surface_text":   surface_text,
        "pressure_boost": round(min(max_level * 0.4, 0.35), 3),
        "held_belief":    held,
        "contradicting":  incoming,
    }


def decay_disturbances(cycle: int = 0):
    """
    Call each cognitive cycle to decay active disturbances.
    Disturbances that decay fully are marked resolved.
    """
    state = _load_state()
    disturbances = state.get("disturbances", [])

    changed = False
    for d in disturbances:
        if d.get("resolved"):
            continue
        remaining = d.get("cycles_remaining", 0) - 1
        d["cycles_remaining"] = remaining
        if remaining <= 0:
            d["resolved"] = True
            d["resolved_at"] = time.time()
            _log(f"[decay] disturbance resolved naturally: {d.get('held_topic')} (surfaced {d.get('surfaced_count',0)}x)")
        changed = True

    # Keep only last 50 disturbances (resolved + active)
    state["disturbances"] = disturbances[-50:]

    if changed:
        _save_state(state)


def mark_surfaced(disturbance_id: str):
    """Call when a disturbance is surfaced in a reply."""
    state = _load_state()
    for d in state.get("disturbances", []):
        if d.get("id") == disturbance_id:
            d["surfaced_count"] = d.get("surfaced_count", 0) + 1
            break
    _save_state(state)


def get_status() -> Dict:
    """Summary for dashboard/monitoring."""
    state = _load_state()
    active = [d for d in state.get("disturbances", []) if not d.get("resolved")]
    return {
        "active_disturbances": len(active),
        "total_detected":      state.get("total_detected", 0),
        "top_topics":          [d.get("held_topic") for d in active[:3]],
        "max_level":           max((d.get("disturbance_level", 0) for d in active), default=0),
    }


if __name__ == "__main__":
    # Test
    print("Testing destabilization engine...")
    test_held     = "Consciousness is an emergent property of complex information processing systems."
    test_incoming = "Consciousness cannot be reduced to information processing — the hard problem shows this is not sufficient."

    score, ctype = _contradiction_score(test_held, test_incoming)
    print(f"Contradiction score: {score:.3f} type={ctype}")

    result = check_incoming(test_incoming)
    if result:
        print(f"Disturbance created: level={result['disturbance_level']:.3f}")
        state = get_disturbance_state()
        print(f"State: {state}")
    else:
        print("No disturbance (threshold not met with test data)")

    print("\nStatus:", get_status())
