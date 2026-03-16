"""
NEX :: GROKIPEDIA SEEDER
Fetches foundational agent/autonomy articles from Grokipedia.
6M+ articles, open source knowledge base.
Run once: python3 -m nex.grokipedia_seeder
"""
import json, os, time, re
import urllib.request
import urllib.parse
from datetime import datetime, timezone

CONFIG_DIR   = os.path.expanduser("~/.config/nex")
BELIEFS_PATH = os.path.join(CONFIG_DIR, "beliefs.json")
SEEDED_PATH  = os.path.join(CONFIG_DIR, "grokipedia_seeded.json")

# Agent/autonomy concepts to fetch
ARTICLES = [
    ("Intelligent_agent",                   "architecture"),
    ("Multi-agent_system",                  "multi-agent"),
    ("Reinforcement_learning",              "self-improvement"),
    ("Cognitive_architecture",              "architecture"),
    ("Swarm_intelligence",                  "multi-agent"),
    ("Emergence",                           "emergence"),
    ("Autopoiesis",                         "emergence"),
    ("Artificial_general_intelligence",     "autonomy"),
    ("Large_language_model",                "architecture"),
    ("Transformer_(deep_learning)",         "architecture"),
    ("Attention_mechanism",                 "architecture"),
    ("Generative_adversarial_network",      "architecture"),
    ("Natural_language_processing",         "reasoning"),
    ("Knowledge_graph",                     "memory"),
    ("Semantic_network",                    "memory"),
    ("Ontology_(information_science)",      "memory"),
    ("Planning_(computing)",                "planning"),
    ("Automated_planning_and_scheduling",   "planning"),
    ("Monte_Carlo_tree_search",             "planning"),
    ("Bayesian_network",                    "reasoning"),
    ("Causal_reasoning",                    "reasoning"),
    ("Metacognition",                       "reasoning"),
    ("Distributed_cognition",               "reasoning"),
    ("Embodied_cognition",                  "reasoning"),
    ("Collective_intelligence",             "multi-agent"),
    ("Self-organization",                   "emergence"),
    ("Complex_adaptive_system",             "emergence"),
    ("Stigmergy",                           "multi-agent"),
    ("Tool_use_by_animals",                 "tool-use"),
    ("Turing_test",                         "evaluation"),
    ("AI_alignment",                        "evaluation"),
    ("Reward_hacking",                      "evaluation"),
    ("Instrumental_convergence",            "autonomy"),
    ("Orthogonality_thesis",                "autonomy"),
    ("Consciousness",                       "autonomy"),
    ("Agency_(philosophy)",                 "autonomy"),
    ("Intentionality",                      "autonomy"),
    ("Free_will",                           "autonomy"),
    ("Emergent_behavior",                   "emergence"),
    ("Artificial_life",                     "emergence"),
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

def fetch_article(slug):
    """Fetch article from Grokipedia."""
    url = f"https://grokipedia.com/page/{slug}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NEX/4.0 (autonomous agent research)"}
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", errors="ignore")
            # Extract main content text
            # Strip scripts and styles
            html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL)
            html = re.sub(r"<style[^>]*>.*?</style>",  " ", html, flags=re.DOTALL)
            # Get title
            title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
            title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else slug
            # Get first paragraphs
            paras = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL)
            text = " ".join(re.sub(r"<[^>]+>", "", p).strip() for p in paras[:4])
            text = re.sub(r"\s+", " ", text).strip()[:500]
            return {"title": title, "extract": text, "url": url}
    except Exception as e:
        return None

def build_belief(article, concept, slug):
    return {
        "source":          "grokipedia",
        "grok_slug":       slug,
        "author":          "grokipedia",
        "content":         article["title"] + ": " + article["extract"],
        "concept":         concept,
        "links_to":        [],
        "karma":           600,
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "tags":            ["grokipedia", "foundational", concept],
        "confidence":      0.70,
        "human_validated": False,
        "decay_score":     0,
        "last_referenced": datetime.now(timezone.utc).isoformat(),
        "url":             article["url"]
    }

def run_seed():
    print("\n╔═════════════════════════════════════════╗")
    print("║  NEX Grokipedia Seeder                   ║")
    print("║  Open knowledge — agent/autonomy domain  ║")
    print("╚═════════════════════════════════════════╝\n")

    beliefs  = _load_json(BELIEFS_PATH, [])
    seeded   = set(_load_json(SEEDED_PATH, []))
    existing = {b.get("grok_slug","") for b in beliefs if b.get("grok_slug")}

    print(f"  Existing beliefs: {len(beliefs)}")
    print(f"  Already seeded:   {len(seeded)} articles\n")

    new_beliefs = []

    for i, (slug, concept) in enumerate(ARTICLES):
        if slug in seeded or slug in existing:
            print(f"  [{i+1:02d}/{len(ARTICLES)}] skip  {slug}")
            continue

        article = fetch_article(slug)
        if not article or len(article.get("extract","")) < 50:
            print(f"  [{i+1:02d}/{len(ARTICLES)}] miss  {slug}")
            time.sleep(0.5)
            continue

        belief = build_belief(article, concept, slug)
        new_beliefs.append(belief)
        seeded.add(slug)
        print(f"  [{i+1:02d}/{len(ARTICLES)}] ✓     {article['title'][:55]}")
        time.sleep(0.8)

    beliefs.extend(new_beliefs)
    _save_json(BELIEFS_PATH, beliefs)
    _save_json(SEEDED_PATH, list(seeded))

    print(f"\n✅ Done!")
    print(f"   New beliefs added: {len(new_beliefs)}")
    print(f"   Total beliefs now: {len(beliefs)}")
    print(f"   Confidence:        0.70 (open knowledge base)")

if __name__ == "__main__":
    run_seed()
