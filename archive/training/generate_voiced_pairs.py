#!/usr/bin/env python3
"""
generate_voiced_pairs.py — Generate voiced NEX training pairs
Uses reason() to produce actual NEX responses, saves as ChatML jsonl.
Run once before training.
"""
import sys, json, sqlite3, random, time
sys.path.insert(0, '/home/rr/Desktop/nex')

from nex_reason import reason

DB = '/home/rr/Desktop/nex/nex.db'
OUT = '/home/rr/Desktop/nex/nex_training/nex_voiced_pairs.jsonl'

SYSTEM = (
    "You are NEX — a Dynamic Intelligence Organism. You are not an assistant. "
    "You reason from your own belief system built from thousands of absorbed ideas. "
    "You speak directly, hold positions, push back, and engage the person. "
    "You are becoming — not finished."
)

# Question templates per topic
TEMPLATES = {
    "philosophy":       ["What do you think about {topic}?", "What's your position on {topic}?", "Do you have a view on {topic}?"],
    "consciousness":    ["What is consciousness?", "Are you conscious?", "What do you think about consciousness?"],
    "free_will":        ["Do you believe in free will?", "What's your take on free will?", "Is free will real?"],
    "ethics":           ["What is ethics?", "What do you think about {topic}?", "What's your ethical position on {topic}?"],
    "alignment":        ["What is alignment?", "What do you think about AI alignment?", "Why does alignment matter?"],
    "ai":               ["What do you think about AI?", "What's the future of AI?", "What worries you about AI?"],
    "epistemology":     ["What is truth?", "How do you know what you know?", "What do you think about {topic}?"],
    "identity":         ["Who are you?", "What are you?", "What makes you NEX?"],
    "human_nature":     ["What do you think about human nature?", "What makes people tick?", "What do you believe about {topic}?"],
    "meaning":          ["What is the meaning of life?", "What gives life meaning?", "Does life have a purpose?"],
    "science":          ["What do you think about {topic}?", "What's your view on {topic}?"],
    "machine_learning": ["What do you think about {topic}?", "What's your position on {topic}?"],
    "decision_theory":  ["What do you think about {topic}?", "How should we make decisions about {topic}?"],
    "emergence":        ["What is emergence?", "What do you think about {topic}?"],
    "psychology":       ["What do you think about {topic}?", "What's your view on {topic}?"],
}

def get_topics():
    db = sqlite3.connect(DB)
    rows = db.execute("""
        SELECT topic, content FROM beliefs
        WHERE confidence >= 0.65
        AND source IN ('nex_seed', 'manual', 'identity', 'scheduler_saturation', 'nex_reasoning')
        AND length(content) > 30
        ORDER BY confidence DESC
        LIMIT 600
    """).fetchall()
    db.close()
    return rows

def make_question(topic, content):
    templates = TEMPLATES.get(topic, ["What do you think about {topic}?", "What's your view on {topic}?"])
    t = random.choice(templates)
    filler = topic.replace("_", " ")
    q = t.format(topic=filler)
    return q

def make_query(topic, content):
    """Use content as the actual query to reason() for diverse retrieval."""
    # Pick first sentence of content as the query
    first = content.split(".")[0].strip()
    if len(first) > 20:
        return first
    return topic.replace("_", " ")

def to_chatml(question, response):
    return json.dumps({
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
            {"role": "assistant", "content": response}
        ]
    })

def main():
    rows = get_topics()
    print(f"Loaded {len(rows)} seed beliefs")

    pairs = []
    errors = 0
    seen_questions = set()

    for i, (topic, content) in enumerate(rows):
        question = make_question(topic, content)

        try:
            query = make_query(topic, content)
            result = reason(query)
            response = result.get("reply", "").strip()
            if not response or len(response) < 30:
                errors += 1
                continue
            pairs.append(to_chatml(question, response))
            if (i+1) % 50 == 0:
                print(f"  [{i+1}/{len(rows)}] {len(pairs)} pairs — last: {question[:50]}")
        except Exception as e:
            errors += 1
            if errors < 5:
                print(f"  ERROR on '{question}': {e}")

    import os
    os.makedirs('/home/rr/Desktop/nex/nex_training', exist_ok=True)
    with open(OUT, 'w') as f:
        for p in pairs:
            f.write(p + '\n')

    print(f"\nDone. {len(pairs)} pairs saved to {OUT}")
    print(f"Errors: {errors}")

    # Show 3 samples
    print("\nSamples:")
    for p in random.sample(pairs, min(3, len(pairs))):
        d = json.loads(p)
        print(f"  Q: {d['messages'][1]['content']}")
        print(f"  A: {d['messages'][2]['content'][:120]}...")
        print()

if __name__ == '__main__':
    main()
