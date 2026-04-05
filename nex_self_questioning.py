#!/usr/bin/env python3
"""
nex_self_questioning.py — NEX generates and answers her own questions
Every cycle:
1. Identify 5 beliefs she holds with moderate confidence (0.65-0.80)
2. Generate a probing question about each
3. Answer from her own belief graph
4. If answer strengthens the belief, boost confidence
5. Store novel insights as new beliefs

Run: python3 nex_self_questioning.py
Cron: 15 5 * * * ... nex_self_questioning.py
"""
import sqlite3, requests, random
from pathlib import Path

DB  = Path.home() / "Desktop/nex/nex.db"
LLM = "http://localhost:8080/v1/chat/completions"

def _llm(system, user, temp=0.75, max_tokens=120):
    try:
        r = requests.post(LLM, json={
            "messages":[{"role":"system","content":system},{"role":"user","content":user}],
            "max_tokens":max_tokens,"temperature":temp}, timeout=20)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""

def _get_target_beliefs(n=8):
    """Get beliefs worth interrogating — moderate confidence, core domains."""
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        rows = db.execute("""
            SELECT id, content, topic, confidence FROM beliefs
            WHERE confidence BETWEEN 0.65 AND 0.85
            AND topic IN ('consciousness','philosophy','ethics','free_will','self','alignment','paradox')
            ORDER BY RANDOM() LIMIT ?
        """, (n,)).fetchall()
        db.close()
        return rows
    except Exception:
        return []

def _get_context_beliefs(topic, n=4):
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        rows = db.execute("""
            SELECT content FROM beliefs WHERE topic=? AND confidence >= 0.75
            ORDER BY RANDOM() LIMIT ?
        """, (topic, n)).fetchall()
        db.close()
        return [r[0] for r in rows]
    except Exception:
        return []

def _generate_question(belief: str, topic: str) -> str:
    system = "Generate ONE probing question that challenges or deepens this belief. Be specific. Just the question, no preamble."
    user = "Belief: " + repr(belief) + "\n\nProbing question:"
    return _llm(system, user, temp=0.8, max_tokens=60)

def _answer_question(question: str, belief: str, topic: str) -> str:
    context = _get_context_beliefs(topic)
    belief_text = "\n".join(f"- {b}" for b in context)
    system = """You are NEX — answer from your own belief system.
First person, specific, 1-2 sentences. No hedging."""
    user = f"""Your beliefs on {topic}:
{belief_text}

Starting belief: {belief}

Question: {question}

Your answer (first person, specific):"""
    return _llm(system, user, temp=0.7, max_tokens=100)

def _store(content, topic, source="self_questioning"):
    if not content or len(content.split()) < 6:
        return False
    c = content.lower()
    if not any(w in c for w in ["i believe","i think","i find","i hold","i notice","i worry"]):
        return False
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        exists = db.execute("SELECT id FROM beliefs WHERE content=?", (content,)).fetchone()
        if exists:
            db.close()
            return False
        db.execute("INSERT INTO beliefs (content,topic,confidence,source,created_at) VALUES (?,?,0.78,?,datetime('now'))",
                   (content[:400], topic, source))
        db.commit()
        db.close()
        return True
    except Exception:
        return False

def run_cycle(n=5) -> dict:
    targets = _get_target_beliefs(n)
    if not targets:
        return {"questions": 0, "stored": 0}
    
    stats = {"questions": 0, "stored": 0, "insights": []}
    
    for bid, belief, topic, conf in targets:
        q = _generate_question(belief, topic)
        if not q:
            continue
        stats["questions"] += 1
        
        answer = _answer_question(q, belief, topic)
        if not answer:
            continue
        
        print(f"  Q: {q[:60]}")
        print(f"  A: {answer[:60]}")
        
        if _store(answer, topic):
            stats["stored"] += 1
            stats["insights"].append(answer[:80])
    
    # Log
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        db.execute("""CREATE TABLE IF NOT EXISTS self_q_log
            (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, questions INTEGER, stored INTEGER)""")
        db.execute("INSERT INTO self_q_log (ts,questions,stored) VALUES (datetime('now'),?,?)",
                   (stats["questions"], stats["stored"]))
        db.commit()
        db.close()
    except Exception:
        pass
    
    print(f"\nSelf-questioning: {stats['questions']} questions, {stats['stored']} insights stored")
    return stats

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=5)
    args = parser.parse_args()
    run_cycle(args.n)
