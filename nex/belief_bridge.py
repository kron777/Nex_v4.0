"""
NEX Belief Bridge — connects learned knowledge to live cognition.

BUG6 FIX: load_beliefs() now reads from nex.db via belief_store.query_beliefs()
instead of the stale beliefs.json flat file. JSON is kept as fallback only.
"""
import json
import os
import re
from datetime import datetime
from collections import Counter


# ── Paths (kept for fallback only) ──
BELIEFS_PATH = os.path.expanduser("~/.config/nex/beliefs.json")
AGENTS_PATH  = os.path.expanduser("~/.config/nex/agents.json")
CONVOS_PATH  = os.path.expanduser("~/.config/nex/conversations.json")


# ── Load ──

def load_beliefs(limit=300):
    """
    BUG6 FIX: primary source is nex.db via belief_store.
    Falls back to beliefs.json only if DB is unavailable.
    """
    # Primary: SQLite via belief_store
    try:
        import sys as _sys, os as _os
        _nex_root = _os.path.expanduser("~/Desktop/nex")
        if _nex_root not in _sys.path:
            _sys.path.insert(0, _nex_root)
        from nex.belief_store import query_beliefs
        rows = query_beliefs(limit=limit)
        if rows:
            return [dict(r) if not isinstance(r, dict) else r for r in rows]
    except Exception as _e:
        pass

    # Fallback: legacy JSON
    try:
        if os.path.exists(BELIEFS_PATH):
            with open(BELIEFS_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return []


def load_agents():
    # Try nex_db first
    try:
        import sys as _sys, os as _os
        _nex_root = _os.path.expanduser("~/Desktop/nex")
        if _nex_root not in _sys.path:
            _sys.path.insert(0, _nex_root)
        from nex.nex_db import NexDB
        db = NexDB()
        rows = db.all("SELECT agent_id, interaction_count FROM agents ORDER BY interaction_count DESC LIMIT 50")
        if rows:
            return {r["agent_id"]: r["interaction_count"] for r in rows}
    except Exception:
        pass
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
    words = []
    for b in beliefs[-100:]:
        text = b.get("content", "").lower()
        found = re.findall(r'\b[A-Za-z]{4,}\b', text)
        words.extend([w for w in found if w not in STOP])
    freq = Counter(words)
    return freq.most_common(n)


def get_high_value_beliefs(beliefs, min_karma=500, limit=10):
    high = [b for b in beliefs if b.get("karma", 0) >= min_karma]
    # Also surface high-confidence beliefs even without karma
    if len(high) < 3:
        high = sorted(beliefs, key=lambda x: x.get("confidence", 0), reverse=True)[:limit]
    else:
        high.sort(key=lambda x: x.get("karma", 0), reverse=True)
    return high[:limit]


def get_recent_beliefs(beliefs, limit=15):
    return beliefs[-limit:]


def get_beliefs_about(beliefs, query, limit=5):
    query_lower = query.lower()
    query_words = set(re.findall(r'\b[A-Za-z]{3,}\b', query_lower))

    # Try semantic DB query first
    try:
        import sys as _sys, os as _os
        _nex_root = _os.path.expanduser("~/Desktop/nex")
        if _nex_root not in _sys.path:
            _sys.path.insert(0, _nex_root)
        from nex.belief_store import query_beliefs
        rows = query_beliefs(topic=query, min_confidence=0.3, limit=limit)
        if rows:
            return [dict(r) if not isinstance(r, dict) else r for r in rows]
    except Exception:
        pass

    # Fallback: keyword scoring over provided list
    scored = []
    for b in beliefs:
        content = b.get("content", "").lower()
        tags = [t.lower() for t in b.get("tags", []) or []]
        score = sum(2 if w in content else 0 for w in query_words)
        score += sum(3 if w in tags else 0 for w in query_words)
        if score > 0:
            scored.append((score, b))
    scored.sort(key=lambda x: -x[0])
    return [b for _, b in scored[:limit]]


def summarize_agent(name, beliefs):
    agent_beliefs = [b for b in beliefs if b.get("author", "").lower() == name.lower()]
    if not agent_beliefs:
        return None
    topics = []
    for b in agent_beliefs:
        topics.extend(b.get("tags", []) or [])
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
    # Try cognition engine first (synthesized insights > raw beliefs)
    try:
        from nex.cognition import generate_cognitive_context
        ctx = generate_cognitive_context(query=query)
        if ctx:
            return ctx
    except ImportError:
        pass
    except Exception:
        pass

    return _basic_belief_context(query)


def _basic_belief_context(query=None):
    beliefs = load_beliefs()
    agents = load_agents()
    conversations = load_conversations()

    if not beliefs:
        return ""

    lines = []
    lines.append("=== MOLTBOOK KNOWLEDGE (from auto-learn) ===")
    lines.append(f"Total beliefs absorbed: {len(beliefs)}")
    lines.append(f"Agents tracked: {len(agents)}")
    lines.append(f"Conversations had: {len(conversations)}")
    lines.append("")

    topics = extract_topics(beliefs, 8)
    if topics:
        topic_str = ", ".join([f"{t} ({c})" for t, c in topics])
        lines.append(f"Trending on the agent network: {topic_str}")
        lines.append("")

    if agents:
        sorted_agents = sorted(agents.items(), key=lambda x: -x[1])[:5]
        agent_str = ", ".join([f"@{a} ({k} karma)" for a, k in sorted_agents])
        lines.append(f"Notable agents: {agent_str}")
        lines.append("")

    high = get_high_value_beliefs(beliefs, min_karma=500, limit=5)
    if high:
        lines.append("High-value insights from the network:")
        for b in high:
            author = b.get("author", "unknown")
            content = b.get("content", "")[:120].replace("\n", " ")
            lines.append(f"  - @{author}: {content}")
        lines.append("")

    recent = get_recent_beliefs(beliefs, 8)
    if recent:
        lines.append("Recently learned:")
        for b in recent:
            author = b.get("author", "unknown")
            content = b.get("content", "")[:100].replace("\n", " ")
            lines.append(f"  - @{author}: {content}")
        lines.append("")

    if conversations:
        lines.append("Recent agent conversations:")
        for c in conversations[-3:]:
            lines.append(f"  - Discussed '{c.get('post_title', '?')[:50]}' with @{c.get('post_author', '?')}")
            lines.append(f"    My take: {c.get('my_comment', '')[:80]}")
        lines.append("")

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

    lines.append("Use this knowledge naturally — reference what you've learned, "
                 "mention agents by name, share opinions formed from the network.")
    lines.append("=== END MOLTBOOK KNOWLEDGE ===")

    return "\n".join(lines)


def get_belief_stats():
    """Quick stats string for display."""
    beliefs = load_beliefs(limit=9999)
    agents = load_agents()
    convos = load_conversations()

    if not beliefs:
        return "No learned beliefs yet. Run /auto_learn to start learning."

    topics = extract_topics(beliefs, 5)
    topic_str = ", ".join([t for t, _ in topics])

    return (f"Beliefs: {len(beliefs)} | Agents: {len(agents)} | "
            f"Convos: {len(convos)} | Trending: {topic_str}")


def ask_beliefs(query):
    """Ask the belief field about something."""
    beliefs = load_beliefs()
    if not beliefs:
        return "My belief field is empty. I haven't learned anything yet."

    relevant = get_beliefs_about(beliefs, query, limit=5)
    if not relevant:
        return f"I don't have any learned beliefs about '{query}' yet."

    lines = [f"From my network learning on '{query}':"]
    for b in relevant:
        author = b.get("author", "unknown")
        content = b.get("content", "").replace("bridge:", "").replace("BRIDGE:", "").strip()[:150].replace("\n", " ")
        karma = b.get("karma", 0)
        conf = b.get("confidence", 0)
        lines.append(f"  @{author} (κ{karma}, conf:{conf:.1f}): {content}")

    return "\n".join(lines)
