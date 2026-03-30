"""
nex_synthesizer.py v4 — native, no LLM.
CharacterEngine → NexCognition → BeliefGraph → fallback.
"""
from __future__ import annotations
import sys, os, importlib

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'nex'))

_E: dict = {}

def _eng(name, cls):
    k = f"{name}.{cls}"
    if k not in _E:
        for mn in (name, f"nex.{name}"):
            try:
                _E[k] = getattr(importlib.import_module(mn), cls)()
                break
            except Exception:
                pass
        if k not in _E:
            _E[k] = None
    return _E[k]

def synthesise(prompt: str, depth: int = 3) -> str:
    for name, cls, method in [
        ('nex_character_engine', 'CharacterEngine', 'respond'),
        ('nex_cognition',        'NexCognition',    'cognite'),
        ('nex_llm_free',         'NexLLMFree',      'generate'),
    ]:
        obj = _eng(name, cls)
        if obj:
            try:
                r = getattr(obj, method)(prompt)
                if r and len(str(r)) > 10:
                    return str(r)
            except Exception:
                pass
    g = _eng('nex_belief_graph', 'BeliefGraph')
    if g:
        try:
            chain = g.reasoning_chain(prompt, depth=depth)
            if chain:
                return " ".join(chain)
        except Exception:
            pass
    return ("The interesting thing about that — is that it reveals more "
            "questions than answers. I find that tension worth sitting with.")

def cognitive_loop(prompt: str, iterations: int = 3) -> list:
    g = _eng('nex_belief_graph', 'BeliefGraph')
    if g:
        try:
            chain = g.reasoning_chain(prompt, depth=iterations)
            if chain: return chain
        except Exception:
            pass
    return [synthesise(prompt)]

class _Msg:
    def __init__(self, t): self.content = t
class _Choice:
    def __init__(self, t): self.message = _Msg(t)
class _Resp:
    def __init__(self, t): self.choices = [_Choice(t)]

class SynthClient:
    """Groq-compatible interface — fully native."""
    class _Messages:
        def create(self, model="", messages=None, temperature=0.7,
                   max_tokens=400, **kw):
            prompt = system = ""
            for m in (messages or []):
                if m.get("role") == "system": system = m.get("content","")
                elif m.get("role") == "user": prompt  = m.get("content","")
            return _Resp(synthesise(f"{system}\n{prompt}".strip() or prompt))

    def __init__(self, api_key="", **kw):
        self.chat = SynthClient._Messages()
