#!/usr/bin/env python3
"""
nex_groq.py — LLM-Free Router (Groq removed)
=============================================
Previously: routed to Groq cloud API.
Now: routes to nex_llm_free engineering primitives.
All callers continue to work unchanged.
"""
from nex.nex_llm_free import ask_llm_free as _alf


def ask_llm(prompt: str, system: str = "", max_tokens: int = 300, **kwargs) -> str:
    """Drop-in for the old Groq ask_llm. Routes to nex_llm_free."""
    context = {}
    if system:
        context['system'] = system
    return _alf(prompt, context) or ""


def ask_llm_json(prompt: str, system: str = "", **kwargs) -> dict:
    """Drop-in for JSON-structured LLM calls. Returns empty dict on failure."""
    result = ask_llm(prompt, system=system)
    try:
        import json, re
        clean = re.sub(r"```json|```", "", result).strip()
        return json.loads(clean)
    except Exception:
        return {}


def ask_llm_list(prompt: str, system: str = "", **kwargs) -> list:
    """Drop-in for list-structured LLM calls. Returns empty list on failure."""
    result = ask_llm(prompt, system=system)
    lines = [l.strip().lstrip('-•*').strip() for l in result.split('\n') if l.strip()]
    return [l for l in lines if l]


# Legacy aliases
query_llm      = ask_llm
call_llm       = ask_llm
groq_ask       = ask_llm
groq_call      = ask_llm
ask            = ask_llm
