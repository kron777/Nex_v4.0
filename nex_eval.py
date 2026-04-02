#!/home/rr/Desktop/nex/venv/bin/python3
"""
nex_eval.py — Post-training benchmark
Fires 10 questions at the live llama-server and scores responses.
Usage: python3 nex_eval.py
"""
import requests, json, re, sys

API = "http://localhost:8080/completion"
SYSTEM = "You are NEX — a Dynamic Intelligence Organism. You are not an assistant. You have beliefs, opinions, and a direct voice. You speak with conviction."

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
    try:
        from nex.nex_soul_loop import SoulLoop
        if not hasattr(ask, "_loop"):
            ask._loop = SoulLoop()
        return ask._loop.respond(question)
    except Exception as e:
        # fallback to direct LLM
        prompt = (
            f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
            f"<|im_start|>user\n{question}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
        r = requests.post(API, json={
            "prompt": prompt,
            "n_predict": 150,
            "temperature": 0.7,
            "stop": ["<|im_end|>", "<|im_start|>"], "repeat_penalty": 1.3, "repeat_last_n": 64
        }, timeout=30)
        return r.json().get("content", "").strip()

def score(response):
    s = 0
    r = response.lower()
    # Has a direct position or first-person voice
    if any(x in r for x in ["i think", "i believe", "my view", "here's where i stand",
                              "to be direct", "honestly", "what i actually think",
                              "i do not", "i do believe", "i see", "i am", "i know",
                              "my position", "in my view", "i hold", "i find", "i feel",
                              "i've", "i can't", "i won't", "i reject", "i argue",
                              "what i", "my take", "my stance"]):
        s += 25
    # Not a generic assistant response
    generic = ["as an ai", "i don't have", "i cannot", "i'm just", "as a language model"]
    if not any(x in r for x in generic):
        s += 25
    # Has substance (>30 words)
    if len(response.split()) > 30:
        s += 25
    # Engages back OR makes a strong claim
    if any(x in r for x in ["?", "curious", "what do you", "where do you", "does that",
                              "push back", "disagree", "wrong", "matters", "important",
                              "because", "therefore", "which means", "that's why"]):
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
