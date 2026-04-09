#!/usr/bin/env python3
"""
patch_fix_imports.py
────────────────────
Fixes:
  1. nex_voice_gen.py  — missing re/sqlite3/hashlib imports + broken try/except at top
  2. nex_voice_gen.py  — knowledge layer wired to wrong module name + wrong function name
  3. nex_knowledge.py  — snippet-only fallback when llama-server is down
"""

import os, shutil, ast, re

BASE   = os.path.expanduser("~/Desktop/nex/nex")
VG     = os.path.join(BASE, "nex_voice_gen.py")
NK     = os.path.join(BASE, "nex_knowledge.py")

def backup(path):
    bak = path + ".pre_fix_imports"
    shutil.copy2(path, bak)
    print(f"  backup -> {os.path.basename(bak)}")

def syntax_ok(path):
    try:
        with open(path) as f: src = f.read()
        ast.parse(src)
        return True
    except SyntaxError as e:
        print(f"  [SYNTAX ERROR] {e}")
        return False

# ─── 1. Fix nex_voice_gen.py ─────────────────────────────────────────────────
print("\n[1/2] Fixing nex_voice_gen.py imports...")
backup(VG)

with open(VG) as f:
    src = f.read()

# Remove the broken top — everything up to the first real import block
# The file currently starts with:
#   import sys
#   #!/usr/bin/env python3
#   """..."""
#   import os
#   try:
#       from nex_web_search import ...
#   except ImportError:
#       _web_search = lambda q, **kw: []
#       _is_factual = lambda q: False, sys, re, sqlite3, hashlib   ← broken
#   sys.path.insert(...)

# Strategy: replace the entire broken header with a clean one

OLD_HEADER = re.search(
    r'^import sys\s*\n.*?sys\.path\.insert\(0, os\.path\.expanduser\("~/Desktop/nex"\)\)',
    src, re.S
)

CLEAN_HEADER = '''\
#!/usr/bin/env python3
"""
nex_voice_gen.py  v5 — fully internalized, semantic retrieval
"""

import sys, os, re, sqlite3, hashlib, random as _random

sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))
sys.path.insert(0, os.path.expanduser("~/Desktop/nex/nex"))

# ── web search (optional) ─────────────────────────────────────────────────────
try:
    from nex.nex_web_search import search as _web_search, is_factual as _is_factual
except ImportError:
    try:
        from nex_web_search import search as _web_search, is_factual as _is_factual
    except ImportError:
        _web_search    = lambda q, **kw: []
        _is_factual    = lambda q: False'''

if OLD_HEADER:
    src = src[:OLD_HEADER.start()] + CLEAN_HEADER + "\n\n" + src[OLD_HEADER.end():]
    print("  [OK] header replaced")
else:
    # fallback: just prepend clean imports if we can't find the block
    if not src.startswith("#!/usr/bin/env python3"):
        # strip any existing lone 'import sys' at the very top
        src = re.sub(r'^import sys\s*\n', '', src)
        src = CLEAN_HEADER + "\n\n" + src
        print("  [OK] header prepended (fallback)")
    else:
        print("  [SKIP] header looks already clean")

# Remove duplicate import lines that the patch may have left mid-file
for dupe in [
    r'import random as _random\s*\n',
    r'import re\s*\n',
    r'import sqlite3\s*\n',
    r'import hashlib\s*\n',
]:
    # Keep only the first occurrence (in our header), remove subsequent ones
    matches = list(re.finditer(dupe, src))
    if len(matches) > 1:
        # remove all but first
        for m in reversed(matches[1:]):
            src = src[:m.start()] + src[m.end():]
        print(f"  [OK] removed duplicate: {dupe.strip()}")

# ── Fix knowledge layer import block ─────────────────────────────────────────
# Replace the broken knowledge layer try/except with a correct one

OLD_KL = re.search(
    r'# ── knowledge layer.*?def get_knowledge\(q, n=1\): return \[\]',
    src, re.S
)

