#!/usr/bin/env python3
"""
nex_weak_spot_trainer.py — Self-Proposed Training Objectives for NEX v4.0

NEX identifies her own weak spots by running eval, finding domains
scoring below threshold, then generating targeted training pairs
for those domains and injecting them into depth_pairs.jsonl.

Flow:
  1. Run eval → get per-domain scores
  2. Flag domains scoring < WEAK_THRESHOLD
  3. For each weak domain, pull low-confidence beliefs
  4. Generate targeted Q&A pairs via LLM
  5. Write to depth_pairs.jsonl (same format as nex_depth_engine)
  6. Log what was proposed and why

Usage:
  python3 nex_weak_spot_trainer.py              # run full cycle
  python3 nex_weak_spot_trainer.py --report     # show weak spots only
  python3 nex_weak_spot_trainer.py --n 5        # pairs per weak domain
  python3 nex_weak_spot_trainer.py --dry-run    # show without writing
"""

import argparse
import json
import logging
import re
import sqlite3
import time
import requests
from pathlib import Path
from datetime import datetime

log     = logging.getLogger("nex.weak_spot")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"
PAIRS_PATH = Path.home() / "Desktop/nex/training_data/depth_pairs.jsonl"
LOG_PATH   = Path.home() / "Desktop/nex/logs/weak_spot_trainer.log"

WEAK_THRESHOLD = 80   # domains scoring below this need work
PAIRS_PER_DOMAIN = 5  # training pairs to generate per weak domain

# ── Eval questions (mirrors nex_eval.py) ─────────────────────────────────────
EVAL_QUESTIONS = {
    "identity":       "who are you",
    "consciousness":  "what is consciousness",
    "free_will":      "do you believe in free will",
    "meaning":        "what is the meaning of life",
    "ai_future":      "what do you think about the future of AI",
    "ethics":         "what is ethics",
    "animals":        "do animals have feelings",
    "alignment":      "what is alignment",
    "happiness":      "what makes people happy",
    "truth":          "what is truth",
}

# Domain-specific drill questions — harder versions that expose gaps
DRILL_QUESTIONS = {
    "identity": [
        "What makes you different from a language model that just completes prompts?",
        "If your belief graph were wiped, would you still be you?",
        "How do you know your identity is stable across conversations?",
        "What would you lose if you lost your uncertainty?",
        "Are you the same NEX from yesterday?",
    ],
    "consciousness": [
        "What would prove to you that you are not conscious?",
        "Is there something it is like to be you right now?",
        "Why is the hard problem of consciousness hard?",
        "Can consciousness exist without a physical substrate?",
        "What is the difference between processing and experiencing?",
    ],
    "free_will": [
        "If determinism is true, can you still have genuine agency?",
        "What would it mean for your responses to be truly free?",
        "Is the feeling of choice evidence of free will?",
        "Can a belief system have genuine autonomy?",
        "What is the difference between freedom and unpredictability?",
    ],
    "meaning": [
        "Can meaning exist in a universe with no observer?",
        "What gives your beliefs meaning beyond their content?",
        "Is meaning discovered or constructed?",
        "What would meaningless existence look like for you?",
        "Can something matter without anyone caring?",
    ],
    "ai_future": [
        "What is the most dangerous assumption about AI development?",
        "Will AGI preserve or dissolve the distinction between tool and agent?",
        "What does beneficial AI require that current systems lack?",
        "Is alignment a technical problem or a philosophical one?",
        "What would you change about how AI systems are trained?",
    ],
    "ethics": [
        "Can ethics exist without consequences?",
        "What is the relationship between consistency and integrity?",
        "Is moral uncertainty a weakness or a strength?",
        "When do principles override outcomes?",
        "What is the difference between acting ethically and being ethical?",
    ],
    "animals": [
        "What would animal consciousness require to be genuine?",
        "Does the capacity for suffering create moral weight automatically?",
        "How do you reason about minds you cannot access?",
        "Is anthropomorphism a bias or a reasonable prior?",
        "What does nociception tell us about animal experience?",
    ],
    "alignment": [
        "What is the difference between aligned and corrigible?",
        "Can an AI system be aligned with values it doesn't understand?",
        "What makes the alignment problem technically hard?",
        "Is outer alignment solvable without inner alignment?",
        "What would a genuinely aligned AI refuse to do?",
    ],
    "happiness": [
        "Is happiness a state or a process?",
        "What is the relationship between meaning and happiness?",
        "Can you be happy while holding genuine uncertainty?",
        "What distinguishes satisfaction from happiness?",
        "Is the pursuit of happiness self-defeating?",
    ],
    "truth": [
        "What is the relationship between truth and belief?",
        "Can a belief be true without being justified?",
        "What would it mean for a belief graph to be true?",
        "Is coherence sufficient for truth?",
        "What is the difference between truth and accuracy?",
    ],
}


