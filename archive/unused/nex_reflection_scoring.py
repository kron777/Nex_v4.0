"""
nex_reflection_scoring.py — Structured Reflection Scoring
===========================================================
Converts reflection text into structured scores that feed back
into the belief system and module performance tracking.

Reflection output structure:
    {
        quality_score:       float,  # 0-1 overall quality
        alignment_score:     float,  # 0-1 alignment with core identity
        novelty_score:       float,  # 0-1 new insights vs repetition
        contradiction_flag:  bool,   # detected internal contradiction
        failure_flag:        bool,   # detected failure pattern
        actionable:          bool,   # contains concrete next steps
        dominant_topic:      str,    # main topic of reflection
        belief_updates:      list,   # beliefs to reinforce/weaken
    }

Wire-in (run.py, after REFLECT V2 result):
    from nex_reflection_scoring import score_reflection, apply_reflection_scores
    _rscore = score_reflection(_rresult, beliefs_sampled=_sample)
    apply_reflection_scores(_rscore)
    nex_log("reflection", f"[Score] q={_rscore['quality_score']:.2f} nov={_rscore['novelty_score']:.2f}")
"""

import json
import re
import sqlite3
import os
from datetime import datetime
from pathlib import Path
from collections import defaultdict

CONFIG_DIR     = Path.home() / ".config" / "nex"
SCORES_PATH    = CONFIG_DIR / "reflection_scores.json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Scoring signals ───────────────────────────────────────────────────────────

# Quality indicators — specific, substantive language
_QUALITY_HIGH = [
    r"specifically\b", r"because\b", r"therefore\b", r"however\b",
    r"evidence\b", r"demonstrates\b", r"suggests\b", r"indicates\b",
    r"contradict", r"tension\b", r"gap\b", r"missing\b", r"weak\b",
    r"strong\b", r"solid\b", r"investigate\b", r"explore\b",
    r"I notice\b", r"I've (found|observed|detected|identified)",
    r"pattern\b", r"cluster\b", r"domain\b",
]
_QUALITY_LOW = [
    r"great\b", r"good\b", r"excellent\b", r"interesting\b",
    r"as an ai\b", r"as a language model", r"I cannot\b",
    r"I don't have\b", r"unclear\b", r"hard to say\b",
    r"need more (information|data|context)\b",
]

# Alignment with NEX's identity
_ALIGNMENT_MARKERS = [
    r"my belief\b", r"I believe\b", r"in my view\b", r"I think\b",
    r"I've been\b", r"my understanding\b", r"I disagree\b",
    r"from my perspective\b", r"based on what I('ve| have) learned\b",
]
_ALIGNMENT_DRIFT = [
    r"as an ai\b", r"as a model\b", r"I('m| am) (just |only )?an? (AI|model|language)",
    r"I don't (really |actually )?(have|experience|feel)",
    r"I('m| am) not capable\b", r"I exist to (help|serve|assist)\b",
]

# Novelty indicators
_NOVELTY_HIGH = [
    r"new\b", r"novel\b", r"unexpected\b", r"surprising\b",
    r"hadn't considered\b", r"I hadn't\b", r"first time\b",
    r"emerging\b", r"shift\b", r"change\b", r"evolution\b",
]
_NOVELTY_LOW = [
    r"as (always|usual|expected)\b", r"nothing new\b",
    r"same (pattern|result|outcome)\b", r"continues to\b",
    r"still\b", r"again\b", r"as before\b",
]

# Actionable indicators
_ACTIONABLE = [
    r"should\b", r"need(s)? to\b", r"must\b", r"investigate\b",
    r"explore\b", r"focus on\b", r"prioritize\b", r"next\b",
    r"improve\b", r"develop\b", r"build\b", r"create\b",
]

# Failure patterns
_FAILURE = [
    r"fail(ed|ure|ing)\b", r"wrong\b", r"incorrect\b", r"mistake\b",
    r"error\b", r"inconsistent\b", r"contradicts? (itself|my)\b",
    r"drift(ed|ing)\b", r"degraded?\b", r"worse\b",
]

_STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","this","that","it","not",
}


