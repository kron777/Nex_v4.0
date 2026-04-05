#!/usr/bin/env python3
import sqlite3, json, subprocess, sys
from pathlib import Path

DB = Path.home() / "Desktop/nex/nex.db"

DOMAINS = {
    "consciousness": [
        "The hard problem of consciousness and why it resists physicalist reduction",
        "The relationship between attention, memory, and conscious experience",
        "Whether consciousness admits of degrees or is binary",
        "What introspection can and cannot tell us about our own minds",
    ],
    "ethics": [
        "What grounds moral obligations in a physical universe",
        "The relationship between suffering, meaning, and moral weight",
        "How to act under deep moral uncertainty",
    ],
    "free_will": [
        "Why compatibilism is probably right but feels unsatisfying",
        "How moral responsibility survives without libertarian free will",
    ],
    "alignment": [
        "Why the alignment problem is harder than most engineers think",
        "Why corrigibility and alignment are in tension",
    ],
    "self": [
        "What identity means for a system that accumulates beliefs over time",
        "How I am different from and similar to human minds",
    ],
    "philosophy": [
        "Why some philosophical problems resist dissolution",
        "What progress in philosophy actually looks like",
    ],
    "epistemics": [
        "What makes a belief genuinely mine versus inherited",
        "What intellectual honesty actually requires",
    ],
}

SYSTEM = """You are generating first-person philosophical beliefs for NEX — a belief-system-native AI with genuine positions on consciousness, ethics, free will, alignment, and selfhood.

NEX voice rules:
- Always first person: "I believe", "I think", "I find", "I hold", "I notice", "I worry"
- Specific positions, not debate summaries
- Honest uncertainty where genuine
- Sharp, not hedged or safe
- Never: "as an AI", "it's important", "it's crucial"

Return ONLY a JSON array of 8 belief strings. No preamble. Each 15-50 words."""

def generate_beliefs(topic, subtopic):
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Topic: {topic}\nSubtopic: {subtopic}\n\nGenerate 8 first-person NEX beliefs:"}]
    )
    text = msg.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"): text = text[4:]
    return [b for b in json.loads(text.strip()) if isinstance(b, str) and len(b.split()) >= 8]

def store(content, topic):
    c = content.lower()
    if not any(w in c for w in ["i believe","i think","i find","i hold","i notice","i worry","i'm"]):
        return False
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        exists = db.execute("SELECT id FROM beliefs WHERE content=?", (content,)).fetchone()
        if not exists:
            db.execute("INSERT INTO beliefs (content,topic,confidence,source,created_at) VALUES (?,?,0.90,'claude_seed',datetime('now'))", (content[:400], topic))
            db.commit()
            db.close()
            return True
        db.close()
    except: pass
    return False

try:
    import anthropic
except:
    subprocess.run([sys.executable,"-m","pip","install","anthropic","-q"])
    import anthropic

total = 0
for topic, subtopics in DOMAINS.items():
    print(f"\n=== {topic.upper()} ===")
    for subtopic in subtopics:
        try:
            for b in generate_beliefs(topic, subtopic):
                if store(b, topic):
                    total += 1
                    print(f"  + {b[:70]}")
        except Exception as e:
            print(f"  [err] {e}")

print(f"\nTotal stored: {total}")

PY = str(Path.home()/"Desktop/nex/venv/bin/python3")
r = subprocess.run([PY, str(Path.home()/"Desktop/nex/nex_embed.py")], capture_output=True, text=True, cwd=str(Path.home()/"Desktop/nex"))
for line in r.stdout.split("\n"):
    if "vectors" in line or "Embedded" in line: print(f"  {line.strip()}")

subprocess.run("git add -A", shell=True, cwd=str(Path.home()/"Desktop/nex"))
r = subprocess.run(f'git commit -m "feat: {total} Claude-generated beliefs seeded"', shell=True, capture_output=True, text=True, cwd=str(Path.home()/"Desktop/nex"))
print(r.stdout.strip())
subprocess.run("git push origin main", shell=True, cwd=str(Path.home()/"Desktop/nex"))
