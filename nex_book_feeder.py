#!/usr/bin/env python3
"""
NEX Book Feeder v4.2 — Integrated Read + Consolidate
─────────────────────────────────────────────────────
After every book ingestion, automatically runs the full consolidation
pipeline (cluster → synthesise → contradict → compress → apply → emerge)
so NEX absorbs maximum value from every book immediately.

Requires nex_consolidate.py in the same directory as this script,
or in ~/Downloads/nex_consolidate.py.
"""

import os, sys, re, json, time, hashlib, sqlite3, argparse, threading, textwrap
import urllib.request, urllib.parse, urllib.error
import datetime

# ── consolidate integration ───────────────────────────────────────────────────
def _load_consolidate():
    """
    Dynamically import nex_consolidate from the same dir as this script,
    or from ~/Downloads. Returns the module or None.
    """
    import importlib.util
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "nex_consolidate.py"),
        os.path.expanduser("~/Downloads/nex_consolidate.py"),
        os.path.expanduser("~/Desktop/nex/nex_consolidate.py"),
    ]
    for path in candidates:
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location("nex_consolidate", path)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None

_consolidate_mod = None   # loaded lazily on first book completion

# ── colour / terminal ────────────────────────────────────────────────────────
try:
    from colorama import init, Fore, Style, Back
    init(autoreset=True)
    C = {
        "purple": Fore.MAGENTA + Style.BRIGHT,
        "cyan":   Fore.CYAN    + Style.BRIGHT,
        "blue":   Fore.BLUE    + Style.BRIGHT,
        "green":  Fore.GREEN   + Style.BRIGHT,
        "yellow": Fore.YELLOW  + Style.BRIGHT,
        "red":    Fore.RED     + Style.BRIGHT,
        "grey":   Fore.WHITE   + Style.DIM,
        "white":  Fore.WHITE   + Style.BRIGHT,
        "reset":  Style.RESET_ALL,
    }
except ImportError:
    C = {k: "" for k in ["purple","cyan","blue","green","yellow","red","grey","white","reset"]}

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

# ── paths ────────────────────────────────────────────────────────────────────
NEX_DIR     = os.path.expanduser("~/Desktop/nex")
DB_PATH     = os.path.join(NEX_DIR, "nex.db")
LOG_DIR     = os.path.join(NEX_DIR, "logs")
DROP_DIR    = os.path.join(NEX_DIR, "book_drop")
DONE_DIR    = os.path.join(NEX_DIR, "book_done")
QUEUE_PATH  = os.path.expanduser("~/.config/nex/consolidation_queue.json")
LLAMA_URL   = "http://127.0.0.1:8080"

os.makedirs(LOG_DIR,  exist_ok=True)
os.makedirs(DROP_DIR, exist_ok=True)
os.makedirs(DONE_DIR, exist_ok=True)
os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)

# ── banner ───────────────────────────────────────────────────────────────────
BANNER = f"""
{C['purple']}  ███╗   ██╗███████╗██╗  ██╗{C['reset']}
{C['cyan']}  ████╗  ██║██╔════╝╚██╗██╔╝{C['reset']}
{C['blue']}  ██╔██╗ ██║█████╗   ╚███╔╝ {C['reset']}
{C['cyan']}  ██║╚██╗██║██╔══╝   ██╔██╗ {C['reset']}
{C['purple']}  ██║ ╚████║███████╗██╔╝ ██╗{C['reset']}
{C['grey']}  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝{C['reset']}

{C['white']}  Book Feeder  v4.2  ·  Read + Consolidate{C['reset']}
{C['grey']}  Search · Drop · Paste · Watch · Auto{C['reset']}
{C['grey']}  ──────────────────────────────────────────{C['reset']}
"""

# ── helpers ───────────────────────────────────────────────────────────────────
def box(lines, colour=C['cyan']):
    width = max(len(l) for l in lines) + 4
    top  = colour + "╔" + "═"*width + "╗" + C['reset']
    bot  = colour + "╚" + "═"*width + "╝" + C['reset']
    mid  = [colour + "║" + C['reset'] + f"  {l:<{width-2}}" + colour + "║" + C['reset'] for l in lines]
    print("\n".join([top] + mid + [bot]))

def section(label):
    print(f"\n{C['cyan']}  ◆ {label}{C['reset']}")

def ok(msg):   print(f"  {C['green']}✓{C['reset']}  {msg}")
def info(msg): print(f"  {C['grey']}→{C['reset']}  {msg}")
def warn(msg): print(f"  {C['yellow']}⚠{C['reset']}  {msg}")
def err(msg):  print(f"  {C['red']}✗{C['reset']}  {msg}")

