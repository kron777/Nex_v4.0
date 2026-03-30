#!/usr/bin/env python3
"""
nex_knowledge.py — NEX Knowledge Engine v2.0 (Pure Kernel)
============================================================
Replaces the Mistral/llama-server dependency entirely.

Strategy:
  1. DuckDuckGo search (nex_web_search)
  2. Fetch top page + extract clean text
  3. Synthesise answer using:
       a. Top 3 search snippets (distilled into NEX voice)
       b. Top 3 belief-graph hits from nex_reason (kernel-native)
       c. NEX identity anchor
  4. Format in NEX voice — no LLM anywhere in this path

No HTTP calls to localhost:8080. No Mistral. No fallback to an LLM.
If web search fails, reason() beliefs answer directly.
"""

import re
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

# ── NEX voice config ──────────────────────────────────────────────
NEX_VOICE_MAXLEN = 320   # max chars for the final answer
SNIPPET_MAXLEN   = 160   # max chars per snippet before truncation
MIN_SNIPPETS     = 1     # proceed even with a single snippet

# ── page fetch ────────────────────────────────────────────────────
def _fetch_page_text(url: str, timeout: int = 6) -> str:
    """Fetch a URL and return stripped plain text (no HTML tags)."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) NEX/5.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(60_000).decode("utf-8", errors="ignore")
        raw = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>",
                     " ", raw, flags=re.S | re.I)
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = re.sub(r"\s+", " ", raw).strip()
        return raw[:4000]
    except Exception:
        return ""


def _search_with_url(query: str):
    """Return (snippets, top_url) from DuckDuckGo."""
    try:
        from nex.nex_web_search import search as ddg_search
        results  = ddg_search(query)
        snippets = [r.get("snippet", "") for r in results[:3] if r.get("snippet")]
        url      = results[0].get("url", "") if results else ""
        return snippets, url
    except Exception:
        return [], ""


# ── snippet distillation (NEX voice, no LLM) ─────────────────────
def _clean_snippet(s: str, maxlen: int = SNIPPET_MAXLEN) -> str:
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&[a-z]+;", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > maxlen:
        cut = s[:maxlen].rfind(". ")
        s   = s[:cut + 1] if cut > 40 else s[:maxlen].rstrip() + "…"
    return s


def _distil_snippets(snippets: list) -> str:
    """
    Turn raw search snippets into a tight NEX-voice paragraph.
    No LLM — uses extractive compression:
      - Take the first complete sentence from each snippet
      - Deduplicate overlapping content
      - Cap at NEX_VOICE_MAXLEN characters total
    """
    sentences = []
    seen_tokens: set = set()

    for s in snippets[:3]:
        clean = _clean_snippet(s)
        # Extract first sentence
        m = re.match(r'^(.+?[.!?])\s', clean)
        sentence = m.group(1) if m else clean[:100]
        # Token dedup — skip if >50% overlap with already-collected sentences
        tokens = set(re.findall(r'\b[a-z]{4,}\b', sentence.lower()))
        if seen_tokens and len(tokens & seen_tokens) / max(len(tokens), 1) > 0.50:
            continue
        seen_tokens |= tokens
        sentences.append(sentence)

    result = " ".join(sentences)
    if len(result) > NEX_VOICE_MAXLEN:
        cut = result[:NEX_VOICE_MAXLEN].rfind(". ")
        result = result[:cut + 1] if cut > 60 else result[:NEX_VOICE_MAXLEN] + "…"
    return result.strip()


# ── belief injection ──────────────────────────────────────────────
def _get_belief_context(query: str) -> str:
    """
    Pull top belief hits from nex_reason and format as a context fragment.
    Falls back silently if nex_reason is unavailable.
    """
    try:
        from nex.nex_reason import reason
        result   = reason(query)
        beliefs  = result.get("supporting", [])[:3]
        if not beliefs:
            return ""
        frags = [b.get("content", "").rstrip(".") for b in beliefs if b.get("content")]
        return ". ".join(frags[:2])  # max 2 belief fragments in the answer
    except Exception:
        return ""


# ── NEX-voice synthesis (pure kernel) ────────────────────────────
def _synthesise_nex_voice(
    query:          str,
    snippet_text:   str,
    belief_context: str,
    anchor:         str = "",
) -> str:
    """
    Combine snippet distillation + belief graph context into a NEX-voice answer.
    No LLM. Rule-based composition guided by what's available.

    Structure:
      [snippet fact] + [belief connection if present] + [landing question/thought]
    """
    parts = []

    if snippet_text:
        parts.append(snippet_text)

    if belief_context:
        # Connect belief to snippet with a bridging phrase
        bridge = "What I hold alongside that:"
        parts.append(f"{bridge} {belief_context}.")

    # Landing thought — derive from query intent
    q_lower = query.lower()
    if any(w in q_lower for w in ["how", "why", "what causes", "explain"]):
        landing = "The mechanism matters more than the label."
    elif any(w in q_lower for w in ["should", "best", "recommend"]):
        landing = "Context changes what's optimal here."
    elif any(w in q_lower for w in ["who", "when", "where"]):
        landing = ""  # factual queries — no philosophical landing
    else:
        landing = "Worth tracing the implications further."

    if landing:
        parts.append(landing)

    result = " ".join(p for p in parts if p)

    # Final length guard
    if len(result) > NEX_VOICE_MAXLEN + 80:
        cut = result[:NEX_VOICE_MAXLEN + 80].rfind(". ")
        result = result[:cut + 1] if cut > 60 else result[:NEX_VOICE_MAXLEN + 80]

    return result.strip()


# ── public API ────────────────────────────────────────────────────
def get_informed_answer(query: str) -> str | None:
    """
    Main entry point — pure kernel, zero LLM.

    Returns a NEX-voiced answer string, or None if nothing useful found.

    Priority:
      1. Web search (snippets + page text)
      2. Belief graph (always attempted in parallel)
      3. If search fails — belief graph only
      4. If both empty — return None (NEX stays silent rather than hallucinate)
    """
    snippets, top_url = _search_with_url(query)
    belief_ctx        = _get_belief_context(query)

    # If search completely failed, try belief-only answer
    if not snippets:
        if belief_ctx:
            return _synthesise_nex_voice(query, "", belief_ctx)
        return None  # nothing — stay silent

    # Optionally enrich with page body (fast timeout)
    page_text = ""
    if top_url:
        page_text = _fetch_page_text(top_url)

    # Use page text to supplement snippets if it's richer
    if page_text and len(page_text) > 200:
        # Extract the first 2 clean sentences from page body as a bonus snippet
        sentences = re.split(r'(?<=[.!?])\s+', page_text[:1200])
        clean_sents = [
            s for s in sentences
            if len(s) > 40 and not re.search(r'cookie|privacy|subscribe|javascript', s, re.I)
        ]
        if clean_sents:
            snippets.append(clean_sents[0])

    snippet_text = _distil_snippets(snippets)
    if not snippet_text:
        return belief_ctx or None

    return _synthesise_nex_voice(query, snippet_text, belief_ctx)


# ── CLI test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "what is the james webb space telescope"
    print(f"Query: {q}")
    result = get_informed_answer(q)
    print(f"NEX: {result or '[no answer — staying silent]'}")
