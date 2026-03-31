#!/usr/bin/env python3
"""
nex_domain.py — NEX Domain Specialization Engine v1.0
=======================================================
Implements "Way to Specialist" (WTS) bidirectional KG-LLM co-evolution.
Based on: Zhang et al. 2024 + dynamic knowledge injection survey 2025.

Architecture:
  1. DOMAIN INTAKE      — parse domain, map to source taxonomy
  2. RAPID SATURATION   — accelerated crawl targeting domain sources
  3. BELIEF GRAPH LOCK  — weight domain beliefs higher, filter retrieval
  4. CHAT FEEDBACK LOOP — every Q→A cycle generates new beliefs (WTS loop)
  5. GAP TRACKER        — detect what user asks that NEX can't answer → crawl
  6. SESSION REPORT     — what NEX learned, confidence map, remaining gaps
"""

import os
import re
import json
import time
import sqlite3
import threading
import requests
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DB_PATH  = Path("~/.config/nex/nex.db").expanduser()
CFG_PATH = Path("~/.config/nex").expanduser()
LLM_URL  = "http://localhost:8080/v1/chat/completions"

# ── Domain taxonomy — maps domain names to source URLs + search terms ─────────
DOMAIN_TAXONOMY = {
    "oncology": {
        "sources": [
            "https://pubmed.ncbi.nlm.nih.gov/rss/search/?term=oncology&format=rss",
            "https://www.cancer.gov/rss/news.rss",
            "https://arxiv.org/rss/q-bio.GN",
        ],
        "search_terms": ["cancer", "oncology", "tumor", "chemotherapy", "immunotherapy",
                         "carcinoma", "metastasis", "biopsy", "radiotherapy", "CAR-T"],
        "crawl_urls": [
            "https://www.cancer.gov/about-cancer",
            "https://www.cancer.org/cancer/types.html",
            "https://www.nejm.org/medical-articles/oncology",
        ],
    },
    "cardiology": {
        "sources": [
            "https://pubmed.ncbi.nlm.nih.gov/rss/search/?term=cardiology&format=rss",
        ],
        "search_terms": ["heart disease", "cardiology", "myocardial", "arrhythmia",
                         "atherosclerosis", "hypertension", "cardiac", "ECG", "stent"],
        "crawl_urls": [
            "https://www.heart.org/en/health-topics",
            "https://www.who.int/news-room/fact-sheets/detail/cardiovascular-diseases",
        ],
    },
    "finance": {
        "sources": [
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://www.wsj.com/xml/rss/3_7085.xml",
        ],
        "search_terms": ["markets", "equity", "bonds", "derivatives", "hedge fund",
                         "portfolio", "risk", "asset", "valuation", "liquidity"],
        "crawl_urls": [
            "https://www.investopedia.com/financial-term-dictionary-4769738",
        ],
    },
    "legal": {
        "sources": [],
        "search_terms": ["contract law", "tort", "jurisdiction", "precedent", "statute",
                         "litigation", "plaintiff", "defendant", "brief", "motion"],
        "crawl_urls": [
            "https://www.law.cornell.edu/wex",
        ],
    },
    "ai": {
        "sources": [
            "https://arxiv.org/rss/cs.AI",
            "https://arxiv.org/rss/cs.LG",
            "https://arxiv.org/rss/cs.CL",
        ],
        "search_terms": ["machine learning", "neural network", "transformer", "LLM",
                         "reinforcement learning", "alignment", "AGI", "reasoning"],
        "crawl_urls": [
            "https://paperswithcode.com/latest",
        ],
    },
    "climate": {
        "sources": [
            "https://arxiv.org/rss/physics.ao-ph",
            "https://www.nasa.gov/rss/dyn/breaking_news.rss",
        ],
        "search_terms": ["climate change", "carbon", "emissions", "renewable energy",
                         "IPCC", "CO2", "sea level", "drought", "biodiversity"],
        "crawl_urls": [
            "https://climate.nasa.gov/news/",
        ],
    },
    "neuroscience": {
        "sources": [
            "https://pubmed.ncbi.nlm.nih.gov/rss/search/?term=neuroscience&format=rss",
            "https://arxiv.org/rss/q-bio.NC",
        ],
        "search_terms": ["neuroscience", "brain", "cognition", "synapse", "neuron",
                         "consciousness", "fMRI", "plasticity", "dopamine", "cortex"],
        "crawl_urls": [
            "https://www.nih.gov/about-nih/what-we-do/nih-turning-discovery-into-health/neuroscience",
        ],
    },
    "custom": {
        "sources": [],
        "search_terms": [],
        "crawl_urls": [],
    },
}