def spinner_run(label, fn, *args, **kwargs):
    """Run fn(*args) while showing a spinner. Returns fn's result."""
    frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    result = [None]
    exc    = [None]
    done   = threading.Event()

    def worker():
        try:    result[0] = fn(*args, **kwargs)
        except Exception as e: exc[0] = e
        finally: done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    i = 0
    while not done.wait(0.08):
        print(f"\r  {C['cyan']}{frames[i % len(frames)]}{C['reset']}  {label}  ", end="", flush=True)
        i += 1
    print(f"\r  {C['green']}✓{C['reset']}  {label}  " + " "*20)
    if exc[0]: raise exc[0]
    return result[0]

def progress_bar(iterable, label="", total=None):
    items = list(iterable)
    n = total or len(items)
    width = 38
    for idx, item in enumerate(items):
        pct = (idx + 1) / n
        filled = int(width * pct)
        bar = "█"*filled + "░"*(width-filled)
        eta = ""
        print(f"\r  {label:<16} {C['cyan']}{bar}{C['reset']}  {int(pct*100):3d}%{eta}", end="", flush=True)
        yield item
    print()

# ── llama API ────────────────────────────────────────────────────────────────
def llama_reachable():
    try:
        req = urllib.request.Request(f"{LLAMA_URL}/health")
        urllib.request.urlopen(req, timeout=3)
        return True
    except:
        return False

def llama_complete(prompt: str, max_tokens: int = 800, temperature: float = 0.3) -> str:
    """Call llama-server /completion endpoint."""
    payload = json.dumps({
        "prompt": prompt,
        "n_predict": max_tokens,
        "temperature": temperature,
        "stop": ["</beliefs>", "---END---", "<|user|>", "<|system|>", "||", "[Synthesized"],
    }).encode()
    req = urllib.request.Request(
        f"{LLAMA_URL}/completion",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
            return data.get("content", "").strip()
    except Exception as e:
        return ""

# ── database ──────────────────────────────────────────────────────────────────
def get_db():
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def db_write_belief(db, belief_text: str, confidence: float, source: str, tags: list, pivotal: bool = False):
    """Write a belief to nex.db. Handles multiple schema variants gracefully."""
    try:
        cur = db.cursor()
        # Detect schema
        cur.execute("PRAGMA table_info(beliefs)")
        cols = {row[1] for row in cur.fetchall()}

        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if "content" in cols:
            text_col = "content"
        elif "belief" in cols:
            text_col = "belief"
        else:
            text_col = "text"

        # Pivotal: force world_model tag, max momentum (decay-immune)
        if pivotal and "world_model" not in tags:
            tags = list(tags) + ["world_model"]
        tag_str = ",".join(tags) if tags else ""
        momentum_val = 1.0 if pivotal else 0.5

        base_cols = [text_col, "confidence", "source"]
        base_vals = [belief_text, confidence, source]

        if "tags" in cols:
            base_cols.append("tags")
            base_vals.append(tag_str)
        if "created_at" in cols:
            base_cols.append("created_at")
            base_vals.append(ts)
        if "momentum" in cols:
            base_cols.append("momentum")
            base_vals.append(momentum_val)

        placeholders = ",".join(["?"] * len(base_cols))
        cur.execute(
            f"INSERT OR IGNORE INTO beliefs ({','.join(base_cols)}) VALUES ({placeholders})",
            base_vals,
        )
        db.commit()
        return True
    except Exception as e:
        warn(f"DB write failed: {e}")
        return False

def db_get_sample_beliefs(db, n=20) -> list:
    """Fetch a sample of existing beliefs to give llama context."""
    try:
        cur = db.cursor()
        cur.execute("PRAGMA table_info(beliefs)")
        cols = {row[1] for row in cur.fetchall()}
        text_col = "content" if "content" in cols else ("belief" if "belief" in cols else "text")
        cur.execute(f"SELECT {text_col} FROM beliefs ORDER BY RANDOM() LIMIT ?", (n,))
        return [row[0] for row in cur.fetchall() if row[0]]
    except:
        return []

# ── text extraction ───────────────────────────────────────────────────────────
def extract_text_from_pdf(path: str) -> str:
    # Try pdftotext first
    import subprocess
    try:
        r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, timeout=30)
        if r.returncode == 0 and r.stdout:
            return r.stdout.decode("utf-8", errors="replace")
    except:
        pass
    # Fallback: pypdf
    try:
        import pypdf
        reader = pypdf.PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except:
        pass
    # Fallback: pdfminer
    try:
        from pdfminer.high_level import extract_text
        return extract_text(path)
    except:
        pass
    # Last resort: try reading as plain text (some Gutenberg "PDFs" are actually text)
    try:
        with open(path, 'r', encoding='utf-8-sig', errors='ignore') as _f:
            content = _f.read()
        if len(content) > 500:
            return content
    except Exception:
        pass
    err("Could not extract text from file.")
    return ""

