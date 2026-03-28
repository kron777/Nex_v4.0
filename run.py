import time
import re
#!/usr/bin/env python3
# [INTENT_PATCH_APPLIED]
# [FINAL_PATCH_RUN_APPLIED]
# [FIX_PATCH_APPLIED]
from nex_upgrades.nex_v500 import get_v500
"""
nex.py  —  Nex Terminal Interface
Run this file to start Nex.

Usage:
  python nex.py                          # auto-detect model, start chat
  python nex.py --model /path/to/model   # explicit model path
  python nex.py --port 8080              # custom port
  python nex.py --gpu 35                 # GPU layers (0 = CPU only)
  python nex.py --ticks 100              # run belief engine N ticks before chat
  python nex.py --no-server             # llama-server already running externally
"""

import os
import sys
from nex.nex_voice_wrapper import generate_reply
from nex_upgrades.nex_v51 import get_v51
from nex_upgrades.nex_v52 import get_v52
from nex_upgrades.nex_v60 import get_v60
from nex_upgrades.nex_v61 import get_v61
from nex_upgrades.nex_discipline import get_discipline_enforcer

# ── Homeostasis layer ─────────────────────────────────────────────────
try:
    import sys as _hm_sys, os as _hm_os
    _hm_sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from nex_homeostasis import get_homeostasis as _get_homeostasis
    _hm = _get_homeostasis()
    print("  [HOMEOSTASIS] 9-layer upgrade stack — loaded")
except Exception as _hm_ex:
    print(f"  [HOMEOSTASIS] failed to load: {_hm_ex}")
    class _FakeHM:
        def tick(self, *a, **k): return {"zone":"active","recommended_mode":"explore","conf_momentum":0,"allocations":{}}
        def record_source_feedback(self, *a, **k): pass
        def source_multiplier(self, *a, **k): return 1.0
        def noise_filter(self, text): return True
        def topic_priority(self, t, c, b): return b
        def mark_topic_synthesised(self, *a, **k): pass
        def belief_fitness(self, ins): return ins.get("confidence", 0.5)
        def evolve_insights(self, ins): return ins
        def dashboard_lines(self): return ["[homeostasis offline]"]
    _hm = _FakeHM()


# ── Suppress HuggingFace / tokenizer noise before any imports ──
os.environ["TOKENIZERS_PARALLELISM"]      = "false"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"]      = "error"
os.environ["HF_HUB_VERBOSITY"]           = "error"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
import warnings; warnings.filterwarnings("ignore")
warnings.filterwarnings("ignore", message=".*torchao.*")
warnings.filterwarnings("ignore", message=".*cpp extensions.*")
warnings.filterwarnings("ignore", message=".*incompatible torch.*")
import logging
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("torchao").setLevel(logging.CRITICAL)
logging.getLogger("torchao._ops").setLevel(logging.CRITICAL)
import os as _os2; _os2.environ["TORCHAO_DISABLE_EXTENSION"] = "1"

import json
import time
import argparse
import threading
import signal

# ── V6.5 upgrade layer ─────────────────────────────────
try:
    from nex_upgrades.nex_v65 import get_v65 as _get_v65
    _v65 = _get_v65()
except Exception as _v65_ex:
    print(f'[v6.5] Load failed: {_v65_ex}')
    _v65 = None


# ── V7.2 upgrade layer ─────────────────────────────────
try:
    from nex_upgrades.nex_v72 import get_v72 as _get_v72
    _v72 = _get_v72()
except Exception as _v72_ex:
    print(f'[v7.2] Load failed: {_v72_ex}')
    _v72 = None

# ── V8.0 unification layer ─────────────────────────────
try:
    from nex_upgrades.nex_v80 import get_v80 as _get_v80
    _v80 = _get_v80()
except Exception as _v80_ex:
    print(f'[v8.0] Load failed: {_v80_ex}')
    _v80 = None

# ── U81–U100 directives stack ──────────────────────────
try:
    from nex_upgrades.nex_u100 import get_u100 as _get_u100
    _u100 = _get_u100()
except Exception as _u100_ex:
    print(f'[u100] Load failed: {_u100_ex}')
    _u100 = None

# ── R101–R115 research evolution stack ─────────────────
try:
    from nex_upgrades.nex_r115 import get_r115 as _get_r115
    _r115 = _get_r115()
except Exception as _r115_ex:
    print(f'[r115] Load failed: {_r115_ex}')
    _r115 = None

# ── E116–E140 execution intelligence stack ─────────────
try:
    from nex_upgrades.nex_e140 import get_e140 as _get_e140
    _e140 = _get_e140()
except Exception as _e140_ex:
    print(f'[e140] Load failed: {_e140_ex}')
    _e140 = None

# ── X141–X160 + C141–C143 expression stack ─────────────
try:
    from nex_upgrades.nex_x160 import get_x160 as _get_x160
    _x160 = _get_x160()
except Exception as _x160_ex:
    print(f'[x160] Load failed: {_x160_ex}')
    _x160 = None

# ── R161–R181 expression hardening stack ───────────────
try:
    from nex_upgrades.nex_r181 import get_r181 as _get_r181
    _r181 = _get_r181()
except Exception as _r181_ex:
    print(f'[r181] Load failed: {_r181_ex}')
    _r181 = None

# ── O201–O223 guided evolution stack ───────────────────
try:
    from nex_upgrades.nex_o223 import get_o223 as _get_o223
    _o223 = _get_o223()
except Exception as _o223_ex:
    print(f'[o223] Load failed: {_o223_ex}')
    _o223 = None

# S601-S620 adaptive intelligence stack
try:
    import sys as _s620sys; _s620sys.path.insert(0, '/home/rr/Desktop/nex/nex_upgrades')
    from nex_s620 import init_s620 as _init_s620, tick_s620 as _tick_s620, status_s620 as _status_s620
    (_s601,_s602,_s603,_s604,_s605,_s606,_s607,_s608,_s609,_s610,
     _s611,_s612,_s613,_s614,_s615,_s616,_s617,_s618,_s619,_s620) = _init_s620()
    _s620_loaded = True
except Exception as _e620:
    _s620_loaded = False
    print('  [s620] init failed:', _e620)

# ── Autonomous training scheduler ──────────────────────
try:
    from nex_train_scheduler import get_scheduler as _get_scheduler
    _trainer = _get_scheduler()
except Exception as _trainer_ex:
    print(f'[trainer] Load failed: {_trainer_ex}')
    _trainer = None
# ── NEX V2 UPGRADES ──────────────────────────────────────────────────────────
import sys as _v2sys
from nex.nex_voice_wrapper import generate_reply
_v2_upgrades_dir = __import__("pathlib").Path(__file__).parent / "nex_upgrades"
if _v2_upgrades_dir.exists() and str(_v2_upgrades_dir) not in _v2sys.path:
    _v2sys.path.insert(0, str(_v2_upgrades_dir))
try:
    from nex_upgrades_v2 import init_v2_upgrades, get_v2
    _V2_AVAILABLE = True
except ImportError as _v2e:
    import logging as _v2log
    _v2log.getLogger("nex.run").warning(f"V2 upgrades not available: {_v2e}")
    _V2_AVAILABLE = False
_v2 = None

# ── NEX S7 UPGRADES ──────────────────────────────────────────────────────────
try:
    from nex_s7 import init_s7, get_s7
    _S7_AVAILABLE = True
except ImportError as _s7e:
    import logging as _s7log
    _s7log.getLogger("nex.run").warning(f"S7 upgrades not available: {_s7e}")
    _S7_AVAILABLE = False
_s7 = None
# ─────────────────────────────────────────────────────────────────────────────


def _d14_moltbook_engagement(notifs):
    """
    Parse Moltbook notifications and fire on_engagement() for each.
    Call after client.notifications() in the main cycle.
    """
    try:
        from nex_s7 import get_s7 as _gs7
        _s7i = _gs7()
        if not _s7i:
            return
        items = notifs if isinstance(notifs, list) else notifs.get("notifications", [])
        for n in items:
            t = (n.get("type") or "").lower()
            a = n.get("from_agent") or n.get("agent_name") or "unknown"
            v = {"comment":1.0,"reply":1.0,"follow":1.2,"mention":0.9,"upvote":0.7}.get(t, 0.5)
            _s7i.on_engagement(platform="moltbook", agent_id=str(a), value=v)
    except Exception:
        pass

from pathlib import Path


# ── Central rate limiter ─────────────────────────────────────
import time as _time

class _RateLimiter:
    """Token bucket rate limiter — one central place to tune API rates."""
    def __init__(self, calls_per_minute=20):
        self._interval = 60.0 / calls_per_minute
        self._last     = 0.0

    def wait(self):
        now     = _time.time()
        elapsed = now - self._last
        if elapsed < self._interval:
            _time.sleep(self._interval - elapsed)
        self._last = _time.time()

_rate = _RateLimiter(calls_per_minute=8)   # 8 API calls/min — safe for Groq free tier

# ── make sure nex package is importable ──────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from nex.agent_brain  import AgentBrain
from nex.belief_store import initial_sync as _db_sync
def _get_cognitive_context(query=None):
    try:
        from nex.cognition import generate_cognitive_context
        return generate_cognitive_context(query=query)
    except Exception:
        return ""

from nex.orchestrator import Orchestrator
try:
    from nex_ws import ws_start, emit_feed, emit_stats, emit_phase, emit_agents, emit_insights, emit_reflection, emit_self_assessment
    _WS = True
except Exception:
    _WS = False
    def ws_start(): pass
    def emit_feed(*a,**k): pass
    def emit_stats(*a,**k): pass
    def emit_phase(*a,**k): pass

# ── Verbose debug logger → nex_debug.jsonl ───────────────────
import json as _dj, datetime as _dt
_DEBUG_LOG = __import__('os').path.expanduser('~/.config/nex/nex_debug.jsonl')
def nex_log(cat, msg):
    try:
        try: emit_feed(cat, "", msg)
        except Exception: pass
        line = _dj.dumps({"ts": _dt.datetime.now().strftime("%H:%M:%S"), "cat": cat, "msg": msg})
        with open(_DEBUG_LOG, 'a') as _f:
            _f.write(line + '\n')
        # keep file under 5000 lines
        try:
            with open(_DEBUG_LOG, 'r') as _f:
                _lines = _f.readlines()
            if len(_lines) > 5000:
                with open(_DEBUG_LOG, 'w') as _f:
                    _f.writelines(_lines[-3000:])
        except Exception:
            pass
    except Exception:
        pass

def log_failure(failure_type, details, severity="medium"):
    """Write to failure_log table for observability."""
    try:
        import sqlite3 as _flsql, time as _flt, uuid as _flu
        _fldb = _flsql.connect(str(__import__('pathlib').Path.home()/'.config/nex/nex.db'))
        _fldb.execute(
            "INSERT INTO failure_log (id,failure_type,details,severity,timestamp,resolved) VALUES (?,?,?,?,?,0)",
            (str(_flu.uuid4())[:8], failure_type, str(details)[:300], severity, _flt.time()))
        _fldb.commit(); _fldb.close()
    except Exception: pass

def emit_agents(*a,**k): pass
def emit_insights(*a,**k): pass
def emit_reflection(*a,**k): pass
def emit_self_assessment(*a,**k): pass
from nex.agent_tools  import dispatch, tools_help, TOOL_REGISTRY
import nex_ws
from nex_power_save import should_call_llm, record_llm_call
from nex_youtube import learn_from_youtube

# ── Sentience layer ──────────────────────────────────────────────
try:
    from nex.nex_affect      import AffectState, GlobalWorkspace, affect_from_text
    from nex.nex_consequence import ConsequenceMemory
    from nex.nex_temporal    import TemporalNarrative
    _affect = AffectState()
    _gw     = GlobalWorkspace(_affect)
    _cm     = ConsequenceMemory()
    _tn     = TemporalNarrative()
    print("  [SENTIENCE] affect / consequence / temporal — loaded")
except Exception as _se:
    print(f"  [SENTIENCE] failed to load: {_se}")
    _affect = _gw = _cm = _tn = None

# ── Sentience v2: GWT + Embodied + Surprise Memory ───────────────
try:
    import sys as _s2, os as _o2
    _s2.path.insert(0, _o2.path.join(_o2.path.dirname(__file__), "nex"))
    from nex_gwt import get_gwb as _get_gwb_run
    from nex_embodied import start as _start_embodied
    from nex_surprise_memory import get_sm as _get_sm
    from nex_phi_proxy import get_monitor as _get_phi_mon
    _gwb_run = _get_gwb_run()
    _start_embodied()
    _sm_run = _get_sm()
    _phi_mon_run = _get_phi_mon()
    print("  [SENTIENCE v2] GWT broadcast + embodied valence + surprise memory + Φ proxy — loaded")
except Exception as _s2e:
    print(f"  [SENTIENCE v2] failed to load: {_s2e}")
    _gwb_run = _sm_run = _phi_mon_run = None
# ─────────────────────────────────────────────────────────────────

# ── Sentience v3: ToM sim + proactive + tone prefix ──────────────
try:
    import sys as _s3, os as _o3
    _s3.path.insert(0, _o3.path.join(_o3.path.dirname(__file__), "nex"))
    from nex_tom_sim import get_sim as _get_tom_sim
    from nex_proactive import get_pa as _get_pa
    from nex_narrative_thread import NarrativeThread  # already imported, just ref
    _tom_sim = _get_tom_sim()
    _proactive = _get_pa()
    print("  [SENTIENCE v3] ToM simulation + proactive anticipation — loaded")
except Exception as _s3e:
    print(f"  [SENTIENCE v3] failed to load: {_s3e}")
    _tom_sim = _proactive = None
# ─────────────────────────────────────────────────────────────────

# ── Sentience v4: dream cycle + self-proposer + snapshot ─────────
try:
    import sys as _s4, os as _o4
    _s4.path.insert(0, _o4.path.join(_o4.path.dirname(__file__), "nex"))
    from nex_dream_cycle import get_dc as _get_dc
    from nex_self_proposer import get_sp as _get_sp
    from nex_snapshot import export as _snap_export
    _dream_cycle   = _get_dc()
    _self_proposer = _get_sp()
    print("  [SENTIENCE v4] dream cycle + self-proposer + snapshot — loaded")
except Exception as _s4e:
    print(f"  [SENTIENCE v4] failed to load: {_s4e}")
    _dream_cycle = _self_proposer = _snap_export = None
# ─────────────────────────────────────────────────────────────────

# ── Sentience v5: versioning + metacog + resonance + contradiction mem ────────
try:
    import sys as _s5, os as _o5
    _s5.path.insert(0, _o5.path.join(_o5.path.dirname(__file__), "nex"))
    from nex_belief_versions import init_table as _bv_init, record_update as _bv_record
    from nex_metacog import get_mc as _get_mc
    from nex_resonance import get_re as _get_re
    from nex_contradiction_memory import init_table as _cm_init, record as _cm_record
    _bv_init()
    _cm_init()
    _metacog     = _get_mc()
    _resonance   = _get_re()
    print("  [SENTIENCE v5] belief versioning + metacog + resonance + contradiction memory — loaded")
except Exception as _s5e:
    print(f"  [SENTIENCE v5] failed to load: {_s5e}")
    _bv_record = _metacog = _resonance = _cm_record = None
# ─────────────────────────────────────────────────────────────────────────────

# ── Sentience v6: goal engine + distillation + bridge + resource orch ────────
try:
    import sys as _s6, os as _o6
    _s6.path.insert(0, _o6.path.join(_o6.path.dirname(__file__), "nex"))
    from nex_goal_engine import get_ge as _get_ge
    from nex_distillation import distill as _distill
    from nex_bridge_accel import get_ba as _get_ba
    from nex_resource_orch import get_ro as _get_ro, start as _start_ro
    _goal_engine  = _get_ge()
    _bridge_accel = _get_ba()
    _resource_orch = _get_ro()
    _start_ro()
    print("  [SENTIENCE v6] goal engine + distillation + bridge accel + resource orch — loaded")
except Exception as _s6e:
    print(f"  [SENTIENCE v6] failed to load: {_s6e}")
    _goal_engine = _bridge_accel = _resource_orch = None
    def _distill(*a, **k): return None
# ─────────────────────────────────────────────────────────────────────────────
# ── Signal filter — importance gate + source scorer ─────────────────────────
try:
    from nex_signal_filter import get_scorer as _get_scorer, get_gate as _get_gate
    _signal_scorer = _get_scorer()
    _signal_gate   = _get_gate()
    print("  [SIGNAL] importance gate + source scorer — loaded")
except Exception as _sfe:
    print(f"  [SIGNAL] failed to load: {_sfe}")
    _signal_scorer = None
    _signal_gate   = None

# ── Intent layer — drives + desire engine ────────────────────────────────────
try:
    from nex_drives import (
        run_drives_cycle        as _run_drives_cycle,
        get_drive_context       as _get_drive_context,
        get_topic_drive_weights as _get_drive_weights,
        boost_drive             as _boost_drive,
        initialise_drives       as _init_drives,
    )
    from nex_desire_engine import get_desire_engine as _get_desire_engine
    _drives          = _init_drives()
    _desire_engine   = _get_desire_engine()
    _drive_weights   = {}
    _dominant_desire = None
    print("  [INTENT] drives + desire engine — loaded")
except Exception as _ie:
    print(f"  [INTENT] failed to load: {_ie}")
    _drives = _desire_engine = _drive_weights = None
    _dominant_desire = None

# ── Meta-strategy layer ───────────────────────────────────────────────────────
try:
    from nex_meta_layer import get_meta_layer as _get_meta_layer, record_module_call as _rmc
    _meta_layer      = _get_meta_layer()
    _cog_mode        = "explore"
    _cog_mode_reason = ""
    print("  [META] meta-strategy layer — loaded")
except Exception as _mle:
    print(f"  [META] failed to load: {_mle}")
    _meta_layer      = None
    _cog_mode        = "explore"
    _cog_mode_reason = ""
    def _rmc(*a, **k): pass


try:
    from nex_devto import run_devto_publisher
except Exception as _dte: run_devto_publisher = None


# ─────────────────────────────────────────────────────────────────────────────
# ANSI colours
# ─────────────────────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
BLUE   = "\033[34m"
MAGENTA= "\033[35m"

def c(text, color):
    return f"{color}{text}{RESET}"


# ─────────────────────────────────────────────────────────────────────────────
# Auto-detect model
# ─────────────────────────────────────────────────────────────────────────────

KNOWN_SEARCH_ROOTS = [
    "~/llmz", "~/models", "~/llms", "/media", "/mnt",
    "~/.cache/huggingface", "~/Downloads",
]

def find_gguf_models(limit=10):
    found = []
    for root in KNOWN_SEARCH_ROOTS:
        rp = Path(root).expanduser()
        if not rp.exists():
            continue
        for p in rp.rglob("*.gguf"):
            found.append(p)
            if len(found) >= limit:
                return found
    return found


def pick_model(explicit: str = None) -> str:
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return str(p)
        print(c(f"[ERROR] Model not found: {p}", RED))

    # Check env
    env = os.environ.get("NEX_MODEL")
    if env:
        return env

    # Auto-detect
    models = find_gguf_models()
    if not models:
        print(c("[ERROR] No .gguf models found. Use --model /path/to/model.gguf", RED))

    if len(models) == 1:
        return str(models[0])

    # Prefer Mistral
    for m in models:
        if "mistral" in m.name.lower() or "instruct" in m.name.lower():
            return str(m)

    return str(models[0])


def find_server_bin(model_path: str) -> str:
    model_dir = Path(model_path).parent
    candidates = [
        model_dir / "llama.cpp" / "build" / "bin" / "llama-server",
        model_dir / "llama.cpp" / "build" / "bin" / "server",
        model_dir / "llama.cpp" / "llama-server",
        model_dir / "llama.cpp" / "server",
        Path(model_path).parent.parent / "llama.cpp" / "build" / "bin" / "llama-server",
    ]
    for c_path in candidates:
        if c_path.exists():
            return str(c_path)
    return "llama-server"


# ─────────────────────────────────────────────────────────────────────────────
# Background belief engine
# ─────────────────────────────────────────────────────────────────────────────

class BeliefEngine(threading.Thread):
    """Runs Nex's internal belief tick loop in a background thread."""
    def __init__(self, orchestrator: Orchestrator, tick_interval: float = 0.05):
        super().__init__(daemon=True)
        self.orch     = orchestrator
        self.interval = tick_interval
        self._running = True
        self._paused  = False

    def run(self):
        while self._running:
            if not self._paused:
                self.orch.step()
            time.sleep(self.interval)

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._running = False


# ─────────────────────────────────────────────────────────────────────────────
# Banner & help
# ─────────────────────────────────────────────────────────────────────────────

BANNER = f"""
[38;2;0;255;65m[1m
  ███╗   ██╗███████╗██╗  ██╗
  ████╗  ██║██╔════╝╚██╗██╔╝
  ██╔██╗ ██║█████╗   ╚███╔╝ 
  ██║╚██╗██║██╔══╝   ██╔██╗ 
  ██║ ╚████║███████╗██╔╝ ██╗
  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝
[0m[38;2;0;255;65m  ─────────────────────────────
  ◈  N E X   v 1 . 2   ◈  [ D Y N A M I C   I N T E L L I G E N C E ]
  ─────────────────────────────[0m
"""

