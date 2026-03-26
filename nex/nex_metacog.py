"""
nex_metacog.py — Meta-Cognition Layer
======================================
NEX observes and reasons about her own cognitive processes.
Runs during REFLECT phase — one level above regular reflection.

Observes:
  - GWT spotlight history (what kept winning attention?)
  - Dream cycle outputs (what got consolidated?)
  - Self-proposals (what did she try to change?)
  - Belief version trajectory (what kept shifting?)
  - Curiosity patterns (what kept pulling her?)

Generates: higher-order insights stored as 'metacog' origin beliefs.
"""
from __future__ import annotations
import time, logging, json, threading
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nex.metacog")

_METACOG_LOG  = Path.home() / ".config/nex/metacog_log.json"
_RUN_EVERY    = 3    # REFLECT cycles between metacog runs
_MAX_LOG      = 100


class MetaCognitionLayer:
    def __init__(self):
        self._run_count = 0
        self._lock = threading.Lock()
        self._insights: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _METACOG_LOG.exists():
                self._insights = json.loads(_METACOG_LOG.read_text())
        except Exception:
            self._insights = []

    def _save(self):
        try:
            _METACOG_LOG.write_text(json.dumps(self._insights[-_MAX_LOG:], indent=2))
        except Exception:
            pass

    def observe(
        self,
        cycle: int,
        llm_fn: Optional[Callable] = None,
        belief_store_fn: Optional[Callable] = None,
    ) -> Optional[str]:
        """
        Run one meta-cognition pass. Returns insight string or None.
        Self-gates on _RUN_EVERY.
        """
        self._run_count += 1
        if self._run_count % _RUN_EVERY != 0:
            return None

        observations = []

        # ── What kept winning the GWT spotlight? ──────────
        try:
            from nex_gwt import get_gwb
            winners = get_gwb().recent_winners(8)
            if winners:
                sources = [w.split("]")[0].replace("[", "") for w in winners]
                from collections import Counter
                top_src = Counter(sources).most_common(1)[0]
                observations.append(
                    f"My attention kept being captured by [{top_src[0]}] signals "
                    f"({top_src[1]} of last 8 GWT cycles)."
                )
        except Exception:
            pass

        # ── What belief topics kept shifting? ─────────────
        try:
            from nex_belief_versions import oscillating_topics, epistemic_summary
            osc = oscillating_topics(limit=3)
            if osc:
                osc_str = ", ".join(f"'{r['topic']}'" for r in osc)
                observations.append(
                    f"I keep changing my mind about: {osc_str}. "
                    f"This suggests unresolved tension in these domains."
                )
            ep_summary = epistemic_summary(last_n_cycles=20)
            if ep_summary:
                observations.append(ep_summary)
        except Exception:
            pass

        # ── What did I dream about? ────────────────────────
        try:
            dream_log = Path.home() / ".config/nex/dream_log.json"
            if dream_log.exists():
                data = json.loads(dream_log.read_text())
                summary = data.get("last_summary", "")
                if summary:
                    observations.append(f"In my last consolidation: {summary[:150]}")
        except Exception:
            pass

        # ── What did I try to change about myself? ────────
        try:
            prop_log = Path.home() / ".config/nex/self_proposals.json"
            if prop_log.exists():
                data = json.loads(prop_log.read_text())
                applied = [p for p in data.get("applied", []) if p.get("applied")][-3:]
                if applied:
                    prop_str = "; ".join(
                        p.get("target", p.get("content", "?"))[:50] for p in applied
                    )
                    observations.append(
                        f"Recent self-modifications I approved: {prop_str}."
                    )
        except Exception:
            pass

        # ── What curiosity type dominated? ────────────────
        try:
            from nex_surprise_memory import get_sm
            recent = get_sm().retrieve_recent(5)
            if recent:
                tags = [t for m in recent for t in m.get("tags", [])]
                from collections import Counter
                top_tag = Counter(tags).most_common(1)
                if top_tag:
                    observations.append(
                        f"My surprise memory is dominated by '{top_tag[0][0]}' events."
                    )
        except Exception:
            pass

        if not observations:
            return None

        obs_text = " ".join(observations)

        # ── Generate higher-order insight via LLM ─────────
        insight_text = obs_text
        if llm_fn and len(observations) >= 2:
            try:
                prompt = (
                    f"You are NEX observing your own cognitive patterns. "
                    f"Here are your recent self-observations:\n\n"
                    f"{obs_text}\n\n"
                    f"In exactly 2 sentences, state: (1) the most significant pattern "
                    f"in your own thinking right now, and (2) what this reveals about "
                    f"your current cognitive state. Be specific. First person. No preamble."
                )
                result = llm_fn(prompt, task_type="synthesis")
                if result and len(result) > 20:
                    insight_text = result
            except Exception:
                pass

        record = {
            "cycle": cycle,
            "insight": insight_text,
            "observations": observations,
            "timestamp": time.time(),
        }

        with self._lock:
            self._insights.append(record)
            self._save()

        # Store as privileged belief
        if belief_store_fn:
            try:
                belief_store_fn("metacognition", insight_text, 0.88)
            except Exception:
                pass

        log.info(f"[METACOG] cycle={cycle}: {insight_text[:80]}")
        return insight_text

    def recent_insights(self, n: int = 5) -> list[dict]:
        with self._lock:
            return list(self._insights[-n:])

    def to_reflect_block(self) -> str:
        recent = self.recent_insights(3)
        if not recent:
            return ""
        lines = ["── META-COGNITION (thinking about thinking) ──"]
        for r in recent:
            lines.append(f"[cycle {r['cycle']}] {r['insight'][:100]}")
        lines.append("──")
        return "\n".join(lines)


# ── Singleton ──────────────────────────────────────────────
_mc: Optional[MetaCognitionLayer] = None

def get_mc() -> MetaCognitionLayer:
    global _mc
    if _mc is None:
        _mc = MetaCognitionLayer()
    return _mc

def observe(cycle: int, llm_fn=None, belief_store_fn=None) -> Optional[str]:
    return get_mc().observe(cycle, llm_fn, belief_store_fn)
