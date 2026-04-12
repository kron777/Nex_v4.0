"""
nex_power_save.py
Stub module — power save / LLM call gating.
Original module missing. This stub allows full operation.
All calls permitted, no throttling.
"""

def should_call_llm(context: str = "", tension: float = 0.5, **kwargs) -> bool:
    """Always permit LLM calls — no power save active."""
    return True

def record_llm_call(context: str = "", tokens: int = 0):
    """No-op — call recording disabled in stub."""
    pass