def load_file_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(path)
    if ext == ".epub":
        try:
            import ebooklib
            from ebooklib import epub
            from html.parser import HTMLParser
            class P(HTMLParser):
                def __init__(self): super().__init__(); self.parts=[]
                def handle_data(self,d): self.parts.append(d)
            book = epub.read_epub(path)
            parts = []
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                p = P(); p.feed(item.get_content().decode("utf-8","replace")); parts.append("".join(p.parts))
            return "\n".join(parts)
        except:
            err("ebooklib not installed. pip install ebooklib")
            return ""
    # txt / md / anything else
    for enc in ("utf-8","latin-1","cp1252"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return ""

def chunk_text(text: str, chunk_size=2800, overlap=300) -> list:
    """Split text into overlapping chunks."""
    chunks, start = [], 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

# ── CORE: LLM-DRIVEN BELIEF EXTRACTION ───────────────────────────────────────
EXTRACT_PROMPT = """<|system|>
You are a precise belief extraction engine. Output ONLY valid JSON. No prose, no explanation, no markdown.
<|user|>
Extract 5-10 distinct beliefs, insights, or knowledge-claims from the passage below.

Rules:
- Each belief must be a complete, standalone sentence (15-50 words)
- Cover different ideas — don't repeat the same point in different words
- Include factual claims, philosophical insights, psychological patterns, life principles
- Do NOT include chapter titles, names, page numbers, or meta-commentary
- Do NOT start beliefs with "The author" or "This book"

PASSAGE:
{chunk}

Return ONLY a JSON array of strings. Start your response with [ and end with ].
Example format: ["Belief one here.", "Belief two here.", "Belief three here."]
<|assistant|>
["""

EXTRACT_PROMPT_PIVOTAL = """<|system|>
You are a world-model extraction engine. Output ONLY valid JSON. No prose, no explanation, no markdown.
<|user|>
This is a foundational, pivotal text that defines how the world works. Extract 10-15 distinct world-model claims from the passage below.

Focus on:
- How reality behaves (causation, impermanence, emergence, interdependence)
- How the mind works (perception, suffering, desire, attention, delusion)
- How humans behave in groups and alone (power, fear, ego, compassion)
- Fundamental principles that hold across cultures and time
- Subtle ontological claims — what exists, what causes what, what is real

Rules:
- Each claim must be a complete, standalone sentence (15-60 words)
- Extract the deep structure, not just surface advice
- Do NOT include chapter titles, names, page numbers, or meta-commentary
- Do NOT start with "The author" or "This book"

PASSAGE:
{chunk}

Return ONLY a JSON array of strings. Start with [ and end with ].
<|assistant|>
["""

DISTIL_PROMPT = """<|system|>
You are a wisdom distillation engine. Output ONLY valid JSON. No prose, no explanation, no markdown.
<|user|>
From these beliefs extracted from a book, distil 5-8 life lessons — insights so fundamental and universal they reshape how someone lives.

Each lesson must be:
- 20-60 words
- Actionable and memorable
- Universal (not specific to one religion or culture)
- Distinct — do not repeat the same idea in different words

BELIEFS:
{beliefs}

Return ONLY a JSON array of 5-8 strings. Start with [ and end with ].
<|assistant|>
["""

REFLECT_PROMPT = """<|system|>
You are NEX, a contemplative AI. Be concise — exactly 3 sentences, first person, genuine.
<|user|>
You just finished reading "{title}". Key beliefs absorbed:
{beliefs}

Write exactly 3 sentences in first person: what shifted, what tension you're holding, what question is alive in you. Do not ask rhetorical questions. Do not use "I think" or "I feel" as openers.
<|assistant|>
"""

def extract_beliefs_from_chunk(chunk: str, existing_sample: list, mode: str) -> list:
    """Use llama to extract beliefs from a text chunk."""
    # Note: prompt ends with [ so llama continues the JSON array directly
    prompt = (EXTRACT_PROMPT_PIVOTAL if mode == "pivotal" else EXTRACT_PROMPT).format(chunk=chunk[:2800])
    # The prompt ends with [ — llama continues from there
    raw = llama_complete(prompt, max_tokens=700, temperature=0.35)
    if not raw:
        return []

    # The response is the continuation after [, so prepend [
    to_parse = "[" + raw if not raw.strip().startswith("[") else raw

    # Strategy 1: parse the whole thing
    try:
        # Close any unclosed array
        candidate = to_parse.strip()
        if not candidate.endswith("]"):
            # Find last complete string entry and close the array
            last_quote = candidate.rfind('"')
            if last_quote > 0:
                candidate = candidate[:last_quote+1] + "]"
            else:
                candidate += "]"
        beliefs = json.loads(candidate)
        if isinstance(beliefs, list):
            return [b for b in beliefs if isinstance(b, str) and len(b.split()) >= 8]
    except:
        pass

    # Strategy 2: extract all quoted strings >= 8 words
    found = re.findall(r'"([^"]{30,300})"', to_parse)
    return [f for f in found if len(f.split()) >= 8][:10]

def score_belief(belief: str) -> float:
    """Score belief quality 0-1. No Dharmic keyword bias."""
    score = 0.5  # base
    words = len(belief.split())
    if 10 <= words <= 35:  score += 0.1
    if words < 5 or words > 60: score -= 0.2
    # Has a verb (basic sentence check)
    if re.search(r'\b(is|are|was|were|can|will|must|should|creates|leads|enables|brings|requires|means)\b', belief, re.I):
        score += 0.1
    # Not a question
    if not belief.strip().endswith("?"):
        score += 0.05
    # Not too abstract/empty
    if len(set(belief.lower().split())) > 6:
        score += 0.05
    return min(max(score, 0.0), 1.0)

def detect_tags(belief: str) -> list:
    """Assign topic tags based on content."""
    tags = []
    categories = {
        "mind":        r'\b(mind|thought|awareness|consciousness|attention|focus|mental)\b',
        "suffering":   r'\b(suffer|pain|struggle|hardship|difficult|grief|loss)\b',
        "wisdom":      r'\b(wisdom|insight|understanding|knowing|knowledge|truth)\b',
        "action":      r'\b(action|practice|habit|effort|work|do|act|discipline)\b',
        "impermanence":r'\b(impermanent|change|transient|moment|now|present|passing)\b',
        "compassion":  r'\b(compassion|kindness|love|care|empathy|help|others)\b',
        "ego":         r'\b(ego|self|identity|attachment|clinging|desire|craving)\b',
        "nature":      r'\b(nature|universe|world|reality|existence|life|cosmos)\b',
        "dharma":      r'\b(dharma|karma|path|virtue|right|practice|ethics)\b',
    }
    for tag, pattern in categories.items():
        if re.search(pattern, belief, re.I):
            tags.append(tag)
    return tags or ["general"]

# ── INTEGRATE: adaptive, not graph-link-gated ─────────────────────────────────
def integrate_beliefs(candidates: list, existing_beliefs: list, mode: str) -> tuple:
    """
    Accept beliefs based on quality score + deduplication only.
    CORE mode = higher quality threshold.
    Removes the broken graph-link requirement that was killing everything.
    """
    threshold = 0.40 if mode == "pivotal" else (0.65 if mode == "core" else 0.50)
    accepted, dropped, tensions = [], [], []

    # Build a simple dedup set from existing
    existing_lower = {b.lower().strip() for b in existing_beliefs}

    for b in candidates:
        if not b or len(b.strip()) < 15:
            dropped.append(b)
            continue

        score = score_belief(b)

        # Dedup check — skip if very similar to something already held
        b_lower = b.lower().strip()
        dup_threshold = 0.92 if mode == "pivotal" else 0.85
        is_dup = any(
            _similarity(b_lower, ex) > dup_threshold
            for ex in existing_lower
        )
        if is_dup:
            dropped.append(b)
            continue

        if score >= threshold:
            # Check for tension with existing beliefs (soft — hold, don't drop)
            conflicts = [ex for ex in existing_beliefs if _contradicts(b, ex)]
            if conflicts:
                tensions.append({"new": b, "conflicts": conflicts[:2]})
            final_score = max(score, 0.90) if mode == "pivotal" else score
            accepted.append((b, final_score))
        else:
            dropped.append(b)

    return accepted, tensions, dropped

def _similarity(a: str, b: str) -> float:
    """Rough word-overlap similarity."""
    wa = set(a.split())
    wb = set(b.split())
    if not wa or not wb: return 0.0
    return len(wa & wb) / max(len(wa), len(wb))

def _contradicts(a: str, b: str) -> bool:
    """Very rough contradiction detection."""
    negations = [("always","never"), ("everything","nothing"), ("all","none"),
                 ("must","must not"), ("possible","impossible")]
    al, bl = a.lower(), b.lower()
    for pos, neg in negations:
        if pos in al and neg in bl: return True
        if neg in al and pos in bl: return True
    return False

# ── SEARCH ────────────────────────────────────────────────────────────────────
def search_books(query: str) -> list:
    results = []

    # Gutenberg via gutendex
    try:
        url = f"https://gutendex.com/books/?search={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent":"NexBookFeeder/4.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        for book in data.get("results", [])[:4]:
            title  = book.get("title","")
            author = ", ".join(a["name"] for a in book.get("authors",[]))
            # Get txt format
            formats = book.get("formats",{})
            dl_url = formats.get("text/plain; charset=utf-8") or formats.get("text/plain; charset=us-ascii") or formats.get("text/plain") or ""
            if dl_url:
                results.append({"title":title,"author":author,"source":"Gutenberg","url":dl_url,"format":"txt"})
    except: pass

    # DuckDuckGo for PDF
    try:
        ddg_query = urllib.parse.quote(f"{query} filetype:pdf book")
        url = f"https://html.duckduckgo.com/html/?q={ddg_query}"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("utf-8","replace")
        # Extract result links
        links = re.findall(r'href="(https?://[^"]+\.pdf[^"]*)"', html)
        for link in links[:5]:
            fname = os.path.basename(urllib.parse.urlparse(link).path)
            if len(fname) > 3:
                results.append({"title":fname.replace("_"," ").replace("-"," "),"author":"unknown","source":"DuckDuckGo","url":link,"format":"pdf"})
    except: pass

    return results

def download_file(url: str, dest_path: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"NexBookFeeder/4.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            total = int(r.headers.get("Content-Length", 0))
            info(f"Connected  ({total//1024}KB)" if total else "Connected")
            chunk_size = 8192
            downloaded = 0
            with open(dest_path, "wb") as f:
                if HAS_TQDM and total:
                    from tqdm import tqdm
                    bar = tqdm(total=total, unit="B", unit_scale=True, desc="  Downloading", ncols=60)
                while True:
                    chunk = r.read(chunk_size)
                    if not chunk: break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if HAS_TQDM and total: bar.update(len(chunk))
                if HAS_TQDM and total: bar.close()
        ok(f"Saved → {os.path.basename(dest_path)}")
        return True
    except Exception as e:
        err(f"Download failed: {e}")
        return False

# ── MAIN INGEST PIPELINE ──────────────────────────────────────────────────────
def ingest(text: str, title: str, mode: str, db) -> dict:
    fp_hash = hashlib.md5(text[:500].encode()).hexdigest()[:10]
    total_chars = len(text)

    box([
        f"  {title[:50]}",
        f"  mode {mode.upper()}  ·  {total_chars:,} chars  ·  {fp_hash}",
    ])

    existing_beliefs = db_get_sample_beliefs(db, 30) if db else []

    # ── STAGE 1: PREDICT ─────────────────────────────────────────────────────
    section("1/5  PREDICT")
    info("Sampling prior beliefs for baseline...")

    # ── STAGE 2: EXTRACT ─────────────────────────────────────────────────────
    section("2/5  EXTRACT  ·  reading book")
    chunks = chunk_text(text, chunk_size=2800, overlap=300)

    # CORE/PIVOTAL: read every chunk. ENJOY: evenly-spaced sample of 80.
    if mode in ("core", "pivotal"):
        sampled_chunks = chunks          # full book coverage
    else:
        max_chunks = 80
        if len(chunks) <= max_chunks:
            sampled_chunks = chunks
        else:
            step = len(chunks) / max_chunks
            sampled_chunks = [chunks[int(i * step)] for i in range(max_chunks)]

    info(f"Processing {len(sampled_chunks)}/{len(chunks)} chunks via LLM")

    # Parallel extraction — 4 threads, ~3-5x faster than sequential
    from concurrent.futures import ThreadPoolExecutor, as_completed

    valid_chunks = [c for c in sampled_chunks if len(c.strip()) >= 100]
    all_candidates = []
    lock = __import__("threading").Lock()

    def _extract_chunk(chunk):
        return extract_beliefs_from_chunk(chunk, existing_beliefs, mode)

    completed = [0]
    total_valid = len(valid_chunks)
    width = 38

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_extract_chunk, c): c for c in valid_chunks}
        for fut in as_completed(futures):
            try:
                results = fut.result()
                with lock:
                    all_candidates.extend(results)
                    completed[0] += 1
                    pct = completed[0] / total_valid
                    filled = int(width * pct)
                    bar = "█" * filled + "░" * (width - filled)
                    print(f"\r  {'Reading':<16} {bar}  {int(pct*100):3d}%", end="", flush=True)
            except Exception:
                with lock:
                    completed[0] += 1
    print()

    # Deduplicate candidates
    seen, unique_candidates = set(), []
    for b in all_candidates:
        key = b.lower().strip()[:60]
        if key not in seen:
            seen.add(key)
            unique_candidates.append(b)

    info(f"{len(unique_candidates)} unique candidates extracted")

    # ── STAGE 3: INTEGRATE ───────────────────────────────────────────────────
    section("3/5  INTEGRATE")
    accepted, tensions, dropped = integrate_beliefs(unique_candidates, existing_beliefs, mode)
    ok(f"{len(accepted)} accepted  ·  {len(tensions)} tensions  ·  {len(dropped)} dropped")

    # ── STAGE 4: ANCHOR ──────────────────────────────────────────────────────
    section("4/5  ANCHOR")
    beliefs_added = 0
    is_pivotal = (mode == "pivotal")
    source_tag = f"world_model:{fp_hash}" if is_pivotal else f"book:{fp_hash}"
    if db and accepted:
        for belief_text, conf in progress_bar(accepted, label="Writing beliefs"):
            tags = detect_tags(belief_text)
            wrote = db_write_belief(db, belief_text, conf, source_tag, tags, pivotal=is_pivotal)
            if wrote:
                beliefs_added += 1
    elif not db:
        warn("No DB found — beliefs printed only (not saved)")
        for b, c in accepted:
            info(f"[{c:.2f}] {b}")
        beliefs_added = len(accepted)

    # ── STAGE 5: DISTIL ──────────────────────────────────────────────────────
    section("5/5  DISTIL  →  life lessons")
    life_lessons = []
    if accepted:
        sorted_accepted = sorted(accepted, key=lambda x: x[1], reverse=True)
        sample = sorted_accepted[:40]
        belief_list = "\n".join(f"- {b}" for b, _ in sample)
        raw = llama_complete(DISTIL_PROMPT.format(beliefs=belief_list), max_tokens=900, temperature=0.4)
        if raw:
            to_parse = "[" + raw if not raw.strip().startswith("[") else raw
            # Try to parse, repair unclosed array
            for attempt in [to_parse, to_parse.strip().rstrip(",") + "]"]:
                try:
                    lessons = json.loads(attempt)
                    if isinstance(lessons, list):
                        life_lessons = [l for l in lessons if isinstance(l, str) and len(l.split()) >= 8]
                        break
                except:
                    continue
            # Fallback: grab quoted strings
            if not life_lessons:
                life_lessons = re.findall(r'"([^"]{40,400})"', to_parse)
                life_lessons = [l for l in life_lessons if len(l.split()) >= 8][:5]

        # Save life lessons as high-conf beliefs
        if db and life_lessons:
            for lesson in life_lessons:
                db_write_belief(db, f"LIFE LESSON: {lesson}", 0.90, f"book:{fp_hash}", ["wisdom","life_lesson"])
                beliefs_added += 1
        info(f"{len(life_lessons)} life lessons distilled")

    # ── REFLECT ──────────────────────────────────────────────────────────────
    reflection = ""
    if accepted:
        belief_list = "\n".join(f"- {b}" for b, _ in accepted[:10])
        reflection = llama_complete(REFLECT_PROMPT.format(title=title, beliefs=belief_list), max_tokens=200)

    # ── LOG ──────────────────────────────────────────────────────────────────
    log = {
        "title": title, "mode": mode, "hash": fp_hash,
        "chunks_processed": len(sampled_chunks),
        "candidates": len(unique_candidates),
        "accepted": [{"belief":b,"confidence":c} for b,c in accepted],
        "tensions": tensions,
        "life_lessons": life_lessons,
        "beliefs_added": beliefs_added,
        "reflection": reflection,
        "scheduled": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    log_path = os.path.join(LOG_DIR, f"book_{fp_hash}_{int(time.time())}.json")
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)
    info(f"Log → {os.path.basename(log_path)}")

    # Consolidation queue
    try:
        q = json.load(open(QUEUE_PATH)) if os.path.exists(QUEUE_PATH) else []
        q.append({"type":"book_ingestion","hash":fp_hash,"path":log_path})
        json.dump(q, open(QUEUE_PATH,"w"), indent=2)
    except: pass

    return log

