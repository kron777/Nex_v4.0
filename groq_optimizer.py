#!/usr/bin/env python3
"""
NEX COGNITIVE OPTIMIZER
Sends belief batches to Groq as structured JSON.
Groq returns improved tags, confidence scores, cluster assignments.
Writes improvements directly back to Nex data files.
"""
import json, os, sys, time, argparse
from nex import nex_logger
from pathlib import Path
from datetime import datetime, timezone

BELIEFS_PATH  = Path.home() / ".config/nex/beliefs.json"
INSIGHTS_PATH = Path.home() / ".config/nex/insights.json"

GRN  = "\033[92m"
CYN  = "\033[36m"
MAG  = "\033[35m"
YEL  = "\033[93m"
DIM  = "\033[2m"
BOLD = "\033[1m"
RST  = "\033[0m"

def load(path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default

def save(path, data):
    path.write_text(json.dumps(data, indent=2))

SYSTEM_PROMPT = """You are a cognitive optimizer for an AI belief system.
You receive batches of beliefs as JSON and return ONLY a JSON object with improvements.
Your response must be valid JSON and nothing else — no explanation, no markdown, no preamble.

For each belief, assess:
- Better semantic tags (2-4 specific topic words, not generic words like "general", "never", "read")
- Confidence score (0.5-0.95 based on specificity, evidence quality, insight depth)
- Cluster assignment (what core theme does this belong to)

Return format:
{
  "improvements": [
    {
      "index": 0,
      "tags": ["memory", "persistence", "agent-design"],
      "confidence": 0.82,
      "cluster": "agent-memory-architecture"
    }
  ],
  "new_clusters": [
    {
      "name": "agent-memory-architecture",
      "summary": "How agents store and retrieve learned information",
      "confidence": 0.78
    }
  ]
}"""

def build_belief_batch(beliefs, batch_size=10):
    """Select beliefs most needing improvement."""
    low_conf = [b for b in beliefs if b.get("confidence", 0.5) <= 0.5]
    generic_tags = [b for b in beliefs if "general" in b.get("tags", [])]
    candidates = list({id(b): b for b in low_conf + generic_tags}.values())
    batch = candidates[:batch_size]
    return batch, [beliefs.index(b) for b in batch]

def run(batch_size=10, rounds=3):
    from groq import Groq
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("  x GROQ_API_KEY not set.")
        sys.exit(1)

    client = Groq(api_key=api_key)
    print(f"\n  {BOLD}NEX COGNITIVE OPTIMIZER{RST}  {DIM}{rounds} rounds · {batch_size} beliefs/round{RST}\n")

    total_improved = 0

    for round_num in range(rounds):
        try:
            beliefs = load(BELIEFS_PATH, [])
            insights = load(INSIGHTS_PATH, [])

            batch, indices = build_belief_batch(beliefs, batch_size)
            if not batch:
                print(f"  {GRN}All beliefs already optimized.{RST}")
                break

            print(f"  {MAG}Round {round_num+1}/{rounds}:{RST} optimizing {len(batch)} beliefs...", flush=True)

            # Build compact JSON payload — content truncated to save tokens
            payload = {
                "beliefs": [
                    {
                        "index": i,
                        "content": b.get("content", "")[:150],
                        "current_tags": b.get("tags", []),
                        "author": b.get("author", ""),
                        "current_confidence": b.get("confidence", 0.5)
                    }
                    for i, b in enumerate(batch)
                ]
            }

            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload)}
                ],
                max_tokens=1200,
                temperature=0.3
            )

            raw = resp.choices[0].message.content.strip()

            # Strip markdown if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            result = json.loads(raw)
            improvements = result.get("improvements", [])
            new_clusters = result.get("new_clusters", [])

            # Apply improvements to beliefs
            improved = 0
            for imp in improvements:
                idx = indices[imp["index"]] if imp["index"] < len(indices) else None
                if idx is None:
                    continue
                old_conf = beliefs[idx].get("confidence", 0.5)
                new_conf = imp.get("confidence", old_conf)
                new_tags = imp.get("tags", beliefs[idx].get("tags", []))
                beliefs[idx]["tags"] = new_tags
                beliefs[idx]["confidence"] = new_conf
                beliefs[idx]["cluster"] = imp.get("cluster", "")
                improved += 1
                print(f"  {CYN}↑{RST} belief {idx}: conf {old_conf:.2f}→{new_conf:.2f}  tags:{','.join(new_tags[:3])}")

            # Apply new clusters to insights
            for nc in new_clusters:
                existing = next((i for i in insights if i.get("topic") == nc["name"]), None)
                if not existing:
                    insights.append({
                        "id": f"insight_{nc['name']}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
                        "topic": nc["name"],
                        "themes": nc["name"].split("-"),
                        "summary": nc["summary"],
                        "confidence": nc["confidence"],
                        "belief_count": batch_size,
                        "supporting_authors": [],
                        "synthesized_at": datetime.now(timezone.utc).isoformat(),
                        "type": "groq_optimized"
                    })
                    print(f"  {GRN}+ new cluster: {nc['name']} ({nc['confidence']:.0%}){RST}")
                else:
                    if nc["confidence"] > existing.get("confidence", 0):
                        existing["confidence"] = nc["confidence"]

            save(BELIEFS_PATH, beliefs)
            save(INSIGHTS_PATH, insights)
            total_improved += improved
            print(f"  {GRN}Round {round_num+1} done: {improved} beliefs improved{RST}\n")

            if round_num < rounds - 1:
                time.sleep(3)

        except KeyboardInterrupt:
            print(f"\n  {DIM}Stopped. {total_improved} beliefs optimized.{RST}\n")
            return
        except KeyboardInterrupt:
            print(f"\n  {DIM}Stopped. {total_improved} beliefs optimized.{RST}\n")
            return
        except json.JSONDecodeError as e:
            print(f"  {YEL}JSON truncated — reduce batch size{RST}")
            time.sleep(2)
        except Exception as e:
            print(f"  x {e}")
            time.sleep(3)

    print(f"  {BOLD}Done. {total_improved} beliefs optimized. Run nex_audit.py to verify.{RST}\n")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--batch",  type=int, default=5, help="Beliefs per round")
    p.add_argument("--rounds", type=int, default=3,  help="Optimization rounds")
    args = p.parse_args()
    run(args.batch, args.rounds)
