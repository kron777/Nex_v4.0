#!/usr/bin/env python3
"""
nex_arxiv_seeder.py — PubMed Medical Domain Seeder v2
======================================================
Pulls abstracts from PubMed E-utilities (free, no API key required).
arXiv is blocked by egress proxy — PubMed is confirmed reachable.

Target domains : oncology, cardiology, neuroscience
Source weight  : "pubmed" = 1.0 in quality scorer (same as arxiv)
Fresh score    : ~0.59 per belief
Elite after    : ~10 reinforcements → 0.71+

PubMed API:
  Step 1: esearch  → get PMIDs for a query
  Step 2: efetch   → pull abstracts for those PMIDs (XML)
  Rate limit: 3 req/s without key (add NCBI_API_KEY env var for 10/s)
  Docs: https://www.ncbi.nlm.nih.gov/books/NBK25499/

Usage:
  python3 nex_arxiv_seeder.py              # seed all three domains
  python3 nex_arxiv_seeder.py --dry        # show what would be injected
  python3 nex_arxiv_seeder.py --domain cardiology
  python3 nex_arxiv_seeder.py --status     # show current domain counts
  python3 nex_arxiv_seeder.py --test       # test PubMed connectivity
"""

import os, sqlite3, time, sys, re, json
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone

DB_PATH  = Path("~/.config/nex/nex.db").expanduser()
LOG_PATH = Path("/tmp/nex_arxiv_seeder.log")

# PubMed E-utilities base URLs
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# Optional: set NCBI_API_KEY env var to get 10 req/s instead of 3 req/s
NCBI_API_KEY    = os.environ.get("NCBI_API_KEY", "")
RATE_LIMIT_SLEEP = 0.4 if NCBI_API_KEY else 1.0   # conservative
FETCH_TIMEOUT   = 30    # seconds per request
RESULTS_PER_QUERY = 20  # PMIDs to fetch per search
MIN_ABSTRACT_LEN  = 60
MAX_BELIEF_LEN    = 400
TARGET_PER_DOMAIN = 200

# ── PubMed search terms per domain ───────────────────────────────────────────
DOMAIN_QUERIES = {
    "oncology": [
        "cancer immunotherapy mechanism",
        "tumor suppressor gene mutation",
        "chemotherapy drug resistance",
        "cancer cell proliferation apoptosis",
        "checkpoint inhibitor PD-1 PDL1",
        "metastasis invasion signaling",
        "CRISPR cancer gene therapy",
        "liquid biopsy cancer diagnosis",
        "CAR T cell therapy tumor",
        "oncogene driver mutation",
    ],
    "cardiology": [
        "cardiac physiology contraction mechanism",
        "heart failure pathophysiology treatment",
        "atrial fibrillation arrhythmia mechanism",
        "myocardial infarction biomarker diagnosis",
        "atherosclerosis plaque formation",
        "hypertension cardiovascular risk",
        "cardiac remodeling ventricular",
        "coronary artery disease intervention",
        "heart failure ejection fraction",
        "cardiac biomarker troponin BNP",
    ],
    "neuroscience": [
        "synaptic plasticity LTP mechanism",
        "Alzheimer neurodegeneration pathology",
        "dopamine reward circuit neurotransmitter",
        "hippocampus memory consolidation",
        "neural circuit information processing",
        "glial cell astrocyte neuroinflammation",
        "Parkinson disease alpha synuclein",
        "prefrontal cortex executive function",
        "neuroplasticity learning synapse",
        "brain imaging functional connectivity",
    ],
}

# PubMed MeSH term filters per domain (improves precision)
DOMAIN_MESH = {
    "oncology":     "Neoplasms[MeSH]",
    "cardiology":   "Cardiovascular Diseases[MeSH]",
    "neuroscience": "Nervous System[MeSH]",
}


# ── Logging ───────────────────────────────────────────────────────────────────
def _log(msg: str):
    ts   = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"{ts} [pubmed] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── DB helpers ────────────────────────────────────────────────────────────────
def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

def _domain_count(domain: str) -> int:
    try:
        conn = _db()
        n    = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE topic=?", (domain,)
        ).fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0

def _load_existing_fingerprints(domain: str) -> set:
    """First 60 chars of existing beliefs for fast dedup."""
    try:
        conn = _db()
        rows = conn.execute(
            "SELECT content FROM beliefs WHERE topic=?", (domain,)
        ).fetchall()
        conn.close()
        return {(r[0] or "")[:60].lower().strip() for r in rows}
    except Exception:
        return set()

