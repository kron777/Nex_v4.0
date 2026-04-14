"""
nex_warmth_context.py
Item 6 — Contextual Re-weighting.

"Truth" in ethics pulls differently than "truth" in epistemology.
Same word, different lean depending on conversational domain.
Currently tags are domain-agnostic — averaged across all contexts.

This module:
  1. Detects conversation domain from question vocabulary
  2. Applies domain_drift_map adjustments to tag values
     for duration of that response only
  3. Returns domain-adjusted resolution for response pipeline

Domain detection uses word signature matching —
each domain has characteristic vocabulary.
When enough signature words appear, domain is confirmed.
"""
import sqlite3, json, re, logging, sys
from pathlib import Path
from collections import Counter

log     = logging.getLogger("nex.context")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"

# Domain signatures — characteristic vocabulary per domain
DOMAIN_SIGNATURES = {
    "consciousness": {
        "words": {"consciousness","qualia","phenomenal",
                  "subjective","experience","awareness",
                  "hard","problem","explanatory","gap",
                  "zombie","mind","brain","neural","mental"},
        "depth_boost":   +1,
        "align_boost":   +0.15,
        "valence_shift": -0.1,
    },
    "ethics": {
        "words": {"moral","ethics","right","wrong","ought",
                  "duty","virtue","harm","good","value",
                  "justice","fairness","obligation","care",
                  "responsibility","autonomy","dignity"},
        "depth_boost":   +1,
        "align_boost":   +0.10,
        "valence_shift": +0.1,
    },
    "epistemology": {
        "words": {"knowledge","belief","justified","true",
                  "evidence","reason","certainty","doubt",
                  "inference","proof","truth","reliable",
                  "epistemic","warrant","justification"},
        "depth_boost":   0,
        "align_boost":   +0.05,
        "valence_shift": +0.05,
    },
    "identity": {
        "words": {"identity","self","person","continuity",
                  "memory","body","soul","who","am","exist",
                  "change","persist","same","different","real"},
        "depth_boost":   +2,
        "align_boost":   +0.20,
        "valence_shift": 0.0,
    },
    "metaphysics": {
        "words": {"existence","reality","substance","property",
                  "causation","time","space","possible","world",
                  "abstract","concrete","universal","particular",
                  "ontology","being","nothing","something"},
        "depth_boost":   +1,
        "align_boost":   +0.08,
        "valence_shift": -0.05,
    },
    "language": {
        "words": {"language","meaning","word","sentence",
                  "reference","symbol","concept","thought",
                  "communication","syntax","semantic","sign",
                  "expression","interpretation","grammar"},
        "depth_boost":   0,
        "align_boost":   0.0,
        "valence_shift": +0.1,
    },
    "physics": {
        "words": {"physical","matter","energy","particle",
                  "quantum","wave","force","mass","space",
                  "time","relativity","entropy","field",
                  "deterministic","causal","mechanism"},
        "depth_boost":   -1,
        "align_boost":   -0.05,
        "valence_shift": +0.0,
    },
}

# Default domain when no strong signal
DEFAULT_DOMAIN = "general"


def detect_domain(text: str,
                  threshold: int = 3) -> tuple:
    """
    Detect the primary domain of a text.
    Returns (domain_name, confidence, signature_hits).
    """
    words = set(re.findall(r'\b[a-z]{4,}\b', text.lower()))
    scores = {}

    for domain, config in DOMAIN_SIGNATURES.items():
        hits = len(words & config["words"])
        if hits >= threshold:
            scores[domain] = hits

    if not scores:
        return (DEFAULT_DOMAIN, 0.0, {})

    # Primary domain = highest hit count
    primary = max(scores, key=scores.get)
    confidence = min(1.0, scores[primary] / 8)

    return (primary, confidence, scores)


def apply_domain_adjustments(tag_values: dict,
                              domain: str,
                              confidence: float) -> dict:
    """
    Apply domain-specific adjustments to tag values.
    Returns adjusted copy — never modifies persistent tag.
    """
    if domain == DEFAULT_DOMAIN or confidence < 0.3:
        return tag_values

    config = DOMAIN_SIGNATURES.get(domain, {})
    if not config:
        return tag_values

    adjusted = dict(tag_values)

    # Apply adjustments weighted by confidence
    weight = confidence * 0.7  # never fully override

    if "depth_boost" in config:
        adjusted["d"] = max(1, min(6,
            int(adjusted.get("d", 3) +
                config["depth_boost"] * weight)))

    if "align_boost" in config:
        adjusted["a"] = max(-1.0, min(1.0,
            adjusted.get("a", 0.0) +
            config["align_boost"] * weight))

    if "valence_shift" in config:
        adjusted["e"] = max(-1.0, min(1.0,
            adjusted.get("e", 0.0) +
            config["valence_shift"] * weight))

    adjusted["domain_adjusted"] = True
    adjusted["domain"]          = domain
    adjusted["domain_conf"]     = round(confidence, 3)

    return adjusted


def contextual_resolve(word: str, question: str,
                       db) -> dict:
    """
    Domain-aware word resolution.
    Detects domain from question, adjusts tag values,
    returns contextually appropriate resolution.
    """
    domain, confidence, scores = detect_domain(question)

    # Get base tag
    row = db.execute(
        "SELECT w, t, d, a, c, f, e, b, s "
        "FROM word_tags WHERE word=?",
        (word.lower(),)).fetchone()

    if not row:
        return {
            "word": word, "known": False,
            "domain": domain,
            "search_needed": True,
            "cost": "high"
        }

    base_tag = {
        "w": row["w"] or 0.0,
        "t": row["t"] or 0.0,
        "d": row["d"] or 1,
        "a": row["a"] or 0.0,
        "c": row["c"] or 0.0,
        "f": row["f"] if row["f"] is not None else 1,
        "e": row["e"] or 0.0,
        "b": row["b"] or 0,
        "s": row["s"] or 0,
    }

    # Apply domain adjustments
    adjusted = apply_domain_adjustments(
        base_tag, domain, confidence)

    return {
        "word":           word,
        "known":          True,
        "domain":         domain,
        "domain_conf":    round(confidence, 3),
        "domain_scores":  scores,
        "base_w":         base_tag["w"],
        "adjusted_w":     adjusted["w"],
        "adjusted_d":     adjusted["d"],
        "adjusted_a":     adjusted["a"],
        "search_needed":  adjusted["f"] == 1,
        "confidence":     adjusted["c"],
        "cost":           ("negligible" if adjusted["w"] >= 0.8
                          else "low" if adjusted["w"] >= 0.6
                          else "medium" if adjusted["w"] >= 0.4
                          else "high"),
    }


def domain_report(question: str) -> None:
    """Show domain analysis for a question."""
    domain, conf, scores = detect_domain(question)
    print(f"\nDomain analysis: '{question[:60]}'")
    print(f"  Primary domain : {domain} (conf={conf:.2f})")
    if scores:
        for d, s in sorted(
                scores.items(), key=lambda x: x[1],
                reverse=True):
            print(f"  {d:20} hits={s}")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", type=str,
        default="Is consciousness reducible to "
                "physical substrate?")
    parser.add_argument("--word", type=str,
        default="truth")
    args = parser.parse_args()

    domain_report(args.question)

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    result = contextual_resolve(args.word,
                                args.question, db)
    print(f"\nContextual resolution of '{args.word}':")
    print(json.dumps(result, indent=2))
    db.close()
