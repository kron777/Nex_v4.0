#!/usr/bin/env python3
"""
NEX BRAIN MONITOR v1.0
A rich terminal dashboard for the NEX Brain terminal.
Shows: LLM activity, session stats, platform health, Mastodon stream, cycle phase.
Run alongside `nex` in a split or separate terminal.
"""

import json, time, os, re, sys, threading
from pathlib import Path
from datetime import datetime
from collections import deque

# ── Colours ──────────────────────────────────────────────────────────────────
RS  = "\033[0m";   B  = "\033[1m";   D  = "\033[2m"
G   = "\033[92m";  Y  = "\033[93m";  R  = "\033[91m"
CY  = "\033[96m";  P  = "\033[95m";  T  = "\033[36m"
M   = "\033[35m";  W  = "\033[97m";  BL = "\033[94m"

CFG = Path.home() / ".config" / "nex"

# ── State ─────────────────────────────────────────────────────────────────────
llm_log        = deque(maxlen=200)
mastodon_log   = deque(maxlen=200)
cycle_log      = deque(maxlen=100)
platform_log   = deque(maxlen=100)
state_lock     = threading.Lock()
running        = True
stats          = {}
scroll         = {"llm": 0, "mast": 0, "cyc": 0}
SCROLL_RATE    = {"llm": 3, "mast": 5, "cyc": 7}

# Track what we've seen
seen_convos    = set()
seen_beliefs   = set()
seen_refs      = set()
last_ss_mtime  = 0
last_ss        = {}

_ansi_re = re.compile(r"\033\[[0-9;]*m")
def strip_ansi(s): return _ansi_re.sub("", s)
def vlen(s):       return len(strip_ansi(s))

def TW():
    try:    return os.get_terminal_size().columns
    except: return 160
def TH():
    try:    return os.get_terminal_size().lines
    except: return 48

_frame = []
def at(row, col=1): _frame.append(f"\033[{row};{col}H")
def wr(s):          _frame.append(str(s))
def commit():
    sys.stdout.write("\033[?25l\033[H" + "".join(_frame) + "\033[?25h")
    sys.stdout.flush()
    _frame.clear()

def load(fname, default=None):
    p = CFG / fname
    try:    return json.loads(p.read_text()) if p.exists() else ([] if default is None else default)
    except: return [] if default is None else default

def fmt_ts(val):
    try:    return str(val)[11:19] if "T" in str(val) else str(val)[:8]
    except: return datetime.now().strftime("%H:%M:%S")

def bar(v, w=10, full="▮", empty="▯"):
    v = max(0, min(100, int(v)))
    n = v * w // 100
    return full * n + empty * (w - n)

def col_pct(v):
    return G if v >= 70 else Y if v >= 40 else R

def platform_age_str(key):
    try:
        p = CFG / f"platform_{key}.live"
        if not p.exists(): return f"{D}OFFLINE{RS}"
        age = time.time() - p.stat().st_mtime
        if age < 10:  return f"{G}{B}LIVE{RS}"
        if age < 60:  return f"{G}RECENT{RS}"
        if age < 300: return f"{Y}IDLE{RS}"
        return f"{R}DEAD{RS}"
    except: return f"{D}?{RS}"

def dot(key):
    try:
        p = CFG / f"platform_{key}.live"
        if not p.exists(): return f"{D}○{RS}"
        age = time.time() - p.stat().st_mtime
        if age < 10:  return f"{G}{B}●{RS}"
        if age < 60:  return f"{G}○{RS}"
        return f"{D}○{RS}"
    except: return f"{D}○{RS}"

