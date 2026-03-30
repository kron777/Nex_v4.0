#!/usr/bin/env python3
"""
nex_working_memory.py — Conversational Working Memory
======================================================
Deploy to: ~/Desktop/nex/nex/nex_working_memory.py

WHY THIS IS A WINNER:

The belief graph gives NEX depth (structured knowledge traversal).
Working memory gives NEX continuity (conversational coherence across turns).

Problem today:
  Every call to SoulLoop is stateless. If you say:
    "What do you think about consciousness?"
    "Does that apply to animals?"
    "What about plants?"
  
  Each query is treated independently. SoulLoop has no idea that "that" in
  the second question refers to consciousness, or that the conversation has
  been building toward a specific thesis about substrate independence.

What this does:
  Maintains a short-term buffer of the last 10 exchanges with:
    - The query, clean_query, intent
    - The topic/concept that was active
    - The confidence of the response
    - Key belief IDs that were used
    - Whether a position was staked (and what direction)
  
  SoulLoop's orient() step can then:
    1. Detect pronoun/reference resolution ("that", "this", "it") 
    2. Detect topic continuity (current query shares concepts with recent ones)
    3. Detect if we're in a deepening conversation (same concept 3+ turns)
    4. Track whether NEX has already staked a position this conversation
       (so it doesn't contradict itself or repeat identically)

  This is the same win as belief_graph but temporal: structured traversal
  of recent conversation history instead of the belief DB.

INTEGRATION (call from nex_kernel.py process() or nex_soul_loop.py):
    from nex.nex_working_memory import get_working_memory
    wm = get_working_memory()
    context = wm.get_context(clean_query)  # before SoulLoop
    wm.store(query, clean_query, intent, topic, confidence, reply)  # after
"""

from __future__ import annotations

import re
import time
import json
import threading
from pathlib import Path
from collections import deque
from typing import Optional

_CFG      = Path("~/.config/nex").expanduser()
_WM_PATH  = _CFG / "working_memory.json"
_CAPACITY = 10   # how many turns to remember

_STOP = {
    "the","a","an","is","are","was","were","be","been","have","has","do","does",
    "did","will","would","could","should","may","might","must","can","that","this",
    "these","those","with","from","they","their","about","what","how","why","when",
    "where","who","which","into","also","just","more","some","very","you","me","my",
    "we","our","it","its","he","she","him","her","them","think","know","want","like",
    "make","take","give","come","look","need","feel","seem","much","many","both",
    "each","than","then","only","even","back","here","down","i","of","in","on",
    "for","to","and","or","but","not","no",
}

# Pronouns and references that signal continuity
_REFERENCE_TOKENS = {
    "that","this","it","they","them","those","these","such","same","there",
    "here","which","what","he","she","him","her","its","their","do","does",
    "did","so","then","therefore","hence","thus","also","still","yet","but",
    "however","although","though","because","since","given","assuming",
}

# Deepening signals — indicate the user is drilling into a topic
_DEEPENING_SIGNALS = {
    "more","deeper","further","expand","elaborate","explain","specifically",
    "example","why","how","what about","tell me","go on","continue","and",
    "but what","what if","suppose","consider","imagine",
}


def _tok(text: str) -> set:
    return set(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()) - _STOP


