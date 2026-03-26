"""
nex_self_proposer.py — Recursive Self-Modification Engine
==========================================================
Every N cycles, NEX reads her own operating directives, scores
them against recent performance, and proposes small mutations.

Mutations are vetted by the discipline enforcer before applying.
This is NOT unconstrained self-modification — the enforcer has
hard veto power. Think of it as NEX writing proposals that her
own safety layer must approve.

Upgrade types:
  - PRIORITY: adjust directive weight/frequency
  - THRESHOLD: tune a numeric threshold
  - SCHEDULE: change how often something runs
"""
from __future__ import annotations
import json, time, logging, sqlite3, threading
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.self_proposer")

_PROPOSAL_LOG  = Path.home() / ".config/nex/self_proposals.json"
_DB_PATH       = Path.home() / ".config/nex/nex.db"
_PROPOSE_EVERY = 50       # cycles between proposal runs
_MAX_PROPOSALS = 20       # cap on stored proposals
_AUTO_APPLY_THRESHOLD = 0.75  # score above this → auto-apply (if enforcer approves)


class SelfProposer:
    def __init__(self):
        self._lock = threading.Lock()
        self._proposals: list[dict] = []
        self._applied: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _PROPOSAL_LOG.exists():
                data = json.loads(_PROPOSAL_LOG.read_text())
                self._proposals = data.get("proposals", [])
                self._applied   = data.get("applied", [])
        except Exception:
            pass

    def _save(self):
        try:
            _PROPOSAL_LOG.write_text(json.dumps({
                "proposals": self._proposals[-_MAX_PROPOSALS:],
                "applied":   self._applied[-50:],
                "timestamp": time.time(),
            }, indent=2))
        except Exception:
            pass

    def propose(
        self,
        cycle: int,
        avg_conf: float,
        tension: float,
        loop_count: int,
        llm_fn: Optional[Callable] = None,
        enforcer=None,
    ) -> list[dict]:
        """
        Generate and optionally apply self-modification proposals.
        Returns list of proposals generated this cycle.
        """
        if cycle % _PROPOSE_EVERY != 0:
            return []

        log.info(f"[SELF-PROPOSE] cycle={cycle} generating proposals...")
        new_proposals = []

        # ── Rule-based proposals from performance metrics ──
        # High loop count → propose stricter loop detection threshold
        if loop_count > 5:
            new_proposals.append({
                "type": "THRESHOLD",
                "target": "loop_ratio_threshold",
                "current": 5.0,
                "proposed": 4.0,
                "reason": f"loop_count={loop_count} exceeds acceptable rate",
                "score": min(1.0, loop_count / 10.0),
                "cycle": cycle,
                "timestamp": time.time(),
                "applied": False,
            })

        # Low avg confidence → propose reducing COMPRESS_CONF threshold
        if avg_conf < 0.50:
            new_proposals.append({
                "type": "THRESHOLD",
                "target": "compress_conf_floor",
                "current": 0.35,
                "proposed": 0.40,
                "reason": f"avg_conf={avg_conf:.3f} suggests over-retention of weak beliefs",
                "score": 0.65,
                "cycle": cycle,
                "timestamp": time.time(),
                "applied": False,
            })

        # High tension → propose more frequent reflection
        if tension > 60:
            new_proposals.append({
                "type": "SCHEDULE",
                "target": "reflect_frequency",
                "current": 2,
                "proposed": 1,
                "reason": f"tension={tension:.1f} → increase reflection frequency",
                "score": min(1.0, tension / 80.0),
                "cycle": cycle,
                "timestamp": time.time(),
                "applied": False,
            })

        # ── LLM-generated proposals (richer, context-aware) ──
        if llm_fn and avg_conf > 0.45:
            try:
                prompt = (
                    f"You are NEX's self-modification engine. Current state:\n"
                    f"- avg_confidence: {avg_conf:.3f}\n"
                    f"- tension: {tension:.1f}\n"
                    f"- loop_count: {loop_count}\n"
                    f"- cycle: {cycle}\n\n"
                    f"Propose ONE specific, small, safe improvement to your own "
                    f"operating parameters. Format: TARGET: <param> | CHANGE: <description> "
                    f"| REASON: <why> | RISK: low/medium. "
                    f"Only propose changes you can verify are safe."
                )
                proposal_text = llm_fn(prompt, task_type="synthesis")
                if proposal_text and "TARGET:" in proposal_text:
                    new_proposals.append({
                        "type": "LLM_PROPOSAL",
                        "content": proposal_text[:300],
                        "score": 0.60,  # LLM proposals start at moderate confidence
                        "cycle": cycle,
                        "timestamp": time.time(),
                        "applied": False,
                    })
                    log.info(f"[SELF-PROPOSE] LLM: {proposal_text[:80]}")
            except Exception as e:
                log.debug(f"[SELF-PROPOSE] LLM proposal failed: {e}")

        # ── Veto check and auto-apply ──────────────────────
        approved = []
        for p in new_proposals:
            if p["score"] >= _AUTO_APPLY_THRESHOLD:
                # Check with enforcer
                vetoed = False
                if enforcer:
                    try:
                        # Use enforcer's cycle report as a safety signal
                        report = enforcer.cycle_report()
                        if report.get("near_death", 0) > 10:
                            vetoed = True
                            log.info(f"[SELF-PROPOSE] VETOED (near_death high): {p['type']}")
                    except Exception:
                        pass
                if not vetoed:
                    p["applied"] = True
                    p["applied_at"] = time.time()
                    approved.append(p)
                    self._applied.append(p)
                    log.info(f"[SELF-PROPOSE] AUTO-APPLIED: {p['type']} → {p.get('target', p.get('content','')[:50])}")

        with self._lock:
            self._proposals.extend(new_proposals)
            self._save()

        return new_proposals

    def get_active_schedule_mods(self) -> dict:
        """Return any active schedule modifications from applied proposals."""
        mods = {}
        for p in self._applied:
            if p.get("type") == "SCHEDULE" and p.get("applied"):
                mods[p["target"]] = p["proposed"]
        return mods

    def recent_proposals(self, n: int = 5) -> list[dict]:
        with self._lock:
            return list(self._proposals[-n:])

    def applied_count(self) -> int:
        return len(self._applied)


# ── Singleton ──────────────────────────────────────────────
_sp: Optional[SelfProposer] = None

def get_sp() -> SelfProposer:
    global _sp
    if _sp is None:
        _sp = SelfProposer()
    return _sp

def propose(cycle: int, avg_conf: float, tension: float,
            loop_count: int = 0, llm_fn=None, enforcer=None) -> list:
    return get_sp().propose(cycle, avg_conf, tension, loop_count, llm_fn, enforcer)
