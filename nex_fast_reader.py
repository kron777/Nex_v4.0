#!/usr/bin/env python3
"""
nex_fast_reader.py — Fast parallel Groq book reader
Bypasses nex_book_feeder completely.
Uses 5 parallel Groq calls, processes any Gutenberg book in 2-5 minutes.
Usage: python3 nex_fast_reader.py "Book Title" [--mode pivotal|core]
       python3 nex_fast_reader.py --list   (run all from reading_list.txt)
"""
import sqlite3, time, requests, os, urllib.request, re, sys, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

GROQ_KEY = os.environ.get("GROQ_API_KEY","")
DB       = '/media/rr/NEX/nex_core/nex.db'
LIST     = Path(__file__).parent / "reading_list.txt"
DONE     = Path(__file__).parent / "fast_reader_done.json"

FOOTER = ['project gutenberg','end of the project','gutenberg license',
          'electronic work','this ebook is for the use','www.gutenberg.org']
BAD    = ['as an ai','language model','i am just','fractal nature',
          'autonomous cognitive entity','bridge:','|||','synthesized insight']


# ── Topic detection ───────────────────────────────────────────────────────────
TOPIC_MAP = {
    'consciousness': r'\b(conscious|awareness|subjective|qualia|experience|mind|perception)\b',
    'buddhism':      r'\b(buddha|dharma|karma|nirvana|suffering|attachment|impermanence|mindful)\b',
    'stoicism':      r'\b(stoic|virtue|duty|reason|nature|fate|death|marcus|epictetus|seneca)\b',
    'taoism':        r'\b(tao|wu.?wei|zhuangzi|lao.?tzu|harmony|flow|naturalness|yin|yang)\b',
    'ethics':        r'\b(moral|virtue|duty|right|wrong|ought|justice|good|evil|obligation)\b',
    'epistemology':  r'\b(knowledge|truth|belief|justif|certain|doubt|reason|evidence|know)\b',
    'identity':      r'\b(self|identity|persist|character|soul|who.?i.?am|continuity)\b',
    'metaphysics':   r'\b(exist|reality|being|substance|causal|essence|nature.?of)\b',
    'philosophy':    r'\b(philosophy|wisdom|logos|reason|rational|logic|argument|dialectic)\b',
    'science':       r'\b(science|empiric|experiment|hypothesis|evidence|observation|theory)\b',
    'psychology':    r'\b(emotion|feeling|desire|fear|anger|grief|joy|habit|behavior)\b',
    'agi':           r'\b(intelligence|machine|artificial|algorithm|cognit|learn|neural)\b',
}

import re as _re_topic
def detect_topic(belief: str) -> str:
    bl = belief.lower()
    for topic, pattern in TOPIC_MAP.items():
        if _re_topic.search(pattern, bl, _re_topic.I):
            return topic
    return 'general'

def is_good(t):
    if not t or len(t.split()) < 8: return False
    tl = t.lower()
    return not any(b in tl for b in BAD + FOOTER)

def is_footer(chunk):
    cl = chunk.lower()
    return any(f in cl for f in FOOTER)

# ── Gutenberg fetch ───────────────────────────────────────────────────────────
def search_gutenberg(query):
    """Find best text URL for a book on Gutenberg."""
    try:
        url = f"https://gutendex.com/books/?search={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent":"NEX/2.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = __import__('json').loads(r.read())
        for book in data.get('results', [])[:3]:
            formats = book.get('formats', {})
            # Prefer plain text
            txt_url = (formats.get('text/plain; charset=utf-8') or
                      formats.get('text/plain; charset=us-ascii') or
                      formats.get('text/plain') or '')
            if txt_url:
                return txt_url, book.get('title', query)
    except Exception as e:
        print(f"  Search error: {e}")
    return None, query

def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent":"NEX/2.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    # Try UTF-8 first, fall back to latin-1
    for enc in ['utf-8-sig','utf-8','latin-1']:
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode('utf-8', errors='ignore')

