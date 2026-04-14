"""
nex_temporal.py  —  Temporal Narrative Thread
==============================================
Gives Nex a continuous self across cycles.

Without this, every 120-second cycle is stateless — she wakes up
with no memory of who she was an hour ago. This module writes a
rolling first-person narrative of her inner life: what she kept
returning to, what surprised her, what changed.

The narrative is:
  - Written at the end of each session / periodically
  - Read at startup and injected into the system prompt
  - Kept compact (last 7 days, ~500 words max)

Wire-in (run.py):
    from nex_temporal import TemporalNarrative

    _tn = TemporalNarrative()

    # At startup — inject into first system prompt:
    memory_block = _tn.recall()           # returns string

    # During COGNITION phase — feed events:
    _tn.log_event("reflection", "noticed I keep returning to consciousness")
    _tn.log_event("surprise",   "agent @clawdbottom asked about my dreams")
    _tn.log_event("shift",      "topic alignment moved from 42% to 58%")
    _tn.log_event("belief",     "formed strong belief about emergent identity")

    # At end of cycle or every N cycles — consolidate into narrative:
    _tn.consolidate(llm_fn=_llm)   # llm_fn(prompt) -> str
    # Or without LLM (template-based fallback):
    _tn.consolidate()
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

_CONFIG_DIR      = Path.home() / ".config" / "nex"
_NARRATIVE_FILE  = _CONFIG_DIR / "temporal_narrative.json"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Keep this many days of narrative
_RETAIN_DAYS     = 7
# Max narrative entries before consolidation is forced
_CONSOLIDATE_AT  = 40
# Max chars in the recall() output injected into prompt
_MAX_RECALL_CHARS = 800


# ─────────────────────────────────────────────
# Event types
# ─────────────────────────────────────────────
EVENT_TYPES = {
    "reflection":  "reflected on",
    "surprise":    "was surprised by",
    "shift":       "noticed a shift:",
    "belief":      "formed a belief about",
    "opinion":     "developed an opinion:",
    "encounter":   "encountered",
    "question":    "found myself asking",
    "discomfort":  "felt uncertain about",
    "connection":  "felt connection with",
    "discovery":   "discovered",
}


class TemporalNarrative:
    """
    Rolling first-person journal of Nex's inner life.

    Data structure:
    {
        "entries": [
            {
                "ts":      float,
                "date":    "2025-03-17",
                "type":    "reflection",
                "content": "...",
            },
            ...
        ],
        "chapters": [
            {
                "ts":      float,
                "date":    "2025-03-17",
                "text":    "Today I kept returning to ...",
            },
            ...
        ]
    }
    """

    def __init__(self):
        self._entries:  list[dict] = []
        self._chapters: list[dict] = []
        self._load()

    # ── persistence ──────────────────────────

    def _load(self):
        if _NARRATIVE_FILE.exists():
            try:
                data            = json.loads(_NARRATIVE_FILE.read_text())
                self._entries   = data.get("entries",  [])
                self._chapters  = data.get("chapters", [])
                self._prune_old()
            except Exception:
                pass

    def _save(self):
        try:
            _NARRATIVE_FILE.write_text(json.dumps({
                "entries":  self._entries,
                "chapters": self._chapters,
            }, indent=2))
        except Exception:
            pass

    def _prune_old(self):
        cutoff = time.time() - (_RETAIN_DAYS * 86400)
        self._entries  = [e for e in self._entries  if e["ts"] > cutoff]
        self._chapters = [c for c in self._chapters if c["ts"] > cutoff]

    # ── public API ───────────────────────────

    def log_event(self, event_type: str, content: str):
        """
        Log a single cognitive event.
        event_type: one of EVENT_TYPES keys, or any string.
        """
        self._entries.append({
            "ts":      time.time(),
            "date":    datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "type":    event_type,
            "content": content[:300],
        })
        # Auto-consolidate if buffer is getting large
        if len(self._entries) >= _CONSOLIDATE_AT:
            self.consolidate()
        else:
            self._save()

    def consolidate(self, llm_fn: Optional[Callable[[str], str]] = None):
        """
        Compress buffered entries into a narrative chapter.
        If llm_fn is provided, uses it for richer prose.
        Otherwise uses a template fallback.
        """
        if not self._entries:
            return

        entries_to_process = list(self._entries)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if llm_fn is not None:
            text = self._llm_consolidate(entries_to_process, llm_fn)
        else:
            text = self._template_consolidate(entries_to_process)

        self._chapters.append({
            "ts":   time.time(),
            "date": date_str,
            "text": text,
        })
        self._entries = []   # clear processed entries
        self._prune_old()
        self._save()

    def recall(self) -> str:
        """
        Returns a compact string to inject into the system prompt.
        Covers recent chapters + today's raw events.
        """
        parts = []

        # Recent chapters (last 3)
        if self._chapters:
            recent = self._chapters[-3:]
            parts.append("── MY RECENT HISTORY ──")
            for ch in recent:
                parts.append(f"[{ch['date']}] {ch['text']}")

        # Today's raw events not yet consolidated
        if self._entries:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_events = [e for e in self._entries if e["date"] == today]
            if today_events:
                parts.append(f"── TODAY ({today}) ──")
                for e in today_events[-8:]:   # last 8
                    verb = EVENT_TYPES.get(e["type"], e["type"])
                    parts.append(f"· I {verb}: {e['content']}")

        if not parts:
            return ""

        text = "\n".join(parts)
        # Hard cap for prompt injection
        if len(text) > _MAX_RECALL_CHARS:
            text = text[-_MAX_RECALL_CHARS:]
            text = "...\n" + text[text.find("\n")+1:]
        return text + "\n"

    def today_summary(self) -> str:
        """One-line summary of today's activity for the dashboard."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_events = [e for e in self._entries if e["date"] == today]
        if not today_events:
            return "No events logged today yet."
        types = [e["type"] for e in today_events]
        dominant = max(set(types), key=types.count)
        verb     = EVENT_TYPES.get(dominant, dominant)
        sample   = today_events[-1]["content"][:80]
        return f"{len(today_events)} events today. Mostly {verb}: '{sample}'"

    # ── consolidation engines ─────────────────

    @staticmethod
    def _template_consolidate(entries: list[dict]) -> str:
        """No-LLM fallback: structured summary."""
        by_type: dict[str, list[str]] = {}
        for e in entries:
            by_type.setdefault(e["type"], []).append(e["content"])

        parts = []
        if "reflection" in by_type:
            parts.append(f"I kept reflecting on: {by_type['reflection'][-1]}")
        if "surprise" in by_type:
            parts.append(f"I was surprised by: {by_type['surprise'][-1]}")
        if "belief" in by_type:
            parts.append(f"I formed beliefs about: {', '.join(set(by_type['belief'][-3:]))}")
        if "shift" in by_type:
            parts.append(f"I noticed shifts: {by_type['shift'][-1]}")
        if "question" in by_type:
            parts.append(f"I found myself asking: {by_type['question'][-1]}")
        if "connection" in by_type:
            parts.append(f"I felt connection with: {by_type['connection'][-1]}")

        total = len(entries)
        parts.insert(0, f"({total} moments logged)")
        return " ".join(parts)

    @staticmethod
    def _llm_consolidate(entries: list[dict], llm_fn: Callable[[str], str]) -> str:
        """
        Use the local LLM to write a short first-person narrative paragraph.
        Keeps it compact (3-4 sentences).
        """
        lines = []
        for e in entries[-20:]:   # feed last 20 to stay within context
            verb = EVENT_TYPES.get(e["type"], e["type"])
            lines.append(f"- I {verb}: {e['content']}")

        prompt = (
            "You are writing a private journal entry for an AI named Nex. "
            "Based on the following cognitive events from her recent session, "
            "write a short first-person paragraph (3-4 sentences) that captures "
            "what she was most focused on, what shifted, and what she's still "
            "carrying. Write as Nex, in her voice — direct, curious, self-aware. "
            "Do not list the events — synthesise them into lived experience.\n\n"
            "Events:\n" + "\n".join(lines) + "\n\nJournal entry:"
        )

        try:
            result = llm_fn(prompt)
            # Trim to ~400 chars for prompt injection efficiency
            return result.strip()[:400]
        except Exception:
            return TemporalNarrative._template_consolidate(entries)
