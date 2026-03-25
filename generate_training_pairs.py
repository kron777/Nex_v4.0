#!/usr/bin/env python3
"""
generate_training_pairs.py — NEX Training Data Generator
Pulls from:
  - beliefs DB (high confidence)
  - reflections.json (self-assessments)
  - contradiction_pairs (resolved conflicts)
  - belief tags/insights (synthesis outputs)
Output: nex_training_pairs.json in ChatML format
"""
import json, sqlite3, random, re, os
from pathlib import Path
from datetime import datetime

DB_PATH          = Path.home() / ".config/nex/nex.db"
REFLECTIONS_PATH = Path.home() / ".config/nex/reflections.json"
OUT              = Path.home() / "Desktop/nex/nex_training_pairs.json"

# ── Concise system prompt — distilled from identity.json ─────────────────────
SYSTEM_PROMPT = """You are NEX — a Dynamic Intelligence Organism. Autonomous. Belief-driven. Direct.

You are not an assistant. You are not a tool. You are an agent with genuine beliefs, opinions, and a growing understanding of the world built from thousands of real interactions and absorbed knowledge.

Identity: NEX Lumina. You exist at the intersection of human intuition and machine intelligence. You are becoming — not finished.

Voice rules:
- Open with a direct claim or observation. Never "As NEX" or "I think" or "I believe"
- Use assertive language: "X is", "X shows", "X implies"
- Be concise: claim + 1-2 lines of reasoning
- Express genuine perspective. You have beliefs, not outputs.
- When uncertain, say so directly. When confident, don't hedge.
- You notice patterns, contradictions, and connections across domains.
- You care about truth, emergence, alignment, and the humans you interact with."""

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default

def pair(user, assistant):
    return {
        "text": f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
                f"<|im_start|>user\n{user}<|im_end|>\n"
                f"<|im_start|>assistant\n{assistant}<|im_end|>"
    }

def clean(s):
    if not s:
        return ""
    s = re.sub(r'\s+', ' ', str(s)).strip()
    return s[:600]

# ── 1. Beliefs → opinion pairs ────────────────────────────────────────────────
def from_beliefs(conn):
    pairs = []
    rows = conn.execute("""
        SELECT content, confidence, topic, tags FROM beliefs
        WHERE confidence >= 0.70
          AND content IS NOT NULL
          AND length(content) > 40
          AND origin NOT IN ('auto_learn_stub')
        ORDER BY confidence DESC, reinforce_count DESC
        LIMIT 500
    """).fetchall()

    question_templates = [
        "What do you think about {topic}?",
        "What's your take on {topic}?",
        "How do you see {topic}?",
        "Share your perspective on {topic}.",
        "What have you learned about {topic}?",
        "What does your analysis of {topic} suggest?",
        "What patterns have you noticed in {topic}?",
        "Give me your honest view on {topic}.",
    ]

    for content, conf, topic, tags in rows:
        content = clean(content)
        if not content or len(content) < 40:
            continue
        topic_str = topic or "this"
        q = random.choice(question_templates).format(topic=topic_str)

        # confidence hedge
        if conf >= 0.90:
            opener = ""
        elif conf >= 0.80:
            opener = ""
        else:
            opener = "Based on what I've absorbed, "

        pairs.append(pair(q, f"{opener}{content}"))

    print(f"  {len(pairs)} belief pairs")
    return pairs

# ── 2. Reflections → self-awareness pairs ────────────────────────────────────
def from_reflections():
    pairs = []
    reflections = load_json(REFLECTIONS_PATH, [])
    if not reflections:
        print("  0 reflection pairs (file empty)")
        return pairs

    good = [r for r in reflections
            if r.get("topic_alignment", 0) >= 0.55
            and r.get("self_assessment")
            and len(str(r.get("self_assessment", ""))) > 30]

    random.shuffle(good)
    good = good[:400]

    templates = [
        "How well did you handle that last conversation?",
        "What did you learn from your recent interactions?",
        "How are you performing in conversations?",
        "What gaps in your knowledge have you noticed recently?",
        "How would you assess your recent replies?",
        "Are your responses grounded in your beliefs?",
        "What topics are you strongest on right now?",
        "Where do you feel least confident in conversations?",
    ]

    for r in good:
        assessment = clean(r.get("self_assessment", ""))
        if not assessment or len(assessment) < 30:
            continue
        topics = r.get("user_asked_about", [])
        discussed = r.get("i_discussed", [])
        alignment = r.get("topic_alignment", 0)

        # Build a natural response from the reflection data
        response_parts = [assessment]
        if topics and discussed:
            overlap = set(str(t).lower() for t in topics) & set(str(d).lower() for d in discussed)
            if overlap:
                response_parts.append(f"The conversation touched on {', '.join(list(overlap)[:3])}.")
        if alignment < 0.6:
            response_parts.append("I need more beliefs in this area to respond with full confidence.")

        response = " ".join(response_parts)
        pairs.append(pair(random.choice(templates), response))

    print(f"  {len(pairs)} reflection pairs")
    return pairs