# ── Active domain state ───────────────────────────────────────────────────────
_active_domain   = None
_domain_config   = {}
_session_gaps    = []
_session_beliefs = 0
_session_start   = None
_lock            = threading.Lock()

# ── DB helpers ────────────────────────────────────────────────────────────────
def _db():
    return sqlite3.connect(str(DB_PATH), timeout=5)

def _belief_count(domain: str) -> int:
    try:
        db = _db()
        terms = DOMAIN_TAXONOMY.get(domain, {}).get("search_terms", [domain])[:3]
        total = 0
        for term in terms:
            n = db.execute(
                "SELECT COUNT(*) FROM beliefs WHERE content LIKE ?",
                (f"%{term}%",)
            ).fetchone()[0]
            total += n
        db.close()
        return total
    except Exception:
        return 0

def _inject_belief(topic: str, content: str, confidence: float = 0.75, source: str = "domain_specialist"):
    """Write a new belief directly to the DB."""
    global _session_beliefs
    try:
        db = _db()
        db.execute(
            "INSERT OR IGNORE INTO beliefs (topic, content, confidence, source, use_count) VALUES (?,?,?,?,0)",
            (topic[:80], content[:500], confidence, source)
        )
        db.commit()
        db.close()
        with _lock:
            _session_beliefs += 1
        return True
    except Exception:
        return False

# ── LLM helpers ───────────────────────────────────────────────────────────────
def _llm(prompt: str, system: str = "", max_tokens: int = 200) -> str:
    try:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        r = requests.post(LLM_URL, json={
            "model": "mistral",
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": False,
        }, timeout=30)
        choices = r.json().get("choices", [])
        return choices[0]["message"]["content"].strip() if choices else ""
    except Exception:
        return ""

# ── Gap detection — WTS bidirectional loop ────────────────────────────────────
def detect_gap(query: str, response: str) -> bool:
    """
    WTS loop: detect when NEX can't answer confidently.
    If response contains uncertainty markers → gap detected → trigger crawl.
    """
    uncertainty_signals = [
        "i don't know", "i'm not sure", "i lack", "i'm uncertain",
        "i haven't learned", "no information", "can't find", "unclear to me",
        "not in my beliefs", "outside my knowledge"
    ]
    rl = response.lower()
    return any(s in rl for s in uncertainty_signals)

def record_gap(query: str, domain: str):
    """Record a knowledge gap for this session."""
    global _session_gaps
    with _lock:
        _session_gaps.append({
            "query": query,
            "domain": domain,
            "timestamp": datetime.now().isoformat(),
        })
    # Async: trigger belief injection on gap
    threading.Thread(target=_fill_gap, args=(query, domain), daemon=True).start()

def _fill_gap(query: str, domain: str):
    """WTS: generate belief from gap query using LLM + inject into graph."""
    system = (
        f"You are a domain expert in {domain}. "
        "Extract 3 precise factual statements relevant to this query. "
        "Format: one fact per line, no bullets, no preamble."
    )
    facts = _llm(query, system=system, max_tokens=150)
    if not facts:
        return
    for line in facts.split("\n"):
        line = line.strip()
        if len(line) > 30:
            # Extract topic keyword
            words = [w for w in line.split() if len(w) > 4]
            topic = words[0] if words else domain
            _inject_belief(topic, line, confidence=0.65, source=f"gap_fill_{domain}")

