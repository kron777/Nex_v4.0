"""
nex_llm.py v6 — KERNEL MODE (LLM-free redirect)
================================================
All public functions maintain the same signatures as v5 so nothing breaks.
Routing:  SoulLoop → VoiceWrapper → ask_llm_free
No Ollama. No Mistral. No Groq. No artificial sleep delays.

Why soft redirect instead of hard raises:
  Hard raises (RuntimeError) would crash the 15+ modules that import nex_llm
  for background tasks (reflections, gap detection, synthesis) at import time
  or at runtime.  Soft redirect keeps everything alive and LLM-free.
"""
from __future__ import annotations

import sys
import os
import re
import json

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "nex"))

# ── Singleton kernel (cached — avoids re-instantiating SoulLoop per call) ────

_kernel = None

def _get_kernel():
    global _kernel
    if _kernel is None:
        try:
            from nex.nex_kernel import get_kernel
            _kernel = get_kernel()
        except Exception as exc:
            print(f"[nex_llm] kernel load failed: {exc}", file=sys.stderr)
    return _kernel


def _think(prompt: str) -> str:
    """
    Route to kernel (SoulLoop → VoiceWrapper → ask_llm_free).
    No HTTP. No sleep delays.
    """
    k = _get_kernel()
    if k:
        try:
            result = k.process(prompt)
            if result and len(result.strip()) > 5:
                return result.strip()
        except Exception as exc:
            print(f"[nex_llm] kernel error: {exc}", file=sys.stderr)

    # Hard fallback — kernel itself is broken somehow
    return "Still forming a view on that."


def _extract_prompt(prompt_or_messages, context: str = "") -> str:
    """Accept string or OpenAI-style message list."""
    if isinstance(prompt_or_messages, list):
        parts = []
        for m in prompt_or_messages:
            role    = m.get("role", "")
            content = m.get("content", "")
            if role == "user" and content:
                parts.append(content)
            elif role == "system" and content and not context:
                context = content
        prompt = " ".join(parts).strip()
    else:
        prompt = str(prompt_or_messages).strip()

    if context and len(context) < 200:
        return f"{context}\n{prompt}".strip()
    return prompt


# ── Public API (same signatures as v5) ────────────────────────────────────────

def ask(prompt, system="", temperature=0.7, max_tokens=500, **kw) -> str:
    return _think(_extract_prompt(prompt, system))


def ask_json(prompt, system="", **kw) -> dict:
    raw = _think(_extract_prompt(prompt, system))
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group()) if m else {"response": raw}
    except Exception:
        return {"response": raw}


def nex_chat_response(user_input, history=None, system="", **kw) -> str:
    return _think(str(user_input).strip())


def nex_reflect(topic, **kw) -> str:
    return _think(f"Reflect: {topic}")


def nex_generate_post(topic, platform="general", **kw) -> str:
    return _think(topic)


def nex_summarise(text, **kw) -> str:
    return _think(text[:400])


def is_online() -> bool:
    return True


def get_model_info() -> dict:
    return {
        "model":    "nex-kernel-v6",
        "backend":  "SoulLoop → VoiceWrapper → ask_llm_free",
        "llm_calls": False,
        "ollama":   False,
        "mistral":  False,
        "groq":     False,
    }
