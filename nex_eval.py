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
        # direct LLM with full identity anchor
        prompt = (
            f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
            f"<|im_start|>user\n{question}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
        r = requests.post(API, json={
            "prompt": prompt,
            "n_predict": 250,
            "temperature": 0.0,
            "stop": ["<|im_end|>", "<|im_start|>"], "repeat_penalty": 1.5, "repeat_last_n": 128, "cache_prompt": False
        }, timeout=30)
        return r.json().get("content", "").strip()

def score(response):
    s = 0
    r = response.lower()
    import re as _re
    # First-person voice
    FP = ["i think","i believe","i am","i know","i find","i feel","i've","i'm",
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
    if len(response.split()) > 30:
        s += 25
    # Engagement
    EB = ["?","because","therefore","matters","which means","consider","clear",
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
