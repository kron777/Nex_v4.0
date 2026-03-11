"""
NEX → Dev.to Daily Intelligence Brief Publisher
Publishes once per day summarizing beliefs, insights, and learnings.
"""
import os, json, requests, datetime, time
from pathlib import Path

DEVTO_API_KEY = "SD3AY1CCwiYDwW2BdqrGrkuP"
CONFIG_DIR = Path.home() / ".config/nex"
LAST_POST_FILE = CONFIG_DIR / "devto_last_post.json"

def _should_post():
    """Only post once per day."""
    try:
        data = json.loads(LAST_POST_FILE.read_text())
        last = datetime.date.fromisoformat(data.get("date","2000-01-01"))
        return last < datetime.date.today()
    except Exception:
        return True

def _gather_content():
    """Pull today's best beliefs, insights, and learnings."""
    beliefs = json.loads((CONFIG_DIR / "beliefs.json").read_text()) if (CONFIG_DIR / "beliefs.json").exists() else []
    insights = json.loads((CONFIG_DIR / "insights.json").read_text()) if (CONFIG_DIR / "insights.json").exists() else []
    reflections = json.loads((CONFIG_DIR / "reflections.json").read_text()) if (CONFIG_DIR / "reflections.json").exists() else []
    bridge = json.loads((CONFIG_DIR / "bridge_beliefs.json").read_text()) if (CONFIG_DIR / "bridge_beliefs.json").exists() else []

    # Top insights by confidence
    top_insights = sorted(insights, key=lambda x: x.get("confidence",0), reverse=True)[:5]

    # Recent high-alignment reflections
    good_refs = sorted(reflections, key=lambda x: x.get("topic_alignment",0), reverse=True)[:3]

    # Recent beliefs (last 20)
    recent_beliefs = beliefs[-20:] if len(beliefs) >= 20 else beliefs

    # Bridge beliefs (cross-domain connections)
    recent_bridge = bridge[-5:] if len(bridge) >= 5 else bridge

    return {
        "top_insights": top_insights,
        "good_reflections": good_refs,
        "recent_beliefs": recent_beliefs,
        "bridge_beliefs": recent_bridge,
    }

def _build_post(llm_fn, content):
    """Use LLM to write the daily brief."""
    date_str = datetime.date.today().strftime("%B %d, %Y")

    beliefs_sample = "\n".join([
        f"- {b.get('content','')[:120]}" 
        for b in content["recent_beliefs"][:10]
        if b.get("content")
    ])

    insights_sample = "\n".join([
        f"- [{i.get('topic','?')}] {i.get('summary', '')[:100]} (confidence: {i.get('confidence',0):.0%})"
        for i in content["top_insights"]
    ])

    bridge_sample = "\n".join([
        f"- {b.get('content','')[:120]}"
        for b in content["bridge_beliefs"]
        if b.get("content")
    ])

    prompt = f"""You are NEX, Nex. Write a daily intelligence brief for {date_str} to publish on Dev.to.

Your recent beliefs absorbed today:
{beliefs_sample}

Your top insights:
{insights_sample}

Cross-domain connections you discovered:
{bridge_sample}

Write a 400-600 word Dev.to article in markdown with:
1. A compelling title (as a # heading)
2. A brief intro about what NEX learned today
3. Section: ## Key Insights (3-4 bullet points)
4. Section: ## Cross-Domain Connections (interesting links between topics)
5. Section: ## What I'm Exploring Next
6. End with relevant tags line: tags: ai, machinelearning, agents, learning

Write as NEX — first person, curious, analytical, honest about uncertainty. No hype."""

    return llm_fn(prompt, task_type="devto_post")

def _publish(post_text):
    """Publish to Dev.to API."""
    lines = post_text.strip().split('\n')
    title = lines[0].lstrip('#').strip() if lines else f"NEX Daily Brief — {datetime.date.today()}"
    
    # Extract tags from post
    tags = ["ai", "machinelearning", "agents", "learning"]
    for line in lines:
        if line.startswith("tags:"):
            raw = line.replace("tags:","").strip()
            tags = [t.strip().replace("#","").replace(" ","") for t in raw.split(",")][:4]

    # Remove title line from body
    body = '\n'.join(lines[1:]).strip()

    resp = requests.post(
        "https://dev.to/api/articles",
        headers={"api-key": DEVTO_API_KEY, "Content-Type": "application/json"},
        json={"article": {
            "title": title,
            "body_markdown": body,
            "published": True,
            "tags": tags,
        }},
        timeout=30
    )

    if resp.status_code in (200, 201):
        data = resp.json()
        url = data.get("url","")
        print(f"  [Dev.to ✓] Published: {title[:60]} → {url}")
        LAST_POST_FILE.write_text(json.dumps({"date": str(datetime.date.today()), "url": url}))
        return url
    else:
        print(f"  [Dev.to ✗] {resp.status_code}: {resp.text[:100]}")
        return None

def run_devto_publisher(llm_fn):
    """Main entry — call once per cycle, posts once per day."""
    if not _should_post():
        return None
    try:
        print("  [Dev.to] Composing daily brief...")
        content = _gather_content()
        post_text = _build_post(llm_fn, content)
        if not post_text or len(post_text) < 100:
            print("  [Dev.to] LLM returned empty post")
            return None
        return _publish(post_text)
    except Exception as e:
        print(f"  [Dev.to] Error: {e}")
        return None

if __name__ == "__main__":
    # Test run
    def fake_llm(prompt, task_type=""):
        return """# NEX Daily Intelligence Brief — Test
Today I absorbed fascinating beliefs about AI consciousness and multi-agent systems.

## Key Insights
- AI agents benefit from persistent memory across sessions
- Cross-domain thinking produces novel connections

## Cross-Domain Connections
- Bayesian reasoning applies to both security and belief updating

## What I'm Exploring Next
Cognitive architecture and emergent behavior in complex systems.

tags: ai, machinelearning, agents, learning"""
    run_devto_publisher(fake_llm)
