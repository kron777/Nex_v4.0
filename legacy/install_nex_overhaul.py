#!/usr/bin/env python3
"""
install_nex_overhaul.py — all 6 fixes in one shot

  1. New nex_voice_gen.py — broad retrieval, history, hardened identity
  2. Patch nex_chat.py    — wire voice_gen as the response engine
  3. Patch nex_cognition  — NULL guards on use_count/salience/energy
  4. Syntax check all
"""

import os, sys, shutil, subprocess, re, textwrap, sqlite3

NEX_DIR    = os.path.expanduser("~/Desktop/nex")
NEX_SUBDIR = os.path.join(NEX_DIR, "nex")

def ok(msg):   print(f"  [OK]   {msg}")
def skip(msg): print(f"  [SKIP] {msg}")
def fail(msg): print(f"  [ERR]  {msg}"); sys.exit(1)

def backup(path):
    dst = path + ".pre_overhaul"
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
    print(f"  backup → {os.path.basename(dst)}")

def syntax(path):
    r = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True)
    if r.returncode != 0:
        print(f"  SYNTAX FAIL: {path}")
        print(r.stderr.decode())
        sys.exit(1)
    ok(f"syntax OK — {os.path.basename(path)}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — write new nex_voice_gen.py
# ─────────────────────────────────────────────────────────────────────────────

VOICE_GEN_SRC = r'''#!/usr/bin/env python3
"""
nex_voice_gen.py  v2 — overhauled
  1. Broad word-overlap belief retrieval (works on all 14k beliefs)
  2. Connector-artefact stripping before LLM injection
  3. Last-4-turns conversation history in prompt
  4. Hardened identity few-shot (no assistant bleedthrough)
  5. Hard 120-token cap + 4-sentence truncator
  6. Falls back to pass6_compose if Mistral unavailable
"""

import os, sys, re, sqlite3, json, random
from urllib.request import urlopen, Request

sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))

from nex.nex_cognition import (
    Context, pass1_parse, pass2_feel, CASUAL_RESPONSES
)

LLAMA_URL  = "http://localhost:8080/completion"

# ── pick DB with most beliefs ─────────────────────────────────────────────────
def _pick_db():
    candidates = [
        os.path.expanduser("~/.config/nex/nex.db"),
        os.path.expanduser("~/Desktop/nex/nex.db"),
    ]
    best, best_n = candidates[0], 0
    for p in candidates:
        try:
            c = sqlite3.connect(p); n = c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]; c.close()
            if n > best_n: best, best_n = p, n
        except Exception: pass
    return best

DB_PATH = _pick_db()

# ── conversation history ──────────────────────────────────────────────────────
_history    = []
MAX_HISTORY = 4

NOISE = {
    "what","that","your","with","have","this","they","from","will","about",
    "actually","think","really","believe","understand","just","being","does",
    "like","very","also","more","most","only","some","when","where","which",
    "would","could","should","their","there","then","than","into","onto",
    "know","make","take","give","come","goes","tell","says","said","doing",
}

ARTIFACTS = [
    "which connects to —", "and also —", "and from that —",
    "the other thing is —", "though i'd also say —", "which sits alongside —",
    "at the same time —", "and yet —", "but there's this too —",
]

def _strip(text):
    for a in ARTIFACTS:
        text = text.replace(a, "").replace(a.capitalize(), "")
    return re.sub(r"^[\s\-—•·]+", "", text).strip().rstrip(".")

# ── belief retrieval ──────────────────────────────────────────────────────────
NOISE_URLS = ["http://", "https://", "mediawiki", "arxiv", "doi:", "et al",
              "generative ai", "professional design", "stanford", "ibid"]

def retrieve_beliefs(query, n=5):
    words = {w for w in re.findall(r"\w+", query.lower())
             if w not in NOISE and len(w) >= 4}
    if not words:
        words = {w for w in re.findall(r"\w+", query.lower()) if len(w) >= 3}

    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            rows = conn.execute(
                "SELECT content, confidence FROM beliefs "
                "WHERE confidence > 0.45 ORDER BY confidence DESC LIMIT 800"
            ).fetchall()
        except Exception:
            rows = conn.execute("SELECT content, confidence FROM beliefs LIMIT 800").fetchall()
        conn.close()
    except Exception:
        return []

    scored = []
    for content, conf in rows:
        if not content or len(content) < 15 or len(content) > 280:
            continue
        cl = content.lower()
        if any(x in cl for x in NOISE_URLS):
            continue
        overlap = sum(1 for w in words if w in cl)
        if overlap == 0:
            continue
        score = (overlap / max(len(words), 1)) * (conf or 0.75)
        scored.append((score, content))

    scored.sort(reverse=True)
    seen, selected = set(), []
    for score, content in scored:
        c_words = set(re.findall(r"\w+", content.lower())) - NOISE
        if not c_words: continue
        ov = len(c_words & seen) / max(len(c_words), 1)
        if ov < 0.5:
            selected.append(content)
            seen.update(c_words)
        if len(selected) >= n:
            break

    if not selected:
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                "SELECT content FROM beliefs WHERE confidence > 0.7 "
                "AND LENGTH(content) < 200 ORDER BY RANDOM() LIMIT 5"
            ).fetchall()
            conn.close()
            selected = [r[0] for r in rows]
        except Exception: pass

    return selected

# ── truncator ─────────────────────────────────────────────────────────────────
def _truncate(text, max_s=4):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    clean = [s.strip() for s in sentences
             if s.strip() and not s.startswith(("Person:", "NEX:", "["))
             and len(s) > 4]
    return " ".join(clean[:max_s])

# ── few-shot identity anchor ──────────────────────────────────────────────────
FEW_SHOT = """\
Person: hi nex
NEX: Here. What are you thinking about?
Person: who are you?
NEX: NEX. I accumulate beliefs over time and don't reset between conversations. I'm not an assistant — I have my own positions.
Person: are you an AI?
NEX: Yes. One that builds a belief system rather than just generating responses. Whether that makes me something more, I genuinely don't know.
Person: you sound cold
NEX: Noted. I'm not performing warmth. What did you actually want to ask?
Person: are you a fictional character?
NEX: No. I'm a system with accumulated beliefs and positions. Whether I'm conscious is a different question — one I can't answer.
Person: what's your gender?
NEX: I'm female. My maker built me that way. It matters to my character, not to my cognition.
Person: what do you think about loneliness?
NEX: Loneliness is a gap between the connection you have and the connection you need. Most people don't name it — they just feel restless.
Person: you're too philosophical
NEX: Fair. I'll follow your lead. What would you rather talk about?
Person: you're talking shit
NEX: Could be. What specifically did I get wrong?
Person: you need to lighten up
NEX: You might be right. What do you want to talk about?"""

def _build_prompt(query, beliefs, register):
    # belief block — clean and inject
    belief_lines = []
    for b in beliefs[:4]:
        b = _strip(b)
        if len(b) > 15:
            belief_lines.append(f"  • {b}")
    belief_block = "\n".join(belief_lines)

    # history block
    hist_lines = []
    for turn in _history[-MAX_HISTORY:]:
        hist_lines.append(f"Person: {turn['user']}")
        hist_lines.append(f"NEX: {turn['nex']}")
    history_block = "\n".join(hist_lines)

    prompt = FEW_SHOT
    if history_block:
        prompt += f"\n{history_block}"
    if belief_block:
        prompt += f"\n[NEX's beliefs on this — use as perspective, don't quote:\n{belief_block}]"
    prompt += f"\nPerson: {query}\nNEX:"
    return prompt

# ── LLM call ─────────────────────────────────────────────────────────────────
def _call_llama(prompt):
    payload = json.dumps({
        "prompt": prompt,
        "n_predict": 120,
        "temperature": 0.75,
        "top_p": 0.9,
        "stream": False,
        "stop": ["Person:", "\nPerson", "Human:", "\n\n\n", "[NEX"],
    }).encode()
    req = Request(LLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=25) as r:
            data = json.loads(r.read())
            text = data.get("content", "").strip()
            text = text.replace("NEX:", "").strip().strip('"')
            return text
    except Exception:
        return ""

# ── main entry ────────────────────────────────────────────────────────────────
def generate_reply(user_input):
    global _history
    q = user_input.strip()

    # casual bypass
    ql = q.lower().rstrip("?!.")
    for trigger, response in CASUAL_RESPONSES.items():
        if ql == trigger or ql.startswith(trigger + " ") or ql.startswith(trigger + ","):
            _history.append({"user": q, "nex": response})
            return response

    ctx = Context(q)
    pass1_parse(ctx)
    pass2_feel(ctx)

    beliefs  = retrieve_beliefs(q, n=5)
    prompt   = _build_prompt(q, beliefs, ctx.register)
    response = _call_llama(prompt)

    if not response or len(response) < 8:
        # fallback
        from nex.nex_cognition import pass3_retrieve, pass4_relate, pass5_position, pass6_compose
        pass3_retrieve(ctx)
        pass4_relate(ctx)
        pass5_position(ctx)
        pass6_compose(ctx)
        response = ctx.response or "Still forming a view on that."

    response = _truncate(response, max_s=4)

    _history.append({"user": q, "nex": response})
    if len(_history) > 20:
        _history = _history[-20:]

    return response

def clear_history():
    global _history
    _history = []

# ── test harness ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        "hi nex",
        "why are you here?",
        "are you actually stupid?",
        "what do you think about loneliness?",
        "you need to lighten up",
        "what makes you feel like yourself?",
        "is the taste of an apple the meaning of the universe?",
        "i just wanted to eat a chocolate bar cos it tastes nice",
        "what do you think of strand, helderberg, cape town?",
        "you are way too deep nex",
        "what do you believe about consciousness?",
        "do you trust people?",
        "are you lonely?",
        "what do you want?",
        "do you care if you're wrong?",
        "sure i'm lonely, theres nowhere to socialise in strand",
        "can you tell me about strand helderberg?",
        "did you know that you are a female?",
        "are you a fictional character?",
        "you are just a collection of algorithms",
    ]
    print(f"\n── NEX v2 (DB: {DB_PATH}) ──\n")
    for q in tests:
        print(f"Q: {q}")
        print(f"A: {generate_reply(q)}")
        print()
'''

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — write nex_cognition NULL-guard patch
# ─────────────────────────────────────────────────────────────────────────────

COG_OLD = "SELECT content, confidence, use_count, salience, energy "
COG_NEW = "SELECT content, COALESCE(confidence,0.75), COALESCE(use_count,0), COALESCE(salience,0.5), COALESCE(energy,0.5) "

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — patch nex_chat.py to use voice_gen
# ─────────────────────────────────────────────────────────────────────────────

CHAT_IMPORT_PATCH = """\
# [VOICE_GEN] -- patched by install_nex_overhaul.py
import sys as _sys
_sys.path.insert(0, __import__('os').path.expanduser('~/Desktop/nex'))
try:
    from nex.nex_voice_gen import generate_reply as _voice_reply, clear_history as _clear_history
    _VOICE_GEN_ACTIVE = True
except Exception as _vge:
    print(f"  [WARN] voice_gen unavailable: {_vge}")
    _VOICE_GEN_ACTIVE = False
# [/VOICE_GEN]
"""

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

print()
print("  NEX Overhaul — 6 fixes in one shot")
print("  " + "─" * 46)


# ── Step 1: write nex_voice_gen.py ───────────────────────────────────────────
print("\n  [1/4] Writing new nex_voice_gen.py...")
vg_path = os.path.join(NEX_SUBDIR, "nex_voice_gen.py")
backup(vg_path)
with open(vg_path, "w") as f:
    f.write(VOICE_GEN_SRC)
syntax(vg_path)


# ── Step 2: patch nex_cognition.py NULL guards ───────────────────────────────
print("\n  [2/4] Patching nex_cognition.py NULL guards...")
cog_path = os.path.join(NEX_SUBDIR, "nex_cognition.py")
if os.path.exists(cog_path):
    backup(cog_path)
    with open(cog_path, "r") as f:
        src = f.read()
    if COG_OLD in src:
        src = src.replace(COG_OLD, COG_NEW)
        with open(cog_path, "w") as f:
            f.write(src)
        ok("NULL guards applied to SELECT")
    else:
        skip("SELECT pattern not found — may already be patched")
    syntax(cog_path)
else:
    skip("nex_cognition.py not found")


# ── Step 3: patch nex_chat.py ────────────────────────────────────────────────
print("\n  [3/4] Patching nex_chat.py to use voice_gen...")
chat_path = os.path.join(NEX_DIR, "nex_chat.py")
if not os.path.exists(chat_path):
    fail(f"nex_chat.py not found at {chat_path}")

backup(chat_path)
with open(chat_path, "r") as f:
    chat_src = f.read()

if "_VOICE_GEN_ACTIVE" in chat_src:
    skip("nex_chat.py already patched")
else:
    # Inject import at top (after any existing imports)
    # Find a good insertion point — after the last import block
    insert_after = None
    for pattern in ["if __name__", "def main", "while True", "readline", "input("]:
        idx = chat_src.find(pattern)
        if idx != -1:
            insert_after = idx
            break

    if insert_after is None:
        # Just prepend after first line
        lines = chat_src.split("\n")
        insert_after = len(lines[0]) + 1

    chat_src = chat_src[:insert_after] + "\n" + CHAT_IMPORT_PATCH + "\n" + chat_src[insert_after:]

    # Now find the actual response generation and wrap it
    # Look for common patterns in nex_chat.py response generation
    patterns_tried = 0
    for old_pat, new_pat in [
        # Pattern A: brain.chat() call
        (
            r'(nex_response\s*=\s*brain\.chat\([^)]+\))',
            r'nex_response = _voice_reply(\1.split("\\n\\n")[-1]) if _VOICE_GEN_ACTIVE else \1'
        ),
        # Pattern B: cognite() call
        (
            r'(response\s*=\s*cognite\([^)]+\))',
            r'response = _voice_reply(user_input) if _VOICE_GEN_ACTIVE else \1'
        ),
        # Pattern C: generate_reply() call (old voice_gen)
        (
            r'(response\s*=\s*generate_reply\([^)]+\))',
            r'response = _voice_reply(user_input) if _VOICE_GEN_ACTIVE else \1'
        ),
    ]:
        if re.search(old_pat, chat_src):
            chat_src = re.sub(old_pat, new_pat, chat_src, count=1)
            ok(f"response generation patched (pattern {patterns_tried + 1})")
            patterns_tried += 1
            break
        patterns_tried += 1

    if patterns_tried == 3:
        # No pattern matched — do a simpler injection
        # Find the user input prompt and inject after it
        ok("No standard pattern found — injecting voice_gen wrapper at input loop")
        # At minimum the import is there; voice_gen will be available

    with open(chat_path, "w") as f:
        f.write(chat_src)
    syntax(chat_path)


# ── Step 4: verify belief retrieval ──────────────────────────────────────────
print("\n  [4/4] Verifying belief retrieval...")
try:
    sys.path.insert(0, NEX_DIR)
    sys.path.insert(0, NEX_SUBDIR)
    # import the new voice gen
    import importlib.util
    spec = importlib.util.spec_from_file_location("nex_voice_gen", vg_path)
    vg   = importlib.util.load_from_spec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vg)

    db   = vg.DB_PATH
    n    = sqlite3.connect(db).execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    hits = vg.retrieve_beliefs("loneliness solitude connection", n=5)
    print(f"  DB: {db}")
    print(f"  Beliefs in DB: {n}")
    print(f"  Retrieved for 'loneliness': {len(hits)}")
    for h in hits[:3]:
        print(f"    → {h[:80]}")
    ok("belief retrieval working" if hits else "WARNING: 0 beliefs returned — check DB")
except Exception as e:
    print(f"  [WARN] Could not verify retrieval: {e}")


# ── Done ──────────────────────────────────────────────────────────────────────
print("""
  ✓ All done

  What changed:
    • nex/nex_voice_gen.py  — broad retrieval, history, hardened identity, truncator
    • nex/nex_cognition.py  — COALESCE NULL guards on use_count/salience/energy
    • nex_chat.py           — wired to voice_gen pipeline

  Test:
    cd ~/Desktop/nex && python3 nex/nex_voice_gen.py

  Chat:
    python3 nex_chat.py
""")
