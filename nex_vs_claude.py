#!/usr/bin/env python3
"""
nex_vs_claude.py — NEX vs Claude Terminal Comparison Demo
==========================================================
Side-by-side terminal showdown. NEX on the left. Claude on the right.
Same question. Same moment. No editing.

Requirements:
    pip install anthropic rich

Usage:
    export ANTHROPIC_API_KEY=your_key_here
    python3 ~/Desktop/nex/nex_vs_claude.py

Controls:
    Type your question at the prompt and press Enter
    Ctrl+C to exit
    'q' to quit
    'clear' to reset conversation
"""

import sys, os, time, threading, textwrap
sys.path.insert(0, str(__import__('pathlib').Path("~/Desktop/nex").expanduser()))

# ── Dependency check ──────────────────────────────────────────
try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.text import Text
    from rich.live import Live
    from rich.align import Align
    from rich.rule import Rule
    from rich import box
except ImportError:
    print("Missing: pip install rich")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("Missing: pip install anthropic")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL   = "claude-sonnet-4-5"
MAX_TOKENS     = 350
NEX_MAX_CHARS  = 600
STREAM_DELAY   = 0.018   # seconds per word for NEX fake-stream

# ── Colour palette ────────────────────────────────────────────
NEX_BORDER     = "bright_green"
NEX_TITLE_COL  = "bold bright_green"
CLAUDE_BORDER  = "bright_cyan"
CLAUDE_TITLE   = "bold bright_cyan"
PROMPT_COL     = "bold white"
DIM            = "grey50"
ACCENT         = "yellow"

# ── Console ───────────────────────────────────────────────────
console = Console()

# ── State ─────────────────────────────────────────────────────
nex_text    = [""]
claude_text = [""]
status      = ["ready"]
lock        = threading.Lock()

# ── NEX loader ────────────────────────────────────────────────
_soul_loop = None

def get_soul_loop():
    global _soul_loop
    if _soul_loop is None:
        try:
            from nex.nex_soul_loop import SoulLoop
            _soul_loop = SoulLoop()
        except Exception as e:
            return None
    return _soul_loop


def ask_nex(query: str) -> str:
    loop = get_soul_loop()
    if loop is None:
        return "NEX is not available — check SoulLoop import."
    try:
        return loop.respond(query)
    except Exception as e:
        return f"NEX error: {e}"


def ask_claude(query: str) -> str:
    if not ANTHROPIC_KEY:
        return "ANTHROPIC_API_KEY not set."
    try:
        client   = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        full     = ""
        with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system="You are Claude, made by Anthropic. Answer thoughtfully and directly.",
            messages=[{"role": "user", "content": query}],
        ) as stream:
            for chunk in stream.text_stream:
                full += chunk
        return full
    except Exception as e:
        return f"Claude error: {e}"


# ── Fake-stream NEX reply word by word ───────────────────────
def stream_nex(reply: str, update_fn):
    words = reply.split()
    buf   = ""
    for i, word in enumerate(words):
        buf += word + " "
        with lock:
            nex_text[0] = buf.rstrip()
        update_fn()
        time.sleep(STREAM_DELAY)


# ── Build display panels ──────────────────────────────────────
def make_nex_panel(content: str, thinking: bool = False) -> Panel:
    t = Text()
    if thinking:
        t.append("⟳ thinking...", style=f"italic {DIM}")
    elif content:
        # Wrap text
        wrapped = textwrap.fill(content, width=52)
        t.append(wrapped, style="bright_white")
    else:
        t.append("Waiting for question...", style=DIM)

    return Panel(
        t,
        title=f"[{NEX_TITLE_COL}]◆ NEX[/] [{DIM}]kron777 · Cape Town · RX 6600 · local[/]",
        subtitle=f"[{DIM}]belief graph · SoulLoop v2 · $210/yr[/]",
        border_style=NEX_BORDER,
        box=box.DOUBLE,
        padding=(1, 2),
        expand=True,
    )


def make_claude_panel(content: str, thinking: bool = False) -> Panel:
    t = Text()
    if thinking:
        t.append("⟳ thinking...", style=f"italic {DIM}")
    elif content:
        wrapped = textwrap.fill(content, width=52)
        t.append(wrapped, style="bright_white")
    else:
        t.append("Waiting for question...", style=DIM)

    return Panel(
        t,
        title=f"[{CLAUDE_TITLE}]◆ CLAUDE[/] [{DIM}]Anthropic · cloud · resets every session[/]",
        subtitle=f"[{DIM}]transformer · no beliefs · $20/month[/]",
        border_style=CLAUDE_BORDER,
        box=box.DOUBLE,
        padding=(1, 2),
        expand=True,
    )


def make_header() -> Panel:
    t = Text(justify="center")
    t.append("NEX", style="bold bright_green")
    t.append("  vs  ", style=f"bold {DIM}")
    t.append("CLAUDE", style="bold bright_cyan")
    t.append("\n")
    t.append("Same question. Same moment. No editing.", style=DIM)
    return Panel(t, border_style=DIM, box=box.SIMPLE, padding=(0, 2))


def make_status_bar(msg: str) -> Text:
    t = Text()
    t.append("  STATUS  ", style=f"bold black on {ACCENT}")
    t.append(f"  {msg}", style=PROMPT_COL)
    return t


