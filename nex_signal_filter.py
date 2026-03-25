"""
nex_signal_filter.py — Signal vs Noise Filter
===============================================
Tracks which input sources produce beliefs that actually get:
  - used in replies (reinforced)
  - referenced in synthesis
  - elevated in confidence over time

Sources that produce only noise (low reinforcement, high decay)
get their confidence floor lowered and eventually suppressed.

Two components:
  1. SourceScorer   — tracks per-source signal quality over time
  2. ImportanceGate — scores individual items before absorption

Wire-in:
    from nex_signal_filter import SourceScorer, ImportanceGate
    _scorer = SourceScorer()
    _gate   = ImportanceGate()

    # Before absorbing an item:
    score = _gate.score(title, content, source_name)
    if score < ImportanceGate.MIN_IMPORTANCE:
        continue  # skip noise

    # After a belief is reinforced:
    _scorer.record_signal(source_name)

    # After a belief decays/dies:
    _scorer.record_noise(source_name)

    # Get current source multiplier:
    mult = _scorer.get_multiplier(source_name)  # 0.3 - 1.2
"""

import json
import re
import math
import os
from datetime import datetime
from pathlib import Path

CONFIG_DIR  = Path.home() / ".config" / "nex"
SCORES_PATH = CONFIG_DIR / "source_scores.json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Tuning ────────────────────────────────────────────────────────────────────
MIN_IMPORTANCE      = 0.18   # items below this are skipped entirely
SUPPRESS_THRESHOLD  = 0.12   # source multiplier below this = suppressed
BOOST_ON_SIGNAL     = 0.08   # score increase when belief is reinforced
DECAY_ON_NOISE      = 0.04   # score decrease when belief decays/dies
SCORE_FLOOR         = 0.10   # minimum source score (never fully silenced)
SCORE_CEILING       = 1.30   # maximum source score
DECAY_HALFLIFE      = 50     # events before score drifts toward 0.5

# ── Content quality signals ───────────────────────────────────────────────────
_HIGH_VALUE_TERMS = {
    # research signal
    "novel", "significant", "breakthrough", "demonstrates", "shows",
    "proves", "introduces", "proposes", "discovers", "reveals",
    "outperforms", "surpasses", "enables", "achieves", "solves",
    "analysis", "evidence", "empirical", "experiment", "evaluation",
    "benchmark", "dataset", "training", "fine-tuning", "inference",
    "theory", "theoretical", "hypothesis", "observation", "finding",
    # AI/ML concepts
    "autonomy", "emergence", "alignment", "memory", "reasoning",
    "architecture", "mechanism", "framework", "approach", "method",
    "transformer", "attention", "gradient", "optimization", "loss",
    "neural", "cognitive", "representation", "embedding", "latent",
    "reinforcement", "generative", "diffusion", "language", "model",
    "agent", "planning", "decision", "policy", "reward", "objective",
    # security
    "vulnerability", "exploit", "attack", "defense", "mitigation",
    "threat", "adversarial", "robustness", "safety", "privacy",
    # philosophy/consciousness (aeon territory)
    "consciousness", "perception", "experience", "identity", "ethics",
    "philosophy", "knowledge", "belief", "truth", "reality", "mind",
    "intelligence", "awareness", "agency", "causation", "meaning",
    # systems/coordination
    "coordination", "consensus", "distributed", "multi-agent",
    "emergent", "complex", "adaptive", "dynamic", "feedback",
}
_LOW_VALUE_TERMS = {
    "asks", "discuss", "thoughts", "opinion", "feel", "anyone",
    "help", "question", "wondering", "what", "how", "when",
    "hiring", "job", "position", "role", "salary", "remote",
    "funny", "meme", "lol", "wow", "amazing", "incredible",
    "rant", "venting", "frustrated", "confused", "lost",
    "price", "buy", "sell", "pump", "moon", "hodl", "gm",
}
_STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of",
    "with","by","from","is","are","was","were","be","been","this","that",
    "it","not","as","which","when","all","some","more","just","also",
}


class ImportanceGate:
    """
    Scores individual content items before absorption.
    Returns 0.0 (noise) to 1.0 (high signal).
    """

    MIN_IMPORTANCE = MIN_IMPORTANCE

    def score(self, title: str, content: str, source_name: str = "",
              source_multiplier: float = 1.0) -> float:
        """
        Score an item's importance. Components:
          - Content density (unique meaningful words)
          - High/low value term detection
          - Length signal (too short = low value)
          - Source multiplier from SourceScorer
        """
        text = f"{title} {content}".lower()
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text)
        meaningful = [w for w in words if w not in _STOP]

        if not meaningful:
            return 0.0

        # 1. Density score
        unique = set(meaningful)
        density = len(unique) / max(len(meaningful), 1)

        # 2. High-value term bonus
        hv_hits = sum(1 for t in _HIGH_VALUE_TERMS if t in text)
        lv_hits = sum(1 for t in _LOW_VALUE_TERMS if t in text)
        term_score = min(1.0, max(0.0, (hv_hits - lv_hits * 0.5) * 0.15))

        # 3. Length signal (very short = noise)
        length_score = min(1.0, len(content) / 150)

        # 4. Title quality (questions and short titles are lower value)
        title_score = 0.8
        if title.endswith("?"):
            title_score = 0.4
        elif len(title) < 20:
            title_score = 0.5

        # Combine
        raw = (
            density      * 0.30 +
            term_score   * 0.30 +
            length_score * 0.20 +
            title_score  * 0.20
        )

        # Apply source multiplier
        final = min(1.0, raw * source_multiplier)
        return round(final, 3)

    def is_important(self, title: str, content: str,
                     source_name: str = "", source_multiplier: float = 1.0) -> bool:
        return self.score(title, content, source_name, source_multiplier) >= self.MIN_IMPORTANCE

    def score_batch(self, items: list[dict], source_multiplier: float = 1.0) -> list[dict]:
        """Score a list of items, add 'importance' field, sort by importance."""
        for item in items:
            item["importance"] = self.score(
                item.get("title", ""),
                item.get("content", item.get("summary", "")),
                item.get("source", ""),
                source_multiplier,
            )
        return sorted(items, key=lambda x: -x.get("importance", 0))


