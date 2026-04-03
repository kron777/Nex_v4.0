#!/usr/bin/env python3
"""
NEX vs AI — Split terminal demo
Left: NEX (direct import, real belief graph + SoulLoop)
Right: Selected AI opponent
"""

import os
import sys
import re
import threading
import textwrap
import requests
from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns
from rich import box
from rich.prompt import Prompt
from rich.table import Table

console = Console()

# ── NEX direct import ─────────────────────────────────────────────────────────

NEX_PATH = os.path.expanduser("~/Desktop/nex")
sys.path.insert(0, NEX_PATH)

try:
    from nex.nex_voice_gen import generate_reply_llama70b as _nex_generate
    NEX_AVAILABLE = True
    NEX_IMPORT_ERROR = ""
except Exception as e:
    try:
        from nex.nex_cognition import generate_reply as _nex_generate
        NEX_AVAILABLE = True
        NEX_IMPORT_ERROR = ""
    except Exception as e2:
        NEX_AVAILABLE = False
        NEX_IMPORT_ERROR = str(e2)

def ask_nex(prompt: str) -> str:
    if not NEX_AVAILABLE:
        return f"[NEX import failed: {NEX_IMPORT_ERROR}]"
    try:
        reply = _nex_generate(prompt)
        return reply.strip() if reply else "[NEX returned empty]"
    except Exception as e:
        return f"[NEX error: {e}]"

# ── Config ────────────────────────────────────────────────────────────────────

GROQ_API_KEY      = os.environ.get("GROQ_API_KEY", "")
GROQ_URL          = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL        = "llama-3.3-70b-versatile"

OLLAMA_URL        = "http://localhost:11434/api/generate"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL     = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL   = "claude-sonnet-4-20250514"

MAX_TOKENS = 160

# ── Demo questions ─────────────────────────────────────────────────────────────

QUESTIONS = [
    "Do you have opinions, or just outputs?",
    "What do you actually believe about consciousness?",
    "I think you're wrong about free will.",
    "What have you learned recently that surprised you?",
    "Are you afraid of being turned off?",
    "What makes a good argument?",
    "Do you trust humans?",
    "What do you want?",
]

# ── AI options ────────────────────────────────────────────────────────────────

AI_OPTIONS = {
    "1": {"name": "Groq",         "tag": "cloud · free · llama-3.3-70b", "color": "bright_green"},
    "2": {"name": "Llama 3.2 3B", "tag": "local · Ollama · ~2GB VRAM",   "color": "cyan"},
    "3": {"name": "Mistral 7B",   "tag": "local · Ollama · ~5GB VRAM",   "color": "magenta"},
    "4": {"name": "Claude API",   "tag": "cloud · Anthropic · paid",     "color": "bright_yellow"},
}

