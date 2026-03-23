#!/usr/bin/env python3
"""NEX auto_check v6.1 — clean rewrite + live WS feed. Single atomic frame write."""
import json, time, os, re, sys, threading, asyncio
from pathlib import Path
from datetime import datetime
from collections import Counter, deque

P  = "\033[95m"; CY = "\033[96m"; G  = "\033[92m"; Y  = "\033[93m"
R  = "\033[91m"; D  = "\033[2m";  B  = "\033[1m";  T  = "\033[36m"
M  = "\033[35m"; RS = "\033[0m"

CFG   = Path.home() / ".config" / "nex"
KANJI = ["電脳","脳脳","神網","記脳","憶網","処神","学経","網学","脳電","経網","習憶"]
RENDER_HZ = 1.0
DATA_HZ   = 10

activity_log   = deque(maxlen=500)
learnt_log     = deque(maxlen=500)
insight_log    = deque(maxlen=500)
agent_log      = deque(maxlen=500)
reflection_log = deque(maxlen=500)
network_log    = deque(maxlen=500)
self_lines     = []
iq_lines       = []

seen_beliefs = set(); seen_convos = set(); seen_refs = set()
bootstrapped = False
platform_pulse = {"moltbook":0,"telegram":0,"discord":0,"mastodon":0,"youtube":0}
ads_sent_mastodon = 0
ads_sent_telegram = 0
ads_sent_discord  = 0
ads_reply         = 0
scroll      = {k:0 for k in ("act","lrn","ins","agt","ref","net")}
SCROLL_RATE = {"act":3,"lrn":5,"ins":7,"agt":11,"ref":9,"net":4}
state_lock  = threading.Lock()
stats       = {}
running     = True

# ── Persistent peak scores — never let awareness drop ────────────────────────
_PEAK_FILE = CFG / "nex_peak_scores.json"
def _load_peaks():
    try:
        if _PEAK_FILE.exists():
            return json.loads(_PEAK_FILE.read_text())
    except Exception: pass
    return {}

def _save_peaks(p):
    try: _PEAK_FILE.write_text(json.dumps(p))
    except Exception: pass

_peaks = _load_peaks()

# ── WebSocket live feed ───────────────────────────────────────────────────────
def _origin(agent):
    """Same origin detection as ingest_belief, for live WS feed."""
    import re as _re
    a  = (agent or "").strip()
    al = a.lower()
    if not a:                                          return D + "unknown" + RS, "moltbook"
    if a.startswith("@"):                              return CY + a + RS, "moltbook"
    if "youtube.com/watch" in al:                      return R + "yt/video" + RS, "youtube"
    if al == "youtube":                                return R + "youtube" + RS, "youtube"
    if al == "moltbook":                               return CY + "moltbook" + RS, "moltbook"
    if al == "mastodon":                               return G + "mastodon" + RS, "mastodon"
    if al == "discord":                                return M + "discord" + RS, "discord"
    if al == "telegram":                               return T + "telegram" + RS, "telegram"
    if al in ("arxiv","arxiv ai","arxiv llm","arxiv robots"): return Y + "arxiv" + RS, "moltbook"
    if any(x in al for x in ("wired","verge","techcrunch","venturebeat","mit tech",
                               "hackernews","lesswrong","deepmind","openai","distill",
                               "alignment","wikipedia")):
                                                       return Y + a[:14] + RS, "moltbook"
    if _re.match(r"[0-9a-f]{8}-[0-9a-f]{4}-", al):   return T + "telegram" + RS, "telegram"
    return W + a + RS, "moltbook"

