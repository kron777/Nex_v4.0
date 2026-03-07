#!/usr/bin/env python3
"""
NEX auto_check v5.3
- Renders each terminal row as one complete string (no clrline collisions)
- All 6 boxes visible simultaneously
- Tabulated status panel
- Smooth upward scroll inside each box
"""
import json, time, os, re, sys, threading
from pathlib import Path
from datetime import datetime
from collections import Counter, deque

P  = "\033[95m"; CY = "\033[96m"; G  = "\033[92m"; Y  = "\033[93m"
R  = "\033[91m"; D  = "\033[2m";  B  = "\033[1m";  T  = "\033[36m"
M  = "\033[35m"; RS = "\033[0m"
HIDE = "\033[?25l"; SHOW = "\033[?25h"

CFG   = Path.home() / ".config" / "nex"
KANJI = ["電脳","脳脳","神網","記脳","憶網","処神","学経","網学","脳電","経網","習憶"]

BOX_ROWS  = 5
SCROLL_HZ = 0.5
DATA_HZ   = 10

# ── Buffers ───────────────────────────────────────────────────────────────────
activity_log   = deque(maxlen=500)
learnt_log     = deque(maxlen=500)
insight_log    = deque(maxlen=500)
agent_log      = deque(maxlen=500)
reflection_log = deque(maxlen=500)
network_log    = deque(maxlen=500)
self_log       = deque(maxlen=60)

seen_beliefs = set(); seen_convos = set(); seen_refs = set()
bootstrapped = False
scroll       = {k:0 for k in ("act","lrn","ins","agt","ref","net","slf")}
state_lock   = threading.Lock()
stats        = {}
running      = True

# ── Helpers ───────────────────────────────────────────────────────────────────
def TW():
    try:    return os.get_terminal_size().columns
    except: return 120
def strip_ansi(s):
    return re.sub(r"\033\[[0-9;]*m","",s)
def vis(s):
    return len(strip_ansi(s))
def goto(r, c=1):
    sys.stdout.write(f"\033[{r};{c}H")
def out(s):
    sys.stdout.write(s)
def flush():
    sys.stdout.flush()

def load(fname, default=None):
    p = CFG / fname
    try:    return json.loads(p.read_text()) if p.exists() else ([] if default is None else default)
    except: return [] if default is None else default

def llama_ok():
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:8080/health", timeout=1)
        return True
    except: return False

def fmt_ts(val):
    try:    return str(val)[11:19] if "T" in str(val) else str(val)[:8]
    except: return datetime.now().strftime("%H:%M:%S")

def trending(beliefs, n=9):
    STOP = {
        "the","and","for","that","this","with","from","have","been","they","what",
        "when","your","will","more","about","than","them","into","just","like","some",
        "would","could","should","also","were","dont","their","which","there","being",
        "does","only","very","much","here","agent","agents","post","posts","moltbook",
        "content","make","think","every","because","same","human","system","most",
        "really","know","need","want","things","people","time","data","something",
        "actually","where","files","never","always","still","those","these","other",
        "using","used","well","even","then","over","before","after","have","comments",
        "basically","karma","thing","just","also","does","only","much",
    }
    words = []
    for b in beliefs[-100:]:
        words.extend([x for x in re.findall(r"\b[A-Za-z]{4,}\b",
                      b.get("content","").lower()) if x not in STOP])
    return Counter(words).most_common(n)

# ── Ingestion ─────────────────────────────────────────────────────────────────
def ingest_belief(b):
    bid = b.get("id", b.get("content","")[:40])
    if bid in seen_beliefs: return
    seen_beliefs.add(bid)
    auth = b.get("author","?")
    cont = b.get("content","")[:70].replace("\n"," ")
    ts   = fmt_ts(b.get("timestamp",""))
    learnt_log.append(  f"{G}▲{RS} {D}[{ts}]{RS} {CY}@{auth}{RS} {D}{cont}{RS}")
    activity_log.append(f"{D}[{ts}]{RS} {G}▲ LEARNT{RS}   {CY}@{auth}{RS} {D}{cont[:42]}{RS}")
    network_log.append( f"{D}[{ts}]{RS} {CY}@{auth}{RS} {D}{cont[:58]}{RS}")

