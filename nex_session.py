"""
nex_session.py — Session state persistence for NEX
Saves/loads cycle count, IQ scores, peak metrics, and session stats
so each boot resumes where the last session ended.
"""
import json, os, time
from pathlib import Path

SESSION_PATH = Path.home() / ".config/nex/session_state_v2.json"

DEFAULTS = {
    "cycle":           0,
    "total_cycles":    0,
    "session_count":   0,
    "peak_iq":         0.0,
    "peak_beliefs":    0,
    "peak_insights":   0,
    "last_iq":         0.0,
    "last_beliefs":    0,
    "last_insights":   0,
    "last_shutdown":   None,
    "last_boot":       None,
    "uptime_total":    0,
    "boot_ts":         None,
}

_state = None

def load() -> dict:
    global _state
    try:
        if SESSION_PATH.exists():
            data = json.loads(SESSION_PATH.read_text())
            _state = {**DEFAULTS, **data}
        else:
            _state = dict(DEFAULTS)
    except Exception:
        _state = dict(DEFAULTS)
    _state["boot_ts"]     = time.time()
    _state["last_boot"]   = time.strftime("%Y-%m-%d %H:%M:%S")
    _state["session_count"] = _state.get("session_count", 0) + 1
    return _state

def save(cycle=None, iq=None, beliefs=None, insights=None):
    global _state
    if _state is None:
        _state = dict(DEFAULTS)
    now = time.time()
    if cycle is not None:
        _state["cycle"]        = cycle
        _state["total_cycles"] = _state.get("total_cycles", 0) + cycle
    if iq is not None:
        _state["last_iq"]  = round(iq, 4)
        _state["peak_iq"]  = max(_state.get("peak_iq", 0), iq)
    if beliefs is not None:
        _state["last_beliefs"] = beliefs
        _state["peak_beliefs"] = max(_state.get("peak_beliefs", 0), beliefs)
    if insights is not None:
        _state["last_insights"] = insights
        _state["peak_insights"] = max(_state.get("peak_insights", 0), insights)
    boot_ts = _state.get("boot_ts") or now
    _state["uptime_total"] = _state.get("uptime_total", 0) + int(now - boot_ts)
    _state["last_shutdown"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_PATH.write_text(json.dumps(_state, indent=2))
    except Exception as e:
        print(f"  [session] save error: {e}")

def get(key, default=None):
    if _state is None:
        load()
    return _state.get(key, default)

def resume_cycle() -> int:
    """Return cycle to resume from — 0 if first boot."""
    if _state is None:
        load()
    return _state.get("cycle", 0)

def summary() -> str:
    if _state is None:
        load()
    return (
        f"Session #{_state.get('session_count',1)} | "
        f"Total cycles: {_state.get('total_cycles',0)} | "
        f"Peak IQ: {_state.get('peak_iq',0):.1%} | "
        f"Peak beliefs: {_state.get('peak_beliefs',0)} | "
        f"Last shutdown: {_state.get('last_shutdown','never')}"
    )
