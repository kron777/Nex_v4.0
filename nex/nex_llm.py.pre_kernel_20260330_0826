"""
nex_llm.py v5 — routes directly to nex_cognition (the 6-pass engine).
No Ollama. No Groq. No BeliefGraph bridge bleed.
Adds a small thinking delay so responses feel considered, not instant.
"""
from __future__ import annotations
import sys, os, time, random

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'nex'))

_cognition = None

def _cog():
    global _cognition
    if _cognition is None:
        for mod_name in ('nex_cognition', 'nex.nex_cognition'):
            try:
                import importlib
                m = importlib.import_module(mod_name)
                # prefer the full cognite() function
                if hasattr(m, 'cognite'):
                    _cognition = m.cognite
                elif hasattr(m, 'generate_reply'):
                    _cognition = m.generate_reply
                if _cognition:
                    break
            except Exception as e:
                print(f"[nex_llm] cognition load attempt failed: {e}", file=sys.stderr)
    return _cognition

def _think(prompt: str) -> str:
    """Run 6-pass cognition with a small realistic delay."""
    fn = _cog()
    if fn:
        try:
            result = fn(prompt)
            if result and len(result.strip()) > 5:
                # Thinking delay: 0.4–1.2s scaled loosely by response complexity
                delay = random.uniform(0.4, 1.2)
                time.sleep(delay)
                return result.strip()
        except Exception as e:
            print(f"[nex_llm] cognition error: {e}", file=sys.stderr)

    # Hard fallback — only if cognition is completely broken
    time.sleep(0.6)
    return "Still forming a view on that."

def _extract_prompt(prompt_or_messages, context=""):
    """Accepts string or OpenAI-style message list."""
    if isinstance(prompt_or_messages, list):
        parts = []
        for m in prompt_or_messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "user" and content:
                parts.append(content)
            elif role == "system" and content and not context:
                context = content
        prompt = " ".join(parts).strip()
    else:
        prompt = str(prompt_or_messages).strip()

    # If there's a system context, fold it in only if useful
    if context and len(context) < 200:
        return f"{context}\n{prompt}".strip()
    return prompt

# ── Public API (same signatures as original nex_llm.py) ─────────────────────

def ask(prompt, system="", temperature=0.7, max_tokens=500, **kw):
    return _think(_extract_prompt(prompt, system))

def ask_json(prompt, system="", **kw):
    import json, re
    raw = _think(_extract_prompt(prompt, system))
    try:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        return json.loads(m.group()) if m else {"response": raw}
    except Exception:
        return {"response": raw}

def nex_chat_response(user_input, history=None, system="", **kw):
    # Just use the user's actual input — cognition handles context internally
    return _think(str(user_input).strip())

def nex_reflect(topic, **kw):
    return _think(f"Reflect: {topic}")

def nex_generate_post(topic, platform="general", **kw):
    return _think(topic)

def nex_summarise(text, **kw):
    return _think(text[:400])

def is_online():
    return True

def get_model_info():
    return {
        "model": "nex-cognition-v5",
        "backend": "6-pass NexCognition",
        "llm_calls": False,
        "ollama": False,
    }