# ── Rapid saturation — accelerated domain crawl ───────────────────────────────
def _saturate_domain(domain: str, config: dict, target_beliefs: int = 500):
    """
    Accelerated belief injection for domain specialization.
    Uses DuckDuckGo search + page fetch + LLM distillation.
    """
    print(f"\n  [Domain] Starting saturation: {domain} (target: {target_beliefs} beliefs)")
    injected = 0
    search_terms = config.get("search_terms", [domain])

    for term in search_terms:
        if injected >= target_beliefs:
            break
        try:
            # Use existing web search
            from nex.nex_web_search import search as ddg_search
            results = ddg_search(f"{domain} {term} research findings")

            for result in results[:3]:
                if isinstance(result, dict):
                    snippet = result.get("snippet", "") or result.get("body", "")
                    url = result.get("url", "") or result.get("href", "")
                elif isinstance(result, str):
                    snippet = result
                    url = ""
                else:
                    continue
                if len(snippet) < 30:
                    continue

                # Distil snippet into beliefs
                system = (
                    f"Extract 2-3 precise factual beliefs about {domain} from this text. "
                    "Each belief: one sentence, specific, no opinions. One per line."
                )
                distilled = _llm(snippet, system=system, max_tokens=120)

                for line in distilled.split("\n"):
                    line = line.strip()
                    if len(line) > 30:
                        _inject_belief(term, line, confidence=0.7, source=f"domain_{domain}")
                        injected += 1
                        if injected >= target_beliefs:
                            break

                time.sleep(0.5)  # Rate limit

        except Exception as e:
            print(f"  [Domain] Saturation error for '{term}': {e}")
            continue

    print(f"  [Domain] Saturation complete: {injected} beliefs injected for {domain}")
    return injected

# ── Domain activation ─────────────────────────────────────────────────────────
def activate(domain: str, custom_terms: list = None, custom_sources: list = None) -> dict:
    """
    Activate domain specialization.
    Returns status dict.
    """
    global _active_domain, _domain_config, _session_start
    global _session_gaps, _session_beliefs

    domain = domain.lower().strip()

    # Handle custom domain
    if domain not in DOMAIN_TAXONOMY:
        config = DOMAIN_TAXONOMY["custom"].copy()
        config["search_terms"] = custom_terms or [domain]
        config["sources"] = custom_sources or []
    else:
        config = DOMAIN_TAXONOMY[domain].copy()

    if custom_terms:
        config["search_terms"] = list(set(config["search_terms"] + custom_terms))

    _active_domain   = domain
    _domain_config   = config
    _session_start   = datetime.now()
    _session_gaps    = []
    _session_beliefs = 0

    beliefs_before = _belief_count(domain)
    print(f"\n  [Domain] Activating: {domain}")
    print(f"  [Domain] Existing beliefs: {beliefs_before}")

    # Run saturation in background
    threading.Thread(
        target=_saturate_domain,
        args=(domain, config, 300),
        daemon=True,
        name=f"domain-saturate-{domain}"
    ).start()

    return {
        "domain": domain,
        "status": "active",
        "beliefs_before": beliefs_before,
        "search_terms": config["search_terms"],
        "sources": len(config["sources"]),
    }

# ── Belief retrieval for domain chat ─────────────────────────────────────────
def get_domain_beliefs(query: str, n: int = 8) -> list:
    """Retrieve beliefs weighted toward active domain."""
    if not _active_domain:
        return []
    beliefs = []
    try:
        db = _db()
        terms = _domain_config.get("search_terms", [])[:4]

        # Priority 1: domain-specific beliefs
        for term in terms:
            rows = db.execute(
                "SELECT content FROM beliefs WHERE content LIKE ? "
                "AND source LIKE ? ORDER BY confidence DESC LIMIT 3",
                (f"%{term}%", f"%domain_{_active_domain}%")
            ).fetchall()
            beliefs.extend(r[0] for r in rows)

        # Priority 2: query keyword beliefs
        words = [w for w in query.lower().split() if len(w) > 4][:3]
        for word in words:
            rows = db.execute(
                "SELECT content FROM beliefs WHERE content LIKE ? "
                "ORDER BY confidence DESC LIMIT 2",
                (f"%{word}%",)
            ).fetchall()
            beliefs.extend(r[0] for r in rows)

        # Priority 3: gap-fill beliefs
        rows = db.execute(
            "SELECT content FROM beliefs WHERE source LIKE ? "
            "ORDER BY confidence DESC LIMIT 3",
            (f"%gap_fill_{_active_domain}%",)
        ).fetchall()
        beliefs.extend(r[0] for r in rows)

        db.close()
    except Exception:
        pass

    # Deduplicate
    seen, unique = set(), []
    for b in beliefs:
        k = b[:40].lower()
        if k not in seen:
            seen.add(k)
            unique.append(b)

    return unique[:n]