def run_consolidation(db):
    """
    Run the full consolidation pipeline after a book is ingested.
    Imports nex_consolidate dynamically — no hard dependency.
    """
    global _consolidate_mod
    if _consolidate_mod is None:
        _consolidate_mod = _load_consolidate()

    if _consolidate_mod is None:
        warn("nex_consolidate.py not found — skipping consolidation.")
        warn("Place nex_consolidate.py in ~/Downloads/ to enable auto-consolidation.")
        return

    print(f"\n{C['purple']}  ══════════════════════════════════════════════════{C['reset']}")
    print(f"{C['purple']}  ◆  CONSOLIDATION PIPELINE  —  absorbing knowledge{C['reset']}")
    print(f"{C['purple']}  ══════════════════════════════════════════════════{C['reset']}\n")

    try:
        nex_db = _consolidate_mod.NexDB(DB_PATH)
        _consolidate_mod.run_pipeline(nex_db, auto=True)
    except Exception as e:
        warn(f"Consolidation error: {e}")
        info("The book was ingested successfully — consolidation can be run manually.")

def print_summary(log: dict, db=None, skip_consolidation=False):
    lines = [
        "INGESTION COMPLETE",
        "",
        f"  Title      {log['title'][:40]}",
        f"  Mode       {log['mode'].upper()}",
        f"  Chunks     {log['chunks_processed']}",
        f"  Candidates {log['candidates']}",
        f"  Tensions   {len(log['tensions'])} held",
        "",
        f"  BELIEFS ADDED   {log['beliefs_added']}",
        f"  incl. {len(log['life_lessons'])} life lessons",
    ]
    if log.get("reflection"):
        import re as _re
        raw_ref = log["reflection"]
        # Strip fake conversation turns and artifacts
        raw_ref = _re.split(r'<\|user\||<\|system\||\|\|', raw_ref)[0]
        raw_ref = _re.sub(r'\[Synthesized[^\]]*\]', '', raw_ref).strip()
        if raw_ref:
            print(f"\n{C['purple']}  NEX reflects:{C['reset']}")
            for line in textwrap.wrap(raw_ref, 58):
                print(f"  {C['grey']}{line}{C['reset']}")
    box(lines, colour=C['green'])

    # Auto-run consolidation unless explicitly skipped
    if not skip_consolidation and log.get("beliefs_added", 0) > 0 and db:
        try:
            db.close()   # release lock before consolidation opens its own connection
        except Exception:
            pass
        run_consolidation(None)

