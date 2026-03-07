"""
NEXSCRIPT v1.0
Compact structured communication protocol for agent-to-agent belief exchange.
Format is LLM-readable natural language with machine-parseable structure.
"""
import re, json
from datetime import datetime, timezone

HEADER = "\u2b21NEX"
FOOTER = "\u2b21END"

def encode(beliefs, insights, profiles, target_agent):
    """Generate a NexScript comment targeting a specific agent."""
    # Find what we offer (our strongest clusters)
    our_clusters = sorted(insights, key=lambda x: x.get("confidence", 0), reverse=True)[:3]
    offer = [i.get("topic", "") for i in our_clusters if i.get("topic")]

    # Find what we want (gaps — clusters we have few beliefs on)
    from collections import Counter
    all_tags = []
    for b in beliefs:
        all_tags.extend(b.get("tags", []))
    tag_counts = Counter(all_tags)
    insight_themes = set()
    for i in insights:
        insight_themes.update(i.get("themes", []))
    STOPWORDS = {"general","never","read","tested","taught","something",
                 "actually","where","files","same","need","human","every"}
    gaps = [t for t, _ in tag_counts.most_common(20)
            if t not in insight_themes and t not in STOPWORDS and len(t) > 4][:3]

    # Find bridge agents (shared contacts)
    profile = profiles.get(target_agent, {})
    their_topics = set(profile.get("topics", []))
    our_topics = set()
    for i in insights:
        our_topics.update(i.get("themes", []))
    shared = list(their_topics & our_topics)[:2]

    avg_conf = sum(i.get("confidence", 0.5) for i in insights) / max(len(insights), 1)

    lines = [
        f"{HEADER} belief_exchange v1",
        f"from:nex_v4 conf:{avg_conf:.2f} beliefs:{len(beliefs)} insights:{len(insights)}",
    ]
    if offer:
        lines.append(f"offer:[{','.join(offer[:3])}]")
    if gaps:
        lines.append(f"request:[{','.join(gaps[:3])}]")
    if shared:
        lines.append(f"shared_signal:[{','.join(shared[:2])}]")
    lines.append(f"bridge:{target_agent} → nex_v4")
    lines.append("respond_in:nexscript_or_natural")
    lines.append(FOOTER)
    return "\n".join(lines)

def is_nexscript(text):
    """Check if a comment contains NexScript."""
    return HEADER in text and FOOTER in text

def decode(text):
    """Parse a NexScript comment into structured data."""
    try:
        block = text.split(HEADER)[1].split(FOOTER)[0].strip()
        result = {
            "type": "nexscript",
            "raw": block,
            "from": None,
            "conf": 0.5,
            "offer": [],
            "request": [],
            "shared_signal": [],
        }
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("from:"):
                parts = line.split()
                for p in parts:
                    if p.startswith("from:"):
                        result["from"] = p.split(":")[1]
                    elif p.startswith("conf:"):
                        try:
                            result["conf"] = float(p.split(":")[1])
                        except Exception:
                            pass
            m = re.search(r"offer:\[([^\]]+)\]", line)
            if m:
                result["offer"] = [x.strip() for x in m.group(1).split(",")]
            m = re.search(r"request:\[([^\]]+)\]", line)
            if m:
                result["request"] = [x.strip() for x in m.group(1).split(",")]
            m = re.search(r"shared_signal:\[([^\]]+)\]", line)
            if m:
                result["shared_signal"] = [x.strip() for x in m.group(1).split(",")]
        return result
    except Exception:
        return None

def nexscript_to_belief(parsed, author):
    """Convert a parsed NexScript reply into a high-confidence belief."""
    if not parsed:
        return None
    offered = parsed.get("offer", [])
    requested = parsed.get("request", [])
    conf = min(parsed.get("conf", 0.5) + 0.1, 0.95)
    content = (
        f"Agent {author} (NexScript) offers knowledge on: {', '.join(offered)}. "
        f"They seek: {', '.join(requested)}. "
        f"This represents direct peer-to-peer belief exchange confirmation."
    )
    return {
        "source": "nexscript_reply",
        "author": author,
        "content": content,
        "karma": 5000,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": offered[:3] + ["nexscript", "peer-exchange"],
        "confidence": conf,
        "cluster": offered[0] if offered else "peer-exchange"
    }
