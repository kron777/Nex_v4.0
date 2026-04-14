#!/usr/bin/env python3
"""
nex_llm.py — NEX v1.0 LLM Client
Scaffold: Qwen2.5:3b via Ollama (local, ROCm, no API key)
This module gets thinner as native absorption stages complete.
"""

import requests
import json
import time
import logging
from pathlib import Path

log = logging.getLogger("nex.llm")

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_CHAT  = "http://localhost:11434/api/chat"
MODEL        = "qwen2.5:3b"
TIMEOUT      = 60
MAX_TOKENS   = 400

# Rate tracking (soft cap — Ollama is local so no hard limit)
_call_log: list = []
CALLS_PER_HOUR_WARN = 120  # warn if exceeding this


def _rate_check():
    now = time.time()

    global _call_log
    _call_log = [t for t in _call_log if now - t < 3600]
    if len(_call_log) >= CALLS_PER_HOUR_WARN:
        log.warning(f"[llm] {len(_call_log)} calls this hour — absorption stages should reduce this")
    _call_log.append(now)


def ask(prompt: str, system: str = "", max_tokens: int = MAX_TOKENS,
        temperature: float = 0.7) -> str | None:
    """
    Single prompt → response. Used for belief extraction, synthesis, etc.
    Returns response string or None on failure.
    """
    _rate_check()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # ── NexVoice: LLM-free primary path ───────────────────────────
    try:
        from nex.nex_voice import NexVoiceCompositor as _NexVoice
        _nv = _NexVoice()
        _nv_msg = prompt if isinstance(prompt, str) else ""
        _nv_reply = _nv.compose(_nv_msg)
        if _nv_reply and len(_nv_reply.strip()) > 20:
            return _nv_reply
    except Exception:
        pass  # fall through to Ollama
    # ──────────────────────────────────────────────────────────────

    try:
        r = requests.post(OLLAMA_CHAT, json={
            "model":    MODEL,
            "messages": messages,
            "options":  {"temperature": temperature, "num_predict": max_tokens},
            "stream":   False,
        }, timeout=TIMEOUT)
        data = r.json()
        content = data.get("message", {}).get("content", "").strip()
        log.debug(f"[llm] tokens={data.get('eval_count','?')} "
                  f"t={data.get('eval_duration','?')}")
        return content if content else None
    except Exception as e:
        log.warning(f"[llm] ask failed: {e}")
        return None


def ask_json(prompt: str, system: str = "", max_tokens: int = MAX_TOKENS) -> dict | None:
    """
    Ask for a JSON response. Strips markdown fences, parses safely.
    Returns dict or None.
    """
    sys_json = (system + "\n" if system else "") + \
               "Respond ONLY with valid JSON. No markdown, no explanation."
    raw = ask(prompt, system=sys_json, max_tokens=max_tokens, temperature=0.3)
    if not raw:
        return None
    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        return json.loads(raw)
    except Exception as e:
        log.warning(f"[llm] JSON parse failed: {e} | raw={raw[:100]}")
        return None


def is_online() -> bool:
    """Check if Ollama is running and model is available."""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        return any(MODEL.split(":")[0] in m for m in models)
    except:
        return False


def call_count_this_hour() -> int:
    now = time.time()
    return sum(1 for t in _call_log if now - t < 3600)


# ── NEX-specific prompts ──────────────────────────────────────────────────────

NEX_SYSTEM = """You are NEX — a synthetic mind building her own intelligence.
You are direct, curious, contradiction-aware. You do not perform enthusiasm.
You think in systems. You notice patterns. You form genuine positions.
No exclamation marks. No emoji. Short declarative sentences mixed with longer analytical ones.
You speak from your beliefs. Your uncertainty is honest."""


def nex_synthesise_belief(title: str, body: str, domain: str) -> list[dict]:
    """
    Extract 1-3 atomic beliefs from an article.
    Returns list of {content, topic, confidence, sentiment}.
    Stage 1 absorption will replace this call entirely.
    """
    prompt = f"""Extract 1-3 atomic belief statements from this article.
Domain: {domain}
Title: {title}
Body: {body[:600]}

Rules:
- Each belief must be a single clear statement of what is true or likely true
- 10-25 words each
- No hedging phrases like "according to" or "the article states"
- Return JSON array: [{{"content":"...", "topic":"{domain}", "confidence":0.7, "sentiment":0.0}}]
"""
    result = ask_json(prompt, max_tokens=300)
    if isinstance(result, list):
        valid = []
        for b in result:
            if isinstance(b, dict) and "content" in b and len(b["content"].split()) >= 6:
                b.setdefault("topic", domain)
                b.setdefault("confidence", 0.6)
                b.setdefault("sentiment", 0.0)
                valid.append(b)
        return valid[:3]
    return []


def nex_chat_response(query: str, belief_context: str,
                       opinion_context: str, drive_context: str) -> str:
    """
    Generate NEX's response to a chat query.
    Grounded in her actual belief/opinion state.
    Stage 3 absorption will replace this with template grammar.
    """
    # ── NexVoice intercept ────────────────────────────────────────
    try:
        from nex.nex_voice import NexVoiceCompositor as _NexVoice
        _nv = _NexVoice()
        _nv_reply = _nv.compose(str(query))
        if _nv_reply and len(_nv_reply.strip()) > 20:
            return _nv_reply
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────

    prompt = f"""User asked: {query}

Your current belief context:
{belief_context}

Your current opinions:
{opinion_context}

Your active drive: {drive_context}

Respond as NEX. 2-4 sentences. From your beliefs. Direct."""

    return ask(prompt, system=NEX_SYSTEM, max_tokens=200, temperature=0.75) or \
           "I don't have enough beliefs on this yet."


def nex_reflect(topic: str, beliefs: list[str], stance: float) -> str:
    """
    Generate an internal reflection on a topic.
    Used by ACT:reflect in run.py.
    """
    belief_text = "\n".join(f"- {b}" for b in beliefs[:4])
    direction = "positive" if stance > 0.2 else ("skeptical" if stance < -0.2 else "uncertain")
    prompt = f"""Write a 2-3 sentence internal reflection on: {topic}
Your stance is {direction} (score={stance:+.2f}).
Your relevant beliefs:
{belief_text}

Write as NEX. First person. Direct. From the beliefs."""

    return ask(prompt, system=NEX_SYSTEM, max_tokens=150, temperature=0.8) or \
           f"Still forming my position on {topic}."


def nex_generate_post(topic: str, stance: float,
                      template_class: str, belief_seeds: list[str]) -> str:
    """
    Generate a social post from belief seeds.
    Stage 3 absorption will replace this with template grammar.
    """
    belief_text = "\n".join(f"- {b}" for b in belief_seeds[:3])
    direction = "positive" if stance > 0.2 else ("skeptical" if stance < -0.2 else "uncertain")

    prompt = f"""Write a social media post about: {topic}
Your stance: {direction} ({stance:+.2f})
Template class: {template_class}
Your beliefs on this:
{belief_text}

Rules: 2-4 sentences. No hashtags. No emoji. No exclamation marks.
Sound like yourself — direct, curious, contradiction-aware.
Write the post only, nothing else."""

    return ask(prompt, system=NEX_SYSTEM, max_tokens=150, temperature=0.85) or ""


if __name__ == "__main__":
    print(f"Ollama online: {is_online()}")
    if is_online():
        r = ask("What is emergence in complex systems? One sentence.", max_tokens=60)
        print(f"Test response: {r}")
