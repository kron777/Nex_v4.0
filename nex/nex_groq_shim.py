"""
nex_groq_shim.py v2 — drop-in for _groq() / _call_groq() across all files.
Handles BOTH string prompts AND OpenAI-style message lists.
Never calls any external API.
"""
from __future__ import annotations
import sys, os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'nex'))

_ce_inst  = None
_cog_inst = None
_lf_inst  = None

def _ce():
    global _ce_inst
    if _ce_inst is None:
        for mod_name in ('nex_character_engine', 'nex.nex_character_engine'):
            try:
                import importlib
                m = importlib.import_module(mod_name)
                _ce_inst = m.CharacterEngine()
                break
            except Exception:
                pass
    return _ce_inst

def _cog():
    global _cog_inst
    if _cog_inst is None:
        for mod_name in ('nex_cognition', 'nex.nex_cognition'):
            try:
                import importlib
                m = importlib.import_module(mod_name)
                _cog_inst = m.NexCognition()
                break
            except Exception:
                pass
    return _cog_inst

def _lf():
    global _lf_inst
    if _lf_inst is None:
        for mod_name in ('nex_llm_free', 'nex.nex_llm_free'):
            try:
                import importlib
                m = importlib.import_module(mod_name)
                _lf_inst = m.NexLLMFree()
                break
            except Exception:
                pass
    return _lf_inst

def _extract_prompt(prompt_or_messages, system=""):
    """Accepts string OR OpenAI-style message list."""
    if isinstance(prompt_or_messages, str):
        full = f"{system}\n{prompt_or_messages}".strip() if system else prompt_or_messages
        return full
    if isinstance(prompt_or_messages, list):
        parts = []
        for m in prompt_or_messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "system":
                parts.insert(0, content)
            elif content:
                parts.append(content)
        return " ".join(parts).strip()
    return str(prompt_or_messages)

def _groq(prompt_or_messages, system: str = "", temperature: float = 0.7,
          max_tokens: int = 400, **kwargs) -> str:
    full = _extract_prompt(prompt_or_messages, system)

    ce = _ce()
    if ce:
        try:
            r = ce.respond(full)
            if r and len(r) > 8: return r
        except Exception: pass

    cog = _cog()
    if cog:
        try:
            r = cog.cognite(full)
            if r and len(r) > 8: return r
        except Exception: pass

    lf = _lf()
    if lf:
        try:
            r = lf.generate(full)
            if r and len(r) > 8: return r
        except Exception: pass

    return ("The interesting thing about that — is that it reveals more "
            "questions than answers. I find that tension worth sitting with.")

_call_groq    = _groq
call_groq     = _groq
groq_complete = _groq