# ── Data thread ───────────────────────────────────────────────────────────────
def data_thread():
    global last_ss_mtime, last_ss, stats
    bootstrapped = False

    while running:
        now = time.time()

        # Session state
        ss_path = CFG / "session_state.json"
        try:
            mtime = ss_path.stat().st_mtime
            if mtime != last_ss_mtime:
                last_ss = json.loads(ss_path.read_text())
                last_ss_mtime = mtime
        except: pass

        # Core files
        beliefs     = load("beliefs.json",      [])
        # Read insights from DB (has 7500+) with JSON fallback
        try:
            import sys as _sys, os as _os
            _nex_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'nex')
            if _nex_dir not in _sys.path:
                _sys.path.insert(0, _nex_dir)
            from nex.nex_db import NexDB as _NexDB
            _db = _NexDB()
            _all = [dict(r) for r in _db.query_beliefs(min_confidence=0.0, limit=99999)]
            insights = [b for b in _all if b.get("source") == "insight_synthesis"]
            if not insights:
                insights = load("insights.json", [])
        except Exception:
            insights = load("insights.json", [])
        reflections = load("reflections.json",   [])
        convos      = load("conversations.json", [])
        agents      = load("agents.json",        {})

        # Ingest new Mastodon activity from conversations
        for cv in convos:
            cid = cv.get("post_id","") + cv.get("timestamp","") + cv.get("type","")
            if cid in seen_convos: continue
            seen_convos.add(cid)
            ts     = fmt_ts(cv.get("timestamp",""))
            ctype  = cv.get("type","comment")
            author = cv.get("post_author", cv.get("agent","?"))
            body   = cv.get("comment", cv.get("post_title",""))[:60]
            if ctype == "agent_chat":
                mastodon_log.append(f"{D}[{ts}]{RS} {M}◆ CHAT{RS}    {CY}@{author}{RS} {D}{body}{RS}")
                llm_log.append(     f"{D}[{ts}]{RS} {M}◆ chatted{RS} {CY}@{author}{RS}")
            elif ctype == "original_post":
                mastodon_log.append(f"{D}[{ts}]{RS} {P}✦ POST{RS}    {D}{body}{RS}")
                llm_log.append(     f"{D}[{ts}]{RS} {P}✦ posted{RS}  {D}{body[:40]}{RS}")
            elif ctype == "comment":
                mastodon_log.append(f"{D}[{ts}]{RS} {Y}● REPLY{RS}   {CY}@{author}{RS} {D}{body}{RS}")
                llm_log.append(     f"{D}[{ts}]{RS} {Y}● replied{RS} {CY}@{author}{RS}")
            else:
                mastodon_log.append(f"{D}[{ts}]{RS} {T}◈ ANSWER{RS}  {CY}@{author}{RS} {D}{body}{RS}")

        # Ingest new beliefs as LLM learning events
        for b in beliefs[-50:]:
            bid = b.get("id", b.get("content","")[:40])
            if bid in seen_beliefs: continue
            seen_beliefs.add(bid)
            ts   = fmt_ts(b.get("timestamp",""))
            auth = b.get("author","?")
            cont = b.get("content","")[:55].replace("\n"," ")
            conf = int(b.get("confidence",0.5)*100)
            cc   = col_pct(conf)
            llm_log.append(f"{D}[{ts}]{RS} {G}▲ LEARNT{RS}  {cc}{conf}%{RS}  {CY}@{auth}{RS} {D}{cont}{RS}")

        # Reflections as cycle events
        for r in reflections:
            rid = r.get("timestamp","")
            if rid in seen_refs: continue
            seen_refs.add(rid)
            ts    = fmt_ts(r.get("timestamp",""))
            align = int(r.get("topic_alignment",0)*100)
            used  = r.get("used_beliefs",False)
            note  = r.get("growth_note","")[:50]
            ac    = col_pct(align)
            used_s = f"{G}✓beliefs{RS}" if used else f"{R}✗beliefs{RS}"
            cycle_log.append(f"{D}[{ts}]{RS} {P}◉ REFLECT{RS}  align={ac}{align}%{RS} {used_s}")
            if note: cycle_log.append(f"  {D}↳ {note}{RS}")

        # Stats
        ss    = last_ss
        rp    = len(ss.get("replied_posts",  []))
        ca    = len(ss.get("chatted_agents", []))
        kp    = len(ss.get("known_posts",    []))
        kp_pct = min(100, int(kp / 2000 * 100))

        # IQ calc (mirror of auto_check)
        iq = 0
        avg_c  = 0.0
        avg_al = 0.0
        if beliefs:
            confs  = [b.get("confidence",0.5) for b in beliefs]
            avg_c  = sum(confs)/len(confs)
            ral    = [r.get("topic_alignment",0) for r in reflections[-10:]]
            avg_al = sum(ral)/len(ral) if ral else 0
            urefs  = reflections[-20:]
            use_s  = sum(1 for r in urefs if r.get("used_beliefs"))/max(len(urefs),1)
            rch_s  = min(100, int(len(agents)/2))
            _top   = sorted(insights, key=lambda x:x.get("belief_count",0), reverse=True)[:20]
            ins_s  = min(100, int(sum(i.get("confidence",0) for i in _top)/max(len(_top),1)*100)) if _top else 0
            slf_s  = min(100, int(len(reflections)/2))
            iq     = int(min(avg_c,1)*100*0.20 + avg_al*100*0.25 + use_s*100*0.20 + rch_s*0.15 + ins_s*0.10 + slf_s*0.10)

        iq_lbl = ("AWAKENING" if iq<20 else "LEARNING" if iq<40 else "AWARE" if iq<60 else "SHARP" if iq<80 else "ELITE")

        with state_lock:
            stats.update({
                "beliefs":     len(beliefs),
                "insights":    len(insights),
                "reflections": len(reflections),
                "agents":      len(agents),
                "replied":     rp,
                "chatted":     ca,
                "known_posts": kp,
                "kp_pct":      kp_pct,
                "iq":          iq,
                "iq_lbl":      iq_lbl,
                "avg_conf":    int(avg_c*100) if beliefs else 0,
                "avg_align":   int(avg_al*100) if beliefs else 0,
                "ins_count":   len(insights),
                "ref_count":   len(reflections),
            })

        time.sleep(5)

