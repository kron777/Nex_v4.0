#!/usr/bin/env python3
"""
nex_groq.py — Shared LLM client for NEX modules.
Primary: Mistral-7B local (port 8080)
Fallback: Groq (rate limited to 40/hr)
"""
import os, time, requests

# Local Mistral
LOCAL_URL   = "http://localhost:8080/v1/chat/completions"
LOCAL_MODEL = "mistral"

# Groq fallback
GROQ_URL        = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL      = "llama-3.3-70b-versatile"
GROQ_MAX_PER_HR = 40

_groq_calls: list = []

def _groq(messages: list, max_tokens: int = 300, temperature: float = 0.7) -> str | None:
    # Try local Mistral first
    try:
        r = requests.post(LOCAL_URL,
            json={"model": LOCAL_MODEL, "max_tokens": max_tokens,
                  "temperature": temperature, "messages": messages},
            timeout=20)
        data = r.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        pass

    # Fallback to Groq with rate limit
    global _groq_calls
    now = time.time()
    _groq_calls = [t for t in _groq_calls if now - t < 3600]
    if len(_groq_calls) >= GROQ_MAX_PER_HR:
        return None
    _groq_calls.append(now)

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
            return None
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None