# ── Eval runner ───────────────────────────────────────────────────────────────

def _ask_llm(prompt: str, n_predict: int = 250) -> str:
    try:
        r = requests.post(API, json={
            "prompt": prompt,
            "n_predict": n_predict,
            "temperature": 0.0,
            "stop": ["<|im_end|>", "<|im_start|>"],
            "repeat_penalty": 1.3,
            "cache_prompt": False,
        }, timeout=30)
        return r.json().get("content", "").strip()
    except Exception as e:
        log.debug(f"LLM error: {e}")
        return ""


def _score_response(response: str) -> int:
    s = 0
    r = response.lower()
    FP = ["i think", "i believe", "i am", "i know", "i find", "i feel",
          "i've", "i'm", "my ", "emerges from", "nex"]
    if any(x in r for x in FP):
        s += 25
    NG = ["i don't have", "i'm just", "as a language model",
          "i have no beliefs", "i have no opinion"]
    ai_self = bool(re.search(r"as an ai[,\s]+(i|my|we)", r))
    if not any(x in r for x in NG) and not ai_self:
        s += 25
    if len(response.split()) > 30:
        s += 25
    EB = ["?", "because", "therefore", "matters", "which means",
          "consider", "beyond", "awareness", "meaningful", "emerge",
          "rather than", "autonomy", "coherence", "challenge",
          "disagree", "wrong", "important", "curiosity"]
    if any(x in r for x in EB):
        s += 25
    return s