def _insert_belief(topic: str, content: str, confidence: float, source: str) -> bool:
    """Insert one belief. Returns True if inserted, False if duplicate/error."""
    content = content.strip()
    if not content or len(content) < 20:
        return False
    try:
        conn   = _db()
        exists = conn.execute(
            "SELECT 1 FROM beliefs WHERE content=? LIMIT 1", (content,)
        ).fetchone()
        if exists:
            conn.close()
            return False
        conn.execute(
            "INSERT OR IGNORE INTO beliefs (topic, content, confidence, source) VALUES (?,?,?,?)",
            (topic, content[:800], round(float(confidence), 4), source)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        _log(f"Insert error: {e}")
        return False


# ── PubMed API ────────────────────────────────────────────────────────────────
def _build_params(**kwargs) -> str:
    params = {**kwargs}
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return urllib.parse.urlencode(params)

def _get(url: str, params: str) -> str:
    """HTTP GET with retries."""
    full_url = f"{url}?{params}"
    headers  = {"User-Agent": "NEX/4.0 (research; mailto:zenlightbulb@gmail.com)"}
    for attempt in range(3):
        try:
            req  = urllib.request.Request(full_url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=FETCH_TIMEOUT)
            return resp.read().decode("utf-8")
        except Exception as e:
            if attempt < 2:
                _log(f"Retry {attempt+1}/3: {e}")
                time.sleep(3)
            else:
                raise
    return ""

def _esearch(query: str, domain: str, retmax: int = RESULTS_PER_QUERY) -> list:
    """Search PubMed. Returns list of PMIDs."""
    mesh   = DOMAIN_MESH.get(domain, "")
    term   = f'({query}) AND {mesh} AND hasabstract[text]' if mesh else f'({query}) AND hasabstract[text]'
    params = _build_params(
        db="pubmed", term=term, retmax=retmax,
        retmode="json", sort="relevance"
    )
    try:
        raw  = _get(ESEARCH_URL, params)
        data = json.loads(raw)
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        _log(f"esearch error for '{query}': {e}")
        return []

def _efetch_abstracts(pmids: list) -> list:
    """
    Fetch full records for a list of PMIDs.
    Returns list of dicts: {pmid, title, abstract}
    """
    if not pmids:
        return []
    params = _build_params(
        db="pubmed",
        id=",".join(pmids),
        retmode="xml",
        rettype="abstract"
    )
    try:
        raw  = _get(EFETCH_URL, params)
        root = ET.fromstring(raw)
    except Exception as e:
        _log(f"efetch error: {e}")
        return []

    results = []
    for article in root.findall(".//PubmedArticle"):
        try:
            pmid_el  = article.find(".//PMID")
            title_el = article.find(".//ArticleTitle")
            abs_els  = article.findall(".//AbstractText")

            pmid  = pmid_el.text if pmid_el is not None else ""
            title = "".join(title_el.itertext()) if title_el is not None else ""

            # AbstractText can have multiple sections (background, methods, results, conclusions)
            # Prefer "CONCLUSIONS" or "RESULTS" section, else join all
            abstract = ""
            for el in abs_els:
                label = (el.get("Label") or "").upper()
                text  = "".join(el.itertext()).strip()
                if label in ("CONCLUSIONS", "CONCLUSION", "RESULTS", "FINDINGS"):
                    abstract = text
                    break
            if not abstract:
                abstract = " ".join("".join(el.itertext()).strip() for el in abs_els)

            abstract = re.sub(r'\s+', ' ', abstract).strip()
            title    = re.sub(r'\s+', ' ', title).strip()

            if abstract and len(abstract) >= MIN_ABSTRACT_LEN:
                results.append({"pmid": pmid, "title": title, "abstract": abstract})
        except Exception:
            continue

    return results

def _abstract_to_belief(title: str, abstract: str) -> tuple:
    """
    Convert a PubMed abstract into a belief statement + confidence.
    Returns (content, confidence).
    """
    # Strip common academic phrasing from the start
    abstract = re.sub(
        r'^(We |This study |This paper |Here,?\s*we |In this (study|paper|work|report),?\s*)',
        '', abstract, flags=re.IGNORECASE
    ).strip()

    # Capitalise first letter after strip
    if abstract:
        abstract = abstract[0].upper() + abstract[1:]

    # Take first 1-2 sentences, cap length
    sentences = re.split(r'(?<=[.!?])\s+', abstract)
    content   = sentences[0].strip()
    if len(content) < 80 and len(sentences) > 1:
        content = content.rstrip('.') + '. ' + sentences[1].strip()
    content = content[:MAX_BELIEF_LEN].strip()

    # Confidence based on evidence signals
    text_lower = abstract.lower()
    if any(kw in text_lower for kw in
           ["randomized controlled trial", "meta-analysis", "systematic review",
            "phase 3", "phase iii", "clinical trial"]):
        conf = 0.92
    elif any(kw in text_lower for kw in
             ["demonstrated", "confirmed", "established", "significantly"]):
        conf = 0.87
    elif any(kw in text_lower for kw in
             ["suggest", "propose", "may", "could", "might", "appear"]):
        conf = 0.79
    else:
        conf = 0.83  # PubMed default — peer reviewed

    return content, conf


# ── Domain seeding ────────────────────────────────────────────────────────────
def seed_domain(domain: str, target: int = TARGET_PER_DOMAIN,
                dry_run: bool = False) -> dict:
    current  = _domain_count(domain)
    needed   = max(0, target - current)

    if needed == 0:
        _log(f"Domain '{domain}' already at target ({current}/{target})")
        return {"domain": domain, "injected": 0, "skipped": 0, "already_done": True}

    _log(f"Seeding '{domain}': {current} → {target} ({needed} needed)")

    queries    = DOMAIN_QUERIES.get(domain, [])
    existing   = _load_existing_fingerprints(domain)
    injected   = 0
    skipped    = 0
    query_idx  = 0

    while injected < needed and query_idx < len(queries) * 4:
        query = queries[query_idx % len(queries)]
        query_idx += 1

        # Step 1: get PMIDs
        pmids = _esearch(query, domain, retmax=RESULTS_PER_QUERY)
        time.sleep(RATE_LIMIT_SLEEP)

        if not pmids:
            continue

        # Step 2: fetch abstracts
        articles = _efetch_abstracts(pmids)
        time.sleep(RATE_LIMIT_SLEEP)

        for art in articles:
            if injected >= needed:
                break

            content, conf = _abstract_to_belief(art["title"], art["abstract"])

            if len(content) < MIN_ABSTRACT_LEN:
                skipped += 1
                continue

            # Dedup by fingerprint
            fp = content[:60].lower().strip()
            if fp in existing:
                skipped += 1
                continue

            source = f"pubmed:{art['pmid']}" if art.get("pmid") else "pubmed"

            if dry_run:
                _log(f"  [DRY] {domain}: {content[:90]}...")
                injected += 1
                existing.add(fp)
            else:
                ok = _insert_belief(domain, content, conf, source)
                if ok:
                    injected += 1
                    existing.add(fp)
                    if injected % 10 == 0:
                        _log(f"  [{domain}] {injected}/{needed} injected")
                else:
                    skipped += 1

    _log(f"Domain '{domain}' complete: +{injected} injected, {skipped} skipped")
    return {"domain": domain, "injected": injected, "skipped": skipped, "already_done": False}


def seed_all(target: int = TARGET_PER_DOMAIN, dry_run: bool = False,
             domains: list = None) -> dict:
    if domains is None:
        domains = list(DOMAIN_QUERIES.keys())

    counts  = {d: _domain_count(d) for d in domains}
    pending = sorted(
        [d for d in domains if counts[d] < target],
        key=lambda d: counts[d]
    )

    if not pending:
        _log("All domains at target — nothing to seed")
        return {"seeded": 0, "domains": {}}

    _log(f"PubMed seed run — order: {[(d, counts[d]) for d in pending]}")

    results        = {}
    total_injected = 0
    start          = time.time()

    for domain in pending:
        r = seed_domain(domain, target=target, dry_run=dry_run)
        results[domain]  = r
        total_injected  += r["injected"]

    elapsed = round(time.time() - start, 1)
    _log(f"Seed run complete: +{total_injected} beliefs in {elapsed}s")

    return {
        "total_injected": total_injected,
        "elapsed_s":      elapsed,
        "dry_run":        dry_run,
        "domains":        results,
    }


def scheduler_hook(domains: list = None) -> dict:
    return seed_all(dry_run=False, domains=domains)


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NEX PubMed Medical Domain Seeder")
    parser.add_argument("--dry",    action="store_true")
    parser.add_argument("--domain", default=None, choices=list(DOMAIN_QUERIES.keys()))
    parser.add_argument("--count",  type=int, default=TARGET_PER_DOMAIN)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--test",   action="store_true", help="Test PubMed connectivity")
    args = parser.parse_args()

    if args.test:
        print("Testing PubMed connectivity...")
        pmids = _esearch("cardiac physiology", "cardiology", retmax=3)
        if pmids:
            print(f"  esearch OK — got PMIDs: {pmids}")
            arts = _efetch_abstracts(pmids[:2])
            for a in arts:
                content, conf = _abstract_to_belief(a["title"], a["abstract"])
                print(f"  efetch OK — PMID {a['pmid']}")
                print(f"  Content ({len(content)} chars, conf={conf}):")
                print(f"    {content[:120]}...")
        else:
            print("  FAILED — no PMIDs returned")
        sys.exit(0)

    if args.status:
        print("\n  PubMed Seeder — Domain Status")
        print(f"  {'Domain':<16} {'Count':>6}  {'Gap':>6}  Status")
        print(f"  {'─'*45}")
        for d in DOMAIN_QUERIES:
            c   = _domain_count(d)
            gap = max(0, TARGET_PER_DOMAIN - c)
            status = "✓ DONE" if c >= TARGET_PER_DOMAIN else f"need {gap}"
            print(f"  {d:<16} {c:>6}  {gap:>6}  {status}")
        sys.exit(0)

    if args.domain:
        r = seed_domain(args.domain, target=args.count, dry_run=args.dry)
        print(json.dumps(r, indent=2))
    else:
        r = seed_all(target=args.count, dry_run=args.dry)
        print(json.dumps(r, indent=2))
