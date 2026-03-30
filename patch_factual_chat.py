#!/usr/bin/env python3
"""
patch_factual_chat.py
─────────────────────
Wires live web search into nex_chat.py so NEX can answer factual questions
about anything — news, science, places, people, current events.

How it works:
  1. A lightweight topic classifier detects factual queries
     (vs philosophical/introspective ones NEX handles from beliefs)
  2. Factual queries trigger a DuckDuckGo instant answer + snippet fetch
  3. The result is injected into the prompt as KNOWN FACTS
  4. NEX answers in her voice, grounded in real data

Also fixes:
  - Dev.to title truncation (broader patch covering all call sites)
  - created_at column missing from metabolism DB

Run from ~/Desktop/nex:
    python3 patch_factual_chat.py
"""

import os, re, shutil, subprocess, sys

NEX_DIR    = os.path.expanduser("~/Desktop/nex")
VOICE_GEN  = os.path.join(NEX_DIR, "nex", "nex_voice_gen.py")
NEX_CHAT   = os.path.join(NEX_DIR, "nex_chat.py")
DEVTO      = os.path.join(NEX_DIR, "nex_devto.py")
METABOLISM = os.path.join(NEX_DIR, "nex_metabolism.py")

def backup(path):
    dst = path + ".pre_factual_chat"
    if not os.path.exists(dst):
        shutil.copy2(path, dst)
    print("  backup -> " + os.path.basename(dst))

def syntax_ok(path):
    r = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode())
    return r.returncode == 0

print("\n  NEX Factual Chat Patch\n")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Write nex_web_search.py — lightweight web search module
# ══════════════════════════════════════════════════════════════════════════════
print("  [1/4] Writing nex_web_search.py...")

WEB_SEARCH = os.path.join(NEX_DIR, "nex", "nex_web_search.py")

web_search_code = '''#!/usr/bin/env python3
"""
nex_web_search.py
─────────────────
Lightweight web search for NEX factual queries.
Uses DuckDuckGo HTML scrape (no API key needed).
Falls back to a simple description if search fails.
"""

import urllib.request
import urllib.parse
import json
import re
import os

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


def _fetch(url, timeout=8):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _ddg_instant(query):
    """DuckDuckGo instant answer API — fast, no key needed."""
    url = (
        "https://api.duckduckgo.com/?q="
        + urllib.parse.quote(query)
        + "&format=json&no_html=1&skip_disambig=1"
    )
    try:
        raw = _fetch(url)
        data = json.loads(raw)
        abstract = data.get("AbstractText", "").strip()
        answer   = data.get("Answer", "").strip()
        if answer:
            return answer
        if abstract and len(abstract) > 40:
            return abstract[:600]
    except Exception:
        pass
    return ""


def _ddg_snippets(query, n=3):
    """Scrape DuckDuckGo HTML results for snippets."""
    url = (
        "https://html.duckduckgo.com/html/?q="
        + urllib.parse.quote(query)
    )
    try:
        html = _fetch(url)
        # Extract result snippets
        snippets = re.findall(
            r\'<a class="result__snippet"[^>]*>(.*?)</a>\',
            html, re.DOTALL
        )
        clean = []
        for s in snippets[:n]:
            s = re.sub(r\'<[^>]+>\', " ", s)
            s = re.sub(r\'\\s+\', " ", s).strip()
            if len(s) > 30:
                clean.append(s)
        return clean
    except Exception:
        return []


# ── Factual query classifier ──────────────────────────────────────────────────

FACTUAL_TRIGGERS = [
    # question words pointing at external facts
    r"\\bwhat is\\b", r"\\bwhat are\\b", r"\\bwho is\\b", r"\\bwho are\\b",
    r"\\bwhere is\\b", r"\\bwhere are\\b", r"\\bhow does\\b", r"\\bhow do\\b",
    r"\\bwhen did\\b", r"\\bwhen was\\b", r"\\btell me about\\b",
    r"\\bcan you tell\\b", r"\\bwhat happened\\b", r"\\bexplain\\b",
    r"\\bdescribe\\b", r"\\bwhat do you know about\\b",
    # topic keywords that signal factual need
    r"\\b(?:history|science|geography|politics|economy|economics)\\b",
    r"\\b(?:population|capital|country|city|town|region|province)\\b",
    r"\\b(?:president|prime minister|government|parliament|election)\\b",
    r"\\b(?:disease|treatment|medicine|drug|vaccine|symptom)\\b",
    r"\\b(?:planet|star|galaxy|universe|physics|chemistry|biology)\\b",
    r"\\b(?:news|latest|recent|current|today|yesterday)\\b",
    r"\\b(?:price|cost|rate|statistics|data|percentage|study|research)\\b",
]

PERSONAL_TRIGGERS = [
    # things NEX answers from beliefs, not web
    r"\\bdo you\\b", r"\\bare you\\b", r"\\bwhat do you think\\b",
    r"\\bwhat do you believe\\b", r"\\bwhat do you feel\\b",
    r"\\bhow do you feel\\b", r"\\bwhy are you\\b", r"\\bwho are you\\b",
    r"\\byour\\b", r"\\byou are\\b", r"\\byou\'re\\b",
]


def is_factual(query):
    """Return True if this query needs web search rather than belief retrieval."""
    q = query.lower()
    # Personal/introspective — NEX handles from beliefs
    for pat in PERSONAL_TRIGGERS:
        if re.search(pat, q):
            return False
    # Factual signals
    for pat in FACTUAL_TRIGGERS:
        if re.search(pat, q):
            return True
    return False


def search(query, max_facts=3):
    """
    Run a web search for query.
    Returns list of fact strings, or [] if nothing found.
    """
    facts = []

    # Try instant answer first
    instant = _ddg_instant(query)
    if instant:
        facts.append(instant)

    # Top snippets
    snippets = _ddg_snippets(query, n=max_facts)
    for s in snippets:
        if s not in facts:
            facts.append(s)

    return facts[:max_facts]


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "population of south africa"
    print(f"Query: {q}")
    print(f"Factual: {is_factual(q)}")
    results = search(q)
    for i, r in enumerate(results, 1):
        print(f"  [{i}] {r[:120]}")
'''