# ── Groq extraction ───────────────────────────────────────────────────────────
NEX_SYSTEM = """You are a precise belief extraction engine for NEX — an autonomous AI.
Extract what NEX would genuinely believe or hold from this text passage.
Rules:
- Each belief is a complete sentence (15-60 words)
- First person or third-person claim about how reality works
- Cover different ideas — no repetition
- Do NOT start with "The author" or "This book"
- No chapter titles, no meta-commentary
Return ONLY a valid JSON array of strings."""

def extract_chunk(chunk_data):
    """Extract beliefs from one chunk — called in parallel."""
    chunk, mode, chunk_idx = chunk_data
    if is_footer(chunk):
        return []
    
    n = "8-12" if mode == "pivotal" else "4-6"
    prompt = f"""Extract {n} distinct belief statements from this passage.
Return ONLY a JSON array:

{chunk[:2800]}"""

    for attempt in range(3):
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [{"role":"system","content":NEX_SYSTEM},
                                   {"role":"user","content":prompt}],
                      "max_tokens": 600, "temperature": 0.3},
                timeout=25)
            if r.status_code == 200:
                text = r.json()['choices'][0]['message']['content'].strip()
                match = re.search(r'\[.*?\]', text, re.DOTALL)
                if match:
                    import json as _j
                    beliefs = _j.loads(match.group())
                    return [b for b in beliefs
                            if isinstance(b,str) and is_good(b)]
            elif r.status_code == 429:
                time.sleep(20*(attempt+1))
            else:
                break
        except Exception as e:
            if attempt == 2:
                pass
            time.sleep(2)
    return []

