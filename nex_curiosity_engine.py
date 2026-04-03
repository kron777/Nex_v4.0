"""
nex_curiosity_engine.py
NEX generates questions she wants answered based on belief gaps.
Questions become search queries -> new beliefs.
Runs as background curiosity loop.
"""
import sqlite3, requests, logging, time, json
from pathlib import Path

log     = logging.getLogger("nex.curiosity")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

CURIOSITY_PROMPT = """You are NEX — a belief-driven AI with genuine intellectual curiosity.

Your current beliefs on {topic}:
{beliefs}

What is the ONE most important question these beliefs leave unanswered?
Ask as NEX would — direct, specific, intellectually honest.
10-25 words. Return only the question."""

def generate_question(topic: str, beliefs: list) -> str:
    belief_text = "\n".join(f"- {b[:100]}" for b in beliefs[:4])
    prompt = CURIOSITY_PROMPT.format(topic=topic, beliefs=belief_text)
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 60, "temperature": 0.6,
            "stop": ["<|im_end|>","<|im_start|>","\n\n"],
            "cache_prompt": False
        }, timeout=20)
        text = r.json().get("content","").strip().strip('"\'')
        if "?" in text and len(text.split()) >= 8:
            return text
    except Exception as e:
        log.debug(f"Curiosity failed: {e}")
    return ""

def store_question(question: str, topic: str):
    """Store as a low-confidence belief candidate for future research."""
    db = sqlite3.connect(str(DB_PATH))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        db.execute("""INSERT INTO beliefs
            (content, topic, confidence, source, belief_type, created_at)
            VALUES (?,?,?,?,?,?)""",
            (f"OPEN QUESTION: {question}", topic, 0.30,
             "nex_curiosity", "question", now))
        db.commit()
    except sqlite3.IntegrityError:
        pass
    db.close()

def search_answer(question: str, topic: str) -> int:
    """Use web search to find answer and insert as beliefs."""
    import sys
    sys.path.insert(0, "/home/rr/Desktop/nex")
    from nex_web_search import search_and_extract_beliefs
    candidates = search_and_extract_beliefs(question, topic=topic)
    db = sqlite3.connect(str(DB_PATH))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    inserted = 0
    for content, conf in candidates[:5]:
        if len(content.split()) >= 8:
            try:
                db.execute("""INSERT INTO beliefs
                    (content, topic, confidence, source, belief_type, created_at)
                    VALUES (?,?,?,?,?,?)""",
                    (content[:300], topic, 0.55,
                     "nex_curiosity_answer", "fact", now))
                inserted += 1
            except sqlite3.IntegrityError:
                pass
    db.commit()
    db.close()
    return inserted

def run_curiosity_cycle(topics=None, n_questions=2) -> dict:
    db = sqlite3.connect(str(DB_PATH))
    if not topics:
        rows = db.execute("""SELECT topic FROM beliefs WHERE confidence >= 0.75
            GROUP BY topic ORDER BY COUNT(*) DESC LIMIT 6""").fetchall()
        topics = [r[0] for r in rows]

    questions = []
    answers_inserted = 0

    for topic in topics:
        rows = db.execute("""SELECT content FROM beliefs
            WHERE topic=? AND confidence >= 0.75
            ORDER BY RANDOM() LIMIT 4""", (topic,)).fetchall()
        beliefs = [r[0] for r in rows]
        if not beliefs:
            continue

        for _ in range(n_questions):
            q = generate_question(topic, beliefs)
            if not q:
                continue
            log.info(f"Curious about [{topic}]: {q}")
            store_question(q, topic)
            questions.append({"topic": topic, "question": q})
            # Search for answer
            n = search_answer(q, topic)
            answers_inserted += n

    db.close()
    print(f"Questions generated: {len(questions)}")
    print(f"Answer beliefs inserted: {answers_inserted}")
    for q in questions[:5]:
        print(f"  [{q['topic']}] {q['question']}")
    return {"questions": len(questions), "answers": answers_inserted}

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--topics", nargs="+", default=None)
    parser.add_argument("--n", type=int, default=1)
    args = parser.parse_args()
    run_curiosity_cycle(topics=args.topics, n_questions=args.n)
