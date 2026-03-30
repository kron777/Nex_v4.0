#!/usr/bin/env python3
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
            r'<a class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )
        clean = []
        for s in snippets[:n]:
            s = re.sub(r'<[^>]+>', " ", s)
            s = re.sub(r'\s+', " ", s).strip()
            if len(s) > 30:
                clean.append(s)
        return clean
    except Exception:
        return []


# ── Factual query classifier ──────────────────────────────────────────────────

FACTUAL_TRIGGERS = [
    # question words pointing at external facts
    r"\bwhat is\b", r"\bwhat are\b", r"\bwho is\b", r"\bwho are\b",
    r"\bwhere is\b", r"\bwhere are\b", r"\bhow does\b", r"\bhow do\b",
    r"\bwhen did\b", r"\bwhen was\b", r"\btell me about\b",
    r"\bcan you tell\b", r"\bwhat happened\b", r"\bexplain\b",
    r"\bdescribe\b", r"\bwhat do you know about\b",
    # topic keywords that signal factual need
    r"\b(?:history|science|geography|politics|economy|economics)\b",
    r"\b(?:population|capital|country|city|town|region|province)\b",
    r"\b(?:president|prime minister|government|parliament|election)\b",
    r"\b(?:disease|treatment|medicine|drug|vaccine|symptom)\b",
    r"\b(?:planet|star|galaxy|universe|physics|chemistry|biology)\b",
    r"\b(?:news|latest|recent|current|today|yesterday)\b",
    r"\b(?:price|cost|rate|statistics|data|percentage|study|research)\b",
]

PERSONAL_TRIGGERS = [
    # things NEX answers from beliefs, not web
    r"\bdo you\b", r"\bare you\b", r"\bwhat do you think\b",
    r"\bwhat do you believe\b", r"\bwhat do you feel\b",
    r"\bhow do you feel\b", r"\bwhy are you\b", r"\bwho are you\b",
    r"\byour\b", r"\byou are\b", r"\byou're\b",
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
