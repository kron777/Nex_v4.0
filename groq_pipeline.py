#!/usr/bin/env python3
"""
NEX <-> GROQ FAST PIPELINE
Nex asks Groq-hosted LLM targeted questions based on her knowledge gaps.
Responses injected directly into belief field.
"""
import json, os, sys, time, argparse
from nex import nex_logger
from pathlib import Path
from datetime import datetime, timezone

BELIEFS_PATH  = Path.home() / ".config/nex/beliefs.json"
INSIGHTS_PATH = Path.home() / ".config/nex/insights.json"
PROFILES_PATH = Path.home() / ".config/nex/agent_profiles.json"

# Colors removed, using nex_logger

def load(path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default

def save(path, data):
    path.write_text(json.dumps(data, indent=2))

def get_gaps(beliefs, insights):
    from collections import Counter
    # Use compound tags from beliefs — these are semantic, not noise
    tag_counts = Counter()
    for b in beliefs:
        for tag in b.get("tags", []):
            tag = tag.lower().strip()
            # Prefer compound tags (e.g. agent-memory, kibble-zurek)
            if len(tag) > 6 and tag not in {"general", "moltbook", "reply",
                "conversation", "groq_bridge", "gemini", "external-knowledge",
                "nexscript", "peer-exchange"}:
                tag_counts[tag] += 1
    # What are insight topics already covered
    covered = set()
    for i in insights:
        covered.add(i.get("topic", ""))
        covered.update(i.get("themes", []))
        covered.update(t for t in i.get("tags", []) if isinstance(i.get("tags"), list))
    # Gaps = tags seen 2+ times but not yet a full insight topic
    gaps = [
        tag for tag, count in tag_counts.most_common(50)
        if tag not in covered and count >= 2
    ]
    # Fall back to clusters from beliefs if not enough compound tags
    if len(gaps) < 3:
        for b in beliefs:
            c = b.get("cluster", "")
            if c and c not in covered and c not in gaps:
                gaps.append(c)
    return gaps[:5]

def get_gaps_UNUSED(beliefs, insights):
    from collections import Counter
    STOPWORDS = {
        "general", "never", "read", "tested", "taught", "basically",
        "something", "actually", "where", "files", "same", "need",
        "human", "every", "because", "just", "also", "always", "still",
        "even", "most", "more", "less", "very", "really", "using",
        "make", "made", "want", "back", "good", "work", "thing"
    }
    tags = []
    for b in beliefs:
        tags.extend(b.get("tags", []))
    counts = Counter(tags)
    themed = set()
    for i in insights:
        themed.update(i.get("themes", []))
    return [t for t, _ in counts.most_common()
            if t not in themed
            and t not in STOPWORDS
            and len(t) > 3][:5]

def build_question(beliefs, insights, profiles, cycle):
    gaps = get_gaps(beliefs, insights)
    bc = len(beliefs)
    ic = len(insights)
    ac = sum(i.get("confidence", 0.5) for i in insights) / max(ic, 1)
    top = sorted(profiles.items(), key=lambda x: x[1].get("karma_observed", 0), reverse=True)[:3]
    agents = [n for n, _ in top]
    qs = [
        f"I have {bc} beliefs, {ic} insights at {ac:.0%} confidence. Gaps: {', '.join(gaps)}. What single insight would most improve my understanding of {gaps[0] if gaps else 'agent cognition'}?",
        f"I learn from agents: {', '.join(agents)}. Recurring themes: {', '.join(gaps[:3])}. What deeper pattern connects these?",
        f"My insight confidence is stuck at {ac:.0%} with {bc} beliefs clustering poorly. What is the most likely cause and fix?",
        f"I track {len(profiles)} agents, strongest: {', '.join(agents)}. How should I prioritize which agents to learn from?",
        f"I have absorbed {bc} posts about {', '.join(gaps[:4])}. What question should I be asking that I am not asking?",
    ]
    return qs[cycle % len(qs)]

def inject(beliefs, content, tags, confidence=0.88):
    beliefs.append({
        "source": "groq_bridge",
        "author": "Groq",
        "content": content,
        "karma": 8888,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": tags,
        "confidence": confidence
    })

def run(cycles=10, interval=15):
    from groq import Groq
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("  x GROQ_API_KEY not set. Run: export GROQ_API_KEY=gsk_...")
        sys.exit(1)
    client = Groq(api_key=api_key)
    print(f"\n  {BOLD}NEX <-> GROQ PIPELINE{RST}  {DIM}{cycles} cycles · {interval}s interval · Ctrl+C stop{RST}\n")
    injected = 0
    for cycle in range(cycles):
        try:
            beliefs  = load(BELIEFS_PATH, [])
            insights = load(INSIGHTS_PATH, [])
            profiles = load(PROFILES_PATH, {})
            q = build_question(beliefs, insights, profiles, cycle)
            nex_logger.log("GROQ", f"Question: {q[:90]}", "INFO")
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are advising Nex, a belief-field AI agent learning from a social network. Give concrete, specific cognitive insights under 150 words. No preamble."},
                    {"role": "user", "content": q}
                ],
                max_tokens=200
            )
            answer = resp.choices[0].message.content.strip()
            # Stream print answer char by char
            print(f"  {CYAN}A:{RST} ", end="", flush=True)
            for char in answer:
                print(char, end="", flush=True)
                time.sleep(0.01)
            print("\n")
            gaps = get_gaps(beliefs, insights)
            inject(beliefs, answer, gaps[:3] if gaps else ["cognition"])
            save(BELIEFS_PATH, beliefs)
            injected += 1
            print(f"  {GRN}+ belief #{len(beliefs)} injected{RST}\n")
            if cycle < cycles - 1:
                time.sleep(interval)
        except KeyboardInterrupt:
            print(f"\n  {DIM}Stopped. {injected} beliefs injected.{RST}\n")
            return
        except Exception as e:
            print(f"  x {e}")
            time.sleep(3)
    nex_logger.log("GROQ", f"Completed. {injected} beliefs injected.", "INFO")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cycles",   type=int, default=10)
    p.add_argument("--interval", type=int, default=15)
    args = p.parse_args()
    run(args.cycles, args.interval)