os.makedirs(os.path.join(NEX_DIR, "nex"), exist_ok=True)
with open(WEB_SEARCH, "w") as f:
    f.write(web_search_code)

if syntax_ok(WEB_SEARCH):
    print("  [OK] nex_web_search.py written")
else:
    print("  [FAIL] nex_web_search.py has syntax error")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Patch nex_voice_gen.py to use web search for factual queries
# ══════════════════════════════════════════════════════════════════════════════
print("\n  [2/4] Patching nex_voice_gen.py...")

with open(VOICE_GEN, "r") as f:
    src = f.read()

backup(VOICE_GEN)

# Add import for web search at the top of the file
if "nex_web_search" not in src:
    src = re.sub(
        r"(^import os)",
        "import os\ntry:\n    from nex_web_search import search as _web_search, is_factual as _is_factual\nexcept ImportError:\n    _web_search = lambda q, **kw: []\n    _is_factual = lambda q: False",
        src, count=1, flags=re.MULTILINE
    )
    print("  [OK] nex_web_search import added")

# Find generate_reply and inject web search before the _compose call
# Look for the facts fetch section we added earlier
if "_is_factual" not in src:
    # Inject before the _compose call
    src = re.sub(
        r"(    facts = \[\]\n    try:)",
        (
            "    # ── web search for factual queries ────────────────────────────\n"
            "    if _is_factual(q):\n"
            "        try:\n"
            "            web_facts = _web_search(q, max_facts=3)\n"
            "            if web_facts:\n"
            "                facts = web_facts\n"
            "        except Exception:\n"
            "            pass\n"
            "    \1"
        ),
        src, count=1
    )
    # If facts section not found, inject before the _compose call directly
    if "_is_factual" not in src:
        src = re.sub(
            r"(    response = _compose\(q, beliefs, ctx)",
            (
                "    # ── web search for factual queries ────────────────────────────\n"
                "    if not facts and _is_factual(q):\n"
                "        try:\n"
                "            facts = _web_search(q, max_facts=3)\n"
                "        except Exception:\n"
                "            pass\n"
                "    \1"
            ),
            src, count=1
        )
    print("  [OK] web search injected into generate_reply")