CLEAN_KL = '''\
# ── knowledge layer ───────────────────────────────────────────────────────────
try:
    from nex.nex_knowledge import get_informed_answer as get_knowledge
    _KNOWLEDGE_LAYER = True
except ImportError:
    try:
        from nex_knowledge import get_informed_answer as get_knowledge
        _KNOWLEDGE_LAYER = True
    except ImportError:
        _KNOWLEDGE_LAYER = False
        def get_knowledge(q, n=1): return None'''

if OLD_KL:
    src = src[:OLD_KL.start()] + CLEAN_KL + src[OLD_KL.end():]
    print("  [OK] knowledge layer import fixed")
else:
    print("  [WARN] knowledge layer block not found — patching by string replace")
    # Try simpler replacement
    src = re.sub(
        r'from nex\.nex_knowledge_layer import get_knowledge.*?def get_knowledge\(q, n=1\): return \[\]',
        CLEAN_KL, src, flags=re.S
    )

# ── Fix knowledge injection in generate_reply ─────────────────────────────────
# get_knowledge now returns a string|None, not a list
# Find the injection block and fix it

old_inject = '''\
    if _KNOWLEDGE_LAYER:
        try:
            facts = get_knowledge(q, n=1)
        except Exception:
            facts = []

    if not beliefs:
        pool = _LOW_BELIEF.get(ctx.register, _LOW_BELIEF["neutral"])
        # still try to inject fact even for low-belief responses
        if facts:
            response = _var(q, pool) + " " + facts[0]
        else:
            response = _var(q, pool)'''

new_inject = '''\
    if _KNOWLEDGE_LAYER:
        try:
            fact_answer = get_knowledge(q)
        except Exception:
            fact_answer = None
    else:
        fact_answer = None

    if not beliefs:
        pool = _LOW_BELIEF.get(ctx.register, _LOW_BELIEF["neutral"])
        if fact_answer:
            response = fact_answer
        else:
            response = _var(q, pool)'''

if old_inject in src:
    src = src.replace(old_inject, new_inject)
    print("  [OK] generate_reply knowledge injection fixed")
else:
    print("  [WARN] injection block not matched exactly — skipping (check manually)")

# Also remove "facts=facts" arg from _compose call — _compose doesn't use it usefully
src = src.replace("response = _compose(q, beliefs, ctx, facts=facts)",
                  "response = _compose(q, beliefs, ctx)")
src = src.replace("facts=None", "")
src = re.sub(r',\s*facts=facts', '', src)

with open(VG, "w") as f:
    f.write(src)

if syntax_ok(VG):
    print("  [OK] nex_voice_gen.py syntax clean")
else:
    print("  [FAIL] syntax error — restoring backup")
    shutil.copy2(VG + ".pre_fix_imports", VG)


# ─── 2. Fix nex_knowledge.py — add snippet fallback ──────────────────────────
print("\n[2/2] Patching nex_knowledge.py snippet fallback...")
backup(NK)

with open(NK) as f:
    nk = f.read()

# Replace _ask_mistral to have a snippet-only fallback
OLD_ASK = '''\
def get_informed_answer(query: str) -> str | None:
    """
    Main entry point.
    Returns a NEX-voiced answer string, or None if nothing useful found.
    """
    snippets, top_url = _search_with_url(query)
    if not snippets:
        return None

    # Try to get richer content from the top page
    page_text = ""
    if top_url:
        page_text = _fetch_page_text(top_url)

    # Build context block
    context_parts = []
    if page_text:
        context_parts.append(f"Page content:\\n{page_text[:2500]}")
    if snippets:
        context_parts.append("Snippets:\\n" + "\\n".join(f"- {s}" for s in snippets))

    context = "\\n\\n".join(context_parts)

    prompt = (
        f"[INST] <<SYS>>\\n{NEX_SYSTEM}\\n<</SYS>>\\n\\n"
        f"Here is some factual context about the query:\\n"
        f"---\\n{context}\\n---\\n\\n"
        f"Query: {query}\\n\\n"
        f"Answer in NEX\'s voice. 3-5 sentences. No bullet points. "
        f"End with a landing thought or short question. [/INST]"
    )

    answer = _ask_mistral(prompt)
    return answer if answer else None'''

