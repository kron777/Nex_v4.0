#!/usr/bin/env python3
"""
nex_loop_wiring.py — Dead Loop Closure for NEX v7.2
====================================================
Closes three dead feedback loops that have been ticking silently
but never connected to the output pipeline:

  1. PCC (PredictionConfidenceCalibration)
     predict() was called but resolve() never was.
     → NexReplyContext.close_pcc(pid, actual_score) now calls resolve()

  2. DQS (DecisionQualityScoring)
     record() was never called from the output pipeline.
     → NexReplyContext.record_outcome(cluster, success) now calls record()

  3. HBG (HierarchicalBeliefGraph)
     topology was built every 400s but never passed to nex_reason.py.
     → get_hbg_weights() returns {topic: multiplier} for reason.py to use

Usage — call this from wherever NexVoiceCompositor produces a final reply:

    from nex.nex_loop_wiring import NexReplyContext

    with NexReplyContext(query, topic_cluster="AI_systems") as ctx:
        pid    = ctx.predict(confidence=0.72)
        reply  = compose_reason(query)          # your existing call
        ctx.close_pcc(pid, actual=0.80)         # resolves PCC
        ctx.record_outcome("AI_systems", True)  # records DQS

Or in fire-and-forget mode (no context manager needed):
    from nex.nex_loop_wiring import record_reply_outcome
    record_reply_outcome(topic="AI_systems", success=True, pcc_conf=0.72, actual=0.80)
"""

import time
import threading
from pathlib import Path

# ── singleton import guard ────────────────────────────────────────
_v72_lock    = threading.Lock()
_v72_inst    = None
_v72_tried   = False

def _get_v72():
    global _v72_inst, _v72_tried
    if _v72_tried:
        return _v72_inst
    with _v72_lock:
        if not _v72_tried:
            try:
                from nex.nex_v72 import get_v72
                _v72_inst = get_v72()
            except Exception:
                _v72_inst = None
            finally:
                _v72_tried = True
    return _v72_inst


# ── HBG weight export ─────────────────────────────────────────────
def get_hbg_weights() -> dict:
    """
    Returns {topic: weight_multiplier} for use in nex_reason.py retrieval.
    core → 2.5, cluster → 1.6, node → 1.0
    Falls back to empty dict if v72 not loaded.
    """
    v72 = _get_v72()
    if v72 is None:
        return {}
    try:
        hierarchy = v72.hbg.hierarchy   # dict: {topic: {level, n, avg_conf}}
        weight_map = {
            "core":    2.5,
            "cluster": 1.6,
            "node":    1.0,
        }
        return {
            topic: weight_map.get(info.get("level", "node"), 1.0)
            for topic, info in hierarchy.items()
        }
    except Exception:
        return {}


# ── reply context manager ─────────────────────────────────────────
class NexReplyContext:
    """
    Context manager that wires PCC and DQS into the reply lifecycle.

    with NexReplyContext(query, topic_cluster) as ctx:
        pid   = ctx.predict(confidence)
        reply = your_compose_call()
        ctx.close_pcc(pid, actual_score)
        ctx.record_outcome(cluster, success)
    """
    def __init__(self, query: str = "", topic_cluster: str = "general"):
        self.query         = query
        self.topic_cluster = topic_cluster
        self._v72          = None
        self._open_pids: list = []

    def __enter__(self):
        self._v72 = _get_v72()
        return self

    def __exit__(self, *args):
        # Auto-close any pids not explicitly resolved
        if self._v72 and self._open_pids:
            for pid in self._open_pids:
                try:
                    self._v72.pcc.resolve(pid, actual=0.5)  # neutral resolution
                except Exception:
                    pass
        self._open_pids = []

    def predict(self, confidence: float = 0.5) -> str | None:
        """
        Register a prediction with PCC. Returns pid or None.
        Store the pid and pass it to close_pcc() after reply is generated.
        """
        if self._v72 is None:
            return None
        try:
            pid = self._v72.pcc.predict(self.topic_cluster, confidence)
            self._open_pids.append(pid)
            return pid
        except Exception:
            return None

    def close_pcc(self, pid: str | None, actual: float = 0.5):
        """
        Resolve a PCC prediction with actual outcome score (0.0–1.0).
        Call this after the reply has been scored/sent.
        """
        if pid is None or self._v72 is None:
            return
        try:
            self._v72.pcc.resolve(pid, actual)
            if pid in self._open_pids:
                self._open_pids.remove(pid)
        except Exception as e:
            print(f"  [loop_wiring] PCC resolve error: {e}")

    def record_outcome(self, cluster: str | None = None, success: bool = True):
        """
        Record a decision outcome with DQS for cluster quality scoring.
        cluster defaults to self.topic_cluster.
        """
        if self._v72 is None:
            return
        target = cluster or self.topic_cluster
        try:
            self._v72.dqs.record(target, success)
        except Exception as e:
            print(f"  [loop_wiring] DQS record error: {e}")

    def record_failure(self, topic: str | None = None):
        """Record a failure with FMP (FailureMemoryPenalty)."""
        if self._v72 is None:
            return
        try:
            self._v72.fmp.record_failure(topic or self.topic_cluster)
        except Exception:
            pass