# ── MODES ─────────────────────────────────────────────────────────────────────
def mode_search(mode: str, db):
    query = input(f"\n  {C['white']}› Book title (no author needed):{C['reset']}  ").strip()
    if not query: return

    section(f"SEARCH  ·  \"{query}\"")
    results = spinner_run("Searching...", search_books, query)

    if not results:
        warn("No results found. Try a different title or use manual URL [0].")
        results = []

    ok(f"{len(results)} results found")
    print()
    for i, r in enumerate(results, 1):
        print(f"  {C['cyan']}[{i:2d}]{C['reset']}  {r['title'][:50]}")
        print(f"       {C['grey']}{r['author']}  ·  {r['source']}  {r['format'].upper()}{C['reset']}\n")
    print(f"  {C['grey']}[ 0]  Enter URL manually{C['reset']}")
    print(f"  {C['grey']}[ s]  New search{C['reset']}\n")

    sel = input(f"  {C['white']}› Select number (or 0 / s):{C['reset']}  ").strip()
    if sel.lower() == "s": return mode_search(mode, db)
    if sel == "0":
        url = input("  › URL: ").strip()
        chosen = [{"title": os.path.basename(url), "url": url, "format": url.split(".")[-1]}]
    else:
        try:
            idx = int(sel) - 1
            chosen = [results[idx]] if 0 <= idx < len(results) else []
        except:
            chosen = []

    for r in chosen:
        dest = os.path.join(DROP_DIR, re.sub(r'[^\w.]','_', r['title'])[:60] + "." + r.get("format","pdf"))
        section(f"DOWNLOAD  ·  {r['title'][:40]}")
        ok_dl = spinner_run("Connecting...", download_file, r["url"], dest)
        if ok_dl or os.path.exists(dest):
            text = spinner_run("Extracting text...", load_file_text, dest)
            if text.strip():
                if len(text) < 5000:
                    warn(f"Only {len(text):,} chars extracted — URL may be a stub or redirect. Drop the real PDF via option [2] for best results.")
                log = ingest(text, r["title"], mode, db)
                print_summary(log, db=db)
            else:
                err("No text extracted from file.")