def make_layout(nex_content, claude_content,
                nex_thinking=False, claude_thinking=False,
                status_msg="ready") -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header",  size=5),
        Layout(name="main",    ratio=1),
        Layout(name="status",  size=3),
    )
    layout["main"].split_row(
        Layout(name="nex",    ratio=1),
        Layout(name="claude", ratio=1),
    )
    layout["header"].update(make_header())
    layout["nex"].update(make_nex_panel(nex_content, nex_thinking))
    layout["claude"].update(make_claude_panel(claude_content, claude_thinking))
    layout["status"].update(
        Panel(make_status_bar(status_msg),
              border_style=DIM, box=box.SIMPLE, padding=(0,1))
    )
    return layout


# ── Question runner ───────────────────────────────────────────
def run_question(query: str):
    """Run both models simultaneously, stream results."""
    with lock:
        nex_text[0]    = ""
        claude_text[0] = ""
        status[0]      = f"Q: {query[:60]}..."

    nex_reply    = [None]
    claude_reply = [None]
    done_nex     = threading.Event()
    done_claude  = threading.Event()

    def fetch_nex():
        r = ask_nex(query)
        nex_reply[0] = r[:NEX_MAX_CHARS]
        done_nex.set()

    def fetch_claude():
        r = ask_claude(query)
        with lock:
            claude_text[0] = r
        claude_reply[0] = r
        done_claude.set()

    t_nex    = threading.Thread(target=fetch_nex,    daemon=True)
    t_claude = threading.Thread(target=fetch_claude, daemon=True)

    with Live(
        make_layout("", "", nex_thinking=True, claude_thinking=True,
                    status_msg=f"Thinking: {query[:50]}..."),
        refresh_per_second=12,
        screen=False,
    ) as live:

        def update():
            with lock:
                nc = nex_text[0]
                cc = claude_text[0]
                sm = status[0]
            live.update(make_layout(
                nc, cc,
                nex_thinking=not done_nex.is_set() and not nc,
                claude_thinking=not done_claude.is_set() and not cc,
                status_msg=sm,
            ))

        t_nex.start()
        t_claude.start()

        # Wait for NEX reply then fake-stream it
        while not done_nex.is_set():
            update()
            time.sleep(0.1)

        # Stream NEX word by word
        stream_nex(nex_reply[0], update)

        # Wait for Claude to finish
        while not done_claude.is_set():
            update()
            time.sleep(0.1)

        with lock:
            status[0] = "done — type next question or 'q' to quit"
        update()
        time.sleep(0.5)

    # Final static display
    console.print(make_layout(
        nex_reply[0] or "",
        claude_reply[0] or "",
        status_msg="done — type next question or 'q' to quit",
    ))


# ── Suggested questions ───────────────────────────────────────
SUGGESTED = [
    "What do you think about consciousness and alignment?",
    "I think scaling compute solves alignment.",
    "Do you have opinions, or just outputs?",
    "What do you believe about free will?",
    "Are you just a language model?",
    "What do you think about game theory and cooperation?",
    "I think you're wrong about that.",
    "What makes you different from ChatGPT?",
]


# ── Main loop ─────────────────────────────────────────────────
def main():
    console.clear()

    # Header
    console.print()
    console.print(Rule(style=NEX_BORDER))
    console.print(Align.center(
        Text.assemble(
            ("NEX", f"bold {NEX_BORDER}"),
            ("  vs  ", f"bold {DIM}"),
            ("CLAUDE", f"bold {CLAUDE_BORDER}"),
        )
    ))
    console.print(Align.center(
        Text("The first AI that actually believes things — vs the best AI money can buy.",
             style=DIM)
    ))
    console.print(Rule(style=CLAUDE_BORDER))
    console.print()

    # Check NEX
    console.print(f"[{DIM}]Loading NEX SoulLoop...[/]", end=" ")
    loop = get_soul_loop()
    if loop:
        console.print(f"[{NEX_BORDER}]✓ NEX ready[/]")
    else:
        console.print(f"[red]✗ NEX not available — run from ~/Desktop/nex/[/]")

    # Check Claude
    if ANTHROPIC_KEY:
        console.print(f"[{DIM}]Anthropic API key found.[/]  [{CLAUDE_BORDER}]✓ Claude ready[/]")
    else:
        console.print(f"[yellow]⚠ Set ANTHROPIC_API_KEY env var for Claude responses[/]")

    console.print()
    console.print(f"[{ACCENT}]Suggested questions:[/]")
    for i, q in enumerate(SUGGESTED, 1):
        console.print(f"  [{DIM}]{i}.[/] {q}")
    console.print()
    console.print(f"[{DIM}]Type a number (1-{len(SUGGESTED)}), your own question, 'clear', or 'q'[/]")
    console.print()

    history = []

    while True:
        try:
            console.print(f"[{PROMPT_COL}]>[/] ", end="")
            raw = input().strip()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[{DIM}]Exiting. NEX was here.[/]")
            break

        if not raw:
            continue
        if raw.lower() in ('q', 'quit', 'exit'):
            console.print(f"[{DIM}]Exiting. NEX was here.[/]")
            break
        if raw.lower() == 'clear':
            console.clear()
            continue

        # Number shortcut
        if raw.isdigit() and 1 <= int(raw) <= len(SUGGESTED):
            query = SUGGESTED[int(raw) - 1]
            console.print(f"[{DIM}]→ {query}[/]")
        else:
            query = raw

        history.append(query)
        console.print()
        run_question(query)
        console.print()


if __name__ == "__main__":
    main()