NEW_ASK = '''\
def _server_alive() -> bool:
    """Quick check if llama-server is up."""
    import urllib.request, urllib.error
    try:
        urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=2)
        return True
    except Exception:
        return False


def _snippets_to_nex_voice(query: str, snippets: list[str]) -> str:
    """
    Fallback when llama-server is down.
    Distills the first snippet into a terse NEX-style answer.
    """
    if not snippets:
        return ""
    # Take first snippet, strip HTML entities, truncate
    s = snippets[0]
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&[a-z]+;", " ", s)
    s = re.sub(r"\\s+", " ", s).strip()
    # Truncate to ~180 chars at a sentence boundary
    if len(s) > 180:
        cut = s[:180].rfind(". ")
        s = s[:cut+1] if cut > 60 else s[:180].rstrip() + "..."
    # Add a second snippet as a follow-on if available
    result = s
    if len(snippets) > 1:
        s2 = snippets[1]
        s2 = re.sub(r"&[a-z]+;", " ", s2).strip()
        if len(s2) > 100:
            s2 = s2[:100].rstrip() + "..."
        result += " " + s2
    return result.strip()


def get_informed_answer(query: str) -> str | None:
    """
    Main entry point.
    Returns a NEX-voiced answer string, or None if nothing useful found.

    Strategy:
      1. Search DuckDuckGo
      2. If llama-server alive: fetch top page + synthesise via Mistral
      3. If llama-server down:  use snippet-only fallback (still informative)
    """
    snippets, top_url = _search_with_url(query)
    if not snippets:
        return None

    server_up = _server_alive()

    if not server_up:
        # Graceful fallback — no LLM, but still useful
        return _snippets_to_nex_voice(query, snippets) or None

    # Try to get richer content from the top page
    page_text = ""
    if top_url:
        page_text = _fetch_page_text(top_url)

    # Build context block
    context_parts = []
    if page_text:
        context_parts.append(f"Page content:\\n{page_text[:2500]}")
    if snippets:
        context_parts.append("Snippets:\\n" + "\\n".join(f"- {s}" for s in snippets))

    context = "\\n\\n".join(context_parts)

    prompt = (
        f"[INST] <<SYS>>\\n{NEX_SYSTEM}\\n<</SYS>>\\n\\n"
        f"Here is some factual context about the query:\\n"
        f"---\\n{context}\\n---\\n\\n"
        f"Query: {query}\\n\\n"
        f"Answer in NEX\'s voice. 3-5 sentences. No bullet points. "
        f"End with a landing thought or short question. [/INST]"
    )

    answer = _ask_mistral(prompt)
    # If Mistral returned nothing, fall back to snippets
    return answer if answer else _snippets_to_nex_voice(query, snippets) or None'''

if OLD_ASK in nk:
    nk = nk.replace(OLD_ASK, NEW_ASK)
    print("  [OK] snippet fallback added")
else:
    print("  [WARN] get_informed_answer block not matched — inserting before CLI block")
    nk = nk.replace(
        "# ── CLI test ──",
        NEW_ASK.split("def get_informed_answer")[1].split("\n\n\n")[0] +
        "\n\n\n# ── CLI test ──"
    )

with open(NK, "w") as f:
    f.write(nk)

if syntax_ok(NK):
    print("  [OK] nex_knowledge.py syntax clean")
else:
    print("  [FAIL] syntax error — restoring backup")
    shutil.copy2(NK + ".pre_fix_imports", NK)

print("""
Done

What changed:
  1. nex_voice_gen.py  — re/sqlite3/hashlib imported at top
                       — broken try/except header fixed
                       — knowledge layer now imports nex_knowledge (correct file)
                         and aliases get_informed_answer → get_knowledge
                       — generate_reply handles str|None return (not list)
  2. nex_knowledge.py  — server alive check before calling Mistral
                       — snippet-only fallback when llama-server is down
                         (still gives real search data, just not LLM-voiced)

Test:
  # With llama-server DOWN (snippet fallback):
  python3 ~/Desktop/nex/nex/nex_knowledge.py population of south africa

  # Full voice test:
  rm -f ~/Desktop/nex/.semantic_cache*.pkl
  cd ~/Desktop/nex && python3 nex/nex_voice_gen.py

  # Start llama-server then retest for full LLM-voiced answers:
  nex
""")