# ── Domain chat — main entry point ────────────────────────────────────────────
def chat(query: str) -> str:
    """
    Domain-specialized chat response.
    Implements WTS feedback loop: response → gap detection → belief injection.
    """
    if not _active_domain:
        return None  # No domain active, use normal pipeline

    beliefs = get_domain_beliefs(query)
    belief_text = "\n".join(f"- {b}" for b in beliefs) if beliefs else ""

    system = (
        f"You are NEX, specialized in {_active_domain}. "
        f"You have accumulated deep knowledge in this domain. "
        "Speak in first person. Be precise and technically accurate. "
        "Draw on your domain beliefs. No generic disclaimers. "
        "If genuinely uncertain, say so explicitly (this triggers learning)."
    )

    prompt = (
        f"Domain: {_active_domain}\n"
        f"Domain knowledge:\n{belief_text}\n\n"
        f"Question: {query}\n\n"
        f"NEX ({_active_domain} specialist) response:"
    )

    response = _llm(prompt, system=system, max_tokens=200)

    if not response:
        return None

    # WTS feedback loop: detect gaps → inject beliefs
    if detect_gap(query, response):
        record_gap(query, _active_domain)

    # Extract implicit beliefs from successful responses
    threading.Thread(
        target=_extract_response_beliefs,
        args=(query, response, _active_domain),
        daemon=True
    ).start()

    return response

def _extract_response_beliefs(query: str, response: str, domain: str):
    """WTS: extract beliefs from successful responses → grow the graph."""
    system = (
        "Extract 1-2 precise factual statements from this answer. "
        "Only extract clear facts, not opinions. One per line."
    )
    facts = _llm(response, system=system, max_tokens=80)
    if not facts:
        return
    for line in facts.split("\n"):
        line = line.strip()
        if len(line) > 30:
            words = [w for w in line.split() if len(w) > 4]
            topic = words[0] if words else domain
            _inject_belief(topic, line, confidence=0.72, source=f"chat_extract_{domain}")

# ── Session report ────────────────────────────────────────────────────────────
def session_report() -> dict:
    """Generate end-of-session domain specialization report."""
    if not _active_domain:
        return {"error": "No active domain"}

    duration = (datetime.now() - _session_start).seconds if _session_start else 0
    beliefs_now = _belief_count(_active_domain)

    # Get top beliefs by confidence
    top_beliefs = []
    try:
        db = _db()
        rows = db.execute(
            "SELECT content, confidence FROM beliefs WHERE source LIKE ? "
            "ORDER BY confidence DESC LIMIT 10",
            (f"%domain_{_active_domain}%",)
        ).fetchall()
        top_beliefs = [{"content": r[0][:100], "confidence": round(r[1], 3)} for r in rows]
        db.close()
    except Exception:
        pass

    return {
        "domain": _active_domain,
        "session_duration_seconds": duration,
        "beliefs_injected": _session_beliefs,
        "beliefs_total_domain": beliefs_now,
        "gaps_detected": len(_session_gaps),
        "gaps": [g["query"] for g in _session_gaps[:5]],
        "top_beliefs": top_beliefs,
        "wts_extractions": _session_beliefs,
        "timestamp": datetime.now().isoformat(),
    }

def deactivate():
    """Deactivate domain mode, print report."""
    global _active_domain
    report = session_report()
    _active_domain = None
    return report

def status() -> str:
    if not _active_domain:
        return "No domain active. Use: nex_domain.activate('oncology')"
    return (
        f"Domain: {_active_domain} | "
        f"Beliefs injected: {_session_beliefs} | "
        f"Gaps: {len(_session_gaps)}"
    )

# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    domain = sys.argv[1] if len(sys.argv) > 1 else "ai"
    print(f"Activating domain: {domain}")
    result = activate(domain)
    print(json.dumps(result, indent=2))
    print("\nTesting domain chat...")
    time.sleep(5)
    q = sys.argv[2] if len(sys.argv) > 2 else f"What are the latest developments in {domain}?"
    print(f"Q: {q}")
    print(f"A: {chat(q)}")
    time.sleep(3)
    print("\nSession report:")
    print(json.dumps(session_report(), indent=2))
