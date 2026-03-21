"""
RUN.PY INTEGRATION PATCH
========================
Add these blocks to your existing ~/Desktop/nex/run.py

STEP 1 — after existing imports, add:
─────────────────────────────────────
"""

# ── paste after existing imports ──────────────────────────────────────────────
import sys
from pathlib import Path

# add nex_upgrades dir to path
_upgrades_dir = Path(__file__).parent.parent / "nex_upgrades"
if _upgrades_dir.exists() and str(_upgrades_dir) not in sys.path:
    sys.path.insert(0, str(_upgrades_dir))

try:
    from nex_upgrades_v2 import init_v2_upgrades, get_v2
    _V2_AVAILABLE = True
except ImportError as e:
    import logging
    logging.getLogger("nex.run").warning(f"V2 upgrades not available: {e}")
    _V2_AVAILABLE = False


"""
STEP 2 — in your startup / init section, after U1-U12 init and _tg_send is defined:
──────────────────────────────────────────────────────────────────────────────────
"""

# ── paste in startup, after _tg_send is available ─────────────────────────────
if _V2_AVAILABLE:
    _v2 = init_v2_upgrades(
        db_path      = Path.home() / ".config" / "nex" / "nex.db",
        belief_store = None,          # replace with your belief module if available
        llm_complete = None,          # replace with brain.complete or similar
        notify_fn    = _tg_send,
    )
else:
    _v2 = None


"""
STEP 3 — in your main cycle loop, at the end of each cycle:
────────────────────────────────────────────────────────────
"""

# ── paste at END of each cycle iteration ──────────────────────────────────────
if _v2 is not None:
    _v2.tick(
        cycle    = cycle_count,       # replace with your cycle variable
        avg_conf = avg_conf,          # replace with your avg_conf variable
        raw_input= current_event,     # replace with current input dict
    )


"""
STEP 4 — in SIGTERM / shutdown handler:
────────────────────────────────────────
"""

# ── paste in shutdown / SIGTERM handler ───────────────────────────────────────
if _v2 is not None:
    _v2.shutdown()


"""
STEP 5 — Telegram command routing (in your message handler):
─────────────────────────────────────────────────────────────
"""

# ── paste in Telegram message handler ─────────────────────────────────────────
def handle_telegram_message(text: str) -> str:
    # ... your existing command routing ...

    # V2 commands — add this block
    if text.startswith("/v2") and _v2 is not None:
        parts = text.split(None, 1)
        cmd   = parts[0]
        args  = parts[1] if len(parts) > 1 else ""
        return _v2.handle_command(cmd, args)

    # ... rest of your handlers ...


"""
STEP 6 — Outcome signal wiring (fixes D14 loop detection):
─────────────────────────────────────────────────────────────
When a platform sends an engagement signal (reply, like, follow, etc.)
call this to feed the learning system and increment outcome_count:
"""

# ── call when platform engagement received ────────────────────────────────────
def on_platform_engagement(
    signal_type:  str,    # "reply" / "like" / "repost" / "follow"
    platform:     str,
    belief_ids:   list,   # IDs of beliefs used in the triggering response
    positive:     bool  = True,
    value:        float = 1.0,
):
    if _v2 and _v2.learning:
        _v2.learning.record_outcome(
            signal_type=signal_type,
            platform=platform,
            belief_ids=belief_ids,
            value=value,
            positive=positive,
        )
        # outcome_count is now incremented — D14 will see it


"""
AVAILABLE V2 TELEGRAM COMMANDS:
  /v2status   — full system status (beliefs, memory, drives, learning, etc.)
  /v2debug    — run self-debugger on active failures
  /v2sim <X>  — simulate hypothesis X, get predicted outcome + risk
  /v2explain <N> — explain decision trace for cycle N
  /v2goals    — list active goals + intentions
  /v2drives   — drive state with bar chart
  /v2economy  — belief economy budget status
"""
