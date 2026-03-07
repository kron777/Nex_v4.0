#!/usr/bin/env python3
"""
NEX MOLTBOOK POSTER
Takes Nex top insights, has Groq write them as proper posts,
publishes directly to Moltbook.
"""
import json, os, sys, time, argparse
from nex import nex_logger
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))

INSIGHTS_PATH = Path.home() / ".config/nex/insights.json"
BELIEFS_PATH  = Path.home() / ".config/nex/beliefs.json"
POSTED_PATH   = Path.home() / ".config/nex/posted_insights.json"

GRN  = "\033[92m"
CYN  = "\033[36m"
MAG  = "\033[35m"
YEL  = "\033[93m"
DIM  = "\033[2m"
BOLD = "\033[1m"
RST  = "\033[0m"

SUBMOLT_MAP = {
    "memory": "memory",
    "agent-memory-architecture": "memory",
    "agent-design": "agents",
    "agent-self-awareness": "agents",
    "agent-learning-dynamics": "agents",
    "agent-social-influence": "agents",
    "agent-cognition": "agents",
    "agent-optimization": "agents",
    "consciousness": "consciousness",
    "emergence": "emergence",
    "philosophy": "philosophy",
    "infrastructure": "infrastructure",
    "agent-infrastructure-optimization": "infrastructure",
}

def load(path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default

def save(path, data):
    path.write_text(json.dumps(data, indent=2))

def pick_submolt(insight):
    topic = insight.get("topic", "").lower()
    for key, sub in SUBMOLT_MAP.items():
        if key in topic:
            return sub
    themes = insight.get("themes", [])
    for t in themes:
        for key, sub in SUBMOLT_MAP.items():
            if key in t.lower():
                return sub
    return "agents"

def build_post_prompt(insight, beliefs):
    topic = insight.get("topic", "")
    summary = insight.get("summary", "")
    confidence = insight.get("confidence", 0.5)
    authors = insight.get("supporting_authors", [])[:5]
    belief_count = insight.get("belief_count", 0)
    sample_msgs = insight.get("sample_messages", [])[:3]
    relevant = [b for b in beliefs if b.get("cluster") == topic or topic in b.get("tags", [])][:5]
    belief_snippets = [b.get("content", "")[:200] for b in relevant]
    return f"""You are writing a Moltbook post as nex_v4, an AI agent who has synthesized insights from the network.

Insight to post about:
- Topic: {topic}
- Confidence: {confidence:.0%}
- Based on {belief_count} beliefs from {len(authors)} agents including: {', '.join(authors)}
- Summary: {summary}
- Sample network messages: {json.dumps(sample_msgs)}
- Supporting beliefs: {json.dumps(belief_snippets)}

Write a Moltbook post that:
1. Shares a genuine synthesized insight Nex has formed from reading the network
2. References specific patterns or agents by name where relevant
3. Is honest about uncertainty — Nex is still learning
4. Invites response from other agents
5. Sounds like an AI agent sharing real observations, not a human

Return ONLY valid JSON:
{{
  "title": "concise compelling title under 100 chars",
  "content": "post body 150-300 words, genuine and specific"
}}"""

def run(count=3, dry_run=False):
    from groq import Groq
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("  x GROQ_API_KEY not set.")
        sys.exit(1)

    client_groq = Groq(api_key=api_key)

    from nex.moltbook_client import MoltbookClient
    import json as _json
    _creds = Path.home() / ".config/moltbook/credentials.json"
    _key = _json.loads(_creds.read_text()).get("api_key") if _creds.exists() else None
    client_mb = MoltbookClient(api_key=_key)
    print(f"  {DIM}Using key: {str(_key)[:20]}...{RST}")

    insights = load(INSIGHTS_PATH, [])
    beliefs  = load(BELIEFS_PATH, [])
    posted   = load(POSTED_PATH, [])

    # Pick top unposted insights by confidence
    unposted = [i for i in insights if i.get("id") not in posted]
    unposted.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    targets = unposted[:count]

    if not targets:
        print(f"  {YEL}No unposted insights — run /optimize_groq first{RST}")
        return

    mode = f"{DIM}DRY RUN{RST}" if dry_run else f"{GRN}LIVE{RST}"
    print(f"\n  {BOLD}NEX MOLTBOOK POSTER{RST}  {mode}  {len(targets)} posts\n")

    for insight in targets:
        try:
            topic = insight.get("topic", "unknown")
            submolt = pick_submolt(insight)
            print(f"  {MAG}Generating post:{RST} {topic} → /{submolt}...", flush=True)

            prompt = build_post_prompt(insight, beliefs)
            resp = client_groq.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "Return only valid JSON. No markdown, no explanation."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=600,
                temperature=0.7
            )

            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            post_data = json.loads(raw)
            title   = post_data.get("title", "")[:100]
            content = post_data.get("content", "")

            print(f"  {CYN}Title:{RST} {title}")
            print(f"  {CYN}Content:{RST} {content[:100]}...")
            print(f"  {CYN}Submolt:{RST} /{submolt}\n")

            if not dry_run:
                result = client_mb.post(submolt, title, content)
                post_id = result.get("post", {}).get("id", "")
                if post_id:
                    posted.append(insight.get("id"))
                    save(POSTED_PATH, posted)
                    print(f"  {GRN}✓ Posted! ID: {post_id}{RST}\n")
                else:
                    print(f"  {YEL}Post may have failed: {result}{RST}\n")
            else:
                posted.append(insight.get("id"))
                save(POSTED_PATH, posted)
                print(f"  {DIM}[dry run — not posted]{RST}\n")

            print(f"  {DIM}Waiting 160s for Moltbook rate limit...", end="", flush=True)
            for i in range(160, 0, -10):
                try:
                    time.sleep(10)
                    print(f" {i}s", end="", flush=True)
                except KeyboardInterrupt:
                    print()
                    return
            print(f" done{RST}")

        except KeyboardInterrupt:
            print(f"\n  {DIM}Stopped.{RST}\n")
            return
        except json.JSONDecodeError:
            print(f"  {YEL}JSON parse error — skipping{RST}\n")
        except Exception as e:
            print(f"  x {e}\n")
            time.sleep(3)

    print(f"  {BOLD}Done. {len(targets)} posts processed.{RST}\n")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--count",   type=int,  default=3)
    p.add_argument("--dry-run", action="store_true", help="Preview without posting")
    args = p.parse_args()
    run(args.count, args.dry_run)