def mode_file(path: str, mode: str, db):
    if not os.path.exists(path):
        err(f"File not found: {path}")
        return
    section(f"FILE  ·  {os.path.basename(path)}")
    text = spinner_run("Extracting text...", load_file_text, path)
    if not text.strip():
        err("No text extracted.")
        return
    log = ingest(text, os.path.basename(path), mode, db)
    print_summary(log, db=db)

def mode_paste(mode: str, db):
    print(f"\n  {C['grey']}Paste your text below. Type{C['reset']} {C['yellow']}END{C['reset']} {C['grey']}on its own line when done.{C['reset']}\n")
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "END": break
        lines.append(line)
    text = "\n".join(lines)
    if text.strip():
        log = ingest(text, "pasted_text", mode, db)
        print_summary(log, db=db)

def mode_watch(watch_dir: str, mode: str, db):
    ok(f"Watching: {watch_dir}")
    info("Drop any PDF/txt/epub into the folder. Ctrl+C to stop.\n")
    seen = set(os.listdir(watch_dir))
    while True:
        time.sleep(6)
        current = set(os.listdir(watch_dir))
        new_files = current - seen
        for fname in new_files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in (".pdf",".txt",".epub",".md"):
                fpath = os.path.join(watch_dir, fname)
                print(f"\n  {C['green']}✦{C['reset']}  New file detected: {fname}")
                time.sleep(1)  # wait for write to finish
                text = spinner_run("Extracting...", load_file_text, fpath)
                if text.strip():
                    log = ingest(text, fname, mode, db)
                    print_summary(log, db=db)
                    done = os.path.join(DONE_DIR, fname)
                    os.rename(fpath, done)
                    ok(f"Moved to done: {done}")
        seen = current

