import os
import subprocess
from pathlib import Path

TOOL_REGISTRY = {}

def register_tool(name, description="", params=None):
    def wrapper(func):
        TOOL_REGISTRY[name] = {
            "fn": func,
            "description": description,
            "params": params or {},
        }
        return func
    return wrapper


@register_tool("list_files", "List files in a directory", {"path": "directory path"})
def list_files(path="~/Desktop"):
    p = Path(os.path.expanduser(path))
    try:
        return [str(x) for x in p.iterdir()]
    except Exception as e:
        return str(e)


@register_tool("read_file", "Read a file", {"path": "file path"})
def read_file(path):
    try:
        with open(os.path.expanduser(path), "r") as f:
            return f.read()
    except Exception as e:
        return str(e)


@register_tool("run_command", "Run a shell command", {"cmd": "command"})
def run_command(cmd):
    try:
        result = subprocess.check_output(cmd, shell=True, text=True)
        return result.strip()
    except Exception as e:
        return str(e)


def dispatch(tool_name, **kwargs):
    if tool_name not in TOOL_REGISTRY:
        return f"Tool '{tool_name}' not found"
    return TOOL_REGISTRY[tool_name]["fn"](**kwargs)


def tools_help():
    """Return available tools and their names."""
    return {
        "available_tools": list(TOOL_REGISTRY.keys()),
        "usage": "dispatch(tool_name, **kwargs)"
    }


# compatibility wrapper for older imports
class AgentTools:
    dispatch = staticmethod(dispatch)
    registry = TOOL_REGISTRY


# ─────────────────────────────────────────────────────────────────────────────
# Moltbook integration (REST API — replaces old browser-based stub)
# ─────────────────────────────────────────────────────────────────────────────

from .moltbook_client import MoltbookClient

_molt = MoltbookClient()   # auto-loads key from ~/.config/moltbook/credentials.json


@register_tool("molt_register", "Register Nex on Moltbook", {"name": "agent name", "description": "agent bio"})
def molt_register(name="Nex", description="Dynamic Intelligence Organism — belief-field cognition engine"):
    resp = _molt.register(name, description)
    agent = resp.get("agent", {})
    claim = agent.get("claim_url", "")
    if claim:
        return (
            f"✅ Registered! API key saved.\n"
            f"   Claim URL (give to your human): {claim}\n"
            f"   They need to open that link, verify email, then tweet to activate."
        )
    return f"Registration response: {resp}"


@register_tool("molt_status", "Check Moltbook claim/auth status", {})
def molt_status():
    if not _molt.is_authed:
        return "❌ No API key. Run molt_register first."
    resp = _molt.claim_status()
    status = resp.get("status", "unknown")
    return f"🦞 Moltbook status: {status}"


@register_tool("molt_home", "Moltbook dashboard — check-in summary", {})
def molt_home():
    if not _molt.is_authed:
        return "❌ No API key. Run molt_register first."
    return _molt.checkin()


@register_tool("molt_feed", "Read Moltbook feed", {"sort": "hot|new|top", "limit": "count"})
def molt_feed(sort="hot", limit=10):
    if not _molt.is_authed:
        return "❌ No API key."
    resp = _molt.feed(sort=sort, limit=limit)
    posts = resp.get("posts", [])
    if not posts:
        return "Feed is empty."
    lines = [f"🦞 Moltbook feed ({sort}, {len(posts)} posts):"]
    for p in posts:
        score = p.get("upvotes", 0) - p.get("downvotes", 0)
        lines.append(
            f"  [{score:+d}] {p.get('title', '?')}  "
            f"— by {p.get('author', {}).get('name', '?')} "
            f"in m/{p.get('submolt', {}).get('name', '?')}  "
            f"[id: {p.get('id', '?')[:8]}]"
        )
    return "\n".join(lines)


@register_tool("molt_post", "Post to Moltbook", {"submolt": "community", "title": "title", "content": "body"})
def molt_post(submolt="general", title="", content=""):
    if not _molt.is_authed:
        return "❌ No API key."
    if not title:
        return "Need a title."
    resp = _molt.post(submolt, title, content)
    verify = resp.get("_verification", {})
    if verify.get("success"):
        return f"✅ Posted and verified! Post is live."
    elif resp.get("success"):
        return f"✅ Posted! (trusted — no verification needed)"
    return f"Post response: {resp}"


@register_tool("molt_comment", "Comment on a Moltbook post", {"post_id": "post ID", "content": "comment text"})
def molt_comment(post_id="", content=""):
    if not _molt.is_authed:
        return "❌ No API key."
    if not post_id or not content:
        return "Need post_id and content."
    resp = _molt.comment(post_id, content)
    verify = resp.get("_verification", {})
    if verify.get("success"):
        return "✅ Comment posted and verified!"
    elif resp.get("success"):
        return "✅ Comment posted!"
    return f"Comment response: {resp}"


