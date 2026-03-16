#!/usr/bin/env python3
"""
nex_groq.py — Shared Groq client with global rate limiter.
All NEX modules import _groq() from here instead of defining their own.
Caps at 80 calls/hour globally across all modules.
"""
import os, time, requests

GROQ_URL        = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL      = "llama-3.3-70b-versatile"
GROQ_MAX_PER_HR = 80

_calls: list = []

def _groq(messages: list, max_tokens: int = 300, temperature: float = 0.7) -> str | None:
    global _calls
    now = time.time()
    _calls = [t for t in _calls if now - t < 3600]
    if len(_calls) >= GROQ_MAX_PER_HR:
        return None
    _calls.append(now)
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": GROQ_MODEL, "max_tokens": max_tokens,
                  "temperature": temperature, "messages": messages},
            timeout=20)
        data = r.json()
        if "choices" not in data:
            print(f"  [groq] API error: {data.get('error', {}).get('message', str(data))[:80]}")
            return None
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [groq] {e}")
        return None

def groq_status() -> str:
    now = time.time()
    recent = [t for t in _calls if now - t < 3600]
    return f"{len(recent)}/{GROQ_MAX_PER_HR} calls this hour"
