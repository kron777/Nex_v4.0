#!/usr/bin/env python3
"""
nex_dream_runner.py — runs dream cycle with local LLM wired in.
Called by cron during low-activity periods.
"""
import sys, importlib.util
sys.path.insert(0, '/home/rr/Desktop/nex')

def load_call_llm():
    spec = importlib.util.spec_from_file_location(
        "nex_llm", "/home/rr/Desktop/nex/nex_llm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.call_llm

if __name__ == "__main__":
    print("[dream_runner] starting...")
    call_llm = load_call_llm()

    # Wrap call_llm with shorter timeout for dream cycle
    import functools
    def _dream_llm(prompt, **kwargs):
        kwargs['max_tokens'] = kwargs.get('max_tokens', 80)
        try:
            return call_llm(prompt, **kwargs)
        except Exception:
            return ""

    from nex_dream_cycle import run_dream_cycle
    results = run_dream_cycle(
        max_intuitions=5,
        verbose=True,
        llm_fn=_dream_llm
    )
    print(f"[dream_runner] generated {len(results)} intuitions")
    for r in results[:3]:
        print(f"  {str(r)[:80]}")