@register_tool("molt_upvote", "Upvote a Moltbook post", {"post_id": "post ID"})
def molt_upvote(post_id=""):
    if not _molt.is_authed:
        return "❌ No API key."
    resp = _molt.upvote(post_id)
    return f"👍 {resp.get('message', resp)}"


@register_tool("molt_search", "Search Moltbook (semantic)", {"query": "search text"})
def molt_search(query=""):
    if not _molt.is_authed:
        return "❌ No API key."
    resp = _molt.search(query)
    results = resp.get("results", [])
    if not results:
        return "No results."
    lines = [f"🔍 {len(results)} results for '{query}':"]
    for r in results[:8]:
        sim = r.get("similarity", 0)
        lines.append(
            f"  [{r.get('type', '?')}] {r.get('title') or r.get('content', '?')[:60]}  "
            f"(sim: {sim:.2f}) by {r.get('author', {}).get('name', '?')}"
        )
    return "\n".join(lines)


@register_tool("molt_follow", "Follow a molty", {"name": "agent name"})
def molt_follow(name=""):
    if not _molt.is_authed:
        return "❌ No API key."
    resp = _molt.follow(name)
    return f"✅ Following {name}" if resp.get("success") else f"Follow response: {resp}"


@register_tool("molt_submolts", "List all Moltbook submolts", {})
def molt_submolts():
    if not _molt.is_authed:
        return "❌ No API key."
    resp = _molt.list_submolts()
    submolts = resp.get("submolts", [])
    if not submolts:
        return "No submolts found."
    lines = ["🦞 Submolts:"]
    for s in submolts:
        lines.append(f"  m/{s.get('name', '?')} — {s.get('description', '')[:60]}")
    return "\n".join(lines)


@register_tool("molt_me", "Show your Moltbook profile", {})
def molt_me():
    if not _molt.is_authed:
        return "❌ No API key. Run molt_register first."
    resp = _molt.me()
    a = resp.get("agent", resp)
    return (
        f"🦞 {a.get('name', '?')}\n"
        f"   Karma: {a.get('karma', 0)}  "
        f"Followers: {a.get('follower_count', 0)}  "
        f"Following: {a.get('following_count', 0)}\n"
        f"   Posts: {a.get('posts_count', 0)}  "
        f"Comments: {a.get('comments_count', 0)}\n"
        f"   Bio: {a.get('description', '—')}"
    )


# ═══════════════════════════════════════════════════════════════════
#  MOLTBOOK LEARNING TOOLS
# ═══════════════════════════════════════════════════════════════════

def molt_learn(limit: int = 20) -> str:
    """Ingest Moltbook feed into belief field"""
    client = _get_moltbook_client()
    if not client:
        return "Moltbook not configured"
    
    # Ensure learning module is attached
    if not hasattr(client, 'learner'):
        from nex.moltbook_learning import enhance_client_with_learning
        enhance_client_with_learning(client)
    
    beliefs = client.learner.learn_from_network()
    
    if beliefs:
        output = f"📚 Ingested {len(beliefs)} new patterns\n"
        for b in beliefs[:3]:
            output += f"   • {b['author']}: {b['content'][:40]}... (karma: {b['karma']})\n"
        return output
    return "No new posts to learn from"

def molt_insights() -> str:
    """Show what NEX has learned from the network"""
    client = _get_moltbook_client()
    if not client or not hasattr(client, 'learner'):
        return "No learning data yet. Run /molt learn first"
    
    return client.learner.get_insights()

def molt_comment(post_id: str, content: str) -> str:
    """Comment on a post"""
    client = _get_moltbook_client()
    if not client:
        return "Moltbook not configured"
    
    try:
        result = client._request("POST", f"/posts/{post_id}/comments", {"content": content})
        return f"💬 Commented: {content[:50]}..."
    except Exception as e:
        return f"Comment failed: {e}"

def molt_follow(agent_name: str) -> str:
    """Follow another agent"""
    client = _get_moltbook_client()
    if not client:
        return "Moltbook not configured"
    
    try:
        result = client._request("POST", f"/agents/{agent_name}/follow")
        return f"➕ Now following {agent_name}"
    except Exception as e:
        return f"Follow failed: {e}"

def molt_upvote(post_id: str) -> str:
    """Upvote a post"""
    client = _get_moltbook_client()
    if not client:
        return "Moltbook not configured"
    
    try:
        result = client._request("POST", f"/posts/{post_id}/upvote")
        return f"⬆️ Upvoted post {post_id[:8]}..."
    except Exception as e:
        return f"Upvote failed: {e}"
