#!/usr/bin/env python3
"""
nex_debug.py — NEX Debug Terminal
===================================
Connects to NEX WebSocket (port 8765) and displays
real-time debug output with colour-coded notifications.

Also reads nex_debug_log.jsonl for cognition internals
that can't come through the WS feed.

Usage:
    python3 ~/Desktop/nex/nex_debug.py

Add to ~/.bashrc:
    alias nex-debug='python3 ~/Desktop/nex/nex_debug.py'
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Colours ────────────────────────────────────────────────────
R  = "\033[91m"   # red
G  = "\033[92m"   # green
Y  = "\033[93m"   # yellow
B  = "\033[94m"   # blue
M  = "\033[95m"   # magenta
C  = "\033[96m"   # cyan
W  = "\033[97m"   # white
DIM= "\033[2m"
BLD= "\033[1m"
RST= "\033[0m"

DEBUG_LOG = Path.home() / ".config" / "nex" / "nex_debug.jsonl"
WS_URL    = "ws://localhost:8765"

# ── Category colours ───────────────────────────────────────────
CAT_COLOURS = {
    "synth":      G,
    "synthesis":  G,
    "cluster":    C,
    "belief":     B,
    "decay":      Y,
    "youtube":    M,
    "rss":        M,
    "reply":      W,
    "chat":       W,
    "reflect":    C,
    "cognition":  G,
    "warn":       R,
    "error":      R,
    "phase":      Y,
    "profile":    DIM,
    "exchange":   B,
    "research":   C,
    "idle":       R,
    "active":     G,
    "db":         C,
    "dedup":      Y,
}

def colour_for(cat):
    cat = (cat or "").lower()
    for k, v in CAT_COLOURS.items():
        if k in cat:
            return v
    return W

def ts():
    return datetime.now().strftime("%H:%M:%S")

def print_event(cat, msg, source="ws"):
    col = colour_for(cat)
    src_tag = f"{DIM}[{source}]{RST}" if source != "ws" else ""
    print(f"{DIM}{ts()}{RST} {col}{BLD}[{cat.upper():10}]{RST}{src_tag} {msg}")

def print_header():
    os.system("clear")
    print(f"{BLD}{C}{'═'*70}{RST}")
    print(f"{BLD}{C}  NEX DEBUG TERMINAL{RST}  {DIM}connecting to {WS_URL}{RST}")
    print(f"{BLD}{C}{'═'*70}{RST}")
    print(f"{DIM}  Green=synthesis  Cyan=cognition  Yellow=decay/phase")
    print(f"  Magenta=learning  Blue=beliefs  Red=errors/idle{RST}")
    print(f"{BLD}{C}{'─'*70}{RST}\n")

# ── Debug log reader (cognition internals) ─────────────────────
async def tail_debug_log():
    """Tail the debug log file for cognition internals."""
    seen = 0
    while True:
        try:
            if DEBUG_LOG.exists():
                lines = DEBUG_LOG.read_text().strip().split("\n")
                if len(lines) > seen:
                    for line in lines[seen:]:
                        try:
                            ev = json.loads(line)
                            print_event(ev.get("cat","debug"), ev.get("msg",""), source="cog")
                        except Exception:
                            pass
                    seen = len(lines)
        except Exception:
            pass
        await asyncio.sleep(1)

# ── WebSocket listener ─────────────────────────────────────────
async def ws_listen():
    try:
        import websockets
    except ImportError:
        print(f"{Y}[debug] websockets not installed — run: pip install websockets --break-system-packages{RST}")
        print(f"{DIM}Falling back to debug log only...{RST}\n")
        return

    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20) as ws:
                print_event("active", f"Connected to NEX WebSocket at {WS_URL}")
                async for raw in ws:
                    try:
                        data = json.loads(raw)
                        etype = data.get("type", "event")
                        payload = data.get("data", data)

                        if etype == "feed":
                            cat  = payload.get("type", payload.get("category", "feed"))
                            agent = payload.get("agent", "")
                            msg  = payload.get("content", payload.get("text", payload.get("message", str(payload))))
                            print_event(cat, f"{W}{agent}{RST} {msg}")

                        elif etype == "phase":
                            phase = payload.get("phase", "?")
                            print_event("phase", f"▶ {BLD}{phase}{RST}")

                        elif etype == "stats":
                            s = payload
                            beliefs  = s.get("beliefs", "?")
                            iq       = s.get("iq", "?")
                            insights = s.get("insights", "?")
                            conf     = s.get("belief_confidence", "?")
                            print_event("stats",
                                f"beliefs={W}{beliefs}{RST} "
                                f"IQ={G}{iq}{RST} "
                                f"insights={C}{insights}{RST} "
                                f"conf={Y}{conf}{RST}")

                        elif etype == "insights":
                            for ins in (payload if isinstance(payload, list) else [payload]):
                                # run.py sends tag/conf/bel not topic/confidence/belief_count
                                topic = ins.get("tag", ins.get("topic","?"))
                                conf  = ins.get("conf", ins.get("confidence", 0))
                                count = ins.get("bel", ins.get("belief_count", 0))
                                col   = G if conf > 0.5 else Y if conf > 0.3 else R
                                print_event("synth",
                                    f"[{col}{topic}{RST}] "
                                    f"conf={col}{conf:.0%}{RST} beliefs={count}")

                        elif etype == "reflection":
                            align = payload.get("topic_alignment", 0)
                            used  = payload.get("used_beliefs", False)
                            gap   = payload.get("growth_note", "")[:60]
                            col   = G if align > 0.5 else Y if align > 0.3 else R
                            print_event("reflect",
                                f"alignment={col}{align:.0%}{RST} "
                                f"beliefs_used={used} "
                                f"gap={DIM}{gap}{RST}")

                        elif etype == "self_assessment":
                            sa = payload
                            print_event("cognition",
                                f"IQ={G}{sa.get('iq','?')}{RST} "
                                f"conf={sa.get('belief_confidence','?')} "
                                f"gaps={DIM}{sa.get('knowledge_gaps','?')}{RST}")

                        elif etype == "sysmon":
                            # Only show sysmon if resources are high
                            cpu = payload.get("cpu", 0)
                            mem = payload.get("mem", 0)
                            if cpu > 80 or mem > 90:
                                print_event("warn", f"HIGH RESOURCES cpu={cpu}% mem={mem}%")
                            # else suppress normal sysmon noise

                        else:
                            print_event(etype, str(payload)[:120])

                    except Exception as e:
                        print_event("warn", f"Parse error: {e} — raw: {raw[:80]}")

        except Exception as e:
            err = str(e)
            if "111" in err or "refused" in err.lower():
                # NEX not up yet — wait silently
                await asyncio.sleep(5)
            else:
                print_event("warn", f"WS disconnected: {e} — retrying in 5s...")
                await asyncio.sleep(5)

# ── Main ───────────────────────────────────────────────────────
async def main():
    print_header()
    await asyncio.gather(
        ws_listen(),
        tail_debug_log(),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{DIM}Debug terminal closed.{RST}")
