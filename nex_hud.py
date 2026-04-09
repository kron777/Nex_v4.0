#!/usr/bin/env python3
"""
nex_hud.py — NEX Live HUD Terminal
Sci-fi styled single terminal monitor for NEX v1.2
"""

import subprocess
import time
import os
import re
import sys
import sqlite3
import threading
import datetime
import collections
from pathlib import Path

# ─── CONFIG ───────────────────────────────────────────────────────────────────
NEX_DB      = Path("/home/rr/Desktop/nex/nex.db")
BRAIN_LOG   = "/tmp/nex_brain.log"
AUTO_LOG    = "/tmp/nex_auto_check.log"
REFRESH     = 2       # seconds between stat refreshes
MAX_STREAM  = 18      # lines in live stream box
WIDTH       = 80      # terminal width

# ─── ANSI COLOURS ─────────────────────────────────────────────────────────────
R   = "\033[0m"
B   = "\033[1m"
DM  = "\033[2m"
CY  = "\033[96m"      # bright cyan  — labels
DCY = "\033[36m"      # dim cyan     — borders
GR  = "\033[92m"      # green        — online/live
YL  = "\033[93m"      # yellow       — beliefs/warnings
RD  = "\033[91m"      # red          — crash/dead
WH  = "\033[97m"      # white        — values
MG  = "\033[95m"      # magenta      — posted/replied
BL  = "\033[94m"      # blue         — platforms

# ─── STREAM COLOURS BY TYPE ───────────────────────────────────────────────────
STREAM_COLORS = {
    "REPLIED": MG, "CHATTED": CY, "POSTED": GR,
    "LEARNT": YL,  "BELIEF": YL,  "CRASH": RD,
    "WARN": YL,    "ERROR": RD,   "BRAIN": CY,
    "SOUL": CY,    "PHASE": DM,   "INFO": DM,
}

# ─── STATE ────────────────────────────────────────────────────────────────────
stream_lines = collections.deque(maxlen=MAX_STREAM)
stream_lock  = threading.Lock()
last_log_pos = 0
start_time   = time.time()

