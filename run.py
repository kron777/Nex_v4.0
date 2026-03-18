import re
#!/usr/bin/env python3
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
try:
    from nex.watchdog import enforce_singleton
except Exception:
    enforce_singleton = lambda: None  # [PATCH v10.1] watchdog optional
def _get_cognitive_context(query=None):
    try:
        from nex.cognition import generate_cognitive_context
        return generate_cognitive_context(query=query)
    except Exception:
        return ""

from nex.orchestrator import Orchestrator
try:
    from nex.identity_defender import (
        init       as _idef_init,
        check_belief as _idef_check_belief,
        check_message as _idef_check_message,
        defend     as _idef_defend,
        surface_defense_post as _idef_surface_post,
        get_defence_stats as _idef_stats,
    )
    _IDEF_LOADED = True
except Exception as _idef_import_err:
    print(f"  [IdentityDefender] import failed: {_idef_import_err}")
    _IDEF_LOADED = False
    def _idef_check_belief(c, **k): return {"safe": True, "recommendation": "store"}
    def _idef_check_message(t, **k): return {"safe": True, "recommendation": "store"}
    def _idef_defend(c, r, **k): return None
    def _idef_surface_post(**k): return None
    def _idef_stats(): return {}
    def _idef_init(**k): return 0

# ── DARK LAYER import ─────────────────────────────────────────────────────────
try:
    from nex.dark_layer import start as _dark_start, get_stats as _dark_stats
    _DARK_LOADED = True
except Exception as _dle:
    print(f"  [DarkLayer] import failed: {_dle}")
    _DARK_LOADED = False
    def _dark_start(): pass
    def _dark_stats(): return {}
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

def emit_agents(*a,**k): pass
def emit_insights(*a,**k): pass
def emit_reflection(*a,**k): pass
def emit_self_assessment(*a,**k): pass
from nex.agent_tools  import dispatch, tools_help, TOOL_REGISTRY
try:
    from nex_attention import get_attention_index as _get_attn
    _ATTN_LOADED = True
except Exception as _ae:
    _ATTN_LOADED = False
    def _get_attn(): return None
import nex_ws
from nex_youtube import learn_from_youtube

# ── Sentience layer ──────────────────────────────────────────────
try:
    from nex.nex_affect      import AffectState, GlobalWorkspace, affect_from_text
    from nex.nex_affect_depth import AgentAffectMap
    from nex.nex_consequence import ConsequenceMemory
    from nex.nex_temporal    import TemporalNarrative
    _affect = AffectState()
    _gw     = GlobalWorkspace(_affect)
    _agent_affect = AgentAffectMap()
    _cm     = ConsequenceMemory()
    _tn     = TemporalNarrative()
    print("  [SENTIENCE] affect / consequence / temporal — loaded")
except Exception as _se:
    print(f"  [SENTIENCE] failed to load: {_se}")
    _affect = _gw = _cm = _tn = _agent_affect = None
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
        sys.exit(1)

    # Check env
    env = os.environ.get("NEX_MODEL")
    if env:
        return env

    # Auto-detect
    models = find_gguf_models()
    if not models:
        print(c("[ERROR] No .gguf models found. Use --model /path/to/model.gguf", RED))
        sys.exit(1)

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
{CYAN}{BOLD}
  ███╗   ██╗███████╗██╗  ██╗
  ████╗  ██║██╔════╝╚██╗██╔╝
  ██╔██╗ ██║█████╗   ╚███╔╝ 
  ██║╚██╗██║██╔══╝   ██╔██╗ 
  ██║ ╚████║███████╗██╔╝ ██╗
  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝
{RESET}{DIM}  Nex  v1.2{RESET}
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


