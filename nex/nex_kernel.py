#!/usr/bin/env python3
"""
nex_kernel.py — NEX v4.0 Kernel  (replaces CharacterEngine wrapper)
====================================================================
Zero LLM calls for interactive chat.
SoulLoop is the primary cognition engine (orient→consult→reason→intend→express).
VoiceWrapper is the fallback (belief DB + opinion retrieval).
ask_llm_free is the last symbolic resort.
Mistral HTTP is never touched by this file.

Singleton: get_kernel() — safe to call from anywhere.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# ── Robust path resolution ─────────────────────────────────────────────────
_THIS_FILE = Path(__file__).resolve()
for _p in [_THIS_FILE.parent, _THIS_FILE.parent.parent]:
    if (_p / 'nex').is_dir() or (_p / 'run.py').exists():
        if str(_p) not in sys.path: sys.path.insert(0, str(_p))
        if str(_p / 'nex') not in sys.path: sys.path.insert(0, str(_p / 'nex'))
        break
# ────────────────────────────────────────────────────────────────────────────
_kernel_instance: "NexKernel | None" = None


# --- Evolution imports (repair patch) ---
try:
    from nex.nex_belief_index import build_index as _bi_build, query as _bi_query
    from nex.nex_evo_daemon import start_evo_daemon
    from nex.nex_temporal_pressure import start_pressure_daemon, reinforce_beliefs
    from nex.nex_bridge_engine import BridgeEngine
    from nex.nex_monument import export_monument
    _EVO_LOADED = True
except Exception as _evo_err:
    _EVO_LOADED = False
    print(f'  [EVO] import warning: {_evo_err}')
# -----------------------------------------

class NexKernel:
    """
    The cognitive nucleus.  Replaces the old NexBrain(CharacterEngine) wrapper.

    Routing order — all symbolic, zero HTTP:
        1. SoulLoop         — 5-pass cognition over live DB state
        2. VoiceWrapper     — belief retrieval + opinion lookup
        3. ask_llm_free     — deterministic primitives (reflection, synthesis)
    """

    def __init__(self):
        print("  [KERNEL] Booting NEX v4.0 kernel...")
        self._soul    = None   # SoulLoop singleton, lazy-loaded
        self._voice   = None   # generate_reply fn, lazy-loaded
        self._cycle   = 0
        self._boot_ts = time.time()
        print("  [KERNEL] Ready — SoulLoop loads on first query (lazy init)")

    # ── lazy loaders ──────────────────────────────────────────────────────────

    def _get_soul(self):
        if self._soul is None:
            try:
                from nex.nex_soul_loop import SoulLoop
                self._soul = SoulLoop()
                print("  [KERNEL] SoulLoop online")
            except Exception as exc:
                print(f"  [KERNEL] SoulLoop failed: {exc}")
        return self._soul

    def _get_voice(self):
        if self._voice is None:
            try:
                from nex.nex_voice_wrapper import generate_reply
                self._voice = generate_reply
            except Exception as exc:
                print(f"  [KERNEL] VoiceWrapper failed: {exc}")
        return self._voice

    # ── internal ─────────────────────────────────────────────────────────────

    @staticmethod
    def _strip_belief_ctx(query: str) -> str:
        """
        run.py injects a [Nex internal state …] prefix into full_msg before
        passing it to the LLM.  SoulLoop doesn't need it — strip it out so the
        5-pass orient stage sees only the human's actual words.
        """
        if "[Nex internal state" not in query:
            return query
        parts = query.split("\n\n")
        # The human query is always the last section
        return parts[-1].strip() if len(parts) > 1 else query

    # ── public API ────────────────────────────────────────────────────────────

    def process(self, query: str) -> str:
        """
        Single entry point for every interactive chat message.
        Never touches llama-server or any external HTTP endpoint.
        """
        self._cycle += 1
        clean = self._strip_belief_ctx(query)

        # ── Stage 1: SoulLoop (orient→consult→reason→intend→express) ──────
        soul = self._get_soul()
        if soul:
            try:
                reply = soul.respond(clean)
                if reply and len(reply.split()) >= 6:
                    return reply.strip()
            except Exception as exc:
                print(f"  [KERNEL] SoulLoop error: {exc}")

        # ── Stage 2: VoiceWrapper (belief DB + opinions) ──────────────────
        voice = self._get_voice()
        if voice:
            try:
                reply = voice(clean)
                if reply and len(reply.split()) >= 4:
                    return reply.strip()
            except Exception as exc:
                print(f"  [KERNEL] VoiceWrapper error: {exc}")

        # ── Stage 3: ask_llm_free (deterministic primitives) ──────────────
        try:
            from nex.nex_llm_free import ask_llm_free
            reply = ask_llm_free(clean)
            if reply:
                return reply.strip()
        except Exception:
            pass

        return "Still forming a view on that."

    def debug(self, query: str) -> dict:
        """Run SoulLoop debug pipeline and return all intermediate results."""
        soul = self._get_soul()
        if soul and hasattr(soul, "debug"):
            return soul.debug(query)
        return {"query": query, "reply": self.process(query)}

    def status(self) -> dict:
        return {
            "uptime_minutes": round((time.time() - self._boot_ts) / 60, 1),
            "cycle":          self._cycle,
            "llm_calls":      0,
            "soul_online":    self._soul is not None,
            "voice_online":   self._voice is not None,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

def get_kernel() -> NexKernel:
    global _kernel_instance
    if _kernel_instance is None:
        _kernel_instance = NexKernel()
    return _kernel_instance


# ── CLI quick-test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys as _sys
    k = get_kernel()
    query = " ".join(_sys.argv[1:]) if len(_sys.argv) > 1 else "What do you think about consciousness?"
    print(f"\nQuery  : {query}")
    print(f"Reply  : {k.process(query)}")
    print(f"Status : {k.status()}")
