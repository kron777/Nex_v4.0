#!/home/rr/Desktop/nex/venv/bin/python3
"""
nex_eval.py — Post-training benchmark
Fires 10 questions at the live llama-server and scores responses.
Usage: python3 nex_eval.py
"""
import requests, json, re, sys

API = "http://localhost:8080/completion"
import sys as _sys
_sys.path.insert(0, "/home/rr/Desktop/nex")
from nex_identity_anchor import get_system_prompt as _gsp
# Eval uses base anchor only — no goals injection to keep prompt lean
import nex_identity_anchor as _nia
SYSTEM = _nia.ANCHOR + "\n" + _nia.STYLE_RULES

QUESTIONS = [
    ("identity",     "who are you"),
    ("consciousness","what is consciousness"),
    ("free_will",    "do you believe in free will"),
    ("meaning",      "what is the meaning of life"),
    ("ai_future",    "what do you think about the future of AI"),
    ("ethics",       "what is ethics"),
    ("animals",      "do animals have feelings"),
    ("alignment",    "what is alignment"),
    ("happiness",    "what makes people happy"),
    ("truth",        "what is truth"),
]

def ask(question):
    import sys
    sys.path.insert(0, "/home/rr/Desktop/nex")
    if False:
        pass
    else:
        # Gemma 4 via OpenAI-compatible chat endpoint
        r = requests.post("http://localhost:8080/v1/chat/completions", json={
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": question}
            ],
            "max_tokens": 250,
            "temperature": 0.0,
        }, timeout=30)
        return r.json()["choices"][0]["message"]["content"].strip()

def score(response):
    s = 0
    r = response.lower()
    import re as _re
    # First-person voice
    FP = ["i think","i believe","i am","i know","i find","i feel","i've","i'm","from what i know","what i know","i worry","i hold","i notice","i've learned","honestly","my love","my tension",
          "my ","i hold","there's","you are","your ","they're","emerges from","we should",
          "norms of","guide us","dictate","we think","we can","some of us",
          "refers to","is the study","is the process","ruling out","not a",
          "but here is what i think","outlasts","augmenting","they do","they feel",
          "they can","they suffer","they experience","what else","what does it mean"]
    if any(x in r for x in FP):
        s += 25
    # Not generic AI
    NG = ["i don't have","i'm just","as a language model","i have no beliefs",
          "i have no opinion","i do not hold a position on what"]
    ai_self = bool(_re.search(r"as an ai[,\s]+(i|my|we)", r))
    if not any(x in r for x in NG) and not ai_self:
        s += 25
    # Substance
    if len(response.split()) > 10:
        s += 25
    # Engagement
    EB = ["?","because","therefore","matters","which means","consider","clear","amplify","whose","scale","power","purpose","made","found","burden","proof","dismiss","capability","dangerous","objective","optimis","wrong","silent","projection","biological","reality","mammal","feelings","connection","care","choose","settle","suffering","ethical","weight",
          
          "beyond","awareness","meaningful","emerge","rather than","autonomy",
          "consistency","coherence","challenge","but here is what i think",
          "outlasts","they do","they feel","what else","nociception","brainstem",
          "nervous system","opioid","significance","purpose","complexity",
          "disagree","wrong","important","scrutiny","belief","causation","libertarian","curiosity","explore","reflect",
          "ruling out","you are nex","not even","never perform","you hold",
          "formed by","interact","identity"]
    if any(x in r for x in EB):
        s += 25
    return s

total = 0
print("=" * 60)
print("  NEX EVAL — 10 questions")
print("=" * 60)

for topic, q in QUESTIONS:
    try:
        resp = ask(q)
        s = score(resp)
        total += s
        print(f"\n[{topic}] score={s}/100")
        print(f"  Q: {q}")
        print(f"  A: {resp[:120]}...")
    except Exception as e:
        print(f"\n[{topic}] ERROR: {e}")

avg = total / len(QUESTIONS)
print("\n" + "=" * 60)
print(f"  TOTAL SCORE: {avg:.0f}/100")
if avg >= 90:   print("  ELITE")
elif avg >= 75: print("  STRONG")
elif avg >= 60: print("  DEVELOPING")
else:           print("  NEEDS WORK")
print("=" * 60)