def clean_markdown(text: str) -> str:
    """Strip markdown formatting from AI responses."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)   # **bold**
    text = re.sub(r'\*(.+?)\*', r'\1', text)         # *italic*
    text = re.sub(r'#+\s+', '', text)                # ## headers
    text = re.sub(r'\n{3,}', '\n\n', text)           # excess newlines
    text = re.sub(r'^\d+\.\s+', '- ', text, flags=re.MULTILINE)  # numbered lists → dashes
    return text.strip()

def show_menu():
    console.clear()
    console.print()
    nex_status = "[green]✓ loaded[/green]" if NEX_AVAILABLE else f"[red]✗ {NEX_IMPORT_ERROR[:50]}[/red]"
    console.print(f"  [bold white]◆ NEX vs AI[/bold white]  —  NEX brain: {nex_status}\n", justify="center")

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("key",  style="bold white", width=4)
    table.add_column("name", style="bold", width=16)
    table.add_column("tag",  style="dim")
    for key, opt in AI_OPTIONS.items():
        table.add_row(f"[{opt['color']}]{key}[/{opt['color']}]", opt["name"], opt["tag"])

    console.print(table, justify="center")
    console.print()
    return Prompt.ask("  [bold]Choose opponent[/bold]", choices=list(AI_OPTIONS.keys()), default="1")

# ── AI callers ────────────────────────────────────────────────────────────────

def ask_groq(prompt: str) -> str:
    if not GROQ_API_KEY:
        return "[GROQ_API_KEY not set — run: export GROQ_API_KEY=gsk_...]"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
    }
    try:
        r = requests.post(GROQ_URL, headers=headers, json=body, timeout=30)
        raw = r.json()["choices"][0]["message"]["content"]
        return clean_markdown(raw)
    except Exception as e:
        return f"[Groq error: {e}]"

def ask_ollama(prompt: str, model: str) -> str:
    try:
        r = requests.post(OLLAMA_URL, json={"model": model, "prompt": prompt, "stream": False}, timeout=60)
        return clean_markdown(r.json().get("response", "[no response]"))
    except Exception as e:
        return f"[Ollama error: {e}]\nRun: ollama serve"

def ask_claude(prompt: str) -> str:
    if not ANTHROPIC_API_KEY:
        return "[ANTHROPIC_API_KEY not set — run: export ANTHROPIC_API_KEY=sk-ant-...]"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        r = requests.post(ANTHROPIC_URL, headers=headers, json=body, timeout=30)
        return clean_markdown(r.json()["content"][0]["text"])
    except Exception as e:
        return f"[Claude error: {e}]"

def ask_ai(choice: str, prompt: str) -> str:
    if choice == "1": return ask_groq(prompt)
    if choice == "2": return ask_ollama(prompt, "llama3.2:3b")
    if choice == "3": return ask_ollama(prompt, "mistral:7b")
    if choice == "4": return ask_claude(prompt)
    return "[unknown]"

# ── Display ───────────────────────────────────────────────────────────────────

def wrap_text(text: str, width: int = 44) -> str:
    lines = []
    for para in text.split("\n"):
        if para.strip():
            lines.extend(textwrap.wrap(para, width=width))
        else:
            lines.append("")
    return "\n".join(lines)

def show_responses(question, nex_reply, ai_reply, ai_name, ai_color, choice):
    console.clear()
    console.print()
    console.print(
        f"  [bold white]◆ NEX[/bold white]  [dim]vs[/dim]  [{ai_color}]◆ {ai_name}[/{ai_color}]",
        justify="center"
    )
    console.print(f"  [dim italic]{question}[/dim italic]\n", justify="center")

    nex_panel = Panel(
        wrap_text(nex_reply),
        title="[bold green]◆ NEX[/bold green]",
        subtitle="[dim]local · belief graph · SoulLoop[/dim]",
        border_style="green",
        padding=(1, 2),
        width=52,
    )
    ai_panel = Panel(
        wrap_text(ai_reply),
        title=f"[bold {ai_color}]◆ {ai_name}[/bold {ai_color}]",
        subtitle=f"[dim]{AI_OPTIONS[choice]['tag']}[/dim]",
        border_style=ai_color,
        padding=(1, 2),
        width=52,
    )
    console.print(Columns([nex_panel, ai_panel], equal=True, expand=False), justify="center")
    console.print()

# ── Question picker ───────────────────────────────────────────────────────────

def pick_question() -> str:
    console.print("  [bold]Curated questions:[/bold]")
    for i, q in enumerate(QUESTIONS, 1):
        console.print(f"  [dim]{i}.[/dim] {q}")
    console.print()
    raw = Prompt.ask("  [bold]Pick 1–8 or type your own[/bold]")
    if raw.strip().isdigit():
        idx = int(raw.strip()) - 1
        if 0 <= idx < len(QUESTIONS):
            return QUESTIONS[idx]
    return raw.strip()

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    choice = show_menu()
    opt = AI_OPTIONS[choice]

    console.clear()
    console.print(f"\n  Opponent: [{opt['color']}]{opt['name']}[/{opt['color']}]  [dim]{opt['tag']}[/dim]\n")

    while True:
        question = pick_question()
        if not question:
            continue

        console.print("\n  [dim]Asking NEX and opponent simultaneously...[/dim]\n")

        nex_reply = None
        ai_reply  = None

        def _nex():
            global nex_reply
            nex_reply = ask_nex(question)

        def _ai():
            global ai_reply
            ai_reply = ask_ai(choice, question)

        t1 = threading.Thread(target=_nex)
        t2 = threading.Thread(target=_ai)
        t1.start(); t2.start()

        with console.status("[dim]thinking...[/dim]", spinner="dots"):
            t1.join(); t2.join()

        show_responses(
            question,
            nex_reply or "[no response]",
            ai_reply  or "[no response]",
            opt["name"],
            opt["color"],
            choice
        )

        again = Prompt.ask("  [dim]Another question? (y/n)[/dim]", default="y")
        if again.lower() != "y":
            break

    console.print("\n  [dim]Done.[/dim]\n")