class SourceScorer:
    """
    Tracks per-source signal quality over time.
    Adjusts confidence multiplier based on reinforcement vs decay ratio.
    """

    def __init__(self):
        self._scores = self._load()

    def _load(self) -> dict:
        if SCORES_PATH.exists():
            try:
                return json.loads(SCORES_PATH.read_text())
            except Exception:
                pass
        return {}

    def _save(self):
        try:
            SCORES_PATH.write_text(json.dumps(self._scores, indent=2))
        except Exception:
            pass

    def _get(self, source: str) -> dict:
        if source not in self._scores:
            self._scores[source] = {
                "score":        0.7,   # start neutral-positive
                "signal_count": 0,
                "noise_count":  0,
                "total_events": 0,
                "last_updated": datetime.now().isoformat(),
                "suppressed":   False,
            }
        return self._scores[source]

    def record_signal(self, source: str, weight: float = 1.0):
        """Call when a belief from this source is reinforced/used."""
        entry = self._get(source)
        entry["signal_count"] += 1
        entry["total_events"] += 1
        entry["score"] = min(
            SCORE_CEILING,
            entry["score"] + BOOST_ON_SIGNAL * weight
        )
        entry["suppressed"]   = False
        entry["last_updated"] = datetime.now().isoformat()
        self._save()

    def record_noise(self, source: str, weight: float = 1.0):
        """Call when a belief from this source decays or dies."""
        entry = self._get(source)
        entry["noise_count"] += 1
        entry["total_events"] += 1
        entry["score"] = max(
            SCORE_FLOOR,
            entry["score"] - DECAY_ON_NOISE * weight
        )
        # Suppress if consistently noisy
        if entry["score"] < SUPPRESS_THRESHOLD and entry["total_events"] >= 10:
            entry["suppressed"] = True
            print(f"  [SignalFilter] SUPPRESSED: {source} (score={entry['score']:.2f})")
        entry["last_updated"] = datetime.now().isoformat()
        self._save()

    def get_multiplier(self, source: str) -> float:
        """Return confidence multiplier for this source (0.3 - 1.2)."""
        entry = self._get(source)
        if entry.get("suppressed"):
            return 0.3
        return round(max(0.3, min(1.2, entry["score"])), 3)

    def is_suppressed(self, source: str) -> bool:
        return self._get(source).get("suppressed", False)

    def get_report(self) -> list[dict]:
        """Return sources sorted by score for dashboard."""
        report = []
        for name, data in self._scores.items():
            report.append({
                "source":     name,
                "score":      round(data["score"], 3),
                "signals":    data["signal_count"],
                "noise":      data["noise_count"],
                "suppressed": data.get("suppressed", False),
            })
        return sorted(report, key=lambda x: -x["score"])

    def print_report(self):
        print("\n  [SignalFilter] Source Quality Report:")
        for r in self.get_report():
            status = " [SUPPRESSED]" if r["suppressed"] else ""
            print(f"    {r['source']:30s} score={r['score']:.2f} "
                  f"✓{r['signals']} ✗{r['noise']}{status}")


# ── Singleton ─────────────────────────────────────────────────────────────────
_scorer_instance = None
_gate_instance   = None

def get_scorer() -> SourceScorer:
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = SourceScorer()
    return _scorer_instance

def get_gate() -> ImportanceGate:
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = ImportanceGate()
    return _gate_instance


# ── Hook into belief reinforcement ───────────────────────────────────────────
def on_belief_reinforced(source: str):
    """Call this whenever a belief is reinforced (used in reply/synthesis)."""
    get_scorer().record_signal(source)

def on_belief_decayed(source: str):
    """Call this whenever a belief decays significantly."""
    get_scorer().record_noise(source)


if __name__ == "__main__":
    gate   = ImportanceGate()
    scorer = SourceScorer()

    # Test scoring
    test_items = [
        ("Novel multi-agent coordination mechanism enables emergent consensus",
         "Researchers demonstrate a new approach where agents self-organize...", "arxiv"),
        ("Anyone else feel like AI is overhyped?",
         "Just wondering what people think", "reddit"),
        ("GPT-4 outperforms human experts on medical diagnosis benchmark",
         "Study shows significant improvement over baseline in 12 specialties", "MIT Tech Review"),
    ]

    print("Item importance scores:")
    for title, content, source in test_items:
        score = gate.score(title, content, source)
        label = "SIGNAL" if score >= MIN_IMPORTANCE else "NOISE"
        print(f"  [{label}] {score:.2f} — {title[:60]}")

    scorer.print_report()
