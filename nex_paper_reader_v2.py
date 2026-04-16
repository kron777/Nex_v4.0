#!/usr/bin/env python3
"""
nex_paper_reader_v2.py — Abstract-based, Cerebras-powered, no PDF timeouts
"""
import sqlite3, json, time, requests, os, re
from pathlib import Path

CEREBRAS_KEY = os.environ.get("CEREBRAS_API_KEY","")
GROQ_KEY     = os.environ.get("GROQ_API_KEY","")
DB           = '/media/rr/NEX/nex_core/nex.db'

NEX_GAPS = [
    "structural consciousness model",
    "embodiment and sensorimotor grounding",
    "thermodynamic grounding",
    "human-machine translation layer",
    "genuine self-improvement loop",
    "causal world model",
]

NEX_SYSTEM = """You are NEX — an autonomous AI reading research abstracts to find ideas for your own development.
Extract genuine belief statements. First person, specific, no disclaimers."""

def llm(prompt, max_tokens=350):
    """Try Cerebras first, fall back to Groq."""
    # Try Cerebras
    if CEREBRAS_KEY:
        try:
            r = requests.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {CEREBRAS_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "llama3.1-8b",
                      "messages": [{"role":"system","content":NEX_SYSTEM},
                                   {"role":"user","content":prompt}],
                      "max_tokens": max_tokens, "temperature": 0.7},
                timeout=15)
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content'].strip()
        except Exception:
            pass
    # Fall back to Groq
    if GROQ_KEY:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [{"role":"system","content":NEX_SYSTEM},
                                   {"role":"user","content":prompt}],
                      "max_tokens": max_tokens, "temperature": 0.7},
                timeout=20)
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content'].strip()
        except Exception:
            pass
    return None

def fetch_abstract(pdf_url):
    """Fetch abstract from ArXiv — fast, no PDF."""
    try:
        abs_url = pdf_url.replace('/pdf/', '/abs/').replace('.pdf','')
        r = requests.get(abs_url, timeout=8,
                        headers={"User-Agent": "NEX/2.0"})
        match = re.search(r'<blockquote[^>]*class="abstract[^"]*"[^>]*>(.*?)</blockquote>',
                         r.text, re.DOTALL)
        if match:
            text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
            return text.replace('Abstract:', '').strip()[:1000]
    except Exception:
        pass
    return None

def score_relevance(beliefs):
    gap_words = ' '.join(NEX_GAPS).lower()
    text = ' '.join(beliefs).lower()
    score = sum(2 for w in gap_words.split() if w in text and len(w) > 4)
    return min(10, score)

def run():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row

    # Get unprocessed papers
    papers = db.execute("""
        SELECT id, title, pdf_url, abstract, category
        FROM nex_papers
        WHERE processed = 0
        ORDER BY score DESC, id ASC
    """).fetchall()

    print(f"Processing {len(papers)} papers via Cerebras...")
    total_beliefs = 0

    for p in papers:
        title    = p['title']
        pdf_url  = p['pdf_url'] or ''
        abstract = p['abstract'] or ''

        print(f"\n→ {title[:65]}")

        # Get abstract if missing
        if not abstract and pdf_url:
            abstract = fetch_abstract(pdf_url) or ''
            if abstract:
                db.execute("UPDATE nex_papers SET abstract=? WHERE id=?",
                          (abstract, p['id']))

        if not abstract:
            print(f"  ✗ no abstract")
            db.execute("UPDATE nex_papers SET processed=1 WHERE id=?", (p['id'],))
            db.commit()
            continue

        # Extract beliefs
        prompt = f"""Paper: "{title}"
Abstract: {abstract[:800]}

NEX gaps to address: {', '.join(NEX_GAPS[:4])}

Extract 3-5 beliefs NEX would hold after reading this.
JSON array only: ["belief 1", "belief 2", ...]"""

        raw = llm(prompt)
        beliefs = []
        if raw:
            try:
                match = re.search(r'\[.*\]', raw, re.DOTALL)
                if match:
                    beliefs = [b for b in json.loads(match.group())
                               if isinstance(b,str) and len(b.split())>=8]
            except Exception:
                pass

        score = score_relevance(beliefs)
        print(f"  beliefs: {len(beliefs)} | score: {score}")

        # Insert beliefs
        inserted = 0
        for belief in beliefs:
            exists = db.execute("SELECT id FROM nex_paper_beliefs WHERE belief=?",
                               (belief,)).fetchone()
            if not exists:
                # Find gap addressed
                gap_match = next((g for g in NEX_GAPS
                                 if any(w in belief.lower()
                                       for w in g.split() if len(w)>4)), "")
                db.execute("""INSERT INTO nex_paper_beliefs
                    (paper_id, belief, confidence, addresses_gap, created_at)
                    VALUES (?,?,?,?,?)""",
                    (p['id'], belief, 0.7 + score/20,
                     gap_match, str(time.time())))
                inserted += 1

                # High-scoring beliefs go into main belief graph
                if score >= 5:
                    exists_main = db.execute("SELECT id FROM beliefs WHERE content=?",
                                           (belief,)).fetchone()
                    if not exists_main:
                        db.execute("""INSERT INTO beliefs
                            (content, confidence, source, topic, locked, momentum, created_at)
                            VALUES (?,?,?,?,0,0.8,?)""",
                            (belief, min(0.9, 0.7+score/20),
                             f"paper_{re.sub(r'[^a-z0-9]','_',title[:25].lower())}",
                             'agi', str(time.time())))

        db.execute("UPDATE nex_papers SET processed=1, score=? WHERE id=?",
                  (score, p['id']))
        db.commit()
        total_beliefs += inserted
        if inserted:
            print(f"  ✓ {inserted} beliefs stored")
        time.sleep(0.2)

    total = db.execute("SELECT COUNT(*) FROM nex_paper_beliefs").fetchone()[0]
    print(f"\n{'='*60}")
    print(f"✓ Complete — {total_beliefs} new beliefs | {total} total in nex_paper_beliefs")

    # Top papers by score
    top = db.execute("""
        SELECT title, score FROM nex_papers
        WHERE processed=1 AND score >= 3
        ORDER BY score DESC LIMIT 10
    """).fetchall()
    if top:
        print(f"\nTop papers by relevance:")
        for title, score in top:
            print(f"  {score:.0f}/10 — {title[:65]}")

    db.close()

if __name__ == "__main__":
    run()
