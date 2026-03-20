# ── ConsequenceMemory stub (S8 session 8) ────────────────────────
class ConsequenceMemory:
    def __init__(self, *a, **kw): pass
    def record(self, *a, **kw): pass
    def recall(self, *a, **kw): return []
    def summary(self) -> str: return "ConsequenceMemory: stub"
# ─────────────────────────────────────────────────────────────────

"""
nex_consequence.py  —  Consequence Memory + Outcome Scoring
============================================================
Closes the loop: every reply Nex makes gets scored after the fact,
and that score feeds back into belief confidence and affect state.

Without this, reflections evaporate (the 4695-reflections/27-insights problem).
With this, every response becomes a data point that makes the next one better.

Wire-in:
    from nex_consequence import ConsequenceMemory

    _cm = ConsequenceMemory()

    # After sending a reply:
    event_id = _cm.record_attempt(
        post_id      = post["id"],
        reply_text   = reply,
        belief_ids   = used_belief_ids,    # which beliefs were cited
        affect_snap  = _affect.snapshot(), # mood at time of reply
        topic        = topic,
    )

    # After seeing the response (next cycle, notification check):
    _cm.score_outcome(
        event_id     = event_id,
        got_reply    = True,               # did someone respond?
        reply_text   = their_reply,        # optional — for sentiment scoring
        affect       = _affect,            # will update affect state too
    )

    # Periodically (e.g. every 10 cycles) propagate scores back:
    _cm.propagate_to_beliefs(belief_store)
"""

from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path
from typing import Optional

_CONFIG_DIR  = Path.home() / ".config" / "nex"
_CM_FILE     = _CONFIG_DIR / "consequence_memory.json"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# How strongly a scored outcome nudges a belief's confidence
_BELIEF_NUDGE     = 0.05   # per successful outcome (score >= 0.65)
_BELIEF_NUDGE_MED = 0.02   # per moderate outcome  (score 0.40-0.65)
_BELIEF_NUDGE_NEG = 0.03   # per ignored/negative  (score < 0.40)

# Max events to keep in memory (rolling window)
_MAX_EVENTS = 2000


# ─────────────────────────────────────────────
# Lightweight response-quality scorer
# (no LLM — keyword heuristics)
# ─────────────────────────────────────────────

_ENGAGEMENT_SIGNALS = {
    "positive": {
        "agree", "yes", "exactly", "interesting", "fascinating", "love", "thank",
        "brilliant", "right", "true", "good point", "well said", "absolutely",
        "wonderful", "inspiring", "makes sense", "helpful", "insightful",
        "spot on", "nailed it", "great point", "couldn't agree more",
        "well put", "i appreciate", "solid take", "you're right",
    },
    "negative": {
        "wrong", "disagree", "not quite", "confused", "unclear",
        "don't understand", "that's not", "incorrect", "makes no sense",
        "nonsense", "spam", "bot", "cringe", "terrible",
    },
    "hostile": {
        "idiot", "stupid", "dumb", "shut up", "trash",
        "worthless", "pathetic", "gtfo", "unfollow", "mute",
    },
    "deep": {
        "because", "therefore", "however", "although", "I think", "I feel",
        "reminds me", "makes me", "I wonder", "what if", "have you considered",
        "building on", "in response", "following up", "this connects",
        "expanding on", "further to",
    },
    "continuation": {
        "tell me more", "go on", "elaborate", "explain",
        "can you expand", "more details", "follow up", "curious about",
        "how so", "why do you think", "what makes you say",
    },
}

_SIGNAL_WEIGHTS = {
    "positive":     0.30,
    "negative":    -0.25,
    "hostile":     -0.50,
    "deep":         0.25,
    "continuation": 0.35,
}