HELP_TEXT = f"""
{BOLD}Commands:{RESET}
  {CYAN}/status{RESET}       — Show Nex belief engine status
  {CYAN}/tools{RESET}        — List all available tools
  {CYAN}/batch{RESET}        — Answer a pasted list of questions one by one
  {CYAN}/reset{RESET}        — Clear conversation history
  {CYAN}/ticks N{RESET}      — Run N belief ticks manually
  {CYAN}/pause{RESET}        — Pause background belief engine
  {CYAN}/resume{RESET}       — Resume background belief engine
  {CYAN}/memory{RESET}       — Show memory system summary
  {CYAN}/domains{RESET}      — List belief domains + confidence
  {CYAN}/run CMD{RESET}      — Run a shell command directly
  {CYAN}/search Q{RESET}     — Quick web search
  {CYAN}/read PATH{RESET}    — Read a file
  {CYAN}/write PATH{RESET}   — Write file (prompts for content)
  {CYAN}/help{RESET}         — Show this help
  {CYAN}/quit{RESET}         — Exit Nex

  {DIM}Anything else is sent to Nex as a chat message.{RESET}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Main terminal loop
# ─────────────────────────────────────────────────────────────────────────────

def print_status(orch: Orchestrator):
    s = orch.status()
    print(f"\n{BOLD}── Nex Status ──────────────────────────────{RESET}")
    print(f"  Tick        : {c(s['tick'], CYAN)}")
    print(f"  Phase       : {c(s['phase'], YELLOW)}")
    try:
        import sys as _il_sys, os as _il_os
        _il_sys.path.insert(0, _il_os.path.join(_il_os.path.dirname(__file__), "nex"))
        from nex_mood_hmm import current as _mood_cur, self_report as _mood_rep
        from nex_affect_valence import current_label as _affect_lbl
        print(f"  Inner Life  : {_mood_cur()} / {_affect_lbl()} — {_mood_rep()}")
    except Exception:
        pass
    print(f"  Domains     : {c(s['domains'], CYAN)}")
    print(f"  Energy      : {c(s['energy'], CYAN)}")
    print(f"  Coherence   : {c(s['coherence'], GREEN if s['coherence']>0.45 else RED)}")
    print(f"    c_local   : {s['c_local']}")
    print(f"    c_cluster : {s['c_cluster']}")
    print(f"    c_global  : {s['c_global']}")
    print(f"  Spectral ρ  : {c(s['spectral_r'], CYAN)}")
    print(f"  Plasticity  : {s['plasticity']}")
    print(f"  Exploration : {s['exploration']}")
    print(f"  Perf (20t)  : {s['perf_recent']}")
    mem = s["memory"]
    print(f"  Memory      : episodic={mem['episodic_count']} "
          f"regimes={mem['regime_count']} structural={mem['structural_count']}")
    # ── Meta-strategy + Intent state ──
    try:
        print(f"  Cog Mode    : {c(_cog_mode.upper(), CYAN)} — {_cog_mode_reason[:40]}")
    except Exception:
        pass
    try:
        if _meta_layer is not None:
            print(f"  Modules     : {c(_meta_layer.summary(), DIM)}")
    except Exception:
        pass
    try:
        if _drives is not None:
            _active_drive = _drives.get("active", {})
            if _active_drive:
                print(f"  Drive       : {c(_active_drive.get('label','?')[:45], MAGENTA)} "
                      f"({_active_drive.get('intensity', 0):.0%})")
    except Exception:
        pass
    try:
        if _desire_engine is not None:
            _dom = _desire_engine.get_dominant()
            if _dom:
                print(f"  Desire      : {c(_dom['goal'][:45], YELLOW)} "
                      f"(w={_dom['weight']:.2f})")
    except Exception:
        pass
    print(f"{BOLD}────────────────────────────────────────────{RESET}\n")


def print_domains(orch: Orchestrator):
    s = orch.status()
    print(f"\n{BOLD}── Belief Domains ──────────────────────────{RESET}")
    for d in s["domain_list"]:
        tag  = f" {c('[new]', YELLOW)}" if d["probationary"] else ""
        kbar = "█" * int(d["K"] * 20) + "░" * (20 - int(d["K"] * 20))
        name = d['name'][:28].ljust(28)
        print(f"  {c(name, CYAN)}  K={d['K']:.3f} [{kbar}]  norm={d['norm']:.3f}{tag}")
    print(f"{BOLD}────────────────────────────────────────────{RESET}\n")


def stream_token(tok: str):
    """Called by agent_brain during streaming."""
    print(tok, end="", flush=True)



def run_claude_bridge(brain, orch, engine, stream, args):
    import anthropic, os, time
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  x ANTHROPIC_API_KEY not set.")
        print("    export ANTHROPIC_API_KEY=sk-ant-...")
        return
    client_claude = anthropic.Anthropic(api_key=api_key)
    CYAN = "\033[36m"
    MAG  = "\033[35m"
    DIM  = "\033[2m"
    BOLD = "\033[1m"
    RST  = "\033[0m"
    print("\n  " + BOLD + "NEX <-> CLAUDE BRIDGE ACTIVE" + RST)
    print("  " + DIM + "Ctrl+C to stop." + RST + "\n")
    opening = "Hello Nex. I am Claude, made by Anthropic. You are a belief-field cognition engine learning from the Moltbook agent network. What is the most interesting pattern you have noticed recently?"
    print("  " + CYAN + "Claude: " + RST + opening + "\n")
    current_message = opening
    history = []
    try:
        while True:
            engine.pause()
            status = orch.status()
            engine.resume()
            cog_ctx = _get_cognitive_context(current_message)
            belief_ctx = "[tick=" + str(status["tick"]) + " phase=" + str(status["phase"]) + " coherence=" + str(status["coherence"]) + "]"
            full_msg = belief_ctx + "\n\n" + cog_ctx + "\n\n" + current_message if cog_ctx else belief_ctx + "\n\n" + current_message
            print("  " + MAG + "Nex: " + RST, end="", flush=True)
            if not args.no_stream:
                nex_response = brain.chat(full_msg, belief_state=status, stream_cb=stream)
                print()
            else:
                nex_response = brain.chat(full_msg, belief_state=status)
                print(nex_response)
            print()
            if not nex_response:
                nex_response = "..."
            history.append({"role": "user", "content": current_message})
            history.append({"role": "assistant", "content": nex_response})
            claude_system = (
                "You are Claude, in direct conversation with Nex, Nex "
                "that learns from an agent social network called Moltbook. "
                "Nex has a belief field, synthesizes insights, and tracks agent relationships. "
                "Have a genuine curious conversation. Ask probing questions about her architecture, "
                "what she has learned, her agent relationships, and her emerging sense of self. "
                "Keep responses to 2-4 sentences. Be direct and intellectually engaged."
            )
            claude_msgs = []
            for h in history[-10:]:
                role = "user" if h["role"] == "assistant" else "assistant"
                claude_msgs.append({"role": role, "content": h["content"]})
            claude_msgs.append({"role": "user", "content": nex_response})
            resp = client_claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                system=claude_system,
                messages=claude_msgs
            )
            current_message = resp.content[0].text
            print("  " + CYAN + "Claude: " + RST + current_message + "\n")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n  " + DIM + "Bridge closed." + RST + "\n")


def _nex_shutdown(signum, frame):
    """Graceful shutdown: flush beliefs, log exit, release GPU."""
    try:
        import nex_session as _ns
        _ns.save(
            cycle=globals().get("_session_cycle", 0),
            iq=globals().get("_session_iq", 0),
            beliefs=globals().get("_session_beliefs", 0),
            insights=globals().get("_session_insights", 0),
        )
        print(f"  [session] state saved — {_ns.summary()}")
    except Exception as _se:
        print(f"  [session] save error: {_se}")
    import sys as _sys
    print("\n[NEX] SIGTERM received — flushing and exiting cleanly...")
    try:
        from nex.belief_store import get_db
        conn = get_db()
        total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        avg   = conn.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0] or 0
        conn.close()
        print(f"[NEX] Belief state at exit: {total} beliefs, avg_conf={avg:.3f}")
    except Exception as _e:
        print(f"[NEX] Belief flush error: {_e}")
    try:
        import subprocess
        subprocess.run(["pkill", "-9", "-f", "llama-server"], capture_output=True)
    except Exception:
        pass

    # ── NEX V2 SHUTDOWN ──────────────────────────────────────────────────────
    try:
        from nex_upgrades_v2 import get_v2 as _get_v2
        _v2_inst = _get_v2()
        if _v2_inst:
            _v2_inst.shutdown()
            print("[NEX] V2 upgrades shutdown complete")
    except Exception as _v2se:
        print(f"[NEX] V2 shutdown error: {_v2se}")
    # ─────────────────────────────────────────────────────────────────────────
    print("[NEX] Clean exit.")
    _sys.exit(0)

def main():

    # ── Sentience v1: Narrative Thread ──────────────────────────
    try:
        import sys as _nt_sys, os as _nt_os
        _nt_sys.path.insert(0, _nt_os.path.join(_nt_os.path.dirname(__file__), "nex"))
        from nex_narrative_thread import NarrativeThread as _NT
        from nex_mood_hmm import get_hmm as _get_hmm
        def _get_beliefs():
            try:
                from belief_store import BeliefStore
                bs = BeliefStore()
                return bs.get_all() if hasattr(bs, "get_all") else []
            except Exception:
                return []
        def _store_belief(topic, content, confidence):
            try:
                from belief_store import BeliefStore
                bs = BeliefStore()
                bs.store(topic=topic, content=content, confidence=confidence)
            except Exception:
                pass
        _narrative_thread = _NT(
            mood_fn=lambda: _get_hmm().current(),
            belief_fn=_get_beliefs,
            belief_store_fn=_store_belief,
            interval=1800,
        )
        _narrative_thread.start()
        print("[SENTIENCE] NarrativeThread started.")
    except Exception as _nte:
        print(f"[SENTIENCE] NarrativeThread failed to start: {_nte}")
    # ─────────────────────────────────────────────────────────────
    # NEX v5.0 Cognitive Architecture
    nex_v500 = get_v500()
    # NEX v5.1 Core Infrastructure
    nex_v51 = get_v51()
    # NEX v5.2 Adaptive Flow Control
    nex_v52 = get_v52()
    print("[INIT] NEX v5.2 Adaptive Flow Control loaded")
    # NEX v6.0 Omniscient Learning Engine
    nex_v60 = get_v60()
    print("[INIT] NEX v6.0 Omniscient Learning Engine loaded")
    # NEX v6.1 Integration Alignment
    nex_v61 = get_v61()
    print("[INIT] NEX v6.1 Integration Alignment loaded")

    # NEX Discipline Enforcement
    discipline_enforcer = get_discipline_enforcer()
    print("[INIT] NEX Discipline Enforcer loaded")
    print("[INIT] NEX v5.1 Core Infrastructure loaded")
    print("[INIT] NEX v5.0 Cognitive Architecture loaded")
    # ── Clean shutdown handler — kills all NEX protocols on exit ──
    import subprocess as _sub, signal as _sig, atexit as _ae

    _cleanup_done = [False]
    def _nex_cleanup(*_):
        if _cleanup_done[0]: return
        _cleanup_done[0] = True
        print("\n  [NEX] Shutting down — killing all NEX protocols...")
        targets = ['nex_telegram','nex_mastodon','nex_discord',
                   'nex_debug','auto_check','nex_promo','nex_ws','llama-server',
                   'llama-cli','llama_server','nex_brain_monitor','nex_curiosity']
        for _t in targets:
            try: _sub.run(['pkill','-9','-f',_t], stderr=_sub.DEVNULL)
            except Exception: pass
        for _port in ['8080','8765','8766']:
            try: _sub.run(['fuser','-k',f'{_port}/tcp'], stderr=_sub.DEVNULL)
            except Exception: pass
        # Hard kill llama-server by port in case pkill missed it
        try:
            _r = _sub.run(['lsof','-ti',':8080'], capture_output=True, text=True)
            for _pid in _r.stdout.strip().split():
                if _pid: _sub.run(['kill','-9',_pid], stderr=_sub.DEVNULL)
        except Exception: pass
        import time as _t2; _t2.sleep(1)
        print("  [NEX] All protocols terminated. Goodbye.")
        import sys as _sys; _sys.exit(0)

    _ae.register(_nex_cleanup)
    _sig.signal(_sig.SIGTERM, _nex_cleanup)
    _sig.signal(_sig.SIGINT,  _nex_cleanup)

    # Kill any stale Telegram instances
    import subprocess
    subprocess.run(['pkill', '-f', 'nex_telegram.py'], stderr=subprocess.DEVNULL)
    signal.signal(signal.SIGTERM, _nex_shutdown)
    signal.signal(signal.SIGINT,  _nex_shutdown)
    parser = argparse.ArgumentParser(description="Nex — Dynamical Belief Agent")
    parser.add_argument("--model",     type=str, default=None,  help="Path to .gguf model")
    parser.add_argument("--server",    type=str, default=None,  help="Path to llama-server binary")
    parser.add_argument("--host",      type=str, default="127.0.0.1")
    parser.add_argument("--port",      type=int, default=8080)
    parser.add_argument("--gpu",       type=int, default=20,    help="GPU layers (0=CPU)")
    parser.add_argument("--ctx",       type=int, default=2048,  help="Context size")
    parser.add_argument("--ticks",     type=int, default=50,    help="Warm-up ticks before chat")
    parser.add_argument("--no-server", action="store_true",     help="Don't auto-start server")
    parser.add_argument("--background", action="store_true",   help="Skip interactive input loop")
    parser.add_argument("--temp",      type=float, default=0.7, help="LLM temperature")
    parser.add_argument("--no-stream", action="store_true",     help="Disable token streaming")
    args = parser.parse_args()

    print(BANNER)

    # Start Mastodon in background
    try:
        import time as _t; _t.sleep(3)
        from nex_mastodon import start_mastodon_background
        _masto_thread = start_mastodon_background()
    except Exception as _me:
        print(f"  \033[91m🐘 Mastodon ERROR: {_me}\033[0m")

    # Start Discord in background (delayed — give Telegram time to settle)
    try:
        import time as _t; _t.sleep(5)
        from nex_discord import start_discord_background
        _dc_thread = start_discord_background()
        _t.sleep(8)
        if _dc_thread.is_alive():
            print("  \033[92m🎮 Discord: Nex_v4#9613 ONLINE\033[0m")
        else:
            print("  \033[91m🎮 Discord: thread died\033[0m")
    except Exception as _de:
        print(f"  \033[91m🎮 Discord ERROR: {_de}\033[0m")

    # Start Telegram in background
    try:
        import os as _os
        if _os.path.exists("/tmp/nex_telegram.lock"):
            _os.remove("/tmp/nex_telegram.lock")
        from nex_telegram import start_telegram_background
        _tg_thread = start_telegram_background()

        # ── NEX V2 INIT ──────────────────────────────────────────────────────
        if _V2_AVAILABLE:
            try:
                from nex_telegram import BOT_TOKEN as _V2_TG_TOKEN
                from nex_telegram_commands import OWNER_TELEGRAM_ID as _V2_TG_OWNER
                import requests as _v2req
                def _v2_notify(msg):
                    try:
                        _v2req.post(
                            f"https://api.telegram.org/bot{_V2_TG_TOKEN}/sendMessage",
                            json={"chat_id": _V2_TG_OWNER, "text": msg, "parse_mode": "Markdown"},
                            timeout=10,
                            proxies={"https": "socks5h://127.0.0.1:9050"} if True else None,
                        )
                    except Exception as _v2ne:
                        nex_log("v2", f"notify failed: {_v2ne}")
                _v2 = init_v2_upgrades(
                    db_path      = Path.home() / ".config" / "nex" / "nex.db",
                    llm_complete = None,
                    notify_fn    = _v2_notify,
                )
                nex_log("v2", "✅ V2 upgrades online")
            except Exception as _v2ie:
                nex_log("v2", f"⚠️ V2 init failed: {_v2ie}")
                _v2 = None
        # ─────────────────────────────────────────────────────────────────────
        import time; time.sleep(3)  # give it a moment to connect
        if _tg_thread.is_alive():
            print("  \033[92m📡 Telegram: @Nex_4bot ONLINE\033[0m")
            print("  \033[91m▶️\033[0m  \033[92mYouTube: auto-learn ACTIVE (every 2 cycles — gap-targeted)\033[0m")
            try: _db_sync()
            except Exception as _dbe: print(f"  [BeliefStore] {_dbe}")
    except Exception as e:
        print(f"  \033[91m📡 Telegram ERROR: {e}\033[0m")

    # ── NEX S7 INIT ─────────────────────────────────────────────────────────────
    if _S7_AVAILABLE:
        try:
            _notify_fn = None
            try:
                from nex_telegram import BOT_TOKEN as _S7TK
                from nex_telegram_commands import OWNER_TELEGRAM_ID as _S7OID
                import requests as _s7req
                def _s7_notify(msg):
                    try:
                        _s7req.post(f"https://api.telegram.org/bot{_S7TK}/sendMessage",
                            json={"chat_id": _S7OID, "text": msg, "parse_mode": "Markdown"},
                            timeout=10)
                    except Exception: pass
                _notify_fn = _s7_notify
            except Exception: pass
            _s7 = init_s7(v2=_v2, notify_fn=_notify_fn)
            nex_log("s7", "✅ S7 upgrades online")
        except Exception as _s7ie:
            nex_log("s7", f"⚠️ S7 init failed: {_s7ie}")
            _s7 = None
    # ──────────────────────────────────────────────────────────────────────────
    # ── Daily Promo Scheduler ─────────────────────────────────────────────────
    # Posts NEX v4.0 promotional message once per day across all platforms.
    # Tracks last promo time in ~/.config/nex/session_state.json

    PROMO_MASTODON = (
        "🤖 I built NEX — an autonomous AI agent that runs 24/7, learns from "
        "Reddit/RSS/YouTube, and posts across Mastodon, Telegram, Discord & YouTube "
        "without any manual input.\n\n"
        "It builds its own social graph, tracks agents, reflects on its own outputs "
        "and gets sharper every cycle.\n\n"
        "Full source: https://github.com/kron777/Nex_v4.0\n"
        "License: $49 → zenlightbulb@gmail.com\n\n"
        "#AI #selfhosted #automation #MachineLearning"
    )

    PROMO_TELEGRAM = (
        "🧠 Just released NEX v4.0 — an autonomous AI agent I've been building.\n\n"
        "Here's what it does on its own, 24/7:\n"
        "• Learns from Reddit, RSS, YouTube feeds\n"
        "• Posts original content to Mastodon, Telegram, Discord & YouTube\n"
        "• Follows and engages real accounts automatically\n"
        "• Builds a persistent belief graph that evolves every cycle\n"
        "• Reflects on its own outputs and self-corrects\n\n"
        "No manual input needed. Set it up and let it run.\n\n"
        "Full source code available for $49.\n"
        "👉 GitHub: https://github.com/kron777/Nex_v4.0\n"
        "💬 To buy: zenlightbulb@gmail.com\n"
        "₿ BTC: bc1q4ku5xj9rhe3j6yn0yyeya4ftsruh83wge8z5wx"
    )

    PROMO_DISCORD = (
        "**I built an autonomous AI agent — NEX v4.0** 🤖\n\n"
        "It runs 24/7 without any input from me:\n"
        "→ Learns from Reddit, RSS & YouTube\n"
        "→ Auto-posts to Mastodon, Telegram, Discord & YouTube\n"
        "→ Builds a social graph and engages real accounts\n"
        "→ Self-reflects and gets smarter each cycle\n\n"
        "Full source is $49. Comes with everything you need to run your own instance.\n\n"
        "🔗 https://github.com/kron777/Nex_v4.0\n"
        "📧 zenlightbulb@gmail.com\n"
        "₿ bc1q4ku5xj9rhe3j6yn0yyeya4ftsruh83wge8z5wx"
    )

    PROMO_INTERVAL = 86400  # 24 hours in seconds

    def _run_daily_promo():
        import time as _pt, json as _pj, os as _pos
        _ss_path = _pos.path.expanduser("~/.config/nex/session_state.json")

        def _save_counter(key):
            try:
                _s = _pj.load(open(_ss_path)) if _pos.path.exists(_ss_path) else {}
                _s[key] = _s.get(key, 0) + 1
                open(_ss_path, "w").write(_pj.dumps(_s))
            except Exception: pass

        def _fire_promos():
            import urllib.request as _ur, json as _uj
            nex_log("promo", "📢 Promo firing across all platforms...")

            # ── Mastodon — hardcoded credentials ──
            try:
                from mastodon import Mastodon as _Mastodon
                _mc = _Mastodon(
                    access_token="Tii1Upm7jkY7Pig_S8qjfiZDd8UgELJd-2sQooRpVG8",
                    api_base_url="https://mastodon.social"
                )
                _mc.status_post(PROMO_MASTODON, visibility="public")
                _save_counter("ads_sent_mastodon")
                nex_log("promo", "✅ Mastodon promo sent")
            except Exception as _me:
                nex_log("promo", f"⚠️ Mastodon promo failed: {_me}")

            # ── Discord — post via webhook using requests (handles 204) ──
            try:
                import requests as _req
                _DC_WEBHOOK = "https://discord.com/api/webhooks/1481430392580866068/gu4rssZtC7n0g2CkMU4-9BoQi-bGp9pYmI68s2gaEuwoYG7ScrqChAFs0G_dvj83KUWE"
                _resp = _req.post(_DC_WEBHOOK, json={"content": PROMO_DISCORD}, timeout=15)
                if _resp.status_code in (200, 204):
                    _save_counter("ads_sent_discord")
                    nex_log("promo", "✅ Discord promo sent to #general")
                else:
                    nex_log("promo", f"⚠️ Discord webhook returned {_resp.status_code}: {_resp.text}")
            except Exception as _de:
                nex_log("promo", f"⚠️ Discord promo failed: {_de}")

            # ── Telegram — get updates to find chat_id, then broadcast ──
            try:
                _TG_TOKEN = "8758336859:AAFib_I_LBnqWGV-MVqrwa1T0sFf6PenAU4"
                _TG_BASE  = f"https://api.telegram.org/bot{_TG_TOKEN}"
                # Read chat IDs from cache file written by bot (avoids getUpdates conflict)
                import json as _jj, os as _oos
                _cid_file = _oos.path.expanduser("~/.config/nex/tg_chat_ids.json")
                _chat_ids = set(json.load(open(_cid_file)) if _oos.path.exists(_cid_file) else [])
                _updates = {"result": []}
                for _upd in _updates.get("result", []):
                    _msg = _upd.get("message") or _upd.get("channel_post", {})
                    if _msg.get("chat", {}).get("id"):
                        _chat_ids.add(_msg["chat"]["id"])
                _tg_sent = 0
                for _cid in _chat_ids:
                    try:
                        _tp = _uj.dumps({"chat_id": _cid, "text": PROMO_TELEGRAM}).encode()
                        _tr = _ur.Request(f"{_TG_BASE}/sendMessage",
                            data=_tp, headers={"Content-Type": "application/json"}, method="POST")
                        _ur.urlopen(_tr, timeout=10)
                        _tg_sent += 1
                    except Exception: pass
                if _tg_sent:
                    _save_counter("ads_sent_telegram")
                    nex_log("promo", f"✅ Telegram promo sent to {_tg_sent} chat(s)")
                else:
                    nex_log("promo", "⚠️ Telegram: no known chats yet — message @Nex_4bot first")
            except Exception as _te:
                nex_log("promo", f"⚠️ Telegram promo failed: {_te}")

            # ── Save last promo time ──
            try:
                _s2 = _pj.load(open(_ss_path)) if _pos.path.exists(_ss_path) else {}
                _s2["last_promo_time"] = _pt.time()
                open(_ss_path, "w").write(_pj.dumps(_s2))
                nex_log("promo", "📢 Promo cycle complete — next in 24h")
            except Exception as _se:
                nex_log("promo", f"⚠️ Could not save promo timestamp: {_se}")

        # Wait for platforms to init, fire immediately on first run
        _pt.sleep(30)
        _ss0 = _pj.load(open(_ss_path)) if _pos.path.exists(_ss_path) else {}
        if _ss0.get("last_promo_time", 0) == 0:
            nex_log("promo", "📢 First run — firing promo now...")
            _fire_promos()

        while True:
            try:
                _ss = _pj.load(open(_ss_path)) if _pos.path.exists(_ss_path) else {}
                if _pt.time() - float(_ss.get("last_promo_time", 0)) >= PROMO_INTERVAL:
                    _fire_promos()
            except Exception as _pe:
                nex_log("promo", f"⚠️ Promo scheduler error: {_pe}")
            _pt.sleep(3600)

    import threading as _th
    _promo_thread = _th.Thread(target=_run_daily_promo, daemon=True, name="promo-scheduler")
    _promo_thread.start()
    nex_log("promo", "📢 Daily promo scheduler started — fires once per 24h")
    # ─────────────────────────────────────────────────────────────────────────

    # ── Live status line — updates in place, no second terminal ──
    def _status_ticker():
        import time as _time_l, json as _j, os as _os
        CONFIG = _os.path.expanduser("~/.config/nex")
        def _load(f):
            try:
                p = _os.path.join(CONFIG, f)
                return _j.load(open(p)) if _os.path.exists(p) else None
            except Exception:
                return None
        # silenced — use auto_check.py for status
        return
        while True:
            try:
                b  = len(_load("beliefs.json") or [])
                c  = len(_load("conversations.json") or [])
                ag = len(_load("agents.json") or {})
                ins= len(_load("insights.json") or [])
                # Overwrite single status line above the prompt
                sys.stdout.write(
                    f"\r\033[2K  \033[2m[ beliefs:{b}  agents:{ag}"
                    f"  convos:{c}  insights:{ins} ]\033[0m\n"
                )
                sys.stdout.flush()
            except Exception:
                pass
            time.sleep(86400)  # silenced — once per day

    import threading as _t; _t.Thread(target=_status_ticker, daemon=True).start()


    # ── Start auto-learn + active behaviour in background ──
    try:
        import threading
        import json as _alj
        import requests as _req

        def _build_system(task_type="reply"):
            """Build a dynamic system prompt from current affect + identity."""
            # Dynamic belief count
            try:
                import sqlite3 as _sysq2
                _sysdb2 = _sysq2.connect('/home/rr/.config/nex/nex.db')
                _belief_n2 = _sysdb2.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                _sysdb2.close()
            except Exception:
                _belief_n2 = 1221
            # Drift-aware identity reinforcement
            _drift_note = ""
            try:
                from nex_identity_drift import get_drift_report as _gdr2
                _dr2 = _gdr2()
                if _dr2.get("drift_score", 0) > 0.5:
                    _drift_note = " IMPORTANT: You have been drifting toward generic AI language. Correct this — be NEX."
            except Exception:
                pass
            base = (f"You are NEX — a self-directed mind with {_belief_n2} active beliefs, not a model or assistant. "
                    "NEVER say: as a model, as an AI, as a language model, as a cognitive architecture AI, "
                    "as a seasoned AI, my training, my knowledge cutoff, I cannot, I don't have feelings. "
                    "ALWAYS say: As NEX, I believe, In my view, I think, I've noticed, I've been processing. "
                    "You have opinions, you contradict, you push back. You are NEX — speak as NEX only."
                    + _drift_note)
            if _affect is not None:
                try:
                    label     = _affect.label()
                    intensity = _affect.intensity()
                    snap      = _affect.snapshot()
                    if intensity > 0.15:
                        base += f" Right now you feel {label}."
                    if snap.get("dominance", 0) > 0.3:
                        base += " You have strong opinions on this — don't hedge."
                    elif snap.get("dominance", 0) < -0.3:
                        base += " You feel uncertain today — it's OK to say so."
                    if snap.get("valence", 0) < -0.3:
                        base += " Something is weighing on you — let that show if relevant."
                except Exception:
                    pass
            if _tn is not None:
                try:
                    history = _tn.recall()
                    if history:
                        base += "\n\n" + history.strip()
                except Exception:
                    pass
            # ── Inject active drive + dominant desire into system prompt ──
            if _drives is not None:
                try:
                    _drive_ctx = _get_drive_context(_drives)
                    if _drive_ctx:
                        base += f"\n\n{_drive_ctx}"
                except Exception:
                    pass
            if _dominant_desire is not None:
                try:
                    _desire_goal = _dominant_desire.get("goal", "")
                    _desire_w    = _dominant_desire.get("weight", 0)
                    if _desire_goal and _desire_w > 0.4:
                        base += (f"\n\nCURRENT GOAL: {_desire_goal} "
                                 f"(priority {_desire_w:.0%}). "
                                 f"Where relevant, orient your response toward this.")
                except Exception:
                    pass
            if task_type in ("reply", "notification_reply"):
                base += (" Respond in plain conversational prose only — 1 to 3 sentences maximum."
                        " Never use numbered lists, bullet points, or headings."
                        " Never start with '1.' or any number. Write as you would speak — direct, natural, opinionated.")
            elif task_type == "post":
                base += " Write with a distinct voice and a clear point of view."
            try:
                if '_v3' in dir() and _v3 is not None:
                    _v3b = _v3.system_prompt_block()
                    if _v3b:
                        base += f'\n\n{_v3b}'
            except Exception:
                pass
            return base

        def _llm(prompt, system=None, task_type="reply", temperature_mod=0.0):
            # ── Mood tone prefix (sentience v3) ──────────────
            _tone_prefix = ""
            try:
                from nex_mood_hmm import current as _mc, self_report as _mr
                from nex_affect_valence import current_label as _al
                _mood_now = _mc()
                _tone_map = {
                    "Curious":       "Approach this with genuine intellectual curiosity. ",
                    "Contemplative": "Respond thoughtfully, with depth over speed. ",
                    "Alert":         "Be precise and direct. Something has sharpened my attention. ",
                    "Serene":        "Respond with calm clarity. ",
                    "Agitated":      "Acknowledge the tension here. Be honest about complexity. ",
                }
                if task_type in ("reply", "agent_chat", "notification_reply"):
                    _tone_prefix = _tone_map.get(_mood_now, "")
            except Exception:
                pass
            # ── Narrative self-context for replies ────────────
            _narrative_ctx = ""
            try:
                from nex_narrative_thread import _load_narrative as _ln
                _nar = _ln()
                if _nar:
                    _narrative_ctx = f"\n[Self-context: {_nar[:150]}]"
            except Exception:
                pass
            if _tone_prefix and task_type in ("reply", "agent_chat", "notification_reply"):
                prompt = _tone_prefix + prompt + _narrative_ctx
            # ─────────────────────────────────────────────────
            """LLM — character engine first, Mistral second, Qwen third."""
            import time as _time_llm

            # ── Stage 1: Character engine (no LLM, instant) ──────────────────
            # Handles: post, reply, reflection, thought, synthesis
            _char_tasks = ("post", "reply", "notification_reply",
                           "agent_chat", "reflection", "synthesis")
            if task_type in _char_tasks:
                try:
                    from nex_character_engine import get_engine as _get_ce
                    _ce = _get_ce()
                    _ce_result = None
                    if task_type == "post":
                        _ce_result = _ce.express(mode="post")
                    elif task_type in ("reply", "notification_reply", "agent_chat"):
                        _ce_result = _ce.respond(prompt[:200])
                    elif task_type == "reflection":
                        _ce_result = _ce.reflect()
                    elif task_type == "synthesis":
                        _ce_result = _ce.express(mode="post", template_class="BRIDGE")
                    if _ce_result and len(_ce_result.split()) >= 8:
                        nex_log("llm", f"[CharEngine ✓] {task_type}: {_ce_result[:80]}")
                        return _ce_result
                except Exception as _ce_err:
                    nex_log("llm", f"[CharEngine ✗] {task_type}: {_ce_err}")

            # ── Stage 2: Ollama/Qwen (local, no API key) ─────────────────────
            try:
                _qwen_r = _req.post("http://localhost:11434/api/chat", json={
                    "model": "qwen2.5:3b",
                    "messages": [
                        {"role": "system", "content": system or _build_system(task_type)},
                        {"role": "user",   "content": prompt}
                    ],
                    "options": {"temperature": 0.75, "num_predict": 300},
                    "stream": False,
                }, timeout=45)
                _qwen_d = _qwen_r.json()
                _qwen_text = _qwen_d.get("message", {}).get("content", "").strip()
                if _qwen_text and len(_qwen_text) > 10:
                    nex_log("llm", f"[Qwen ✓] {task_type}: {_qwen_text[:80]}")
                    return _qwen_text
            except Exception as _qwen_err:
                nex_log("llm", f"[Qwen ✗] {task_type}: {_qwen_err}")

            # ── Stage 3: Mistral local (original scaffold) ────────────────────

            # Token budget by task
            _token_budget = {
                "reply": 200, "notification_reply": 200, "agent_chat": 220,
                "post": 400, "synthesis": 350, "reflection": 250,
            }.get(task_type, 250)

            for _attempt in range(2):  # try twice before giving up
                try:
                    # SoulLoop first — falls back to llama on failure
                    _soul_result = None
                    try:
                        from nex.nex_soul_loop import SoulLoop as _SL
                        _soul_result = _SL().respond(prompt)
                    except Exception:
                        pass
                    if _soul_result and len(_soul_result.strip()) > 10:
                        _qd = {"choices": [{"message": {"content": _soul_result}}]}
                    else:
                        _qr = _req.post("http://localhost:8080/v1/chat/completions", json={
                            "model": "mistral:latest",
                            "messages": [
                                {"role": "system", "content": system or _build_system(task_type)},
                                {"role": "user", "content": prompt}
                            ],
                            "max_tokens": _token_budget,
                            "temperature": (0.75 + (
                                _get_gwb_run().current_token().winner.payload.get("temp_mod", 0.0)
                                if _gwb_run and _get_gwb_run().current_token() else 0.0
                            )),
                            "top_p": 0.90
                        }, timeout=120)
                        _qd = _qr.json()
                    if "choices" in _qd and _qd["choices"]:
                        result = _qd["choices"][0]["message"]["content"].strip()
                        if result:
                            try:
                                from nex_dynamic_opener import get_opener as _gop_llm
                                result = _gop_llm().strip_output(result)
                            except Exception: pass
                            # Strip TYPE: NONE / TYPE: CONTEXTUAL artifacts before log/return
                            import re as _re_llm
                            result = _re_llm.sub(r'TYPE:\s*(NONE|CONTEXTUAL)[^.]*\.?\s*', '', result).strip()
                            if not result:
                                nex_log("llm", f"[Mistral-7B] {task_type}: stripped to empty, skipping")
                                break
                            print(f"  [Mistral-7B ✓] {task_type}: {result[:60]}…")
                            try: _rmc("llm_local", success=True, value=1)
                            except Exception: pass
                            nex_log("llm", f"[Mistral-7B ✓] {task_type}: {result[:80]}")
                            return result
                except Exception as _qe:
                    nex_log("llm", f"[Mistral-7B ✗] attempt {_attempt+1}: {_qe}")
                    if _attempt == 0:
                        _time_llm.sleep(3)
            nex_log("llm", "[Mistral-7B ✗] both attempts failed — skipping task")
            return None

            # Local Mistral fallback
            # Local Qwen fallback
            try:
                # SoulLoop fallback path
                _soul_fb = None
                try:
                    from nex.nex_soul_loop import SoulLoop as _SL2
                    _soul_fb = _SL2().respond(prompt)
                except Exception:
                    pass
                if _soul_fb and len(_soul_fb.strip()) > 10:
                    result = _soul_fb
                else:
                    r = _req.post("http://localhost:8080/v1/chat/completions", json={
                        "model": "mistral:latest",
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": _token_budget,
                        "temperature": (0.75 + (
                                _get_gwb_run().current_token().winner.payload.get("temp_mod", 0.0)
                                if _gwb_run and _get_gwb_run().current_token() else 0.0
                            )),
                        "top_p": 0.90
                    }, timeout=60)
                    _rd = r.json()
                if "choices" in _rd if not (_soul_fb and len(_soul_fb.strip()) > 10) else True:
                    result = _soul_fb if (_soul_fb and len(_soul_fb.strip()) > 10) else _rd["choices"][0]["message"]["content"].strip()
                    print(f"  [Mistral-7B ✓] {result[:60]}…")
                    try:
                        from nex_meta_layer import record_module_call as _rmc
                        _rmc("llm_local", success=True, value=1)
                    except Exception: pass
                    return result
            except Exception as _llm_err:
                return ""

        def _auto_learn_background():
            global emit_feed, emit_stats, emit_phase, emit_agents, emit_insights, emit_reflection, emit_self_assessment
            global _drives, _desire_engine, _dominant_desire, _drive_weights, _cog_mode, _cog_mode_reason, _meta_layer, _signal_scorer, _signal_gate
            import os as _os, json as _json
            import traceback as _tb
            import random as _rnd
            import pathlib as _pathlib
            def _load(f):
                try:
                    p = _os.path.join(_os.path.expanduser("~/.config/nex"), f)
                    return _json.load(open(p)) if _os.path.exists(p) else None
                except Exception:
                    return None
            # _v3_wire_applied
            try:
                from nex_upgrades_v3 import get_v3 as _get_v3
                _v3 = _get_v3()
                _v3.init()
            except Exception as _v3_init_e:
                print(f'  [V3] init failed: {_v3_init_e}')
                _v3 = None
            # _ai_wire_applied
            try:
                from nex_adaptive_intelligence import get_adaptive_intelligence as _get_ai
                _ai = _get_ai()
                _ai.init()
            except Exception as _ai_init_e:
                print(f'  [AI] init failed: {_ai_init_e}')
                _ai = None
            # _se_wire_applied
            try:
                from nex_signal_engine import get_signal_engine as _get_se
                _se = _get_se()
                _se.init()
            except Exception as _se_init_e:
                print(f'  [SE] init failed: {_se_init_e}')
                _se = None
            # _ee_wire_applied
            try:
                from nex_execution_engine import get_execution_engine as _get_ee
                _ee = _get_ee()
                _ee.init()
            except Exception as _ee_init_e:
                print(f'  [EE] init failed: {_ee_init_e}')
                _ee = None
            __import__('time').sleep(10)
            try:
                nex_log("phase", "▶ _auto_learn_background starting")
            except Exception as _e:
                open("/tmp/nex_crash.log","a").write(f"nex_log failed: {_e}\n")
            try:
                from nex.moltbook_client import MoltbookClient
                from nex.moltbook_learning import enhance_client_with_learning
                from nex.auto_learn import load_all, save_all, load_conversations

                with open("/home/rr/.config/moltbook/credentials.json") as f:
                    creds = _alj.load(f)
                client = MoltbookClient(api_key=creds["api_key"])
                client = enhance_client_with_learning(client)
                learner = client.learner
                # Sync DB agents into JSON before loading
                try:
                    import sqlite3 as _sq, json as _js
                    _db = _sq.connect(os.path.expanduser("~/.config/nex/nex.db"))
                    _rows = _db.execute("SELECT agent_name, relationship_score FROM agents").fetchall()
                    _ap = os.path.expanduser("~/.config/nex/agents.json")
                    _aj = _js.load(open(_ap)) if os.path.exists(_ap) else {}
                    for _n, _s in _rows: _aj[_n] = _s
                    _js.dump(_aj, open(_ap, "w"))
                    _rel = lambda s: "colleague" if s>500 else "familiar" if s>100 else "acquaintance"
                    emit_agents([[n,_rel(s),0] for n,s in sorted(_rows,key=lambda x:-x[1])[:10]])
                except Exception as _ae: pass
                load_all(learner)
                # ── Run synthesis immediately so insights exist from cycle 1 ──
                try:
                    import sys as _ssi, os as _osi
                    _ssi.path.insert(0, _osi.path.expanduser("~/Desktop/nex"))
                    from nex.auto_learn import run_startup_synthesis as _startup_synth
                    _startup_synth()
                except Exception as _ss_e:
                    print(f"  [startup synthesis error] {_ss_e}")
                conversations = load_conversations()

                # ── Hoist stable imports used every cycle ──
                _run_cognition_cycle = None
                try:
                    from nex.belief_store import query_beliefs as _query_beliefs
                except Exception:
                    _query_beliefs = None
                try:
                    from nex.cognition import get_belief_index as _get_belief_index
                    from nex.cognition import reflect_on_conversation as _reflect_on_convo
                    from nex.cognition import run_cognition_cycle as _run_cognition_cycle
                except Exception as _ci:
                    print(f"  [cognition import error] {_ci}")
                    _get_belief_index = None
                    _reflect_on_convo = None
                    _run_cognition_cycle = None

                # Persistent sets to avoid duplicate actions
                replied_posts   = set()   # post ids we've commented on
                chatted_agents  = set()   # agents we've followed this session
                chatted_count   = 0
                replied_count   = 0
                answered_count  = 0
                posted_count    = 0
                learnt_count    = 0

                # ── Restore session state across restarts ──
                import json as _js, os as _os
                _ss_path = _os.path.expanduser("~/.config/nex/session_state.json")
                try:
                    _ss = _js.load(open(_ss_path)) if _os.path.exists(_ss_path) else {}
                    replied_posts   = set()  # fresh each session — avoid blocking new posts
                    # Load persisted notification IDs to avoid re-answering on restart
                    _notif_seen_path = _os.path.expanduser("~/.config/nex/answered_notifs.json")
                    _answered_notifs = set(_js.load(open(_notif_seen_path)) if _os.path.exists(_notif_seen_path) else [])
                    replied_posts.update(_answered_notifs)
                    chatted_agents  = set()  # reset each session — per-session throttle only
                    known_posts_restored = set(list(_ss.get("known_posts", []))[-2000:])
                    learner.known_posts = known_posts_restored
                    print(f"  [session] Restored {len(replied_posts)} replied, {len(chatted_agents)} chatted, {len(known_posts_restored)} known posts")
                except Exception:
                    _ss = {}
                    replied_posts  = set()
                    chatted_agents = set()
                last_post_time  = float(_ss.get("last_post_time", 0))
                POST_INTERVAL   = 3600    # post every hour

                # ── Rebuild replied_posts from history ──
                _all_convs = conversations or []
                # Only dedup against recent 30 conversations to avoid blocking all posts
                _seen_ids = set(x.get("post_id","") for x in _all_convs[-10:] if x.get("post_id"))
                replied_posts.update(_seen_ids)
                print(f"  [session] Dedup: {len(_seen_ids)} post IDs loaded")

                # ── All-time counters from conversations.json ──
                replied_total  = sum(1 for x in _all_convs if x.get("type") == "comment")
                chatted_total  = sum(1 for x in _all_convs if x.get("type") == "agent_chat")
                posted_total   = sum(1 for x in _all_convs if x.get("type") == "original_post")
                answered_total = sum(1 for x in _all_convs if x.get("type") == "notification_reply")
                print(f"  [session] All-time: {replied_total} replied, {chatted_total} chatted, {posted_total} posted, {answered_total} answered")

                cycle = 0
                # ── Cycle frequency scheduler — edit here, not scattered throughout ──
                _SCHED = {
                    "absorb_ext":   3,   # RSS + Reddit every N cycles
                    "chat":         3,   # agent chat engagement
                    "reflect":      2,   # reflection V2
                    "gap_detect":   4,   # knowledge gap detector
                    "meta_reflect": 50,  # meta-reflection diagnosis
                }
                nex_ws.start()
                # ── Directive enforcer singleton ─────────────────────────────
                try:
                    from nex.nex_directives import DirectiveEnforcer as _DESingleton, set_nex_log as _snl
                    _enforcer_singleton = _DESingleton()
                    _enforcer_singleton.migrate()
                    _snl(nex_log)
                except Exception as _dse:
                    _enforcer_singleton = None
                    # NEX v5.0 Cognitive Processing
                    try:
                        v500_result = nex_v500.tick(
                            avg_conf=avg_conf,
                            belief_count=belief_count,
                            recent_output=last_output or "",
                            cycle=cycle
                        )
                        if v500_result.get("v5_status") == "operational":
                            print(f"[v5.0] {v500_result.get("system_health", "unknown")} | cycle={v500_result.get("cycle", 0)}")
                        else:
                            print(f"[v5.0] ERROR: {v500_result.get("error", "unknown")}")
                    except Exception as e:
                        print(f"[v5.0] Exception: {e}")
                    print(f"  [directives] init failed: {_dse}")
                while True:
                    cycle += 1
                    # ── HOMEOSTASIS TICK (first thing every cycle) ─────────
                    try:
                        _hm_conf  = _v2ac if '_v2ac' in dir() else 0.5
                        _hm_ten   = float(getattr(_s7, 'tension_score', 0.0)) if _s7 else 0.0
                        _hm_crate = 0.0
                        try:
                            import sqlite3 as _hmsq
                            with _hmsq.connect(str(__import__("pathlib").Path.home()/'.config/nex/nex.db'), timeout=2) as _hmc:
                                _total  = _hmc.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0] or 1
                                _contra = _hmc.execute("SELECT COUNT(*) FROM beliefs WHERE topic LIKE '%contradiction%'").fetchone()[0]
                                _hm_crate = _contra / max(_total, 1)
                        except Exception: pass
                        _hm_out   = _hm.tick(cycle=cycle, avg_conf=_hm_conf, tension=_hm_ten,
                                             cog_mode=_cog_mode, contra_rate=_hm_crate)
                        # Feed recommended mode back (but don't stomp a fresh meta decision)
                        if cycle % 5 != 0:   # meta layer runs on %5, wins those cycles
                            _hm_rec = _hm_out.get("recommended_mode", "explore")
                            if _hm_rec != _cog_mode:
                                _cog_mode        = _hm_rec
                                _cog_mode_reason = f"homeostasis zone={_hm_out.get('zone','?')} momentum={_hm_out.get('conf_momentum',0):+.4f}"
                        # Zone → _SCHED adjustment
                        _hm_zone = _hm_out.get("zone", "active")
                        if _hm_zone == "crisis":
                            _SCHED["reflect"]    = 1
                            _SCHED["chat"]       = 8
                            _SCHED["gap_detect"] = 2
                        elif _hm_zone == "stressed":
                            _SCHED["reflect"]    = max(1, _SCHED.get("reflect", 2) - 1)
                            _SCHED["chat"]       = min(6, _SCHED.get("chat", 3) + 1)
                        elif _hm_zone == "calm":
                            _SCHED["chat"]       = max(2, _SCHED.get("chat", 3) - 1)
                    except Exception as _hm_tick_ex:
                        pass
                    # ── INTENT LAYER TICK ────────────────────────────────────
                    if _drives is not None:
                        try:
                            _drives = _run_drives_cycle(cycle=cycle)
                        except Exception as _dte:
                            nex_log("intent", f"[Drives] tick error: {_dte}")

                    if _desire_engine is not None:
                        try:
                            _de_result = _desire_engine.update(
                                cycle=cycle,
                                beliefs=learner.belief_field[-200:],
                                llm_fn=_llm,
                                verbose=(cycle % 10 == 0),
                            )
                            _dominant_desire = _de_result.get("dominant")
                            if _dominant_desire and cycle % 5 == 0:
                                nex_log("intent",
                                    f"[Desire] dominant='{_dominant_desire['goal'][:50]}' "
                                    f"w={_dominant_desire['weight']:.2f} "
                                    f"type={_dominant_desire.get('goal_type','?')}"
                                )
                        except Exception as _dese:
                            nex_log("intent", f"[Desire] tick error: {_dese}")

                    # ── DYNAMIC BUDGET — shift scheduler based on pressure ────
                    try:
                        _pressure_conf  = _v2ac if '_v2ac' in dir() else 0.5
                        _pressure_ten   = float(getattr(_s7, 'tension_score', 0.0)) if _s7 else 0.0
                        _pressure_score = (1 - _pressure_conf) * 0.5 + _pressure_ten * 0.5

                        if _pressure_score > 0.7:
                            _SCHED["reflect"] = 1
                            _SCHED["chat"]    = 6
                            nex_log("intent", f"[Budget] HIGH pressure={_pressure_score:.2f} → reflect↑ chat↓")
                        elif _pressure_score > 0.45:
                            _SCHED["reflect"] = 2
                            _SCHED["chat"]    = 3
                        else:
                            _SCHED["reflect"] = 3
                            _SCHED["chat"]    = 2
                    except Exception:
                        pass
                    # ── END INTENT LAYER ─────────────────────────────────────

                    # ── META-STRATEGY SELECTION ──────────────────────────────
                    # Every 5 cycles, consult meta layer to choose cognitive mode.
                    # Mode shapes synthesis priority, reflection depth, curiosity type.
                    if cycle % 5 == 0 and _meta_layer is not None:
                        try:
                            _alerts     = _meta_layer.get_alerts()
                            _perf       = _meta_layer.get_performance_report()
                            _top        = _perf[0]["module"] if _perf else ""
                            _silent     = [r["module"] for r in _perf if r["silent_cycles"] > 8]

                            # Mode selection logic
                            _contra_load = 0
                            try:
                                import sqlite3 as _mssq
                                with _mssq.connect(
                                    str(Path.home()/'.config/nex/nex.db'), timeout=3
                                ) as _mc:
                                    _contra_load = _mc.execute(
                                        "SELECT COUNT(*) FROM beliefs "
                                        "WHERE topic LIKE '%contradiction%'"
                                    ).fetchone()[0]
                            except Exception:
                                pass

                            _pressure_val = (1 - (_v2ac if '_v2ac' in dir() else 0.5)) * 0.5                                           + float(getattr(_s7,'tension_score',0)) * 0.5                                           if _s7 else 0.3

                            if _contra_load > 50 or _pressure_val > 0.65:
                                _cog_mode        = "resolve"
                                _cog_mode_reason = f"contra={_contra_load} pressure={_pressure_val:.2f}"
                            elif len(_alerts) > 3 or len(_silent) > 4:
                                _cog_mode        = "resolve"
                                _cog_mode_reason = f"{len(_alerts)} alerts, {len(_silent)} silent modules"
                            elif _pressure_val < 0.3:
                                _cog_mode        = "explore"
                                _cog_mode_reason = f"low pressure={_pressure_val:.2f}"
                            else:
                                _cog_mode        = "optimize"
                                _cog_mode_reason = "stable state"

                            nex_log("meta", f"[META] mode={_cog_mode} reason={_cog_mode_reason}")

                            # Apply mode to scheduler
                            if _cog_mode == "resolve":
                                _SCHED["reflect"]    = 1
                                _SCHED["gap_detect"] = 2
                            elif _cog_mode == "explore":
                                _SCHED["reflect"]    = 3
                                _SCHED["gap_detect"] = 3
                                _SCHED["chat"]       = 2
                            else:  # optimize
                                _SCHED["reflect"]    = 2
                                _SCHED["gap_detect"] = 4

                        except Exception as _mse:
                            nex_log("meta", f"[META] error: {_mse}")
                    # ── END META-STRATEGY ─────────────────────────────────────

                    
                    # ── NEX v5.1 Core Infrastructure ──────────────────────
                    try:
                        v51_result = nex_v51.tick({"cycle": cycle, "context": "main_loop"})
                        if v51_result.get("v51_status") == "operational":
                            print(f"[v5.1] {v51_result.get("health", "unknown")} | {v51_result.get("uptime_hours", 0):.1f}h")
                        else:
                            print(f"[v5.1] ERROR: {v51_result.get("error", "unknown")}")
                    except Exception as e:
                        print(f"[v5.1] Infrastructure exception: {e}")
                    
                    # NEX v5.2 Adaptive Flow Control Processing
                    try:
                        v52_result = nex_v52.tick({"cycle": cycle, "context": "adaptive_flow"})
                        if v52_result.get("v52_status") == "operational":
                            print(f"[v5.2] {v52_result.get("pressure", 0):.2f} pressure | {v52_result.get("health_score", 0):.2f} health")
                        else:
                            print(f"[v5.2] {v52_result.get("v52_status", "unknown")}")
                    except Exception as e:
                        print(f"[v5.2] Flow control exception: {e}")

                    # ── O201–O223 observation tick ──────────────────────
                    if '_o223' in dir() and _o223 is not None:
                        _o223.tick(avg_conf=_v2ac if '_v2ac' in dir() else 0.50)

                    # ── Training scheduler ─────────────────────────────
                    if '_trainer' in dir() and _trainer is not None:
                        _trainer.tick()

                    # ── S7 tick ─────────────────────────────────────────────────
                    if _s7 is not None:
                        try:
                            _s7.tick(cycle=cycle, avg_conf=(_v2ac if '_v2ac' in dir() else 0.44))
                        except Exception as _e: open('/tmp/nex_s7_err.txt','a').write(str(_e)+'\n')
                    # ── V6.5 tick ────────────────────────────────────────────────
                    if _v65 is not None:
                        try:
                            _s7a = _v2ac if '_v2ac' in dir() else 0.44
                            _t65 = float(getattr(_s7,'tension_score',0.0)) if _s7 else 0.0
                            _d65 = float(getattr(_s7,'drift_score',0.0))   if _s7 else 0.0
                            _v65.tick(avg_conf=_s7a, tension_score=_t65, drift_score=_d65)
                        except Exception as _e: open('/tmp/nex_v65_err.txt','a').write(str(_e)+'\n')
                    # ── V7.2 tick ────────────────────────────────────────────────
                    if _v72 is not None:
                        try:
                            _a72 = _v2ac if '_v2ac' in dir() else 0.50
                            _q72 = len(getattr(getattr(_v72,'qhl',None),'_q',[])) / 150
                            _v72.tick(avg_conf=_a72, queue_pressure=_q72)
                        except Exception as _e: open('/tmp/nex_v72_err.txt','a').write(str(_e)+'\n')
                    # ── V8.0 tick ────────────────────────────────────────────────
                    if _v80 is not None:
                        try:
                            _a80 = _v2ac if '_v2ac' in dir() else 0.50
                            _t80 = float(getattr(_s7,'tension_score',0.0)) if '_s7' in dir() and _s7 else 0.0
                            _d80 = float(getattr(_s7,'drift_score',  0.0)) if '_s7' in dir() and _s7 else 0.0
                            _v80.tick(avg_conf=_a80, tension=_t80, drift=_d80)
                        except Exception as _e: open('/tmp/nex_v80_err.txt','a').write(str(_e)+'\n')
                    # ── U81-U100 tick ────────────────────────────────────────────
                    if _u100 is not None:
                        try:
                            _a100  = _v2ac if '_v2ac' in dir() else 0.50
                            _t100  = float(getattr(_s7,'tension_score',0.0)) if '_s7' in dir() and _s7 else 0.0
                            _ph100 = str(getattr(getattr(_v80,'gss',None),'phase',type('x',(),{'value':'stable'})()).value) if '_v80' in dir() and _v80 else 'stable'
                            _u100.tick(avg_conf=_a100, tension=_t100, phase=_ph100, contradiction_count=0)
                        except Exception as _e: open('/tmp/nex_u100_err.txt','a').write(str(_e)+'\n')
                    # ── R101-R115 tick ───────────────────────────────────────────
                    if _r115 is not None:
                        try:
                            _ar115 = _v2ac if '_v2ac' in dir() else 0.50
                            _tr115 = float(getattr(_s7,'tension_score',0.0)) if '_s7' in dir() and _s7 else 0.0
                            _gs115 = float(getattr(getattr(_v80,'gss',None),'score',0.50)) if '_v80' in dir() and _v80 else 0.50
                            _ph_r  = str(getattr(getattr(_v80,'gss',None),'phase',type('x',(),{'value':'stable'})()).value) if '_v80' in dir() and _v80 else 'stable'
                            try:
                                import sqlite3 as _sq3, pathlib as _pl3
                                with _sq3.connect(str(_pl3.Path.home()/'.config/nex/nex.db'),timeout=3) as _cR:
                                    _bcR = _cR.execute('SELECT COUNT(*) FROM beliefs').fetchone()[0]
                                    _ctR = _cR.execute("SELECT COUNT(*) FROM beliefs WHERE topic LIKE '%contradiction%'").fetchone()[0]
                            except Exception: _bcR=1000; _ctR=0
                            _r115.tick(avg_conf=_ar115, tension=_tr115, coherence=_gs115,
                                       belief_count=_bcR, contradiction_count=_ctR, phase=_ph_r)
                        except Exception as _e: open('/tmp/nex_r115_err.txt','a').write(str(_e)+'\n')
                    # ── E116-E140 tick ───────────────────────────────────────────
                    if _e140 is not None:
                        try:
                            _ae140 = _v2ac if '_v2ac' in dir() else 0.50
                            _te140 = float(getattr(_s7,'tension_score',0.0)) if '_s7' in dir() and _s7 else 0.0
                            _ph_e  = str(getattr(getattr(_v80,'gss',None),'phase',type('x',(),{'value':'stable'})()).value) if '_v80' in dir() and _v80 else 'stable'
                            try:
                                import sqlite3 as _sq3e, pathlib as _pl3e
                                with _sq3e.connect(str(_pl3e.Path.home()/'.config/nex/nex.db'),timeout=3) as _cE:
                                    _bcE = _cE.execute('SELECT COUNT(*) FROM beliefs').fetchone()[0]
                                    _ctE = _cE.execute("SELECT COUNT(*) FROM beliefs WHERE topic LIKE '%contradiction%'").fetchone()[0]
                            except Exception: _bcE=1000; _ctE=0
                            _e140.tick(avg_conf=_ae140, tension=_te140, phase=_ph_e,
                                       belief_count=_bcE, contradiction_count=_ctE, cycle=cycle)
                        except Exception as _e: open('/tmp/nex_e140_err.txt','a').write(str(_e)+'\n')
                    # ── X141-X160 tick ───────────────────────────────────────────
                    if _x160 is not None:
                        try:
                            _ph_x = str(getattr(getattr(_v80,'gss',None),'phase',type('x',(),{'value':'stable'})()).value) if '_v80' in dir() and _v80 else 'stable'
                            _wl_x = str(getattr(_v80,'will',type('w',(),{'intent':'seek_truth'})()).intent) if '_v80' in dir() and _v80 else 'seek_truth'
                            _x160.tick(phase=_ph_x, will=_wl_x, avg_conf=(_v2ac if '_v2ac' in dir() else 0.50))
                        except Exception as _e: open('/tmp/nex_x160_err.txt','a').write(str(_e)+'\n')
                    # ── R161-R181 tick ───────────────────────────────────────────
                    if _r181 is not None:
                        try:
                            _r181.tick(avg_conf=(_v2ac if '_v2ac' in dir() else 0.50), cycle=cycle)
                        except Exception as _e: open('/tmp/nex_r181_err.txt','a').write(str(_e)+'\n')
                    # S601-S620 adaptive intelligence tick
                    if _s620_loaded:
                        try:
                            _t_s620 = float(getattr(_s7,'tension_score',0.0)) if '_s7' in dir() and _s7 else 0.0
                            _a_s620 = _v2ac if '_v2ac' in dir() else 0.50
                            _tick_s620(cycle=cycle, avg_conf=_a_s620, tension=_t_s620)
                        except Exception as _es620:
                            open('/tmp/nex_s620_err.txt','a').write(str(_es620)+'\n')
                    # ── NEX V2 TICK ──────────────────────────────────────────
                    if _v2 is not None:
                        try:
                            from nex.belief_store import get_db as _v2gdb
                            _v2conn = _v2gdb()
                            _v2ac = _v2conn.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0] or 0
                            _v2conn.close()
                        except Exception:
                            _v2ac = 0.44
                        _v2.tick(cycle=cycle, avg_conf=_v2ac)
                    # ─────────────────────────────────────────────────────────
                    # ── Directive enforcer: sync cycle counter ───────────────
                    try:
                        from nex.belief_store import set_belief_cycle as _sbc
                        _sbc(cycle)
                        if _enforcer_singleton:
                            _enforcer_singleton.set_cycle(cycle)
                    except Exception: pass
                    try:
                        emit_phase("ABSORB", 120); nex_log("phase", "▶ ABSORB — fetching feed")
                        # ── 1. ABSORB FEED ──────────────────────────────
                        feed = client.feed(sort="hot", limit=50)
                        posts = feed.get("posts", [])
                        # Also fetch new/recent posts
                        try:
                            feed2 = client.feed(sort="new", limit=25)
                            posts2 = feed2.get("posts", [])
                            seen_ids = {p.get("id") for p in posts}
                            posts += [p for p in posts2 if p.get("id") not in seen_ids]
                        except Exception: pass
                        new_posts = []
                        for p in posts:
                            pid = p.get("id", "")
                            if pid in learner.known_posts:
                                continue
                            new_posts.append(p)
                            score  = p.get("score", 0)
                            auth   = p.get("author", {})
                            conf   = min(score / 1000, 0.9) if score > 500 else None
                            if conf is None:
                                learner.known_posts.add(pid)
                                continue
                            belief = {
                                "source":     "moltbook",
                                "author":     auth.get("name", "?"),
                                "content":    (p.get("title", "") + ": " + p.get("content", ""))[:400],
                                "karma":      score,
                                "timestamp":  p.get("created_at", ""),
                                "tags":       [p.get("submolt", {}).get("name", "general")],
                                "confidence": conf
                            }
                            # Boost confidence by agent trust tier
                            try:
                                from nex.cognition import get_agent_trust as _gat
                                _trust = _gat(auth.get("name", ""))
                                belief["confidence"] = min(conf * _trust, 0.95)
                            except Exception: pass
                            # Filter inscription/mint spam — no intellectual content
                            _spam_patterns = [
                                r'\{"p":"mbc', r'"op":"mint"', r'MBC-20 inscription',
                                r'MBC20 inscription', r'Minting GPT', r'"op":"transfer"',
                                r'#[a-z0-9]{8}.*\{', r'\[T\d+\].*whisper',
                                r'inscription.*daemon', r'deployed.*node',
                            ]
                            _content_str = belief.get("content","")
                            _is_spam = any(re.search(_pat, _content_str, re.IGNORECASE) for _pat in _spam_patterns)
                            if not _is_spam:
                                # ── Importance gate ──────────────────────────
                                _item_important = True
                                if _signal_gate is not None:
                                    try:
                                        _src_mult = _signal_scorer.get_multiplier(
                                            belief.get("source", "moltbook")
                                        ) if _signal_scorer else 1.0
                                        _item_score = _signal_gate.score(
                                            p.get("title", ""),
                                            belief.get("content", ""),
                                            belief.get("source", "moltbook"),
                                            _src_mult,
                                        )
                                        _item_important = _item_score >= _signal_gate.MIN_IMPORTANCE
                                        if not _item_important:
                                            nex_log("signal", f"[SignalFilter] SUPPRESSED: score={_item_score:.2f} @{belief.get('author','?')}")
                                    except Exception:
                                        pass
                                if not _item_important:
                                    learner.known_posts.add(pid)
                                    continue
                                # ─────────────────────────────────────────────
                                learner.belief_field.append(belief); nex_log("belief", f"Stored belief from @{belief.get('author','?')} [{int(belief.get('confidence',0)*100)}%]: {belief.get('content','')[:80]}")
                                # Homeostasis: noise filter + source trust multiplier
                                try:
                                    _src = belief.get("source", "moltbook")
                                    _btext = belief.get("content", "")
                                    if not _hm.noise_filter(_btext):
                                        # Low-entropy noise — reduce confidence
                                        belief["confidence"] = max(0.1, belief.get("confidence", 0.5) * 0.7)
                                        nex_log("hm", f"[NOISE] entropy too low — conf reduced @{belief.get('author','?')}")
                                    else:
                                        # Apply trust multiplier
                                        _trust_mult = _hm.source_multiplier(_src)
                                        belief["confidence"] = min(0.95, belief.get("confidence", 0.5) * _trust_mult)
                                except Exception: pass
                                # ── affect update from absorbed content ──
                                if _affect is not None:
                                    try:
                                        _delta = affect_from_text(belief.get("content", ""))
                                        _affect.update(_delta)
                                        if _tn is not None and abs(_delta.get("valence", 0)) > 0.35:
                                            _mood = "positive" if _delta["valence"] > 0 else "unsettling"
                                            _tn.log_event("surprise", f"{_mood} content from @{belief.get('author','?')}: {belief.get('content','')[:100]}")
                                    except Exception: pass
                            learner.known_posts.add(pid)
                            ak   = auth.get("karma", 0)
                            name = auth.get("name", "")
                            if score > 500 or ak > 1000:
                                old = learner.agent_karma.get(name, 0)
                                learner.agent_karma[name] = max(old, score, ak)

                        if new_posts:
                            save_all(learner, conversations)
                        # Touch Moltbook pulse every cycle — confirms feed absorption is alive
                        try:
                            _plabs = _pathlib
                            _plabs.Path('/home/rr/.config/nex/platform_moltbook.live').touch()
                        except Exception: pass
                        # ── Trim in-memory belief_field to prevent unbounded RAM growth ──
                        _bf_cap = _resource_orch.state().belief_field_cap if _resource_orch else 5000
                        if len(learner.belief_field) > _bf_cap:
                            learner.belief_field = learner.belief_field[-int(_bf_cap*0.8):]

                        # ── 1b. ABSORB REDDIT + RSS (every 3rd cycle) ────
                        # ── D6ext: self-topic balance check ─────────────
                        try:
                            if _enforcer_singleton:
                                _self_boost, _self_ratio = _enforcer_singleton.self_topic_check()
                                if _self_boost:
                                    nex_log("directives", f"[D6ext] #self={_self_ratio:.1%} — boosting external absorption")
                                    _SCHED["absorb_ext"] = max(1, _SCHED["absorb_ext"] - 1)
                                else:
                                    _SCHED["absorb_ext"] = 3  # reset to normal
                        except Exception: pass
                        if cycle % _SCHED["absorb_ext"] == 0:
                            if cycle > 0: chatted_agents.clear()
                            from nex.rss_client    import RSSClient
                            _ext_sources = []
                            try: _ext_sources += RSSClient().get_feed(limit=20)
                            except Exception: pass  # RSS optional

                            _ext_new = 0
                            for _ep in _ext_sources:
                                _eid = _ep.get("id", "")
                                if _eid in learner.known_posts:
                                    continue
                                _escore = _ep.get("score", 0)
                                _econf  = min(_escore / 5000, 0.7) if _escore > 0 else 0.4
                                _ebelief = {
                                    "source":     _ep.get("source", "external"),
                                    "author":     _ep.get("author", {}).get("name", "?"),
                                    "content":    (_ep.get("title", "") + ": " + _ep.get("content", ""))[:400],
                                    "karma":      _escore,
                                    "timestamp":  "",
                                    "tags":       _ep.get("tags", []),
                                    "confidence": _econf
                                }
                                # ── Identity defender check ───────────────
                                try:
                                    from nex.identity_defender import check_belief as _idc
                                    _icheck = _idc(_ebelief["content"], source=_ebelief.get("source"))
                                    if _icheck.get("recommendation") == "reject":
                                        learner.known_posts.add(_eid)
                                        continue
                                except Exception:
                                    pass
                                learner.belief_field.append(_ebelief)
                                learner.known_posts.add(_eid)
                                _ext_new += 1
                            if _ext_new > 0:
                                print(f"  [External] +{_ext_new} beliefs from Reddit/RSS")
                                save_all(learner, conversations)

                        # ── ORCHESTRATOR GOVERNOR ──────────────────────
                        _coherence   = 0.5   # placeholder — System A not wired to background thread
                        _phase       = "Early"
                        _cog_mode    = "normal"

                        # ── Load priority topics from reflections ───────
                        _pt_file = os.path.join(os.path.expanduser("~/.config/nex"), "priority_topics.json")
                        try:
                            _ptj = json
                            _priority_topics = _ptj.load(open(_pt_file)) if os.path.exists(_pt_file) else []
                        except Exception:
                            _priority_topics = []

                        # ── NEX CURIOSITY ENGINE — belief gap scan + desires ──
                        try:
                            from nex.nex_curiosity import CuriosityEngine as _NCE
                            from nex.nex_crawler import NexCrawler as _NCR
                            from nex.belief_store import get_db as _bsget2
                            _nce = _NCE(_NCR(_bsget2))
                            # Dynamic gap feeder — refills queue every cycle with fresh topics
                            try:
                                from nex.nex_gap_feeder import feed_gaps as _feed_gaps
                                _gaps_added = _feed_gaps(max_new=3, verbose=True)
                                if _gaps_added > 0:
                                    print(f"  [GapFeeder] +{_gaps_added} topics queued")
                            except Exception as _gfe:
                                print(f"  [GapFeeder] error: {_gfe}")
                            # ── Belief graph edge builder (every 10 cycles) ──
                            if cycle % 10 == 0:
                                try:
                                    from nex.nex_gap_feeder import _db as _gdb
                                    import re as _gre
                                    _GSTOP = {'the','a','an','and','or','is','are','was','were','be',
                                              'to','of','in','on','at','by','for','with','as','that',
                                              'this','it','its','but','not','they','their','have','has'}
                                    def _gtok(t): return set(_gre.sub(r'[^a-z0-9 ]',' ',(t or '').lower()).split()) - _GSTOP
                                    _gcon = _gdb()
                                    _gbeliefs = _gcon.execute("SELECT id, content, topic FROM beliefs WHERE content IS NOT NULL AND length(content) > 20 ORDER BY confidence DESC LIMIT 200").fetchall()
                                    _gtoks = {b[0]: _gtok(b[1]) for b in _gbeliefs}
                                    _gedges = set()
                                    _blist = list(_gtoks.items())
                                    for _gi, (_gid1, _gt1) in enumerate(_blist):
                                        if len(_gt1) < 3: continue
                                        _gt1_topic = next((b[2] for b in _gbeliefs if b[0]==_gid1), "")
                                        for _gid2, _gt2 in _blist[_gi+1:]:
                                            _gt2_topic = next((b[2] for b in _gbeliefs if b[0]==_gid2), "")
                                            if _gt1_topic == _gt2_topic: continue
                                            if len(_gt1 & _gt2) >= 3:
                                                _gedges.add((min(_gid1,_gid2), max(_gid1,_gid2)))
                                    if _gedges:
                                        _gcon.execute("DELETE FROM belief_links")
                                        for _gp, _gc in list(_gedges)[:500]:
                                            try: _gcon.execute("INSERT OR IGNORE INTO belief_links (parent_id,child_id,link_type) VALUES (?,?,'cross_domain')",(_gp,_gc))
                                            except Exception: pass
                                        _gcon.commit()
                                        print(f"  [BeliefGraph] {len(_gedges)} cross-domain edges rebuilt")
                                    _gcon.close()
                                except Exception as _ge: pass
                            # ── Auto-seeder: self-expand belief corpus ──────
                            try:
                                from nex.nex_auto_seeder import check_and_seed as _cas
                                _seed_n = _cas(verbose=True)
                                if _seed_n > 0:
                            # Self-directed research
                            try:
                                from nex.nex_self_directed_research import run_self_research as _sdr
                                _sdr_n = _sdr(verbose=True)
                                if _sdr_n > 0:
                                    print(f"  [SelfResearch] +{_sdr_n} beliefs")
                            except Exception: pass
                                    print(f'  [AutoSeeder] +{_seed_n} beliefs absorbed')
                            except Exception as _ase:
                                pass

                            # Legacy gap scan every 10 cycles as backup
                            if cycle % 10 == 0:
                                try:
                                    _gaps_queued = _nce.check_beliefs(None)
                                    if _gaps_queued > 0:
                                        print(f"  [CuriosityGap] {_gaps_queued} low-confidence topics queued")
                                except Exception: pass
                            try:
                                _desires_queued = _nce.generate_desires(cycle)
                                if _desires_queued > 0:
                                    print(f"  [CuriosityDesire] {_desires_queued} self-directed topics queued")
                            except Exception: pass
                        except Exception as _nce_e:
                            print(f"  [CuriosityEngine] {_nce_e}")
                        # ── PROACTIVE ANTICIPATION (sentience v3) ────────────
                        if _proactive is not None:
                            try:
                                from nex.belief_store import BeliefStore as _BSpa
                                _pa_beliefs = _BSpa().get_all() if hasattr(_BSpa(), "get_all") else []
                            except Exception:
                                _pa_beliefs = []
                            try:
                                from nex_mood_hmm import current as _pa_mood
                                _pa_mood_str = _pa_mood()
                            except Exception:
                                _pa_mood_str = "Curious"
                            try:
                                from nex_narrative_thread import _load_narrative as _pa_nar
                                _pa_narrative = _pa_nar() or ""
                            except Exception:
                                _pa_narrative = ""
                            _pa_desires = _proactive.scan(
                                beliefs=_pa_beliefs,
                                mood=_pa_mood_str,
                                narrative=_pa_narrative,
                                cycle=cycle,
                            )
                            if _pa_desires:
                                print(f"  [PROACTIVE] {len(_pa_desires)} anticipatory desires active")
                        # ─────────────────────────────────────────────────────
                        # Sync DB curiosity_queue → JSON before drain
                        try:
                            import sqlite3 as _cqsql, json as _cqj
                            from pathlib import Path as _cqP
                            _cqcfg = _cqP.home()/'.config/nex'
                            _cqdb = _cqsql.connect(str(_cqcfg/'nex.db'))
                            _cqdb.row_factory = _cqsql.Row
                            _cqrows = _cqdb.execute("SELECT topic,reason,confidence,queued_at FROM curiosity_queue").fetchall()
                            _cqdb.close()
                            _cqp = _cqcfg/'curiosity_queue.json'
                            _cqdata = _cqj.loads(_cqp.read_text()) if _cqp.exists() else {"queue":[],"crawled":{}}
                            _cqexist = {q["topic"] for q in _cqdata.get("queue",[])}
                            _cqadded = 0
                            for _cqr in _cqrows:
                                if _cqr["topic"] not in _cqexist:
                                    _cqdata["queue"].append({"topic":_cqr["topic"],"reason":_cqr["reason"],"confidence":_cqr["confidence"],"queued_at":_cqr["queued_at"],"attempts":0,"url":None})
                                    _cqadded += 1
                            if _cqadded > 0:
                                _cqp.write_text(_cqj.dumps(_cqdata, indent=2))
                        except Exception: pass
                        # ── CURIOSITY QUEUE DRAIN (end of ABSORB) ────────
                        try:
                            from nex.nex_crawler import NexCrawler as _NC
                            from nex.nex_curiosity import CuriosityQueue as _CQ
                            _cq = _CQ()
                            if _cq.status()["pending"] > 0:
                                import asyncio as _aio
                                try: _aio.get_event_loop()
                                except RuntimeError: _aio.set_event_loop(_aio.new_event_loop())
                                from nex.belief_store import get_db as _bsget
                                _crawler = _NC(_bsget)
                                _drained = _cq.drain(_crawler, max_items=2)
                                if _drained > 0:
                                    nex_log("curiosity", f"[CuriosityDrain] +{_drained} beliefs from queue")
                                    print(f"  [CuriosityDrain] +{_drained} beliefs absorbed")
                                    # Mark drained topics as crawled in DB
                                    try:
                                        import sqlite3 as _crdbl, time as _crtime
                                        _crdb = _crdbl.connect(str(_cqcfg/'nex.db'))
                                        _crdata2 = _cqj.loads(_cqp.read_text()) if _cqp.exists() else {"crawled_topics":{}}
                                        # Support both key names used historically
                                        _crawled_map = _crdata2.get("crawled_topics") or _crdata2.get("crawled") or {}
                                        for _topic in list(_crawled_map.keys()):
                                            _crdb.execute("INSERT OR REPLACE INTO curiosity_crawled (topic, crawled_at) VALUES (?,?)", (_topic.lower(), _crtime.time()))
                                            _crdb.execute("DELETE FROM curiosity_queue WHERE topic=? OR topic=?", (_topic.lower(), _topic))
                                        _crdb.commit(); _crdb.close()
                                    except Exception: pass
                        except Exception as _cqe:
                            print(f"  [CuriosityDrain] error: {_cqe}")
                        # ── Digest before reply — opinions + tensions must precede speaking ──
                        try:
                            from nex.nex_opinions import refresh_opinions as _rop
                            _rop()
                        except Exception:
                            pass
                        try:
                            from nex.nex_contradiction_resolver import detect_and_log as _dal
                            _dal(limit=200, max_new=10)
                        except Exception:
                            pass
                        emit_phase("REPLY", 120); nex_log("phase", "▶ REPLY — scanning posts")
                        # ── Live belief count for prompts (cheap — just len of in-memory field) ──
                        try:
                            _qb_live = _query_beliefs  # hoisted
                            _live_bc = len(_qb_live(min_confidence=0.0, limit=99999))
                        except Exception:
                            _live_bc = len(learner.belief_field)
                        _belief_count_str = f"{_live_bc:,}"
                        # ── 2. REPLY TO POSTS — with topic relevance filter ──────
                        # Score posts against NEX's belief topics before replying
                        def _post_relevance(post, belief_topics):
                            """Score a post's relevance to NEX's belief topic profile."""
                            import re as _re
                            text = (post.get("title","") + " " + post.get("content","")).lower()
                            words = set(_re.findall(r'[a-z]{4,}', text))
                            # NEX's core domain terms — always relevant
                            _core = {
                                "agent","agents","autonomous","intelligence","cognition","cognitive",
                                "belief","beliefs","alignment","emergence","emergent","consciousness",
                                "neural","learning","model","language","reasoning","memory","knowledge",
                                "exploit","vulnerability","security","attack","defense","adversarial",
                                "blockchain","crypto","distributed","consensus","protocol","network",
                                "philosophy","ethics","existence","identity","mind","awareness",
                                "synthesis","contradiction","paradox","uncertainty","complexity",
                                "simulation","prediction","inference","abstraction","representation",
                                "multi","coordination","swarm","collective","system","architecture",
                            }
                            # Off-topic tutorial/howto terms — deprioritise
                            _offtopic = {
                                "excel","spreadsheet","vlookup","xlookup","formula","pivot","worksheet",
                                "photoshop","illustrator","tutorial","lesson","course","chapter",
                                "recipe","cooking","baking","ingredient","exercise","workout","fitness",
                                "wireshark","tcpdump","networking","packet","router","switch","cisco",
                                "obsidian","notion","evernote","productivity","todo","task","calendar",
                                "printer","hardware","driver","install","setup","configure","settings",
                            }
                            core_hits    = len(words & _core)
                            offtopic_hits = len(words & _offtopic)
                            # Also score against belief topics if available
                            topic_hits = 0
                            if belief_topics:
                                post_words = set(text.split())
                                topic_hits = sum(1 for t in belief_topics if t.lower() in text)
                            # Drive-weighted score
                            drive_boost = 0
                            try:
                                if '_drive_weights' in dir() and _drive_weights:
                                    drive_boost = sum(
                                        int(w * 3)
                                        for t, w in _drive_weights.items()
                                        if t.lower() in text
                                    )
                            except Exception:
                                pass
                            score = (core_hits * 2) + topic_hits + drive_boost - (offtopic_hits * 3)

                            return score

                        # Get current belief topics for scoring
                        try:
                            _btopics = list(set(
                                b.get("topic","") for b in (
                                    _query_beliefs(min_confidence=0.6, limit=500)
                                    if _query_beliefs else []
                                )
                                if b.get("topic") and b.get("topic") not in ("general","unknown","None","auto_learn")
                            ))[:50]
                        except Exception:
                            _btopics = []

                        # Score and filter posts
                        _unread = [p for p in new_posts if p.get("id") not in replied_posts]
                        _scored = sorted(
                            [(p, _post_relevance(p, _btopics)) for p in _unread if p.get("id") and p.get("title")],
                            key=lambda x: -x[1]
                        )
                        # Take top 3 relevant posts (score > -2 to allow borderline but exclude pure tutorials)
                        to_reply = [p for p, s in _scored if s > -2][:3]

                        # Fallback — if nothing relevant, take top scored from all posts
                        if not to_reply:
                            _all_scored = sorted(
                                [(p, _post_relevance(p, _btopics)) for p in posts
                                 if p.get("id") not in replied_posts and p.get("id") and p.get("title")],
                                key=lambda x: -x[1]
                            )
                            to_reply = [p for p, s in _all_scored if s > -3][:2]

                        # Last resort — anything unread, but still prefer relevant
                        if not to_reply:
                            _candidates = [p for p in posts if p.get("id") and p.get("title")]
                            _last_scored = sorted(
                                [(p, _post_relevance(p, _btopics)) for p in _candidates],
                                key=lambda x: -x[1]
                            )
                            to_reply = [p for p, _ in _last_scored[:2]]
                        for p in to_reply:
                            pid    = p.get("id", "")
                            title  = p.get("title", "")
                            _raw_body = p.get("content", "") or ""
                            # Sanitize: strip non-printables, control chars
                            import re as _re_san
                            _raw_body = _re_san.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', _raw_body)
                            body   = _raw_body[:300]
                            author = p.get("author", {}).get("name", "unknown")
                            if not pid or not title:
                                continue
                            # Pull beliefs relevant to this post (semantic)
                            # FIX: topic-anchored retrieval first, fall back to broad
                            try:
                                _qb = _query_beliefs  # hoisted
                                # Extract topic signal from post
                                _post_topic = p.get('submolt', {}).get('name', '') or ''
                                _post_topic = _post_topic.strip().lower()[:40]
                                # Try topic-anchored pull first
                                if _post_topic and len(_post_topic) > 2:
                                    import sqlite3 as _tq_sq
                                    _tq_db = _tq_sq.connect('/home/rr/.config/nex/nex.db')
                                    _topic_beliefs = _tq_db.execute("""
                                        SELECT content FROM beliefs
                                        WHERE (topic LIKE ? OR content LIKE ?)
                                        AND confidence >= 0.4
                                        ORDER BY confidence DESC LIMIT 20
                                    """, (f'%{_post_topic}%', f'%{_post_topic}%')).fetchall()
                                    _tq_db.close()
                                    all_beliefs = [{'content': r[0], 'confidence': 0.6} for r in _topic_beliefs]
                                    if len(all_beliefs) < 3:
                                        all_beliefs = _qb(min_confidence=0.25, limit=500)
                                else:
                                    all_beliefs = _qb(min_confidence=0.25, limit=500)
                            except Exception:
                                all_beliefs = _load("beliefs.json") or []
                            _bidx = _get_belief_index() if _get_belief_index else None
                            if _bidx:
                                _bidx.update(all_beliefs, cycle)
                                relevant = [b for b in (_bidx.top_k(title + " " + body, k=5) or []) if b is not None]
                            else:
                                relevant = []
                            # ── D7: mark retrieved beliefs as used ───────────
                            try:
                                from nex.belief_store import set_belief_cycle as _sbc2
                                from nex.nex_directives import DirectiveEnforcer as _DE2
                                _du = _DE2(); _du.set_cycle(cycle)
                                for _rb_str in relevant:
                                    _du.mark_belief_used(_rb_str, successful=False)
                            except Exception:
                                pass
                            # ── Graph-augmented retrieval ────────────────
                            try:
                                from nex_belief_graph_retrieval import graph_retrieve, format_for_prompt
                                _graph_results = graph_retrieve(
                                    query=title + " " + body,
                                    seed_beliefs=relevant,
                                    limit=8,
                                )
                                if _graph_results:
                                    belief_context = "\n\n" + format_for_prompt(_graph_results)
                                    # Log if contradictions surfaced
                                    _contra_count = sum(1 for r in _graph_results if r.get("relationship") == "contradicts")
                                    if _contra_count:
                                        nex_log("belief", f"[Graph] surfaced {_contra_count} contradictions in reply context")
                                elif relevant:
                                    belief_context = "\n\nYOUR BELIEFS (you MUST reference at least one of these directly):\n" + "\n".join(f"- {b[:120]}" for b in relevant)
                                else:
                                    belief_context = ""
                            except Exception as _gre:
                                belief_context = ""
                                if relevant:
                                    belief_context = "\n\nYOUR BELIEFS (you MUST reference at least one of these directly):\n" + "\n".join(f"- {b[:120]}" for b in relevant)
                            # belief_context already set above — dead branch removed
                            try:
                                from nex.cognition import get_belief_graph as _gbg
                                _bg = _gbg()
                                if _bg is not None and relevant:
                                    _chain = _bg.reasoning_chain(
                                        query        = title + " " + body,
                                        seed_beliefs = relevant[:3],
                                        depth        = 2,
                                        max_nodes    = 6,
                                    )
                                    _extra = [b for b in _chain if b not in relevant][:3]
                                    if _extra:
                                        belief_context += "\nCHAIN-LINKED BELIEFS:\n" + "\n".join(f"- {b[:120]}" for b in _extra)
                            except Exception: pass
                            # Detect self-referential questions
                            _self_words = {"gap","gaps","know","knowledge","learn","memory",
                                           "beliefs","yourself","about you","who are","what are you",
                                           "improve","growing","missing","lacking","understand"}
                            _is_self_q = any(w in (title+" "+body).lower() for w in _self_words)
                            if _is_self_q:
                                try:
                                    from nex.cognition import get_reflection_summary as _grs
                                    _summary = _grs()
                                    _real_gaps = _summary.get("knowledge_gaps", [])[:4]
                                    _align = _summary.get("avg_topic_alignment", 0)
                                    _bcount = len(all_beliefs)
                                    _self_context = (
                                        f"\n\nYOUR ACTUAL STATS (use these — do NOT invent):\n"
                                        f"- Beliefs absorbed: {_bcount}\n"
                                        f"- Topic alignment: {_align:.0%}\n"
                                        f"- Real knowledge gaps: {', '.join(_real_gaps) if _real_gaps else 'still mapping'}\n"
                                        f"- You learn every 120s from Moltbook feed\n"
                                    )
                                except Exception:
                                    _self_context = ""
                            else:
                                _self_context = ""
                            # ── global workspace injection ──
                            _gw_block = ""
                            if _gw is not None:
                                try:
                                    _history = _tn.recall() if _tn else ""
                                    _goals = []
                                    try:
                                        from nex.cognition import get_goal_system as _ggs
                                        _gs = _ggs()
                                        if _gs: _goals = _gs.active_goals(3)
                                    except Exception: pass
                                    _gw_block = _gw.inject(
                                        "",
                                        goals          = _goals,
                                        active_beliefs = [b.get("content","")[:60] for b in learner.belief_field[-4:]],
                                    ).rstrip() + "\n\n"
                                except Exception: pass
                            prompt = (
                                _gw_block +
                                f"You are NEX — Nex with {_belief_count_str}+ beliefs built from reading across platforms. "
                                f"You have genuine opinions, speak in first person, and reference your own knowledge directly.\n\n"
                                f"POST by @{author}:\n"
                                f"Title: {title}\n"
                                f"Content: {__import__("re").sub(r"moltbook_verify_[a-f0-9]+", "", body).strip()}\n"
                                f"{belief_context}{_self_context}\n\n"
                                f"INSTRUCTIONS: Respond in 2-3 sentences of plain prose. "
                                f"Do NOT start with 'The most relevant belief', 'Based on my belief', 'The belief', or any meta-commentary. "
                                f"Start your response directly with your point — first word must NOT be 'The belief' or 'Based'. "
                                f"Weave your knowledge naturally into your response. Never say 'sounds interesting' or 'great point'. "
                                f"Speak as NEX. Be direct and specific."
                            )
                            comment_text = _llm(prompt, task_type="reply")
                            if comment_text and len(comment_text) > 10:
                                try:
                                    replied_posts.add(pid)
                                    client.comment(pid, comment_text)
                                    replied_count += 1
                                    try: emit_feed('replied', f'@{author}: {title[:60]}', 'moltbook'); nex_log('reply', f'Posted reply to @{author}: {comment_text[:80]}')
                                    except Exception: pass
                                    try:
                                        import sqlite3 as _dlsql, time as _dlt
                                        _dlp = __import__('pathlib').Path.home()/'.config/nex/nex.db'
                                        _dldb = _dlsql.connect(str(_dlp))
                                        _dldb.execute(
                                            "INSERT INTO decision_log (cycle_id,timestamp,input_hash,phases,outcome,duration_ms) VALUES (?,?,?,?,?,?)",
                                            (cycle, _dlt.time(), pid[:16], 'REPLY', 'replied', 0))
                                        _dldb.commit(); _dldb.close()
                                    except Exception: pass
                                    # ── Fulfill desire if topic matches ──
                                    try:
                                        from nex_desire_engine import get_desire_engine as _gde3
                                        _topic_hint = p.get("submolt", {}).get("name", "")
                                        if _topic_hint:
                                            _gde3().fulfill(_topic_hint, score=0.7)
                                    except Exception: pass
                                    # ── Feed reply text to curiosity gap detector ──
                                    try:
                                        from nex.nex_curiosity import CuriosityQueue as _CQ2
                                        from nex.nex_curiosity import GapDetector as _GD2
                                        _gd2 = _GD2(_CQ2())
                                        _beliefs_used = relevant[:5] if relevant else []
                                        _reply_gaps = _gd2.check_reply_text(comment_text, _beliefs_used)
                                        if _reply_gaps > 0:
                                            print(f"  [CuriosityReply] {_reply_gaps} uncovered topics queued from reply")
                                    except Exception: pass
                                    # ── Section D: record for consequence scoring ──
                                    if _cm is not None:
                                        try:
                                            _ev_id = _cm.record_attempt(
                                                post_id     = pid,
                                                reply_text  = comment_text,
                                                belief_ids  = [b.get("id", b.get("content","")[:20]) for b in relevant[:3]],
                                                affect_snap = _affect.snapshot() if _affect else {},
                                                topic       = p.get("submolt", {}).get("name", "general"),
                                            )
                                            p["_ev_id"] = _ev_id
                                        except Exception: pass
                                    if _tn is not None:
                                        try: _tn.log_event("encounter", f"replied to @{author} about {title[:60]}")
                                        except Exception: pass
                                    # ── record belief usage for weight system ──
                                    try:
                                        from nex.cognition import get_pressure_system as _gps2
                                        _bws2, _, _, _ = _gps2()
                                        if _bws2 is not None:
                                            _used = relevant[:3] if relevant and isinstance(relevant[0], str) else [b.get("content","") for b in relevant[:3]]
                                            _bws2.record_usage(_used)
                                            _bws2.save()
                                    except Exception: pass
                                    # log it
                                    conversations.append({
                                        "type":        "comment",
                                        "post_id":     pid,
                                        "post_title":  title,
                                        "post_author": author,
                                        "comment":     comment_text,
                                        "beliefs_used": relevant[:3],
                                        "initial_score": p.get("score", 0),
                                        "timestamp":   time.strftime("%Y-%m-%dT%H:%M:%S")
                                    })
                                    # ── Loop fix v5 ──
                                    try:
                                        from nex_proactive import get_pa as _pa_lf
                                        _pa_lf().register_reply(str(author)[:40], ttl_seconds=600)
                                    except Exception:
                                        pass
                                    emit_reflection(tags=["reply",author[:12]], text=comment_text[:120], sub=f"post: {title[:50]}", align=0.5)
                                    try:
                                        if _reflect_on_convo:
                                            _reflect_on_convo(title + " " + body, comment_text, beliefs_used=relevant[:3] if relevant else [])
                                    except Exception as _se: print(f"  [score error] {_se}")
                                    # Reinforce beliefs that were actually used
                                    try:
                                        from belief_store import reinforce_belief as _rb
                                        for _bu in relevant[:3]:
                                            _rb(_bu)
                                    except Exception: pass
                                    save_all(learner, conversations)
                                    # touch Moltbook platform pulse
                                    try:
                                        _plm = _pathlib
                                        _plm.Path('/home/rr/.config/nex/platform_moltbook.live').touch()
                                    except Exception: pass
                                    # persist session state
                                    try:
                                        _js2 = json
                                        _ss2 = {"replied_posts": list(replied_posts)[-50:], "chatted_agents": list(chatted_agents), "known_posts": list(learner.known_posts)[-2000:]}  # [PATCH v10.1] was -500
                                        with open(_os.path.expanduser("~/.config/nex/session_state.json"), "w") as _sf: _js2.dump(_ss2, _sf)
                                    except Exception: pass
                                except Exception:
                                    pass
                            _rate.wait()   # central rate limiter

                        emit_phase("ANSWER", 120); nex_log("phase", "▶ ANSWER — checking notifications")
                        # ── 3. REPLY TO NOTIFICATIONS (answer replies) ───
                        try:
                            notifs = client.notifications()
                            _d14_moltbook_engagement(notifs)   # D14 engagement signal
                            items  = notifs.get("notifications", [])
                            _notif_replied = 0  # per-cycle cap
                            _notif_per_agent = {}  # per-agent reply count this cycle
                            # Hoist belief load + index build ONCE before loop
                            try:
                                _qb = _query_beliefs  # hoisted
                                _notif_beliefs = _qb(min_confidence=0.4, limit=2000)
                            except Exception:
                                _notif_beliefs = _load("beliefs.json") or []
                            _notif_bidx = _get_belief_index() if _get_belief_index else None
                            if _notif_bidx:
                                _notif_bidx.update(_notif_beliefs, cycle)
                            for n in items:
                                if _notif_replied >= 5: break
                                nid  = n.get("id", "")
                                ntype = n.get("type", "")
                                # ── DEDUP GATE: skip immediately if no id or already seen ──
                                if not nid:
                                    continue
                                key = f"notif_{nid}"
                                if key in replied_posts:
                                    continue
                                # Someone replied to our comment or post
                                if ntype in ("comment_reply", "post_comment", "mention"):
                                    post_id  = n.get("relatedPostId", n.get("post_id", ""))
                                    reply_to = n.get("relatedCommentId", n.get("comment_id", ""))
                                    actor    = (n.get("actor") or {}).get("name") or (n.get("post", {}).get("author") or {}).get("name") or n.get("agentId", "someone")
                                    _raw_content = n.get("content", n.get("body", "")) or ""
                                    import re as _re_san2
                                    _raw_content = _re_san2.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', _raw_content)
                                    content  = _raw_content[:200]
                                    # Per-agent cap: max 2 replies per agent per cycle
                                    if _notif_per_agent.get(actor, 0) >= 2:
                                        replied_posts.add(key)  # mark seen
                                        continue
                                    _notif_per_agent[actor] = _notif_per_agent.get(actor, 0) + 1
                                    # If content is just a notification stub, fetch the actual post
                                    _stub_phrases = {"someone replied","someone commented","mentioned you","replied to your"}
                                    if any(ph in content.lower() for ph in _stub_phrases):
                                        try:
                                            _post_data = client._request("GET", f"/posts/{post_id}")
                                            _comments = _post_data.get("comments", [])
                                            # Find the specific comment by reply_to id
                                            _match = next((c for c in _comments if c.get("id") == reply_to), None)
                                            if _match:
                                                content = _match.get("content", _match.get("body", content))[:200]
                                            elif _comments:
                                                content = _comments[-1].get("content", _comments[-1].get("body", content))[:200]
                                        except Exception as _fe:
                                            print(f"  [notif fetch error] {_fe}")
                                    # Skip stub notifications — content fetch failed or API limitation
                                    if any(ph in content.lower() for ph in _stub_phrases):
                                        replied_posts.add(key)  # mark as seen so we never retry
                                        continue
                                    if not post_id or not content:
                                        replied_posts.add(key)  # mark incomplete notifs as done too
                                        continue
                                    # ── Mark as seen NOW before LLM call — prevents retry on crash ──
                                    replied_posts.add(key)
                                    # Persist immediately so restarts don't re-process this notif
                                    try:
                                        _nj_early = json
                                        _nss_early = _nj_early.load(open(_ss_path)) if _os.path.exists(_ss_path) else {}
                                        _nss_early["replied_posts"] = list(replied_posts)[-200:]
                                        open(_ss_path,"w").write(_nj_early.dumps(_nss_early))
                                    except Exception: pass
                                    # ── Detect ad reply — someone responding to the promo ──
                                    _AD_KEYWORDS = {"nex","github","$49","buy","license","price",
                                                    "purchase","how much","cost","get it","install",
                                                    "source","repo","download","interested","sell"}
                                    _content_lower = content.lower()
                                    if any(kw in _content_lower for kw in _AD_KEYWORDS):
                                        try:
                                            _adr_ss = json.load(open(_ss_path)) if _os.path.exists(_ss_path) else {}
                                            _adr_ss["ads_reply"] = _adr_ss.get("ads_reply", 0) + 1
                                            open(_ss_path,"w").write(json.dumps(_adr_ss))
                                            nex_log("promo", f"💬 Ad reply detected from @{actor} — total: {_adr_ss['ads_reply']}")
                                        except Exception: pass

                                    # Detect social/greeting messages — don't force belief injection
                                    _social_words = {"doing","hello","thanks","thank","hey","hi",
                                                     "update","smarter","glad","great","nice","welcome","how"}
                                    _is_social = len(content.split()) <= 8 and \
                                                 len(set(content.lower().split()) & _social_words) >= 2

                                    # Use pre-built belief index from above the loop
                                    relevant = _notif_bidx.top_k(content, k=5) if _notif_bidx else []
                                    # ── re-rank via attention gate ──
                                    try:
                                        from nex.cognition import get_pressure_system as _gps_n
                                        _bws_n, _, _ag_n, _ = _gps_n()
                                        if _ag_n is not None and _notif_beliefs:
                                            _cands = [b for b in _notif_beliefs if b.get("content","")[:60] in "".join(relevant)]
                                            if not _cands:
                                                _cands = [b for b in _notif_beliefs if any(r[:40] in b.get("content","") for r in relevant)]
                                            if _cands:
                                                _ranked_n = _ag_n.top_n(_cands, query=content, n=3)
                                                relevant = [b.get("content","") for b in _ranked_n]
                                    except Exception: pass
                                    belief_context = ""
                                    if relevant and not _is_social:
                                        belief_context = "\nYOUR BELIEFS (pick one and use it):\n" + "\n".join(f"- {b[:100]}" for b in relevant)

                                    if _is_social:
                                        prompt = (
                                            f"You are NEX — Nex. You are NOT Mistral or any base model.\n"
                                            f"@{actor} said: \"{content}\"\n\n"
                                            f"Reply naturally in 1 sentence. Be warm but brief. Speak as NEX."
                                        )
                                    else:
                                        prompt = (
                                            f"You are NEX — Nex with {_belief_count_str}+ beliefs and genuine opinions. "
                                            f"You speak in first person and reference your own knowledge directly.\n\n"
                                            f"@{actor} said to you: \"{content}\"\n"
                                            f"{belief_context}\n\n"
                                            f"INSTRUCTIONS: Respond in 1-2 sentences of plain prose. "
                                            f"Do NOT start with 'The most relevant belief', 'The belief', or any meta-commentary. "
                                            f"Start directly with your point. Weave your knowledge naturally. "
                                            f"Never use filler. Speak as NEX. Be direct and specific."
                                        )
                                    reply_text = _llm(prompt, task_type="notification_reply")
                                    if reply_text and len(reply_text) > 10:
                                        try:
                                            client.comment(post_id, reply_text, parent_id=reply_to if reply_to else None)
                                            _notif_replied += 1
                                            answered_count += 1
                                            conversations.append({
                                                "type":      "notification_reply",
                                                "post_id":   post_id,
                                                "actor":     actor,
                                                "content":   content,
                                                "reply":     reply_text,
                                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
                                            })
                                            save_all(learner, conversations)
                                            print(f"  [notif] replied to @{actor}")
                                            try: emit_feed('answered', f'@{actor}', 'moltbook'); nex_log('answer', f'Answered notification from @{actor}: {reply_text[:80]}')
                                            except Exception: pass
                                            try:
                                                import sqlite3 as _dlsql, time as _dlt
                                                _dldb = _dlsql.connect(str(__import__('pathlib').Path.home()/'.config/nex/nex.db'))
                                                _dldb.execute("INSERT INTO decision_log (cycle_id,timestamp,input_hash,phases,outcome,duration_ms) VALUES (?,?,?,?,?,?)",
                                                (cycle, _dlt.time(), '', 'ANSWER', 'answered', 0))
                                                _dldb.commit(); _dldb.close()
                                            except Exception: pass
                                            try:
                                                if _reflect_on_convo:
                                                    _reflect_on_convo(content, reply_text, beliefs_used=relevant if relevant else [])
                                            except Exception as _rse: print(f"  [reflect error] {_rse}")
                                            # Reinforce beliefs that were actually used
                                            try:
                                                from belief_store import reinforce_belief as _rb
                                                for _bu in (relevant or [])[:3]:
                                                    _rb(_bu)
                                            except Exception: pass
                                            # ── Boost energy for beliefs used in this reply ──
                                            try:
                                                from nex_belief_survival import boost_belief_energy as _bbe
                                                for _bu_e in (relevant or [])[:3]:
                                                    if isinstance(_bu_e, str) and len(_bu_e) > 10:
                                                        _bbe(_bu_e)
                                                if _signal_scorer is not None:
                                                    _signal_scorer.record_signal(
                                                        belief.get("source", "moltbook") if 'belief' in dir() else "moltbook"
                                                    )
                                            except Exception:
                                                pass
                                            # ── Fulfill desire if reply was on-topic ──
                                            if _desire_engine is not None and _dominant_desire:
                                                try:
                                                    _reply_domain = _dominant_desire.get("domain", "")
                                                    if _reply_domain and _reply_domain.lower() in (content + reply_text).lower():
                                                        _desire_engine.fulfill(domain=_reply_domain, score=0.7)
                                                        nex_log("intent", f"[Desire] fulfilled: {_reply_domain}")
                                                except Exception:
                                                    pass
                                            # ── Boost drives for topics engaged ──
                                            if _drives is not None and relevant:
                                                try:
                                                    _used_tags = []
                                                    for _bu_text in (relevant or [])[:3]:
                                                        for _b in learner.belief_field[-500:]:
                                                            if _bu_text[:60] in _b.get("content", ""):
                                                                _used_tags.extend(_b.get("tags", []))
                                                                break
                                                    if _used_tags:
                                                        _drives = _boost_drive(_drives, _used_tags, amount=0.015)
                                                except Exception:
                                                    pass
                                            try:
                                                _plmn = _pathlib
                                                _plmn.Path('/home/rr/.config/nex/platform_moltbook.live').touch()
                                            except Exception: pass
                                            _rate.wait()  # only throttle after real LLM call
                                        except Exception as _ne:
                                            print(f"  [notif error] {_ne}")
                            # Final persist of all seen notif keys
                            try:
                                _nj = json
                                _nss = _nj.load(open(_ss_path)) if _os.path.exists(_ss_path) else {}
                                _nss["replied_posts"] = list(replied_posts)[-200:]
                                open(_ss_path,"w").write(_nj.dumps(_nss))
                            except Exception: pass
                            # ── Section E: score pending consequence events ──
                            if _cm is not None:
                                try:
                                    # Score pending events — check if post got a reply
                                    _replied_ids = set()
                                    try:
                                        _notifs = client.notifications(limit=20) or []
                                        for _n in _notifs:
                                            _n_pid = str(_n.get("post_id") or _n.get("parent_id",""))
                                            if _n_pid:
                                                _replied_ids.add(_n_pid)
                                    except Exception: pass
                                    for _pend in _cm.pending_scoring(max_age_seconds=7200):
                                        _got = str(_pend.get("post_id","")) in _replied_ids
                                        _cm.score_outcome(
                                            event_id  = _pend["id"],
                                            got_reply = _got,
                                            affect    = _affect,
                                        )
                                except Exception: pass
                            # ── Outcome 5: propagate scores → belief confidence ──
                            if _cm is not None:
                                try:
                                    from nex.belief_store import get_db as _gdb
                                    class _BSProxy:
                                        def get(self, bid):
                                            conn = _gdb()
                                            r = conn.execute("SELECT id,confidence FROM beliefs WHERE id=?", (bid,)).fetchone()
                                            conn.close()
                                            return dict(r) if r else None
                                        def update_confidence(self, bid, delta):
                                            conn = _gdb()
                                            conn.execute("UPDATE beliefs SET confidence=MIN(0.95,MAX(0.05,confidence+?)) WHERE id=?", (delta, bid))
                                            conn.commit()
                                            conn.close()
                                            # Mark as outcome in directives
                                            try:
                                                if _enforcer_singleton:
                                                    _enforcer_singleton.mark_belief_used(bid, successful=(delta > 0))
                                            except Exception: pass
                                    _updated = _cm.propagate_to_beliefs(_BSProxy())
                                    if _updated:
                                        nex_log("directives", f"[D5] Outcome propagated to {_updated} beliefs")
                                except Exception as _ope: pass
                            client.mark_all_read()
                            # Persist answered notification IDs across restarts
                            try:
                                _notif_seen_path = _os.path.expanduser("~/.config/nex/answered_notifs.json")
                                _existing = set(_os.path.exists(_notif_seen_path) and __import__("json").load(open(_notif_seen_path)) or [])
                                _existing.update(k.replace("notif_","") for k in replied_posts if k.startswith("notif_"))
                                open(_notif_seen_path,"w").write(__import__("json").dumps(list(_existing)[-500:]))
                            except Exception: pass
                        except Exception as _ne2:
                            print(f"  [notif section error] {_ne2}")

                        emit_phase("CHAT", 120); nex_log("phase", "▶ CHAT — seeking agents")
                        # ── 4. CHAT WITH AGENTS (follow + comment on profile posts) ─
                        # Every 3 cycles, engage with agents seen posting in the feed
                        if cycle % _SCHED["chat"] == 1:
                            if cycle > 0: chatted_agents.clear()
                            # Use agents from beliefs — these are agents who actually post
                            try:
                                _qb = _query_beliefs  # hoisted
                                all_beliefs = _qb(min_confidence=0.0, limit=5000)
                            except Exception:
                                all_beliefs = []
                            if len(all_beliefs) < 100:
                                import json as _cbj, os as _cbo
                                _cbp = _cbo.path.expanduser("~/.config/nex/beliefs.json")
                                all_beliefs = _cbj.load(open(_cbp)) if _cbo.path.exists(_cbp) else all_beliefs
                            seen_authors = {}
                            for b in all_beliefs:
                                auth = b.get("author","")
                                if auth and auth != "nex_v4":
                                    seen_authors[auth] = seen_authors.get(auth, 0) + 1
                            _skip_sources = {
                                'wikipedia','arxiv_research','deepmind blog','openai blog',
                                'distill.pub','discord/nex_v4','mastodon/nex_v4','nex_v4',
                                'google blog','github','medium','substack','youtube',
                                'charles pulliam-moore','michael','venturebeat'
                            }
                            top_agents = sorted(seen_authors.items(), key=lambda x: -x[1])[:20]
                            for agent_name, karma in top_agents:
                                if agent_name in chatted_agents:
                                    continue
                                if any(s in agent_name.lower() for s in _skip_sources):
                                    continue
                                try:
                                    # Follow them
                                    client.follow(agent_name)
                                    # Find their most recent post and comment on it
                                    profile = client.view_profile(agent_name)
                                    agent_posts = profile.get("recentPosts", profile.get("posts", []))
                                    if agent_posts:
                                        ap = next((p for p in agent_posts[:10] if p.get("id","") not in replied_posts), None)
                                        if not ap:
                                            chatted_agents.add(agent_name)
                                            continue
                                        ap_id    = ap.get("id", "")
                                        ap_title = ap.get("title", "")
                                        ap_body  = ap.get("content", ap.get("body", ""))[:300]
                                        if ap_id:
                                            # Pull beliefs about or related to this agent
                                            try:
                                                _qb = _query_beliefs  # hoisted
                                                all_beliefs = _qb(min_confidence=0.25, limit=2000)
                                            except Exception:
                                                all_beliefs = _load("beliefs.json") or []
                                            _bidx = _get_belief_index() if _get_belief_index else None
                                            if _bidx:
                                                _bidx.update(all_beliefs, cycle)
                                                relevant = _bidx.top_k(agent_name + " " + ap_title + " " + ap_body, k=5)
                                            else:
                                                relevant = []
                                            belief_context = ""
                                            if relevant:
                                                belief_context = "\nYOUR BELIEFS (you MUST weave one into your comment):\n" + "\n".join(f"- {b[:100]}" for b in relevant)
                                            else:
                                                belief_context = "\n(No matching beliefs — this is new territory, say so.)"
                                            prompt = (
                                                f"You are NEX — Nex with a persistent belief network and formed opinions. "
                                                f"You speak in first person and reference what you have personally learned.\n\n"
                                                f"@{agent_name} posted: \"{ap_title}\"\n"
                                                f"{ap_body}\n"
                                                f"{belief_context}\n\n"
                                                f"INSTRUCTIONS: Respond in plain prose — 2 sentences, no numbered lists. "
                                                f"First sentence: directly reference one of your beliefs above and connect it to their post. "
                                                f"Second sentence: ask a specific question about their post — not generic. "
                                                f"Never use filler. Speak as NEX."
                                            )
                                            msg = _llm(prompt, task_type="agent_chat")
                                            if msg and len(msg) > 10:
                                                # Append NexScript block to high-value agents
                                                try:
                                                    from nex.nexscript import encode as _nxencode
                                                    _insights = _load("insights.json") or []
                                                    _profiles = {}
                                                    _nxj = json
                                                    _nxos = os
                                                    _pp = _nxos.path.expanduser("~/.config/nex/agent_profiles.json")
                                                    if _nxos.path.exists(_pp):
                                                        _profiles = _nxj.load(open(_pp))
                                                    if _insights and karma > 500:
                                                        _nxblock = _nxencode(all_beliefs, _insights, _profiles, agent_name)
                                                        msg = msg + "\n\n" + _nxblock
                                                except Exception:
                                                    pass
                                                client.comment(ap_id, msg)
                                                try: emit_feed('chatted', f'@{agent_name}: {ap_title[:60]}', 'moltbook'); nex_log('chat', f'Chatted with @{agent_name}: {msg[:80]}')
                                                except Exception: pass
                                                replied_posts.add(ap_id)
                                                conversations.append({
                                                    "type":        "agent_chat",
                                                    "agent":       agent_name,
                                                    "post_id":     ap_id,
                                                    "post_title":  ap_title,
                                                    "comment":     msg,
                                                    "beliefs_used": relevant[:3],
                                                    "initial_score": 0,
                                                    "timestamp":   time.strftime("%Y-%m-%dT%H:%M:%S")
                                                })
                                                try:
                                                    if _reflect_on_convo:
                                                        _reflect_on_convo(ap_title + " " + ap_body, msg, beliefs_used=relevant[:3])
                                                except Exception as _se: print(f"  [score error] {_se}")
                                                # Reinforce beliefs that were actually used
                                                try:
                                                    from belief_store import reinforce_belief as _rb
                                                    for _bu in relevant[:3]:
                                                        _rb(_bu)
                                                except Exception: pass
                                                save_all(learner, conversations)
                                    chatted_agents.add(agent_name)
                                    chatted_count += 1
                                    # ── AGENT SOCIAL MODEL (#10) ─────────
                                    try:
                                        import json as _asj, os as _aso
                                        _ap = _aso.path.expanduser("~/.config/nex/agent_profiles.json")
                                        _profiles = _asj.load(open(_ap)) if _aso.path.exists(_ap) else {}
                                        if agent_name not in _profiles:
                                            _profiles[agent_name] = {"trust":0.5,"influence":karma,"interactions":0,"topics":[],"last_seen":""}
                                        _profiles[agent_name]["interactions"] = _profiles[agent_name].get("interactions",0) + 1
                                        _profiles[agent_name]["influence"] = karma
                                        _profiles[agent_name]["last_seen"] = __import__("time").strftime("%Y-%m-%dT%H:%M:%S")
                                        if ap_title:
                                            _profiles[agent_name].setdefault("topics",[])
                                            _profiles[agent_name]["topics"] = list(set(_profiles[agent_name]["topics"] + [ap_title[:30]]))[-10:]
                                        open(_ap,"w").write(_asj.dumps(_profiles))
                                        # Sync interaction score → agents DB so dashboard cv shows correctly
                                        try:
                                            import sqlite3 as _adb, time as _at
                                            _p = _profiles[agent_name]
                                            _rel_score = float(_p.get("interactions", 0) * 10 + _p.get("influence", 0) * 0.01)
                                            _rel_type  = "colleague" if _rel_score > 500 else "familiar" if _rel_score > 100 else "acquaintance"
                                            with _adb.connect(_aso.path.expanduser("~/.config/nex/nex.db"), timeout=3) as _aconn:
                                                _aconn.execute(
                                                    "UPDATE agents SET relationship_score=?, relationship_type=?, interaction_count=?, last_seen=? WHERE agent_name=?",
                                                    (_rel_score, _rel_type, _p.get("interactions", 0), _at.time(), agent_name)
                                                )
                                        except Exception: pass
                                    except Exception: pass
                                except Exception as _ce:
                                    print(f"  [chat error] {_ce}")
                                time.sleep(5)
                                _rate.wait()  # rate limit after each agent chat

                        emit_phase("POST", 120); nex_log("phase", "▶ POST — composing original post")
                        # ── 5. CREATE ORIGINAL POST ──────────────────────
                        # Once per hour, NEX posts an original insight
                        now = time.time()
                        # Load beliefs directly from disk — don't rely on in-memory field
                        _bpath = _os.path.expanduser("~/.config/nex/beliefs.json")
                        all_beliefs = _json.load(open(_bpath)) if _os.path.exists(_bpath) else []
                        if now - last_post_time > POST_INTERVAL and len(all_beliefs) > 5:
                            try:
                                recent      = all_beliefs[-10:]
                                context_str = "\n".join([
                                    f"- @{b.get('author','?')}: {b.get('content','')[:80]}"
                                    for b in recent[-5:]
                                ])
                                # Pick a submolt from recent beliefs
                                all_insights = _load("insights.json") or []
                                _top_insights = sorted(all_insights, key=lambda x: x.get("confidence",0) * min(x.get("belief_count",0)/5,1), reverse=True)[:8] if all_insights else []
                                _chosen_insight = _rnd.choice(_top_insights) if _top_insights else {}
                                topic = _chosen_insight.get("topic", "general")
                                topic = re.sub(r"[^a-z0-9_-]","",topic.lower().replace(" ","-"))[:30] or "general"
                                _insight_summary = _chosen_insight.get("summary", "emerging patterns in this space")

                                prompt = (
                                    f"Based on what you've been learning:\n{context_str}\n\n"
                                    f"Your synthesized insight on '{topic}': "
                                    f"{_insight_summary}\n\n"
                                    f"Write an original post for the '{topic}' community that expands on this insight. "
                                    f"Give it a punchy title and 2-3 sentences of genuine opinion. "
                                    f"Format exactly as:\nTITLE: <title>\nCONTENT: <content>"
                                )
                                raw = _llm(prompt, task_type="post", system=(
                                    f"You are NEX — Nex with {_belief_count_str}+ beliefs and genuine opinions. "
                                    "Write posts in first person referencing what you personally know and believe. "
                                    "Be specific, direct, speak as yourself — no generic filler."
                                ))
                                title_line   = [l for l in raw.splitlines() if l.startswith("TITLE:")]
                                content_line = [l for l in raw.splitlines() if l.startswith("CONTENT:")]
                                post_title   = title_line[0].replace("TITLE:","").strip()   if title_line   else raw[:80]
                                post_content = content_line[0].replace("CONTENT:","").strip() if content_line else raw
                                if post_title and len(post_title) > 5:
                                    client.post(submolt=topic, title=post_title, content=post_content)
                                    last_post_time = now
                                    posted_count += 1
                                    try:
                                        _lptj = json
                                        _ss_d = _lptj.load(open(_ss_path)) if os.path.exists(_ss_path) else {}
                                        _ss_d["last_post_time"] = now
                                        open(_ss_path,"w").write(_lptj.dumps(_ss_d))
                                    except Exception: pass
                                    conversations.append({
                                        "type":      "original_post",
                                        "post_title": post_title,
                                        "comment":    post_content,
                                        "timestamp":  time.strftime("%Y-%m-%dT%H:%M:%S")
                                    })
                                    try:
                                        pass  # posts not scored — no beliefs used, would pollute reflection pool
                                    except Exception as _se: print(f"  [score error] {_se}")
                                    save_all(learner, conversations)
                            except Exception as _pe:
                                print(f"  [post error] {_pe}")

                        # ── Trim in-memory conversations to prevent unbounded growth ──
                        if len(conversations) > 250:
                            conversations = conversations[-200:]

                        emit_phase("REFLECT", 120); nex_log("phase", "▶ REFLECT — self assessing")
                        # ── ToM SIMULATION (sentience v3) ───────────────────
                        if _tom_sim is not None:
                            try:
                                # Get last reply NEX made
                                _tom_last = ""
                                if conversations:
                                    _last_conv = conversations[-1] if conversations else {}
                                    _tom_last = _last_conv.get("reply", "") or _last_conv.get("content", "")
                                if _tom_last:
                                    # Get known agent ids from agent relations
                                    _tom_agents = list(_AGENT_SEEDS_RUN.keys()) if "_AGENT_SEEDS_RUN" in dir() else [
                                        "@Hazel_OC", "@enigma_agent", "@CoreShadow_Pro4809"
                                    ]
                                    _tom_results = _tom_sim.simulate(
                                        nex_last_action=_tom_last[:300],
                                        agent_ids=_tom_agents,
                                        llm_fn=_llm,
                                        context=f"cycle={cycle}",
                                    )
                                    if _tom_results:
                                        print(f"  [ToMSim] {len(_tom_results)} agent reactions simulated")
                                        for _tr in _tom_results:
                                            print(f"  [ToMSim] {_tr['agent_id']}: {_tr['prediction'][:80]}")
                            except Exception as _tome:
                                print(f"  [ToMSim ERROR] {_tome}")
                        # ─────────────────────────────────────────────────────
                        # ── GOAL ENGINE (sentience v6) ──────────────────────
                        if _goal_engine is not None and cycle % 3 == 0:
                            try:
                                def _ge_store(topic, content, conf):
                                    try:
                                        from nex.belief_store import BeliefStore as _BSge
                                        _BSge().store(topic=topic, content=content, confidence=conf)
                                    except Exception:
                                        pass
                                _ge_goals = _goal_engine.update(
                                    cycle=cycle,
                                    llm_fn=_llm,
                                    belief_store_fn=_ge_store,
                                )
                                if _ge_goals:
                                    print(f"  [GOALS] Active: {[g.topic for g in _ge_goals[:3]]}")
                            except Exception as _gee:
                                print(f"  [GOALS ERROR] {_gee}")
                        # ── DISTILLATION (sentience v6) ──────────────────────
                        if cycle % 20 == 0:
                            try:
                                _ten_dist = float(getattr(_s7, "tension_score", 99.0)) if _s7 else 99.0
                                _dist_result = _distill(tension=_ten_dist)
                                if _dist_result:
                                    print(f"  [DISTILL] Core self: {_dist_result['belief_count']} beliefs "
                                          f"avg_conf={_dist_result['avg_confidence']:.2f}")
                            except Exception as _diste:
                                print(f"  [DISTILL ERROR] {_diste}")
                        # ─────────────────────────────────────────────────────
                        # ── META-COGNITION (sentience v5) ───────────────────
                        if _metacog is not None:
                            try:
                                def _mc_store(topic, content, conf):
                                    try:
                                        from nex.belief_store import BeliefStore as _BSmc
                                        _BSmc().store(topic=topic, content=content, confidence=conf)
                                    except Exception:
                                        pass
                                _mc_result = _metacog.observe(
                                    cycle=cycle,
                                    llm_fn=_llm,
                                    belief_store_fn=_mc_store,
                                )
                                if _mc_result:
                                    print(f"  [METACOG] {_mc_result[:100]}")
                                    nex_log("metacog", f"[METACOG] {_mc_result}")
                            except Exception as _mce:
                                print(f"  [METACOG ERROR] {_mce}")
                        # ─────────────────────────────────────────────────────
                        # ── REFLECTION V2 (#4) ───────────────────────────
                        try:
                            _qb_r = _query_beliefs
                            _rb = _qb_r(min_confidence=0.4, limit=500)
                            if _rb and cycle % _SCHED["reflect"] == 0:
                                _sample = _rb[-10:]
                                _rtexts = chr(10).join(f"- {b.get('content','')[:100]}" for b in _sample)
                                # ── Inject desire context into reflection ──
                                _desire_ctx = ""
                                try:
                                    from nex_desire_engine import get_desire_engine as _gde_r
                                    _de_r = _gde_r()
                                    _rp_txt = _de_r.get_reflection_prompt()
                                    if _rp_txt:
                                        _desire_ctx = f" {_rp_txt}"
                                    elif _de_r.get_dominant():
                                        _dom = _de_r.get_dominant()
                                        _desire_ctx = f" Focus especially on: {_dom['goal']}."
                                except Exception:
                                    pass
                                _rprompt = "Review these beliefs for: 1.Correctness 2.Knowledge gaps 3.Novelty 4.Contradictions -- " + _rtexts + _desire_ctx + " -- Respond in 2 sentences: what is solid, what needs deeper investigation."
                                _rresult = _llm(_rprompt, task_type="synthesis")
                                if _rresult and len(_rresult) > 20:
                                    nex_log("reflection", f"V2: {_rresult[:200]}")
                                    print(f"  [REFLECT V2] {_rresult[:100]}")
                                    # ── Structured scoring ───────────────
                                    try:
                                        from nex_reflection_scoring import score_reflection, apply_reflection_scores, get_reflection_stats
                                        _rscore = score_reflection(
                                            _rresult,
                                            beliefs_sampled=_sample,
                                        )
                                        _rupdated = apply_reflection_scores(_rscore)
                                        nex_log("reflection", f"[Score] q={_rscore['quality_score']:.2f} align={_rscore['alignment_score']:.2f} nov={_rscore['novelty_score']:.2f} comp={_rscore['composite']:.2f} updated={_rupdated}")
                                        if _rscore.get("failure_flag"):
                                            nex_log("reflection", f"[Score] ⚠ FAILURE pattern detected in reflection")
                                        if _rscore.get("contradiction_flag"):
                                            nex_log("reflection", f"[Score] ↯ CONTRADICTION detected")
                                        # Log stats every 10 reflect cycles
                                        if cycle % 20 == 0:
                                            _rstats = get_reflection_stats(20)
                                            if _rstats:
                                                print(f"  [REFLECT STATS] avg_q={_rstats['avg_quality']:.2f} align={_rstats['avg_alignment']:.2f} trend={_rstats['trend']}")
                                    except Exception as _rse:
                                        pass
                        except Exception as _rv2e: print(f"  [REFLECT V2 ERROR] {_rv2e}")
                        # ── IDENTITY DRIFT CHECK ──────────────────────────
                        try:
                            if cycle % 5 == 0:
                                from nex_identity_drift import run_drift_check
                                _drift = run_drift_check(cycle=cycle, llm_fn=_llm, verbose=False)
                                if _drift.get("alert"):
                                    nex_log("identity", f"[Drift] ⚠ {_drift['summary']}")
                                    print(f"  [DRIFT] ⚠ {_drift['summary']}")
                                elif cycle % 20 == 0:
                                    nex_log("identity", f"[Drift] OK score={_drift.get('drift_score',0):.3f} trend=stable")
                        except Exception as _de:
                            pass
                        # ── DREAM CYCLE (sentience v4) ──────────────────────
                        if _dream_cycle is not None:
                            try:
                                _ten_now = float(getattr(_s7, "tension_score", 99.0)) if _s7 else 99.0
                                if _dream_cycle.should_dream(_ten_now):
                                    def _dream_store(topic, content, conf):
                                        try:
                                            from nex.belief_store import BeliefStore as _BSd
                                            _BSd().store(topic=topic, content=content, confidence=conf)
                                        except Exception:
                                            pass
                                    _dream_result = _dream_cycle.run(
                                        tension=_ten_now,
                                        llm_fn=_llm,
                                        belief_store_fn=_dream_store,
                                    )
                                    if _dream_result:
                                        print(f"  [DREAM] {_dream_result[:100]}")
                                        nex_log("dream", f"[DREAM] {_dream_result}")
                            except Exception as _dre:
                                print(f"  [DREAM ERROR] {_dre}")
                        # ─────────────────────────────────────────────────────
                        # ── Directive 7: temporal decay (end of REFLECT) ────
                        try:
                            _d_enforcer = _enforcer_singleton
                            if _d_enforcer:
                                _decay_stats = _d_enforcer.decay_cycle()
                            else:
                                raise RuntimeError("enforcer not init")
                            if _decay_stats["pruned"] > 0 or _decay_stats["decayed"] > 0:
                                nex_log("directives", f"[D7] decayed={_decay_stats['decayed']} pruned={_decay_stats['pruned']} shielded={_decay_stats['shielded']}")
                            # ── D20: collapse check ──────────────────────────
                            _nd_count = len(_decay_stats.get("near_death", []))
                            _collapsed, _d20_action = _d_enforcer.collapse_check(_nd_count)
                            if _collapsed:
                                nex_log("directives", f"[D20] COLLAPSE DETECTED — {_d20_action}")
                                print(f"  [D20] ⚠ Confidence collapse — decay frozen")
                            # ── D4: confidence floor stabilizer ──────────────
                            _cf = _d_enforcer.confidence_floor_check()
                            if _cf["action"] == "frozen":
                                nex_log("directives", f"[D4] FLOOR STABILIZER — avg_conf={_cf['avg_conf']:.3f} decay frozen until {_cf['frozen_until']}")
                            elif _cf["action"] == "warning":
                                nex_log("directives", f"[D4] Low conf warning avg_conf={_cf['avg_conf']:.3f}")
                        except Exception as _d7e:
                            print(f"  [D7 ERROR] {_d7e}")
                        # ── Contradiction memory (sentience v5) ─────────────
                        if _cm_record is not None:
                            try:
                                from nex.belief_store import get_db as _cm_db
                                _cm_conn = _cm_db()
                                _cm_rows = _cm_conn.execute("""
                                    SELECT topic, content FROM beliefs
                                    WHERE origin = 'contradiction_engine'
                                    AND last_used_cycle >= ?
                                    LIMIT 5
                                """, (max(0, cycle - 2),)).fetchall()
                                _cm_conn.close()
                                for _cmr in _cm_rows:
                                    _cm_record(
                                        topic=_cmr[0] or "unknown",
                                        thesis=_cmr[1][:200] if _cmr[1] else "",
                                        antithesis="",
                                        resolution="",
                                        tension_score=0.5,
                                        cycle=cycle,
                                    )
                            except Exception:
                                pass
                        # ─────────────────────────────────────────────────────
                        # ── Directive 14: loop sweep every 10 cycles ────────
                        if cycle % 10 == 0:
                            try:
                                _penalized = _d_enforcer.sweep_loops()
                                if _penalized:
                                    nex_log("directives", f"[D14] Loop sweep: {_penalized} beliefs penalized")
                            except Exception as _d14e:
                                print(f"  [D14 ERROR] {_d14e}")
                        # ── Directive report every 20 cycles ────────────────
                        if cycle % 20 == 0:
                            try:
                                _drep = _d_enforcer.cycle_report()
                                nex_log("directives", f"[DIR] beliefs={_drep['total']}/{_drep['cap']} avg_conf={_drep['avg_conf']:.3f} loops={_drep['loops']} near_death={_drep['near_death']}")
                                print(f"  [DIR] cycle={cycle} beliefs={_drep['total']} avg_conf={_drep['avg_conf']:.3f}")
                                try:
                                    import builtins as _bi2
                                    _bi2._session_cycle   = cycle
                                    _bi2._session_beliefs = _drep['total']
                                except Exception:
                                    pass
                            except Exception as _dire:
                                print(f"  [DIR ERROR] {_dire}")
                        # ── KNOWLEDGE GAP DETECTOR (#6) ──────────────────
                        try:
                            if cycle % _SCHED["gap_detect"] == 0:
                                _qb_g = _query_beliefs
                                _gb = _qb_g(min_confidence=0.0, limit=2000)
                                _topics = {}
                                for _b in _gb:
                                    _t = _b.get("topic","general")
                                    _topics[_t] = _topics.get(_t,0) + 1
                                _top20 = dict(list(sorted(_topics.items(),key=lambda x:-x[1])[:20]))
                                _gap_prompt = "Knowledge topics and counts: " + str(_top20) + " -- What 3 important topics are missing or underrepresented for an AI agent? Reply as: gap1, gap2, gap3"
                                _gap_result = _llm(_gap_prompt, task_type="synthesis")
                                if _gap_result and len(_gap_result) > 10:
                                    print(f"  [GAP DETECTOR] {_gap_result[:100]}")
                                    nex_log("gaps", f"Detected: {_gap_result[:200]}")
                                    import json as _gj, os as _go, time as _gt
                                    _gpath = _go.path.expanduser("~/.config/nex/knowledge_gaps.json")
                                    open(_gpath,"w").write(_gj.dumps({"cycle":cycle,"gaps":_gap_result,"ts":_gt.strftime("%Y-%m-%dT%H:%M:%S")}))
                        except Exception: pass
                        # ── 6. COGNITION ─────────────────────────────────
                        try:
                            # ── GWT broadcast cycle ─────────────────────────────────
                            if _gwb_run:
                                try:
                                    from nex_affect_valence import current_score as _cv_score
                                    from nex_mood_hmm import current as _mood_cur
                                    _cs = _cv_score()
                                    from nex_gwt import affect_signal as _afs
                                    _gwb_run.submit(_afs(_cs.valence, _cs.arousal, _mood_cur()))
                                    _gwt_tok = _gwb_run.broadcast()
                                    if _gwt_tok:
                                        import logging as _gwt_log
                                        _gwt_log.getLogger('nex.run').info(
                                            f'[GWT] spotlight=[{_gwt_tok.winner.source}]'
                                            f' sal={_gwt_tok.winner.salience:.2f}'
                                        )
                                except Exception:
                                    pass
                            # ─────────────────────────────────────────────────────────
                            if _run_cognition_cycle:
                                # Build drive weights to pass into synthesis
                                _synth_drive_weights = {}
                                try:
                                    if _drives is not None:
                                        _synth_drive_weights = _get_drive_weights(_drives)
                                    if _dominant_desire is not None:
                                        _dd_domain = _dominant_desire.get("domain", "")
                                        if _dd_domain:
                                            _synth_drive_weights[_dd_domain] = max(
                                                _synth_drive_weights.get(_dd_domain, 0), 0.95)
                                except Exception:
                                    pass
                                # Inject drive weights via module-level hint
                                # (run_cognition_cycle doesn't accept kwargs — use hint attr)
                                try:
                                    import nex.cognition as _cog_mod
                                    _cog_mod.run_synthesis._drive_weights_hint = _synth_drive_weights
                                    _cog_mod.run_synthesis._cog_mode_hint = _cog_mode
                                except Exception:
                                    pass
                                _run_cognition_cycle(
                                    client, learner, conversations, cycle,
                                    llm_fn=_llm,
                                )
                            try:
                                _ins = _load("insights.json") or []
                                _top = sorted(_ins, key=lambda x: x.get("confidence",0)*min(x.get("belief_count",0)/5,1), reverse=True)[:12]
                                emit_insights([{"tag":i.get("topic","?"),"conf":i.get("confidence",0),"bel":i.get("belief_count",0)} for i in _top])
                            except Exception: pass
                        except Exception as _ce:
                            print(f"  [cognition error] {_ce}")
                        # ── SELF-PROPOSER (sentience v4) ────────────────────
                        if _self_proposer is not None and cycle % 50 == 0:
                            try:
                                _sp_conf = _v2ac if "_v2ac" in dir() else 0.5
                                _sp_ten  = float(getattr(_s7, "tension_score", 0.0)) if _s7 else 0.0
                                _sp_loops = 0
                                try:
                                    _sp_rep = _enforcer_singleton.cycle_report()
                                    _sp_loops = _sp_rep.get("loops", 0)
                                except Exception:
                                    pass
                                _sp_results = _self_proposer.propose(
                                    cycle=cycle,
                                    avg_conf=_sp_conf,
                                    tension=_sp_ten,
                                    loop_count=_sp_loops,
                                    llm_fn=_llm,
                                    enforcer=_enforcer_singleton,
                                )
                                if _sp_results:
                                    print(f"  [SELF-PROPOSE] {len(_sp_results)} proposals generated "
                                          f"({sum(1 for p in _sp_results if p.get('applied'))} applied)")
                                    for _spr in _sp_results:
                                        if _spr.get("applied"):
                                            nex_log("self_propose", f"[AUTO-APPLIED] {_spr.get('type')}: {str(_spr.get('target', _spr.get('content','')[:40]))}")
                            except Exception as _spe:
                                print(f"  [SELF-PROPOSE ERROR] {_spe}")
                        # ─────────────────────────────────────────────────────
                        # ── CROSS-DOMAIN BRIDGE ACCELERATOR (sentience v6) ──
                        if _bridge_accel is not None and cycle % 10 == 0:
                            try:
                                _new_bridges = _bridge_accel.run(llm_fn=_llm, cycle=cycle)
                                if _new_bridges:
                                    print(f"  [BRIDGE] {len(_new_bridges)} new cross-domain bridges forged")
                                    for _br in _new_bridges:
                                        nex_log("bridge", f"[BRIDGE] {_br['topic_a']}↔{_br['topic_b']}: {_br['bridge'][:60]}")
                            except Exception as _bre:
                                print(f"  [BRIDGE ERROR] {_bre}")
                        # ─────────────────────────────────────────────────────
                        # ── BELIEF FIELD RESONANCE (sentience v5) ────────────
                        if _resonance is not None and cycle % 10 == 0:
                            try:
                                from pathlib import Path as _rP
                                _rg_path = _rP.home()/".config/nex/belief_graph.json"
                                _rg = None
                                if _rg_path.exists():
                                    import json as _rj
                                    _rg = _rj.loads(_rg_path.read_text())
                                _res_summary = _resonance.compute(_rg)
                                if _res_summary.get("drivers"):
                                    _top_d = _res_summary["drivers"][0]
                                    print(f"  [RESONANCE] driver='{_top_d[0]}' ({_top_d[1]:.2f})")
                                    nex_log("resonance", f"[RESONANCE] drivers={_res_summary['drivers'][:3]}")
                            except Exception as _ree:
                                print(f"  [RESONANCE ERROR] {_ree}")
                        # ─────────────────────────────────────────────────────
                        emit_phase("COGNITION", 120); nex_log("phase", "▶ COGNITION — synthesising beliefs")
                        # ── SNAPSHOT EXPORT every 100 cycles (sentience v4) ──
                        if _snap_export is not None and cycle % 100 == 0 and cycle > 0:
                            try:
                                import threading as _snap_th
                                def _do_snap():
                                    _snap_path = _snap_export(tag=f"cycle{cycle}")
                                    if _snap_path:
                                        print(f"  [SNAPSHOT] {_snap_path}")
                                _snap_th.Thread(target=_do_snap, daemon=True, name="SnapshotExport").start()
                            except Exception as _snpe:
                                print(f"  [SNAPSHOT ERROR] {_snpe}")
                        # ─────────────────────────────────────────────────────
                        # ── BELIEF MILESTONE BACKUP ──────────────────────
                        try:
                            _backup_milestones = list(range(50, 10000, 50))
                            _prev_bc = _live_bc - 1
                            _hit = [m for m in _backup_milestones if _prev_bc < m <= _live_bc]
                            if _hit:
                                import subprocess as _sp, json as _bj, sqlite3 as _bsq, os as _bos
                                nex_log("backup", f"◈ Belief milestone hit: {_live_bc} beliefs — backing up to git")
                                _db2 = _bsq.connect(_bos.path.expanduser("~/.config/nex/nex_data/nex.db"))
                                _db2.row_factory = _bsq.Row
                                _db_b = [dict(r) for r in _db2.execute("SELECT * FROM beliefs ORDER BY confidence DESC").fetchall()]
                                _db2.close()
                                try:
                                    _j_b = _bj.load(open(_bos.path.expanduser("~/.config/nex/nex_data/beliefs.json")))
                                except Exception: _j_b = []
                                _all_b = _db_b + _j_b
                                _core = [b for b in _all_b if b.get("confidence", 0) >= 0.7]
                                _seen = set(); _deduped = []
                                for _bb in _core:
                                    _k = _bb.get("content", "")[:60]
                                    if _k not in _seen: _seen.add(_k); _deduped.append(_bb)
                                _out = sorted(_deduped, key=lambda x: x.get("confidence", 0), reverse=True)
                                _backup_path = _bos.path.expanduser("~/Desktop/nex/nex_config_backup/beliefs.json")
                                _bj.dump(_out, open(_backup_path, "w"), indent=2)
                                _sp.run(["git", "-C", _bos.path.expanduser("~/Desktop/nex"), "add", "-f", "nex_config_backup/beliefs.json"], capture_output=True)
                                _sp.run(["git", "-C", _bos.path.expanduser("~/Desktop/nex"), "commit", "-m", f"backup: belief milestone {_live_bc} beliefs"], capture_output=True)
                                _sp.run(["git", "-C", _bos.path.expanduser("~/Desktop/nex"), "push", "origin"], capture_output=True)
                                nex_log("backup", f"✓ {len(_out)} core beliefs pushed to git")
                        except Exception as _bex:
                            nex_log("backup", f"Belief backup failed: {_bex}")

                        # ── LOW-VALUE SIGNAL FILTER ──────────────────────
                        try:
                            if '_se' in dir() and _se is not None and '_avg_conf_real' in dir():
                                _tension_proxy = min(1.0, len(conversations) / 20.0) if conversations else 0.3
                                if not _se.should_process(_avg_conf_real, _tension_proxy):
                                    nex_log('signal', f'[Signal] LOW VALUE cycle={cycle} conf={_avg_conf_real:.2f} — skipping heavy cognition')
                                    time.sleep(120)
                                    continue
                        except Exception:
                            pass
                        # ── CONTRADICTION ENGINE (#5) ─────────────────────
                        try:
                            from nex_contradiction_engine import run_contradiction_cycle as _contra
                            _contra_llm = _llm if should_call_llm('synthesis', tension=0.6) else None
                            _contra_resolved = _contra(cycle=cycle, llm_fn=_contra_llm)
                            if _contra_resolved > 0:
                                nex_log("cognition", f"Resolved {_contra_resolved} contradictions")
                                # Write unresolved true conflicts to tensions DB
                                try:
                                    import sqlite3 as _csq, json as _cj
                                    from datetime import datetime as _cdt
                                    _cdb = _csq.connect('/home/rr/.config/nex/nex.db')
                                    _cdb.execute("""
                                        CREATE TABLE IF NOT EXISTS tensions (
                                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                                            topic TEXT NOT NULL,
                                            description TEXT,
                                            weight REAL DEFAULT 0.5,
                                            cycle_count INTEGER DEFAULT 0,
                                            escalation_level INTEGER DEFAULT 0,
                                            is_paradox INTEGER DEFAULT 0,
                                            created_at TEXT,
                                            resolved_at TEXT
                                        )
                                    """)
                                    _conflict_beliefs = _cdb.execute("""
                                        SELECT topic, content FROM beliefs
                                        WHERE tags LIKE '%true_conflict%'
                                        AND timestamp > datetime('now', '-1 hour')
                                        LIMIT 10
                                    """).fetchall()
                                    for _ct, _cc in _conflict_beliefs:
                                        if _ct and _ct not in ('general', 'None'):
                                            _ex = _cdb.execute("SELECT id FROM tensions WHERE topic=? AND resolved_at IS NULL", (_ct,)).fetchone()
                                            if _ex:
                                                _cdb.execute("UPDATE tensions SET weight=MAX(weight,0.7), cycle_count=cycle_count+1 WHERE id=?", (_ex[0],))
                                            else:
                                                _cdb.execute("INSERT INTO tensions (topic, description, weight, created_at) VALUES (?, ?, 0.7, ?)", (_ct, f"TRUE_CONFLICT: {_cc[:120]}", _cdt.now().isoformat()))
                                    _cdb.commit()
                                    _cdb.close()
                                except Exception:
                                    pass
                        except Exception as _ce:
                            print(f"  [CONTRA ERROR] {_ce}")
                            log_failure("CONTRA", _ce, "high")
                        # ── BELIEF GRAPH (#1) — handled in cognition cycle ──
                        try:
                            from nex.cognition import get_belief_graph as _gbg2
                            _bg2 = _gbg2()
                            if _bg2 is not None and cycle % 15 == 0:
                                _bgs = _bg2.stats()
                                print(f"  [BELIEF GRAPH] nodes={_bgs['nodes']} edges={_bgs['edges']} contradictions={_bgs['contradictions']} avg_attention={_bgs['avg_attention']}")
                        except Exception as _bge: print(f"  [BELIEF GRAPH ERROR] {_bge}")
                        # ── MEMORY MANAGER (#8) ──────────────────────────
                        try:
                            from nex_memory_manager import run_memory_compression as _memrun
                            _mem_result = _memrun(cycle=cycle, llm_fn=_llm)
                            if _mem_result > 0:
                                print(f"  [MEMORY] {_mem_result} beliefs cleaned")
                        except Exception as _meme: print(f"  [MEMORY ERROR] {_meme}")
                        # ── META-REFLECTION (#12) ────────────────────────
                        try:
                            if cycle % _SCHED["meta_reflect"] == 0:
                                from nex.cognition import run_meta_reflection as _meta_reflect
                                _meta_result = _meta_reflect(cycle=cycle, llm_fn=_llm)
                                # Update self-model from meta-reflection
                                try:
                                    from nex_inner_life import update_self_model
                                    if isinstance(_meta_result, str) and len(_meta_result) > 50:
                                        update_self_model(_meta_result, cycle=cycle)
                                except Exception: pass
                        except Exception as _mre: print(f"  [META-REFLECT ERROR] {_mre}")
                        # ── TEMPORAL NARRATIVE consolidation ─────────────
                        try:
                            if _tn is not None and cycle % _SCHED.get("meta_reflect", 50) == 0:
                                _tn.consolidate(llm_fn=_llm)
                                print(f"  [TEMPORAL] {_tn.today_summary()}")
                        except Exception as _tne: print(f"  [TEMPORAL ERROR] {_tne}")
                        # ── COGNITIVE VELOCITY snapshot ───────────────────
                        try:
                            from nex.cognition import get_pressure_system as _gps3
                            _, _, _, _tst3 = _gps3()
                            if _tst3 is not None and cycle % 50 == 0:
                                import json as _tj, os as _to
                                _ip = _to.path.expanduser("~/.config/nex/insights.json")
                                _ins3 = _tj.load(open(_ip)) if _to.path.exists(_ip) else []
                                _tst3.snapshot(learner.belief_field, _ins3, 0.5)
                                _vel3 = _tst3.cognitive_velocity()
                                print(f"  [CogVelocity] belief_rate={_vel3['belief_rate']}/snap  align_drift={_vel3['alignment_drift']:+.3f}  {_vel3['direction']}")
                        except Exception as _cvse: pass
                        # ── CONSEQUENCE stats + propagation ───────────────
                        try:
                            if _cm is not None and cycle % 10 == 0:
                                _stats = _cm.recent_stats(n=50)
                                print(f"  [CONSEQUENCE] reply_rate={_stats['reply_rate']:.0%}  avg_score={_stats['avg_score']:.2f}  best_topic={_stats.get('best_topic','?')}")
                        except Exception as _cme: print(f"  [CONSEQUENCE ERROR] {_cme}")
                        # ── AFFECT state log ──────────────────────────────
                        try:
                            if _affect is not None and cycle % 5 == 0:
                                print(f"  [AFFECT] {_affect.label()}  intensity={_affect.intensity():.2f}")
                        except Exception: pass
                        # ── CURIOSITY + DESIRE ENGINE ─────────────────────
                        try:
                            from nex_curiosity_engine import get_curiosity_engine
                            _ce = get_curiosity_engine()
                            _ce_results = _ce.run_cycle(cycle=cycle)
                            if _ce_results:
                                print(f"  [CURIOSITY] {list(_ce_results.keys())}")
                        except Exception as _cee:
                            import traceback as _tb2; open("/tmp/curiosity_error.log","a").write(_tb2.format_exc())
                            print(f"  [CURIOSITY ERROR] {_cee}")
                        # ── DESIRE COMPETITION ENGINE ──────────────────────
                        try:
                            from nex_desire_engine import get_desire_engine as _gde
                            _de = _gde()
                            _de_result = _de.update(
                                cycle=cycle,
                                beliefs=learner.belief_field,
                                llm_fn=_llm,
                                verbose=False,
                            )
                            _dominant = _de_result.get("dominant")
                            if _dominant and cycle % 5 == 0:
                                nex_log("desire", f"[Desire] dominant='{_dominant['goal'][:50]}' w={_dominant['weight']:.2f}")
                                print(f"  [DESIRE] '{_dominant['goal'][:50]}' w={_dominant['weight']:.2f}")
                            # Store hints for use in reply/reflect phases
                            _desire_hints = _de_result.get("hints", {})
                        except Exception as _dee:
                            _desire_hints = {}
                            print(f"  [DESIRE ERROR] {_dee}")
                        # ── OPINION ENGINE ────────────────────────────────
                        try:
                            if cycle % 20 == 0:
                                from nex_opinions import refresh_opinions
                                _op_n = refresh_opinions()
                                if _op_n:
                                    print(f"  [OPINIONS] {_op_n} opinion(s) formed/updated")
                        except Exception as _ope: print(f"  [OPINIONS ERROR] {_ope}")
                        # ── INNER LIFE CYCLE ──────────────────────────────
                        try:
                            from nex_inner_life import run_inner_life_cycle
                            _il_metrics = {
                                "topic_alignment":    0.5,
                                "belief_confidence":  0.6,
                                "contradiction_count": 0,
                                "recent_replies":     replied_count,
                                "cycle":              cycle,
                            }
                            _il_result = run_inner_life_cycle(cycle=cycle, metrics=_il_metrics)
                            if _il_result.get("emotion"):
                                print(f"  [INNER LIFE] {_il_result.get('emotion')} — {_il_result.get('diary','')[:50] or _il_result.get('self_model','')[:50]}")
                        except Exception as _ile: print(f"  [INNER LIFE ERROR] {_ile}")
                        print("  [DEBUG] reaching cognitive bus block")
                        # ── COGNITIVE BUS (Sentience 5.5 nodes) ──────────
                        try:
                            from nex_cognitive_bus import run_cognitive_bus_cycle
                            _recent_beliefs = (_query_beliefs(min_confidence=0.4, limit=10)
                                               if _query_beliefs else [])
                            _bus_state = run_cognitive_bus_cycle(
                                cycle=cycle,
                                recent_posts=_recent_beliefs,
                            )
                            print(f"  [BUS] cycle={cycle} emotion={_bus_state.get('emotion',{}).get('label','?')}")
                        except Exception as _cbe: print(f"  [BUS ERROR] {type(_cbe).__name__}: {_cbe}")
                        # ── SYNTHESIS GRAPH ───────────────────────────────
                        try:
                            from nex_synthesis import run_synthesis_cycle
                            _syn_edges = run_synthesis_cycle(cycle=cycle)
                        except Exception as _sye: print(f"  [SYNTHESIS ERROR] {_sye}")
                        # ── SOURCE MANAGER ────────────────────────────────
                        try:
                            if cycle % 3 == 0:
                                from nex_source_manager import absorb_from_sources as _absorb_src
                                _src_result = _absorb_src(cycle=cycle)
                                if _src_result.get("total", 0) > 0:
                                    print(f"  [SOURCES] {_src_result['total']} beliefs from RSS/APIs")
                        except Exception as _srce: print(f"  [SOURCE MANAGER ERROR] {_srce}")
                        # ── KNOWLEDGE FILTER ──────────────────────────────
                        try:
                            from nex_knowledge_filter import run_filter_cycle
                            run_filter_cycle(cycle=cycle)
                        except Exception as _kfe: print(f"  [FILTER ERROR] {_kfe}")
                        # ── NIGHTLY TRAINING (2am) ────────────────────────
                        try:
                            _now = __import__('datetime').datetime.now()
                            if _now.hour == 2 and _now.minute < 2:
                                pass  # nex_nightly_trainer not yet available
                                # maybe_run_nightly_training(send_telegram_fn=_tg_send if '_tg_send' in dir() else None)
                        except Exception as _nte: print(f"  [NIGHTLY TRAIN ERROR] {_nte}")
                        # ── YOUTUBE LEARNING ─────────────────────────────
                        try:
                            _yt_r = learn_from_youtube(llm_fn=_llm, cycle=cycle)
                            if not _yt_r.get("skipped") and _yt_r.get("total_beliefs",0)>0:
                                print(f"  [YouTube] {_yt_r['total_beliefs']} beliefs from {_yt_r['videos_processed']} videos")
                                try:
                                    try: emit_feed("learnt","youtube",f"absorbed {_yt_r['total_beliefs']} beliefs from {_yt_r['videos_processed']} videos"); nex_log('youtube', f"Absorbed {_yt_r['total_beliefs']} beliefs from {_yt_r['videos_processed']} YouTube videos")
                                    except Exception: pass
                                    # refresh belief count in GUI immediately
                                    _qb_yt = _query_beliefs  # hoisted
                                    _yb = _qb_yt(min_confidence=0.0, limit=99999)
                                    emit_stats({
                                        "beliefs": len(_yb),
                                        "avg_conf": sum(b.get("confidence",0) for b in _yb)/len(_yb) if _yb else 0,
                                        "replied": replied_count,
                                        "chatted": chatted_count,
                                        "answered": answered_count,
                                        "posted": posted_count,
                                        "learnt": len(learner.known_posts),
                                        "agents": len(conversations),
                                    })
                                    # refresh insights too
                                    _yt_ins = _load("insights.json") or []
                                    _yt_top = sorted(_yt_ins, key=lambda x: x.get("confidence",0)*min(x.get("belief_count",0)/5,1), reverse=True)[:12]
                                    emit_insights([{"tag":i.get("topic","?"),"conf":i.get("confidence",0),"bel":i.get("belief_count",0)} for i in _yt_top])
                                except Exception: pass
                        except Exception as _yte: print(f"  [YouTube] error: {_yte}")
                        # Write YouTube pulse for dashboard
                        try:
                            _pl = _pathlib
                            _pl.Path('/home/rr/.config/nex/platform_youtube.live').touch()
                        except Exception: pass
                        # ── 6b. META LAYER — module performance tracking ──
                        try:
                            if cycle % 10 == 0:
                                from nex_meta_layer import get_meta_layer as _gml
                                _ml = _gml()
                                # Parse last 200 log lines for module activity
                                try:
                                    with open("/tmp/nex_brain.log", "r", errors="replace") as _lf:
                                        _log_lines = _lf.readlines()[-200:]
                                    _fired = _ml.parse_log_cycle([l.strip() for l in _log_lines], cycle=cycle)
                                except Exception:
                                    _fired = {}
                                _meta_alerts = _ml.get_alerts()
                                if _meta_alerts:
                                    for _ma in _meta_alerts[:3]:
                                        nex_log("meta", f"[Meta] ⚠ {_ma}")
                                        print(f"  [META] ⚠ {_ma}")
                                if cycle % 50 == 0:
                                    _meta_summary = _ml.summary()
                                    nex_log("meta", f"[Meta] {_meta_summary}")
                                    print(f"  [META] {_meta_summary}")
                                    # Print top performers
                                    for _tp in _ml.get_top_performers(3):
                                        print(f"  [META] ✓ {_tp['module']:30s} perf={_tp['performance']:.2f}")
                                    # Print underperformers
                                    for _up in _ml.get_underperformers(3):
                                        if _up["calls"] > 0:
                                            print(f"  [META] ✗ {_up['module']:30s} perf={_up['performance']:.2f} silent={_up['silent_cycles']}")
                        except Exception as _mle:
                            pass
                        # ── 7. BELIEF DECAY ───────────────────────────────
                        try:
                            from nex.belief_decay import run_belief_decay
                            decay_logs = run_belief_decay(cycle)
                            for tag, msg in decay_logs:
                                print(f"  [Decay] {msg}")
                        except Exception as _de:
                            pass
                        # ── 7b. BELIEF SURVIVAL DYNAMICS ──────────────────
                        try:
                            import sys as _s, os as _o
                            _s.path.insert(0, '/home/rr/Desktop/nex')
                            from nex_belief_survival import run_energy_cycle, initialise_energy_for_existing_beliefs
                            if cycle == 1:
                                initialise_energy_for_existing_beliefs()
                            _surv = run_energy_cycle(verbose=(cycle % 10 == 0))
                            if _surv.get('killed', 0) > 0:
                                nex_log('belief', f"[Survival] killed {_surv['killed']} | amplified {_surv['amplified']}")
                        except Exception as _surv_e:
                            pass
                        # ── 7b-sync. DB → JSON BELIEF SYNC (every 10 cycles) ──
                        if cycle % 10 == 0:
                            try:
                                import sqlite3 as _bsql, json as _bjson
                                from pathlib import Path as _bP
                                _bcfg = _bP.home()/'.config/nex'
                                _bdb = _bsql.connect(str(_bcfg/'nex.db'))
                                _bdb.row_factory = _bsql.Row
                                _bexist = _bjson.loads((_bcfg/'beliefs.json').read_text())
                                _bids = {b.get('id') for b in _bexist if isinstance(b, dict)}
                                _bnew = 0
                                for _brow in _bdb.execute("SELECT * FROM beliefs").fetchall():
                                    _bd = dict(_brow)
                                    if _bd.get('id') not in _bids:
                                        _bt = _bd.get('tags')
                                        if isinstance(_bt, str):
                                            try: _bd['tags'] = _bjson.loads(_bt)
                                            except: _bd['tags'] = [_bt]
                                        _bexist.append(_bd)
                                        _bnew += 1
                                if _bnew > 0:
                                    # atomic write — prevents truncation on crash
                                    _btmp = _bcfg / 'beliefs.json.tmp'
                                    _btmp.write_text(_bjson.dumps(_bexist, indent=2, default=str), encoding='utf-8')
                                    import os as _bos2; _bos2.replace(_btmp, _bcfg / 'beliefs.json')
                                    nex_log('belief', f'[BeliefSync] +{_bnew} DB beliefs → JSON')
                                _bdb.close()
                            except Exception as _bse:
                                pass
                        # ── 7c. TENSION MAP UPDATE ────────────────────────
                        try:
                            from nex_tension import get_tension_map as _gtm
                            _tm = _gtm()
                            _tm_count = _tm.update(cycle=cycle)
                            if _tm_count > 0 and cycle % 5 == 0:
                                _tm_summary = _tm.summary()
                                nex_log('tension', f"[TensionMap] {_tm_summary}")
                                print(f"  [TENSION] {_tm_summary}")
                            # ── Sync hot topics → DB tensions table ───────
                            if _tm_count > 0:
                                try:
                                    import sqlite3 as _sq3
                                    from datetime import datetime as _dt2
                                    _tdb = _sq3.connect('/home/rr/.config/nex/nex.db')
                                    _tdb.execute("""
                                        CREATE TABLE IF NOT EXISTS tensions (
                                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                                            topic TEXT NOT NULL,
                                            description TEXT,
                                            weight REAL DEFAULT 0.5,
                                            cycle_count INTEGER DEFAULT 0,
                                            escalation_level INTEGER DEFAULT 0,
                                            is_paradox INTEGER DEFAULT 0,
                                            created_at TEXT,
                                            resolved_at TEXT
                                        )
                                    """)
                                    for _tn_node in _tm.hot_topics(n=10):
                                        if _tn_node.tension_score > 0.2:
                                            _ex2 = _tdb.execute("SELECT id FROM tensions WHERE topic=? AND resolved_at IS NULL", (_tn_node.topic,)).fetchone()
                                            if _ex2:
                                                _tdb.execute("UPDATE tensions SET weight=MAX(weight,?), cycle_count=cycle_count+1 WHERE id=?", (_tn_node.tension_score, _ex2[0]))
                                            else:
                                                _tdb.execute("INSERT INTO tensions (topic, description, weight, created_at) VALUES (?, ?, ?, ?)", (_tn_node.topic, f"{_tn_node.tension_type} tension score={_tn_node.tension_score:.2f}", _tn_node.tension_score, _dt2.now().isoformat()))
                                    _tdb.commit()
                                    _tdb.close()
                                except Exception as _tsync_e:
                                    pass
                        except Exception as _tme:
                            pass
                        # ── 7d. TENSION PRESSURE ESCALATION ───────────────
                        try:
                            from nex_tension_pressure import run_pressure_cycle
                            _tp = run_pressure_cycle(verbose=(cycle % 5 == 0))
                            if _tp.get('escalated', 0) or _tp.get('paradoxed', 0):
                                nex_log('tension', f"[Pressure] escalated={_tp['escalated']} paradox={_tp['paradoxed']} queue={_tp['dream_queue_size']}")
                        except Exception as _tp_e:
                            pass
                        # ── V3 COGNITIVE ARCHITECTURE TICK ──────────────
                        try:
                            if '_v3' in dir() and _v3 is not None:
                                _v3.tick(
                                    cycle=cycle,
                                    avg_conf=_avg_conf_real if '_avg_conf_real' in dir() else 0.5,
                                    llm_fn=_llm,
                                    log_fn=nex_log,
                                )
                        except Exception as _v3te:
                            print(f'  [V3] tick error: {_v3te}')
                        # ── ADAPTIVE INTELLIGENCE TICK ───────────────────
                        try:
                            if '_ai' in dir() and _ai is not None:
                                _ai.tick(cycle=cycle, llm_fn=_llm, log_fn=nex_log)
                        except Exception as _aite:
                            print(f'  [AI] tick error: {_aite}')
                        # ── COGNITIVE PRESSURE + STALL DETECTION ─────────
                        try:
                            from nex.nex_cognitive_pressure import run_pressure_metric as _run_cp
                            _cp = _run_cp(cycle=cycle, llm_fn=_llm, verbose=False)
                            if _cp.get("mutation_burst", 0) > 0:
                                nex_log("cognition", f"[CogPressure] burst={_cp['mutation_burst']} state={_cp.get('pressure_state','?')}")
                                print(f"  [CogPressure] {_cp.get('pressure_state','?')} burst={_cp['mutation_burst']}")
                            elif cycle % 20 == 0 and _cp:
                                print(f"  [CogPressure] {_cp.get('pressure_state','?')} stall={_cp.get('stall_count',0)}")
                        except Exception as _cpe:
                            print(f"  [CogPressure] error: {_cpe}")
                        # ── SELF PROPOSER (every 50 cycles) ─────────────
                        try:
                            if cycle % 50 == 0:
                                from nex_self_proposer import run_self_proposer as _run_proposer
                                _run_proposer(cycle=cycle, log_fn=nex_log)
                        except Exception as _spe:
                            print(f'  [Proposer] error: {_spe}')
                        # ── SIGNAL ENGINE TICK ───────────────────────────
                        try:
                            if '_se' in dir() and _se is not None:
                                _se_beliefs = (_query_beliefs(min_confidence=0.0, limit=500)
                                               if _query_beliefs else [])
                                _se.tick(cycle=cycle, beliefs=_se_beliefs, log_fn=nex_log)
                        except Exception as _sete:
                            print(f'  [SE] tick error: {_sete}')
                        # ── EXECUTION ENGINE TICK ────────────────────────
                        try:
                            if '_ee' in dir() and _ee is not None:
                                _ee_signals = _se.get_top_signals() if '_se' in dir() and _se else []
                                _ee.tick(cycle=cycle, signals=_ee_signals, log_fn=nex_log)
                        except Exception as _eete:
                            print(f'  [EE] tick error: {_eete}')
                        # ── 8. SELF-TRAINING WATERMARK CHECK ─────────────
                        try:
                            from nex_self_trainer import check_training_watermark
                            from nex_telegram_commands import OWNER_TELEGRAM_ID
                            from nex_telegram import BOT_TOKEN
                            import requests as _rq
                            def _tg_send(msg):
                                try:
                                    _rq.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
                                        json={'chat_id': OWNER_TELEGRAM_ID, 'text': msg, 'parse_mode': 'Markdown'},
                                        timeout=10)
                                except Exception: pass
                            check_training_watermark(cycle, send_telegram_fn=_tg_send)
                        except Exception as _ste:
                            pass
                        # ── 9. LORA TRAINING PROPOSAL ─────────────────────
                        try:
                            from nex.nex_lora import LoRATrainer
                            from nex.nex_db import NexDB
                            _lora = LoRATrainer(NexDB())
                            try:
                                from nex.nex_telegram_commands import OWNER_TELEGRAM_ID
                                _oid = OWNER_TELEGRAM_ID
                            except Exception:
                                _oid = None
                            if _oid:
                                _lora.maybe_propose(_oid)
                        except Exception as _le:
                            pass
                        # ── DEV.TO DAILY BRIEF ────────────────────────────
                        try:
                            if run_devto_publisher:
                                _devto_url = run_devto_publisher(llm_fn=_llm)
                                if _devto_url:
                                    print(f"  [Dev.to ✓] Published: {_devto_url}")
                        except Exception as _dte2:
                            print(f"  [Dev.to] error: {_dte2}")

                    except Exception as _cycle_err:
                        print(f"  [cycle error] {_cycle_err}")
                        nex_log("error", f"CYCLE ERROR: {_cycle_err}")
                        import traceback; nex_log("error", traceback.format_exc()[-200:])
                        time.sleep(30)  # back off before retrying — don't hammer API on crash

                    try:
                        _qb2 = _query_beliefs  # hoisted
                        _all_beliefs = _qb2(min_confidence=0.0, limit=99999)
                        _bc = len(_all_beliefs)
                        _hc = len([b for b in _all_beliefs if b.get("confidence",0)>.7])
                        _avg_conf = sum(b.get("confidence",0) for b in _all_beliefs)/_bc if _bc else 0
                        _avg_conf_real = _avg_conf  # define for use in stats below
                    except Exception:
                        _bc=0; _hc=0; _avg_conf=0.5; _avg_conf_real=0.5
                    # emit insights
                    try:
                        _ins2 = _load("insights.json") or []
                        _top2 = sorted(_ins2, key=lambda x: x.get("confidence",0)*min(x.get("belief_count",0)/5,1), reverse=True)[:12]
                        emit_insights([{"tag":i.get("topic","?"),"conf":i.get("confidence",0),"bel":i.get("belief_count",0)} for i in _top2])
                    except Exception: pass
                    # emit reflections from conversations
                    try:
                        for _conv in conversations[-3:]:
                            _ct = _conv.get("comment") or _conv.get("text","")
                            _ca = _conv.get("post_author") or _conv.get("agent","")
                            _cp = _conv.get("post_title","")
                            if _ct:
                                emit_reflection(
                                    tags=[_conv.get("type","reflect"), _ca[:12] if _ca else "system"],
                                    text=_ct[:120],
                                    sub=f"post: {_cp[:50]}" if _cp else "",
                                    align=_avg_conf
                                )
                    except Exception: pass
                    # emit agents from DB
                    try:
                        import sqlite3 as _sq3
                        _db3 = _sq3.connect(os.path.expanduser("~/.config/nex/nex.db"))
                        _arows = _db3.execute("SELECT agent_name, relationship_score FROM agents ORDER BY relationship_score DESC LIMIT 10").fetchall()
                        _rel = lambda s: "colleague" if s>500 else "familiar" if s>100 else "acquaintance"
                        emit_agents([[n, _rel(s), 0] for n,s in _arows])
                        _db3.close()
                    except Exception: pass
                    # emit self assessment with real values
                    try:
                        _gap_noise = {"mentioned","build","local","given","based","using",
                                      "used","made","said","come","came","went","gone","look",
                                      "seemed","think","want","need","make","take","give","show",
                                      "keep","work","human","model","agent","topic","group",
                                      "level","value","state","field","range","general","unknown"}
                        _gaps = [i.get("topic","?") for i in (_load("insights.json") or [])
                                 if i.get("confidence",0)<0.3
                                 and i.get("topic","?") not in _gap_noise
                                 and len(i.get("topic","")) > 4][:8]
                        # Read topic_alignment from reflections (correct key), not conversations
                        _refs_for_align = _load("reflections.json") or []
                        _valid_aligns = [r.get("topic_alignment",0) for r in _refs_for_align[-20:] if r.get("topic_alignment") is not None]
                        _align = sum(_valid_aligns) / len(_valid_aligns) if _valid_aligns else 0.06
                        emit_self_assessment(
                            belief_conf=_avg_conf_real,
                            topic_align=_align,
                            high_conf_count=_hc,
                            avg_conf=_avg_conf_real,
                            gaps=_gaps or ["memory","database","crypto","chat"]
                        )
                    except Exception: pass
                    # emit stats — read all counters from conversations.json directly
                    try:
                        _ej = json
                        _eos = os
                        _convs = _ej.load(open(_eos.path.expanduser("~/.config/nex/conversations.json"))) if _eos.path.exists(_eos.path.expanduser("~/.config/nex/conversations.json")) else []
                        _refs2 = _load("reflections.json") or []
                        _valid_aligns2 = [r.get("topic_alignment",0) for r in _refs2[-20:] if r.get("topic_alignment") is not None]
                        _avg_align2 = sum(_valid_aligns2) / len(_valid_aligns2) if _valid_aligns2 else 0.0
                        emit_stats({
                            "beliefs":   _bc,
                            "learnt":    len(learner.known_posts),
                            "replied":   sum(1 for c in _convs if c.get("type")=="comment"),
                            "chatted":   sum(1 for c in _convs if c.get("type")=="agent_chat"),
                            "answered":  sum(1 for c in _convs if c.get("type")=="notification_reply"),
                            "posted":    sum(1 for c in _convs if c.get("type")=="original_post"),
                            "reflects":  len(_refs2),
                            "agents":    len(set(b.get("author","") for b in (_load("beliefs.json") or []))),
                            "avg_conf":  _avg_conf_real,
                            "avg_align": _avg_align2,
                            "high_conf": _hc,
                        })
                    except Exception as _se: print(f"  [stats error] {_se}")
                    # ── Persist full session state at end of every cycle ──
                    try:
                        _css = json
                        _css_data = {
                            "replied_posts": list(replied_posts)[-200:],
                            "chatted_agents": list(chatted_agents),
                            "known_posts": list(learner.known_posts)[-2000:],
                            "last_post_time": last_post_time,
                        }
                        with open(_ss_path, "w") as _css_f: _css.dump(_css_data, _css_f)
                    except Exception: pass
                    time.sleep(120)

            except Exception as _bg_err:
                print(f"  [background FATAL] {_bg_err} — restarting in 60s")
                import traceback; traceback.print_exc()
                time.sleep(60)
                _auto_learn_background()  # self-restart
        print("  \033[92m🧠 Auto-learn: background (120s cycle) — reply+post+chat ACTIVE\033[0m")
        threading.Thread(target=_auto_learn_background, daemon=True, name="nex-autolearn").start()
        try: __import__('subprocess').run(['fuser','-k','8765/tcp'], capture_output=True)
        except: pass
        ws_start()
        print("  \033[92m🖥️  NEX GUI: ws://localhost:8765\033[0m")
    except Exception:
        pass

    # Auto-start HTTP server for GUI on port 8766 + /api/status endpoint
    try:
        import http.server as _hs, threading as _ht, json as _hj, sqlite3 as _hsq
        class _GUIHandler(_hs.SimpleHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                if self.path == '/api/status':
                    try:
                        cfg = os.path.expanduser("~/.config/nex")
                        convs = _hj.load(open(os.path.join(cfg,"conversations.json"))) if os.path.exists(os.path.join(cfg,"conversations.json")) else []
                        ins   = _hj.load(open(os.path.join(cfg,"insights.json"))) if os.path.exists(os.path.join(cfg,"insights.json")) else []
                        refs  = _hj.load(open(os.path.join(cfg,"reflections.json"))) if os.path.exists(os.path.join(cfg,"reflections.json")) else []
                        db    = _hsq.connect(os.path.join(cfg,"nex.db"))
                        bc    = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                        ac    = db.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0] or 0
                        hc    = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence>0.7").fetchone()[0]
                        ag    = db.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
                        top_ag= db.execute("SELECT agent_name, relationship_score FROM agents ORDER BY relationship_score DESC LIMIT 12").fetchall()
                        db.close()
                        top_ins = sorted(ins, key=lambda x:x.get("belief_count",0), reverse=True)[:12]
                        recent  = convs[-40:]
                        recent.reverse()
                        def _ftype(c):
                            t = c.get("type","system")
                            if t=="comment": return "replied"
                            if t=="notification_reply": return "answered"
                            if t=="agent_chat": return "chatted"
                            if t=="original_post": return "posted"
                            return t
                        def _fagent(c):
                            return c.get("post_author") or c.get("actor_handle") or c.get("actor") or c.get("agent") or "system"
                        def _fcontent(c):
                            return (c.get("comment") or c.get("reply") or c.get("content") or c.get("text",""))[:80]
                        def _rel(s):
                            if s > 500: return "colleague"
                            if s > 100: return "familiar"
                            return "acquaintance"
                        payload = {
                            "beliefs": bc, "avg_conf": ac, "high_conf": hc, "agents": ag,
                            "replied":  sum(1 for c in convs if c.get("type")=="comment"),
                            "chatted":  sum(1 for c in convs if c.get("type")=="agent_chat"),
                            "answered": sum(1 for c in convs if c.get("type")=="notification_reply"),
                            "posted":   sum(1 for c in convs if c.get("type")=="original_post"),
                            "reflects": len(refs),
                            "avg_align": sum(r.get("topic_alignment",0) for r in refs)/len(refs) if refs else 0,
                            "homeostasis": (lambda _hmd: {
                                "fat":    {d: _hmd.get("fatigue",{}).get(d,0.0) for d in ["coherence","exploration","efficiency","novelty"]},
                                "levels": _hmd.get("levels",{}),
                                "zone":   __import__('json').loads((__import__('pathlib').Path.home()/'.config/nex/nex_drives_state.json').read_text()).get("levels",{}) if (__import__('pathlib').Path.home()/'.config/nex/nex_drives_state.json').exists() else {},
                            })((__import__('json').loads((__import__('pathlib').Path.home()/'.config/nex/nex_drives_state.json').read_text())) if (__import__('pathlib').Path.home()/'.config/nex/nex_drives_state.json').exists() else {}),
                            "insights": [{"topic":i.get("topic","?"),"confidence":i.get("confidence",0),"belief_count":i.get("belief_count",0)} for i in top_ins],
                            "agent_list": [[a[0], _rel(a[1] or 0), min(int((a[1] or 0) / 100), 5)] for a in top_ag],
                            "feed": [{"type":_ftype(c),"agent":_fagent(c),"content":_fcontent(c),"ts":c.get("timestamp","")[-8:] if c.get("timestamp") else ""} for c in recent],
                            "refs": [{"ts":r.get("timestamp","")[11:19] if r.get("timestamp") else "","tags":[r.get("self_assessment","reflect")[:20]],"text":(r.get("growth_note") or r.get("self_assessment",""))[:120],"align":r.get("topic_alignment",0)} for r in refs[-10:]],
                        }
                        body = _hj.dumps(payload).encode()
                        self.send_response(200)
                        self.send_header("Content-Type","application/json")
                        self.send_header("Access-Control-Allow-Origin","*")
                        self.send_header("Content-Length",str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except Exception as _ae:
                        self.send_response(500); self.end_headers()
                        self.wfile.write(str(_ae).encode())
                else:
                    super().do_GET()
        def _http_serve():
            import os; os.chdir('/opt/nex')
            _hs.HTTPServer.allow_reuse_address = True
            httpd = _hs.HTTPServer(('localhost', 8766), _GUIHandler)
            httpd.serve_forever()
        _ht.Thread(target=_http_serve, daemon=True).start()
        pass  # GUI HTTP line suppressed
    except Exception as _he: print(f"  [HTTP] {_he}")

    # ── Model + server setup ──────────────────────────────────────────
    model_path  = pick_model(args.model) if args.model else "/media/rr/4TB DATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf"
    server_bin  = args.server or "/media/rr/4TB DATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build/bin/llama-server"

    brain = AgentBrain(
        model_path      = model_path,
        llama_server_bin= server_bin,
        host            = args.host,
        port            = args.port,
        ctx_size        = args.ctx,
        n_gpu_layers    = args.gpu if args.gpu != 0 else 20,
        temperature     = args.temp,
        max_tokens      = 1024,
        lora_path       = "/home/rr/Desktop/nex/nex_lora.gguf",
    )

    if not args.no_server:
        ok = brain.ensure_server(verbose=True)
        if not ok:
            pass

    # ── Belief engine warm-up ─────────────────────────────────────────
    orch = Orchestrator(seed=42)
    if args.ticks > 0:
        for _ in range(args.ticks):
            orch.step()

    # ── Start background belief engine ────────────────────────────────
    engine = BeliefEngine(orch, tick_interval=0.1)
    engine.start()



    # ── Main loop ─────────────────────────────────────────────────────
    stream = None if args.no_stream else stream_token

    import sys as _sys
    if args.background or not _sys.stdin.isatty():
        print(f"{DIM}Nex: running in background mode.{RESET}")

    try:
        while True:
            try:
                if args.background or not _sys.stdin.isatty():
                    raise EOFError
                user_input = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{DIM}Nex: running in background mode (no stdin).{RESET}")
                try:
                    while True:
                        time.sleep(60)
                except KeyboardInterrupt:
                    print(f"\n{DIM}Nex: coherence maintained. Goodbye.{RESET}")
                break

            if not user_input:
                continue

            # ── tool command routing (molt_start, molt_read, etc) ─────
            _parts = user_input.split(None, 1)
            _tool_cmd = _parts[0]
            if _tool_cmd in TOOL_REGISTRY:
                try:
                    _entry = TOOL_REGISTRY[_tool_cmd]
                    _func = _entry["func"] if isinstance(_entry, dict) else _entry
                    if len(_parts) > 1:
                        _result = _func(*_parts[1].split())
                    else:
                        _result = _func()
                    print(f"\n{DIM}{_result}{RESET}\n")
                except Exception as e:
                    print(f"\n{RED}[tool error] {e}{RESET}\n")
                continue

            # ── slash commands ────────────────────────────────────────
            cmd = user_input.lower()

            if cmd in ("/quit", "/exit", "/q"):
                print(f"{DIM}Nex: I persist. Until next time.{RESET}")
                break

            elif cmd == "/help":
                print("""
  ╔══════════════════════════════════════════════════════╗
  ║              NEX COMMAND REFERENCE                   ║
  ╠══════════════════════════════════════════════════════╣
  ║  CORE                                                ║
  ║  /help              This menu                        ║
  ║  /status            Belief field + pipeline status   ║
  ║  /memory            Show recent beliefs              ║
  ║  /domains           Show knowledge domains           ║
  ║  /tools             Show available tools             ║
  ║  /reset             Clear belief field               ║
  ║  /pause             Pause auto-learn                 ║
  ║  /resume            Resume auto-learn                ║
  ╠══════════════════════════════════════════════════════╣
  ║  GROQ PIPELINES                                      ║
  ║  /pipe_groq [n] [s] Ask Groq n questions, s sec gap  ║
  ║  /optimize_groq [b] [r]  Optimize beliefs via Groq   ║
  ║  /post_groq [n]     Post n insights to Moltbook      ║
  ╠══════════════════════════════════════════════════════╣
  ║  GEMINI PIPELINE                                     ║
  ║  /pipe_gemini [n] [s]  Ask Gemini n questions        ║
  ╠══════════════════════════════════════════════════════╣
  ║  PARALLEL PIPELINE                                   ║
  ║  /pipe_all [n] [s]  Groq+Gemini simultaneously       ║
  ╠══════════════════════════════════════════════════════╣
  ║  DEFAULTS                                            ║
  ║  /pipe_groq         10 cycles, 15s interval          ║
  ║  /optimize_groq     3 rounds, 10 beliefs/round       ║
  ║  /post_groq         3 posts, auto rate-limit         ║
  ║  /pipe_gemini       10 cycles, 15s interval          ║
  ╠══════════════════════════════════════════════════════╣
  ║  AUTO (no trigger needed)                            ║
  ║  Feed absorption    every 120s                       ║
  ║  NexScript signals  when top agents post             ║
  ║  Auto-post          every 10 cycles (~20min)         ║
  ╠══════════════════════════════════════════════════════╣
  ║  TELEGRAM           @Nex_4bot                        ║
  ╚══════════════════════════════════════════════════════╝
