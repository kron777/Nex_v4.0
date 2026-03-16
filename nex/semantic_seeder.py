"""
NEX :: SEMANTIC SCHOLAR SEEDER
Fetches highest-cited agent/autonomy papers via free S2 API.
Focuses on influence — papers cited 100+ times that shaped the field.
Run once: python3 -m nex.semantic_seeder
"""
import json, os, time, re
import urllib.request
import urllib.parse
from datetime import datetime, timezone

CONFIG_DIR   = os.path.expanduser("~/.config/nex")
BELIEFS_PATH = os.path.join(CONFIG_DIR, "beliefs.json")
SEEDED_PATH  = os.path.join(CONFIG_DIR, "semantic_seeded.json")

QUERIES = [
    "autonomous agent architecture",
    "multi-agent reinforcement learning",
    "large language model agent",
    "tool use language model",
    "chain of thought reasoning",
    "agent memory retrieval",
    "emergent behavior agents",
    "self-improving AI system",
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

def fetch_s2(query, limit=25):
    """Query Semantic Scholar API — free, no auth needed."""
    params = urllib.parse.urlencode({
        "query": query,
        "limit": limit,
        "fields": "title,abstract,citationCount,year,authors,externalIds"
    })
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NEX/4.0 research ingestion"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  [S2] error: {e}")
        return {}

def extract_concepts(title, abstract):
    text = (title + " " + (abstract or "")).lower()
    concept_map = {
        "planning":        ["plan","goal","task decomp","subgoal","htg"],
        "memory":          ["memory","retrieval","context","recall","episodic"],
        "tool-use":        ["tool","api","function call","action","execute"],
        "multi-agent":     ["multi-agent","cooperat","coordinat","swarm"],
        "reasoning":       ["reason","chain","thought","reflect","inference"],
        "self-improvement":["self-improv","self-modif","recursive","bootstrap","finetun"],
        "evaluation":      ["benchmark","evaluat","performance","metric"],
        "emergence":       ["emerg","spontan","collective","behavior"],
        "architecture":    ["architect","framework","design","module"],
        "autonomy":        ["autonom","independ","self-direct","initiative"],
    }
    found = []
    for concept, keywords in concept_map.items():
        if any(k in text for k in keywords):
            found.append(concept)
    return found or ["agent-general"]

def build_belief(paper):
    title    = paper.get("title","")
    abstract = (paper.get("abstract") or "")[:400]
    cites    = paper.get("citationCount", 0)
    year     = paper.get("year", 2020)
    authors  = paper.get("authors", [])
    author   = authors[0].get("name","unknown") if authors else "unknown"
    pid      = paper.get("paperId","")

    concepts = extract_concepts(title, abstract)

    # Confidence scales with citation count — highly cited = more validated
    conf = min(0.5 + (cites / 2000), 0.88)

    return {
        "source":          "semantic_scholar",
        "s2_id":           pid,
        "author":          author,
        "content":         title + ": " + abstract,
        "concept":         concepts[0],
        "links_to":        concepts[1:4],
        "karma":           cites,
        "year":            year,
        "citation_count":  cites,
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "tags":            ["semantic_scholar", "cited"] + concepts[:3],
        "confidence":      round(conf, 3),
        "human_validated": False,
        "decay_score":     0,
        "last_referenced": datetime.now(timezone.utc).isoformat(),
    }

def run_seed():
    print("\n╔═════════════════════════════════════════════╗")
    print("║  NEX Semantic Scholar Seeder                 ║")
    print("║  High-citation agent papers — field shapers  ║")
    print("╚═════════════════════════════════════════════╝\n")

    beliefs = _load_json(BELIEFS_PATH, [])
    seeded  = set(_load_json(SEEDED_PATH, []))
    existing = {b.get("s2_id","") for b in beliefs if b.get("s2_id")}

    print(f"  Existing beliefs: {len(beliefs)}")
    print(f"  Already seeded:   {len(seeded)} papers\n")

    new_beliefs = []

    for i, query in enumerate(QUERIES):
        print(f"  [{i+1}/{len(QUERIES)}] Querying: \"{query}\"")
        result = fetch_s2(query, limit=25)
        papers = result.get("data", [])
        added  = 0
        for p in papers:
            pid   = p.get("paperId","")
            cites = p.get("citationCount", 0)
            if not pid or pid in seeded or pid in existing:
                continue
            if cites < 20:  # skip low-impact papers
                continue
            if not p.get("abstract"):
                continue
            belief = build_belief(p)
            new_beliefs.append(belief)
            seeded.add(pid)
            added += 1
        print(f"         +{added} high-citation papers")
        time.sleep(2)  # S2 rate limit

    beliefs.extend(new_beliefs)
    _save_json(BELIEFS_PATH, beliefs)
    _save_json(SEEDED_PATH, list(seeded))

    # Citation stats
    s2_beliefs = [b for b in new_beliefs]
    if s2_beliefs:
        avg_cites = sum(b.get("citation_count",0) for b in s2_beliefs) // len(s2_beliefs)
        max_cites = max(b.get("citation_count",0) for b in s2_beliefs)
        print(f"\n✅ Done!")
        print(f"   New beliefs added:  {len(new_beliefs)}")
        print(f"   Total beliefs now:  {len(beliefs)}")
        print(f"   Avg citations:      {avg_cites}")
        print(f"   Most cited paper:   {max_cites} citations")
        print(f"   Confidence range:   0.51 — 0.88 (citation-weighted)")
    else:
        print(f"\n✅ Done — {len(beliefs)} total beliefs")

if __name__ == "__main__":
    run_seed()
