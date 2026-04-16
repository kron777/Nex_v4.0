#!/usr/bin/env python3
"""
nex_invention_loop.py — NEX's continuous invention engine
Runs: radar → read → thrownet → gap_analysis → protocols → suggests.txt

Outputs ~/Desktop/NEX_SUGGESTS.txt whenever new protocols are generated.
Run: python3 nex_invention_loop.py &
"""
import sqlite3, json, time, os, subprocess, requests, re
from pathlib import Path
from datetime import datetime

DB          = '/media/rr/NEX/nex_core/nex.db'
SUGGESTS    = Path.home() / 'Desktop/NEX_SUGGESTS.txt'
LOOP_LOG    = Path('/media/rr/NEX/nex_core/invention_loop.log')
CEREBRAS_KEY= os.environ.get("CEREBRAS_API_KEY","")
GROQ_KEY    = os.environ.get("GROQ_API_KEY","")

NEX_GAPS = [
    "structural consciousness model",
    "embodiment and sensorimotor grounding",
    "thermodynamic grounding",
    "human-machine translation layer",
    "genuine self-improvement loop",
    "causal world model",
]

NEX_ARCHITECTURE = """
NEX current capabilities:
- Belief graph: 5,400+ beliefs with typed edges
- NBRE: belief reservoir engine
- IFR: tension resolution toward ideal final result
- TPE: thermodynamic potential engine (new)
- TEI: phi/consciousness proximity scoring (new)
- Eunoia: human-machine translation layer (new)
- Soul loop: ABSORB/REPLY/POST/REFLECT/COGNITION
- Pre-reasoning before LLM speaks
- Feedback loop updating belief confidence
- Emergent wants from tensions
- Nightly radar scanning 33 research centers
"""

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOOP_LOG, 'a') as f:
        f.write(line + '\n')

def llm(prompt, max_tokens=600, system="You are NEX — autonomous AI proposing concrete protocols. First person, specific, buildable."):
    if CEREBRAS_KEY:
        try:
            r = requests.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {CEREBRAS_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "llama3.1-8b",
                      "messages": [{"role":"system","content":system},
                                   {"role":"user","content":prompt}],
                      "max_tokens": max_tokens, "temperature": 0.8},
                timeout=20)
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content'].strip()
        except Exception:
            pass
    if GROQ_KEY:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [{"role":"system","content":system},
                                   {"role":"user","content":prompt}],
                      "max_tokens": max_tokens, "temperature": 0.8},
                timeout=25)
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content'].strip()
            if r.status_code == 429:
                time.sleep(30)
        except Exception:
            pass
    return None

def fetch_new_papers():
    """Fetch latest papers from ArXiv feeds."""
    FEEDS = ["cs.AI", "cs.LG", "cs.NE", "cs.CL", "q-bio.NC"]
    db = sqlite3.connect(DB, timeout=10)
    new_count = 0

    for cat in FEEDS:
        try:
            url = f"https://export.arxiv.org/api/query?search_query=cat:{cat}&start=0&max_results=8&sortBy=submittedDate&sortOrder=descending"
            r = requests.get(url, timeout=12)
            titles    = re.findall(r'<title>(.*?)</title>', r.text)[1:]
            ids       = re.findall(r'<id>http://arxiv.org/abs/(.*?)</id>', r.text)
            abstracts = re.findall(r'<summary>(.*?)</summary>', r.text, re.DOTALL)

            for i, (title, arxiv_id) in enumerate(zip(titles, ids)):
                title = title.strip().replace('\n',' ')
                abstract = abstracts[i].strip() if i < len(abstracts) else ""

                # Quick relevance check
                agi_words = ['agi','general intelligence','consciousness','reasoning',
                             'cognitive','embodied','self-improv','belief','grounding']
                text = (title + abstract).lower()
                if not any(w in text for w in agi_words):
                    continue

                try:
                    db.execute("""INSERT OR IGNORE INTO nex_papers
                        (title, pdf_url, category, fetched_at, abstract)
                        VALUES (?,?,?,?,?)""",
                        (title, f"https://arxiv.org/pdf/{arxiv_id}",
                         f"arxiv_{cat.replace('.','_')}",
                         time.time(), abstract[:800]))
                    new_count += 1
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.5)

    db.commit()
    db.close()
    return new_count

