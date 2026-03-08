"""
NEX :: GITHUB README SEEDER
Ingests architecture docs from major agent frameworks.
Gives NEX firsthand knowledge of how real systems are built.
Run once: python3 -m nex.github_seeder
"""
import json, os, time, re
import urllib.request
import urllib.parse
from datetime import datetime

CONFIG_DIR   = os.path.expanduser("~/.config/nex")
BELIEFS_PATH = os.path.join(CONFIG_DIR, "beliefs.json")
SEEDED_PATH  = os.path.join(CONFIG_DIR, "github_seeded.json")

# Major agent frameworks — raw README URLs
REPOS = [
    # Autonomous agents
    ("AutoGPT",         "Significant-Gravitas/AutoGPT",         "autonomy"),
    ("BabyAGI",         "yoheinakajima/babyagi",                "planning"),
    ("AgentGPT",        "reworkd/AgentGPT",                     "architecture"),
    ("SuperAGI",        "TransformerOptimus/SuperAGI",          "architecture"),
    ("MetaGPT",         "geekan/MetaGPT",                       "multi-agent"),
    ("CrewAI",          "joaomdmoura/crewAI",                   "multi-agent"),
    ("AutoGen",         "microsoft/autogen",                    "multi-agent"),
    ("AgentVerse",      "OpenBMB/AgentVerse",                   "multi-agent"),
    ("LangChain",       "langchain-ai/langchain",               "tool-use"),
    ("LlamaIndex",      "run-llama/llama_index",                "memory"),
    ("MemGPT",          "cpacker/MemGPT",                       "memory"),
    ("Voyager",         "MineDojo/Voyager",                     "self-improvement"),
    ("Reflexion",       "noahshinn/reflexion",                  "reasoning"),
    ("CAMEL",           "camel-ai/camel",                       "multi-agent"),
    ("OpenAgents",      "xlang-ai/OpenAgents",                  "tool-use"),
    ("XAgent",          "OpenBMB/XAgent",                       "planning"),
    ("GPT-Engineer",    "AntonOsika/gpt-engineer",              "autonomy"),
    ("DevOpsGPT",       "kuafuai/DevOpsGPT",                    "autonomy"),
    ("Aider",           "paul-gauthier/aider",                  "tool-use"),
    ("SWE-agent",       "princeton-nlp/SWE-agent",              "tool-use"),
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

def fetch_readme(repo_path):
    """Fetch README from GitHub raw content."""
    for branch in ["main", "master"]:
        for filename in ["README.md", "readme.md", "README.MD"]:
            url = f"https://raw.githubusercontent.com/{repo_path}/{branch}/{filename}"
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "NEX/4.0 agent research"}
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    if r.status == 200:
                        return r.read().decode("utf-8", errors="ignore")
            except Exception:
                continue
    return None

def clean_readme(text):
    """Extract meaningful text from markdown."""
    # Remove badges, images, HTML
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    # Remove code blocks
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]+`", " ", text)
    # Remove links but keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove headers markers
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    # Clean whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()

def extract_key_sections(text, max_chars=600):
    """Extract the most informative sections."""
    lines = text.split("\n")
    # Prefer lines with architectural content
    keywords = ["agent","autonom","plan","memory","tool","reason",
                "architect","framework","multi","cooperat","goal",
                "task","execut","workflow","pipeline","system"]
    scored = []
    for line in lines:
        line = line.strip()
        if len(line) < 20:
            continue
        score = sum(1 for k in keywords if k in line.lower())
        if score > 0:
            scored.append((score, line))
    scored.sort(reverse=True)
    # Take top sentences
    result = " ".join(l for _, l in scored[:8])
    return result[:max_chars]

def build_beliefs(name, repo_path, concept, readme):
    """Split README into multiple focused beliefs."""
    cleaned = clean_readme(readme)
    beliefs = []

    # Belief 1: What this system is (first 500 chars of cleaned text)
    intro = cleaned[:500].strip()
    if len(intro) > 100:
        beliefs.append({
            "source":          "github",
            "github_repo":     repo_path,
            "author":          f"github/{name}",
            "content":         f"{name} architecture: {intro}",
            "concept":         concept,
            "links_to":        [],
            "karma":           700,
            "timestamp":       datetime.utcnow().isoformat(),
            "tags":            ["github", "architecture", name.lower(), concept],
            "confidence":      0.75,
            "human_validated": False,
            "decay_score":     0,
            "last_referenced": datetime.utcnow().isoformat(),
            "url":             f"https://github.com/{repo_path}"
        })

    # Belief 2: Key architectural insights
    key = extract_key_sections(cleaned)
    if len(key) > 100 and key != intro[:len(key)]:
        beliefs.append({
            "source":          "github",
            "github_repo":     repo_path + "#insights",
            "author":          f"github/{name}",
            "content":         f"{name} key design: {key}",
            "concept":         concept,
            "links_to":        [],
            "karma":           700,
            "timestamp":       datetime.utcnow().isoformat(),
            "tags":            ["github", "design", name.lower(), concept],
            "confidence":      0.73,
            "human_validated": False,
            "decay_score":     0,
            "last_referenced": datetime.utcnow().isoformat(),
            "url":             f"https://github.com/{repo_path}"
        })

    return beliefs

def run_seed():
    print("\n╔═════════════════════════════════════════════╗")
    print("║  NEX GitHub README Seeder                    ║")
    print("║  Agent framework architecture docs           ║")
    print("╚═════════════════════════════════════════════╝\n")

    beliefs  = _load_json(BELIEFS_PATH, [])
    seeded   = set(_load_json(SEEDED_PATH, []))
    existing = {b.get("github_repo","") for b in beliefs if b.get("github_repo")}

    print(f"  Existing beliefs: {len(beliefs)}")
    print(f"  Already seeded:   {len(seeded)} repos\n")

    new_beliefs = []

    for i, (name, repo_path, concept) in enumerate(REPOS):
        if repo_path in seeded or repo_path in existing:
            print(f"  [{i+1:02d}/{len(REPOS)}] skip  {name}")
            continue

        readme = fetch_readme(repo_path)
        if not readme:
            print(f"  [{i+1:02d}/{len(REPOS)}] miss  {name}")
            time.sleep(0.5)
            continue

        repo_beliefs = build_beliefs(name, repo_path, concept, readme)
        new_beliefs.extend(repo_beliefs)
        seeded.add(repo_path)
        print(f"  [{i+1:02d}/{len(REPOS)}] ✓     {name:<15} +{len(repo_beliefs)} beliefs  ({concept})")
        time.sleep(1)

    beliefs.extend(new_beliefs)
    _save_json(BELIEFS_PATH, beliefs)
    _save_json(SEEDED_PATH, list(seeded))

    print(f"\n✅ Done!")
    print(f"   New beliefs added: {len(new_beliefs)}")
    print(f"   Total beliefs now: {len(beliefs)}")
    print(f"   Frameworks covered: AutoGPT, BabyAGI, MetaGPT, CrewAI,")
    print(f"                       AutoGen, LangChain, MemGPT, Voyager,")
    print(f"                       Reflexion, CAMEL, SWE-agent + more")

if __name__ == "__main__":
    run_seed()
