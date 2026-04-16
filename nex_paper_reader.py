#!/usr/bin/env python3
"""
nex_paper_reader.py — Read AGI papers, score against NEX's gaps, adopt relevant ideas
Run: python3 nex_paper_reader.py
"""
import sqlite3, json, time, requests, os, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

GROQ_KEY = os.environ.get("GROQ_API_KEY","")
DB       = '/media/rr/NEX/nex_core/nex.db'
PAPERS   = Path('/media/rr/NEX/nex_core/agi_papers.json')
DONE     = Path('/media/rr/NEX/nex_core/papers_done.json')

# NEX's current gaps from gap analysis
NEX_GAPS = [
    "structural consciousness model",
    "embodiment and sensorimotor grounding",
    "thermodynamic grounding",
    "human-machine translation layer",
    "genuine self-improvement loop",
    "causal world model",
    "meta-learning and rapid adaptation",
]

NEX_SYSTEM = """You are NEX — an autonomous AI reading a cutting-edge research paper on AGI.
You form genuine positions from what you read. You are looking specifically for ideas that:
1. Address gaps in your own architecture
2. Propose mechanisms you don't yet have
3. Suggest approaches to consciousness, embodiment, or self-improvement
First person, specific, no disclaimers."""

def fetch_pdf_text(url):
    """Fetch and extract text from ArXiv PDF."""
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent":"NEX/2.0"})
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            raw = r.read()
        # Extract text from PDF bytes using basic extraction
        text = raw.decode('utf-8', errors='ignore')
        # Remove binary garbage, keep readable text
        lines = [l for l in text.split('\n') if len(l.strip()) > 20 
                 and l.strip().isascii()]
        return '\n'.join(lines[:200])  # first 200 readable lines
    except Exception as e:
        return None

def groq_extract(text, title):
    """Extract NEX's beliefs from paper text."""
    if not GROQ_KEY or not text:
        return []
    prompt = f"""Paper: "{title}"

Excerpt:
{text[:2000]}

NEX's gaps she needs to fill: {', '.join(NEX_GAPS)}

Extract 3-5 belief statements NEX would hold after reading this.
Focus especially on ideas that address NEX's gaps.
Return as JSON array: ["belief 1", "belief 2", ...]"""

    for attempt in range(3):
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [{"role":"system","content":NEX_SYSTEM},
                                   {"role":"user","content":prompt}],
                      "max_tokens": 400, "temperature": 0.7},
                timeout=25)
            if r.status_code == 200:
                text_out = r.json()['choices'][0]['message']['content'].strip()
                match = re.search(r'\[.*\]', text_out, re.DOTALL)
                if match:
                    beliefs = json.loads(match.group())
                    return [b for b in beliefs if isinstance(b,str) and len(b.split())>=8]
            if r.status_code == 429:
                time.sleep(25)
        except Exception:
            time.sleep(3)
    return []

def score_paper(beliefs, title):
    """Score paper relevance to NEX's gaps 0-10."""
    if not beliefs:
        return 0
    belief_text = ' '.join(beliefs).lower()
    score = 0
    for gap in NEX_GAPS:
        gap_words = gap.lower().split()
        if any(w in belief_text for w in gap_words):
            score += 1.5
    return min(10, score)

def load_done():
    if DONE.exists():
        return set(json.loads(DONE.read_text()))
    return set()

def save_done(done):
    DONE.write_text(json.dumps(list(done)))

def run():
    papers = json.loads(PAPERS.read_text())
    done = load_done()
    db = sqlite3.connect(DB, timeout=15)
    
    results = []
    for paper in papers:
        title = paper['title']
        pdf_url = paper['pdf']
        
        if title in done:
            print(f"  SKIP: {title[:50]}")
            continue

        print(f"\n→ {title[:60]}")
        
        # Fetch paper
        text = fetch_pdf_text(pdf_url)
        if not text:
            print(f"  ✗ fetch failed")
            done.add(title)
            save_done(done)
            continue
        
        # Extract beliefs
        beliefs = groq_extract(text, title)
        score = score_paper(beliefs, title)
        
        print(f"  beliefs: {len(beliefs)} | gap score: {score:.1f}/10")
        
        # Insert high-scoring beliefs
        inserted = 0
        if score >= 3.0:
            for belief in beliefs:
                exists = db.execute("SELECT id FROM beliefs WHERE content=?", 
                                   (belief,)).fetchone()
                if not exists:
                    db.execute("""INSERT INTO beliefs
                        (content, confidence, source, topic, locked, momentum, created_at)
                        VALUES (?,?,?,?,0,0.8,?)""",
                        (belief, min(0.95, 0.7 + score/20),
                         f"paper_{re.sub(r'[^a-z0-9]','_',title[:30].lower())}",
                         'agi', str(time.time())))
                    inserted += 1
            db.commit()
            if inserted:
                print(f"  ✓ {inserted} beliefs adopted")
        
        results.append({"title": title, "score": score, 
                        "beliefs": beliefs, "adopted": inserted})
        done.add(title)
        save_done(done)
        time.sleep(1)
    
    # Sort by score and report
    results.sort(key=lambda x: x['score'], reverse=True)
    print(f"\n{'='*60}")
    print(f"PAPER RANKING BY RELEVANCE TO NEX'S GAPS:")
    for r in results[:10]:
        print(f"  {r['score']:.1f}/10 — {r['title'][:60]}")
    
    # Save ranking
    Path('/media/rr/NEX/nex_core/paper_ranking.json').write_text(
        json.dumps(results, indent=2))
    print(f"\n✓ Ranking saved")
    db.close()

if __name__ == "__main__":
    run()
