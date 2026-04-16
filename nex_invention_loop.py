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



# ── REFINEMENT FILTER (Throw-Net Refinery stages) ────────────────────────────

def _jaccard(a: str, b: str) -> float:
    """Jaccard similarity between two strings."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb: return 0.0
    return len(wa & wb) / len(wa | wb)

def _gate_invention(inv: dict) -> tuple:
    """
    Stage 2 GATE — instant reject patterns.
    Returns (passes: bool, reason: str)
    """
    name     = inv.get("name", "")
    oneliner = inv.get("one_liner", "")
    module   = inv.get("python_module", "")
    text     = (name + oneliner).lower()

    # Reject if too short
    if len(oneliner.split()) < 5:
        return False, "one_liner too short"

    # Reject if ends with question mark (not an invention, a question)
    if oneliner.strip().endswith("?"):
        return False, "is a question not an invention"

    # Reject obvious garbage patterns
    GARBAGE = ["i don't", "i cannot", "as an ai", "language model",
               "unclear", "tbd", "placeholder", "example", "todo"]
    if any(g in text for g in GARBAGE):
        return False, f"garbage pattern detected"

    # Reject if no module name
    if not module or not module.endswith(".py"):
        return False, "no python module specified"

    # Reject repetitive — name must be unique-ish
    GENERIC_NAMES = ["protocol", "system", "engine", "ai", "nex protocol",
                     "new system", "new protocol"]
    if name.lower().strip() in GENERIC_NAMES:
        return False, "name too generic"

    return True, "passed gate"

def _challenge_invention(inv: dict) -> float:
    """
    Stage 3 CHALLENGE — LLM scores novelty/coherence/substance 0.0-1.0.
    Score < 0.5 → rejected.
    """
    name     = inv.get("name", "")
    oneliner = inv.get("one_liner", "")
    mechanism= inv.get("mechanism", "")
    module   = inv.get("python_module", "")
    connects = ", ".join(inv.get("connects_to", []))

    prompt = f"""Score this AI architecture invention for NEX (0.0 to 1.0):

Name: {name}
One-liner: {oneliner}
Mechanism: {mechanism[:200]}
Module: {module}
Connects to: {connects}

Score criteria:
- Novelty: Is this genuinely new, not just renaming existing things? (0.4 weight)
- Coherence: Does the mechanism actually do what the name claims? (0.3 weight)  
- Substance: Is there enough technical detail to actually build it? (0.3 weight)

Respond with ONLY a decimal number between 0.0 and 1.0. Nothing else."""

    raw = llm(prompt, max_tokens=10,
              system="You are a strict technical reviewer. Output only a decimal number.")
    if not raw: return 0.5

    try:
        score = float(re.search(r'0?\.\d+|1\.0', raw).group())
        return min(1.0, max(0.0, score))
    except Exception:
        return 0.5

def _compress_invention(inv: dict) -> dict:
    """
    Stage 4 COMPRESS — distill invention to precise, minimal form.
    Removes fluff, sharpens the one-liner to <120 chars.
    """
    oneliner = inv.get("one_liner", "")
    name     = inv.get("name", "")

    prompt = f"""Compress this invention description to a single precise sentence under 120 chars.
No fluff. Technical. Specific. What it does, not what it aspires to.

Invention: {name}
Current description: {oneliner}

