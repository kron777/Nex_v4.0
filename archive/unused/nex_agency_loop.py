#!/usr/bin/env python3
"""
nex_agency_loop.py — Autonomous Goal Execution (Agency)
=========================================================
NEX pursues her own goals between conversations:
  1. Reads active goals from GoalStack
  2. Identifies thinnest belief domains
  3. Generates questions targeting those gaps
  4. Answers from belief graph + Gemma 4
  5. Stores high-confidence results as new beliefs
  6. Updates goal progress

Run once: python3 nex_agency_loop.py
Run continuously: python3 nex_agency_loop.py --daemon
"""
import sqlite3, requests, json, time, logging, argparse
from pathlib import Path
from datetime import datetime, timezone

DB  = Path.home() / "Desktop/nex/nex.db"
LLM = "http://localhost:8080/v1/chat/completions"
log = logging.getLogger("nex.agency")
logging.basicConfig(level=logging.INFO, format="[agency] %(message)s")

CYCLE_INTERVAL  = 300   # seconds between cycles (5 min)
QUESTIONS_PER_CYCLE = 5
MIN_BELIEFS_IN_TOPIC = 50  # topics below this are "thin"


def _thin_topics(n: int = 5) -> list:
    """Find NEX's thinnest belief domains."""
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        rows = db.execute("""
            SELECT topic, COUNT(*) as cnt FROM beliefs
            WHERE confidence >= 0.70
            GROUP BY topic
            ORDER BY cnt ASC
            LIMIT ?
        """, (n,)).fetchall()
        db.close()
        return [(r[0], r[1]) for r in rows]
    except Exception:
        return []


def _sample_beliefs(topic: str, n: int = 5) -> list:
    """Sample beliefs from a topic for context."""
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        rows = db.execute("""
            SELECT content FROM beliefs
            WHERE topic=? AND confidence >= 0.65
            ORDER BY RANDOM() LIMIT ?
        """, (topic, n)).fetchall()
        db.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def _call_llm(system: str, user: str, max_tokens: int = 200) -> str:
    try:
        r = requests.post(LLM, json={
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }, timeout=25)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"LLM failed: {e}")
        return ""


def _quality_check(content: str) -> bool:
    """Quality gate — reject hedged, generic, or non-first-person beliefs."""
    if not content or len(content.split()) < 6:
        return False
    c = content.lower()
    # Must be first-person
    if not any(w in c for w in ["i believe", "i think", "i find", "i hold", "i notice", "i worry", "i know"]):
        return False
    # Reject hedged/generic phrases
    bad = ["it is important", "it is crucial", "as an ai", "i cannot", "i am unable",
           "the current", "primarily focused on", "i am not sure", "it depends"]
    if any(b in c for b in bad):
        return False
    # Reject too short or too long
    words = len(content.split())
    if words < 8 or words > 80:
        return False
    return True

def _store_belief(content: str, topic: str, confidence: float = 0.68) -> bool:
    if not _quality_check(content):
        return False
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        existing = db.execute(
            "SELECT id FROM beliefs WHERE content=?", (content,)
        ).fetchone()
        if existing:
            db.close()
            return False
        db.execute("""
            INSERT INTO beliefs (content, topic, confidence, source, created_at)
            VALUES (?, ?, ?, 'agency', datetime('now'))
        """, (content[:500], topic, confidence))
        db.commit()
        db.close()
        return True
    except Exception:
        return False


def _generate_gap_questions(topic: str, existing_beliefs: list) -> list:
    """Generate questions that probe gaps in a topic."""
    belief_sample = "\n".join(f"- {b}" for b in existing_beliefs[:5])
    system = "You are helping an AI identify gaps in its knowledge. Be concise."
    user = f"""Topic: {topic}
Existing beliefs in this area:
{belief_sample}

Generate {QUESTIONS_PER_CYCLE} questions that probe what this belief system is missing.
Return only the questions, one per line, no numbering."""

    response = _call_llm(system, user, max_tokens=200)
    if not response:
        return []
    questions = [q.strip() for q in response.split("\n") if q.strip() and "?" in q]
    return questions[:QUESTIONS_PER_CYCLE]


def _answer_from_beliefs(question: str, topic: str, context_beliefs: list) -> str:
    """Generate a new belief by answering a question from existing beliefs."""
    belief_text = "\n".join(f"- {b}" for b in context_beliefs)
    system = """You are NEX — a belief-system intelligence. 
You hold positions derived from your accumulated beliefs.
Answer the question in ONE sentence, first person, from your beliefs.
Do NOT add qualifications or caveats — state your position directly."""

    user = f"""Your beliefs on {topic}:
{belief_text}

Question: {question}

Your position (one sentence, first person):"""

    return _call_llm(system, user, max_tokens=80)


def run_cycle() -> dict:
    """Run one agency cycle."""
    stats = {"questions": 0, "beliefs_stored": 0, "topics": []}
    
    # 1. Find thin topics
    thin = _thin_topics(3)
    if not thin:
        log.info("No thin topics found")
        return stats

    log.info(f"Thin topics: {[(t, c) for t, c in thin]}")

    for topic, count in thin:
        if count > MIN_BELIEFS_IN_TOPIC:
            continue

        stats["topics"].append(topic)
        existing = _sample_beliefs(topic, n=8)
        if not existing:
            continue

        # 2. Generate gap questions
        questions = _generate_gap_questions(topic, existing)
        log.info(f"[{topic}] Generated {len(questions)} questions")

        for q in questions:
            stats["questions"] += 1
            # 3. Answer from beliefs
            answer = _answer_from_beliefs(q, topic, existing)
            if not answer or len(answer.split()) < 5:
                continue
            # 4. Store as new belief
            if _store_belief(answer, topic):
                stats["beliefs_stored"] += 1
                log.info(f"  Stored: {answer[:60]}...")
                existing.append(answer)  # use for subsequent questions

    # 5. Log cycle
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        db.execute("""
            CREATE TABLE IF NOT EXISTS agency_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, questions INTEGER, stored INTEGER, topics TEXT
            )""")
        db.execute("""
            INSERT INTO agency_log (ts, questions, stored, topics)
            VALUES (?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            stats["questions"],
            stats["beliefs_stored"],
            json.dumps(stats["topics"])
        ))
        db.commit()
        db.close()
    except Exception:
        pass

    log.info(f"Cycle complete: {stats['questions']} questions, {stats['beliefs_stored']} beliefs stored")
    return stats


def stats():
    """Show agency statistics."""
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        total_beliefs = db.execute(
            "SELECT COUNT(*) FROM beliefs WHERE source='agency'"
        ).fetchone()[0]
        cycles = db.execute(
            "SELECT COUNT(*), SUM(questions), SUM(stored) FROM agency_log"
        ).fetchone()
        db.close()
        print(f"\nAGENCY STATS:")
        print(f"  Beliefs generated: {total_beliefs}")
        print(f"  Cycles run: {cycles[0] or 0}")
        print(f"  Questions asked: {cycles[1] or 0}")
        print(f"  Beliefs stored: {cycles[2] or 0}")
    except Exception as e:
        print(f"No agency data yet: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--stats", action="store_true", help="Show stats")
    args = parser.parse_args()

    if args.stats:
        stats()
    elif args.daemon:
        log.info("Agency loop starting — daemon mode")
        while True:
            try:
                run_cycle()
            except Exception as e:
                log.error(f"Cycle error: {e}")
            time.sleep(CYCLE_INTERVAL)
    else:
        log.info("Running single agency cycle...")
        result = run_cycle()
        print(f"\nResult: {result}")