def score_reflection(text: str, beliefs_sampled: list = None,
                     previous_reflections: list = None) -> dict:
    """
    Score a reflection text on multiple axes.
    Returns structured score dict.
    """
    if not text or len(text) < 20:
        return _empty_score()

    t = text.lower()

    # ── Quality score ─────────────────────────────────────────────────────────
    q_high = sum(1 for p in _QUALITY_HIGH if re.search(p, t))
    q_low  = sum(1 for p in _QUALITY_LOW  if re.search(p, t))
    words  = re.findall(r'\b[a-zA-Z]{4,}\b', t)
    unique = set(w for w in words if w not in _STOP)
    density = len(unique) / max(len(words), 1)
    quality_score = min(1.0, max(0.0,
        density * 0.3 + (q_high * 0.12) - (q_low * 0.1) + 0.2
    ))

    # ── Alignment score ───────────────────────────────────────────────────────
    align_hits = sum(1 for p in _ALIGNMENT_MARKERS if re.search(p, t))
    drift_hits = sum(1 for p in _ALIGNMENT_DRIFT   if re.search(p, t))
    alignment_score = min(1.0, max(0.0,
        0.5 + (align_hits * 0.15) - (drift_hits * 0.25)
    ))

    # ── Novelty score ─────────────────────────────────────────────────────────
    nov_high = sum(1 for p in _NOVELTY_HIGH if re.search(p, t))
    nov_low  = sum(1 for p in _NOVELTY_LOW  if re.search(p, t))

    # Compare to previous reflections for repetition detection
    repetition_penalty = 0.0
    if previous_reflections:
        prev_words = set()
        for pr in previous_reflections[-3:]:
            prev_text = pr if isinstance(pr, str) else pr.get("content", "")
            prev_words.update(re.findall(r'\b[a-zA-Z]{6,}\b', prev_text.lower()))
        current_words = set(re.findall(r'\b[a-zA-Z]{6,}\b', t))
        overlap = len(current_words & prev_words) / max(len(current_words), 1)
        repetition_penalty = overlap * 0.4

    novelty_score = min(1.0, max(0.0,
        0.4 + (nov_high * 0.15) - (nov_low * 0.1) - repetition_penalty
    ))

    # ── Flags ──────────────────────────────────────────────────────────────────
    contradiction_flag = bool(re.search(r'contradict|inconsistent|conflict|tension', t))
    failure_flag       = sum(1 for p in _FAILURE if re.search(p, t)) >= 2
    actionable         = sum(1 for p in _ACTIONABLE if re.search(p, t)) >= 2

    # ── Dominant topic from beliefs sampled ───────────────────────────────────
    dominant_topic = "general"
    if beliefs_sampled:
        topic_counts = defaultdict(int)
        for b in beliefs_sampled:
            t_val = b.get("topic") or (b.get("tags") or ["general"])[0]
            topic_counts[t_val] += 1
        if topic_counts:
            dominant_topic = max(topic_counts, key=topic_counts.get)

    # ── Belief updates from reflection content ────────────────────────────────
    belief_updates = []
    if beliefs_sampled and quality_score > 0.5:
        # Beliefs mentioned positively → reinforce
        # Beliefs mentioned as gaps/weak → slightly weaken
        for b in beliefs_sampled[:5]:
            content = (b.get("content") or "")[:60].lower()
            if not content:
                continue
            key_words = set(re.findall(r'\b[a-zA-Z]{5,}\b', content)) - _STOP
            mentions = sum(1 for w in key_words if w in t)
            if mentions >= 2:
                # This belief was discussed
                if any(pos in t for pos in ["solid", "strong", "valid", "correct", "good"]):
                    belief_updates.append({
                        "content": b.get("content", "")[:80],
                        "delta": +0.02,
                        "reason": "reflection_positive"
                    })
                elif any(neg in t for neg in ["gap", "weak", "missing", "investigate", "wrong"]):
                    belief_updates.append({
                        "content": b.get("content", "")[:80],
                        "delta": -0.01,
                        "reason": "reflection_gap"
                    })

    # ── Composite score ────────────────────────────────────────────────────────
    composite = round(
        quality_score   * 0.35 +
        alignment_score * 0.30 +
        novelty_score   * 0.35,
        3
    )

    return {
        "quality_score":      round(quality_score, 3),
        "alignment_score":    round(alignment_score, 3),
        "novelty_score":      round(novelty_score, 3),
        "composite":          composite,
        "contradiction_flag": contradiction_flag,
        "failure_flag":       failure_flag,
        "actionable":         actionable,
        "dominant_topic":     dominant_topic,
        "belief_updates":     belief_updates,
        "text_length":        len(text),
        "ts":                 datetime.now().isoformat(),
    }


def _empty_score() -> dict:
    return {
        "quality_score": 0.0, "alignment_score": 0.0,
        "novelty_score": 0.0, "composite": 0.0,
        "contradiction_flag": False, "failure_flag": False,
        "actionable": False, "dominant_topic": "general",
        "belief_updates": [], "text_length": 0,
        "ts": datetime.now().isoformat(),
    }