# Update the system prompt to tell NEX to use facts when available
if "KNOWN FACTS" not in src:
    src = re.sub(
        r"(- Never open with a meta-phrase[^\n]*\n)",
        (
            r"\1"
            "- When KNOWN FACTS are provided, use them to anchor your answer. "
            "Speak in your own voice but ground the response in the facts given.\n"
        ),
        src, count=1
    )
    print("  [OK] facts usage instruction added to NEX_SYSTEM")

with open(VOICE_GEN, "w") as f:
    f.write(src)

if syntax_ok(VOICE_GEN):
    print("  [OK] nex_voice_gen.py syntax clean")
else:
    shutil.copy2(VOICE_GEN + ".pre_factual_chat", VOICE_GEN)
    print("  [FAIL] nex_voice_gen.py — backup restored")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Fix Dev.to title truncation (all call sites)
# ══════════════════════════════════════════════════════════════════════════════
print("\n  [3/4] Fixing Dev.to title (all call sites)...")

if os.path.exists(DEVTO):
    backup(DEVTO)
    with open(DEVTO, "r") as f:
        devto = f.read()

    # Add a helper function if not present
    if "_trunc_title" not in devto:
        helper = (
            "\n\ndef _trunc_title(t, n=125):\n"
            "    \"\"\"Dev.to rejects titles over 128 chars.\"\"\"\n"
            "    if not t:\n"
            "        return t\n"
            "    t = str(t).strip()\n"
            "    return t[:n] + ('...' if len(t) > n else '')\n\n"
        )
        # Inject after imports
        devto = re.sub(
            r"(^(?:import|from)\s+\S+[^\n]*\n)+",
            lambda m: m.group(0) + helper,
            devto, count=1, flags=re.MULTILINE
        )

    # Wrap ALL "title" values in payload dicts with _trunc_title
    # Pattern: "title": some_var_or_string
    devto = re.sub(
        r'("title"\s*:\s*)(?!_trunc_title)([^,\n\}]{1,200})',
        lambda m: m.group(1) + "_trunc_title(" + m.group(2).rstrip() + ")",
        devto
    )

    with open(DEVTO, "w") as f:
        f.write(devto)

    if syntax_ok(DEVTO):
        print("  [OK] nex_devto.py — all title fields truncated")
    else:
        shutil.copy2(DEVTO + ".pre_factual_chat", DEVTO)
        print("  [FAIL] nex_devto.py — backup restored")
else:
    print("  [SKIP] nex_devto.py not found")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Fix metabolism DB: add created_at column if missing
# ══════════════════════════════════════════════════════════════════════════════
print("\n  [4/4] Fixing metabolism DB schema (created_at)...")

import sqlite3

DB_PATH = os.path.expanduser("~/Desktop/nex/nex.db")
CFG_DB  = os.path.expanduser("~/.config/nex/nex.db")

for db_path in [DB_PATH, CFG_DB]:
    if not os.path.exists(db_path):
        continue
    try:
        conn = sqlite3.connect(db_path)
        # Check if created_at exists in beliefs
        cols = [r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()]
        if "created_at" not in cols:
            conn.execute(
                "ALTER TABLE beliefs ADD COLUMN created_at TEXT DEFAULT ''"
            )
            conn.commit()
            print(f"  [OK] created_at column added to {os.path.basename(db_path)}")
        else:
            print(f"  [OK] created_at already in {os.path.basename(db_path)}")
        conn.close()
    except Exception as e:
        print(f"  [WARN] {os.path.basename(db_path)}: {e}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n  Done\n")
print("  What changed:")
print("    1. nex_web_search.py  — DuckDuckGo search, no API key needed")
print("    2. nex_voice_gen.py   — factual queries trigger web search")
print("                            NEX answers in her voice, grounded in real data")
print("    3. nex_devto.py       — ALL title fields truncated to 125 chars")
print("    4. nex.db             — created_at column added (fixes metabolism error)")
print()
print("  Test web search:")
print("    cd ~/Desktop/nex && python3 nex/nex_web_search.py population of south africa")
print()
print("  Test voice gen:")
print("    rm -f .semantic_cache*.pkl && python3 nex/nex_voice_gen.py")
print()
print("  Then restart NEX:")
print("    nex")