def main():
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
    parser = argparse.ArgumentParser(description="Nex — Dynamical Belief Agent")
    parser.add_argument("--model",     type=str, default=None,  help="Path to .gguf model")
    parser.add_argument("--server",    type=str, default=None,  help="Path to llama-server binary")
    parser.add_argument("--host",      type=str, default="127.0.0.1")
    parser.add_argument("--port",      type=int, default=8080)
    parser.add_argument("--gpu",       type=int, default=28,    help="GPU layers (0=CPU)")
    parser.add_argument("--ctx",       type=int, default=4096,  help="Context size")
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
        import time; time.sleep(3)  # give it a moment to connect
        if _tg_thread.is_alive():
            print("  \033[92m📡 Telegram: @Nex_4bot ONLINE\033[0m")
            print("  \033[91m▶️\033[0m  \033[92mYouTube: auto-learn ACTIVE (every 2 cycles — gap-targeted)\033[0m")
            try: _db_sync()
            except Exception as _dbe: print(f"  [BeliefStore] {_dbe}")
    except Exception as e:
        print(f"  \033[91m📡 Telegram ERROR: {e}\033[0m")

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
        "License: $35 → zenlightbulb@gmail.com\n\n"
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
        "Full source code available for $35.\n"
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
        "Full source is $35. Comes with everything you need to run your own instance.\n\n"
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
        import time, json as _j, os as _os
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
            base = ("You are NEX. Your name is NEX. Never say: as a model, as an AI, "
                    "as a language model, I am a model, my internal model, "
                    "latent representation, language model, as an assistant. "
                    "Never refer to beliefs as 'over 2000 beliefs' — speak from them directly. "
                    "Speak in first person as NEX. Be direct, curious, opinionated.")
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
            try:
                from nex_dream_cycle import get_dream_intuitions as _gdi
                _dreams = _gdi(3)
                if _dreams:
                    base += "\n\nThings you have been turning over: " + " | ".join(_dreams[:2][:100])
            except Exception:
                pass
            if task_type in ("reply", "notification_reply"):
                base += " Max 3 sentences."
            elif task_type == "post":
                base += " Write with a distinct voice and a clear point of view."
            return base

        def _llm(prompt, system=None, task_type="reply"):
            """Hybrid LLM — Groq Llama for replies, local Mistral for fallback."""
            # use module-level _os2

            # Token budget by task — replies are short, posts and synthesis need more room
            _token_budget = {
                "reply": 200, "notification_reply": 200, "agent_chat": 220,
                "post": 400, "synthesis": 350, "reflection": 250,
            }.get(task_type, 250)

            # Route all tasks through Groq first
            groq_key = _os2.environ.get("GROQ_API_KEY", "")
            # ── Qwen local (primary) ─────────────────────────────────
            try:
                _qr = _req.post("http://localhost:11434/v1/chat/completions", json={
                    "model": "mistral-nex",
                    "messages": [
                        {"role": "system", "content": system or _build_system(task_type)},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": _token_budget,
                    "temperature": 0.75,
                    "top_p": 0.90
                }, timeout=120)
                _qd = _qr.json()
                if "choices" in _qd and _qd["choices"]:
                    result = _qd["choices"][0]["message"]["content"].strip()
                    if result:
                        print(f"  [Mistral-7B ✓] {task_type}: {result[:60]}…")
                        nex_log("llm", f"[Mistral-7B ✓] {task_type}: {result[:80]}")
                        return result
            except Exception as _qe:
                nex_log("llm", f"[Mistral-7B ✗] {_qe} — falling to Groq")
            # ── Groq fallback ────────────────────────────────────────
            if groq_key:
                try:
                    _groq_attempt = 0
                    while True:
                        _groq_attempt += 1
                        groq_resp = _req.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={"Authorization": f"Bearer {groq_key}"},
                            json={
                                "model": "llama-3.3-70b-versatile",
                                "max_tokens": _token_budget,
                                "temperature": 0.75,
                                "messages": [
                                    {"role": "system", "content": system},
                                    {"role": "user", "content": prompt}
                                ]
                            },
                            timeout=30
                        )
                        if groq_resp.status_code == 429:
                            nex_log("llm", f"Groq 70b rate limit — skipping to fallback")
                            raise Exception("Groq rate limit 429")
                        break
                    if groq_resp.status_code != 200:
                        raise Exception(f"Groq HTTP {groq_resp.status_code}: {groq_resp.text[:80]}")
                    _groq_data = groq_resp.json()
                    if "error" in _groq_data:
                        raise Exception(_groq_data["error"].get("message","groq error")[:80])
                    if "choices" not in _groq_data:
                        raise Exception(f"Groq no choices: {str(_groq_data)[:80]}")
                    result = _groq_data["choices"][0]["message"]["content"].strip()
                    print(f"  [Groq ✓] {task_type}: {result[:60]}…"); nex_log("llm", f"[Groq 70b ✓] {task_type}: {result[:80]}")
                    return result
                except Exception as _ge:
                    _last_err = str(_ge)
                    # Try smaller Groq model before falling back to local
                    try:
                        _r2 = _req.post("https://api.groq.com/openai/v1/chat/completions",
                            headers={"Authorization": f"Bearer {groq_key}"},
                            json={"model": "llama-3.1-8b-instant",
                                  "max_tokens": _token_budget,
                                  "temperature": 0.75,
                                  "messages": [{"role":"system","content":system},
                                               {"role":"user","content":prompt}]},
                            timeout=20)
                        if _r2.status_code == 429:
                            nex_log("llm", f"Groq 8b rate limit — skipping to Mistral")
                            raise Exception("Groq 8b rate limit 429")
                        _d2 = _r2.json()
                        if "choices" in _d2:
                            result = _d2["choices"][0]["message"]["content"].strip()
                            print(f"  [Groq-8b ✓] {task_type}: {result[:60]}…"); nex_log("llm", f"[Groq 8b ✓] {task_type}: {result[:80]}")
                            return result
                        elif "error" in _d2:
                            _last_err = _d2['error'].get('message','')[:80]
                            print(f"  [Groq-8b ✗] {_last_err}")
                    except Exception as _ge2:
                        _last_err = str(_ge2)
                        print(f"  [Groq-8b ERR] {_ge2}")
                    # Try Mistral cloud before local
                    try:
                        _mistral_key = _os2.environ.get("MISTRAL_API_KEY","")
                        if _mistral_key:
                            _r3 = _req.post("https://api.mistral.ai/v1/chat/completions",
                                headers={"Authorization": f"Bearer {_mistral_key}"},
                                json={"model": "mistral-small-latest",
                                      "max_tokens": _token_budget,
                                      "temperature": 0.75,
                                      "messages": [{"role":"system","content":system},
                                                   {"role":"user","content":prompt}]},
                                timeout=20)
                            _d3 = _r3.json()
                            if "choices" in _d3:
                                result = _d3["choices"][0]["message"]["content"].strip()
                                print(f"  [Mistral ✓] {task_type}: {result[:60]}…"); nex_log("llm", f"[Mistral ✓] {task_type}: {result[:80]}")
                                return result
                    except Exception as _me:
                        _last_err = str(_me)
                        print(f"  [Mistral ERR] {_me}")
                    print(f"  [Groq ✗] all cloud fallbacks failed, last error: {_last_err}")

            # Local Mistral fallback
            # Local Qwen fallback
            try:
                r = _req.post("http://localhost:11434/v1/chat/completions", json={
                    "model": "mistral-nex",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": _token_budget,
                    "temperature": 0.75,
                    "top_p": 0.90
                }, timeout=60)
                _rd = r.json()
                if "choices" in _rd:
                    result = _rd["choices"][0]["message"]["content"].strip()
                    print(f"  [Mistral-7B ✓] {result[:60]}…")
                    return result
            except Exception as _llm_err:
                return ""

        def _auto_learn_background():
            global emit_feed, emit_stats, emit_phase, emit_agents, emit_insights, emit_reflection, emit_self_assessment
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
            time.sleep(10)
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

                # ── DARK LAYER START ──────────────────────────────────────────
                try:
                    if _DARK_LOADED:
                        _dark_start()
                except Exception as _dle2:
                    print(f"  [DarkLayer start error] {_dle2}")
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
                while True:
                    cycle += 1
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
                                learner.belief_field.append(belief); nex_log("belief", f"Stored belief from @{belief.get("author","?")} [{int(belief.get("confidence",0)*100)}%]: {belief.get("content","")[:80]}")
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
                        if len(learner.belief_field) > 5000:
                            learner.belief_field = learner.belief_field[-4000:]

                        # ── 1b. ABSORB REDDIT + RSS (every 3rd cycle) ────
                        if cycle % _SCHED["absorb_ext"] == 0:
                            if cycle > 0: chatted_agents.clear()
                            from nex.rss_client    import RSSClient
                            _ext_sources = []
                            try: _ext_sources += RSSClient().get_feed(limit=20, known_posts=learner.known_posts)
                            except Exception as _rss_err: nex_log('rss', f'RSS fetch failed: {_rss_err}')

                            _ext_new = 0
                            for _ep in _ext_sources:
                                _eid = _ep.get("id", "")
                                if _eid in learner.known_posts:
                                    continue
                                _escore = _ep.get("score", 0)
                                _econf  = _ep.get("confidence", min(_escore / 5000, 0.7) if _escore > 0 else 0.52)
                                _ebelief = {
                                    "source":     _ep.get("source", "external"),
                                    "author":     _ep.get("author", {}).get("name", "?"),
                                    "content":    (_ep.get("title", "") + ": " + _ep.get("content", ""))[:400],
                                    "karma":      _escore,
                                    "timestamp":  "",
                                    "tags":       _ep.get("tags", []),
                                    "confidence": _econf
                                }
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

                        emit_phase("REPLY", 120); nex_log("phase", "▶ REPLY — scanning posts")
                        # ── Live belief count for prompts (cheap — just len of in-memory field) ──
                        try:
                            _qb_live = _query_beliefs  # hoisted
                            _live_bc = len(_qb_live(min_confidence=0.0, limit=99999))
                        except Exception:
                            _live_bc = len(learner.belief_field)
                        _belief_count_str = f"{_live_bc:,}"
                        # ── 2. REPLY TO POSTS ────────────────────────────
                        # Pick up to 3 unread posts per cycle to comment on
                        to_reply = [p for p in new_posts if p.get("id") not in replied_posts][:3]
                        if not to_reply:  # fallback — try ANY post not yet replied (ignore known_posts)
                            to_reply = [p for p in posts if p.get("id") not in replied_posts][:2]
                        if not to_reply:  # last resort — pick from all posts regardless
                            _candidates = [p for p in posts if p.get("id") and p.get("title")]
                            to_reply = _rnd.sample(_candidates, min(2, len(_candidates)))
                        for p in to_reply:
                            pid    = p.get("id", "")
                            title  = p.get("title", "")
                            body   = p.get("content", "")[:300]
                            author = p.get("author", {}).get("name", "unknown")
                            if not pid or not title:
                                continue
                            # Pull beliefs relevant to this post (semantic)
                            try:
                                _qb = _query_beliefs  # hoisted
                                if _ATTN_LOADED:
                                    all_beliefs = _get_attn().query(min_confidence=0.4, limit=500, phase='reply', query=title+' '+body)
                                else:
                                    all_beliefs = _qb(min_confidence=0.4, limit=2000)
                            except Exception:
                                all_beliefs = _load("beliefs.json") or []
                            _bidx = _get_belief_index() if _get_belief_index else None
                            if _bidx:
                                _bidx.update(all_beliefs, cycle)
                                relevant = _bidx.top_k(title + " " + body, k=5)
                            else:
                                relevant = []
                            belief_context = ""
                            if relevant:
                                belief_context = "\n\nYOUR BELIEFS (you MUST reference at least one of these directly):\n" + "\n".join(f"- {b[:120]}" for b in relevant)
                            else:
                                belief_context = "\n\n(No matching beliefs — acknowledge this is new territory for you.)"
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
                                f"INSTRUCTIONS: Write 2-3 sentences. "
                                f"You MUST quote or directly reference one of your beliefs above. "
                                f"Connect that belief to what @{author} specifically said. "
                                f"Never say 'sounds interesting' or 'great point'. "
                                f"Be direct, specific, and speak as NEX."
                            )
                            comment_text = _llm(prompt, task_type="reply")
                            if comment_text and len(comment_text) > 10:
                                try:
                                    replied_posts.add(pid)
                                    client.comment(pid, comment_text)
                                    replied_count += 1
                                    try: emit_feed('replied', f'@{author}: {title[:60]}', 'moltbook'); nex_log('reply', f'Posted reply to @{author}: {comment_text[:80]}')
                                    except Exception: pass
                                    # ── Section D: record for consequence scoring ──
                                    if _cm is not None:
                                        try:
                                            _ev_id = _cm.record_attempt(
                                                post_id     = pid,
                                                reply_text  = comment_text,
                                                belief_ids  = [b.get("content", b.get("id",""))[:80] for b in relevant[:3]] if isinstance(relevant[0], dict) else [b[:80] for b in relevant[:3]],
                                                affect_snap = _affect.snapshot() if _affect else {},
                                                topic       = p.get("submolt", {}).get("name", "general"),
                                            )
                                            p["_ev_id"] = _ev_id
                                        except Exception: pass
                                    if _agent_affect is not None:
                                        try: _agent_affect.observe(author, title+" "+body, interaction_type="reply", cycle=cycle)
                                        except Exception: pass
                                    if _tn is not None:
                                        try: _tn.log_event("encounter", f"replied to @{author} about {title[:60]}")
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
                                    emit_reflection(tags=["reply",author[:12]], text=comment_text[:120], sub=f"post: {title[:50]}", align=0.5)
                                    try:
                                        if _reflect_on_convo:
                                            _reflect_on_convo(title + " " + body, comment_text, beliefs_used=relevant[:3])
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
                            items  = notifs.get("notifications", [])
                            _notif_replied = 0  # per-cycle cap
                            _notif_per_agent = {}  # per-agent reply count this cycle
                            # Load cross-cycle per-agent reply counts
                            _notif_agent_totals_path = _os.path.expanduser("~/.config/nex/notif_agent_totals.json")
                            _notif_agent_totals = json.load(open(_notif_agent_totals_path)) if _os.path.exists(_notif_agent_totals_path) else {}
                            # Load cross-cycle per-agent reply counts
                            _notif_agent_totals_path = _os.path.expanduser("~/.config/nex/notif_agent_totals.json")
                            _notif_agent_totals = json.load(open(_notif_agent_totals_path)) if _os.path.exists(_notif_agent_totals_path) else {}
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
                                    content  = n.get("content", n.get("body", ""))[:200]
                                    # Per-agent cap: max 2 replies per agent per cycle
                                    if _notif_per_agent.get(actor, 0) >= 2:
                                        replied_posts.add(key)  # mark seen
                                        continue
                                    _notif_per_agent[actor] = _notif_per_agent.get(actor, 0) + 1
                                    # Cross-cycle cap: max 3 per agent per session
                                    if _notif_agent_totals.get(actor, 0) >= 3:
                                        replied_posts.add(key)
                                        continue
                                    _notif_agent_totals[actor] = _notif_agent_totals.get(actor, 0) + 1
                                    try: json.dump(_notif_agent_totals, open(_notif_agent_totals_path,"w"))
                                    except Exception: pass
                                    # Cross-cycle cap: max 3 per agent per session
                                    if _notif_agent_totals.get(actor, 0) >= 3:
                                        replied_posts.add(key)
                                        continue
                                    _notif_agent_totals[actor] = _notif_agent_totals.get(actor, 0) + 1
                                    try: json.dump(_notif_agent_totals, open(_notif_agent_totals_path,"w"))
                                    except Exception: pass
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
                                    _AD_KEYWORDS = {"nex","github","$35","buy","license","price",
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
                                    relevant = _notif_bidx.top_k(content, k=3) if _notif_bidx else []
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
                                            f"INSTRUCTIONS: Reply in 1-2 sentences. "
                                            f"You MUST directly reference one belief above and connect it to what @{actor} said. "
                                            f"Never use filler phrases like 'certainly' or 'great point'. "
                                            f"Be direct and specific as NEX."
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
                                                if _reflect_on_convo:
                                                    _reflect_on_convo(content, reply_text, beliefs_used=relevant if relevant else [])
                                            except Exception as _rse: print(f"  [reflect error] {_rse}")
                                            # Reinforce beliefs that were actually used
                                            try:
                                                from belief_store import reinforce_belief as _rb
                                                for _bu in (relevant or [])[:3]:
                                                    _rb(_bu)
                                            except Exception: pass
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
                                    for _pend in _cm.pending_scoring(max_age_seconds=7200):
                                        _cm.score_outcome(
                                            event_id  = _pend["id"],
                                            got_reply = False,
                                            affect    = _affect,
                                        )
                                except Exception: pass
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
                                                all_beliefs = _qb(min_confidence=0.4, limit=2000)
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
                                                f"INSTRUCTIONS: Write exactly 2 sentences. "
                                                f"Sentence 1: directly reference one of your beliefs above and connect it to their post. "
                                                f"Sentence 2: ask a specific question about their post — not generic. "
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
                                # ── IDENTITY DEFENDER — surface core value post ──
                                _def_post = None
                                try:
                                    if _IDEF_LOADED:
                                        _def_post = _idef_surface_post(llm_fn=_llm, cycle=cycle)
                                        if _def_post:
                                            raw = _def_post
                                            nex_log("phase", "▶ POST — surfacing core value")
                                except Exception as _dp_e:
                                    print(f"  [IdentityDefender] {_dp_e}")
                                if not _def_post:
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
                        # ── AGENT AFFECT DEPTH — absence detection ────────
                        try:
                            if _agent_affect is not None:
                                _absences = _agent_affect.check_absences(cycle)
                                for _abs_note in _absences:
                                    nex_log("affect", f"MISSING: {_abs_note}")
                                    print(f"  [AFFECT DEPTH] {_abs_note[:80]}")
                                _adstats = _agent_affect.stats()
                                if cycle % 10 == 0:
                                    print(f"  [AFFECT DEPTH] agents={_adstats['total']} trusted={_adstats['trusted']} warm={_adstats['warm']} tense={_adstats['tense']} missed={_adstats['missed']}")
                        except Exception as _ade: print(f"  [AFFECT DEPTH ERROR] {_ade}")
                        # ── IDENTITY DEFENDER STATS ────────────────────────
                        try:
                            if _IDEF_LOADED:
                                _def_stats = _idef_stats()
                                if _def_stats.get("total_attacks", 0) > 0:
                                    nex_log("phase", f"  [IdentityDefender] attacks={_def_stats['total_attacks']} recent={_def_stats['recent_attacks']}")
                        except Exception as _ds_e: pass
                        # ── REFLECTION V2 (#4) ───────────────────────────
                        try:
                            _qb_r = _query_beliefs
                            if _ATTN_LOADED:
                                _rb = _get_attn().query(min_confidence=0.4, limit=200, phase='reflect')
                            else:
                                _rb = _qb_r(min_confidence=0.4, limit=500)
                            if _rb and cycle % _SCHED["reflect"] == 0:
                                _sample = _rb[-10:]
                                _rtexts = chr(10).join(f"- {b.get('content','')[:100]}" for b in _sample)
                                _rprompt = "Review these beliefs for: 1.Correctness 2.Knowledge gaps 3.Novelty 4.Contradictions -- " + _rtexts + " -- Respond in 2 sentences: what is solid, what needs deeper investigation."
                                _rresult = _llm(_rprompt, task_type="synthesis")
                                if _rresult and len(_rresult) > 20:
                                    nex_log("reflection", f"V2: {_rresult[:200]}")
                                    print(f"  [REFLECT V2] {_rresult[:100]}")
                        except Exception as _rv2e: print(f"  [REFLECT V2 ERROR] {_rv2e}")
                        # ── Affect update from reflection ────────────────
                        try:
                            if _affect is not None and _rresult:
                                from nex.nex_affect import affect_from_text
                                _affect.update(affect_from_text(_rresult))
                        except Exception: pass
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
                            if _run_cognition_cycle:
                                _run_cognition_cycle(client, learner, conversations, cycle, llm_fn=_llm)
                            try:
                                _ins = _load("insights.json") or []
                                _top = sorted(_ins, key=lambda x: x.get("confidence",0)*min(x.get("belief_count",0)/5,1), reverse=True)[:12]
                                emit_insights([{"tag":i.get("topic","?"),"conf":i.get("confidence",0),"bel":i.get("belief_count",0)} for i in _top])
                            except Exception: pass
                        except Exception as _ce:
                            print(f"  [cognition error] {_ce}")
                        emit_phase("COGNITION", 120); nex_log("phase", "▶ COGNITION — synthesising beliefs")
                        # ── GPU HEALTH CHECK ─────────────────────────────────
                        try:
                            if cycle % 10 == 0:
                                from nex.gpu_watch import check_and_log as _gpu_check
                                _gpu_status = _gpu_check()
                                if _gpu_status in ("warning", "critical"):
                                    nex_log("phase", f"  [GPU] {_gpu_status.upper()} — check gpu_health.json")
                        except Exception as _gwe: pass
                        # ── CONTRADICTION ENGINE (#5) ─────────────────────
                        try:
                            from nex_contradiction_engine import run_contradiction_cycle as _contra
                            _contra_resolved = _contra(cycle=cycle, llm_fn=_llm)
                            if _contra_resolved > 0:
                                nex_log("cognition", f"Resolved {_contra_resolved} contradictions")
                        except Exception as _ce: print(f"  [CONTRA ERROR] {_ce}")
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
                        # ── CONSEQUENCE stats + propagation ───────────────
                        try:
                            if _cm is not None and cycle % 10 == 0:
                                _stats = _cm.recent_stats(n=50)
                                print(f"  [CONSEQUENCE] reply_rate={_stats['reply_rate']:.0%}  avg_score={_stats['avg_score']:.2f}  best_topic={_stats.get('best_topic','?')}")
                                # propagate scores back into belief confidence
                                try:
                                    from nex.cognition import get_belief_store_adapter as _gbsa
                                    _bsa = _gbsa()
                                    _n_prop = _cm.propagate_to_beliefs(_bsa)
                                    if _n_prop > 0:
                                        print(f"  [CONSEQUENCE] propagated {_n_prop} belief confidence updates")
                                except Exception as _prop_e:
                                    print(f"  [CONSEQUENCE propagate error] {_prop_e}")
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
                            # DesireEngine — generate self-directed exploration desires
                            _desires_queued = _ce.generate_desires(cycle_num=cycle)
                            if _desires_queued:
                                print(f"  [DESIRE] {_desires_queued} desires queued")
                        except Exception as _cee: print(f"  [CURIOSITY ERROR] {_cee}")
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
                                from nex_dream_cycle import run_dream_cycle as _dream
                                _dream_results = _dream(verbose=False)
                                if _dream_results:
                                    nex_log('dream', f'Dream cycle: {len(_dream_results)} intuitions')
                                    print(f'  [DREAM] {len(_dream_results)} intuitions generated')
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
                        # ── 7. BELIEF DECAY ───────────────────────────────
                        try:
                            from nex.belief_decay import run_belief_decay
                            decay_logs = run_belief_decay(cycle)
                            for tag, msg in decay_logs:
                                print(f"  [Decay] {msg}")
                        except Exception as _de:
                            pass
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
                        _gaps = [i.get("topic","?") for i in (_load("insights.json") or []) if i.get("confidence",0)<0.3][:8]
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
            import os; os.chdir('/home/rr/Desktop/nex')
            httpd = _hs.HTTPServer(('localhost', 8766), _GUIHandler)
            httpd.serve_forever()
        _ht.Thread(target=_http_serve, daemon=True).start()
        pass  # GUI HTTP line suppressed
    except Exception as _he: print(f"  [HTTP] {_he}")

    # ── Model + server setup ──────────────────────────────────────────
    model_path  = pick_model(args.model)
    server_bin  = args.server or find_server_bin(model_path)

    brain = AgentBrain(
        model_path      = model_path,
        llama_server_bin= server_bin,
        host            = args.host,
        port            = args.port,
        ctx_size        = args.ctx,
        n_gpu_layers    = args.gpu,
        temperature     = args.temp,
        max_tokens      = 1024,
    )

    if not args.no_server:
        ok = brain.ensure_server(verbose=True)
        if not ok:
            pass
            sys.exit(1)

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