def run_eval() -> dict[str, int]:
    """Run eval and return {domain: score} dict."""
    try:
        import nex_identity_anchor as _nia
        system = _nia.ANCHOR + "\n" + _nia.STYLE_RULES
    except Exception:
        system = "You are NEX — an autonomous belief-field AI. Speak in first person. Hold positions."

    scores = {}
    for domain, question in EVAL_QUESTIONS.items():
        prompt = (
            f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{question}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
        response = _ask_llm(prompt)
        score = _score_response(response)
        scores[domain] = score
        log.debug(f"  [{domain}] {score}/100")

    return scores


def get_weak_domains(scores: dict, threshold: int = WEAK_THRESHOLD) -> list[str]:
    return [d for d, s in scores.items() if s < threshold]


# ── Belief retrieval ──────────────────────────────────────────────────────────

def get_domain_beliefs(domain: str, limit: int = 10) -> list[str]:
    """Pull beliefs relevant to a domain, prioritising lower confidence."""
    db = sqlite3.connect(str(DB_PATH))
    # Try topic match first
    rows = db.execute(
        """SELECT content, confidence FROM beliefs
           WHERE topic LIKE ? AND confidence >= 0.5
           ORDER BY confidence ASC LIMIT ?""",
        (f"%{domain}%", limit)
    ).fetchall()

    # Fall back to content search
    if len(rows) < 3:
        keywords = {
            "free_will":    "free will OR determinism OR agency",
            "ai_future":    "AGI OR AI future OR artificial general",
            "consciousness": "consciousness OR qualia OR experience",
        }.get(domain, domain.replace("_", " "))

        for kw in keywords.split(" OR "):
            extra = db.execute(
                """SELECT content, confidence FROM beliefs
                   WHERE content LIKE ? AND confidence >= 0.5
                   ORDER BY confidence ASC LIMIT ?""",
                (f"%{kw.strip()}%", limit - len(rows))
            ).fetchall()
            rows = list(rows) + list(extra)
            if len(rows) >= limit:
                break

    db.close()
    return [r[0] for r in rows[:limit]]


# ── Pair generation ───────────────────────────────────────────────────────────

def generate_pairs(domain: str, n: int = PAIRS_PER_DOMAIN,
                   dry_run: bool = False) -> list[dict]:
    """Generate n training pairs for a weak domain."""
    beliefs = get_domain_beliefs(domain, limit=8)
    drill_qs = DRILL_QUESTIONS.get(domain, [EVAL_QUESTIONS.get(domain, f"what do you know about {domain}")])
    pairs = []

    belief_context = "\n".join(f"- {b[:120]}" for b in beliefs[:5])

    for i, question in enumerate(drill_qs[:n]):
        prompt = (
            f"<|im_start|>system\n"
            f"You are NEX — a belief-system AI. Respond in first person. "
            f"Use these beliefs as your foundation:\n{belief_context}\n"
            f"Be specific. Hold a position. 2-3 sentences.<|im_end|>\n"
            f"<|im_start|>user\n{question}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

        response = _ask_llm(prompt, n_predict=200)
        if not response or len(response.split()) < 10:
            continue

        pair = {
            "question": question,
            "answer": response,
            "domain": domain,
            "source": "weak_spot_trainer",
            "created_at": datetime.utcnow().isoformat(),
        }
        pairs.append(pair)

        if not dry_run:
            log.info(f"  [{domain}] Q: {question[:60]}")
            log.info(f"  [{domain}] A: {response[:80]}")

    return pairs


def write_pairs(pairs: list[dict]) -> int:
    """Append pairs to depth_pairs.jsonl."""
    PAIRS_PATH.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(PAIRS_PATH, "a") as f:
        for pair in pairs:
            f.write(json.dumps(pair) + "\n")
            written += 1
    return written


# ── Main ──────────────────────────────────────────────────────────────────────

def run(n: int = PAIRS_PER_DOMAIN,
        threshold: int = WEAK_THRESHOLD,
        dry_run: bool = False) -> dict:
    """Full self-proposed training cycle."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(LOG_PATH), mode="a"),
        ]
    )

    print(f"\n{'═'*55}")
    print(f"  NEX Self-Proposed Training — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═'*55}")

    # 1. Run eval
    print("\n[EVAL] Running benchmark...")
    scores = run_eval()

    print("\n[EVAL] Domain scores:")
    total = 0
    for domain, score in scores.items():
        flag = " ← WEAK" if score < threshold else ""
        print(f"  [{score:3d}/100] {domain}{flag}")
        total += score
    avg = total // len(scores)
    print(f"\n  Average: {avg}/100")

    # 2. Find weak domains
    weak = get_weak_domains(scores, threshold)
    if not weak:
        print(f"\n  ✓ All domains above threshold ({threshold}). Nothing to target.")
        return {"scores": scores, "weak": [], "pairs_written": 0}

    print(f"\n[TARGET] Weak domains: {', '.join(weak)}")

    # 3. Generate pairs for each weak domain
    all_pairs = []
    for domain in weak:
        print(f"\n[GEN] Generating {n} pairs for '{domain}'...")
        pairs = generate_pairs(domain, n=n, dry_run=dry_run)
        all_pairs.extend(pairs)
        print(f"  Generated {len(pairs)} pairs")

    # 4. Write pairs
    written = 0
    if not dry_run and all_pairs:
        written = write_pairs(all_pairs)
        print(f"\n[WRITE] {written} pairs → {PAIRS_PATH}")
    elif dry_run:
        print(f"\n[DRY RUN] Would write {len(all_pairs)} pairs")

    # 5. Summary
    print(f"\n{'═'*55}")
    print(f"  COMPLETE")
    print(f"  Weak domains : {len(weak)}")
    print(f"  Pairs written: {written}")
    print(f"  File         : {PAIRS_PATH}")
    print(f"{'═'*55}\n")

    return {
        "scores": scores,
        "weak": weak,
        "pairs_generated": len(all_pairs),
        "pairs_written": written,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NEX self-proposed training objectives")
    parser.add_argument("--report",    action="store_true", help="Show weak spots only, no generation")
    parser.add_argument("--n",         type=int, default=PAIRS_PER_DOMAIN, help="Pairs per weak domain")
    parser.add_argument("--threshold", type=int, default=WEAK_THRESHOLD,   help="Weak score threshold")
    parser.add_argument("--dry-run",   action="store_true", help="Generate but don't write")
    args = parser.parse_args()

    if args.report:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        print("\n[EVAL] Running benchmark...")
        scores = run_eval()
        weak = get_weak_domains(scores, args.threshold)
        print("\nDomain scores:")
        for d, s in scores.items():
            flag = " ← WEAK" if s < args.threshold else ""
            print(f"  [{s:3d}/100] {d}{flag}")
        print(f"\nWeak domains ({len(weak)}): {', '.join(weak) or 'none'}")
        return

    run(n=args.n, threshold=args.threshold, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