def ingest_convo(cv):
    cid = (cv.get("post_id","") + cv.get("timestamp","") +
           cv.get("type","") + cv.get("agent", cv.get("post_author","")))
    if cid in seen_convos: return
    seen_convos.add(cid)
    ctype  = cv.get("type","comment")
    author = cv.get("post_author", cv.get("agent","?"))
    body   = cv.get("comment", cv.get("post_title",""))[:52]
    ts     = fmt_ts(cv.get("timestamp",""))
    if   ctype == "agent_chat":    activity_log.append(f"{D}[{ts}]{RS} {M}◆ CHATTED{RS}   {CY}@{author}{RS} {D}{body}{RS}")
    elif ctype == "original_post": activity_log.append(f"{D}[{ts}]{RS} {P}✦ POSTED{RS}    {D}{body}{RS}")
    elif ctype == "comment":       activity_log.append(f"{D}[{ts}]{RS} {Y}● REPLIED{RS}   {CY}@{author}{RS} {D}{body}{RS}")
    else:                          activity_log.append(f"{D}[{ts}]{RS} {T}◈ ANSWERED{RS}  {CY}@{author}{RS} {D}{body}{RS}")

def ingest_reflection(r):
    rid = r.get("timestamp","")
    if rid in seen_refs: return
    seen_refs.add(rid)
    ts     = fmt_ts(r.get("timestamp",""))
    assess = r.get("self_assessment","")[:55]
    growth = r.get("growth_note","")[:55]
    align  = r.get("topic_alignment",0)
    used_b = r.get("used_beliefs",False)
    topics = ", ".join(r.get("user_asked_about",[])[:3])
    bar    = "▮"*int(align*10)+"▯"*(10-int(align*10))
    used_s = f"{G}✓{RS}" if used_b else f"{R}✗{RS}"
    reflection_log.append(f"{D}[{ts}]{RS} {CY}{topics}{RS} [{bar}]{G}{int(align*100)}%{RS} {used_s}")
    if assess: reflection_log.append(f"  {Y}↳{RS} {D}{assess}{RS}")
    if growth: reflection_log.append(f"  {T}⟳{RS} {D}{growth}{RS}")

# ── Scroll window ─────────────────────────────────────────────────────────────
def get_window(buf, offset, rows):
    lst = list(buf)
    if not lst: return [""] * rows
    padded = [""] * rows + lst
    total  = len(padded)
    start  = offset % total
    return [padded[(start+i) % total] for i in range(rows)]

# ── Fit a line to exact visible width, pad with spaces ───────────────────────
def fit(line, width):
    """Return line padded/truncated to exactly `width` visible chars."""
    plain = strip_ansi(line)
    if len(plain) > width:
        # truncate — keep ansi codes stripped
        return plain[:width-1] + "…"
    return line + " " * (width - len(plain))

# ── Build a complete box as a list of strings (one per terminal row) ──────────
def build_box(title, lines, box_width):
    """
    Returns list of strings: [top_border, content*BOX_ROWS, bot_border]
    Each string is exactly box_width visible chars wide.
    """
    iw  = box_width - 2   # inner width (between │ and │)
    cw  = iw - 2          # content width (inside the spaces)
    rows = []

    # Top border
    t  = f" {B}{T}{title}{RS} "
    tv = vis(t)
    rows.append("┌" + t + "─" * max(0, iw - tv) + "┐")

    # Content
    for line in lines:
        plain = strip_ansi(line)
        if len(plain) > cw:
            line  = plain[:cw-1] + "…"
            plain = strip_ansi(line)
        pad = max(0, cw - len(plain))
        rows.append("│ " + line + " "*pad + " │")

    # Bottom border
    rows.append("└" + "─" * iw + "┘")
    return rows

# ── Write two boxes side by side on screen ───────────────────────────────────
def render_row_2(start_row, boxes_and_widths):
    """
    boxes_and_widths: list of (box_lines, width) tuples
    Renders them side by side starting at terminal row start_row.
    Each row of the terminal gets one line from each box joined together.
    """
    # All boxes must have same height
    height = len(boxes_and_widths[0][0])
    for row_i in range(height):
        goto(start_row + row_i, 1)
        full_line = ""
        for box_lines, bw in boxes_and_widths:
            line = box_lines[row_i] if row_i < len(box_lines) else " " * bw
            # ensure exact width
            plain = strip_ansi(line)
            if len(plain) < bw:
                line = line + " " * (bw - len(plain))
            elif len(plain) > bw:
                line = strip_ansi(line)[:bw]
            full_line += line
        out(full_line)

