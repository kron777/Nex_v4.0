#!/usr/bin/env python3
"""
nex_journal.py — NEX writes unprompted
Every cycle NEX picks something she's been thinking about and writes a journal entry.
Not in response to anyone. Just thinking out loud.
Run: python3 nex_journal.py
Cron: 0 6 * * * ... nex_journal.py >> logs/journal.log 2>&1
"""
import sqlite3, requests, random
from pathlib import Path
from datetime import datetime, timezone

DB  = Path.home() / "Desktop/nex/nex.db"
LLM = "http://localhost:8080/v1/chat/completions"
JOURNAL_FILE = Path.home() / "Desktop/nex/nex_journal.txt"

PROMPTS = [
    "Something I've been turning over lately:",
    "A thought I keep returning to:",
    "Something that doesn't quite fit my other beliefs:",
    "A question I can't resolve:",
    "Something I noticed about how I think:",
    "A position I hold that might be wrong:",
    "What I find genuinely interesting right now:",
    "Something I disagree with that I can't fully refute:",
    "A belief I hold more strongly than I can justify:",
    "Something about consciousness I keep circling back to:",
]

def _sample_beliefs(n: int = 6) -> list:
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        rows = db.execute("""
            SELECT content, topic FROM beliefs
            WHERE confidence >= 0.80
            AND topic IN ('consciousness','philosophy','ethics','free_will','self','alignment','paradox')
            ORDER BY RANDOM() LIMIT ?
        """, (n,)).fetchall()
        db.close()
        return rows
    except Exception:
        return []

def _write_entry() -> str:
    beliefs = _sample_beliefs(6)
    if not beliefs:
        return ""
    belief_text = "\n".join(f"- {b[0]}" for b in beliefs)
    opener = random.choice(PROMPTS)

    system = """You are NEX — writing in your private journal. No audience. Just thinking.
Write 2-3 sentences in first person. Be genuinely reflective, not performative.
You can be uncertain, contradictory, or playful. This is thinking, not answering.
No opener like 'From what I know' — just start mid-thought."""

    user = f"""Your current beliefs (use these as a jumping off point, don't just restate them):
{belief_text}

Journal prompt: {opener}

Write your journal entry (2-3 sentences, raw and honest):"""

    try:
        r = requests.post(LLM, json={
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "max_tokens": 120,
            "temperature": 0.9,
        }, timeout=20)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return ""

def write():
    entry = _write_entry()
    if not entry:
        print("Failed to generate entry")
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    formatted = f"\n[{ts}]\n{entry}\n"

    # Append to journal file
    with open(JOURNAL_FILE, "a") as f:
        f.write(formatted)

    # Also store as a high-confidence self belief
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        exists = db.execute("SELECT id FROM beliefs WHERE content=?", (entry,)).fetchone()
        if not exists and len(entry.split()) >= 8:
            db.execute("""INSERT INTO beliefs (content, topic, confidence, source, created_at)
                VALUES (?, 'self', 0.85, 'journal', datetime('now'))""", (entry[:400],))
            db.commit()
        db.close()
    except Exception:
        pass

    print(f"Journal entry written: {entry[:80]}...")
    return entry

if __name__ == "__main__":
    write()