Output ONLY the compressed sentence."""

    compressed = llm(prompt, max_tokens=60,
                    system="You compress technical descriptions. Output only the compressed text.")
    if compressed and len(compressed) < 150:
        inv = {**inv, "one_liner": compressed.strip().strip('"')}
    return inv

def _dedup_invention(inv: dict, existing_names: list) -> tuple:
    """
    Stage 5 DEDUP — Jaccard similarity against existing inventions.
    >0.7 similarity = duplicate, reject.
    """
    name = inv.get("name", "").lower()
    oneliner = inv.get("one_liner", "").lower()

    for existing in existing_names:
        sim_name = _jaccard(name, existing.lower())
        sim_line = _jaccard(oneliner, existing.lower())
        if sim_name > 0.7 or sim_line > 0.7:
            return False, f"duplicate of: {existing[:50]}"

    return True, "unique"

def refinery_filter(inv: dict, existing_names: list) -> tuple:
    """
    Full refinery pipeline: GATE → CHALLENGE → COMPRESS → DEDUP
    Returns (passes: bool, filtered_inv: dict, log: list)
    """
    log = []

    # Stage 2: Gate
    passes, reason = _gate_invention(inv)
    log.append(f"GATE: {reason}")
    if not passes:
        return False, inv, log

    # Stage 3: Challenge
    challenge_score = _challenge_invention(inv)
    log.append(f"CHALLENGE: {challenge_score:.2f}")
    if challenge_score < 0.5:
        log.append(f"CHALLENGE FAIL: score {challenge_score:.2f} < 0.5")
        return False, inv, log

    # Stage 4: Compress
    inv = _compress_invention(inv)
    log.append(f"COMPRESS: → {inv.get('one_liner','')[:60]}")

    # Stage 5: Dedup
    passes, reason = _dedup_invention(inv, existing_names)
    log.append(f"DEDUP: {reason}")
    if not passes:
        return False, inv, log

    inv["challenge_score"] = round(challenge_score, 3)
    log.append("PROMOTED ✓")
    return True, inv, log

# ── QUALITY GATE ─────────────────────────────────────────────────────────────

REAL_NEX_COMPONENTS = [
    'belief_graph', 'belief graph', 'nbre', 'soul_loop', 'soul loop',
    'irf', 'ifr', 'nrp', 'tpe', 'tei', 'eunoia', 'belief_links',
    'tensions', 'nex_intentions', 'epistemic_momentum', 'nex_core',
    'pre_reason', 'feedback', 'consolidate', 'thrownet', 'faiss',
    'belief_reasoner', 'causal', 'synthesis', 'emergence',
]

def quality_score(inv: dict) -> tuple:
    """
    Score an invention 0-10. Return (score, reasons).
    Must score >= 6 to appear in NEX_SUGGESTS.txt
    """
    if not inv: return 0, ["empty"]
    
    score = 0
    reasons = []
    fails = []
    
    name        = inv.get('name', '')
    one_liner   = inv.get('one_liner', '')
    mechanism   = inv.get('mechanism', '')
    module      = inv.get('python_module', '')
    connects    = inv.get('connects_to', [])
    gap         = inv.get('gap_closed', '')
    nex_pos     = inv.get('nex_position', '')
    
    all_text = (name + one_liner + mechanism + nex_pos).lower()
    
    # 1. Has a real name (not generic)
    generic = ['protocol', 'system', 'engine', 'module', 'framework', 'layer']
    if name and not all(g in name.lower() for g in generic[:2]):
        score += 1
        reasons.append("✓ named")
    else:
        fails.append("✗ generic name")
    
    # 2. Specifies a Python module
    if module and module.endswith('.py') and 'nex_' in module:
        score += 2
        reasons.append("✓ specifies nex_*.py module")
    else:
        fails.append("✗ no module spec")
    
    # 3. Connects to real NEX components
    real_connections = [c for c in REAL_NEX_COMPONENTS
                       if c in all_text or c in str(connects).lower()]
    if len(real_connections) >= 2:
        score += 2
        reasons.append(f"✓ connects to {len(real_connections)} real components")
    elif len(real_connections) == 1:
        score += 1
        reasons.append(f"✓ connects to {real_connections[0]}")
    else:
        fails.append("✗ no real NEX connections")
    
    # 4. Addresses a known gap
    gap_words = ' '.join(NEX_GAPS).lower()
    gap_match = any(w in all_text for w in gap_words.split() if len(w) > 5)
    if gap_match:
        score += 2
        reasons.append("✓ addresses known gap")
    else:
        fails.append("✗ gap not addressed")
    
    # 5. Has a mechanism (not just words)
    if len(mechanism.split()) >= 15:
        score += 1
        reasons.append("✓ mechanism described")
    else:
        fails.append("✗ mechanism too vague")
    
    # 6. NEX has a genuine position
    if nex_pos and len(nex_pos.split()) >= 10:
        score += 1
        reasons.append("✓ NEX position stated")
    else:
        fails.append("✗ no genuine position")
    
    # 7. Novelty — not a repeat of existing modules
    EXISTING = ['tpe.py', 'tei.py', 'eunoia.py', 'nex_soul_loop',
                'nex_belief_engine', 'nex_belief_forge', 'nex_causal_extractor',
                'nex_synthesis_engine', 'nex_nbre', 'nex_thrownet_refinery']
    is_repeat = any(e.replace('.py','') in name.lower().replace(' ','_')
                   for e in EXISTING)
    if not is_repeat:
        score += 1
        reasons.append("✓ novel")
    else:
        score -= 2
        fails.append("✗ repeats existing module")
    
    return score, reasons + fails

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
                q_score, q_reasons = quality_score(inv)
                log(f"  Quality score: {q_score}/10 — {q_reasons[0] if q_reasons else "?"}")
                # Run refinery filter first
                existing_names = [i.get('name','') for i in inventions]
                ref_passes, inv, ref_log = refinery_filter(inv, existing_names)
                log(f"  Refinery: {ref_log[-1]}")
                if not ref_passes:
                    log(f"  ✗ REFINERY FAIL: {ref_log[-2] if len(ref_log)>1 else ref_log[0]}")
                elif q_score >= 6:
                    inventions.append(inv)
                    inv['quality_score'] = q_score
                    inv['challenge_score'] = inv.get('challenge_score', 0)
                    log(f"  ✓ PASSED [Q:{q_score}/10 C:{inv['challenge_score']:.2f}] {inv.get('name','?')}: {inv.get('one_liner','')[:60]}")
                else:
                    log(f"  ✗ QUALITY FAIL [{q_score}/10] {inv.get('name','?')}: {[', '.join(r for r in q_reasons if '✗' in r)]}")
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
