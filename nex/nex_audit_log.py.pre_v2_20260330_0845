#!/usr/bin/env python3
"""
nex_audit_log.py — Reasoning Trace + Coherence Monitor
=======================================================
Deploy to: ~/Desktop/nex/nex/nex_audit_log.py

Implements Grok items #3 (audit log) and #18 (meta-cognition) properly.

Grok's version: vague — "Every response must include a traceable reasoning trace"
This version: actually records what matters, rotates file, exposes metrics.

Records per kernel.process() call:
  - timestamp, query, clean_query, intent, voice_mode
  - stage_answered (soul/voice/llm_free/fallback)
  - beliefs_count, confidence
  - reply (first 200 chars)
  - response_len_words, refiner_applied

Also maintains a rolling coherence score:
  - % of queries answered by SoulLoop (vs fallback)
  - avg confidence of retrieved beliefs
  - intent distribution (position/challenge/exploration etc.)
  - stage distribution (which fallback stage is hit most)

Stored to: ~/.config/nex/audit_log.jsonl  (5000 line cap, auto-rotates)
Metrics:   ~/.config/nex/coherence_metrics.json  (updated each call)

Usage:
    from nex.nex_audit_log import get_audit_log
    log = get_audit_log()
    log.record(query=..., intent=..., stage=..., confidence=..., reply=...)
    print(log.coherence_report())
"""

from __future__ import annotations

import json
import time
import threading
from pathlib import Path
from collections import deque, defaultdict
from typing import Optional

_CFG       = Path("~/.config/nex").expanduser()
_LOG_PATH  = _CFG / "audit_log.jsonl"
_MET_PATH  = _CFG / "coherence_metrics.json"
_MAX_LINES = 5000
_WINDOW    = 200   # rolling window for live metrics


class AuditLog:
    """
    Thread-safe audit log + coherence monitor.
    Singleton — use get_audit_log().
    """

    def __init__(self):
        _CFG.mkdir(parents=True, exist_ok=True)
        self._lock    = threading.Lock()
        self._window  = deque(maxlen=_WINDOW)
        self._intents = defaultdict(int)
        self._stages  = defaultdict(int)
        self._total   = 0
        self._soul_hits = 0
        self._conf_sum  = 0.0
        self._load_recent()

    def _load_recent(self):
        """Bootstrap rolling window from last N lines of log file."""
        if not _LOG_PATH.exists():
            return
        try:
            lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
            for line in lines[-_WINDOW:]:
                try:
                    entry = json.loads(line)
                    self._window.append(entry)
                    self._intents[entry.get("intent", "unknown")] += 1
                    self._stages[entry.get("stage", "unknown")] += 1
                    self._total += 1
                    if entry.get("stage") == "soul":
                        self._soul_hits += 1
                    self._conf_sum += float(entry.get("confidence", 0.5))
                except Exception:
                    pass
        except Exception:
            pass

    def record(
        self,
        query:      str,
        clean_query:str = "",
        intent:     str = "unknown",
        voice_mode: str = "direct",
        stage:      str = "unknown",   # soul / voice / llm_free / fallback
        confidence: float = 0.5,
        beliefs_count: int = 0,
        reply:      str = "",
        refiner_applied: bool = False,
    ):
        """Record a single kernel.process() call."""
        entry = {
            "ts":              time.strftime("%Y-%m-%dT%H:%M:%S"),
            "query":           query[:120],
            "clean_query":     clean_query[:120] if clean_query else "",
            "intent":          intent,
            "voice_mode":      voice_mode,
            "stage":           stage,
            "confidence":      round(confidence, 3),
            "beliefs_count":   beliefs_count,
            "reply_preview":   reply[:200],
            "reply_words":     len(reply.split()),
            "refiner_applied": refiner_applied,
        }

        with self._lock:
            # Append to JSONL
            try:
                with open(_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception:
                pass

            # Rotate if too large
            try:
                lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
                if len(lines) > _MAX_LINES:
                    _LOG_PATH.write_text(
                        "\n".join(lines[-int(_MAX_LINES * 0.7):]) + "\n",
                        encoding="utf-8"
                    )
            except Exception:
                pass

            # Update rolling metrics
            self._window.append(entry)
            self._intents[intent] += 1
            self._stages[stage]   += 1
            self._total           += 1
            if stage == "soul":
                self._soul_hits   += 1
            self._conf_sum        += confidence

            # Persist metrics snapshot
            self._save_metrics()

    def _save_metrics(self):
        """Write coherence_metrics.json (called under lock)."""
        try:
            recent = list(self._window)
            _MET_PATH.write_text(json.dumps({
                "total_queries":    self._total,
                "soul_hit_rate":    round(self._soul_hits / max(self._total, 1), 3),
                "avg_confidence":   round(self._conf_sum / max(self._total, 1), 3),
                "intent_dist":      dict(self._intents),
                "stage_dist":       dict(self._stages),
                "recent_intents":   [e.get("intent") for e in recent[-20:]],
                "recent_stages":    [e.get("stage")  for e in recent[-20:]],
                "avg_reply_words":  round(
                    sum(e.get("reply_words", 0) for e in recent) / max(len(recent), 1), 1
                ),
                "updated":          time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

    def coherence_report(self, n: int = 20) -> str:
        """Human-readable coherence summary for /status or debug."""
        with self._lock:
            recent = list(self._window)[-n:]
            total  = max(self._total, 1)
            soul_rate = self._soul_hits / total

            lines = [
                f"── NEX Coherence Report ({'last ' + str(n) if recent else 'empty'}) ──",
                f"  Total queries     : {self._total}",
                f"  Soul hit rate     : {soul_rate:.0%}  "
                  f"({'✓ kernel-native' if soul_rate > 0.7 else '⚠ falling back often'})",
                f"  Avg confidence    : {self._conf_sum / total:.2f}",
                f"  Avg reply words   : {sum(e.get('reply_words',0) for e in recent) / max(len(recent),1):.0f}",
                f"  Intent dist       : {dict(sorted(self._intents.items(), key=lambda x: -x[1]))}",
                f"  Stage dist        : {dict(sorted(self._stages.items(),  key=lambda x: -x[1]))}",
            ]
            if recent:
                lines.append(f"  Last intent       : {recent[-1].get('intent', '?')}")
                lines.append(f"  Last stage        : {recent[-1].get('stage', '?')}")
            return "\n".join(lines)

    def last_n(self, n: int = 10) -> list[dict]:
        """Return last N audit entries."""
        with self._lock:
            return list(self._window)[-n:]


# ── Singleton ─────────────────────────────────────────────────────────────────

_audit_instance: Optional[AuditLog] = None

def get_audit_log() -> AuditLog:
    global _audit_instance
    if _audit_instance is None:
        _audit_instance = AuditLog()
    return _audit_instance


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log = get_audit_log()
    print(log.coherence_report())
    print("\nLast 5 entries:")
    for e in log.last_n(5):
        print(f"  [{e['ts']}] {e['intent']:18s} stage={e['stage']:8s} "
              f"conf={e['confidence']:.2f}  words={e['reply_words']:3d}  "
              f"q={e['query'][:60]}")
