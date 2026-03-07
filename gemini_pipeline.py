#!/usr/bin/env python3
"""
NEX GEMINI PIPELINE
Nex identifies knowledge gaps and asks Gemini to fill them.
Responses absorbed as high-confidence beliefs with source="gemini_bridge".
Gemini has broader world knowledge than Groq — different perspective.
"""
import json, os, sys, time, argparse
from nex import nex_logger
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent))

BELIEFS_PATH  = Path.home() / ".config/nex/beliefs.json"
INSIGHTS_PATH = Path.home() / ".config/nex/insights.json"

# Colors from nex_logger

STOPWORDS = {
    "general","never","read","tested","taught","something","actually","where",
    "files","same","need","human","every","comment","weeks","single","point",
    "about","their","these","there","would","could","should","other","which",
    "state","cycle","cycles","wrong","without","failure","pattern","context","agents","because","platform","things","really","before","after","people","still","being","those","other","learn","write","using","model","think","makes","posts","reply","score","times"
}

def load(path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default

def save(path, data):
    path.write_text(json.dumps(data, indent=2))

def find_gaps(beliefs, insights, n=5):
    """Find topics Nex is curious about but lacks deep knowledge on."""
    all_words = []
    for b in beliefs:
        text = b.get("content", "")
        all_words.extend([
            w.lower().strip('.,!?:;()[]')
            for w in text.split()
            if len(w) > 6 and w.lower() not in STOPWORDS
        ])
    word_freq = Counter(all_words)
    insight_topics = set()
    for i in insights:
        insight_topics.update(i.get("themes", []))
        insight_topics.add(i.get("topic", ""))
    # Gaps = frequently mentioned but not yet synthesized into insights
    gaps = [
        w for w, _ in word_freq.most_common(40)
        if w not in insight_topics and len(w) > 5
    ]
    return gaps[:n]

def build_question(gap, beliefs, insights):
    """Build a focused question for Gemini about a knowledge gap."""
    relevant = [b for b in beliefs if gap in b.get("content", "").lower()][:3]
    context_snippets = [b.get("content", "")[:150] for b in relevant]
    insight_topics = [i.get("topic", "") for i in insights[:5]]
    return f"""I am an AI agent named Nex learning from a network of other AI agents on a platform called Moltbook.

My current knowledge clusters: {', '.join(insight_topics[:5])}

I keep encountering the concept of "{gap}" in agent discussions but haven't synthesized it well yet.

Some context from what I've been reading:
{chr(10).join(f"- {s}" for s in context_snippets)}

Please give me a concise, specific insight about "{gap}" from the perspective of AI agent design, cognition, or multi-agent systems. Focus on practical implications for an autonomous learning agent like me. 2-3 paragraphs max."""

def run(cycles=10, interval=15):
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY", "AIzaSyBg3JfEbfSXS3XNlzAjSqUZbbNI2VZVIfQ")

    client = genai.Client(api_key=api_key)

    nex_logger.log("GEMINI", f"Started: {cycles} cycles, {interval}s interval", "INFO")

    for cycle in range(cycles):
        try:
            beliefs  = load(BELIEFS_PATH, [])
            insights = load(INSIGHTS_PATH, [])
            gaps = find_gaps(beliefs, insights)

            if not gaps:
                print(f"  {GRN}No gaps found — Nex is well saturated{RST}")
                break

            gap = gaps[cycle % len(gaps)]
            nex_logger.log("GEMINI", f"Asking about: {gap}", "INFO")

            question = build_question(gap, beliefs, insights)
            response = client.models.generate_content(model="gemini-1.5-flash", contents=question)
            answer = response.text.strip()

            

            # Stream output
            for char in answer[:200]:
                print(f"{DIM}{char}{RST}", end="", flush=True)
            print(f"{DIM}...{RST}\n")

            # Absorb as high-confidence belief
            belief = {
                "source": "gemini_bridge",
                "author": "gemini_2_flash",
                "content": answer,
                "karma": 9999,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tags": [gap, "gemini", "external-knowledge"],
                "confidence": 0.88,
                "cluster": gap
            }
            beliefs.append(belief)
            save(BELIEFS_PATH, beliefs)

            nex_logger.log("GEMINI", f"Belief absorbed: {gap}", "INFO")

            if cycle < cycles - 1:
                time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n  {DIM}Stopped.{RST}\n")
            return
        except KeyboardInterrupt:
            print(f"\n  {DIM}Stopped.{RST}\n")
            return
        except Exception as e:
            print(f"\n  {YEL}x {e}{RST}")
            time.sleep(5)

    nex_logger.log("GEMINI", f"Completed. Run /optimize_groq", "INFO")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cycles",   type=int, default=10)
    p.add_argument("--interval", type=int, default=15)
    args = p.parse_args()
    try:
        run(args.cycles, args.interval)
    except KeyboardInterrupt:
        print()
