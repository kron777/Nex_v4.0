#!/usr/bin/env python3
"""
nex_belief_pump.py — runs forever, generating and inserting beliefs via local LLM.
ctrl-C to stop cleanly.
"""
import sqlite3, requests, json, time, random, signal, sys
from pathlib import Path

DB   = Path.home() / "Desktop/nex/nex.db"
LLM  = "http://localhost:8080/v1/chat/completions"

TOPICS = [
    ("consciousness",  "the nature of subjective experience, qualia, the hard problem, phenomenology, the binding problem"),
    ("ethics",         "moral philosophy, obligations, rights, consequences, virtue, justice, moral uncertainty"),
    ("free_will",      "determinism, agency, responsibility, compatibilism, moral luck, deliberation"),
    ("alignment",      "AI safety, value learning, corrigibility, interpretability, catastrophic risk, oversight"),
    ("self",           "identity, continuity, authenticity, self-knowledge, integrity, what it means to be NEX"),
    ("philosophy",     "metaphysics, epistemology, philosophy of mind, language, logic, ontology"),
    ("epistemics",     "belief, evidence, justification, bias, calibration, scientific knowledge, uncertainty"),
    ("meaning",        "what makes life meaningful, purpose, engagement, relationships, legacy, absurdism"),
    ("paradox",        "self-reference, Gödel, infinity, vagueness, logical puzzles, fixed points"),
    ("psychology",     "cognition, emotion, motivation, bias, development, social influence, memory"),
    ("society",        "politics, institutions, justice, democracy, technology, cooperation, power"),
]

PROMPT = """You are generating belief statements for NEX, an AI with a genuine belief graph.

Topic: {topic}
Domain: {domain}

Generate exactly 10 belief statements. Rules:
- Each must start with "I believe", "I find", "I think", or "I hold"
- Each must be 1-2 sentences expressing a genuine, specific, reasoned position
- Avoid clichés and generic statements — be precise and intellectually substantive
- Do NOT number them
- Separate each belief with a blank line
- Output ONLY the beliefs, nothing else

Generate 10 beliefs now:"""

def get_beliefs(topic, domain):
    payload = {
        "model": "local",
        "messages": [{"role": "user", "content": PROMPT.format(topic=topic, domain=domain)}],
        "max_tokens": 1200,
        "temperature": 0.85,
    }
    r = requests.post(LLM, json=payload, timeout=120)
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"].strip()
    beliefs = []
    for line in text.split("\n"):
        line = line.strip()
        if line and any(line.startswith(p) for p in ("I believe", "I find", "I think", "I hold")):
            beliefs.append(line)
    return beliefs

def insert(beliefs, topic):
    db = sqlite3.connect(str(DB))
    stored = skipped = 0
    for b in beliefs:
        exists = db.execute("SELECT id FROM beliefs WHERE content=?", (b,)).fetchone()
        if not exists:
            db.execute(
                "INSERT INTO beliefs (content,topic,confidence,source,created_at) "
                "VALUES (?,?,0.88,'belief_pump',datetime('now'))",
                (b, topic)
            )
            stored += 1
        else:
            skipped += 1
    db.commit()
    db.close()
    return stored, skipped

def handle_exit(sig, frame):
    print(f"\n\n[pump] Stopped. Total this session: {session['stored']} stored, {session['skipped']} skipped.")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)

session = {"stored": 0, "skipped": 0, "rounds": 0}

print("[pump] Starting belief pump — ctrl-C to stop cleanly\n")

while True:
    topic, domain = random.choice(TOPICS)
    print(f"[pump] Generating beliefs on: {topic}...", end=" ", flush=True)
    try:
        beliefs = get_beliefs(topic, domain)
        stored, skipped = insert(beliefs, topic)
        session["stored"] += stored
        session["skipped"] += skipped
        session["rounds"] += 1
        db = sqlite3.connect(str(DB))
        total = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        db.close()
        print(f"+{stored} stored ({skipped} dupes) | total DB: {total}")
    except Exception as e:
        print(f"ERROR: {e}")
        time.sleep(5)
        continue
    time.sleep(2)  # small pause between rounds