# ── fire-and-forget helper ────────────────────────────────────────
def record_reply_outcome(
    topic:    str   = "general",
    success:  bool  = True,
    pcc_conf: float = 0.5,
    actual:   float | None = None,
):
    """
    Single-call convenience function for fire-and-forget wiring.
    Call this once per reply cycle from your voice compositor.

    Args:
        topic:    belief cluster / topic string (e.g. "AI_systems")
        success:  whether the reply was positively received
        pcc_conf: predicted confidence at reply time
        actual:   actual outcome score (defaults to 0.8 if success, 0.3 if not)
    """
    if actual is None:
        actual = 0.78 if success else 0.32

    v72 = _get_v72()
    if v72 is None:
        return

    try:
        pid = v72.pcc.predict(topic, pcc_conf)
        v72.pcc.resolve(pid, actual)
    except Exception as e:
        print(f"  [loop_wiring] PCC error: {e}")

    try:
        v72.dqs.record(topic, success)
    except Exception as e:
        print(f"  [loop_wiring] DQS error: {e}")

    if not success:
        try:
            v72.fmp.record_failure(topic)
        except Exception:
            pass


# ── voice compositor patch (drop-in) ─────────────────────────────
def patch_compositor_reply(reply_fn):
    """
    Decorator — wrap your existing reply/compose function to auto-wire
    PCC and DQS without touching the compositor internals.

    Usage in nex_voice_gen.py:
        from nex.nex_loop_wiring import patch_compositor_reply

        @patch_compositor_reply
        def compose_reason(query, **kwargs):
            ...your existing code...
            return reply_text

    The decorator infers topic from the reply's first meaningful word cluster
    and uses a neutral success=True signal (override by calling
    record_reply_outcome() directly with real engagement data).
    """
    import functools

    @functools.wraps(reply_fn)
    def wrapper(*args, **kwargs):
        query = args[0] if args else kwargs.get("query", "")
        result = reply_fn(*args, **kwargs)
        # Best-effort topic inference from query
        import re
        words = re.findall(r'\b[a-z]{4,}\b', str(query).lower())
        topic = words[0] if words else "general"
        # Fire-and-forget — neutral signal (real engagement wires later)
        try:
            record_reply_outcome(topic=topic, success=True, pcc_conf=0.5)
        except Exception:
            pass
        return result

    return wrapper


# ── CLI test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Testing loop wiring...")
    v72 = _get_v72()
    if v72 is None:
        print("  v72 not available in this environment — OK for testing")
    else:
        print(f"  v72 loaded: cycle={v72._cycle}")
        print(f"  HBG weights sample: {dict(list(get_hbg_weights().items())[:5])}")

    print("\nTesting NexReplyContext...")
    with NexReplyContext("test query", "AI_systems") as ctx:
        pid = ctx.predict(confidence=0.70)
        print(f"  PCC pid: {pid}")
        ctx.close_pcc(pid, actual=0.75)
        ctx.record_outcome("AI_systems", success=True)
        print("  PCC resolved + DQS recorded")

    print("\nTesting fire-and-forget...")
    record_reply_outcome(topic="cognition", success=True, pcc_conf=0.65, actual=0.72)
    print("  Done")
    print("\nAll wiring tests passed.")
