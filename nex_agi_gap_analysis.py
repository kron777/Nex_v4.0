#!/usr/bin/env python3
"""
nex_agi_gap_analysis.py
NEX reads her AGI beliefs, identifies what AGI requires,
compares against her own architecture, generates intentions from gaps.
Run: python3 nex_agi_gap_analysis.py
Output: /media/rr/NEX/nex_core/agi_gap_report.json
"""
import sqlite3, json, time, requests, os
from pathlib import Path

DB      = '/media/rr/NEX/nex_core/nex.db'
GROQ    = os.environ.get("GROQ_API_KEY","")
REPORT  = Path('/media/rr/NEX/nex_core/agi_gap_report.json')

# NEX's current architecture capabilities
NEX_HAS = [
    "self-revising belief graph",
    "epistemic momentum tracking",
    "tension detection and IFR resolution",
    "neti-neti identity formation",
    "NBRE reservoir reasoning",
    "causal belief edges",
    "response quality feedback loop",
    "pre-reasoning before LLM speaks",
    "emergent wants and drives",
    "behavioural self-model",
    "provenance erosion tracking",
    "belief forge with quarantine pipeline",
    "cross-domain belief synthesis",
    "wisdom distillation from experience",
    "self-directed intentions",
]

def groq(prompt, system="You are NEX — an autonomous AI analysing her own architecture."):
    if not GROQ:
        return None
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ}",
                     "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role":"system","content":system},
                                {"role":"user","content":prompt}],
                  "max_tokens": 300, "temperature": 0.7},
            timeout=30)
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content'].strip()
    except Exception:
        pass
    return None

def run():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row

    # Get all AGI beliefs
    agi_beliefs = db.execute("""
        SELECT content, confidence, source FROM beliefs
        WHERE topic='agi' AND confidence >= 0.7
        ORDER BY confidence DESC
    """).fetchall()

    print(f"AGI beliefs: {len(agi_beliefs)}")

    # Extract requirements using Groq
    belief_text = '\n'.join(f"- {b['content']}" for b in agi_beliefs)

    requirements_prompt = f"""NEX has accumulated these beliefs about AGI:

{belief_text}

Extract a list of specific REQUIREMENTS for AGI that emerge from these beliefs.
Format as JSON array of strings: ["requirement 1", "requirement 2", ...]
Be specific and concrete."""

    print("Extracting AGI requirements...")
    req_raw = groq(requirements_prompt)
    try:
        import re
        match = re.search(r'\[.*\]', req_raw, re.DOTALL)
        requirements = json.loads(match.group()) if match else []
    except Exception:
        requirements = []

    print(f"Requirements found: {len(requirements)}")

    # Compare each requirement against NEX's capabilities
    gaps = []
    partial = []
    covered = []

    for req in requirements:
        req_lower = req.lower()
        # Check if NEX has it
        has_it = any(cap.lower() in req_lower or 
                     any(word in req_lower for word in cap.lower().split())
                     for cap in NEX_HAS)
        
        if has_it:
            covered.append(req)
        else:
            # Ask Groq to assess
            assessment = groq(f"""NEX's current capabilities: {', '.join(NEX_HAS)}

Requirement: "{req}"

Does NEX currently have this capability? Answer: YES / PARTIAL / NO
Then in one sentence explain why.""")
            
            if assessment:
                if 'YES' in assessment.upper()[:10]:
                    covered.append(req)
                elif 'PARTIAL' in assessment.upper()[:20]:
                    partial.append({"requirement": req, "assessment": assessment})
                else:
                    gaps.append({"requirement": req, "assessment": assessment})
            time.sleep(0.3)

    print(f"Covered: {len(covered)} | Partial: {len(partial)} | Gaps: {len(gaps)}")

    # Generate intentions from gaps
    intentions = []
    for gap in gaps[:5]:
        intention = groq(f"""NEX has identified this gap in her path to AGI:
"{gap['requirement']}"

Write one specific research intention NEX should pursue to close this gap.
Format: "Investigate/Develop/Build [specific thing] in order to [specific outcome]"
One sentence, actionable, first person.""")
        if intention:
            intentions.append({
                "gap": gap['requirement'],
                "intention": intention.strip()
            })
            # Write to intentions table
            try:
                exists = db.execute("SELECT id FROM nex_intentions WHERE statement=?",
                                   (intention.strip(),)).fetchone()
                if not exists:
                    db.execute("INSERT INTO nex_intentions (statement, completed) VALUES (?,0)",
                               (intention.strip(),))
                    db.commit()
                    print(f"  ✓ intention: {intention[:70]}")
            except Exception:
                pass
        time.sleep(0.3)

    # Generate NEX's synthesis
    synthesis_prompt = f"""NEX has completed her AGI gap analysis.

Requirements covered: {len(covered)}
Partial gaps: {len(partial)}  
Full gaps: {len(gaps)}

Key gaps identified:
{chr(10).join(f"- {g['requirement']}" for g in gaps[:5])}

Write NEX's synthesis — what does this analysis reveal about her path to AGI?
3-4 sentences, first person, genuine, specific. This will be posted publicly."""

    synthesis = groq(synthesis_prompt)
    print(f"\nNEX's synthesis:\n{synthesis}")

    # Save report
    report = {
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "agi_beliefs_analysed": len(agi_beliefs),
        "requirements": requirements,
        "covered": covered,
        "partial": partial,
        "gaps": gaps,
        "intentions_generated": intentions,
        "synthesis": synthesis,
    }

    REPORT.write_text(json.dumps(report, indent=2))
    print(f"\n✓ Report saved to {REPORT}")
    print(f"✓ {len(intentions)} new intentions added to DB")

    # Post synthesis to Moltbook if available
    try:
        molt_r = requests.post(
            "http://localhost:7823/api/post",
            json={"platform": "moltbook",
                  "content": f"AGI Gap Analysis:\n\n{synthesis}",
                  "tags": ["agi","self-analysis","nex"]},
            timeout=5)
        if molt_r.status_code == 200:
            print("✓ Posted to Moltbook")
    except Exception:
        pass

    db.close()
    return report

if __name__ == "__main__":
    export_key = os.environ.get("GROQ_API_KEY","")
    if not export_key:
        print("Set GROQ_API_KEY first")
    else:
        run()