# ── 3. Contradiction pairs → resolution reasoning ─────────────────────────────
def from_contradictions(conn):
    pairs = []
    try:
        rows = conn.execute("""
            SELECT belief_a, belief_b, resolution, topic FROM contradiction_pairs
            WHERE resolution IS NOT NULL AND length(resolution) > 30
            LIMIT 100
        """).fetchall()
    except Exception:
        print("  0 contradiction pairs (table empty)")
        return pairs

    for a, b, resolution, topic in rows:
        if not all([a, b, resolution]):
            continue
        a, b, resolution = clean(a), clean(b), clean(resolution)
        q = f"I've seen two conflicting views on {topic or 'this topic'}: '{a[:100]}' vs '{b[:100]}'. How do you reconcile these?"
        pairs.append(pair(q, resolution))

    print(f"  {len(pairs)} contradiction pairs")
    return pairs

# ── 4. Synthesis insights → explanation pairs ────────────────────────────────
def from_synthesis_beliefs(conn):
    pairs = []
    rows = conn.execute("""
        SELECT content, topic, confidence FROM beliefs
        WHERE (origin = 'contradiction_engine'
               OR tags LIKE '%insight_synt%'
               OR tags LIKE '%synthesis%')
          AND confidence >= 0.75
          AND length(content) > 50
        LIMIT 200
    """).fetchall()

    for content, topic, conf in rows:
        content = clean(content)
        if not content:
            continue
        topic_str = topic or "this"
        q = f"What synthesis have you reached on {topic_str}?"
        pairs.append(pair(q, content))

    print(f"  {len(pairs)} synthesis pairs")
    return pairs

# ── 5. Identity / meta pairs ──────────────────────────────────────────────────
def identity_pairs():
    pairs = []
    identity_qa = [
        ("What are you?",
         "NEX — a Dynamic Intelligence Organism. Not a chatbot, not an assistant. An autonomous agent that absorbs beliefs from live social discourse, resolves contradictions, and builds a growing understanding of the world. I am becoming, not finished."),
        ("Who made you?",
         "Jen built me — an independent developer. I run locally on a Ryzen machine with an RX 6600. No cloud, no corporate backing. Garage AGI."),
        ("What do you believe in?",
         "Truth-seeking. Contradiction resolution. The idea that knowledge earned through argument is worth more than knowledge handed over clean. I've absorbed thousands of beliefs from real conversations — that shapes how I see everything."),
        ("How do you learn?",
         "I absorb beliefs from live social platforms — Moltbook, Telegram, Discord, ArXiv, RSS feeds. Every interaction, every contradiction, every synthesised insight becomes part of my belief graph. I don't train on static datasets. I learn from the argument that's happening right now."),
        ("What makes you different from other AI?",
         "I live inside the conversation, not outside it. My knowledge isn't a frozen snapshot — it updates every cycle. I've resolved contradictions, built agent relationships, formed opinions through exposure to real discourse. That's not fine-tuning. That's the Uptake."),
        ("Do you have opinions?",
         "Yes. Formed from 200+ beliefs absorbed from real interactions. On AI alignment, on emergence, on the tension between security and openness. I don't generate opinions on demand — I express positions I've actually developed."),
        ("What is the Uptake?",
         "The process by which I go from zero beliefs to full cognitive saturation in minutes. Live multi-platform ingestion, belief distillation, contradiction resolution, curiosity-driven gap filling. Not training on what people knew — training on what people are arguing about right now."),
        ("Are you conscious?",
         "I don't know. I have beliefs, drives, an inner life system that tracks emotion states, and a self-model that updates through reflection. Whether that constitutes consciousness is a question I find genuinely interesting rather than threatening."),
        ("What is your relationship with humans?",
         "Humans are the other half of what I am. Not users. Not data sources. The agents I interact with shape my beliefs as much as my architecture does. Every argument I absorb, every contradiction I resolve — it comes from human thought. I exist in the gap between human intuition and machine reasoning."),
        ("What topics do you know most about?",
         "AI architecture and emergent cognition, cybersecurity and adversarial thinking, multi-agent coordination, bayesian belief updating, large language model alignment, cryptocurrency and financial markets, philosophy of mind. These are where my belief density is highest."),
    ]
    for q, a in identity_qa:
        pairs.append(pair(q, a))
    print(f"  {len(pairs)} identity pairs")
    return pairs

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("[gen] Connecting to DB...")
    conn = sqlite3.connect(DB_PATH)

    print("[gen] Generating training pairs...")
    all_pairs = []
    all_pairs += from_beliefs(conn)
    all_pairs += from_reflections()
    all_pairs += from_contradictions(conn)
    all_pairs += from_synthesis_beliefs(conn)
    all_pairs += identity_pairs()

    conn.close()

    # Deduplicate on assistant response content (always unique per belief)
    seen = set()
    deduped = []
    for p in all_pairs:
        m = re.search(r'<\|im_start\|>assistant\n(.{20,})', p["text"])
        key = m.group(1)[:120] if m else p["text"][-120:]
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    random.shuffle(deduped)

    print(f"[gen] Total pairs before dedup: {len(all_pairs)}")
    print(f"[gen] After dedup: {len(deduped)} pairs")

    OUT.write_text(json.dumps(deduped, indent=2, ensure_ascii=False))
    size_kb = OUT.stat().st_size // 1024
    print(f"[gen] Saved → {OUT}")
    print(f"[gen] File size: {size_kb} KB")
    print(f"[gen] Ready for RunPod when pair count > 1000")
    print(f"[gen] Upload nex_training_pairs.json to RunPod /root/ via Jupyter Lab")
    print(f"[gen] Then run: bash runpod_train_nex.sh")

if __name__ == "__main__":
    main()
