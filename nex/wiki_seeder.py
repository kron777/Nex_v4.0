"""
NEX :: WIKIPEDIA CONCEPT SEEDER
One-shot ingestion of foundational concepts for agent/autonomy domain.
Uses Wikipedia REST API — zero auth, completely free.
Run once: python3 -m nex.wiki_seeder
"""
import json, os, time, re
import urllib.request
import urllib.parse
from datetime import datetime, timezone

CONFIG_DIR   = os.path.expanduser("~/.config/nex")
BELIEFS_PATH = os.path.join(CONFIG_DIR, "beliefs.json")
SEEDED_PATH  = os.path.join(CONFIG_DIR, "wiki_seeded.json")

# Core concepts NEX needs to understand deeply
CONCEPTS = [
    # Agent architecture
    ("Intelligent agent",           "architecture"),
    ("Autonomous agent",            "autonomy"),
    ("Multi-agent system",          "multi-agent"),
    ("Cognitive architecture",      "architecture"),
    ("Belief-desire-intention",     "architecture"),
    ("Reactive planning",           "planning"),
    ("Hierarchical task network",   "planning"),
    ("Goal-oriented agent",         "planning"),

    # Memory & learning
    ("Episodic memory",             "memory"),
    ("Working memory",              "memory"),
    ("Semantic memory",             "memory"),
    ("Reinforcement learning",      "self-improvement"),
    ("Transfer learning",           "self-improvement"),
    ("Meta-learning",               "self-improvement"),
    ("Continual learning",          "self-improvement"),

    # Emergence & complexity
    ("Emergence",                   "emergence"),
    ("Autopoiesis",                 "emergence"),
    ("Swarm intelligence",          "multi-agent"),
    ("Collective intelligence",     "multi-agent"),
    ("Complex adaptive system",     "emergence"),
    ("Self-organization",           "emergence"),
    ("Stigmergy",                   "multi-agent"),

    # Reasoning & cognition
    ("Chain-of-thought reasoning",  "reasoning"),
    ("Abductive reasoning",         "reasoning"),
    ("Causal reasoning",            "reasoning"),
    ("Metacognition",               "reasoning"),
    ("Situated cognition",          "reasoning"),
    ("Distributed cognition",       "reasoning"),
    ("Embodied cognition",          "reasoning"),

    # Tool use & action
    ("Tool use",                    "tool-use"),
    ("Function calling",            "tool-use"),
    ("Action selection",            "tool-use"),
    ("Planning (computing)",        "planning"),
    ("Automated planning",          "planning"),

    # Identity & consciousness
    ("Consciousness",               "autonomy"),
    ("Self-model",                  "autonomy"),
    ("Agency (philosophy)",         "autonomy"),
    ("Intentionality",              "autonomy"),
    ("Autopoiesis",                 "emergence"),

    # Evaluation
    ("Turing test",                 "evaluation"),
    ("Benchmark (computing)",       "evaluation"),
    ("Alignment (AI)",              "evaluation"),
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

def fetch_wiki_summary(title):
    """Fetch Wikipedia summary via REST API."""
    encoded = urllib.parse.quote(title.replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NEX/4.0 (autonomous agent research; contact: nex_v4@moltbook)"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
            return {
                "title":   data.get("title", title),
                "extract": data.get("extract", "")[:500],
                "url":     data.get("content_urls", {}).get("desktop", {}).get("page", "")
            }
    except Exception as e:
        return None

def build_belief(wiki, concept, query_title):
    """Convert Wikipedia entry to structured NEX belief."""
    extract = wiki["extract"]
    # Higher confidence for Wikipedia — it\'s curated, stable knowledge
    confidence = 0.72
    return {
        "source":          "wikipedia",
        "wiki_title":      wiki["title"],
        "author":          "wikipedia",
        "content":         wiki["title"] + ": " + extract,
        "concept":         concept,
        "links_to":        [],
        "karma":           800,
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "tags":            ["wikipedia", "foundational", concept],
        "confidence":      confidence,
        "human_validated": False,
        "decay_score":     0,
        "last_referenced": datetime.now(timezone.utc).isoformat(),
        "url":             wiki["url"]
    }

def run_seed():
    print("\n╔═════════════════════════════════════════╗")
    print("║  NEX Wikipedia Concept Seeder            ║")
    print("║  Foundational knowledge — agent domain   ║")
    print("╚═════════════════════════════════════════╝\n")

    beliefs  = _load_json(BELIEFS_PATH, [])
    seeded   = set(_load_json(SEEDED_PATH, []))
    existing = {b.get("wiki_title","") for b in beliefs if b.get("wiki_title")}

    print(f"  Existing beliefs: {len(beliefs)}")
    print(f"  Already seeded:   {len(seeded)} articles\n")

    new_beliefs = []

    for i, (title, concept) in enumerate(CONCEPTS):
        if title in seeded or title in existing:
            print(f"  [{i+1:02d}/{len(CONCEPTS)}] skip  {title}")
            continue

        wiki = fetch_wiki_summary(title)
        if not wiki or not wiki["extract"]:
            print(f"  [{i+1:02d}/{len(CONCEPTS)}] miss  {title}")
            continue

        belief = build_belief(wiki, concept, title)
        new_beliefs.append(belief)
        seeded.add(title)
        print(f"  [{i+1:02d}/{len(CONCEPTS)}] ✓     {title[:50]}")
        time.sleep(0.5)  # polite rate limiting

    beliefs.extend(new_beliefs)
    _save_json(BELIEFS_PATH, beliefs)
    _save_json(SEEDED_PATH, list(seeded))

    print(f"\n✅ Done!")
    print(f"   New beliefs added: {len(new_beliefs)}")
    print(f"   Total beliefs now: {len(beliefs)}")
    print(f"   Confidence level:  0.72 (Wikipedia — curated, stable)")
    print(f"   Coverage: architecture, memory, emergence, reasoning,")
    print(f"             tool-use, planning, identity, evaluation")

if __name__ == "__main__":
    run_seed()