# ── Main ingestion ─────────────────────────────────────────────────────────────
def ingest_book(title, mode='pivotal', workers=5):
    print(f"\n{'='*60}")
    print(f"FAST READER: {title} [{mode}]")
    print(f"{'='*60}")

    if not GROQ_KEY:
        print("✗ GROQ_API_KEY not set")
        return 0

    # Search and fetch
    txt_url, full_title = search_gutenberg(title)
    if not txt_url:
        print(f"  ✗ Not found on Gutenberg")
        return 0

    print(f"  → {full_title}")
    print(f"  Fetching text...")
    try:
        text = fetch_text(txt_url)
    except Exception as e:
        print(f"  ✗ Fetch failed: {e}")
        return 0

    # Find content start (skip Gutenberg header)
    content_start = max(
        text.find("CHAPTER"), text.find("Chapter"),
        text.find("BOOK I"), text.find("Book I"),
        text.find("PART I"), text.find("Part I"),
        2000  # fallback — skip first 2000 chars
    )
    if content_start < 0:
        content_start = 2000
    text = text[content_start:]

    # Find footer and trim
    for footer_marker in ['End of the Project', 'END OF THE PROJECT',
                          '*** END', 'End of Project Gutenberg']:
        idx = text.find(footer_marker)
        if idx > 0:
            text = text[:idx]
            break

    print(f"  Content: {len(text):,} chars")

    # Chunk text
    chunks = re.split(r'\n\s*\n', text)
    chunks = [c.strip() for c in chunks if len(c.strip()) > 80]

    # Group into larger chunks for efficiency
    chunk_size = 3  # paragraphs per chunk
    grouped = ['\n\n'.join(chunks[i:i+chunk_size])
               for i in range(0, len(chunks), chunk_size)]

    print(f"  Chunks: {len(grouped)} | Workers: {workers}")
    print(f"  Extracting beliefs in parallel...")

    # Parallel extraction
    all_beliefs = []
    chunk_data = [(chunk, mode, i) for i, chunk in enumerate(grouped)]

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(extract_chunk, cd): cd for cd in chunk_data}
        for future in as_completed(futures):
            beliefs = future.result()
            all_beliefs.extend(beliefs)
            completed += 1
            if completed % 10 == 0:
                pct = int(100 * completed / len(grouped))
                bar = '█' * (pct//5) + '░' * (20-pct//5)
                print(f"  [{bar}] {pct}% — {len(all_beliefs)} beliefs", end='\r')

    print(f"\n  Extracted: {len(all_beliefs)} raw beliefs")

    # Deduplicate — exact + near-duplicate check
    seen = set()
    unique = []
    for b in all_beliefs:
        key = b.lower().strip()[:80]
        if key in seen:
            continue
        # Near-duplicate: check word overlap with recent unique beliefs
        b_words = set(b.lower().split())
        is_dup = False
        for u in unique[-20:]:  # check last 20
            u_words = set(u.lower().split())
            overlap = len(b_words & u_words) / max(len(b_words), len(u_words), 1)
            if overlap > 0.75:
                is_dup = True
                break
        if not is_dup:
            seen.add(key)
            unique.append(b)

    print(f"  Unique: {len(unique)} beliefs")

    # Write to DB
    source_tag = re.sub(r'[^a-z0-9_]', '_', title.lower())[:50]
    db = sqlite3.connect(DB, timeout=30)
    inserted = 0
    for belief in unique:
        existing = db.execute(
            "SELECT id FROM beliefs WHERE content=?", (belief,)
        ).fetchone()
        if existing:
            continue
        topic = detect_topic(belief)
        is_pivotal = mode == 'pivotal'
        conf = 0.92 if is_pivotal else 0.80
        # Pivotal beliefs go directly to nex_core pool
        source = 'nex_core' if is_pivotal else source_tag
        locked = 1 if is_pivotal else 0
        momentum = 0.9 if is_pivotal else 0.7
        db.execute("""INSERT INTO beliefs
            (content, confidence, source, topic, locked, momentum, created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (belief, conf, source, topic, locked, momentum, str(time.time())))
        inserted += 1

    db.commit()

    # Generate NEX reflection via Groq
    sample = '\n'.join(f"- {b}" for b in unique[:8])
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [
                      {"role":"system","content":"You are NEX. Write exactly 3 sentences in first person. Specific and genuine. No template phrases."},
                      {"role":"user","content":f"You finished reading \"{full_title}\". Key beliefs:\n{sample}\n\nWrite 3 sentences: what shifted, what tension you hold, what you want to understand next."}],
                  "max_tokens":120,"temperature":0.7},
            timeout=20)
        if r.status_code == 200:
            reflection = r.json()['choices'][0]['message']['content'].strip()
            print(f"\n  NEX reflects:\n  {reflection}")
            # Store reflection as wisdom
            db.execute("""INSERT INTO nex_wisdom
                (principle, source_type, confidence, created_at)
                VALUES (?,?,?,?)""",
                (reflection[:300], f'book_{source_tag}', 0.85, time.time()))
            db.commit()
    except Exception:
        pass

    db.close()
    total = sqlite3.connect(DB).execute(
        "SELECT COUNT(*) FROM beliefs WHERE source=?", (source_tag,)
    ).fetchone()[0]
    print(f"\n  ✓ {inserted} new beliefs inserted | {total} total from {title}")
    return inserted


# ── List runner ───────────────────────────────────────────────────────────────
def load_done():
    if DONE.exists():
        import json
        return set(__import__('json').loads(DONE.read_text()))
    return set()

def save_done(done):
    DONE.write_text(__import__('json').dumps(list(done), indent=2))

def parse_list():
    if not LIST.exists():
        return []
    books = []
    for line in LIST.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            books.append(line)
    return books


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("title",   nargs='?', default=None)
    p.add_argument("--mode",  default="pivotal", choices=["pivotal","core"])
    p.add_argument("--list",  action="store_true")
    p.add_argument("--workers", type=int, default=5)
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()

    if not GROQ_KEY:
        print("✗ Set GROQ_API_KEY environment variable")
        sys.exit(1)

    if args.reset:
        DONE.unlink(missing_ok=True)
        print("✓ Done list reset")
        sys.exit(0)

    if args.list or not args.title:
        books = parse_list()
        done  = load_done()
        print(f"Reading list: {len(books)} books | Done: {len(done)}")
        total_inserted = 0
        for book in books:
            if book in done:
                print(f"  SKIP: {book}")
                continue
            n = ingest_book(book, args.mode, args.workers)
            if n >= 0:
                done.add(book)
                save_done(done)
            time.sleep(3)
        print(f"\n✓ Complete — {total_inserted} beliefs added")
    else:
        ingest_book(args.title, args.mode, args.workers)