stats = {
    "status": "IDLE", "llm": "OFFLINE", "replied": 0,
    "beliefs": 0, "learnt": 0, "posted": 0, "chatted": 0,
    "conf": 0, "align": 0, "network": 0, "iq": 0,
    "gaps": 0, "needs": "", "original": 0, "reflects": 0,
    "platforms": {
        "MOLTBOOK": "IDLE", "TELEGRAM": "IDLE",
        "DISCORD": "IDLE",  "MASTODON": "IDLE", "YOUTUBE": "IDLE"
    },
    "gpu_pct": 0, "gpu_w": 0, "gpu_max": 100,
    "brain_alive": False, "telegram_alive": False,
    "llama_alive": False,  "autocheck_alive": False,
    "crash_msg": "",
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
        return r.stdout.strip()
    except Exception:
        return ""

def bar(pct, width=10, filled="█", empty="░"):
    n = int((pct / 100) * width)
    return filled * n + empty * (width - n)

def uptime():
    s = int(time.time() - start_time)
    h, m = divmod(s, 3600)
    m, s = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def trunc(s, n):
    s = str(s)
    return s[:n-1] + "…" if len(s) > n else s.ljust(n)

def platform_color(state):
    if state == "LIVE":   return GR
    if state == "RECENT": return CY
    return DM

# ─── GPU ──────────────────────────────────────────────────────────────────────

def get_gpu():
    out = run("rocm-smi --showuse --showpower --csv 2>/dev/null | tail -1")
    if not out:
        # fallback
        out2 = run("rocm-smi 2>/dev/null | grep -E 'GPU use|Avg Pwr'")
        pct = 0
        w   = 0
        for line in out2.splitlines():
            if "GPU use" in line:
                m = re.search(r'(\d+)%', line)
                if m: pct = int(m.group(1))
            if "Avg Pwr" in line or "Power" in line:
                m = re.search(r'(\d+\.?\d*)\s*[Ww]', line)
                if m: w = float(m.group(1))
        return pct, int(w)
    parts = out.split(",")
    try:
        pct = int(parts[3].strip().replace("%","")) if len(parts) > 3 else 0
        w   = int(float(parts[5].strip().replace("W","").replace("N/A","0"))) if len(parts) > 5 else 0
        return pct, w
    except Exception:
        return 0, 0

# ─── PROCESS CHECK ────────────────────────────────────────────────────────────

def check_processes():
    stats["brain_alive"]     = bool(run("pgrep -f 'run.py'"))
    stats["llama_alive"]     = bool(run("pgrep -f 'llama-server'"))
    stats["telegram_alive"]  = bool(run("pgrep -f 'nex_telegram_clean'"))
    stats["autocheck_alive"] = bool(run("pgrep -f 'auto_check'"))
    stats["llm"]    = "ONLINE" if stats["llama_alive"] else "OFFLINE"
    stats["status"] = "ACTIVE" if stats["brain_alive"] else "IDLE"

# ─── DB STATS ─────────────────────────────────────────────────────────────────

def get_db_stats():
    try:
        if not NEX_DB.exists():
            return
        con = sqlite3.connect(str(NEX_DB), timeout=2)
        cur = con.cursor()

        # Total beliefs
        cur.execute("SELECT COUNT(*) FROM beliefs")
        stats["beliefs"] = cur.fetchone()[0]

        # Original beliefs (NEX-generated, not seeded)
        try:
            cur.execute("SELECT COUNT(*) FROM beliefs WHERE source NOT LIKE '%auto_seeder%' AND source NOT LIKE '%seed%' AND confidence > 0.5")
            stats["original"] = cur.fetchone()[0]
        except Exception:
            stats["original"] = 0

        # Confidence avg
        cur.execute("SELECT AVG(confidence) FROM beliefs WHERE confidence > 0")
        conf = cur.fetchone()[0] or 0
        stats["conf"] = int(conf * 100)

        # Knowledge gaps
        try:
            cur.execute("SELECT COUNT(DISTINCT topic) FROM beliefs WHERE confidence < 0.4")
            stats["gaps"] = cur.fetchone()[0]
        except Exception:
            stats["gaps"] = 0

        con.close()
    except Exception:
        pass

# ─── LOG PARSER ───────────────────────────────────────────────────────────────

def parse_auto_log():
    """Extract stats from auto_check log."""
    try:
        if not os.path.exists(AUTO_LOG):
            return
        size = os.path.getsize(AUTO_LOG)
        if size == 0:
            return
        with open(AUTO_LOG, "r", errors="replace") as f:
            content = f.read()

        # Platform states
        for plat in ["MOLTBOOK", "TELEGRAM", "DISCORD", "MASTODON", "YOUTUBE"]:
            if f"{plat}  LIVE" in content or f"{plat} LIVE" in content:
                stats["platforms"][plat] = "LIVE"
            elif f"{plat}  RECENT" in content or f"{plat} RECENT" in content:
                stats["platforms"][plat] = "RECENT"
            else:
                stats["platforms"][plat] = "IDLE"

        # Counters
        m = re.search(r'REPLIED\s+(\d+)', content)
        if m: stats["replied"] = int(m.group(1))

        m = re.search(r'LEARNT\s+(\d+)', content)
        if m: stats["learnt"] = int(m.group(1))

        m = re.search(r'POSTED\s+(\d+)', content)
        if m: stats["posted"] = int(m.group(1))

        m = re.search(r'CHATTED\s+(\d+)', content)
        if m: stats["chatted"] = int(m.group(1))

        m = re.search(r'REFLECTS\s+(\d+)', content)
        if m: stats["reflects"] = int(m.group(1))

        # Topic alignment
        m = re.search(r'Topic alignment.*?(\d+)%', content)
        if m: stats["align"] = int(m.group(1))

        # Network coverage
        m = re.search(r'Network reach.*?(\d+)%', content)
        if m: stats["network"] = int(m.group(1))

        # NEX IQ
        m = re.search(r'NEX IQ.*?(\d+)%', content)
        if m: stats["iq"] = int(m.group(1))

        # Needs to learn
        m = re.search(r'Needs to learn\s+(.+)', content)
        if m: stats["needs"] = m.group(1).strip()[:45]

    except Exception:
        pass

# ─── STREAM BRAIN LOG ─────────────────────────────────────────────────────────

def classify_line(line):
    """Classify a brain log line into a type and short label."""
    if "REPLIED" in line or "replied" in line:
        return "REPLIED", MG
    if "CHATTED" in line or "chatted" in line:
        return "CHATTED", CY
    if "POSTED" in line or "posted" in line:
        return "POSTED", GR
    if "LEARNT" in line or "auto_seeder" in line or "learnt" in line:
        return "LEARNT", YL
    if "inferred belief" in line or "★" in line or "soul_loop" in line:
        return "BELIEF", YL
    if "FATAL" in line or "CRASH" in line or "Traceback" in line:
        return "CRASH", RD
    if "ERROR" in line or "error" in line:
        return "ERROR", RD
    if "[METABOLISM]" in line:
        return "META", DM
    if "PHASE" in line or "phase" in line:
        return "PHASE", DM
    if "[ABMv2]" in line or "[BKS]" in line or "[MPF]" in line:
        return "BRAIN", CY
    if "SoulLoop" in line or "soul_loop" in line or "KERNEL" in line:
        return "SOUL", CY
    return "INFO", DM

def stream_log():
    """Background thread: tail brain log and add to stream."""
    global last_log_pos
    while True:
        try:
            if not os.path.exists(BRAIN_LOG):
                time.sleep(1)
                continue
            size = os.path.getsize(BRAIN_LOG)
            if size < last_log_pos:
                last_log_pos = 0  # file truncated
            if size > last_log_pos:
                with open(BRAIN_LOG, "r", errors="replace") as f:
                    f.seek(last_log_pos)
                    new = f.read()
                last_log_pos = size
                for line in new.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    # Skip noisy lines
                    skip = ["urllib3", "warnings.warn", "UserWarning",
                            "hipBLAS", "BertModel", "UNEXPECTED",
                            "RequestsDependency", "Loading weights"]
                    if any(s in line for s in skip):
                        continue
                    ltype, col = classify_line(line)
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    # Clean line
                    line = re.sub(r'\033\[[0-9;]*m', '', line)  # strip ansi
                    entry = (ts, ltype, col, line[:55])
                    with stream_lock:
                        stream_lines.append(entry)
        except Exception:
            pass
        time.sleep(0.3)

# ─── DRAW ─────────────────────────────────────────────────────────────────────

def draw():
    os.system("clear")
    W = WIDTH
    now = datetime.datetime.now().strftime("%d-%b-%Y  %H:%M:%S")
    up  = uptime()

    def hline(left="╠", mid="═", right="╣", label=""):
        if label:
            pad = mid * 3
            rest = mid * (W - len(label) - 8)
            return f"{DCY}{left}{pad}[{R}{CY}{B}{label}{R}{DCY}]{rest}{right}{R}"
        return f"{DCY}{left}{mid * (W-2)}{right}{R}"

    def box_line(content):
        # content should be exactly W-2 wide
        return f"{DCY}║{R}{content}{DCY}║{R}"

    # ── HEADER ────────────────────────────────────────────────────────────────
    title = f" NEX v1.2  ◆  DYNAMIC INTELLIGENCE "
    ts_str = f" {now}  UP {up} "
    gap = W - 2 - len(title) - len(ts_str)
    print(f"{DCY}╔{'═'*(W-2)}╗{R}")
    print(box_line(f"{CY}{B}{title}{R}{' '*gap}{DM}{ts_str}{R}"))

    # ── PLATFORMS ─────────────────────────────────────────────────────────────
    print(hline())
    plats = stats["platforms"]
    pline = "  "
    for name, state in plats.items():
        col = platform_color(state)
        dot = "●" if state == "LIVE" else ("◐" if state == "RECENT" else "○")
        pline += f"{col}{dot}{name}{R}{DM}:{state}{R}  "
    print(box_line(f"{pline:<{W-2}}"))

    # ── STATUS ROW ────────────────────────────────────────────────────────────
    print(hline())
    scol = GR if stats["status"] == "ACTIVE" else RD
    lcol = GR if stats["llm"] == "ONLINE" else RD
    bcol = GR if stats["brain_alive"] else RD
    tcol = GR if stats["telegram_alive"] else YL

    s1 = f"  {CY}STATUS{R} {scol}{B}{stats['status']:<8}{R}  {CY}LLM{R} {lcol}{B}{stats['llm']:<8}{R}  {CY}TELEGRAM{R} {tcol}{'ONLINE' if stats['telegram_alive'] else 'OFFLINE':<8}{R}"
    print(box_line(f"{s1:<{W+30}}"))

    s2 = f"  {CY}REPLIED{R} {WH}{stats['replied']:<6}{R}  {CY}LEARNT{R} {WH}{stats['learnt']:<6}{R}  {CY}POSTED{R} {WH}{stats['posted']:<6}{R}  {CY}CHATTED{R} {WH}{stats['chatted']:<6}{R}"
    print(box_line(f"{s2:<{W+60}}"))

    # ── METRICS ROW ───────────────────────────────────────────────────────────
    print(hline())
    s3 = f"  {CY}BELIEFS{R} {YL}{B}{stats['beliefs']:<6}{R}  {CY}CONF{R} {WH}{stats['conf']}%{R}  {CY}ALIGN{R} {WH}{stats['align']}%{R}  {CY}NETWORK{R} {WH}{stats['network']}%{R}  {CY}IQ{R} {GR}{B}{stats['iq']}%{R}"
    print(box_line(f"{s3:<{W+70}}"))

    s4 = f"  {CY}ORIGINAL BELIEFS{R} {YL}{stats['original']}{R}{DM} (NEX-generated){R}   {CY}REFLECTS{R} {WH}{stats['reflects']}{R}"
    print(box_line(f"{s4:<{W+30}}"))

    # ── GPU ROW ───────────────────────────────────────────────────────────────
    print(hline("╠","═","╣","GPU"))
    gpu_pct = stats["gpu_pct"]
    gpu_w   = stats["gpu_w"]
    gcol    = GR if gpu_pct < 60 else (YL if gpu_pct < 85 else RD)
    gb      = bar(gpu_pct, 12)
    wb      = bar(min(gpu_w, stats["gpu_max"]), 10, "▓", "░")
    gline   = f"  {CY}USAGE{R} {gcol}{gb}{R} {WH}{gpu_pct}%{R}     {CY}POWER{R} {gcol}{wb}{R} {WH}{gpu_w}W / {stats['gpu_max']}W{R}"
    print(box_line(f"{gline:<{W+50}}"))

    # ── KNOWLEDGE ─────────────────────────────────────────────────────────────
    print(hline())
    kline = f"  {CY}KNOWLEDGE GAPS{R} {YL}{stats['gaps']} topics{R}   {CY}NEEDS{R} {DM}{stats['needs']}{R}"
    print(box_line(f"{kline:<{W+30}}"))

    # ── CRASH ALERT ───────────────────────────────────────────────────────────
    dead = []
    if not stats["brain_alive"]:    dead.append("BRAIN")
    if not stats["llama_alive"]:    dead.append("LLM")
    if not stats["telegram_alive"]: dead.append("TELEGRAM")
    if dead:
        alert = f"  {RD}{B}✗ DEAD: {' | '.join(dead)}{R}"
        print(box_line(f"{alert:<{W+20}}"))

    # ── LIVE STREAM ───────────────────────────────────────────────────────────
    print(hline("╠","═","╣","LIVE STREAM"))
    with stream_lock:
        lines = list(stream_lines)

    # Pad to MAX_STREAM
    while len(lines) < MAX_STREAM:
        lines.insert(0, None)

    for entry in lines:
        if entry is None:
            print(box_line(f"{DM}{'':>{W-2}}{R}"))
        else:
            ts, ltype, col, text = entry
            type_str = f"{ltype:<7}"
            line_str = f"  {DM}{ts}{R}  {col}{B}{type_str}{R}  {WH}{text}{R}"
            print(box_line(f"{line_str:<{W+40}}"))

    # ── FOOTER ────────────────────────────────────────────────────────────────
    print(f"{DCY}╚{'═'*(W-2)}╝{R}")

# ─── UPDATE LOOP ──────────────────────────────────────────────────────────────

def updater():
    while True:
        try:
            check_processes()
            get_db_stats()
            parse_auto_log()
            pct, w = get_gpu()
            stats["gpu_pct"] = pct
            stats["gpu_w"]   = w
        except Exception:
            pass
        time.sleep(REFRESH)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"{CY}NEX HUD starting...{R}")

    # Start background threads
    t1 = threading.Thread(target=stream_log, daemon=True)
    t2 = threading.Thread(target=updater, daemon=True)
    t1.start()
    t2.start()

    # Initial data load
    time.sleep(2)

    try:
        while True:
            draw()
            time.sleep(REFRESH)
    except KeyboardInterrupt:
        print(f"\n{CY}NEX HUD stopped.{R}")

if __name__ == "__main__":
    main()