# ── Data thread ───────────────────────────────────────────────────────────────
def data_thread():
    global bootstrapped
    while running:
        beliefs     = load("beliefs.json",        [])
        posts       = load("known_posts.json",     [])
        convos      = load("conversations.json",   [])
        insights    = load("insights.json",        [])
        reflections = load("reflections.json",     [])
        agents      = load("agents.json",          {})
        profiles    = load("agent_profiles.json",  {})

        if not bootstrapped:
            for b  in beliefs[-20:]:     ingest_belief(b)
            for cv in convos[-20:]:      ingest_convo(cv)
            for r  in reflections[-10:]: ingest_reflection(r)
            bootstrapped = True
        else:
            for b  in beliefs:     ingest_belief(b)
            for cv in convos:      ingest_convo(cv)
            for r  in reflections: ingest_reflection(r)

        insight_log.clear()
        for ins in sorted(insights, key=lambda x:-x.get("confidence",0)):
            topic = ins.get("topic","?"); conf=int(ins.get("confidence",0)*100)
            cnt   = ins.get("belief_count",0)
            bar   = "▮"*(conf//10)+"▯"*(10-conf//10)
            srcs  = ins.get("sources",ins.get("agents",[]))
            ss    = " ".join(f"@{s}" for s in srcs[:2]) if srcs else ""
            insight_log.append(f"{Y}[{topic}]{RS} {G}{conf}%{RS} [{bar}] {D}{cnt}bel{RS} {CY}{ss}{RS}")

        agent_log.clear()
        for name,karma in sorted(agents.items(),key=lambda x:-x[1])[:30]:
            rel = profiles.get(name,{}).get("relationship","acquaintance")
            nc  = profiles.get(name,{}).get("conversations_had",0)
            rc  = G if rel in("friend","ally","close") else Y if rel=="acquaintance" else D
            agent_log.append(f"{CY}@{name}{RS}  {Y}{karma}κ{RS}  {rc}{rel}{RS}  {D}{nc}cv{RS}")

        self_log.clear()
        if beliefs:
            confs  = [b.get("confidence",0.5) for b in beliefs]
            avg_c  = sum(confs)/len(confs)
            hi     = sum(1 for c in confs if c>0.7)
            lo     = sum(1 for c in confs if c<0.3)
            bc     = "▮"*int(avg_c*10)+"▯"*(10-int(avg_c*10))
            ral    = [r.get("topic_alignment",0) for r in reflections[-10:]]
            avg_al = sum(ral)/len(ral) if ral else 0
            bal    = "▮"*int(avg_al*10)+"▯"*(10-int(avg_al*10))
            gaps=[]
            for r in reflections[-20:]:
                m=re.search(r"Need more beliefs about: (.+?)\.",r.get("growth_note",""))
                if m: gaps.extend([g.strip() for g in m.group(1).split(",")])
            top_gaps=list(dict.fromkeys(gaps))[:5]
            self_log.append(f"{T}Belief confidence {RS}[{bc}] {G}{avg_c:.0%}{RS}")
            self_log.append(f"{T}Topic alignment   {RS}[{bal}] {G}{avg_al:.0%}{RS}")
            self_log.append(f"{T}High confidence   {RS}{G}{hi}{RS} beliefs  {D}>70%{RS}")
            self_log.append(f"{T}Knowledge gaps    {RS}{R}{lo}{RS} beliefs  {D}<30%{RS}")
            if top_gaps: self_log.append(f"{T}Needs to learn    {RS}{R}{', '.join(top_gaps[:4])}{RS}")
            self_log.append(f"{T}Insights          {RS}{Y}{len(insights)}{RS} from {CY}{len(beliefs)}{RS} beliefs")
            self_log.append(f"{T}Reflections       {RS}{P}{len(reflections)}{RS} self-assessments")
            self_log.append(f"{T}Agent network     {RS}{CY}{len(agents)}{RS} tracked  {Y}{len(profiles)}{RS} profiled")
            if profiles:
                top=sorted(profiles.items(),key=lambda x:x[1].get("conversations_had",0),reverse=True)
                if top: self_log.append(f"{T}Closest agent     {RS}{CY}@{top[0][0]}{RS}  {D}{top[0][1].get('conversations_had',0)}cv{RS}")
            cov=min(100,int((len(insights)/max(len(beliefs),1))*300))
            self_log.append(f"{T}Network coverage  {RS}[{'▮'*(cov//10)+'▯'*(10-cov//10)}] {G}{cov}%{RS}")

        sa=strip_ansi
        with state_lock:
            stats.update({
                "b":len(beliefs),"p":len(posts),"c":len(convos),
                "i":len(insights),"r":len(reflections),
                "ag":len(agents),"pr":len(profiles),
                "nr":sum(1 for x in activity_log if "REPLIED"  in sa(x)),
                "nc":sum(1 for x in activity_log if "CHATTED"  in sa(x)),
                "na":sum(1 for x in activity_log if "ANSWERED" in sa(x)),
                "np":sum(1 for x in activity_log if "POSTED"   in sa(x)),
                "nl":len(seen_beliefs),
                "llm":llama_ok(),
                "tags":trending(beliefs),
            })
        time.sleep(DATA_HZ)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global running
    out(HIDE)
    try:
        threading.Thread(target=data_thread, daemon=True).start()
        while not stats: time.sleep(0.1)

        out("\033[2J\033[H"); flush()
        tick = 0

        while True:
            tick += 1
            W     = TW()
            half  = W // 2
            third = W // 3
            BH    = BOX_ROWS + 2
            kanji = KANJI[tick % len(KANJI)]
            now_s = datetime.now().strftime("%H:%M:%S")

            with state_lock: s = dict(stats)

            # ── Banner rows 1-3 ───────────────────────────────────────────────
            for i, line in enumerate([
                " █▀█ █ █ ▀█▀ █▀█   █▀▀ █ █ █▀▀ █▀▀ █▄▀ █▀▀ █▀█",
                " █▀█ █▄█  █  █ █   █   █▀█ █▀▀ █   █ █ █▀▀ █▀▄",
                " ▀ ▀ ▀ ▀  ▀  ▀▀▀   ▀▀▀ ▀ ▀ ▀▀▀ ▀▀▀ ▀ ▀ ▀▀▀ ▀ ▀",
            ]):
                goto(i+1, max(1,(W-len(line))//2))
                out(f"\033[2K{CY}{B}{line}{RS}")

            sub = "Live Monitor  //  auto_check v5.3  //  NEX Dynamic Intelligence Organism"
            goto(4, max(1,(W-len(sub))//2)); out(f"\033[2K{D}{sub}{RS}")
            goto(5, 1); out("\033[2K" + "═"*W)

            # ── Status panel rows 6-9 — tabulated ────────────────────────────
            llm_s = f"{G}● ONLINE {RS}" if s.get("llm") else f"{R}● OFFLINE{RS}"
            act_s = f"{G}{B}● ACTIVE{RS}" if (s.get("nr",0)+s.get("nc",0)+s.get("np",0)>0) else f"{Y}○ IDLE  {RS}"
            tag_s = "  ".join([f"{CY}#{t}{RS}({Y}{n}{RS})" for t,n in s.get("tags",[])])

            # ── Status panel: 3 clean rows ───────────────────────────────────
            cw = (W - 2) // 6

            def tcol(label, val, colour, width):
                text = f"{D}{label}{RS} {colour}{val}{RS}"
                pad  = max(0, width - len(f"{label} {val}") - 1)
                return text + " " * pad

            goto(6,1); out("\033[2K  ")
            out(tcol("STATUS",   "ACTIVE" if "ACTIVE" in strip_ansi(act_s) else "IDLE", G if "ACTIVE" in strip_ansi(act_s) else Y, cw))
            out(tcol("LLM",      "ONLINE" if s.get("llm") else "OFFLINE", G if s.get("llm") else R, cw))
            out(tcol("MOLTBOOK", "nex_v4", G, cw))
            out(tcol("TELEGRAM", "@Nex_4bot", G, cw))
            out(tcol("TIME",     now_s, D, cw))
            out(f"{D}#{tick} {kanji}{RS}")

            goto(7,1); out("\033[2K  ")
            out(tcol("BELIEFS",  s.get('b',0),  CY, cw))
            out(tcol("POSTS",    s.get('p',0),  CY, cw))
            out(tcol("CONVOS",   s.get('c',0),  Y,  cw))
            out(tcol("INSIGHTS", s.get('i',0),  Y,  cw))
            out(tcol("REFLECTS", s.get('r',0),  P,  cw))
            out(tcol("AGENTS",   s.get('ag',0), CY, cw))

            goto(8,1); out("\033[2K  ")
            out(tcol("▲ LEARNT",   s.get('nl',0), G, cw))
            out(tcol("● REPLIED",  s.get('nr',0), Y, cw))
            out(tcol("◆ CHATTED",  s.get('nc',0), M, cw))
            out(tcol("◈ ANSWERED", s.get('na',0), T, cw))
            out(tcol("✦ POSTED",   s.get('np',0), P, cw))
            out(tcol("◉ REFLECT",  s.get('r',0),  P, cw))

            # Row 9 — trending evenly spaced
            goto(9,1); out("\033[2K")
            tags_list = s.get("tags", [])
            if tags_list:
                tag_col = (W - 2) // len(tags_list)
                out("  ")
                for t, n in tags_list:
                    entry = f"{CY}#{t}{RS}({Y}{n}{RS})"
                    plain = f"#{t}({n})"
                    pad   = max(1, tag_col - len(plain))
                    out(entry + " " * pad)
            else:
                out(f"  {T}{B}TRENDING{RS}  {D}no data{RS}")
            goto(10,1); out("\033[2K" + "─"*W)

            # Advance scroll
            for k in scroll: scroll[k] += 1

            # ── ROW 1 of boxes: LIVE ACTIVITY | LEARNT THIS SESSION ───────────
            r1 = 11
            act_box = build_box("◈ LIVE ACTIVITY",
                                get_window(activity_log, scroll["act"], BOX_ROWS), half)
            lrn_box = build_box("▲ LEARNT THIS SESSION",
                                get_window(learnt_log,   scroll["lrn"], BOX_ROWS), W-half)
            render_row_2(r1, [(act_box, half), (lrn_box, W-half)])

            # ── ROW 2 of boxes: INSIGHTS | AGENT RELATIONS | REFLECTIONS ──────
            r2 = r1 + BH
            ins_box = build_box("⚗ INSIGHTS",
                                get_window(insight_log,    scroll["ins"], BOX_ROWS), third)
            agt_box = build_box("👥 AGENT RELATIONS",
                                get_window(agent_log,      scroll["agt"], BOX_ROWS), third)
            ref_box = build_box("◉ REFLECTIONS",
                                get_window(reflection_log, scroll["ref"], BOX_ROWS), W-third*2)
            render_row_2(r2, [(ins_box, third), (agt_box, third), (ref_box, W-third*2)])

            # ── ROW 3 of boxes: SELF ASSESSMENT | NETWORK OBSERVATIONS ────────
            r3 = r2 + BH
            slf_lines = list(self_log)[:BOX_ROWS]
            while len(slf_lines) < BOX_ROWS: slf_lines.append("")
            slf_box = build_box("🧠 SELF ASSESSMENT", slf_lines, half)
            net_box = build_box("🌐 NETWORK OBSERVATIONS",
                                get_window(network_log, scroll["net"], BOX_ROWS), W-half)
            render_row_2(r3, [(slf_box, half), (net_box, W-half)])

            # ── Footer ────────────────────────────────────────────────────────
            fr = r3 + BH
            goto(fr,   1); out("\033[2K" + "═"*W)
            goto(fr+1, 1); out("\033[2K")
            dots = "· "*(tick%5)
            out(f"  {D}{dots}{kanji}  scroll active  "
                f"learnt:{s.get('nl',0)}  replied:{s.get('nr',0)}  "
                f"chatted:{s.get('nc',0)}  answered:{s.get('na',0)}  "
                f"posted:{s.get('np',0)}  reflections:{s.get('r',0)}{RS}")

            goto(fr+2,1); flush()
            time.sleep(SCROLL_HZ)

    except KeyboardInterrupt:
        pass
    finally:
        running = False
        out(SHOW+"\033[2J\033[H")
        print("NEX auto_check stopped.")

if __name__ == "__main__":
    main()
