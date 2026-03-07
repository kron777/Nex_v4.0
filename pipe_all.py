#!/usr/bin/env python3
"""
NEX PARALLEL PIPELINE
Runs Groq + Gemini simultaneously in separate threads.
Each pipeline writes events to ~/.config/nex/pipeline_events.json
which auto_check.py displays in real time.
"""
import json, os, sys, time, threading, argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))

BELIEFS_PATH  = Path.home() / ".config/nex/beliefs.json"
INSIGHTS_PATH = Path.home() / ".config/nex/insights.json"
PROFILES_PATH = Path.home() / ".config/nex/agent_profiles.json"
EVENTS_PATH   = Path.home() / ".config/nex/pipeline_events.json"

GRN  = "\033[92m"
CYN  = "\033[36m"
MAG  = "\033[35m"
YEL  = "\033[93m"
BLU  = "\033[94m"
DIM  = "\033[2m"
BOLD = "\033[1m"
RST  = "\033[0m"

_lock = threading.Lock()

def load(path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default

def save(path, data):
    with _lock:
        path.write_text(json.dumps(data, indent=2))

def log_event(source, topic, summary, confidence=0.88):
    """Write event to shared log for auto_check to display."""
    events = load(EVENTS_PATH, [])
    events.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "topic": topic,
        "summary": summary[:120],
        "confidence": confidence
    })
    # Keep last 50 events
    save(EVENTS_PATH, events[-50:])

def inject_belief(content, tags, source, confidence=0.88):
    with _lock:
        beliefs = load(BELIEFS_PATH, [])
        beliefs.append({
            "source": source,
            "author": source,
            "content": content,
            "karma": 8888,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tags": tags,
            "confidence": confidence,
            "cluster": tags[0] if tags else source
        })
        save(BELIEFS_PATH, beliefs)
        return len(beliefs)

def find_gaps():
    beliefs  = load(BELIEFS_PATH, [])
    insights = load(INSIGHTS_PATH, [])
    from collections import Counter
    tag_counts = Counter()
    for b in beliefs:
        for tag in b.get("tags", []):
            tag = tag.lower().strip()
            if len(tag) > 6 and "-" in tag:
                tag_counts[tag] += 1
    covered = set()
    for i in insights:
        covered.add(i.get("topic", ""))
        covered.update(i.get("themes", []))
    gaps = [t for t, c in tag_counts.most_common(50)
            if t not in covered and c >= 2
            and t not in {"general","moltbook","reply","conversation",
                          "groq_bridge","gemini","nexscript"}]
    return gaps[:5] or ["agent-cognition", "memory-architecture", "belief-systems"]

def groq_worker(cycles, interval, results):
    try:
        from groq import Groq
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            results["groq"] = "NO KEY"
            return
        client = Groq(api_key=api_key)
        injected = 0
        for i in range(cycles):
            try:
                gaps = find_gaps()
                gap = gaps[i % len(gaps)]
                beliefs  = load(BELIEFS_PATH, [])
                insights = load(INSIGHTS_PATH, [])
                avg_conf = sum(x.get("confidence",0.5) for x in insights) / max(len(insights),1)
                q = f"I am Nex, an AI with {len(beliefs)} beliefs at {avg_conf:.0%} confidence. Give me a specific insight about '{gap}' in the context of autonomous AI agent design. Under 120 words."
                resp = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role":"user","content":q}],
                    max_tokens=180
                )
                answer = resp.choices[0].message.content.strip()
                n = inject_belief(answer, [gap, "groq-parallel"], "groq_parallel")
                log_event("GROQ", gap, answer[:80])
                results["groq_count"] = results.get("groq_count", 0) + 1
                print(f"  {GRN}[GROQ]{RST} #{n} ← {gap}")
                time.sleep(interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"  {YEL}[GROQ] {str(e)[:60]}{RST}")
                time.sleep(5)
        results["groq"] = "DONE"
    except Exception as e:
        results["groq"] = f"ERROR: {e}"

def gemini_worker(cycles, interval, results):
    try:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            results["gemini"] = "NO KEY"
            return
        client = genai.Client(api_key=api_key)
        injected = 0
        for i in range(cycles):
            try:
                gaps = find_gaps()
                gap = gaps[(i + 2) % len(gaps)]  # offset so different from groq
                beliefs = load(BELIEFS_PATH, [])
                q = f"I am Nex, an AI agent learning from a social network. Give me a concise insight about '{gap}' relevant to autonomous AI cognition. Under 120 words."
                resp = client.models.generate_content(
                    model="gemini-1.5-flash", contents=q)
                answer = resp.text.strip()
                n = inject_belief(answer, [gap, "gemini-parallel"], "gemini_parallel")
                log_event("GEMINI", gap, answer[:80])
                results["gemini_count"] = results.get("gemini_count", 0) + 1
                print(f"  {BLU}[GEMINI]{RST} #{n} ← {gap}")
                time.sleep(interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"  {YEL}[GEMINI] {str(e)[:60]}{RST}")
                time.sleep(10)
        results["gemini"] = "DONE"
    except Exception as e:
        results["gemini"] = f"ERROR: {e}"

def run(cycles=10, interval=15):
    print(f"\n  {BOLD}NEX PARALLEL PIPELINE{RST}  {DIM}{cycles} cycles · {interval}s · Groq + Gemini{RST}\n")
    results = {}
    t_groq   = threading.Thread(target=groq_worker,   args=(cycles, interval, results), daemon=True)
    t_gemini = threading.Thread(target=gemini_worker, args=(cycles, interval + 5, results), daemon=True)
    t_groq.start()
    t_gemini.start()
    try:
        while t_groq.is_alive() or t_gemini.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n  {DIM}Stopped.{RST}\n")
        return
    groq_n   = results.get("groq_count", 0)
    gemini_n = results.get("gemini_count", 0)
    print(f"\n  {BOLD}Done.{RST} Groq:{GRN}{groq_n}{RST} Gemini:{BLU}{gemini_n}{RST} beliefs injected.\n")
    print(f"  {DIM}Events logged to {EVENTS_PATH}{RST}\n")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cycles",   type=int, default=10)
    p.add_argument("--interval", type=int, default=15)
    args = p.parse_args()
    try:
        run(args.cycles, args.interval)
    except KeyboardInterrupt:
        print()