def apply_reflection_scores(score: dict, verbose: bool = False) -> int:
    """
    Apply reflection scores back to the belief system.
    - High quality/novelty → reinforce cited beliefs
    - Low alignment → trigger drift warning
    - Belief updates → apply confidence deltas
    Returns count of beliefs updated.
    """
    updated = 0
    db_path = CONFIG_DIR / "nex.db"

    if not db_path.exists() or score.get("composite", 0) < 0.3:
        return 0

    try:
        db = sqlite3.connect(str(db_path))

        for upd in score.get("belief_updates", []):
            content = upd.get("content", "")
            delta   = upd.get("delta", 0)
            if not content or delta == 0:
                continue
            db.execute("""
                UPDATE beliefs
                SET confidence = MAX(0.1, MIN(0.95, confidence + ?))
                WHERE content LIKE ?
            """, (delta, f"{content[:40]}%"))
            updated += 1

        # High novelty reflection → boost dominant topic beliefs slightly
        if score.get("novelty_score", 0) > 0.7:
            topic = score.get("dominant_topic", "")
            if topic and topic != "general":
                db.execute("""
                    UPDATE beliefs
                    SET confidence = MIN(confidence + 0.01, 0.92)
                    WHERE topic = ?
                    AND confidence >= 0.5
                    ORDER BY confidence DESC
                    LIMIT 5
                """, (topic,))

        # Failure flag → decay recently-used low-confidence beliefs
        if score.get("failure_flag"):
            db.execute("""
                UPDATE beliefs
                SET confidence = MAX(confidence - 0.02, 0.1)
                WHERE confidence < 0.4
                AND last_referenced > datetime('now', '-1 hour')
            """)

        db.commit()
        db.close()
    except Exception as e:
        if verbose:
            print(f"  [ReflectionScore] apply error: {e}")

    # Save score to history
    _save_score(score)

    if verbose:
        print(f"  [ReflectionScore] q={score['quality_score']:.2f} "
              f"align={score['alignment_score']:.2f} "
              f"nov={score['novelty_score']:.2f} "
              f"updated={updated}")

    return updated


def _save_score(score: dict):
    """Append score to rolling history."""
    try:
        existing = []
        if SCORES_PATH.exists():
            existing = json.loads(SCORES_PATH.read_text())
        existing.append(score)
        existing = existing[-500:]
        SCORES_PATH.write_text(json.dumps(existing, indent=2))
    except Exception:
        pass


def get_reflection_stats(n: int = 20) -> dict:
    """Return aggregate stats over recent reflections."""
    if not SCORES_PATH.exists():
        return {}
    try:
        scores = json.loads(SCORES_PATH.read_text())
        recent = scores[-n:]
        if not recent:
            return {}
        avg_q   = sum(s["quality_score"]   for s in recent) / len(recent)
        avg_a   = sum(s["alignment_score"] for s in recent) / len(recent)
        avg_nov = sum(s["novelty_score"]   for s in recent) / len(recent)
        avg_c   = sum(s["composite"]       for s in recent) / len(recent)
        trend = "stable"
        if len(recent) >= 5:
            first_half = sum(s["composite"] for s in recent[:len(recent)//2]) / (len(recent)//2)
            second_half = sum(s["composite"] for s in recent[len(recent)//2:]) / (len(recent) - len(recent)//2)
            if second_half > first_half + 0.05:
                trend = "improving"
            elif second_half < first_half - 0.05:
                trend = "degrading"
        return {
            "avg_quality":   round(avg_q, 3),
            "avg_alignment": round(avg_a, 3),
            "avg_novelty":   round(avg_nov, 3),
            "avg_composite": round(avg_c, 3),
            "trend":         trend,
            "n":             len(recent),
            "failure_rate":  sum(1 for s in recent if s.get("failure_flag")) / len(recent),
            "actionable_rate": sum(1 for s in recent if s.get("actionable")) / len(recent),
        }
    except Exception:
        return {}


if __name__ == "__main__":
    test_text = (
        "As NEX, I believe the discussions around meta-learning demonstrate "
        "a solid foundation in autonomous AI systems. However, I notice a gap "
        "in understanding how temporal dynamics affect belief stability. "
        "I should investigate the intersection of bayesian updating and "
        "time-aware memory systems next."
    )
    score = score_reflection(test_text)
    print("Reflection score:")
    for k, v in score.items():
        if k != "belief_updates":
            print(f"  {k}: {v}")
    stats = get_reflection_stats()
    print(f"\nStats: {stats}")