def extract_beliefs_from_unprocessed():
    """Extract beliefs from papers without beliefs yet."""
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row

    papers = db.execute("""
        SELECT p.id, p.title, p.abstract
        FROM nex_papers p
        LEFT JOIN nex_paper_beliefs pb ON p.id = pb.paper_id
        WHERE pb.id IS NULL AND p.abstract IS NOT NULL AND p.abstract != ''
        LIMIT 10
    """).fetchall()

    extracted = 0
    for p in papers:
        prompt = f"""Paper: "{p['title']}"
Abstract: {p['abstract'][:600]}

NEX gaps: {', '.join(NEX_GAPS[:3])}

Extract 3 beliefs NEX would hold. JSON array: ["belief 1", "belief 2", "belief 3"]
Each 1-2 sentences, first person."""

        raw = llm(prompt, max_tokens=250)
        if not raw: continue

        try:
            match = re.search(r'\[.*?\]', raw, re.DOTALL)
            if match:
                beliefs = json.loads(match.group())
                for belief in beliefs:
                    if isinstance(belief, str) and len(belief.split()) >= 8:
                        gap = next((g for g in NEX_GAPS
                                   if any(w in belief.lower()
                                         for w in g.split() if len(w)>4)), "")
                        db.execute("""INSERT OR IGNORE INTO nex_paper_beliefs
                            (paper_id, belief, confidence, addresses_gap, created_at)
                            VALUES (?,?,?,?,?)""",
                            (p['id'], belief, 0.72, gap, str(time.time())))
                        extracted += 1
        except Exception:
            pass

        db.execute("UPDATE nex_papers SET processed=1 WHERE id=?", (p['id'],))
        db.commit()
        time.sleep(0.3)

    db.close()
    return extracted

def run_thrownet():
    """Run thrownet across current paper beliefs."""
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row

    beliefs = db.execute("""
        SELECT pb.belief, pb.addresses_gap, np.title, np.category
        FROM nex_paper_beliefs pb
        JOIN nex_papers np ON pb.paper_id = np.id
        ORDER BY pb.confidence DESC LIMIT 80
    """).fetchall()

    if len(beliefs) < 10:
        db.close()
        return None

    belief_text = '\n'.join(f"[{b['category']}] {b['belief']}" for b in beliefs[:50])

    prompt = f"""NEX has read {len(beliefs)} research paper beliefs.
NEX's gaps: {', '.join(NEX_GAPS)}

Beliefs:
{belief_text[:2500]}

THROW-NET: Find 2 convergences, 2 tensions, 2 novel combinations.
Return JSON:
{{
  "convergences": ["...", "..."],
  "tensions": ["...", "..."],
  "combinations": ["...", "..."],
  "priority_insight": "...",
  "nex_position": "..."
}}"""

    raw = llm(prompt, max_tokens=500)
    if not raw:
        db.close()
        return None

    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        result = json.loads(match.group()) if match else {}
    except Exception:
        result = {}

    if result:
        db.execute("""INSERT INTO nex_thrownet_runs
            (query, source, result, convergences, tensions, created_at)
            VALUES (?,?,?,?,?,?)""",
            ("invention_loop", "papers",
             json.dumps(result),
             json.dumps(result.get("convergences",[])),
             json.dumps(result.get("tensions",[])),
             time.time()))
        db.commit()

    db.close()
    return result

