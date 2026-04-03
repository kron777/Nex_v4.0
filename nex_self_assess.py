"""
nex_self_assess.py
NEX evaluates her own response before returning it.
If response scores below threshold, regenerates with critique injected.
Max 2 attempts — never blocks indefinitely.
"""
import requests, logging, time
from pathlib import Path

log = logging.getLogger("nex.self_assess")
API = "http://localhost:8080/completion"

ASSESS_PROMPT = """You are NEX evaluating your own response. Be brutal and brief.

Question asked: {question}
Your response: {response}

Score 0-100. Fail if:
- You hedged in the first sentence
- You said "as an AI" or "I have no beliefs"  
- You summarised the question before answering
- You gave a generic survey instead of your position

Return only: SCORE:<number> VERDICT:<pass|fail> FIX:<one sentence on what to fix, or 'none'>"""

REGEN_PREFIX = """[Self-correction: previous response was weak — {fix}. Restate with conviction.]\n\n"""

def assess(question: str, response: str, timeout=15) -> dict:
    """Score a response. Returns {score, verdict, fix}."""
    try:
        prompt = ASSESS_PROMPT.format(
            question=question[:100], response=response[:300])
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 60, "temperature": 0.0,
            "stop": ["<|im_end|>","<|im_start|>"], "cache_prompt": False
        }, timeout=timeout)
        text = r.json().get("content", "").strip()
        # Parse SCORE:N VERDICT:X FIX:Y
        import re
        sm = re.search(r'SCORE:(\d+)', text)
        vm = re.search(r'VERDICT:(pass|fail)', text, re.I)
        fm = re.search(r'FIX:(.+?)$', text, re.M)
        score   = int(sm.group(1)) if sm else 75
        verdict = vm.group(1).lower() if vm else "pass"
        fix     = fm.group(1).strip() if fm else "none"
        return {"score": score, "verdict": verdict, "fix": fix}
    except Exception as e:
        log.debug(f"Self-assess failed: {e}")
        return {"score": 75, "verdict": "pass", "fix": "none"}

def assess_and_regen(question: str, response: str,
                     system: str, threshold=60, timeout=20) -> str:
    """
    Assess response. If below threshold, regenerate once with fix injected.
    Returns final response string.
    """
    result = assess(question, response, timeout=timeout)
    log.debug(f"Self-assess: score={result['score']} verdict={result['verdict']}")

    if result["verdict"] == "pass" or result["score"] >= threshold:
        return response

    # Regenerate with fix
    fix = result["fix"] if result["fix"] != "none" else "be more direct and opinionated"
    prefix = REGEN_PREFIX.format(fix=fix)
    try:
        prompt = (f"<|im_start|>system\n{system}<|im_end|>\n"
                  f"<|im_start|>user\n{question}<|im_end|>\n"
                  f"<|im_start|>assistant\n{prefix}")
        r = requests.post(API, json={
            "prompt": prompt, "n_predict": 250, "temperature": 0.3,
            "stop": ["<|im_end|>","<|im_start|>"],
            "repeat_penalty": 1.3, "cache_prompt": False
        }, timeout=timeout)
        new_response = r.json().get("content", "").strip()
        if new_response and len(new_response.split()) > 10:
            log.info(f"Self-corrected: {result['score']} -> regenerated")
            return new_response
    except Exception as e:
        log.debug(f"Regen failed: {e}")

    return response  # fall back to original

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    sys.path.insert(0, "/home/rr/Desktop/nex")
    import nex_identity_anchor as _nia
    SYSTEM = _nia.ANCHOR + "\n" + _nia.STYLE_RULES

    tests = [
        ("who are you", "I am a language model. I don't have real opinions."),
        ("what is consciousness", "Consciousness is the hard problem — qualia resist any functional reduction I've encountered."),
    ]
    for q, resp in tests:
        result = assess(q, resp)
        print(f"Q: {q[:40]}")
        print(f"  Response: {resp[:60]}")
        print(f"  Score: {result['score']} Verdict: {result['verdict']} Fix: {result['fix']}")