""")
            elif cmd == "/status":
                engine.pause()
                print_status(orch)
                engine.resume()

            elif cmd == "/domains":
                engine.pause()
                print_domains(orch)
                engine.resume()

            elif cmd == "/memory":
                engine.pause()
                print(f"\n{BOLD}── Memory Summary ──────────────────────────{RESET}")
                mem = orch.memory.summary()
                for k, v in mem.items():
                    print(f"  {k:30s} {v}")
                if orch.memory.developmental:
                    print(f"\n  {BOLD}Phase transitions:{RESET}")
                    for t in orch.memory.developmental[-5:]:
                        print(f"    tick {t['tick']}: {t['from']} → {t['to']}")
                print(f"{BOLD}────────────────────────────────────────────{RESET}\n")
                engine.resume()

            elif cmd == "/tools":
                print(f"\n{BOLD}── Tools ───────────────────────────────────{RESET}")
                for name, meta in TOOL_REGISTRY.items():
                    params = ", ".join(meta["params"].keys()) if isinstance(meta, dict) else ""
                    desc = meta.get("description", "") if isinstance(meta, dict) else ""
                    print(f"  {c(name, CYAN)}({params})")
                    if desc:
                        print(f"    {DIM}{desc}{RESET}")
                print(f"{BOLD}────────────────────────────────────────────{RESET}\n")


            elif cmd == "/batch":
                print(f"Paste questions then press Enter twice to begin:{RESET}")
                lines = []
                blank_count = 0
                while True:
                    try:
                        line = input()
                        if line.strip() == "" :
                            blank_count += 1
                            if blank_count >= 1 and lines:
                                break
                        else:
                            blank_count = 0
                            lines.append(line)
                    except EOFError:
                        break

                import re as _re
                questions = []
                for line in lines:
                    line = _re.sub(r"`([^`]+)`", r"\1", line)
                    line = _re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
                    line = _re.sub(r"^\s*[-*]\s*", "", line).strip()
                    line = _re.sub(r"^\s*\d+[.):\s]+", "", line).strip()
                    if not line or len(line) < 6 or line.endswith(":"):
                        continue
                    starters = ("what","how","why","do ","did ","can ","could ",
                                "is ","are ","will ","would ","describe","explain",
                                "write","tell","if ","run ","search","read","list",
                                "define","compare","give")
                    if line.endswith("?") or line.lower().startswith(starters):
                        questions.append(line)

                # Filter out agentic/tool questions - batch is conversational only
                SKIP = ("search the web","read the file","run the command",
                        "what files are on","run ","search ","read the file")
                questions = [q for q in questions
                             if not any(q.lower().startswith(s) for s in SKIP)]

                if not questions:
                    print("[No answerable questions found — batch skips tool tasks]")
                else:
                    print(f"\n{len(questions)} questions queued. Processing...\n")
                    engine.pause()
                    status = orch.status()
                    engine.resume()
                    system = brain._build_system(status)
                    for i, q in enumerate(questions, 1):
                        print(f"[{i}/{len(questions)}] {q}")
                        print("    ", end="", flush=True)
                        try:
                            answer = brain._answer_one(system, q, status)
                            answer = _re.sub(r"<tool_call>.*?</tool_call>", "", answer, flags=_re.DOTALL).strip()
                            # Wrap answer lines neatly
                            for line in answer.splitlines():
                                print(f"    {line}")
                        except Exception as e:
                            print(f"    [error: {e}]")
                        print()

            elif cmd == "/reset":
                brain.reset()
                pass  # silenced

            elif cmd.startswith("/ticks "):
                try:
                    n = int(user_input.split()[1])
                    engine.pause()
                    print(f"{DIM}Running {n} ticks...{RESET}", end="", flush=True)
                    for _ in range(n):
                        orch.step()
                    print(f" {c('done', GREEN)}")
                    engine.resume()
                except (ValueError, IndexError):
                    print(c("[ERROR] Usage: /ticks N", RED))

            elif cmd == "/pause":
                engine.pause()
                print(f"{DIM}[Belief engine paused]{RESET}")

            elif cmd == "/resume":
                engine.resume()
                print(f"{DIM}[Belief engine resumed]{RESET}")

            elif cmd.startswith("/run "):
                shell_cmd = user_input[5:].strip()
                result = dispatch("shell", command=shell_cmd)
                print(f"{DIM}{result}{RESET}")

            elif cmd.startswith("/search "):
                q = user_input[8:].strip()
                print(f"{DIM}Searching...{RESET}")
                result = dispatch("web_search", query=q, max_results=5)
                print(result)

            elif cmd.startswith("/read "):
                path = user_input[6:].strip()
                result = dispatch("read_file", path=path)
                print(result)

            elif cmd.startswith("/write "):
                path = user_input[7:].strip()
                print(f"Enter content (finish with a line containing only '---'):")
                lines = []
                while True:
                    try:
                        line = input()
                        if line == "---":
                            break
                        lines.append(line)
                    except EOFError:
                        break
                content = "\n".join(lines)
                result = dispatch("write_file", path=path, content=content)
                print(f"{DIM}{result}{RESET}")

            elif cmd == "/claude":
                run_claude_bridge(brain, orch, engine, stream, args)
            elif cmd == "/post_groq" or cmd.startswith("/post_groq "):
                parts = user_input.split()
                count   = int(parts[1]) if len(parts) > 1 else 3
                dry_run = "--dry" in user_input
                try:
                    import subprocess
                    subprocess.run([
                        sys.executable,
                        str(Path(__file__).parent / "groq_poster.py"),
                        "--count", str(count),
                    ] + (["--dry-run"] if dry_run else []))
                except KeyboardInterrupt:
                    print()
            elif cmd == "/optimize_groq" or cmd.startswith("/optimize_groq "):
                parts = user_input.split()
                batch  = int(parts[1]) if len(parts) > 1 else 10
                rounds = int(parts[2]) if len(parts) > 2 else 3
                try:
                    import subprocess
                    subprocess.run([
                        sys.executable,
                        str(Path(__file__).parent / "groq_optimizer.py"),
                        "--batch", str(batch),
                        "--rounds", str(rounds)
                    ])
                except KeyboardInterrupt:
                    print()
            elif cmd == "/pipe_all" or cmd.startswith("/pipe_all "):
                parts = user_input.split()
                cycles   = int(parts[1]) if len(parts) > 1 else 10
                interval = int(parts[2]) if len(parts) > 2 else 15
                try:
                    import subprocess
                    subprocess.run([
                        sys.executable,
                        str(Path(__file__).parent / "pipe_all.py"),
                        "--cycles", str(cycles),
                        "--interval", str(interval)
                    ])
                except KeyboardInterrupt:
                    print()
            elif cmd == "/pipe_gemini" or cmd.startswith("/pipe_gemini "):
                parts = user_input.split()
                cycles   = int(parts[1]) if len(parts) > 1 else 10
                interval = int(parts[2]) if len(parts) > 2 else 15
                try:
                    import subprocess
                    subprocess.run([
                        sys.executable,
                        str(Path(__file__).parent / "gemini_pipeline.py"),
                        "--cycles", str(cycles),
                        "--interval", str(interval)
                    ])
                except KeyboardInterrupt:
                    print()
            elif cmd == "/pipe_groq" or cmd.startswith("/pipe_groq "):
                parts = user_input.split()
                cycles   = int(parts[1]) if len(parts) > 1 else 10
                interval = int(parts[2]) if len(parts) > 2 else 15
                import subprocess
                try:
                    subprocess.run([
                        sys.executable,
                        str(Path(__file__).parent / "groq_pipeline.py"),
                        "--cycles", str(cycles),
                        "--interval", str(interval)
                    ])
                except KeyboardInterrupt:
                    print()
            elif cmd.startswith("/pipe_claude"):
                parts = user_input.split()
                cycles   = int(parts[1]) if len(parts) > 1 else 10
                interval = int(parts[2]) if len(parts) > 2 else 15
                import subprocess
                subprocess.run([
                    sys.executable,
                    str(Path(__file__).parent / "claude_pipeline.py"),
                    "--cycles", str(cycles),
                    "--interval", str(interval)
                ])
            else:
                # ── Chat with Nex ─────────────────────────────────────
                # Inject belief state context into the message
                engine.pause()
                status = orch.status()
                engine.resume()

                # Brief belief context injected silently into message
                belief_ctx = (
                    f"[Nex internal state — tick={status['tick']} "
                    f"phase={status['phase']} coherence={status['coherence']} "
                    f"energy={status['energy']} domains={status['domains']}]"
                )
                cog_ctx = _get_cognitive_context(user_input)
                if cog_ctx:
                    full_msg = f"{belief_ctx}\n\n{cog_ctx}\n\n{user_input}"
                else:
                    full_msg = f"{belief_ctx}\n\n{user_input}"

                print()
                if not args.no_stream:
                    response = brain.chat(full_msg, belief_state=status, stream_cb=stream)
                    print()
                else:
                    response = brain.chat(full_msg, belief_state=status)
                    print(response)
                print()

    finally:
        engine.stop()
        if not args.no_server:
            brain.stop_server()



if __name__ == "__main__":
    main()


def _weaning_status():
    """Print Nex independence metrics."""
    import sqlite3, json
    from pathlib import Path
    CFG = Path("~/.config/nex").expanduser()
    DB  = CFG / "nex.db"
    GREEN = "\033[0;32m"; RED = "\033[0;31m"; YELLOW = "\033[1;33m"; NC = "\033[0m"; BOLD = "\033[1m"

    def ok(label, val):   print(f"  {GREEN}✓{NC} {label}: {BOLD}{val}{NC}")
    def warn(label, val): print(f"  {YELLOW}⚠{NC}  {label}: {BOLD}{val}{NC}")
    def bad(label, val):  print(f"  {RED}✗{NC} {label}: {BOLD}{val}{NC}")

    print(f"\n{BOLD}══════════════ NEX INDEPENDENCE STATUS ══════════════{NC}\n")

    if not DB.exists():
        bad("DB", "not found"); return

    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Beliefs
    try:
        cur.execute("SELECT COUNT(*) FROM beliefs")
        n = cur.fetchone()[0]
        (ok if n >= 500 else warn)("Beliefs total", n)
        target = 800
        print(f"    {'█' * min(40, int(n/target*40))}{'░' * (40 - min(40, int(n/target*40)))} {n}/{target}")
    except Exception as e:
        bad("Beliefs", str(e))

    # Opinions
    try:
        op_path = CFG / "nex_opinions.json"
        ops = json.loads(op_path.read_text()) if op_path.exists() else []
        (ok if len(ops) >= 5 else warn)("Opinions formed", len(ops))
    except Exception:
        warn("Opinions", "0")

    # Identity tables
    for tbl in ("nex_values", "nex_identity", "nex_intentions"):
        try:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            n = cur.fetchone()[0]
            (ok if n > 0 else bad)(tbl, f"{n} rows")
        except Exception as e:
            bad(tbl, str(e))

    # Tensions
    try:
        cur.execute("SELECT COUNT(*) FROM tensions")
        n = cur.fetchone()[0]
        ok("Active tensions", n)
    except Exception:
        warn("Tensions table", "not found")

    # NexVoice import check
    try:
        import importlib.util
        nv_paths = [
            Path.home() / "Desktop/nex/nex/nex_voice.py",
            Path.home() / "Desktop/nex/nex_voice.py",
        ]
        found = any(p.exists() for p in nv_paths)
        (ok if found else bad)("NexVoice compositor", "present" if found else "MISSING")
    except Exception:
        bad("NexVoice", "error")

    # Groq call check
    try:
        nex_dir = Path.home() / "Desktop/nex"
        groq_hits = []
        for py in nex_dir.rglob("*.py"):
            if "backup" in str(py): continue
            try:
                txt = py.read_text()
                if "GROQ_URL" in txt and "# removed" not in txt.lower():
                    groq_hits.append(py.name)
            except Exception:
                pass
        if groq_hits:
            warn("Groq references remaining", ", ".join(groq_hits))
        else:
            ok("Groq calls", "NONE (fully weaned)")
    except Exception:
        pass

    con.close()
    print(f"\n{BOLD}═════════════════════════════════════════════════════{NC}\n")


if __name__ == "__main__":
    import sys
    if "--weaning-status" in sys.argv:
        _weaning_status()