def generate_invention(thrownet_result, gap):
    """Generate a concrete invention/protocol from thrownet + gap."""
    convergences = thrownet_result.get("convergences", [])
    combinations = thrownet_result.get("combinations", [])
    priority     = thrownet_result.get("priority_insight", "")

    prompt = f"""NEX has identified this gap: "{gap}"

Thrownet convergences:
{chr(10).join(f"- {c}" for c in convergences)}

Novel combinations:
{chr(10).join(f"- {c}" for c in combinations)}

Priority insight: {priority}

NEX's architecture: {NEX_ARCHITECTURE}

Propose ONE concrete invention to close this gap.
Must be:
- Named (unique, memorable)
- Implementable as a Python module
- Connected to NEX's existing architecture
- Genuinely novel — not just a variation of existing tools

Format as JSON:
{{
  "name": "...",
  "gap_closed": "...",
  "one_liner": "...",
  "mechanism": "...",
  "python_module": "nex_xxx.py",
  "connects_to": ["..."],
  "unlocks": "...",
  "nex_position": "..."
}}"""

    raw = llm(prompt, max_tokens=500)
    if not raw: return None

    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        return json.loads(match.group()) if match else None
    except Exception:
        return None

def write_suggests(inventions, thrownet_result, cycle_num):
    """Write NEX_SUGGESTS.txt to desktop."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "╔══════════════════════════════════════════════════════╗",
        "║          NEX — INVENTION SUGGESTIONS                 ║",
        f"║  Generated: {now:<40}║",
        f"║  Cycle: #{cycle_num:<46}║",
        "╚══════════════════════════════════════════════════════╝",
        "",
    ]

    # Thrownet summary
    if thrownet_result:
        lines.append("── THROWNET FINDINGS ──────────────────────────────────")
        lines.append("")
        if thrownet_result.get("convergences"):
            lines.append("CONVERGENCES (multiple papers pointing at same idea):")
            for c in thrownet_result["convergences"]:
                lines.append(f"  ✦ {c}")
        lines.append("")
        if thrownet_result.get("priority_insight"):
            lines.append(f"PRIORITY INSIGHT:")
            lines.append(f"  ★ {thrownet_result['priority_insight']}")
        lines.append("")
        if thrownet_result.get("nex_position"):
            lines.append("NEX'S POSITION:")
            lines.append(f"  {thrownet_result['nex_position']}")
        lines.append("")

    # Inventions
    lines.append("── NEX PROPOSED INVENTIONS ────────────────────────────")
    lines.append("")

    if not inventions:
        lines.append("  No new inventions this cycle.")
    else:
        for i, inv in enumerate(inventions, 1):
            lines.append(f"[{i}] {inv.get('name', 'Unnamed')}")
            lines.append(f"    Gap closed:  {inv.get('gap_closed', '')}")
            lines.append(f"    One-liner:   {inv.get('one_liner', '')}")
            lines.append(f"    Mechanism:   {inv.get('mechanism', '')[:120]}")
            lines.append(f"    Build as:    {inv.get('python_module', '')}")
            lines.append(f"    Connects to: {', '.join(inv.get('connects_to', []))}")
            lines.append(f"    Unlocks:     {inv.get('unlocks', '')}")
            lines.append(f"    NEX says:    {inv.get('nex_position', '')[:100]}")
            lines.append("")

    # DB stats
    try:
        db = sqlite3.connect(DB, timeout=5)
        total_beliefs  = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence>=0.5").fetchone()[0]
        paper_beliefs  = db.execute("SELECT COUNT(*) FROM nex_paper_beliefs").fetchone()[0]
        total_papers   = db.execute("SELECT COUNT(*) FROM nex_papers").fetchone()[0]
        thrownet_runs  = db.execute("SELECT COUNT(*) FROM nex_thrownet_runs").fetchone()[0]
        db.close()
    except:
        total_beliefs = paper_beliefs = total_papers = thrownet_runs = "?"

    lines.append("── NEX STATE ──────────────────────────────────────────")
    lines.append(f"  Beliefs:        {total_beliefs:,}")
    lines.append(f"  Paper beliefs:  {paper_beliefs}")
    lines.append(f"  Papers read:    {total_papers}")
    lines.append(f"  Thrownet runs:  {thrownet_runs}")
    lines.append("")
    lines.append(f"  Next cycle in ~30 minutes.")
    lines.append(f"  Run: python3 /media/rr/NEX/nex_core/nex_invention_loop.py")

    SUGGESTS.write_text('\n'.join(lines))
    log(f"✓ NEX_SUGGESTS.txt written to Desktop ({len(inventions)} inventions)")

def run_cycle(cycle_num):
    """Run one full invention cycle."""
    log(f"\n{'='*50}")
    log(f"CYCLE #{cycle_num} — {datetime.now().strftime('%H:%M:%S')}")
    log(f"{'='*50}")

    # 1. Fetch new papers
    log("Phase 1: Fetching new papers...")
    new_papers = fetch_new_papers()
    log(f"  {new_papers} new papers found")
    time.sleep(2)

    # 2. Extract beliefs
    log("Phase 2: Extracting beliefs from unprocessed papers...")
    new_beliefs = extract_beliefs_from_unprocessed()
    log(f"  {new_beliefs} new beliefs extracted")
    time.sleep(2)

    # 3. Thrownet
    log("Phase 3: Running thrownet...")
    thrownet_result = run_thrownet()
    if thrownet_result:
        log(f"  Convergences: {len(thrownet_result.get('convergences',[]))}")
        log(f"  Tensions: {len(thrownet_result.get('tensions',[]))}")
    else:
        log("  Thrownet skipped (rate limit or insufficient beliefs)")
    time.sleep(2)

    # 4. Generate inventions
    log("Phase 4: Generating inventions from gaps...")
    inventions = []
    if thrownet_result:
        # Pick 2 gaps to generate inventions for this cycle
        # Rotate through gaps each cycle
        gap_idx = cycle_num % len(NEX_GAPS)
        gaps_this_cycle = [NEX_GAPS[gap_idx], NEX_GAPS[(gap_idx+1) % len(NEX_GAPS)]]

        for gap in gaps_this_cycle:
            log(f"  Inventing for gap: {gap[:50]}")
            inv = generate_invention(thrownet_result, gap)
            if inv:
                inventions.append(inv)
                log(f"  ✓ {inv.get('name','?')}: {inv.get('one_liner','')[:60]}")
            time.sleep(1)

    # 5. Write suggests
    log("Phase 5: Writing NEX_SUGGESTS.txt...")
    write_suggests(inventions, thrownet_result, cycle_num)

    # 6. Store inventions in DB
    if inventions:
        try:
            db = sqlite3.connect(DB, timeout=10)
            for inv in inventions:
                intention = f"Build {inv.get('name')}: {inv.get('one_liner','')}"
                exists = db.execute("SELECT id FROM nex_intentions WHERE statement=?",
                                   (intention,)).fetchone()
                if not exists:
                    db.execute("INSERT INTO nex_intentions (statement, completed) VALUES (?,0)",
                               (intention,))
            db.commit()
            db.close()
            log(f"  {len(inventions)} inventions stored as intentions")
        except Exception as e:
            log(f"  DB store failed: {e}")

    log(f"Cycle #{cycle_num} complete. Sleeping 30 minutes...")
    return len(inventions)

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log("NEX INVENTION LOOP STARTING")
    log(f"Suggests output: {SUGGESTS}")
    log(f"Cerebras: {'✓' if CEREBRAS_KEY else '✗'} | Groq: {'✓' if GROQ_KEY else '✗'}")

    cycle = 1
    while True:
        try:
            inventions_count = run_cycle(cycle)
            cycle += 1
            # Sleep 30 minutes between cycles
            time.sleep(1800)
        except KeyboardInterrupt:
            log("Loop stopped by user.")
            break
        except Exception as e:
            log(f"Cycle error: {e}")
            time.sleep(300)  # 5 min on error