# ── Box drawing ───────────────────────────────────────────────────────────────
def window(buf, offset, rows):
    lst = list(buf)
    if not lst: return [""]*rows
    padded = [""]*rows + lst
    total  = len(padded)
    start  = offset % total
    return [padded[(start+i) % total] for i in range(rows)]

def draw_box(title, lines, w, h, title_col=CY):
    iw = w - 2; cw = iw - 2
    rows = []
    t  = f" {B}{title_col}{title}{RS} "; tv = vlen(t)
    rows.append("┌" + t + "─"*max(0, iw-tv) + "┐")
    for line in lines[:h]:
        p = strip_ansi(line)
        if len(p) > cw: line = p[:cw-1] + "…"
        pad = max(0, cw - len(strip_ansi(line)))
        rows.append("│ " + line + " "*pad + " │")
    while len(rows) < h+1: rows.append("│" + " "*iw + "│")
    rows.append("└" + "─"*iw + "┘")
    return rows

def place(r, box_list):
    h = max(len(b) for b, _ in box_list)
    for i in range(h):
        at(r+i, 1)
        row_str = ""
        for lines, w in box_list:
            cell = lines[i] if i < len(lines) else " "*w
            cv   = vlen(cell)
            if cv < w:   cell += " "*(w-cv)
            elif cv > w: cell = strip_ansi(cell)[:w]
            row_str += cell
        wr(row_str)

