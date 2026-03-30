#!/usr/bin/env python3
"""
nex_independence_dashboard.py — Rich Terminal Independence Dashboard
====================================================================
Deploy to: ~/Desktop/nex/nex/nex_independence_dashboard.py

Run standalone: python3 ~/Desktop/nex/nex/nex_independence_dashboard.py

WHY THIS MATTERS (Grok's #21 done properly):

Grok said "independence dashboard + weaning status". NEX already has
/_weaning_status() in run.py. What it doesn't have is a live view that 
combines ALL the new systems we've built into one readable display.

This dashboard shows everything at once:
  ┌─ KERNEL ──────────────────────────────────────────────────────┐
  │ Soul hit rate:  78%  ████████████████░░░░  (last 200 queries) │
  │ Avg confidence: 0.67 ██████████████░░░░░░                     │
  │ Avg reply words: 24  Good                                     │
  │ Stage dist: soul=78% voice=14% llm_free=5% fallback=3%        │
  ├─ BELIEFS ─────────────────────────────────────────────────────┤
  │ Total: 32,169   High-conf (>0.7): 8,432   Topics: 287         │
  │ Growth today: +54   Avg conf: 0.671                           │
  ├─ CONCEPT GRAPH ────────────────────────────────────────────────┤
  │ Concepts mapped: 15   Topics covered: 203                     │
  │ Top concept: consciousness (431 beliefs, 23 topics)           │
  ├─ WORKING MEMORY ───────────────────────────────────────────────┤
  │ Turns: 12   Active topic: consciousness   Thread: 3           │
  ├─ GAPS ─────────────────────────────────────────────────────────┤
  │ Conversation gaps queued today: 4                             │
  │ Most recent: "plant consciousness" (thread=3, stage=fallback) │
  ├─ QUALITY ──────────────────────────────────────────────────────┤
  │ Top quality topics: consciousness, alignment, emergence...    │
  │ Weak topics: generosity, sport, stats                        │
  └────────────────────────────────────────────────────────────────┘

Uses `rich` library if available, plain text fallback if not.
Can be run standalone OR called via /status in run.py.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

_CFG     = Path("~/.config/nex").expanduser()
_DB_PATH = _CFG / "nex.db"


# ── Data loaders ──────────────────────────────────────────────────────────────

def _db() -> Optional[sqlite3.Connection]:
    if not _DB_PATH.exists():
        return None
    try:
        con = sqlite3.connect(str(_DB_PATH), timeout=2)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


def _load_json(path: Path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def collect_metrics() -> dict:
    """Collect all metrics into a single dict."""
    m = {}

    # ── Beliefs ──────────────────────────────────────────────────────────
    db = _db()
    if db:
        try:
            m["belief_total"]    = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
            m["belief_high"]     = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence>0.7").fetchone()[0]
            m["belief_avg_conf"] = round(float(db.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0] or 0), 3)
            m["topic_count"]     = db.execute("SELECT COUNT(DISTINCT topic) FROM beliefs WHERE topic IS NOT NULL AND topic!=''").fetchone()[0]
            m["opinion_count"]   = 0
            m["tension_count"]   = 0
            try: m["opinion_count"] = db.execute("SELECT COUNT(*) FROM opinions").fetchone()[0]
            except: pass
            try: m["tension_count"] = db.execute("SELECT COUNT(*) FROM tensions WHERE resolved_at IS NULL").fetchone()[0]
            except: pass
            db.close()
        except Exception:
            try: db.close()
            except: pass
    else:
        m.update({"belief_total":0,"belief_high":0,"belief_avg_conf":0,"topic_count":0,"opinion_count":0,"tension_count":0})

    # ── Coherence (audit log) ─────────────────────────────────────────────
    coherence = _load_json(_CFG / "coherence_metrics.json", {})
    m["soul_hit_rate"]    = coherence.get("soul_hit_rate", 0.0)
    m["total_queries"]    = coherence.get("total_queries", 0)
    m["avg_reply_words"]  = coherence.get("avg_reply_words", 0)
    m["stage_dist"]       = coherence.get("stage_dist", {})
    m["intent_dist"]      = coherence.get("intent_dist", {})

    # ── Concept graph ─────────────────────────────────────────────────────
    cg = _load_json(_CFG / "concept_graph.json", {})
    meta = cg.get("meta", {})
    m["concept_count"]    = meta.get("concept_count", 0)
    m["concept_topics"]   = meta.get("topic_count", 0)
    # Find top concept by belief count
    concepts = cg.get("concepts", {})
    if concepts:
        top = max(concepts.items(), key=lambda x: x[1].get("belief_count", 0))
        m["top_concept"]      = top[0]
        m["top_concept_beliefs"] = top[1].get("belief_count", 0)
        m["top_concept_topics"]  = len(top[1].get("topics", []))
    else:
        m["top_concept"] = ""; m["top_concept_beliefs"] = 0; m["top_concept_topics"] = 0

    # ── Working memory ────────────────────────────────────────────────────
    wm = _load_json(_CFG / "working_memory.json", {})
    entries = wm.get("entries", [])
    m["wm_turns"]         = len(entries)
    m["wm_active_topic"]  = entries[-1].get("topic", "") if entries else ""
    m["wm_active_concept"]= entries[-1].get("concept", "") if entries else ""
    if len(entries) >= 2:
        # Calculate current thread length
        last_topic = m["wm_active_topic"]
        thread = sum(1 for e in reversed(entries) if e.get("topic") == last_topic)
        m["wm_thread"] = min(thread, len(entries))
    else:
        m["wm_thread"] = 0

    # ── Conversation gaps ─────────────────────────────────────────────────
    gaps_today = 0
    last_gap   = ""
    gap_path   = _CFG / "conversation_gaps.jsonl"
    if gap_path.exists():
        try:
            today = time.strftime("%Y-%m-%d")
            lines = gap_path.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines[-50:]):
                try:
                    g = json.loads(line)
                    if g.get("ts", "").startswith(today):
                        gaps_today += 1
                    if not last_gap:
                        last_gap = f"{g.get('topic','')} (thread={g.get('thread_length',0)}, stage seen)"
                except Exception:
                    pass
        except Exception:
            pass
    m["gaps_today"] = gaps_today
    m["last_gap"]   = last_gap

    # ── Belief quality ────────────────────────────────────────────────────
    qual = _load_json(_CFG / "belief_quality_scores.json", {})
    scores = qual.get("scores", {})
    if scores:
        sorted_s = sorted(scores.items(), key=lambda x: -x[1])
        m["quality_top"]    = [t for t, _ in sorted_s[:5]]
        m["quality_bottom"] = [t for t, s in sorted_s if s < 0.4][:3]
    else:
        m["quality_top"] = []; m["quality_bottom"] = []

    # ── Memory API ────────────────────────────────────────────────────────
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    m["api_running"] = s.connect_ex(("127.0.0.1", 8767)) == 0
    s.close()

    return m


# ── Renderers ─────────────────────────────────────────────────────────────────

def _bar(value: float, width: int = 20) -> str:
    filled = int(value * width)
    return "█" * filled + "░" * (width - filled)


def render_plain(m: dict) -> str:
    """Plain text dashboard — works without rich library."""
    lines = []
    W = 62

    def box(title):
        lines.append(f"┌─ {title} {'─' * (W - len(title) - 3)}┐")

    def row(text):
        lines.append(f"│  {text:<{W-3}}│")

    def sep(title=""):
        if title:
            lines.append(f"├─ {title} {'─' * (W - len(title) - 3)}┤")
        else:
            lines.append(f"├{'─' * (W+1)}┤")

    def end():
        lines.append(f"└{'─' * (W+1)}┘")

    box("NEX INDEPENDENCE DASHBOARD")

    # Kernel
    sep("KERNEL")
    soul_rate = m["soul_hit_rate"]
    soul_status = "✓ kernel-native" if soul_rate > 0.7 else "⚠ falling back" if soul_rate > 0.4 else "✗ mostly fallback"
    row(f"Soul hit rate:   {soul_rate:.0%}  {_bar(soul_rate)}  {soul_status}")
    row(f"Avg confidence:  {m['belief_avg_conf']:.3f}  {_bar(m['belief_avg_conf'])}")
    row(f"Avg reply words: {m['avg_reply_words']:.0f}  {'Good' if m['avg_reply_words'] >= 18 else 'Short'}")
    row(f"Total queries:   {m['total_queries']}")

    sd = m["stage_dist"]
    if sd:
        dist_str = "  ".join(f"{k}={v}" for k, v in sorted(sd.items(), key=lambda x: -x[1]))
        row(f"Stages: {dist_str}")

    # Beliefs
    sep("BELIEFS")
    row(f"Total: {m['belief_total']:,}   High-conf (>0.7): {m['belief_high']:,}   Topics: {m['topic_count']}")
    row(f"Avg confidence: {m['belief_avg_conf']:.3f}   Opinions: {m['opinion_count']}   Tensions: {m['tension_count']}")

    # Concept graph
    sep("CONCEPT GRAPH")
    if m["concept_count"]:
        row(f"Concepts mapped: {m['concept_count']}   Topics covered: {m['concept_topics']}")
        row(f"Top concept: {m['top_concept']} ({m['top_concept_beliefs']} beliefs, {m['top_concept_topics']} topics)")
    else:
        row("Not yet built — run: python3 nex_concept_graph.py")

    # Working memory
    sep("WORKING MEMORY")
    if m["wm_turns"]:
        row(f"Turns: {m['wm_turns']}   Active topic: {m['wm_active_topic'] or 'none'}   Thread: {m['wm_thread']}")
        if m["wm_active_concept"]:
            row(f"Active concept: {m['wm_active_concept']}")
    else:
        row("Empty — no conversation yet this session")

    # Gaps
    sep("CONVERSATION GAPS")
    row(f"Gaps queued today: {m['gaps_today']}")
    if m["last_gap"]:
        row(f"Most recent: {m['last_gap'][:55]}")

    # Quality
    sep("BELIEF QUALITY")
    if m["quality_top"]:
        row(f"Top topics: {', '.join(m['quality_top'][:4])}")
    if m["quality_bottom"]:
        row(f"Weak topics: {', '.join(m['quality_bottom'])}")
    if not m["quality_top"] and not m["quality_bottom"]:
        row("Not yet scored — run nex_belief_quality.py")

    # API
    sep("MEMORY API")
    row(f"http://localhost:8767/ — {'RUNNING ✓' if m['api_running'] else 'not started'}")
    if m["api_running"]:
        row("Endpoints: /status /beliefs /opinions /tensions /concepts /memory /gaps")

    end()
    return "\n".join(lines)


def render_rich(m: dict) -> None:
    """Rich-formatted dashboard."""
    from rich.console import Console
    from rich.table   import Table
    from rich.panel   import Panel
    from rich.columns import Columns
    from rich import box as rbox

    console = Console()

    soul_rate  = m["soul_hit_rate"]
    soul_color = "green" if soul_rate > 0.7 else "yellow" if soul_rate > 0.4 else "red"

    # Kernel panel
    kernel_lines = [
        f"[{soul_color}]Soul hit rate:   {soul_rate:.0%}  {_bar(soul_rate)}[/{soul_color}]",
        f"Avg confidence:  {m['belief_avg_conf']:.3f}  {_bar(m['belief_avg_conf'])}",
        f"Avg reply words: {m['avg_reply_words']:.0f}",
        f"Total queries:   {m['total_queries']}",
    ]
    sd = m["stage_dist"]
    if sd:
        kernel_lines.append("Stages: " + "  ".join(f"{k}={v}" for k, v in sorted(sd.items(), key=lambda x: -x[1])))

    # Beliefs panel
    belief_lines = [
        f"Total: [bold]{m['belief_total']:,}[/bold]   High-conf: [green]{m['belief_high']:,}[/green]   Topics: {m['topic_count']}",
        f"Avg conf: {m['belief_avg_conf']:.3f}   Opinions: {m['opinion_count']}   Tensions: {m['tension_count']}",
    ]

    console.print()
    console.print(Panel("\n".join(kernel_lines),   title="[bold cyan]KERNEL[/bold cyan]",  border_style="cyan"))
    console.print(Panel("\n".join(belief_lines),   title="[bold blue]BELIEFS[/bold blue]", border_style="blue"))

    if m["concept_count"]:
        cg_lines = [
            f"Concepts: {m['concept_count']}   Topics covered: {m['concept_topics']}",
            f"Top: [yellow]{m['top_concept']}[/yellow] ({m['top_concept_beliefs']} beliefs)",
        ]
        console.print(Panel("\n".join(cg_lines), title="[bold yellow]CONCEPT GRAPH[/bold yellow]", border_style="yellow"))

    if m["wm_turns"]:
        wm_lines = [
            f"Turns: {m['wm_turns']}   Active: [magenta]{m['wm_active_topic'] or 'none'}[/magenta]   Thread depth: {m['wm_thread']}",
        ]
        console.print(Panel("\n".join(wm_lines), title="[bold magenta]WORKING MEMORY[/bold magenta]", border_style="magenta"))

    console.print()


def show_dashboard(use_rich: bool = True) -> str:
    """Main entry point. Shows the dashboard."""
    m = collect_metrics()
    if use_rich:
        try:
            render_rich(m)
            return ""
        except ImportError:
            pass
    result = render_plain(m)
    print(result)
    return result


# ── Weaning status (Grok #21) ─────────────────────────────────────────────────

def weaning_status() -> str:
    """
    Shows how independent NEX is right now.
    Improved version of run.py's _weaning_status().
    """
    m = collect_metrics()

    GREEN  = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED    = "\033[0;31m"
    BOLD   = "\033[1m"
    NC     = "\033[0m"

    def grade(val, good, warn):
        if val >= good:  return f"{GREEN}✓{NC}"
        if val >= warn:  return f"{YELLOW}⚠{NC}"
        return f"{RED}✗{NC}"

    print(f"\n{BOLD}══════════════ NEX WEANING STATUS ══════════════{NC}\n")

    soul  = m["soul_hit_rate"]
    print(f"  {grade(soul,0.7,0.4)} Soul hit rate:      {soul:.0%}  {_bar(soul,30)}  (target: >70%)")

    conf  = m["belief_avg_conf"]
    print(f"  {grade(conf,0.65,0.5)} Avg belief conf:   {conf:.3f}  {_bar(conf,30)}  (target: >0.65)")

    bc    = m["belief_total"]
    print(f"  {grade(bc,2000,500)} Belief corpus:     {bc:,}  (target: >2,000)")

    wds   = m["avg_reply_words"]
    print(f"  {grade(wds,18,10)} Avg reply words:   {wds:.0f}  (target: >18)")

    cg    = m["concept_count"]
    print(f"  {grade(cg,10,5)} Concept graph:     {cg} concepts mapped")

    wm    = m["wm_turns"]
    print(f"  {grade(wm,5,1)} Working memory:    {wm} turns active")

    api   = m["api_running"]
    print(f"  {grade(int(api),1,0)} Memory API:        {'running on :8767' if api else 'not started'}")

    # LLM dependency check
    import subprocess, sys
    try:
        nex_dir = Path.home() / "Desktop/nex"
        r = subprocess.run(
            ["grep", "-rl", "localhost:8080", str(nex_dir / "nex")],
            capture_output=True, text=True
        )
        llm_deps = [l.strip() for l in r.stdout.splitlines()
                    if "pre_kernel" not in l and ".pyc" not in l and l.strip()]
        if llm_deps:
            print(f"  {YELLOW}⚠{NC}  Llama refs remaining: {', '.join(Path(l).name for l in llm_deps[:3])}")
        else:
            print(f"  {GREEN}✓{NC}  Llama refs: NONE (fully weaned from localhost:8080)")
    except Exception:
        pass

    print(f"\n{BOLD}══════════════════════════════════════════════════{NC}\n")
    return ""


if __name__ == "__main__":
    import sys
    if "--weaning" in sys.argv:
        weaning_status()
    else:
        show_dashboard()