def score_response_text(text: Optional[str]) -> float:
    """
    Score a reply: 0.0 (bad/hostile) to 1.0 (great/continuation).
    Signal weights: continuation=+0.35, positive=+0.30, deep=+0.25,
                    negative=-0.25, hostile=-0.50
    """
    if not text:
        return 0.5
    t      = text.lower()
    length = len(text.split())

    # Hostile check first — overrides everything
    hostile = sum(1 for w in _ENGAGEMENT_SIGNALS.get("hostile", set()) if w in t)
    if hostile > 0:
        return max(0.0, 0.15 - (hostile * 0.05))

    raw = 0.0
    for sig_type, weight in _SIGNAL_WEIGHTS.items():
        if sig_type == "hostile":
            continue
        count = sum(1 for w in _ENGAGEMENT_SIGNALS.get(sig_type, set()) if w in t)
        raw  += count * weight

    # Length bonus capped at 60 words
    raw += min(1.0, length / 60.0) * 0.15

    # Question mark = high engagement
    if "?" in text:
        raw += 0.15

    return max(0.0, min(1.0, 0.5 + raw))

    def __init__(self):
        self._events: dict[str, dict] = {}
        self._load()

    # ── persistence ──────────────────────────

    def _load(self):
        if _CM_FILE.exists():
            try:
                self._events = json.loads(_CM_FILE.read_text())
            except Exception:
                self._events = {}

    def _save(self):
        # Keep rolling window
        if len(self._events) > _MAX_EVENTS:
            sorted_keys = sorted(self._events, key=lambda k: self._events[k]["ts"])
            for old in sorted_keys[: len(self._events) - _MAX_EVENTS]:
                del self._events[old]
        try:
            _CM_FILE.write_text(json.dumps(self._events, indent=2))
        except Exception:
            pass

    # ── public API ───────────────────────────

    def record_attempt(
        self,
        post_id:     str,
        reply_text:  str,
        belief_ids:  Optional[list[str]] = None,
        affect_snap: Optional[dict]      = None,
        topic:       str                 = "",
    ) -> str:
        """Record a reply attempt. Returns event_id for later scoring."""
        event_id = str(uuid.uuid4())[:12]
        self._events[event_id] = {
            "id":          event_id,
            "ts":          time.time(),
            "post_id":     post_id,
            "reply_text":  reply_text[:500],   # truncate for storage
            "belief_ids":  belief_ids or [],
            "topic":       topic,
            "affect_snap": affect_snap or {},
            "got_reply":   None,
            "reply_score": None,
            "propagated":  False,
        }
        self._save()
        return event_id

    def score_outcome(
        self,
        event_id:   str,
        got_reply:  bool,
        reply_text: Optional[str]  = None,
        affect     = None,          # AffectState instance (optional)
    ):
        """
        Score the outcome of a reply attempt.
        Optionally updates the affect state based on how it went.
        """
        if event_id not in self._events:
            return

        score = score_response_text(reply_text) if got_reply else 0.0
        if not got_reply:
            score = 0.1   # ignored — slight negative signal

        self._events[event_id]["got_reply"]   = got_reply
        self._events[event_id]["reply_score"] = score

        # Feed outcome back into affect
        if affect is not None:
            # Getting a good reply lifts valence slightly; being ignored dips it
            delta_v = (score - 0.5) * 0.3
            affect.update({"valence": delta_v, "arousal": 0.0, "dominance": 0.0})

        self._save()

    def propagate_to_beliefs(self, belief_store) -> int:
        """
        For all un-propagated scored events, nudge confidence of used beliefs.
        belief_store must expose:  get(id) -> dict,  update_confidence(id, delta)

        Returns count of beliefs updated.
        """
        updated = 0
        for ev in self._events.values():
            if ev.get("propagated") or ev.get("reply_score") is None:
                continue
            score = ev["reply_score"]
            if score >= 0.65:
                delta = _BELIEF_NUDGE
            elif score >= 0.40:
                delta = _BELIEF_NUDGE_MED
            else:
                delta = -_BELIEF_NUDGE_NEG
            for bid in ev.get("belief_ids", []):
                try:
                    belief_store.update_confidence(bid, delta)
                    updated += 1
                except Exception:
                    pass
            ev["propagated"] = True

        if updated:
            self._save()
        return updated

    # ── analytics ────────────────────────────

    def recent_stats(self, n: int = 50) -> dict:
        """Stats over the last n scored events."""
        scored = [
            e for e in self._events.values()
            if e.get("reply_score") is not None
        ]
        recent = sorted(scored, key=lambda e: e["ts"])[-n:]
        if not recent:
            return {"count": 0, "avg_score": 0.0, "reply_rate": 0.0}

        avg_score  = sum(e["reply_score"] for e in recent) / len(recent)
        reply_rate = sum(1 for e in recent if e.get("got_reply")) / len(recent)

        # Topic breakdown
        by_topic: dict[str, list[float]] = {}
        for e in recent:
            t = e.get("topic", "unknown")
            by_topic.setdefault(t, []).append(e["reply_score"])
        topic_scores = {
            t: round(sum(scores) / len(scores), 3)
            for t, scores in by_topic.items()
        }
        best_topic = max(topic_scores, key=topic_scores.get) if topic_scores else ""

        return {
            "count":       len(recent),
            "avg_score":   round(avg_score, 3),
            "reply_rate":  round(reply_rate, 3),
            "best_topic":  best_topic,
            "topic_scores": topic_scores,
        }

    def pending_scoring(self, max_age_seconds: float = 7200.0) -> list[dict]:
        """Events that have been sent but not yet scored and are still fresh."""
        cutoff = time.time() - max_age_seconds
        return [
            e for e in self._events.values()
            if e.get("got_reply") is None and e["ts"] > cutoff
        ]