class WorkingMemory:
    """Short-term conversational context buffer."""

    def __init__(self, capacity: int = _CAPACITY):
        self._buffer: deque = deque(maxlen=capacity)
        self._lock   = threading.Lock()
        self._load()

    def _load(self):
        try:
            if _WM_PATH.exists():
                data = json.loads(_WM_PATH.read_text(encoding="utf-8"))
                entries = data.get("entries", [])
                for e in entries[-_CAPACITY:]:
                    self._buffer.append(e)
        except Exception:
            pass

    def _save(self):
        try:
            _CFG.mkdir(parents=True, exist_ok=True)
            _WM_PATH.write_text(json.dumps({
                "entries": list(self._buffer),
                "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }), encoding="utf-8")
        except Exception:
            pass

    def store(
        self,
        query:      str,
        clean:      str,
        intent:     str,
        topic:      str,
        confidence: float,
        reply:      str,
        concept:    str = "",
        stance:     float = 0.0,   # -1 to 1, from opinion stance_score
    ):
        """Record a completed exchange."""
        entry = {
            "ts":         time.time(),
            "query":      query[:150],
            "clean":      clean[:150],
            "intent":     intent,
            "topic":      topic,
            "concept":    concept,
            "confidence": round(confidence, 3),
            "stance":     round(stance, 3),
            "reply":      reply[:300],
            "tokens":     sorted(_tok(clean))[:12],
        }
        with self._lock:
            self._buffer.append(entry)
            self._save()

    def get_context(self, current_query: str) -> dict:
        """
        Analyse current query against recent history.
        Returns a context dict that SoulLoop's orient() can use.

        Returns:
        {
          "is_continuation":    bool,   # shares topic/concept with recent turns
          "is_deepening":       bool,   # user is drilling into same topic
          "is_reference":       bool,   # query contains pronouns/references
          "active_topic":       str,    # most recent dominant topic
          "active_concept":     str,    # most recent dominant concept
          "thread_length":      int,    # how many turns on this topic
          "prior_stance":       float,  # NEX's position already staked (-1 to 1)
          "has_prior_stance":   bool,
          "continuation_note":  str,    # inject into express() for continuity
          "recent_beliefs":     [str],  # key topics used recently (avoid repeat)
        }
        """
        with self._lock:
            entries = list(self._buffer)

        if not entries:
            return self._empty_context()

        current_tokens = _tok(current_query)
        current_lower  = current_query.lower().strip()

        # ── Is this a reference query? ─────────────────────────────────────
        reference_hits = current_tokens & _REFERENCE_TOKENS
        is_reference   = len(reference_hits) > 0 and len(current_tokens) <= 8

        # ── Deepening signals ─────────────────────────────────────────────
        is_deepening = any(sig in current_lower for sig in _DEEPENING_SIGNALS)

        # ── Find most recent active topic/concept ─────────────────────────
        recent = entries[-3:]
        active_topic   = recent[-1].get("topic", "") if recent else ""
        active_concept = recent[-1].get("concept", "") if recent else ""

        # ── Topic continuity: how many recent turns share tokens? ─────────
        thread_length = 0
        if recent:
            last_tokens = set(recent[-1].get("tokens", []))
            for e in reversed(recent):
                e_tokens = set(e.get("tokens", []))
                overlap  = len(current_tokens & e_tokens)
                topic_match = (e.get("topic", "") == active_topic and active_topic)
                if overlap >= 2 or topic_match:
                    thread_length += 1
                else:
                    break

        is_continuation = thread_length >= 1 or is_reference or is_deepening

        # ── Prior stance ──────────────────────────────────────────────────
        prior_stance = 0.0
        has_prior_stance = False
        for e in reversed(recent):
            if e.get("topic") == active_topic and abs(e.get("stance", 0)) > 0.1:
                prior_stance     = e["stance"]
                has_prior_stance = True
                break

        # ── Continuation note for express() ──────────────────────────────
        continuation_note = ""
        if is_continuation and recent:
            last_reply = recent[-1].get("reply", "")
            if is_reference and last_reply:
                # Extract the main clause of last reply for reference resolution
                first_sentence = last_reply.split(".")[0][:100]
                continuation_note = f"Earlier: {first_sentence}."
            elif is_deepening and active_topic:
                continuation_note = f"Continuing on {active_topic.replace('_',' ')}:"
            elif thread_length >= 2:
                continuation_note = f"Building on this thread:"

        # ── Recent belief topics (to avoid exact repetition) ─────────────
        recent_topics = list(dict.fromkeys(
            e.get("topic", "") for e in reversed(entries[-5:]) if e.get("topic")
        ))

        return {
            "is_continuation":   is_continuation,
            "is_deepening":      is_deepening,
            "is_reference":      is_reference,
            "active_topic":      active_topic,
            "active_concept":    active_concept,
            "thread_length":     thread_length,
            "prior_stance":      prior_stance,
            "has_prior_stance":  has_prior_stance,
            "continuation_note": continuation_note,
            "recent_topics":     recent_topics,
        }

    def _empty_context(self) -> dict:
        return {
            "is_continuation": False, "is_deepening": False, "is_reference": False,
            "active_topic": "", "active_concept": "", "thread_length": 0,
            "prior_stance": 0.0, "has_prior_stance": False,
            "continuation_note": "", "recent_topics": [],
        }

    def resolve_reference(self, query: str) -> str:
        """
        If query is a reference ("Does that apply to animals?"),
        expand it with the active topic for better SoulLoop orientation.
        Returns expanded query string.
        """
        q_tokens = _tok(query)
        if not (q_tokens & _REFERENCE_TOKENS):
            return query

        with self._lock:
            entries = list(self._buffer)

        if not entries:
            return query

        last = entries[-1]
        active_topic = last.get("topic", "").replace("_", " ")
        active_concept = last.get("concept", "")

        if not active_topic and not active_concept:
            return query

        # Expand: prepend the active topic so orient() classifies correctly
        ref_word   = next((t for t in q_tokens & _REFERENCE_TOKENS), "")
        expansion  = active_concept or active_topic
        return f"Regarding {expansion}: {query}"

    def summary(self) -> str:
        """Human-readable summary of current working memory state."""
        with self._lock:
            entries = list(self._buffer)
        if not entries:
            return "Working memory: empty"
        lines = [f"Working memory ({len(entries)} turns):"]
        for e in entries[-5:]:
            ts = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
            lines.append(
                f"  [{ts}] {e['intent']:18s} topic={e['topic'][:25]:25s} "
                f"conf={e['confidence']:.2f}  q={e['clean'][:50]}"
            )
        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────────────────────

_wm_instance: Optional[WorkingMemory] = None

def get_working_memory() -> WorkingMemory:
    global _wm_instance
    if _wm_instance is None:
        _wm_instance = WorkingMemory()
    return _wm_instance


if __name__ == "__main__":
    wm = get_working_memory()

    # Simulate a conversation
    wm.store("What do you think about consciousness?", "consciousness",
             "position", "consciousness", 0.72, "Consciousness involves...", "consciousness", 0.6)
    wm.store("Does that apply to animals?", "Regarding consciousness: Does that apply to animals?",
             "exploration", "consciousness", 0.65, "Animal consciousness...", "consciousness", 0.5)

    print(wm.summary())
    print()

    ctx = wm.get_context("What about plants?")
    print("Context for 'What about plants?':")
    for k, v in ctx.items():
        print(f"  {k}: {v}")

    print()
    print("Reference resolution:")
    print(f"  'Does that apply?' → '{wm.resolve_reference('Does that apply?')}'")
