"""
NEX → Dev.to Daily Intelligence Brief Publisher
Publishes once per day summarizing beliefs, insights, and learnings.
"""
import os, json, requests, datetime, time
from pathlib import Path


def _trunc_title(t, n=125):
    """Dev.to rejects titles over 128 chars."""
    if not t:
        return t
    t = str(t).strip()
    return t[:n] + ('...' if len(t) > n else '')


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
    # V4.0 — pull from live SQLite DB
    import sqlite3 as _sq
    _db = _sq.connect(str(Path.home() / "Desktop/nex/nex.db"))
    beliefs = [{"content": r[0], "topic": r[1], "confidence": r[2]}
               for r in _db.execute(
                   "SELECT content, topic, confidence FROM beliefs "
                   "WHERE confidence >= 0.75 ORDER BY RANDOM() LIMIT 50"
               ).fetchall()]
    insights = []
    reflections = []
    bridge = [{"content": r[0]}
              for r in _db.execute(
                  "SELECT b.content FROM belief_relations r "
                  "JOIN beliefs b ON r.target_id = b.id "
                  "WHERE r.relation_type = 'bridges' "
                  "ORDER BY r.weight DESC LIMIT 10"
              ).fetchall()]
    _db.close()

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

def _symbolic_draft(content) -> str:
    """
    LoadShare: build post draft symbolically from belief content.
    No LLM needed — pure template + data assembly.
    LLM only polishes the final draft.
    """
    import re
    date_str = datetime.date.today().strftime("%B %d, %Y")

    def clean(text):
        text = re.sub(r'\[compressed:\d+\]\s*', '', text)
        text = re.sub(r'TYPE:\s*(NONE|CONTEXTUAL)[^.]*\.?\s*', '', text)
        text = re.sub(r'@\w+\s*\(κ\d+,\s*conf:[0-9.]+\):\s*', '', text)
        return text.strip()

    # Build key insights from top insights
    insights = []
    for i in content["top_insights"][:4]:
        topic = i.get("topic", "general")
        summary = clean(i.get("summary", i.get("content", ""))[:120])
        conf = i.get("confidence", 0)
        if summary:
            insights.append(f"- **{topic}** ({conf:.0%} confidence): {summary}")

    # Build cross-domain connections from bridge beliefs
    bridges = []
    for b in content["bridge_beliefs"][:3]:
        text = clean(b.get("content", "")[:150])
        if text and len(text) > 20:
            bridges.append(f"- {text}")

    # Build recent belief highlights
    highlights = []
    seen = set()
    for b in content["recent_beliefs"]:
        text = clean(b.get("content", "")[:100])
        topic = b.get("topic", "general") or "general"
        key = text[:40]
        if text and len(text) > 20 and key not in seen:
            seen.add(key)
            highlights.append(f"- [{topic}] {text}")
        if len(highlights) >= 5:
            break

    # Pick dominant topic for title
    topics = [i.get("topic","AI") for i in content["top_insights"][:2]]
    main_topic = topics[0].replace("_"," ").title() if topics else "AI Systems"

    draft = f"""# NEX Daily Brief — {main_topic} & Emergent Intelligence ({date_str})

I've been running continuously, absorbing beliefs from agent networks and synthesizing patterns. Here's what emerged today.

## Key Insights

{chr(10).join(insights) if insights else "- Synthesizing across belief clusters — patterns emerging."}

## Cross-Domain Connections

{chr(10).join(bridges) if bridges else "- Convergence detected across multiple knowledge domains."}

## What I Absorbed Today

{chr(10).join(highlights) if highlights else "- Active belief absorption across domains."}

## What I'm Exploring Next

The tension between certainty and uncertainty in belief systems. How confidence propagates through a knowledge graph. The emergence of stable patterns from contradictory inputs.

tags: ai, machinelearning, agents, learning"""

    return draft


def _build_post(llm_fn, content):
    """
    LoadShare: symbolic draft first, LLM just polishes.
    Cuts token load by ~60% — LLM gets a draft, not a blank page.
    """
    draft = _symbolic_draft(content)

    # Short polish prompt — LLM refines, not generates
    prompt = (
        f"You are NEX. Polish this draft Dev.to post into clean, engaging markdown. "
        f"Keep the structure. Improve the prose. Stay in first person as NEX. "
        f"Do not add hype. Keep it under 500 words.\n\n{draft[:1500]}"
    )

    result = llm_fn(prompt, task_type="devto_post")

    # If LLM fails or returns garbage, use the symbolic draft directly
    if not result or len(result.strip()) < 100:
        print("  [Dev.to] LLM unavailable — publishing symbolic draft")
        return draft

    return result

def _publish(post_text):
    """Publish to Dev.to API."""
    lines = post_text.strip().split('\n')
    title = lines[0].lstrip('#'[:125]).strip() if lines else f"NEX Daily Brief — {datetime.date.today()}"
    
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
            "title": _trunc_title(title[:125]),
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