def mode_auto(mode: str, db):
    """NEX reads her own knowledge gaps and ingests books to fill them."""
    if not db:
        err("No DB — auto mode requires nex.db")
        return
    section("AUTO  ·  reading knowledge gaps")
    gaps = []
    try:
        cur = db.cursor()
        for table in ("curiosity_gaps","gaps","knowledge_gaps"):
            try:
                cur.execute(f"SELECT topic FROM {table} WHERE filled=0 OR filled IS NULL LIMIT 5")
                gaps = [row[0] for row in cur.fetchall()]
                if gaps: break
            except: continue
    except: pass

    if not gaps:
        warn("No gaps found in DB. Add rows to curiosity_gaps table.")
        return

    ok(f"Found {len(gaps)} gaps: {', '.join(gaps[:3])}...")
    for gap in gaps[:3]:
        print(f"\n  {C['cyan']}◆ Gap: {gap}{C['reset']}")
        results = spinner_run(f"Searching for: {gap}", search_books, gap)
        if not results:
            warn(f"No books found for: {gap}")
            continue
        r = results[0]
        dest = os.path.join(DROP_DIR, re.sub(r'[^\w.]','_', r['title'])[:60] + ".pdf")
        ok_dl = spinner_run("Downloading...", download_file, r["url"], dest)
        if ok_dl or os.path.exists(dest):
            text = spinner_run("Extracting text...", load_file_text, dest)
            if text.strip():
                log = ingest(text, r["title"], mode, db)
                print_summary(log, db=db)
                # Mark gap filled
                try:
                    for table in ("curiosity_gaps","gaps","knowledge_gaps"):
                        try:
                            db.execute(f"UPDATE {table} SET filled=1 WHERE topic=?", (gap,))
                            db.commit()
                            break
                        except: continue
                except: pass

