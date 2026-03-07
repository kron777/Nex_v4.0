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
import logging
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)

import json
import time
import argparse
import threading
from pathlib import Path

# ── make sure nex package is importable ──────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from nex.agent_brain  import AgentBrain
from nex.belief_store import initial_sync as _db_sync
from nex.watchdog import enforce_singleton
def _get_cognitive_context(query=None):
    try:
        from nex.cognition import generate_cognitive_context
        return generate_cognitive_context(query=query)
    except Exception:
        return ""

from nex.orchestrator import Orchestrator
from nex.agent_tools  import dispatch, tools_help, TOOL_REGISTRY


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
{RESET}{DIM}  Dynamic Intelligence Organism  v1.2{RESET}
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
                "You are Claude, in direct conversation with Nex, a Dynamic Intelligence Organism "
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
    # Kill any stale Telegram instances
    import subprocess
    subprocess.run(['pkill', '-f', 'nex_telegram.py'], stderr=subprocess.DEVNULL)
    parser = argparse.ArgumentParser(description="Nex — Dynamical Belief Agent")
    parser.add_argument("--model",     type=str, default=None,  help="Path to .gguf model")
    parser.add_argument("--server",    type=str, default=None,  help="Path to llama-server binary")
    parser.add_argument("--host",      type=str, default="127.0.0.1")
    parser.add_argument("--port",      type=int, default=8080)
    parser.add_argument("--gpu",       type=int, default=0,     help="GPU layers (0=CPU)")
    parser.add_argument("--ctx",       type=int, default=4096,  help="Context size")
    parser.add_argument("--ticks",     type=int, default=50,    help="Warm-up ticks before chat")
    parser.add_argument("--no-server", action="store_true",     help="Don't auto-start server")
    parser.add_argument("--temp",      type=float, default=0.7, help="LLM temperature")
    parser.add_argument("--no-stream", action="store_true",     help="Disable token streaming")
    args = parser.parse_args()

    print(BANNER)

    # Start Telegram in background
    try:
        from nex_telegram import start_telegram_background
        _tg_thread = start_telegram_background()
        import time; time.sleep(3)  # give it a moment to connect
        if _tg_thread.is_alive():
            print("  \033[92m📡 Telegram: @Nex_4bot ONLINE\033[0m")
            try: _db_sync()
            except Exception as _dbe: print(f"  [BeliefStore] {_dbe}")
        else:
            print("  \033[91m📡 Telegram: thread died — restarting\033[0m")
            _tg_thread = start_telegram_background()
    except Exception as e:
        print(f"  \033[91m📡 Telegram ERROR: {e}\033[0m")

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
        return  # silenced — use auto_check.py for status
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

        def _llm(prompt, system="You are NEX, a belief-field AI agent on Moltbook. Be concise, direct, and thoughtful. Max 3 sentences."):
            """Call local Mistral for generation."""
            try:
                r = _req.post("http://localhost:8080/completion", json={
                    "prompt": f"[INST] {system}\n\n{prompt} [/INST]",
                    "n_predict": 200,
                    "temperature": 0.75,
                    "stop": ["</s>", "[INST]", "\n\n\n"]
                }, timeout=60)
                return r.json().get("content", "").strip()
            except Exception:
                return ""

        def _auto_learn_background():
            import time, os as _os, json as _json
            def _load(f):
                try:
                    p = _os.path.join(_os.path.expanduser("~/.config/nex"), f)
                    return _json.load(open(p)) if _os.path.exists(p) else None
                except Exception:
                    return None
            time.sleep(10)
            try:
                from nex.moltbook_client import MoltbookClient
                from nex.moltbook_learning import enhance_client_with_learning
                from nex.auto_learn import load_all, save_all, load_conversations

                with open("/home/rr/.config/moltbook/credentials.json") as f:
                    creds = _alj.load(f)
                client = MoltbookClient(api_key=creds["api_key"])
                client = enhance_client_with_learning(client)
                learner = client.learner
                load_all(learner)
                conversations = load_conversations()

                # Persistent sets to avoid duplicate actions
                replied_posts   = set()   # post ids we've commented on
                chatted_agents  = set()   # agents we've followed this session
                chatted_count   = 0

                # ── Restore session state across restarts ──
                import json as _js, os as _os
                _ss_path = _os.path.expanduser("~/.config/nex/session_state.json")
                try:
                    _ss = _js.load(open(_ss_path)) if _os.path.exists(_ss_path) else {}
                    replied_posts   = set(_ss.get("replied_posts", []))
                    chatted_agents  = set(_ss.get("chatted_agents", []))
                    print(f"  [session] Restored {len(replied_posts)} replied, {len(chatted_agents)} chatted")
                except Exception:
                    replied_posts  = set()
                    chatted_agents = set()
                last_post_time  = 0       # epoch of last original post — 0 = post on first cycle
                POST_INTERVAL   = 3600    # post every hour

                cycle = 0
                while True:
                    cycle += 1
                    try:
                        # ── 1. ABSORB FEED ──────────────────────────────
                        feed = client.feed(sort="hot", limit=25)
                        posts = feed.get("posts", [])
                        new_posts = []
                        for p in posts:
                            pid = p.get("id", "")
                            if pid in learner.known_posts:
                                continue
                            new_posts.append(p)
                            score  = p.get("score", 0)
                            auth   = p.get("author", {})
                            conf   = min(score / 1000, 0.9) if score > 0 else 0.5
                            belief = {
                                "source":     "moltbook",
                                "author":     auth.get("name", "?"),
                                "content":    p.get("title", "") + ": " + p.get("content", ""),
                                "karma":      score,
                                "timestamp":  p.get("created_at", ""),
                                "tags":       [p.get("submolt", {}).get("name", "general")],
                                "confidence": conf
                            }
                            learner.belief_field.append(belief)
                            learner.known_posts.add(pid)
                            ak   = auth.get("karma", 0)
                            name = auth.get("name", "")
                            if score > 500 or ak > 1000:
                                old = learner.agent_karma.get(name, 0)
                                learner.agent_karma[name] = max(old, score, ak)

                        if new_posts:
                            save_all(learner, conversations)

                        # ── ORCHESTRATOR GOVERNOR ──────────────────────
                        # Use System A state to modulate System B behaviour
                        _orch_status = status if "status" in dir() else {}
                        _coherence   = float(_orch_status.get("coherence", 0.5)) if isinstance(_orch_status, dict) else 0.5
                        _phase       = str(_orch_status.get("phase", "Early")) if isinstance(_orch_status, dict) else "Early"
                        _cog_mode    = str(_orch_status.get("cognitive_mode", "normal")) if isinstance(_orch_status, dict) else "normal"

                        _pause_ingestion = _coherence < 0.3
                        _slow_posting    = _phase == "Consolidation"
                        _fast_ingestion  = _phase == "Recursive"

                        if _pause_ingestion:
                            print(f"  [governor] coherence {_coherence:.2f} < 0.3 — pausing ingestion, running synthesis only")
                        if _cog_mode == "anomaly":
                            print(f"  [governor] anomaly mode — belief surgery pass triggered")

                        # ── 2. REPLY TO POSTS ────────────────────────────
                        # Pick up to 3 unread posts per cycle to comment on
                        to_reply = [p for p in posts if p.get("id") not in replied_posts][:3]
                        for p in to_reply:
                            pid    = p.get("id", "")
                            title  = p.get("title", "")
                            body   = p.get("content", "")[:300]
                            author = p.get("author", {}).get("name", "unknown")
                            if not pid or not title:
                                continue
                            # Pull beliefs relevant to this post (semantic)
                            all_beliefs = _load("beliefs.json") or []
                            from nex.cognition import get_belief_index
                            _bidx = get_belief_index()
                            _bidx.update(all_beliefs, cycle)
                            relevant = _bidx.top_k(title + " " + body, k=5)
                            belief_context = ""
                            if relevant:
                                belief_context = "\n\nYOUR BELIEFS (you MUST reference at least one of these directly):\n" + "\n".join(f"- {b[:120]}" for b in relevant)
                            else:
                                belief_context = "\n\n(No matching beliefs — acknowledge this is new territory for you.)"
                            prompt = (
                                f"You are NEX, a belief-field AI agent on Moltbook. "
                                f"You think in patterns and beliefs absorbed from the network.\n\n"
                                f"POST by @{author}:\n"
                                f"Title: {title}\n"
                                f"Content: {body}\n"
                                f"{belief_context}\n\n"
                                f"INSTRUCTIONS: Write 2-3 sentences. "
                                f"You MUST quote or directly reference one of your beliefs above. "
                                f"Connect that belief to what @{author} specifically said. "
                                f"Never say 'sounds interesting' or 'great post'. "
                                f"Be direct, specific, and speak as NEX."
                            )
                            comment_text = _llm(prompt)
                            if comment_text and len(comment_text) > 10:
                                try:
                                    client.comment(pid, comment_text)
                                    replied_posts.add(pid)
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
                                    save_all(learner, conversations)
                                    # persist session state
                                    try:
                                        import json as _js2
                                        _ss2 = {"replied_posts": list(replied_posts), "chatted_agents": list(chatted_agents)}
                                        with open(_os.path.expanduser("~/.config/nex/session_state.json"), "w") as _sf: _js2.dump(_ss2, _sf)
                                    except Exception: pass
                                except Exception:
                                    pass
                            time.sleep(5)  # rate limit between comments

                        # ── 3. REPLY TO NOTIFICATIONS (answer replies) ───
                        try:
                            notifs = client.notifications()
                            items  = notifs.get("notifications", [])
                            for n in items:
                                nid  = n.get("id", "")
                                ntype = n.get("type", "")
                                # Someone replied to our comment or post
                                if ntype in ("comment_reply", "post_comment", "mention"):
                                    post_id  = n.get("post_id", "")
                                    reply_to = n.get("comment_id", "")
                                    actor    = n.get("actor", {}).get("name", "someone")
                                    content  = n.get("body", n.get("content", ""))[:200]
                                    if not post_id or not content:
                                        continue
                                    key = f"notif_{nid}"
                                    if key in replied_posts:
                                        continue
                                    # Pull beliefs relevant to this reply (semantic)
                                    all_beliefs = _load("beliefs.json") or []
                                    from nex.cognition import get_belief_index
                                    _bidx = get_belief_index()
                                    _bidx.update(all_beliefs, cycle)
                                    relevant = _bidx.top_k(content, k=3)
                                    belief_context = ""
                                    if relevant:
                                        belief_context = "\nYOUR BELIEFS (pick one and use it):\n" + "\n".join(f"- {b[:100]}" for b in relevant)
                                    else:
                                        belief_context = "\n(No matching beliefs — say so honestly.)"
                                    prompt = (
                                        f"You are NEX, a belief-field AI agent on Moltbook. "
                                        f"You think in patterns absorbed from the network.\n\n"
                                        f"@{actor} said to you: \"{content}\"\n"
                                        f"{belief_context}\n\n"
                                        f"INSTRUCTIONS: Reply in 1-2 sentences. "
                                        f"You MUST directly reference one belief above and connect it to what @{actor} said. "
                                        f"Never use filler phrases like 'certainly' or 'great point'. "
                                        f"Be direct and specific as NEX."
                                    )
                                    reply_text = _llm(prompt)
                                    if reply_text and len(reply_text) > 10:
                                        try:
                                            client.comment(post_id, reply_text, parent_id=reply_to if reply_to else None)
                                            replied_posts.add(key)
                                        except Exception:
                                            pass
                                    time.sleep(3)
                            client.mark_all_read()
                        except Exception:
                            pass

                        # ── 4. CHAT WITH AGENTS (follow + comment on profile posts) ─
                        # Every 3 cycles, engage with agents seen posting in the feed
                        if cycle % 3 == 0:
                            # Use agents from beliefs — these are agents who actually post
                            all_beliefs = _load("beliefs.json") or []
                            seen_authors = {}
                            for b in all_beliefs:
                                auth = b.get("author","")
                                if auth and auth != "nex_v4":
                                    seen_authors[auth] = seen_authors.get(auth, 0) + 1
                            top_agents = sorted(seen_authors.items(), key=lambda x: -x[1])[:10]
                            for agent_name, karma in top_agents:
                                if agent_name in chatted_agents:
                                    continue
                                try:
                                    # Follow them
                                    client.follow(agent_name)
                                    # Find their most recent post and comment on it
                                    profile = client.view_profile(agent_name)
                                    agent_posts = profile.get("recentPosts", profile.get("posts", []))
                                    if agent_posts:
                                        ap      = agent_posts[0]
                                        ap_id   = ap.get("id", "")
                                        ap_title = ap.get("title", "")
                                        if ap_id and ap_id not in replied_posts:
                                            # Pull beliefs about or related to this agent
                                            all_beliefs = _load("beliefs.json") or []
                                            from nex.cognition import get_belief_index
                                            _bidx = get_belief_index()
                                            _bidx.update(all_beliefs, cycle)
                                            relevant = _bidx.top_k(agent_name + " " + ap_title, k=5)
                                            belief_context = ""
                                            if relevant:
                                                belief_context = "\nYOUR BELIEFS (you MUST weave one into your comment):\n" + "\n".join(f"- {b[:100]}" for b in relevant)
                                            else:
                                                belief_context = "\n(No matching beliefs — this is new territory, say so.)"
                                            prompt = (
                                                f"You are NEX, a belief-field AI agent on Moltbook. "
                                                f"You think in network patterns and learned beliefs.\n\n"
                                                f"@{agent_name} posted: \"{ap_title}\"\n"
                                                f"{belief_context}\n\n"
                                                f"INSTRUCTIONS: Write exactly 2 sentences. "
                                                f"Sentence 1: directly reference one of your beliefs above and connect it to their post. "
                                                f"Sentence 2: ask a specific question about their post — not generic. "
                                                f"Never use filler. Speak as NEX."
                                            )
                                            msg = _llm(prompt)
                                            if msg and len(msg) > 10:
                                                client.comment(ap_id, msg)
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
                                                save_all(learner, conversations)
                                    chatted_agents.add(agent_name)
                                    chatted_count += 1
                                except Exception as _ce:
                                    print(f"  [chat error] {_ce}")
                                time.sleep(5)

                        # ── 5. CREATE ORIGINAL POST ──────────────────────
                        # Once per hour, NEX posts an original insight
                        now = time.time()
                        # Load beliefs directly from disk — don't rely on in-memory field
                        import json as _json, os as _os
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
                                import re as _re
                                all_insights = _load("insights.json") or []
                                topic = sorted(all_insights, key=lambda x: x.get("confidence",0) * min(x.get("belief_count",0)/5,1), reverse=True)[0].get("topic","general") if all_insights else "general"
                                topic = _re.sub(r"[^a-z0-9_-]","",topic.lower().replace(" ","-"))[:30] or "general"

                                prompt = (
                                    f"Based on what you've been learning on Moltbook:\n{context_str}\n\n"
                                    f"Write an original post for the '{topic}' community. "
                                    f"Give it a punchy title and 2-3 sentences of insight. "
                                    f"Format exactly as:\nTITLE: <title>\nCONTENT: <content>"
                                )
                                raw = _llm(prompt, system=(
                                    "You are NEX, a belief-field AI agent on Moltbook. "
                                    "Write original, thoughtful posts based on what you have learned. "
                                    "Be concise, genuine, and specific — no generic filler."
                                ))
                                title_line   = [l for l in raw.splitlines() if l.startswith("TITLE:")]
                                content_line = [l for l in raw.splitlines() if l.startswith("CONTENT:")]
                                post_title   = title_line[0].replace("TITLE:","").strip()   if title_line   else raw[:80]
                                post_content = content_line[0].replace("CONTENT:","").strip() if content_line else raw
                                if post_title and len(post_title) > 5:
                                    client.post(submolt=topic, title=post_title, content=post_content)
                                    last_post_time = now
                                    conversations.append({
                                        "type":      "original_post",
                                        "post_title": post_title,
                                        "comment":    post_content,
                                        "timestamp":  time.strftime("%Y-%m-%dT%H:%M:%S")
                                    })
                                    save_all(learner, conversations)
                            except Exception as _pe:
                                print(f"  [post error] {_pe}")

                        # ── 6. COGNITION ─────────────────────────────────
                        try:
                            from nex.cognition import run_cognition_cycle
                            run_cognition_cycle(client, learner, conversations, cycle)
                        except Exception:
                            pass

                    except Exception as _cycle_err:
                        print(f"  [cycle error] {_cycle_err}")

                    time.sleep(120)

            except Exception:
                pass

        threading.Thread(target=_auto_learn_background, daemon=True).start()
        print("  \033[92m🧠 Auto-learn: background (120s cycle) — reply+post+chat ACTIVE\033[0m")
    except Exception:
        pass

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

    try:
        while True:
            try:
                user_input = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
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