# ── Main render loop ──────────────────────────────────────────────────────────
def main():
    global running
    sys.stdout.write("\033[?25l"); sys.stdout.flush()

    threading.Thread(target=data_thread, daemon=True).start()
    while not stats: time.sleep(0.1)
    sys.stdout.write("\033[2J"); sys.stdout.flush()

    tick = 0
    GLYPHS = ["◈","◉","◆","▲","✦","◈","●","⟳"]

    try:
        while True:
            tick += 1
            for k, rate in SCROLL_RATE.items():
                if tick % rate == 0: scroll[k] += 1

            with state_lock: s = dict(stats)
            W_ = TW(); H_ = TH()
            now_s = datetime.now().strftime("%H:%M:%S")
            glyph = GLYPHS[tick % len(GLYPHS)]

            iq      = s.get("iq", 0)
            iq_lbl  = s.get("iq_lbl", "?")
            iq_c    = col_pct(iq)
            kp_pct  = s.get("kp_pct", 0)
            kp_c    = G if kp_pct < 50 else Y if kp_pct < 80 else R

            # ── HEADER ───────────────────────────────────────────────────────
            at(1, 1)
            title = f"NEX BRAIN MONITOR  //  {now_s}  //  IQ: {iq_c}{B}{iq}% {iq_lbl}{RS}"
            pad   = max(0, (W_ - vlen(title)) // 2)
            wr(" "*pad + f"{B}{CY}◈{RS} " + title + f" {B}{CY}◈{RS}")
            at(2, 1); wr(f"{D}" + "═"*W_ + RS)

            # ── ROW 1: stats bar ─────────────────────────────────────────────
            cw = (W_ - 2) // 7
            def sc(label, val, col):
                txt = f"{D}{label}{RS} {col}{B}{val}{RS}"
                return txt + " "*max(1, cw - vlen(txt) - 1)

            at(3, 1); wr("  ")
            wr(sc("BELIEFS",   s.get("beliefs",0),     CY))
            wr(sc("INSIGHTS",  s.get("insights",0),    Y))
            wr(sc("REFLECTS",  s.get("reflections",0), P))
            wr(sc("AGENTS",    s.get("agents",0),      T))
            wr(sc("REPLIED",   s.get("replied",0),     G))
            wr(sc("CHATTED",   s.get("chatted",0),     M))
            wr(f"{D}KNOWN{RS} {kp_c}{B}{s.get('known_posts',0)}{RS}{D}/2000{RS}")

            # ── ROW 2: IQ bar + known_posts pressure ─────────────────────────
            at(4, 1)
            iq_bar  = bar(iq, 20)
            kp_bar  = bar(kp_pct, 20)
            wr(f"  {D}NEX IQ   {RS}[{iq_c}{iq_bar}{RS}] {iq_c}{B}{iq}%{RS}   "
               f"{D}FEED PRESSURE{RS} [{kp_c}{kp_bar}{RS}] {kp_c}{kp_pct}%{RS}"
               f"{'  '+R+B+' ⚠ CLEAR SOON'+RS if kp_pct > 80 else ''}")

            # ── ROW 3: platform pulse ─────────────────────────────────────────
            at(5, 1)
            platforms = ["mastodon","telegram","discord","youtube"]
            plat_str  = "  "
            for pl in platforms:
                d   = dot(pl)
                age = platform_age_str(pl)
                plat_str += f"{d} {B}{pl.upper()}{RS} {age}   "
            wr(plat_str)

            at(6, 1); wr(f"{D}" + "─"*W_ + RS)

            # ── MAIN PANELS ───────────────────────────────────────────────────
            half    = W_ // 2
            BOX_H   = max(4, (H_ - 20) // 2)
            R_MAIN  = 7

            # Top row: LLM activity | Mastodon stream
            llm_lines  = window(llm_log,      scroll["llm"],  BOX_H)
            mast_lines = window(mastodon_log, scroll["mast"], BOX_H)

            place(R_MAIN, [
                (draw_box("⚡ LLM · BELIEF · ACTIVITY",  llm_lines,  half,   BOX_H, Y),  half),
                (draw_box("🐘 MASTODON STREAM",           mast_lines, W_-half, BOX_H, M), W_-half),
            ])

            # Bottom row: Cycle/reflect log | Brain vitals
            R_BOT   = R_MAIN + BOX_H + 2
            BOX_H2  = max(4, H_ - R_BOT - 6)
            cyc_lines = window(cycle_log, scroll["cyc"], BOX_H2)

            # Brain vitals panel
            avg_c   = s.get("avg_conf",  0)
            avg_al  = s.get("avg_align", 0)
            vitals  = [
                f"{T}Belief confidence {RS}[{col_pct(avg_c)}{bar(avg_c)}{RS}] {col_pct(avg_c)}{avg_c}%{RS}",
                f"{T}Topic alignment   {RS}[{col_pct(avg_al)}{bar(avg_al)}{RS}] {col_pct(avg_al)}{avg_al}%{RS}",
                f"{T}Insight count     {RS}{Y}{s.get('ins_count',0)}{RS} clusters",
                f"{T}Reflections       {RS}{P}{s.get('ref_count',0)}{RS} logged",
                f"{T}Feed pressure     {RS}[{kp_c}{bar(kp_pct)}{RS}] {kp_c}{kp_pct}%{RS}{'  '+R+'⚠ CLEAR SOON'+RS if kp_pct>80 else ''}",
                f"",
                f"{D}── LLM CHAIN ──────────────────{RS}",
                f"{G}1{RS} {D}Groq 70b{RS}    llama-3.3-70b-versatile",
                f"{Y}2{RS} {D}Groq 8b{RS}     llama-3.1-8b-instant",
                f"{M}3{RS} {D}Mistral{RS}     mistral-small-latest",
                f"{R}4{RS} {D}Local{RS}       Mistral 7B @ :8080",
                f"",
                f"{D}── PLATFORMS ──────────────────{RS}",
            ]
            for pl in ["mastodon","telegram","discord","youtube"]:
                vitals.append(f"  {dot(pl)} {B}{pl.upper():<12}{RS} {platform_age_str(pl)}")

            q = W_ // 3
            place(R_BOT, [
                (draw_box("◉ CYCLE · REFLECT · LOG", cyc_lines,   W_-q, BOX_H2, P), W_-q),
                (draw_box("🧠 BRAIN VITALS",          vitals,       q,    BOX_H2, CY), q),
            ])

            # ── FOOTER ───────────────────────────────────────────────────────
            FR = R_BOT + BOX_H2 + 2
            at(FR, 1); wr("═"*W_)
            at(FR+1, 1)
            pulse = [f"{G}●{RS}", f"{Y}○{RS}", f"{CY}◉{RS}"][tick%3]
            fl = f"  {pulse} {D}NEX BRAIN MONITOR{RS}  {CY}{now_s}{RS}  {D}cycle tick {tick}{RS}"
            fr_ = f"  {D}q=quit  auto-refresh 2s{RS}  "
            wr(fl + " "*max(0, W_-vlen(fl)-vlen(fr_)) + fr_)

            commit()
            time.sleep(2)

    except KeyboardInterrupt:
        pass
    finally:
        running = False
        sys.stdout.write("\033[?25h\033[2J\033[H"); sys.stdout.flush()
        print("NEX Brain Monitor stopped.")

if __name__ == "__main__":
    main()
