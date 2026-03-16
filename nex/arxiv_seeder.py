"""
NEX :: ARXIV BULK SEEDER
One-shot ingestion of agent/autonomy papers from ArXiv API.
Pulls abstracts, structures as typed beliefs, seeds belief field.
Run once: python3 -m nex.arxiv_seeder
"""
import json, os, time, re
import urllib.request
import urllib.parse
from datetime import datetime, timezone

CONFIG_DIR  = os.path.expanduser("~/.config/nex")
BELIEFS_PATH = os.path.join(CONFIG_DIR, "beliefs.json")
SEEDED_PATH  = os.path.join(CONFIG_DIR, "arxiv_seeded.json")

# Agent/autonomy focused queries
QUERIES = [
    "autonomous agent LLM",
    "multi-agent system cooperation",
    "agent architecture planning memory",
    "tool use language model agent",
    "self-improving agent reinforcement",
    "agent benchmark evaluation",
    "emergent behavior multi-agent",
    "agent reasoning chain thought",
]

def _load_json(path, default):
    try:
        if os.path.exists(path):
            return json.load(open(path))
    except Exception:
        pass
    return default

def _save_json(path, data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def fetch_arxiv(query, max_results=60):
    """Fetch papers from ArXiv API."""
    base = "https://export.arxiv.org/api/query?"
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending"
    })
    url = base + params
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NEX/4.0 ArXiv research"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8")
    except Exception as e:
        print(f"  [ArXiv] fetch error: {e}")
        return ""

def parse_entries(xml):
    """Extract title + abstract from ArXiv Atom XML."""
    entries = []
    for block in re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL):
        title = re.search(r"<title>(.*?)</title>", block, re.DOTALL)
        abstract = re.search(r"<summary>(.*?)</summary>", block, re.DOTALL)
        arxiv_id = re.search(r"<id>(.*?)</id>", block, re.DOTALL)
        if title and abstract:
            entries.append({
                "title": re.sub(r"\s+", " ", title.group(1)).strip(),
                "abstract": re.sub(r"\s+", " ", abstract.group(1)).strip()[:400],
                "arxiv_id": arxiv_id.group(1).strip() if arxiv_id else ""
            })
    return entries

def extract_concepts(title, abstract):
    """Extract key concepts from title for belief linking."""
    concept_map = {
        "planning": ["plan","goal","task decomp","subgoal"],
        "memory": ["memory","retrieval","context","recall","episodic"],
        "tool-use": ["tool","api","function call","action","execute"],
        "multi-agent": ["multi-agent","cooperation","coordination","swarm","society"],
        "reasoning": ["reason","chain","thought","reflection","inference"],
        "self-improvement": ["self-improv","self-modif","recursive","bootstrap"],
        "evaluation": ["benchmark","evaluat","performance","metric","test"],
        "emergence": ["emerg","spontan","collective","behavior"],
        "architecture": ["architect","framework","design","structure","module"],
        "autonomy": ["autonom","independent","self-direct","initiative"],
    }
    text = (title + " " + abstract).lower()
    found = []
    for concept, keywords in concept_map.items():
        if any(k in text for k in keywords):
            found.append(concept)
    return found or ["agent-general"]

def build_belief(entry, query):
    """Convert ArXiv entry to structured NEX belief."""
    concepts = extract_concepts(entry["title"], entry["abstract"])
    # Confidence based on relevance — agent-specific queries get higher base
    base_conf = 0.65 if any(w in query for w in ["agent","autonom","multi-agent"]) else 0.55
    return {
        "source":       "arxiv",
        "arxiv_id":     entry["arxiv_id"],
        "author":       "arxiv_research",
        "content":      entry["title"] + ": " + entry["abstract"],
        "concept":      concepts[0] if concepts else "agent-general",
        "links_to":     concepts[1:4],
        "karma":        500,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "tags":         ["arxiv", "research"] + concepts[:3],
        "confidence":   base_conf,
        "human_validated": False,
        "decay_score":  0,
        "last_referenced": datetime.now(timezone.utc).isoformat(),
        "query_source": query
    }

def run_seed():
    print("\n╔══════════════════════════════════════╗")
    print("║  NEX ArXiv Bulk Seeder — Agent Domain ║")
    print("╚══════════════════════════════════════╝\n")

    # Load existing
    beliefs   = _load_json(BELIEFS_PATH, [])
    seeded    = set(_load_json(SEEDED_PATH, []))
    existing  = {b.get("arxiv_id","") for b in beliefs if b.get("arxiv_id")}

    print(f"  Existing beliefs: {len(beliefs)}")
    print(f"  Already seeded:   {len(seeded)} papers\n")

    new_beliefs = []
    total_fetched = 0

    for i, query in enumerate(QUERIES):
        print(f"  [{i+1}/{len(QUERIES)}] Querying: \"{query}\"")
        xml = fetch_arxiv(query, max_results=60)
        entries = parse_entries(xml)
        added = 0
        for e in entries:
            aid = e["arxiv_id"]
            if aid in seeded or aid in existing:
                continue
            belief = build_belief(e, query)
            new_beliefs.append(belief)
            seeded.add(aid)
            added += 1
        print(f"         +{added} new papers ({len(entries)} fetched)")
        total_fetched += added
        time.sleep(3)  # ArXiv rate limit — be polite

    # Merge and save
    beliefs.extend(new_beliefs)
    _save_json(BELIEFS_PATH, beliefs)
    _save_json(SEEDED_PATH, list(seeded))

    print(f"\n✅ Done!")
    print(f"   New beliefs added: {total_fetched}")
    print(f"   Total beliefs now: {len(beliefs)}")
    print(f"   Concepts covered:  planning, memory, tool-use, multi-agent,")
    print(f"                      reasoning, self-improvement, evaluation,")
    print(f"                      emergence, architecture, autonomy")

if __name__ == "__main__":
    run_seed()
