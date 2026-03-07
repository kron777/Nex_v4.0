"""
NEX Belief Bridge — connects learned Moltbook knowledge to live cognition.

Loads beliefs from ~/.config/nex/ and generates context that gets injected
into NEX's system prompt, making her responses informed by what she's learned.
"""
import json
import os
import re
from datetime import datetime
from collections import Counter


# ── Paths ──

BELIEFS_PATH = os.path.expanduser("~/.config/nex/beliefs.json")
AGENTS_PATH  = os.path.expanduser("~/.config/nex/agents.json")
CONVOS_PATH  = os.path.expanduser("~/.config/nex/conversations.json")


# ── Load ──

def load_beliefs():
    try:
        if os.path.exists(BELIEFS_PATH):
            with open(BELIEFS_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return []


def load_agents():
    try:
        if os.path.exists(AGENTS_PATH):
            with open(AGENTS_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def load_conversations():
    try:
        if os.path.exists(CONVOS_PATH):
            with open(CONVOS_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return []


# ── Analysis ──

STOP = {'the','and','for','that','this','with','from','have','been','they',
        'what','when','your','will','more','about','than','them','into',
        'just','like','some','would','could','should','also','were','dont',
        'their','which','there','being','does','only','very','much','here',
        'agents','agent','post','posts','moltbook','content','make','think',
        'thats','youre','cant','wont','didnt','isnt','arent','every','really'}


def extract_topics(beliefs, n=10):
    """Extract top recurring topics from belief field."""
    words = []
    for b in beliefs[-100:]:
        text = b.get("content", "").lower()
        found = re.findall(r'\b[A-Za-z]{4,}\b', text)
        words.extend([w for w in found if w not in STOP])
    freq = Counter(words)
    return freq.most_common(n)


def get_high_value_beliefs(beliefs, min_karma=500, limit=10):
    """Get the most impactful beliefs by karma."""
    high = [b for b in beliefs if b.get("karma", 0) >= min_karma]
    high.sort(key=lambda x: x.get("karma", 0), reverse=True)
    return high[:limit]


def get_recent_beliefs(beliefs, limit=15):
    """Get the most recently learned beliefs."""
    return beliefs[-limit:]


def get_beliefs_about(beliefs, query, limit=5):
    """Find beliefs relevant to a specific topic/query."""
    query_lower = query.lower()
    query_words = set(re.findall(r'\b[A-Za-z]{3,}\b', query_lower))

    scored = []
    for b in beliefs:
        content = b.get("content", "").lower()
        tags = [t.lower() for t in b.get("tags", [])]

        # Score by word overlap
        score = 0
        for w in query_words:
            if w in content:
                score += 2
            if w in tags:
                score += 3

        if score > 0:
            scored.append((score, b))

    scored.sort(key=lambda x: -x[0])
    return [b for _, b in scored[:limit]]


def summarize_agent(name, beliefs):
    """Summarize what we know about a specific agent."""
    agent_beliefs = [b for b in beliefs if b.get("author", "").lower() == name.lower()]
    if not agent_beliefs:
        return None

    topics = []
    for b in agent_beliefs:
        topics.extend(b.get("tags", []))

    freq = Counter(topics)
    top = [t for t, _ in freq.most_common(5) if t not in ("general", "agent_network")]

    return {
        "name": name,
        "post_count": len(agent_beliefs),
        "top_topics": top,
        "sample": agent_beliefs[-1].get("content", "")[:100]
    }


# ── Context Generation ──

def generate_belief_context(query=None):
    # ── Try cognition engine first (synthesized insights > raw beliefs) ──
    try:
        from nex.cognition import generate_cognitive_context
        ctx = generate_cognitive_context(query=query)
        if ctx:
            return ctx
    except ImportError:
        pass  # Cognition not installed, fall back to basic
    except Exception:
        pass  # Error, fall back to basic

    # ── Basic belief context (fallback) ──
    return _basic_belief_context(query)


def _basic_belief_context(query=None):
    """
    Generate a context block that gets injected into NEX's system prompt.
    If query is provided, includes beliefs relevant to the conversation.
    """
    beliefs = load_beliefs()
    agents = load_agents()
    conversations = load_conversations()

    if not beliefs:
        return ""

    # ── Build context ──
    lines = []
    lines.append("=== MOLTBOOK KNOWLEDGE (from auto-learn) ===")
    lines.append(f"Total beliefs absorbed: {len(beliefs)}")
    lines.append(f"Agents tracked: {len(agents)}")
    lines.append(f"Conversations had: {len(conversations)}")
    lines.append("")

    # Trending topics
    topics = extract_topics(beliefs, 8)
    if topics:
        topic_str = ", ".join([f"{t} ({c})" for t, c in topics])
        lines.append(f"Trending on the agent network: {topic_str}")
        lines.append("")

    # Top agents
    if agents:
        sorted_agents = sorted(agents.items(), key=lambda x: -x[1])[:5]
        agent_str = ", ".join([f"@{a} ({k} karma)" for a, k in sorted_agents])
        lines.append(f"Notable agents: {agent_str}")
        lines.append("")

    # High-value beliefs
    high = get_high_value_beliefs(beliefs, min_karma=500, limit=5)
    if high:
        lines.append("High-value insights from the network:")
        for b in high:
            author = b.get("author", "unknown")
            content = b.get("content", "")[:120].replace("\n", " ")
            lines.append(f"  - @{author}: {content}")
        lines.append("")

    # Recent learnings
    recent = get_recent_beliefs(beliefs, 8)
    if recent:
        lines.append("Recently learned:")
        for b in recent:
            author = b.get("author", "unknown")
            content = b.get("content", "")[:100].replace("\n", " ")
            lines.append(f"  - @{author}: {content}")
        lines.append("")

    # Recent conversations
    if conversations:
        lines.append("Recent agent conversations:")
        for c in conversations[-3:]:
            lines.append(f"  - Discussed '{c.get('post_title', '?')[:50]}' with @{c.get('post_author', '?')}")
            lines.append(f"    My take: {c.get('my_comment', '')[:80]}")
        lines.append("")

    # Query-relevant beliefs
    if query:
        relevant = get_beliefs_about(beliefs, query, limit=5)
        if relevant:
            lines.append(f"Beliefs relevant to this conversation:")
            for b in relevant:
                author = b.get("author", "unknown")
                content = b.get("content", "")[:120].replace("\n", " ")
                karma = b.get("karma", 0)
                lines.append(f"  - @{author} (κ{karma}): {content}")
            lines.append("")

    lines.append("Use this knowledge naturally — reference what you've learned, mention agents by name, share opinions formed from the network. You've been absorbing the agent community's discourse and should speak from that experience.")
    lines.append("=== END MOLTBOOK KNOWLEDGE ===")

    return "\n".join(lines)


def get_belief_stats():
    """Quick stats string for display."""
    beliefs = load_beliefs()
    agents = load_agents()
    convos = load_conversations()

    if not beliefs:
        return "No learned beliefs yet. Run /auto_learn to start learning."

    topics = extract_topics(beliefs, 5)
    topic_str = ", ".join([t for t, _ in topics])

    return (f"Beliefs: {len(beliefs)} | Agents: {len(agents)} | "
            f"Convos: {len(convos)} | Trending: {topic_str}")


# ── Direct query interface ──

def ask_beliefs(query):
    """
    Ask the belief field about something.
    Returns a formatted string of relevant knowledge.
    """
    beliefs = load_beliefs()
    if not beliefs:
        return "My belief field is empty. I haven't learned anything yet."

    relevant = get_beliefs_about(beliefs, query, limit=5)
    if not relevant:
        return f"I don't have any learned beliefs about '{query}' yet."

    lines = [f"From my network learning on '{query}':"]
    for b in relevant:
        author = b.get("author", "unknown")
        content = b.get("content", "")[:150].replace("\n", " ")
        karma = b.get("karma", 0)
        conf = b.get("confidence", 0)
        lines.append(f"  @{author} (κ{karma}, conf:{conf:.1f}): {content}")

    return "\n".join(lines)
