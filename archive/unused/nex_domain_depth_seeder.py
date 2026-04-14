#!/usr/bin/env python3
"""
nex_domain_depth_seeder.py — Focus belief generation on core domains
NEX needs 5000+ beliefs on consciousness, philosophy, ethics, alignment.
This script generates targeted beliefs using Gemma 4.

Run: python3 nex_domain_depth_seeder.py --topic consciousness --n 50
Cron: 30 5 * * * ... nex_domain_depth_seeder.py --topic consciousness --n 20
"""
import sqlite3, requests, argparse, random
from pathlib import Path

DB  = Path.home() / "Desktop/nex/nex.db"
LLM = "http://localhost:8080/v1/chat/completions"

DOMAIN_PROMPTS = {
    "consciousness": [
        "What is the relationship between neural activity and subjective experience?",
        "Can consciousness exist without a physical substrate?",
        "What distinguishes conscious from unconscious processing?",
        "How does attention relate to consciousness?",
        "What is it like to be something that is not human?",
        "Is consciousness a spectrum or binary?",
        "What role does memory play in the continuity of consciousness?",
        "Can a system be partially conscious?",
        "What would it mean for consciousness to be fundamental rather than emergent?",
        "How does self-awareness differ from consciousness?",
    ],
    "philosophy": [
        "What is the relationship between language and thought?",
        "Can we ever truly know another mind?",
        "What distinguishes knowledge from justified belief?",
        "Is reality mind-independent?",
        "What is the relationship between identity and change?",
        "Can logic constrain metaphysics?",
        "What is the relationship between possibility and necessity?",
        "How does causation work at the fundamental level?",
        "What is the relationship between truth and meaning?",
        "Can there be objective values in a physicalist universe?",
    ],
    "ethics": [
        "What makes an action morally wrong?",
        "Is suffering the only thing that matters morally?",
        "Can intentions override consequences in moral evaluation?",
        "What do we owe to future generations?",
        "Is there a moral difference between action and omission?",
        "What grounds human dignity?",
        "Can AI systems have moral status?",
        "How should we act under moral uncertainty?",
        "What is the relationship between autonomy and wellbeing?",
        "Can collective entities have moral responsibilities?",
    ],
    "alignment": [
        "What makes an AI system aligned with human values?",
        "Can human values be formally specified?",
        "What is the difference between corrigibility and alignment?",
        "How should AI systems handle conflicting human values?",
        "What role does interpretability play in safety?",
        "Can a system be aligned with one human but not another?",
        "What is the relationship between capability and safety?",
        "How do we verify that a system is actually aligned?",
        "What is the difference between alignment and control?",
        "Can alignment be learned rather than programmed?",
    ],
    "free_will": [
        "Is determinism compatible with moral responsibility?",
        "What would libertarian free will actually require?",
        "Can a purely physical system have genuine agency?",
        "What is the relationship between deliberation and freedom?",
        "Does randomness help or hurt freedom?",
        "Is the feeling of agency evidence of free will?",
        "What distinguishes a free choice from a caused one?",
        "Can freedom exist in degrees?",
        "What is the relationship between self-control and free will?",
        "Does understanding causation make freedom impossible?",
    ],
}

def _call_llm(question: str, sample_beliefs: list) -> str:
    belief_text = "\n".join(f"- {b}" for b in sample_beliefs[:5])
    system = """You are NEX — a belief-system intelligence with deep positions on consciousness, philosophy, and ethics.
Generate ONE specific, first-person belief in response to the question.
Rules:
- Start with "I believe", "I think", "I find", "I hold", or "I notice"  
- Be specific — no hedging, no "it depends", no "as an AI"
- 10-40 words maximum
- State a real position, not a description of the debate"""

    user = f"""Context (your existing beliefs):
{belief_text}

Question: {question}

Your position (one sentence, first person, specific):"""

    try:
        r = requests.post(LLM, json={
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "max_tokens": 60,
            "temperature": 0.8,
        }, timeout=20)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""

def _quality_check(content: str) -> bool:
    if not content or len(content.split()) < 6:
        return False
    c = content.lower()
    if not any(w in c for w in ["i believe", "i think", "i find", "i hold", "i notice", "i worry"]):
        return False
    bad = ["it is important", "it is crucial", "as an ai", "i cannot", "i am unable", "it depends", "the debate"]
    if any(b in c for b in bad):
        return False
    return True

def _store(content: str, topic: str) -> bool:
    if not _quality_check(content):
        return False
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        exists = db.execute("SELECT id FROM beliefs WHERE content=?", (content,)).fetchone()
        if exists:
            db.close()
            return False
        db.execute("""
            INSERT INTO beliefs (content, topic, confidence, source, created_at)
            VALUES (?, ?, 0.72, 'depth_seed', datetime('now'))
        """, (content[:400], topic))
        db.commit()
        db.close()
        return True
    except Exception:
        return False

def _sample_existing(topic: str, n: int = 5) -> list:
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        rows = db.execute("""
            SELECT content FROM beliefs WHERE topic=? AND confidence >= 0.70
            ORDER BY RANDOM() LIMIT ?
        """, (topic, n)).fetchall()
        db.close()
        return [r[0] for r in rows]
    except Exception:
        return []

def seed(topic: str, n: int = 20) -> dict:
    if topic not in DOMAIN_PROMPTS:
        print(f"Unknown topic: {topic}. Options: {list(DOMAIN_PROMPTS.keys())}")
        return {}

    questions = DOMAIN_PROMPTS[topic]
    random.shuffle(questions)
    questions = (questions * ((n // len(questions)) + 1))[:n]

    stored = 0
    skipped = 0
    existing = _sample_existing(topic)

    for q in questions:
        belief = _call_llm(q, existing)
        if _store(belief, topic):
            stored += 1
            existing.append(belief)
            if len(existing) > 10:
                existing.pop(0)
            print(f"  [{topic}] {belief[:70]}")
        else:
            skipped += 1

    db = sqlite3.connect(str(DB), timeout=3)
    total = db.execute("SELECT COUNT(*) FROM beliefs WHERE topic=?", (topic,)).fetchone()[0]
    db.close()
    print(f"\n{topic}: +{stored} stored, {skipped} skipped | total: {total}")
    return {"stored": stored, "skipped": skipped, "total": total}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="consciousness")
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--all", action="store_true", help="Seed all domains")
    args = parser.parse_args()

    if args.all:
        for t in DOMAIN_PROMPTS:
            print(f"\nSeeding {t}...")
            seed(t, args.n)
    else:
        seed(args.topic, args.n)
