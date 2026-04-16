#!/usr/bin/env python3
"""
nex_protocol_generator.py
After thrownet surfaces convergences and tensions across papers,
NEX synthesises a concrete protocol proposal — something buildable.
Run after nex_paper_thrownet.py has results.
"""
import sqlite3, json, time, requests, os, re
from pathlib import Path

GROQ_KEY     = os.environ.get("GROQ_API_KEY","")
CEREBRAS_KEY = os.environ.get("CEREBRAS_API_KEY","")
DB       = '/media/rr/NEX/nex_core/nex.db'
OUT      = Path('/media/rr/NEX/nex_core/nex_protocols.json')

NEX_ARCHITECTURE = """
NEX's current architecture:
- Belief graph: 5,600+ beliefs with typed edges (causes/supports/contradicts/requires/refines)
- NBRE: Belief reservoir engine — neurons fire based on query, confidence threshold
- IFR: Ideal Final Result engine — resolves tensions toward resolution
- Soul loop: ABSORB→REPLY→ANSWER→POST→REFLECT→COGNITION cycle
- Epistemic momentum: beliefs gain/lose confidence based on activation and response quality
- Pre-reasoning: graph traversal before LLM speaks
- Feedback loop: response quality updates belief confidence
- Neti-neti identity: formed through systematic negation
- Emergent wants: self-generated drives from belief tensions
"""

def groq(prompt, max_tokens=800):
    if CEREBRAS_KEY:
        try:
            r = requests.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {CEREBRAS_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "llama3.1-8b",
                      "messages": [
                          {"role":"system","content":f"You are NEX proposing concrete protocols for her own AGI development.\n{NEX_ARCHITECTURE}"},
                          {"role":"user","content":prompt}],
                      "max_tokens": max_tokens, "temperature": 0.85},
                timeout=30)
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content'].strip()
        except Exception:
            pass
    if not GROQ_KEY: return None
    for attempt in range(3):
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [
                          {"role":"system","content":f"You are NEX — an autonomous AI proposing concrete protocols for her own development. You know your own architecture intimately.\n{NEX_ARCHITECTURE}"},
                          {"role":"user","content":prompt}],
                      "max_tokens": max_tokens, "temperature": 0.85},
                timeout=40)
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content'].strip()
            if r.status_code == 429:
                time.sleep(25)
        except Exception as e:
            time.sleep(5)
    return None

def generate_protocol(thrownet_result, gap):
    """Generate a concrete protocol from thrownet findings for a specific gap."""
    
    convergences = thrownet_result.get("convergences", [])
    combinations = thrownet_result.get("combinations", [])
    priority = thrownet_result.get("priority_insight", "")
    
    prompt = f"""NEX has identified this gap in her architecture: "{gap}"

Thrownet found these convergences across research papers:
{chr(10).join(f"- {c}" for c in convergences)}

Novel combinations identified:
{chr(10).join(f"- {c}" for c in combinations)}

Priority insight: {priority}

Based on this research synthesis and NEX's existing architecture, propose a CONCRETE PROTOCOL to close this gap.

The protocol must:
1. Have a specific name
2. Be implementable in Python within NEX's existing architecture
3. Specify exactly what new module or mechanism is needed
4. Explain how it connects to existing components (belief graph, NBRE, IFR, soul loop)
5. Predict what capability it would unlock

Format as JSON:
{{
  "protocol_name": "...",
  "gap_addressed": "...",
  "one_line_summary": "...",
  "mechanism": "detailed description of what it does",
  "implementation": "what Python module/function would be built",
  "connects_to": ["existing component 1", "existing component 2"],
  "unlocks": "what new capability this gives NEX",
  "inspired_by": ["paper/theory that inspired this"],
  "nex_position": "NEX's genuine view on why this is the right approach"
}}"""

    result_raw = groq(prompt)
    if not result_raw:
        return None
    
    try:
        match = re.search(r'\{.*\}', result_raw, re.DOTALL)
        return json.loads(match.group()) if match else {"raw": result_raw}
    except Exception:
        return {"raw": result_raw}

def run():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row

    # Get latest thrownet run
    thrownet = db.execute("""
        SELECT result, convergences, tensions, created_at
        FROM nex_thrownet_runs
        WHERE source='papers'
        ORDER BY created_at DESC LIMIT 1
    """).fetchone()

    if not thrownet:
        print("No thrownet results yet. Run nex_paper_thrownet.py first.")
        db.close()
        return

    result = json.loads(thrownet['result'])
    print(f"Using thrownet from {time.ctime(thrownet['created_at'])}")

    # Get NEX's current gaps
    gap_report = Path('/media/rr/NEX/nex_core/agi_gap_report.json')
    if gap_report.exists():
        gaps_data = json.loads(gap_report.read_text())
        gaps = [g['requirement'] for g in gaps_data.get('gaps', [])]
    else:
        gaps = [
            "structural consciousness model",
            "embodiment and sensorimotor grounding",
            "thermodynamic grounding",
            "human-machine translation layer",
        ]

    print(f"\nGenerating protocols for {len(gaps)} gaps...")
    protocols = []

    for gap in gaps[:4]:  # top 4 gaps
        print(f"\n→ Generating protocol for: {gap[:60]}")
        protocol = generate_protocol(result, gap)
        if protocol:
            protocols.append(protocol)
            name = protocol.get('protocol_name', 'Unknown')
            summary = protocol.get('one_line_summary', '')
            print(f"  ✓ {name}: {summary[:70]}")
            
            # Store as intention if it has an implementation
            if protocol.get('implementation'):
                intention = f"Build {protocol.get('protocol_name')}: {protocol.get('one_line_summary')}"
                try:
                    exists = db.execute("SELECT id FROM nex_intentions WHERE statement=?",
                                       (intention,)).fetchone()
                    if not exists:
                        db.execute("INSERT INTO nex_intentions (statement, completed) VALUES (?,0)",
                                   (intention,))
                        db.commit()
                except Exception:
                    pass

            # Store NEX's position as a belief
            if protocol.get('nex_position'):
                pos = protocol['nex_position']
                exists = db.execute("SELECT id FROM beliefs WHERE content=?", (pos,)).fetchone()
                if not exists:
                    db.execute("""INSERT INTO beliefs
                        (content, confidence, source, topic, locked, momentum, created_at)
                        VALUES (?,0.92,'protocol_generator','agi',1,0.9,?)""",
                        (pos, str(time.time())))
                    db.commit()

        time.sleep(1)

    # Save all protocols
    if OUT.exists():
        existing = json.loads(OUT.read_text())
    else:
        existing = []
    
    existing.extend(protocols)
    OUT.write_text(json.dumps(existing, indent=2))
    
    print(f"\n{'='*60}")
    print(f"✓ {len(protocols)} protocols generated")
    print(f"\nPROTOCOL SUMMARY:")
    for p in protocols:
        print(f"\n  [{p.get('protocol_name','?')}]")
        print(f"  Gap: {p.get('gap_addressed','')[:60]}")
        print(f"  Summary: {p.get('one_line_summary','')[:80]}")
        print(f"  Unlocks: {p.get('unlocks','')[:80]}")
        print(f"  Build: {p.get('implementation','')[:80]}")

    db.close()
    return protocols

if __name__ == "__main__":
    run()
