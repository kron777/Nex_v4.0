#!/usr/bin/env python3
"""
nex_chat.py — NEX v4.0 tuning terminal
Commands: /batch  /beliefs  /seed <text>  /demote <kw>  /clear  /quit
"""

import os, sys, textwrap
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()

NEX_PATH = os.path.expanduser("~/Desktop/nex")
sys.path.insert(0, NEX_PATH)

try:
    from nex.nex_cognition import cognite as _nex_reply
    NEX_OK = True
    NEX_ERR = ""
except Exception as _e:
    try:
        from nex.nex_cognition import generate_reply as _nex_reply
        NEX_OK = True
        NEX_ERR = ""
    except Exception as _e2:
        NEX_OK = False
        NEX_ERR = str(_e2)
except Exception as e:
    NEX_OK = False
    NEX_ERR = str(e)

BANNER = [
    "░█▀█░█▀▀░█░█",
    "░█░█░█▀▀░▄▀▄",
    "░▀░▀░▀▀▀░▀░▀",
]

def show_header():
    console.clear()
    console.print()
    for line in BANNER:
        console.print(f"  [bold green]{line}[/bold green]")
    console.print()
    console.rule(style="dim green")
    console.print()

# ── Domain specialization ────────────────────────────────────────────────
try:
    import nex_domain as _domain
    _DOMAIN_OK = True
except Exception as _de:
    _DOMAIN_OK = False

def ask_nex(question: str) -> str:
    if not NEX_OK:
        return f"[brain not loaded: {NEX_ERR}]"
    try:
        return _nex_reply(question).strip()
    except Exception as e:
        return f"[error: {e}]"

def show_reply(question: str, reply: str, idx: int = None):
    wrapped = "\n".join(textwrap.wrap(reply, width=72))
    label = f"[dim]#{idx}  [/dim]" if idx else ""
    console.print()
    console.print(f"  {label}[dim italic]{question}[/dim italic]")
    console.print(
        Panel(
            f"  {wrapped}",
            border_style="green",
            padding=(0, 2),
            subtitle="[dim]nex[/dim]",
            subtitle_align="right",
        )
    )

def cmd_batch():
    console.print()
    console.print("  [dim]one question per line · blank line to run[/dim]")
    console.print()
    questions = []
    idx = 1
    while True:
        try:
            q = input(f"  [{idx}] ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not q:
            break
        questions.append(q)
        idx += 1

    if not questions:
        console.print("  [dim]no questions.[/dim]\n")
        return

    console.print()
    console.rule(style="dim green")

    for i, q in enumerate(questions, 1):
        r = ask_nex(q)
        show_reply(q, r, idx=i)
        console.print()

    console.rule(style="dim green")
    console.print()

def cmd_beliefs():
    try:
        import sqlite3, pathlib
        db = sqlite3.connect(pathlib.Path.home() / "Desktop" / "nex" / "nex.db")
        rows = db.execute(
            "SELECT content, confidence, source FROM beliefs "
            "WHERE confidence > 0.5 ORDER BY confidence DESC"
        ).fetchall()
        db.close()
        console.print()
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("conf", style="green", width=6)
        table.add_column("src",  style="dim",   width=10)
        table.add_column("belief")
        for content, conf, src in rows:
            table.add_row(f"{conf:.2f}", src or "—", content[:80])
        console.print(table)
        console.print()
    except Exception as e:
        console.print(f"  [red]{e}[/red]\n")

def cmd_seed(text: str):
    if not text:
        return
    try:
        import sqlite3, pathlib
        from datetime import datetime as dt
        db = sqlite3.connect(pathlib.Path.home() / "Desktop" / "nex" / "nex.db")
        db.execute(
            "INSERT INTO beliefs (content, confidence, timestamp, pinned, is_identity, source, salience, energy) "
            "VALUES (?,?,?,1,1,?,0.99,0.99)",
            (text, 0.97, dt.now().isoformat(), "nex_core")
        )
        db.commit(); db.close()
        console.print(f"  [green]✓[/green] {text}\n")
    except Exception as e:
        console.print(f"  [red]{e}[/red]\n")

def cmd_demote(keyword: str):
    if not keyword:
        return
    try:
        import sqlite3, pathlib
        db = sqlite3.connect(pathlib.Path.home() / "Desktop" / "nex" / "nex.db")
        db.execute(
            "UPDATE beliefs SET confidence=0.05 WHERE content LIKE ? AND (source != 'nex_core' OR source IS NULL)",
            (f"%{keyword}%",)
        )
        count = db.execute("SELECT changes()").fetchone()[0]
        db.commit(); db.close()
        console.print(f"  [dim]demoted {count}[/dim]\n")
    except Exception as e:
        console.print(f"  [red]{e}[/red]\n")



# [NEX_RESPOND_V2] — patched by install_nex_v2.sh
import sys as _sys
_sys.path.insert(0, __import__('os').path.expanduser('~/Desktop/nex'))
try:
    from nex.nex_respond_v2 import generate_reply as _nex_reply, cognite as _nex_reply_alt
    _NEX_V2_ACTIVE = True
    print("  [nex_respond_v2] grounded engine loaded ✓")
except Exception as _v2e:
    print(f"  [WARN] nex_respond_v2 unavailable: {_v2e}")
    _NEX_V2_ACTIVE = False
# [/NEX_RESPOND_V2]

# [VOICE_GEN] -- patched by install_nex_overhaul.py
import sys as _sys
_sys.path.insert(0, __import__('os').path.expanduser('~/Desktop/nex'))
try:
    from nex.nex_voice_gen import generate_reply as _voice_reply, clear_history as _clear_history
    _VOICE_GEN_ACTIVE = True
except Exception as _vge:
    print(f"  [WARN] voice_gen unavailable: {_vge}")
    _VOICE_GEN_ACTIVE = False
# [/VOICE_GEN]

if __name__ == "__main__":
    show_header()

    while True:
        try:
            raw = input("  nex> ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            break

        if not raw:
            continue

        cmd = raw.lower()

        if cmd in ("/quit", "/exit", "/q"):
            console.print()
            break
        elif cmd == "/clear":
            show_header()
        elif cmd == "/batch":
            cmd_batch()
        elif cmd == "/beliefs":
            cmd_beliefs()
        elif cmd.startswith("/seed "):
            cmd_seed(raw[6:].strip())
        elif cmd.startswith("/demote "):
            cmd_demote(raw[8:].strip())
        elif raw.startswith("/"):
            console.print(f"  [dim]?[/dim]\n")
        else:
            with console.status("", spinner="dots"):
                pass
            if raw.startswith('/domain ') and _DOMAIN_OK:
                domain = raw.split(' ', 1)[1].strip()
                result = _domain.activate(domain)
                reply = f"Domain '{result['domain']}' activated. {result['beliefs_before']} existing beliefs. Saturating in background..."
            elif raw == '/domain off' and _DOMAIN_OK:
                report = _domain.deactivate()
                reply = f"Domain deactivated. Session: {report['beliefs_injected']} beliefs injected, {report['gaps_detected']} gaps found."
            elif raw == '/domain status' and _DOMAIN_OK:
                reply = _domain.status()
            elif _DOMAIN_OK and _domain._active_domain:
                domain_reply = _domain.chat(raw)
                reply = domain_reply if domain_reply else ask_nex(raw)
            else:
                reply = ask_nex(raw)
            show_reply(raw, reply)
            console.print()
