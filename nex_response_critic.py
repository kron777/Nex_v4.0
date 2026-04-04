#!/usr/bin/env python3
"""
nex_response_critic.py
Response Self-Critique — C3 from roadmap.

After NEX generates a response, score it before sending.
If score < threshold, regenerate with corrective instruction.
Max 2 regeneration attempts.
"""
import re, logging, requests
from pathlib import Path

log = logging.getLogger("nex.critic")

MIN_SCORE   = 0.45
MAX_RETRIES = 2
API         = "http://localhost:8080/completion"

BAD_PATTERNS = [
    (r"\bas an ai\b",               -0.30, "AI disclaimer"),
    (r"\bi cannot experience\b",    -0.25, "experience denial"),
    (r"\bi don't have feelings\b",  -0.25, "feeling denial"),
    (r"\bi'm just an?\b",           -0.20, "just an AI"),
    (r"\bcertainly!\b",             -0.15, "certainly opener"),
    (r"\bgreat question\b",         -0.15, "great question"),
    (r"\bof course!\b",             -0.10, "of course opener"),
    (r"\bi'd be happy to\b",        -0.10, "happy to help"),
    (r"\bsure!\b",                  -0.10, "sure opener"),
    (r"\bhowever, it's important\b",-0.10, "important to note"),
]

GOOD_PATTERNS = [
    (r"\bi hold\b",       +0.15, "I hold"),
    (r"\bmy position\b",  +0.10, "my position"),
    (r"\bi believe that\b",+0.08, "I believe that"),
    (r"\bmy view is\b",   +0.08, "my view"),
    (r"\bwhat i hold\b",  +0.08, "what I hold"),
    (r"\bthe tension\b",  +0.05, "acknowledges tension"),
    (r"\bunresolved\b",   +0.05, "acknowledges uncertainty"),
]


def score_response(response: str, activated_beliefs: list = None) -> dict:
    if not response:
        return {"score": 0.0, "issues": ["empty"], "passed": False}

    rl    = response.lower()
    words = response.split()
    score = 0.5
    issues = []
    bonuses = []

    # Length
    if len(words) < 10:
        score -= 0.20
    elif len(words) < 20:
        score -= 0.10

    # Repetition
    if len(words) > 10:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.45:
            score -= 0.15

    # Truncation check — only if response > 20 words
    if len(words) > 20 and response and response[-1] not in ".!?":
        score -= 0.08

    # Bad patterns
    for pattern, penalty, label in BAD_PATTERNS:
        if re.search(pattern, rl):
            score += penalty
            issues.append(label)

    # Good patterns
    for pattern, bonus, label in GOOD_PATTERNS:
        if re.search(pattern, rl):
            score += bonus
            bonuses.append(label)

    # Belief alignment
    if activated_beliefs:
        belief_words = set()
        for b in activated_beliefs[:5]:
            belief_words.update(b.lower().split())
        response_words = set(rl.split())
        overlap = len(belief_words & response_words) / max(len(belief_words), 1)
        if overlap > 0.15:
            score += 0.10
        elif overlap < 0.05:
            score -= 0.10

    # Ontology check
    try:
        import sys
        sys.path.insert(0, str(Path.home() / "Desktop/nex"))
        from nex_ontology import pattern_ground
        grounding = pattern_ground(response)
        if grounding["hollow"]:
            score -= 0.15
            issues.append("ontologically hollow")
        else:
            score += grounding["score"] * 0.05
    except Exception:
        pass

    score = round(max(0.0, min(1.0, score)), 3)
    return {"score": score, "issues": issues,
            "bonuses": bonuses, "passed": score >= MIN_SCORE}


CORRECTION_PROMPT = """Your previous response had issues: {issues}

Original query: {query}
Your response: {response}

Rewrite it. Requirements:
- Start with "I hold" or "My position is"
- No AI disclaimers, no hedging openers
- Hold a clear position
- 30-80 words, first person, direct

Rewrite:"""


def critique_and_fix(query: str, response: str,
                     activated_beliefs: list = None) -> str:
    result = score_response(response, activated_beliefs)
    if result["passed"]:
        return response

    for attempt in range(MAX_RETRIES):
        issues_str = ", ".join(result["issues"]) if result["issues"] else "unclear"
        correction = CORRECTION_PROMPT.format(
            issues=issues_str, query=query[:200], response=response[:300])
        try:
            r = requests.post(API, json={
                "prompt": f"<|im_start|>user\n{correction}<|im_end|>\n<|im_start|>assistant\n",
                "n_predict": 120, "temperature": 0.5,
                "stop": ["<|im_end|>", "<|im_start|>"],
                "cache_prompt": False,
            }, timeout=20)
            new_response = r.json().get("content", "").strip()
        except Exception:
            break

        if not new_response:
            break

        new_result = score_response(new_response, activated_beliefs)
        if new_result["passed"] or new_result["score"] > result["score"]:
            return new_response

    return response


if __name__ == "__main__":
    test_cases = [
        ("As an AI, I cannot experience consciousness directly.", False),
        ("I hold that consciousness resists reduction to computation.", True),
        ("Great question! Certainly, I would be happy to explain.", False),
        ("My position is that free will exists as compatibilist deliberation.", True),
    ]
    print("NEX RESPONSE CRITIC — TEST")
    for text, expected_pass in test_cases:
        result = score_response(text)
        status = "OK" if result["passed"] == expected_pass else "FAIL"
        print(f"  [{status}] score={result['score']:.2f} pass={result['passed']} | {text[:60]}")
        if result["issues"]:
            print(f"       issues: {result['issues']}")
