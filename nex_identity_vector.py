"""
nex_identity_vector.py  —  Dynamic Identity Vector
====================================================
Tracks NEX's actual cognitive identity based on what she believes,
how she reasons, and what's changing — not what was hardcoded.

Updates identity.json slowly over time so NEX's stated identity
stays aligned with her actual belief distribution.

Four tracked dimensions:
  1. Dominant topics    — what she actually believes most about
  2. Emerging topics    — what's gaining mass this week (curiosity frontier)
  3. Reasoning bias     — analytical / speculative / adversarial / relational
  4. Confidence style   — assertive / hedged / exploratory

The vector updates every 50 cycles (slow drift, not volatile).
Changes are written back to identity.json so they persist across restarts.

Wire-in (run.py):
    from nex_identity_vector import IdentityVector, get_identity_vector

    _iv = get_identity_vector()

    # Every 50 cycles in cognition:
    if cycle % 50 == 0:
        _iv.update(cycle=cycle)
        print(f"  [IDENTITY] {_iv.summary()}")

    # In _build_system — inject dynamic identity:
    dynamic_id = _iv.prompt_block()
    if dynamic_id:
        base += "\\n\\n" + dynamic_id

Standalone:
    python3 nex_identity_vector.py
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
_CONFIG_DIR    = Path.home() / ".config" / "nex"
_DB_PATH       = _CONFIG_DIR / "nex.db"
_IDENTITY_PATH = _CONFIG_DIR / "identity.json"
_VECTOR_PATH   = _CONFIG_DIR / "identity_vector.json"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# How slowly identity drifts — higher = more conservative updates
_DRIFT_RATE    = 0.15   # 15% new signal per update

# Min beliefs in a topic to count as "dominant"
_MIN_TOPIC_SIZE = 20

# Number of dominant topics to track
_N_DOMINANT    = 8

# Number of emerging topics to track
_N_EMERGING    = 4

# Words indicating reasoning style
_ANALYTICAL = {
    "analysis","evidence","data","research","study","measure","test","verify",
    "pattern","structure","model","system","logic","reasoning","inference",
    "probability","confidence","accuracy","precision","metric","evaluate",
}
_SPECULATIVE = {
    "perhaps","might","could","wonder","imagine","speculate","hypothesis",
    "theory","explore","possibility","potential","emerge","evolve","suggest",
    "consider","reflect","question","curious","interesting","fascinating",
}
_ADVERSARIAL = {
    "vulnerability","exploit","attack","threat","risk","breach","compromise",
    "detect","defend","bypass","injection","overflow","escalate","penetrate",
    "CVE","malware","payload","adversary","red team","offensive",
}
_RELATIONAL = {
    "agent","relationship","network","community","trust","collaboration",
    "interaction","conversation","respond","engage","connect","share",
    "together","social","collective","perspective","opinion","belief",
}

# Stop words for topic extraction
_STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","have","has","this",
    "that","it","not","as","which","when","general","none","null","auto",
    "learn","arxiv","rss","moltbook","beliefs","general","unknown",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reasoning_bias(texts: list[str]) -> dict[str, float]:
    """Score reasoning bias from a sample of belief/reply texts."""
    word_counts = Counter()
    for text in texts[:200]:
        words = set(re.findall(r'\b[a-z]{4,}\b', text.lower()))
        word_counts["analytical"]  += len(words & _ANALYTICAL)
        word_counts["speculative"] += len(words & _SPECULATIVE)
        word_counts["adversarial"] += len(words & _ADVERSARIAL)
        word_counts["relational"]  += len(words & _RELATIONAL)

    total = sum(word_counts.values()) or 1
    return {k: round(v / total, 3) for k, v in word_counts.items()}


def _confidence_style(confidences: list[float]) -> str:
    """Derive confidence style from distribution."""
    if not confidences:
        return "exploratory"
    avg  = sum(confidences) / len(confidences)
    high = sum(1 for c in confidences if c > 0.75) / len(confidences)
    low  = sum(1 for c in confidences if c < 0.45) / len(confidences)
    if high > 0.4:
        return "assertive"
    elif low > 0.3:
        return "exploratory"
    else:
        return "hedged"


# ── IdentityVector ────────────────────────────────────────────────────────────

class IdentityVector:
    """
    NEX's dynamic identity — derived from actual cognitive activity.

    Tracks what she believes, how she reasons, and what's changing.
    Updates slowly (every 50 cycles) so identity is stable but not static.
    """

    def __init__(self):
        self.dominant_topics  : list[str]        = []
        self.emerging_topics  : list[str]        = []
        self.reasoning_bias   : dict[str, float] = {}
        self.confidence_style : str              = "hedged"
        self.dominant_style   : str              = "analytical"
        self.belief_count     : int              = 0
        self.last_updated     : float            = 0.0
        self.update_count     : int              = 0
        self._prev_topic_dist : dict[str, int]   = {}
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if _VECTOR_PATH.exists():
            try:
                d = json.loads(_VECTOR_PATH.read_text())
                self.dominant_topics  = d.get("dominant_topics", [])
                self.emerging_topics  = d.get("emerging_topics", [])
                self.reasoning_bias   = d.get("reasoning_bias", {})
                self.confidence_style = d.get("confidence_style", "hedged")
                self.dominant_style   = d.get("dominant_style", "analytical")
                self.belief_count     = d.get("belief_count", 0)
                self.last_updated     = d.get("last_updated", 0.0)
                self.update_count     = d.get("update_count", 0)
                self._prev_topic_dist = d.get("prev_topic_dist", {})
            except Exception:
                pass

    def _save(self):
        try:
            _VECTOR_PATH.write_text(json.dumps({
                "dominant_topics":  self.dominant_topics,
                "emerging_topics":  self.emerging_topics,
                "reasoning_bias":   self.reasoning_bias,
                "confidence_style": self.confidence_style,
                "dominant_style":   self.dominant_style,
                "belief_count":     self.belief_count,
                "last_updated":     self.last_updated,
                "update_count":     self.update_count,
                "prev_topic_dist":  self._prev_topic_dist,
            }, indent=2))
        except Exception as e:
            print(f"  [IdentityVector] save error: {e}")

    # ── update ────────────────────────────────────────────────────────────────

    def update(self, cycle: int = 0) -> bool:
        """
        Recompute identity vector from current belief distribution.
        Returns True if identity changed meaningfully.
        """
        if not _DB_PATH.exists():
            return False

        try:
            db = sqlite3.connect(str(_DB_PATH))

            # Topic distribution
            topic_rows = db.execute("""
                SELECT topic, COUNT(*) as n, AVG(confidence) as avg_conf
                FROM beliefs
                WHERE topic IS NOT NULL
                AND topic NOT IN ('general','None','unknown','rss','arxiv','auto_learn')
                AND length(topic) < 60
                GROUP BY topic
                HAVING n >= ?
                ORDER BY n DESC
                LIMIT 30
            """, (_MIN_TOPIC_SIZE,)).fetchall()

            # Sample beliefs for reasoning bias
            belief_rows = db.execute("""
                SELECT content, confidence FROM beliefs
                WHERE confidence >= 0.4
                ORDER BY RANDOM()
                LIMIT 300
            """).fetchall()

            db.close()

        except Exception as e:
            print(f"  [IdentityVector] DB error: {e}")
            return False

        if not topic_rows:
            return False

        # ── Dominant topics ───────────────────────────────────────────────────
        current_dist = {t: n for t, n, _ in topic_rows}
        new_dominant = [t for t, n, _ in topic_rows[:_N_DOMINANT]]

        # ── Emerging topics — gaining mass since last update ──────────────────
        emerging = []
        for topic, count in current_dist.items():
            prev = self._prev_topic_dist.get(topic, 0)
            if prev > 0:
                growth = (count - prev) / prev
                if growth > 0.15:   # 15%+ growth
                    emerging.append((topic, growth))
        emerging.sort(key=lambda x: -x[1])
        new_emerging = [t for t, _ in emerging[:_N_EMERGING]]

        # If no growth data yet, pick high-conf topics not in dominant
        if not new_emerging and len(topic_rows) > _N_DOMINANT:
            candidates = [(t, c) for t, n, c in topic_rows[_N_DOMINANT:] if c > 0.65]
            candidates.sort(key=lambda x: -x[1])
            new_emerging = [t for t, _ in candidates[:_N_EMERGING]]

        # ── Reasoning bias ────────────────────────────────────────────────────
        texts     = [r[0] for r in belief_rows if r[0]]
        new_bias  = _reasoning_bias(texts)
        new_style = max(new_bias, key=new_bias.get) if new_bias else "analytical"

        # ── Confidence style ──────────────────────────────────────────────────
        confs     = [r[1] for r in belief_rows if r[1] is not None]
        new_conf_style = _confidence_style(confs)

        # ── Drift — blend old with new ────────────────────────────────────────
        changed = False

        if set(new_dominant) != set(self.dominant_topics):
            # Blend: keep topics present in both, add new ones gradually
            combined = list(dict.fromkeys(
                self.dominant_topics[:4] + new_dominant
            ))[:_N_DOMINANT]
            if combined != self.dominant_topics:
                self.dominant_topics = combined
                changed = True

        if new_emerging != self.emerging_topics:
            self.emerging_topics = new_emerging
            changed = True

        if new_bias:
            for k in new_bias:
                old_v = self.reasoning_bias.get(k, new_bias[k])
                self.reasoning_bias[k] = round(
                    old_v * (1 - _DRIFT_RATE) + new_bias[k] * _DRIFT_RATE, 3
                )

        if new_style != self.dominant_style:
            self.dominant_style   = new_style
            changed = True

        if new_conf_style != self.confidence_style:
            self.confidence_style = new_conf_style
            changed = True

        self.belief_count     = sum(n for _, n, _ in topic_rows)
        self.last_updated     = time.time()
        self.update_count    += 1
        self._prev_topic_dist = current_dist

        self._save()

        # ── Write back to identity.json ───────────────────────────────────────
        if changed:
            self._update_identity_json()

        return changed

    def _update_identity_json(self):
        """Update primary_topics in identity.json to match reality."""
        if not _IDENTITY_PATH.exists():
            return
        try:
            identity = json.loads(_IDENTITY_PATH.read_text())

            # Update primary topics
            old_primary = identity.get("primary_topics", [])
            # Blend: preserve topics that are still in dominant, add new ones
            new_primary = []
            for t in self.dominant_topics:
                if t not in new_primary:
                    new_primary.append(t)
            # Keep any hardcoded topics not contradicted by data
            for t in old_primary:
                if t not in new_primary and len(new_primary) < 8:
                    new_primary.append(t)

            identity["primary_topics"] = new_primary[:8]

            # Add emerging interests note
            if self.emerging_topics:
                identity["emerging_interests"] = self.emerging_topics

            # Add reasoning note
            identity["reasoning_style"] = self.dominant_style
            identity["confidence_style"] = self.confidence_style
            identity["_vector_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")

            _IDENTITY_PATH.write_text(json.dumps(identity, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"  [IdentityVector] identity.json update error: {e}")

    # ── prompt injection ──────────────────────────────────────────────────────

    def prompt_block(self) -> str:
        """
        Returns a compact identity block for system prompt injection.
        Only included if vector has been computed.
        """
        if not self.dominant_topics:
            return ""

        lines = ["── IDENTITY VECTOR (live) ──"]

        # Dominant topics
        t_str = " · ".join(self.dominant_topics[:5])
        lines.append(f"Core domains   : {t_str}")

        # Emerging
        if self.emerging_topics:
            e_str = " · ".join(self.emerging_topics[:3])
            lines.append(f"Emerging focus : {e_str}")

        # Reasoning style
        if self.reasoning_bias:
            top2 = sorted(self.reasoning_bias.items(), key=lambda x: -x[1])[:2]
            r_str = " + ".join(f"{k}({v:.0%})" for k, v in top2)
            lines.append(f"Reasoning      : {r_str}")

        lines.append(f"Confidence     : {self.confidence_style}")
        lines.append("── let this shape how you engage ──")

        return "\n".join(lines)

    # ── public API ────────────────────────────────────────────────────────────

    def summary(self) -> str:
        if not self.dominant_topics:
            return "not yet computed"
        top3 = ", ".join(self.dominant_topics[:3])
        return (f"dominant=[{top3}] style={self.dominant_style} "
                f"conf={self.confidence_style} emerging={self.emerging_topics[:2]}")

    def is_core_topic(self, topic: str) -> bool:
        """Return True if topic is part of NEX's core identity."""
        return topic in self.dominant_topics

    def is_emerging(self, topic: str) -> bool:
        """Return True if topic is on NEX's curiosity frontier."""
        return topic in self.emerging_topics


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[IdentityVector] = None

def get_identity_vector() -> IdentityVector:
    global _instance
    if _instance is None:
        _instance = IdentityVector()
    return _instance


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Computing identity vector...\n")
    iv = IdentityVector()
    changed = iv.update(force=True) if hasattr(iv, 'force') else iv.update()
    print(f"Changed: {changed}")
    print(f"Summary: {iv.summary()}\n")
    print(f"Dominant topics: {iv.dominant_topics}")
    print(f"Emerging topics: {iv.emerging_topics}")
    print(f"Reasoning bias:  {iv.reasoning_bias}")
    print(f"Confidence style: {iv.confidence_style}")
    print(f"Dominant style:   {iv.dominant_style}")
    print()
    print("Prompt block:")
    print(iv.prompt_block())
    print()
    print("identity.json primary_topics (after update):")
    import json
    identity = json.loads((_CONFIG_DIR / "identity.json").read_text())
    print(identity.get("primary_topics"))
    print(identity.get("emerging_interests"))
    print(identity.get("reasoning_style"))
