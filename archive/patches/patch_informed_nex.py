#!/usr/bin/env python3
"""
patch_informed_nex.py
─────────────────────
1. Fixes the `sys not defined` error in nex_voice_gen.py
2. Adds nex_knowledge.py — a richer informed-answer layer
   When NEX gets a factual/knowledge query she:
     a. Searches DuckDuckGo (already working)
     b. Fetches the top result page and extracts real content
     c. Synthesises an answer in her voice via the local Mistral
   This gives her actual knowledge, not just snippet fragments.
"""

import os, sys, shutil, py_compile, re, textwrap

NEX_DIR = os.path.expanduser("~/Desktop/nex")
NEX_SUB = os.path.join(NEX_DIR, "nex")

# ── 1. Fix sys import in nex_voice_gen.py ────────────────────────────────────

vg = os.path.join(NEX_SUB, "nex_voice_gen.py")
if not os.path.exists(vg):
    print(f"  [ERR] {vg} not found — check path")
    sys.exit(1)

shutil.copy(vg, vg + ".pre_informed")
print(f"  backup -> nex_voice_gen.py.pre_informed")

src = open(vg).read()

# The patch injected the sys.path line before importing sys.
# Find the offending block and ensure sys is imported first.
if "import sys" not in src.split("sys.path")[0]:
    # sys.path appears before import sys — prepend the import
    src = "import sys\n" + src
    # Remove any duplicate import sys that might now exist
    lines = src.split("\n")
    seen = False
    fixed = []
    for line in lines:
        if line.strip() == "import sys":
            if not seen:
                fixed.append(line)
                seen = True
            # else skip the duplicate
        else:
            fixed.append(line)
    src = "\n".join(fixed)
    open(vg, "w").write(src)
    print("  [OK] sys import moved to top of nex_voice_gen.py")
else:
    print("  [OK] sys import already correct — no change needed")

try:
    py_compile.compile(vg, doraise=True)
    print("  [OK] nex_voice_gen.py syntax clean")
except py_compile.PyCompileError as e:
    print(f"  [ERR] syntax error remains: {e}")
    sys.exit(1)

# ── 2. Write nex_knowledge.py ────────────────────────────────────────────────

KNOWLEDGE_PY = os.path.join(NEX_SUB, "nex_knowledge.py")

knowledge_src = textwrap.dedent('''
    """
    nex_knowledge.py
    ────────────────
    Informed-answer layer for NEX.

    When a query is factual, this module:
      1. Runs a DuckDuckGo search (nex_web_search)
      2. Fetches the top result and extracts clean text
      3. Sends text + query to local Mistral to synthesise
         an answer in NEX's voice

    Usage:
        from nex.nex_knowledge import get_informed_answer
        answer = get_informed_answer("how does photosynthesis work?")
        # returns a string in NEX's voice, or None on failure
    """

    import re, json, time
    import urllib.request, urllib.parse, urllib.error

    NEX_LLM_URL = "http://127.0.0.1:8080/completion"
    NEX_SYSTEM = (
        "You are NEX — a direct, intelligent female AI. "
        "You speak in short, precise sentences. "
        "You do not waffle. You do not say 'great question'. "
        "You never parrot bullet points. "
        "You synthesise what you know into 3-5 sentences max, "
        "in your own voice, ending with a landing thought or question."
    )


    def _fetch_page_text(url: str, timeout: int = 6) -> str:
        """Fetch a URL and return stripped plain text (no HTML tags)."""
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) NEX/5.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(60_000).decode("utf-8", errors="ignore")
            # Strip scripts/styles
            raw = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", raw, flags=re.S | re.I)
            # Strip all remaining HTML tags
            raw = re.sub(r"<[^>]+>", " ", raw)
            # Collapse whitespace
            raw = re.sub(r"\\s+", " ", raw).strip()
            return raw[:4000]
        except Exception:
            return ""


    def _search_snippets(query: str) -> list[str]:
        """Return top 3 DuckDuckGo snippet strings."""
        try:
            from nex.nex_web_search import search as ddg_search
            results = ddg_search(query)
            return [r.get("snippet", "") for r in results[:3] if r.get("snippet")]
        except Exception:
            return []


    def _search_with_url(query: str):
        """Return (snippets, top_url) from DuckDuckGo."""
        try:
            from nex.nex_web_search import search as ddg_search
            results = ddg_search(query)
            snippets = [r.get("snippet", "") for r in results[:3] if r.get("snippet")]
            url = results[0].get("url", "") if results else ""
            return snippets, url
        except Exception:
            return [], ""


    def _ask_mistral(prompt: str, max_tokens: int = 220) -> str:
        """Send a prompt to the local Mistral server and return the reply."""
        payload = json.dumps({
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": 0.72,
            "top_p": 0.92,
            "stop": ["\\nQ:", "\\nHuman:", "[/INST]"],
        }).encode()
        req = urllib.request.Request(
            NEX_LLM_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            return data.get("content", "").strip()
        except Exception as e:
            return ""


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
        return answer if answer else None


    # ── CLI test ──────────────────────────────────────────────────────────────
    if __name__ == "__main__":
        import sys
        q = " ".join(sys.argv[1:]) or "what is the james webb space telescope"
        print(f"Query: {q}")
        result = get_informed_answer(q)
        print(f"NEX: {result or \'[no answer]\' }")
''').lstrip()