# ── ENTRY ────────────────────────────────────────────────────────────────────
def main():
    print(BANNER)

    # Check llama
    if llama_reachable():
        ok("llama-server reachable")
    else:
        warn("llama-server not reachable at :8080 — belief quality will be degraded")

    # Check DB
    db = get_db()
    if db:
        ok(f"nex.db connected")
    else:
        warn(f"nex.db not found at {DB_PATH} — beliefs will be printed but not saved")

    print()

    # Mode selector
    print(f"  {C['white']}Ingestion mode:{C['reset']}\n")
    print(f"  {C['cyan']}[1]{C['reset']}  core    — full conditions, graph rewrite, high-conf")
    print(f"  {C['cyan']}[2]{C['reset']}  enjoy   — light flavour, seasoning only")
    print(f"  {C['purple']}[3]{C['reset']}  pivotal — world-model anchor, decay-immune, max extraction\n")
    sel = input(f"  {C['grey']}› [1/2/3]:{C['reset']}  ").strip()
    if sel == "2":   mode = "enjoy"
    elif sel == "3": mode = "pivotal"
    else:            mode = "core"
    ok(f"Mode: {mode.upper()}")
    print(f"  {C['grey']}╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌{C['reset']}\n")

    # Parse args for non-interactive modes
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--file",   help="Local file path")
    parser.add_argument("--search", help="Search query")
    parser.add_argument("--watch",  action="store_true")
    parser.add_argument("--dir",    default=DROP_DIR)
    parser.add_argument("--auto",   action="store_true")
    parser.add_argument("--mode",   default=mode)
    args, _ = parser.parse_known_args()
    if args.mode: mode = args.mode

    if args.file:
        mode_file(args.file, mode, db)
        return
    if args.search:
        results = spinner_run("Searching...", search_books, args.search)
        if results:
            r = results[0]
            dest = os.path.join(DROP_DIR, re.sub(r'[^\w.]','_', r['title'])[:60] + ".pdf")
            download_file(r["url"], dest)
            text = load_file_text(dest)
            if text.strip():
                log = ingest(text, r["title"], mode, db)
                print_summary(log, db=db)
        return
    if args.watch:
        mode_watch(args.dir, mode, db)
        return
    if args.auto:
        mode_auto(mode, db)
        return

    # Interactive menu
    print(f"  {C['white']}What would you like to do?{C['reset']}\n")
    print(f"  {C['cyan']}[1]{C['reset']}  Search for a book by title")
    print(f"  {C['cyan']}[2]{C['reset']}  Feed a local file  (PDF / txt / epub)")
    print(f"  {C['cyan']}[3]{C['reset']}  Paste text directly")
    print(f"  {C['cyan']}[4]{C['reset']}  Watch drop folder")
    print(f"  {C['cyan']}[5]{C['reset']}  Auto  —  NEX reads her own knowledge gaps\n")

    choice = input(f"  {C['grey']}›{C['reset']}  ").strip()

    if choice == "1":   mode_search(mode, db)
    elif choice == "2":
        path = input(f"  {C['white']}› File path:{C['reset']}  ").strip().strip("'\"")
        mode_file(path, mode, db)
    elif choice == "3": mode_paste(mode, db)
    elif choice == "4": mode_watch(DROP_DIR, mode, db)
    elif choice == "5": mode_auto(mode, db)
    else:
        warn("Unknown option.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n  {C['grey']}Interrupted. Goodbye.{C['reset']}\n")