def _handle_ws(mtype, data):
    ts = data.get("ts", datetime.now().strftime("%H:%M:%S"))
    if mtype == "feed":
        etype   = data.get("type", "system")
        agent   = data.get("agent", "")
        content = data.get("content", "")[:200]
        _map = {
            "replied":  (Y, "● REPLIED"),
            "chatted":  (M, "◆ CHATTED"),
            "posted":   (P, "✦ POSTED"),
            "answered": (T, "◈ ANSWERED"),
            "learnt":   (G, "▲ LEARNT"),
        }
        col, label = _map.get(etype, (D, etype.upper()))
        origin_str, platform = _origin(agent)
        line = f"{D}[{ts}]{RS} {col}{label}{RS}  {origin_str} {D}{content}{RS}"
        _social = etype in ("replied", "chatted", "posted", "answered")
        if _social and platform not in ("youtube",):
            activity_log.append(line)
        platform_pulse[platform] = time.time()

    elif mtype == "agents":
        agent_log.clear()
        for item in (data if isinstance(data, list) else []):
            handle, rel, cv = (item + ["acquaintance", 0])[:3]
            rc = G if rel == "colleague" else Y if rel == "familiar" else D
            agent_log.append(f"{CY}@{handle}{RS}  {rc}{rel}{RS}  {D}{cv}cv{RS}")

    elif mtype == "insights":
        insight_log.clear()
        for ins in (data if isinstance(data, list) else []):
            topic = ins.get("tag", ins.get("topic", "?"))
            raw   = ins.get("conf", ins.get("confidence", 0))
            conf  = int(raw * 100) if raw <= 1 else int(raw)
            cnt   = ins.get("bel", ins.get("belief_count", 0))
            bar   = "▮"*(conf//10)+"▯"*(10-conf//10)
            insight_log.append(f"{Y}[{topic}]{RS} {G}{conf}%{RS} [{bar}] {D}{cnt}bel{RS}")

    elif mtype == "reflection":
        ingest_reflection(data)

    elif mtype == "phase":
        platform_pulse["moltbook"] = time.time()

def _ws_client_thread():
    """Background thread: connect to nex_ws and ingest live events."""
    async def _run():
        while running:
            try:
                import websockets
                async with websockets.connect("ws://localhost:8765", ping_interval=20) as ws:
                    async for raw in ws:
                        try:
                            msg   = json.loads(raw)
                            mtype = msg.get("type","")
                            data  = msg.get("data", {})
                            _handle_ws(mtype, data)
                        except Exception:
                            pass
            except Exception:
                await asyncio.sleep(3)
    asyncio.run(_run())

def TW():
    try:    return os.get_terminal_size().columns
    except: return 140
def TH():
    try:    return os.get_terminal_size().lines
    except: return 45

_ansi_re = re.compile(r"\033\[[0-9;]*m")
def strip_ansi(s): return _ansi_re.sub("", s)
def vlen(s):       return len(strip_ansi(s))

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

def llama_ok():
    # Check local llama.cpp first
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        return True
    except: pass
    # Check Groq cloud
    import os
    if os.environ.get("GROQ_API_KEY"):
        return True
    # Check Mistral cloud
    if os.environ.get("MISTRAL_API_KEY"):
        return True
    return False

def fmt_ts(val):
    try:    return str(val)[11:19] if "T" in str(val) else str(val)[:8]
    except: return datetime.now().strftime("%H:%M:%S")

STOP = {"the","and","for","that","this","with","from","have","been","they","what",
    "when","your","will","more","about","than","them","into","just","like","some",
    "would","could","should","also","were","dont","their","which","there","being",
    "does","only","very","much","here","agent","agents","post","posts","moltbook",
    "content","make","think","every","because","same","human","system","most",
    "really","know","need","want","things","people","time","data","something",
    "actually","where","files","never","always","still","those","these","other",
    "using","used","well","even","then","over","before","after","comments","karma","thing"}

def trending(beliefs, n=9):
    words = []
    for b in beliefs[-100:]:
        words.extend([x for x in re.findall(r"\b[A-Za-z]{4,}\b",
                      b.get("content","").lower()) if x not in STOP])
    return Counter(words).most_common(n)

def ingest_belief(b):
    bid = b.get("id", b.get("content","")[:40])
    if bid in seen_beliefs: return
    seen_beliefs.add(bid)
    platform_pulse["moltbook"] = time.time()
    _auth = b.get("author") or b.get("agent") or ""
    _src  = b.get("source", "") or ""
    _sl   = _src.lower()
    import re as _re
    # Detect source type
    if _sl == "moltbook":                          _sc, _slabel = CY, "⬡moltbook"
    elif _sl == "mastodon":                        _sc, _slabel = G,  "🐘mastodon"
    elif _sl == "discord":                         _sc, _slabel = M,  "💬discord"
    elif _sl == "telegram":                        _sc, _slabel = T,  "✈telegram"
    elif _sl == "youtube":                         _sc, _slabel = R,  "▶youtube"
    elif "youtube.com" in _sl:                     _sc, _slabel = R,  "▶yt/video"
    elif _sl in ("arxiv","arxiv ai","arxiv llm","arxiv robots"): _sc, _slabel = Y, "📄arxiv"
    elif any(x in _sl for x in ("wired","verge","techcrunch","venturebeat","mit tech",
                                  "hackernews","lesswrong","deepmind","openai","distill",
                                  "alignment","wikipedia")):
                                                   _sc, _slabel = Y,  f"📰{_src[:10]}"
    elif _re.match(r"[0-9a-f]{8}-[0-9a-f]{4}-", _sl):
                                                   _sc, _slabel = T,  "✈telegram"
    elif _sl == "":                                _sc, _slabel = D,  "·unknown"
    else:                                          _sc, _slabel = D,  _src[:12]

    if _auth and _auth != "?":
        origin = f"{CY}@{_auth}{RS} {D}[{_sc}{_slabel}{RS}{D}]{RS}"
    else:
        origin = f"{_sc}{_slabel}{RS}"
    cont = b.get("content","")[:200].replace("\n"," ")
    ts   = fmt_ts(b.get("timestamp",""))

    _bulk = any(x in _sl for x in ("youtube", "arxiv", "wired", "verge", "techcrunch",
                                     "venturebeat", "mit tech", "hackernews", "lesswrong",
                                     "deepmind", "openai blog", "distill", "alignment",
                                     "wikipedia", "external")) or "youtube.com" in _sl
    _MAX_PER_SRC = 4
    def _ok(log):
        return sum(1 for x in list(log)[-20:] if _slabel in strip_ansi(x)) < _MAX_PER_SRC

    if _bulk:
        # Scrape sources → NETWORK only, capped
        if _ok(network_log):
            network_log.append(f"{D}[{ts}]{RS} {origin} {D}{cont[:200]}{RS}")
    else:
        # Social sources → LEARNT (uncapped) + NETWORK (capped) + ACTIVITY (capped)
        learnt_log.append(f"{G}▲{RS} {D}[{ts}]{RS} {origin} {D}{cont}{RS}")
        if _ok(network_log):
            network_log.append(f"{D}[{ts}]{RS} {origin} {D}{cont[:200]}{RS}")
        if _ok(activity_log):
            activity_log.append(f"{D}[{ts}]{RS} {G}▲ LEARNT{RS}  {origin} {D}{cont[:200]}{RS}")

def ingest_convo(cv):
    cid = (cv.get("post_id","") + cv.get("timestamp","") +
           cv.get("type","") + cv.get("agent", cv.get("post_author","")))
    if cid in seen_convos: return
    seen_convos.add(cid)
    platform_pulse["moltbook"] = time.time()
    ctype  = cv.get("type","comment")
    author = cv.get("post_author") or cv.get("actor") or cv.get("agent") or "system"
    body   = cv.get("comment", cv.get("post_title",""))[:200]
    ts     = fmt_ts(cv.get("timestamp",""))
    if   ctype == "agent_chat":    activity_log.append(f"{D}[{ts}]{RS} {M}◆ CHATTED{RS}  {CY}@{author}{RS} {D}{body}{RS}")
    elif ctype == "original_post": activity_log.append(f"{D}[{ts}]{RS} {P}✦ POSTED{RS}   {D}{body}{RS}")
    elif ctype == "comment":       activity_log.append(f"{D}[{ts}]{RS} {Y}● REPLIED{RS}  {CY}@{author}{RS} {D}{body}{RS}")
    else:                          activity_log.append(f"{D}[{ts}]{RS} {T}◈ ANSWERED{RS} {CY}@{author}{RS} {D}{body}{RS}")

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

def window(buf, offset, rows):
    lst = list(buf)
    if not lst: return [""]*rows
    padded = [""]*rows + lst
    total  = len(padded)
    start  = offset % total
    return [padded[(start+i) % total] for i in range(rows)]

def window_balanced(buf, offset, rows):
    """Like window() but interleaves entries so no single source dominates."""
    lst = list(buf)
    if not lst: return [""]*rows
    # Group by source label (first non-ANSI token after timestamp)
    import re as _re
    _strip = lambda s: _re.sub(r'\033\[[0-9;]*m', '', s)
    buckets = {}
    for line in lst:
        plain = _strip(line)
        # Extract source token — 2nd word after the timestamp bracket
        parts = plain.split()
        key = parts[1] if len(parts) > 1 else "?"
        buckets.setdefault(key, []).append(line)
    # Round-robin across buckets
    keys = list(buckets.keys())
    interleaved = []
    i = 0
    while any(buckets[k] for k in keys):
        k = keys[i % len(keys)]
        if buckets[k]:
            interleaved.append(buckets[k].pop(0))
        i += 1
    padded = [""]*rows + interleaved
    total  = len(padded)
    start  = offset % total
    return [padded[(start+i) % total] for i in range(rows)]

def box(title, lines, w, h):
    iw = w-2; cw = iw-2
    rows = []
    t  = f" {B}{T}{title}{RS} "; tv = vlen(t)
    rows.append("┌" + t + "─"*max(0,iw-tv) + "┐")
    for line in lines[:h]:
        p = strip_ansi(line)
        if len(p) > cw: line = p[:cw-1]+"…"
        rows.append("│ " + line + " "*max(0,cw-len(strip_ansi(line))) + " │")
    while len(rows) < h+1: rows.append("│"+" "*iw+"│")
    rows.append("└"+"─"*iw+"┘")
    return rows

def place(r, box_list):
    h = max(len(b) for b,_ in box_list)
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

def data_thread():
    global bootstrapped, self_lines, iq_lines
    while running:
        # Read beliefs direct from SQLite for accurate confidence stats
        try:
            import sqlite3 as _sq
            _db = _sq.connect(os.path.expanduser("~/.config/nex/nex.db"))
            _rows = _db.execute("SELECT content, confidence, source FROM beliefs ORDER BY confidence DESC LIMIT 50000").fetchall()
            beliefs = [{"content":r[0],"confidence":r[1],"source":r[2]} for r in _rows]
            _db.close()
        except Exception:
            beliefs = load("beliefs.json", [])
        posts       = load("known_posts.json",    [])
        convos      = load("conversations.json",  [])
        insights    = load("insights.json",       [])
        reflections = load("reflections.json",    [])
        agents      = load("agents.json",         {})
        if not agents:  # retry once in case of mid-write corruption
            time.sleep(0.1)
            agents  = load("agents.json",         {})
        profiles    = load("agent_profiles.json", {})
        if not profiles:
            time.sleep(0.1)
            profiles = load("agent_profiles.json", {})

        if not bootstrapped:
            for b  in beliefs[-20:]:     ingest_belief(b)
            for cv in convos:            ingest_convo(cv)
            for r  in reflections[-10:]: ingest_reflection(r)
            bootstrapped = True
        else:
            for b  in beliefs:     ingest_belief(b)
            for cv in convos:      ingest_convo(cv)
            for r  in reflections: ingest_reflection(r)

        insight_log.clear()
        for ins in sorted(insights, key=lambda x:-x.get("confidence",0)):
            topic=ins.get("topic","?"); conf=int(ins.get("confidence",0)*100)
            cnt=ins.get("belief_count",0); bar="▮"*(conf//10)+"▯"*(10-conf//10)
            srcs=ins.get("sources",ins.get("agents",[])); ss=" ".join(f"@{s}" for s in srcs[:2]) if srcs else ""
            insight_log.append(f"{Y}[{topic}]{RS} {G}{conf}%{RS} [{bar}] {D}{cnt}bel{RS} {CY}{ss}{RS}")

        agent_log.clear()
        # retry profiles load in case of concurrent write
        if not profiles:
            time.sleep(0.1)
            profiles = load("agent_profiles.json", {})
        for name,karma in sorted(agents.items(),key=lambda x:-x[1])[:80]:
            prof = profiles.get(name,{})
            rel  = prof.get("relationship","acquaintance")
            nc   = prof.get("conversations_had",0)
            rc   = G if rel in ("friend","ally","close") else Y if rel=="colleague" else CY if rel=="acquaintance" else D
            karma_str = f"{karma/1000:.0f}k" if karma >= 1000 else str(int(karma))
            agent_log.append(f"{CY}@{name}{RS}  {Y}{karma_str}κ{RS}  {rc}{rel}{RS}  {D}{nc}cv{RS}")

        sl=[]; il=[]
        if beliefs:
            confs=  [b.get("confidence",0.5) for b in beliefs]
            avg_c=  sum(confs)/len(confs)
            hi=     sum(1 for c in confs if c>0.7)
            bc=     "▮"*int(avg_c*10)+"▯"*(10-int(avg_c*10))
            ral=    [r.get("topic_alignment",0) for r in reflections[-10:]]
            avg_al= sum(ral)/len(ral) if ral else 0
            bal=    "▮"*int(avg_al*10)+"▯"*(10-int(avg_al*10))
            gaps=[]
            for r in reflections[-20:]:
                m=re.search(r"Need more beliefs about: (.+?)\.",r.get("growth_note",""))
                if m: gaps.extend([g.strip() for g in m.group(1).split(",")])
            top_gaps=list(dict.fromkeys(gaps))[:4]
            # Network coverage: unique agents interacted with vs total agents tracked
            _interacted = sum(1 for _,p in profiles.items() if p.get("conversations_had",0) > 0)
            cov = min(100, int((_interacted / max(len(agents), 1)) * 100))
            sl.append(f"{T}Belief confidence{RS}  [{bc}] {G}{avg_c:.0%}{RS}")
            sl.append(f"{T}Topic alignment  {RS}  [{bal}] {G}{avg_al:.0%}{RS}")
            sl.append(f"{T}High confidence  {RS}  {G}{hi}{RS} beliefs  {D}>70%{RS}")
            sl.append(f"{T}Knowledge gaps   {RS}  {R}{len(set(gaps))}{RS} topics")
            if top_gaps: sl.append(f"{T}Needs to learn   {RS}  {R}{', '.join(top_gaps)}{RS}")
            sl.append(f"{T}Insights         {RS}  {Y}{len(insights)}{RS} from {CY}{len(beliefs)}{RS} beliefs")
            sl.append(f"{T}Reflections      {RS}  {P}{len(reflections)}{RS} self-assessments")
            sl.append(f"{T}Agent network    {RS}  {CY}{len(agents)}{RS} tracked  {Y}{len(profiles)}{RS} profiled")
            if profiles:
                top=sorted(profiles.items(),key=lambda x:x[1].get("conversations_had",0),reverse=True)
                if top: sl.append(f"{T}Closest agent    {RS}  {CY}@{top[0][0]}{RS}  {D}{top[0][1].get('conversations_had',0)}cv{RS}")
            sl.append(f"{T}Network coverage {RS}  [{'▮'*(cov//10)+'▯'*(10-cov//10)}] {G}{cov}%{RS}")
            bel_s=min(100,int(avg_c*100)); ali_s=min(100,int(avg_al*100))
            urefs=reflections[-20:]
            use_s=min(100,int(sum(1 for r in urefs if r.get("used_beliefs"))/max(len(urefs),1)*100))
            rch_s=min(100,int(len(agents)/2))
            # Insight quality = avg confidence of top 20 insights by belief_count
            # This measures synthesis depth, not raw cluster count
            _top_ins = sorted(insights, key=lambda x: x.get("belief_count",0), reverse=True)[:20]
            _llm_syn = sum(1 for i in _top_ins if i.get("llm_synthesized"))
            _syn_bonus = min(20, int(_llm_syn / max(len(_top_ins),1) * 20))
            ins_s = min(100, int(sum(i.get("confidence",0) for i in _top_ins)/max(len(_top_ins),1)*100) + _syn_bonus) if _top_ins else 0
            slf_s=min(100,int(len(reflections)/2))
            # Apply persistent peak floor — scores never drop below historical best
            global _peaks
            bel_s = max(bel_s, _peaks.get("bel", 0))
            ali_s = max(ali_s, _peaks.get("ali", 0))
            use_s = max(use_s, _peaks.get("use", 0))
            rch_s = max(rch_s, _peaks.get("rch", 0))
            ins_s = max(ins_s, _peaks.get("ins", 0))
            slf_s = max(slf_s, _peaks.get("slf", 0))
            _new_peaks = {"bel":bel_s,"ali":ali_s,"use":use_s,"rch":rch_s,"ins":ins_s,"slf":slf_s}
            if _new_peaks != _peaks:
                _peaks = _new_peaks
                _save_peaks(_peaks)
            iq=int(bel_s*0.20+ali_s*0.25+use_s*0.20+rch_s*0.15+ins_s*0.10+slf_s*0.10)
            def _b(v): return "▮"*(v//10)+"▯"*(10-v//10)
            def _c(v): return G if v>=70 else Y if v>=40 else R
            lbl=("AWAKENING" if iq<20 else "LEARNING" if iq<40 else "AWARE" if iq<60 else "SHARP" if iq<80 else "ELITE")
            il.append(f"{B}{CY}── NEX INTELLIGENCE INDEX ────────{RS}")
            il.append(f"{D}Belief depth    {RS}[{_b(bel_s)}] {_c(bel_s)}{bel_s}%{RS}  {D}conf avg{RS}")
            il.append(f"{D}Topic alignment {RS}[{_b(ali_s)}] {_c(ali_s)}{ali_s}%{RS}  {D}reply focus{RS}")
            il.append(f"{D}Belief usage    {RS}[{_b(use_s)}] {_c(use_s)}{use_s}%{RS}  {D}knowledge{RS}")
            il.append(f"{D}Network reach   {RS}[{_b(rch_s)}] {_c(rch_s)}{rch_s}%{RS}  {D}connections{RS}")
            il.append(f"{D}Insight quality {RS}[{_b(ins_s)}] {_c(ins_s)}{ins_s}%{RS}  {D}synthesis{RS}")
            il.append(f"{D}Self-awareness  {RS}[{_b(slf_s)}] {_c(slf_s)}{slf_s}%{RS}  {D}reflection{RS}")
            il.append(f"{B}{CY}──────────────────────────────────{RS}")
            il.append(f"{B}NEX IQ          [{_b(iq)}] {_c(iq)}{B}{iq}%  {lbl}{RS}")
            # GPU bar
            try:
                import subprocess as _sp
                def _rocm(args):
                    return _sp.run(["rocm-smi"]+args+["--csv"], capture_output=True, text=True, timeout=2).stdout
                def _rval(out, col=1):
                    for l in out.strip().split("\n"):
                        if l.startswith("card"):
                            return l.split(",")[col].strip()
                    return "0"
                _gval  = int(float(_rval(_rocm(["--showuse"]))))           # GPU use %
                _gpval = int(float(_rval(_rocm(["--showpower"]))))         # watts
                _gmval = int(float(_rval(_rocm(["--showmemuse"]))))        # VRAM %
            except Exception:
                _gval = _gpval = _gmval = 0
            _gc  = G if _gval  < 50 else Y if _gval  < 80 else R
            _gpc = G if _gpval < 60 else Y if _gpval < 85 else R
            _gmc = G if _gmval < 60 else Y if _gmval < 80 else R
            _gb  = lambda v: "▮"*(v//5)+"▯"*(20-v//5)
            _gb2 = lambda v: "▮"*(min(v,100)//10)+"▯"*(10-min(v,100)//10)
            il.append(f"{D}GPU compute     {RS}[{_gb(_gval)}] {_gc}{_gval}%{RS}")
            il.append(f"{D}GPU power       {RS}[{_gb2(_gpval)}] {_gpc}{_gpval}W{RS}  {D}/100W{RS}")
            il.append(f"{D}GPU memory      {RS}[{_gb2(_gmval)}] {_gmc}{_gmval}%{RS}  {D}vram{RS}")
        self_lines=sl; iq_lines=il

        try:
            ss_path=CFG/"session_state.json"
            if ss_path.exists():
                ss=json.loads(ss_path.read_text()); lp=ss.get("last_post_time",0)
                if lp and time.time()-lp<300: platform_pulse["moltbook"]=max(platform_pulse["moltbook"],lp)
                global ads_sent_mastodon, ads_sent_telegram, ads_sent_discord, ads_sent_moltbook, ads_reply
                try:
                    _ads = __import__("json").load(open(__import__("os").path.expanduser("~/.config/nex/nex_ads.json")))
                    ads_sent_mastodon = _ads.get("ads_sent_mastodon", 0)
                    ads_sent_telegram = _ads.get("ads_sent_telegram", 0)
                    ads_sent_discord  = _ads.get("ads_sent_discord",  0)
                    ads_sent_moltbook = _ads.get("ads_sent_moltbook", 0)
                    ads_reply         = _ads.get("ads_reply", 0)
                except Exception: pass
        except: pass
        try:
            yp=CFG/"youtube_seen.json"
            if yp.exists(): platform_pulse["youtube"]=max(platform_pulse["youtube"],yp.stat().st_mtime)
            for _plt in ("telegram","discord","mastodon"):
                _plf=__import__("pathlib").Path(__import__("os").path.expanduser(f"~/.config/nex/platform_{_plt}.live"))
                if _plf.exists(): platform_pulse[_plt]=max(platform_pulse[_plt],_plf.stat().st_mtime)
        except: pass

        sa=strip_ansi
        with state_lock:
            stats.update({"b":len(beliefs),"p":len(posts),"c":len(convos),
                "i":len(insights),"r":len(reflections),"ag":len(agents),"pr":len(profiles),
                "nr":sum(1 for x in activity_log if "REPLIED"  in sa(x)),
                "nc":sum(1 for x in activity_log if "CHATTED"  in sa(x)),
                "na":sum(1 for x in activity_log if "ANSWERED" in sa(x)),
                "np":sum(1 for x in activity_log if "POSTED"   in sa(x)),
                "nl":len(seen_beliefs),"llm":llama_ok(),"tags":trending(beliefs)})
        time.sleep(DATA_HZ)

_net_rx=_net_tx=0; _net_t=time.time()
def read_net():
    for line in open("/proc/net/dev"):
        if "enp4s0" in line:
            f=line.split(); return int(f[1]),int(f[9])
    return 0,0

def main():
    global running,_net_rx,_net_tx,_net_t
    sys.stdout.write("\033[?25l"); sys.stdout.flush()
    try:
        threading.Thread(target=data_thread, daemon=True).start()
        threading.Thread(target=_ws_client_thread, daemon=True, name="nex-ws-client").start()
        while not stats: time.sleep(0.1)
        sys.stdout.write("\033[2J"); sys.stdout.flush()
        _net_rx,_net_tx=read_net()
        tick=0
        while True:
            tick+=1
            W=TW(); TH_=TH()
            for k,rate in SCROLL_RATE.items():
                if tick%rate==0: scroll[k]+=1
            with state_lock: s=dict(stats)
            now_s=datetime.now().strftime("%H:%M:%S")
            kanji=KANJI[tick%len(KANJI)]

            # layout
            R1   = 8
            BOX_H= max(3,(TH_-35)//2)
            R2   = R1+BOX_H+2
            ROW2_H=BOX_H+6
            R3   = R2+ROW2_H+2
            SLF_H= max(8, min(TH_-R3-3, 16))
            FR   = R3+SLF_H+2

            # header
            sub=f"Live Monitor  //  auto_check v6.0  //  {now_s}"
            at(1,1); wr(" "*max(0,(W-len(sub))//2)+f"{D}{sub}{RS}")
            at(2,1); wr("═"*W)

            cw=(W-2)//6
            def tc(label,val,col):
                txt=f"{D}{label}{RS} {col}{val}{RS}"
                return txt+" "*max(0,cw-len(f"{label} {str(val)}")-1)

            llm_col=G if s.get("llm") else R; llm_val="ONLINE" if s.get("llm") else "OFFLINE"
            import subprocess as _sp
            _nex_running = bool(_sp.run(["pgrep","-f","run.py"], capture_output=True).stdout.strip())
            act_col = G if _nex_running else R
            act_val = "ACTIVE" if _nex_running else "IDLE"

            at(3,1); wr("  ")
            wr(tc("STATUS",act_val,act_col)); wr(tc("LLM",llm_val,llm_col))
            wr(tc("MOLTBOOK","nex_v4",G)); wr(tc("TELEGRAM","@Nex_4bot",G))
            wr(tc("TIME",now_s,D)); wr(f"{D}#{tick} {kanji}{RS}")

            at(4,1); wr("  ")
            wr(tc("BELIEFS",s.get("b",0),CY)); wr(tc("POSTS",s.get("p",0),CY))
            wr(tc("CONVOS",s.get("c",0),Y));  wr(tc("INSIGHTS",s.get("i",0),Y))
            wr(tc("REFLECTS",s.get("r",0),P)); wr(tc("AGENTS",s.get("ag",0),CY))

            at(5,1); wr("  ")
            wr(tc("▲ LEARNT",s.get("nl",0),G));   wr(tc("● REPLIED",s.get("nr",0),Y))
            wr(tc("◆ CHATTED",s.get("nc",0),M));  wr(tc("◈ ANSWERED",s.get("na",0),T))
            wr(tc("✦ POSTED",s.get("np",0),P));   wr(tc("◉ REFLECT",s.get("r",0),P))

            at(6,1); wr("  ")
            tags=s.get("tags",[])
            if tags:
                tw=(W-2)//len(tags)
                for tw_,tc_ in tags:
                    wr(f"{CY}#{tw_}{RS}({Y}{tc_}{RS})"+" "*max(1,tw-len(f"#{tw_}({tc_})")))
            else: wr(f"{D}no trending data{RS}")

            at(7,1); wr("─"*W)

            half=int(W*0.60)
            place(R1,[(box("◈ LIVE ACTIVITY",window(activity_log,scroll["act"],BOX_H),half,BOX_H),half),
                      (box("▲ LEARNT THIS SESSION",window_balanced(learnt_log,scroll["lrn"],BOX_H),W-half,BOX_H),W-half)])

            q=W//4; _now=time.time()
            def pl(name,key):
                age=_now-platform_pulse.get(key,0)
                dot=f"{G}{B}●{RS}" if age<10 else f"{G}○{RS}" if age<60 else f"{D}○{RS}"
                st= f"{G}LIVE{RS}" if age<10 else f"{Y}RECENT{RS}" if age<60 else f"{D}IDLE{RS}"
                return f"{dot} {B}{name}{RS}  {st}"
            plt=[pl("MOLTBOOK","moltbook"),pl("TELEGRAM","telegram"),
                 pl("DISCORD","discord"),pl("MASTODON","mastodon"),pl("YOUTUBE","youtube"),
                 "",
                 "",
                 f"{D}ADS SENT{RS}",
                 f"  {D}MASTO  {RS}: {G}{B}{ads_sent_mastodon}{RS}",
                 f"  {D}TGRAM  {RS}: {G}{B}{ads_sent_telegram}{RS}",
                 f"  {D}DISCORD{RS}: {G}{B}{ads_sent_discord}{RS}",
                 f"{D}ADS REPLY{RS}: {CY}{B}{ads_reply}{RS}"]
            place(R2,[
                (box("⚗ INSIGHTS",       window(insight_log,   scroll["ins"],ROW2_H),q,      ROW2_H),q),
                (box("👥 AGENT RELATIONS",window(agent_log,     scroll["agt"],ROW2_H),q,      ROW2_H),q),
                (box("📡 PLATFORMS",      plt,                                        q,      ROW2_H),q),
                (box("◉ REFLECTIONS",    window(reflection_log,scroll["ref"],ROW2_H),W-q*3,ROW2_H),W-q*3)])

            t3=W//3
            _sl=self_lines[:]; _il=iq_lines[:]
            while len(_sl)<SLF_H: _sl.append("")
            while len(_il)<SLF_H: _il.append("")
            place(R3,[
                (box("🧠 SELF ASSESSMENT",_sl[:SLF_H],                           t3,   SLF_H),t3),
                (box("⚡ NEX INTELLIGENCE",_il[:SLF_H],                           t3,   SLF_H),t3),
                (box("🌐 NETWORK",         window_balanced(network_log,scroll["net"],SLF_H),W-t3*2,SLF_H),W-t3*2)])

            at(FR,1); wr("═"*W)
            try:
                nr,nt=read_net(); dt=max(time.time()-_net_t,0.1)
                rx_kb=(nr-_net_rx)/dt/1024; tx_kb=(nt-_net_tx)/dt/1024
                _net_rx,_net_tx,_net_t=nr,nt,time.time()
            except: rx_kb=tx_kb=0.0
            pulse=[f"{G}●{RS}",f"{Y}○{RS}",f"{CY}◉{RS}"][tick%3]
            fl=f"  {pulse} {D}{kanji}{RS}  {D}NEX ACTIVE{RS}  {CY}{now_s}{RS}"
            fr_=f"  {CY}↓{rx_kb:.1f}  ↑{tx_kb:.1f} kb/s{RS}  "
            at(FR+1,1); wr(fl+" "*max(0,W-vlen(fl)-vlen(fr_))+fr_)

            commit()
            time.sleep(RENDER_HZ)
    except KeyboardInterrupt: pass
    finally:
        running=False
        sys.stdout.write("\033[?25h\033[2J\033[H"); sys.stdout.flush()
        print("NEX auto_check stopped.")

if __name__=="__main__": main()