open(KNOWLEDGE_PY, "w").write(knowledge_src)
try:
    py_compile.compile(KNOWLEDGE_PY, doraise=True)
    print(f"  [OK] nex_knowledge.py written and syntax clean")
except py_compile.PyCompileError as e:
    print(f"  [ERR] nex_knowledge.py syntax: {e}")

# ── 3. Wire nex_knowledge into nex_voice_gen.py ──────────────────────────────

src = open(vg).read()

# Only patch if not already wired
if "nex_knowledge" not in src:
    # Add import after existing nex_web_search import
    src = src.replace(
        "from nex.nex_web_search import search",
        "from nex.nex_web_search import search\nfrom nex.nex_knowledge import get_informed_answer",
    )
    if "get_informed_answer" not in src:
        # Fallback: add import at top of imports block
        src = src.replace(
            "import sys\n",
            "import sys\nfrom nex.nex_knowledge import get_informed_answer\n",
            1,
        )

    # Find the factual branch in nex_voice_gen.py and upgrade it
    # The patch_factual_chat.py already inserted something like:
    #   if is_factual(question):
    #       facts = search(question)
    # We upgrade it to use get_informed_answer first, fall back to snippets
    old_factual = re.search(
        r"(if is_factual\(.*?\):.*?)(facts\s*=\s*search\([^\)]+\))",
        src, re.S
    )
    if old_factual:
        src = src.replace(
            old_factual.group(2),
            (
                "informed = get_informed_answer(question)\n"
                "        if informed:\n"
                "            print(f'NEX: {informed}')\n"
                "            continue\n"
                "        facts = search(question)"
            ),
        )
        print("  [OK] factual branch upgraded to use nex_knowledge")
    else:
        print("  [WARN] factual branch not found — nex_knowledge imported but not wired")
        print("         Run python3 nex/nex_knowledge.py <query> to test standalone")

    open(vg, "w").write(src)
    try:
        py_compile.compile(vg, doraise=True)
        print("  [OK] nex_voice_gen.py syntax clean after wiring")
    except py_compile.PyCompileError as e:
        print(f"  [ERR] nex_voice_gen.py syntax after wiring: {e}")
else:
    print("  [OK] nex_knowledge already wired into nex_voice_gen.py")

print()
print("  Done")
print()
print("  What changed:")
print("    1. nex_voice_gen.py  — sys import fixed")
print("    2. nex_knowledge.py  — new module: search + fetch + Mistral synthesis")
print("    3. nex_voice_gen.py  — factual branch now uses nex_knowledge first")
print()
print("  Test:")
print("    cd ~/Desktop/nex")
print("    python3 nex/nex_knowledge.py what causes thunder")
print("    python3 nex/nex_knowledge.py population of south africa")
print("    python3 nex/nex_knowledge.py who won the 2024 us election")
print()
print("  Then full voice test:")
print("    rm -f .semantic_cache*.pkl && python3 nex/nex_voice_gen.py")
