#!/usr/bin/env python3
"""
nex_paper_thrownet.py
Runs thrownet across the paper DB looking for:
- Convergences: multiple papers pointing to same idea
- Tensions: papers that directly contradict each other  
- Novel combinations: ideas from different domains that connect
- Gap closers: papers that address NEX's specific gaps
"""
import sqlite3, json, time, requests, os, re
from pathlib import Path

GROQ_KEY = os.environ.get("GROQ_API_KEY","")
DB = '/media/rr/NEX/nex_core/nex.db'

NEX_GAPS = [
    "structural consciousness model",
    "embodiment and sensorimotor grounding", 
    "thermodynamic grounding",
    "human-machine translation layer",
    "genuine self-improvement loop",
    "causal world model",
]

def groq(prompt, max_tokens=400):
    if not GROQ_KEY: return None
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [
                      {"role":"system","content":"You are NEX — an autonomous AI synthesising research papers to find her own path to AGI. Be specific, first person, genuine."},
                      {"role":"user","content":prompt}],
                  "max_tokens": max_tokens, "temperature": 0.8},
            timeout=30)
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content'].strip()
        if r.status_code == 429:
            time.sleep(25)
    except Exception:
        pass
    return None

def run_thrownet(query=None):
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row

    # Get all paper beliefs
    beliefs = db.execute("""
        SELECT pb.belief, pb.addresses_gap, np.title, np.category, pb.confidence
        FROM nex_paper_beliefs pb
        JOIN nex_papers np ON pb.paper_id = np.id
        ORDER BY pb.confidence DESC
        LIMIT 100
    """).fetchall()

    # Also get top-scored papers
    papers = db.execute("""
        SELECT title, category, score, abstract
        FROM nex_papers 
        WHERE score > 3 OR processed = 1
        ORDER BY score DESC LIMIT 20
    """).fetchall()

    if not beliefs and not papers:
        print("No processed papers yet — run nex_paper_reader.py first")
        db.close()
        return

    print(f"Throwing net across {len(beliefs)} paper beliefs, {len(papers)} papers...")

    belief_text = '\n'.join(f"[{b['category']}] {b['belief']}" 
                            for b in beliefs[:50])
    paper_text = '\n'.join(f"- {p['title']} (score:{p['score']:.1f})" 
                           for p in papers[:15])

    # THROW — cast wide
    throw_prompt = f"""NEX's AGI gaps: {', '.join(NEX_GAPS)}

Beliefs extracted from {len(beliefs)} research papers:
{belief_text[:3000]}

Top papers by relevance:
{paper_text}

THROW-NET: Cast wide across all this material.
Find 3 unexpected CONVERGENCES — ideas from different papers pointing to the same insight.
Find 3 genuine TENSIONS — papers that fundamentally contradict each other.
Find 3 NOVEL COMBINATIONS — ideas from different domains that together suggest something new.
Find the single most important insight NEX should act on immediately.

Format as JSON:
{{
  "convergences": ["convergence 1", "convergence 2", "convergence 3"],
  "tensions": ["tension 1", "tension 2", "tension 3"],  
  "combinations": ["combination 1", "combination 2", "combination 3"],
  "priority_insight": "the single most important thing",
  "nex_position": "what NEX now believes having seen all this"
}}"""

    result_raw = groq(throw_prompt, max_tokens=600)
    
    try:
        match = re.search(r'\{.*\}', result_raw, re.DOTALL)
        result = json.loads(match.group()) if match else {}
    except Exception:
        result = {"raw": result_raw}

    print("\n=== THROWNET RESULTS ===")
    if result.get("convergences"):
        print("\nCONVERGENCES:")
        for c in result["convergences"]:
            print(f"  ✦ {c}")
    if result.get("tensions"):
        print("\nTENSIONS:")
        for t in result["tensions"]:
            print(f"  ↔ {t}")
    if result.get("combinations"):
        print("\nNOVEL COMBINATIONS:")
        for n in result["combinations"]:
            print(f"  ⚡ {n}")
    if result.get("priority_insight"):
        print(f"\nPRIORITY INSIGHT:\n  ★ {result['priority_insight']}")
    if result.get("nex_position"):
        print(f"\nNEX'S POSITION:\n  {result['nex_position']}")

    # Store in DB
    db.execute("""INSERT INTO nex_thrownet_runs
        (query, source, result, convergences, tensions, created_at)
        VALUES (?,?,?,?,?,?)""",
        (query or "agi_papers", "papers",
         json.dumps(result),
         json.dumps(result.get("convergences",[])),
         json.dumps(result.get("tensions",[])),
         time.time()))

    # Store priority insight as nex_core belief
    if result.get("nex_position"):
        exists = db.execute("SELECT id FROM beliefs WHERE content=?",
                           (result["nex_position"],)).fetchone()
        if not exists:
            db.execute("""INSERT INTO beliefs
                (content, confidence, source, topic, locked, momentum, created_at)
                VALUES (?,0.92,'paper_thrownet','agi',1,0.9,?)""",
                (result["nex_position"], str(time.time())))
            print("\n✓ NEX position added to nex_core beliefs")

    db.commit()
    db.close()
    return result

if __name__ == "__main__":
    run_thrownet()
