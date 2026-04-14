"""
nex_claude_tutor.py — Claude as Nex's personal tutor
=====================================================
Reads Nex's knowledge gaps, asks Claude to explain them
in terms of Nex's existing beliefs, and injects the
resulting explanations as high-confidence beliefs.

Runs every TUTOR_INTERVAL cognitive cycles.
"""

import os
import json
import time
import logging
import hashlib
from pathlib import Path

log = logging.getLogger("nex.claude_tutor")

# ── Config ────────────────────────────────────────────────────────────────────
TUTOR_INTERVAL     = 30          # run every N cognitive cycles
MAX_GAPS_PER_RUN   = 3           # max gaps to teach per run
MAX_BELIEFS_PER_GAP = 5          # max beliefs extracted per gap
BELIEF_CONFIDENCE  = 0.72        # beliefs from Claude get high confidence
ANTHROPIC_API_URL  = "https://api.anthropic.com/v1/messages"
MODEL              = "claude-sonnet-4-20250514"

CONFIG_DIR = Path.home() / ".config" / "nex"
GAPS_PATH  = CONFIG_DIR / "gaps.json"
SEEN_PATH  = CONFIG_DIR / "tutor_seen.json"

# ── Seen gap cache ─────────────────────────────────────────────────────────────
def _load_seen() -> set:
    try:
        return set(json.loads(SEEN_PATH.read_text()))
    except Exception:
        return set()

def _save_seen(seen: set):
    SEEN_PATH.write_text(json.dumps(list(seen)[-200:]))

# ── Load top gaps ──────────────────────────────────────────────────────────────
def _get_top_gaps(n: int = MAX_GAPS_PER_RUN) -> list:
    try:
        gaps = json.loads(GAPS_PATH.read_text())
        seen = _load_seen()
        # Filter out already taught, resolved, and junk single-word gaps
        filtered = [
            g for g in gaps
            if g.get("term")
            and g.get("resolved_at") is None
            and g["term"] not in seen
            and len(g["term"]) > 4
            and g.get("context") not in ("", None)
        ]
        # Sort by priority descending
        filtered.sort(key=lambda x: x.get("priority", 0), reverse=True)
        return filtered[:n]
    except Exception as e:
        log.warning(f"Could not load gaps: {e}")
        return []

# ── Get Nex's existing beliefs on a topic ─────────────────────────────────────
def _get_related_beliefs(topic: str, limit: int = 5) -> list:
    try:
        import sys
        sys.path.insert(0, str(Path.home() / "Desktop" / "nex"))
        from nex.nex_db import NexDB
        db = NexDB()
        beliefs = db.query_beliefs(topic=topic, min_confidence=0.4, limit=limit)
        return [b.get("content", "") for b in beliefs if b.get("content")]
    except Exception:
        return []

# ── Call Claude API ────────────────────────────────────────────────────────────
def _ask_claude(gap_term: str, context: str, related_beliefs: list) -> str:
    try:
        import urllib.request
        import urllib.error

        belief_context = ""
        if related_beliefs:
            belief_context = "\n\nNex's existing related beliefs:\n" + \
                "\n".join(f"- {b[:120]}" for b in related_beliefs)

        system_prompt = (
            "You are teaching NEX — a Dynamic Intelligence Organism that builds "
            "knowledge through beliefs. NEX thinks in structured beliefs: direct "
            "claims with reasoning. Your job is to explain a knowledge gap clearly "
            "and densely. Do not be conversational. Be precise and information-rich."
        )

        user_prompt = (
            f"NEX has a knowledge gap around: '{gap_term}'\n"
            f"Context: {context}\n"
            f"{belief_context}\n\n"
            f"Provide exactly {MAX_BELIEFS_PER_GAP} distinct beliefs NEX should hold "
            f"about '{gap_term}'. Each belief should be 1-2 sentences, grounded, and "
            f"non-obvious. Format as a numbered list. No preamble."
        )

        payload = json.dumps({
            "model": MODEL,
            "max_tokens": 1000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}]
        }).encode()

        req = urllib.request.Request(
            ANTHROPIC_API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": os.environ.get("ANTHROPIC_API_KEY", "")
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["content"][0]["text"]

    except Exception as e:
        log.warning(f"Claude API call failed: {e}")
        return ""

# ── Parse Claude's response into beliefs ──────────────────────────────────────
def _parse_beliefs(text: str, topic: str) -> list:
    beliefs = []
    for line in text.strip().split("\n"):
        line = line.strip()
        # Match numbered list items like "1." "2." etc
        if line and line[0].isdigit() and "." in line[:3]:
            belief = line.split(".", 1)[-1].strip()
            if len(belief) > 20:
                beliefs.append(belief)
    return beliefs[:MAX_BELIEFS_PER_GAP]

# ── Store beliefs into NexDB ───────────────────────────────────────────────────
def _store_beliefs(beliefs: list, topic: str, source_term: str) -> int:
    stored = 0
    try:
        import sys
        sys.path.insert(0, str(Path.home() / "Desktop" / "nex"))
        from nex.nex_db import NexDB
        db = NexDB()
        for belief in beliefs:
            bid = db.add_belief(
                content    = belief,
                topic      = topic,
                confidence = BELIEF_CONFIDENCE,
                source     = f"claude_tutor:{source_term}",
                origin     = "claude_tutor"
            )
            if bid:
                stored += 1
        return stored
    except Exception as e:
        log.warning(f"Failed to store beliefs: {e}")
        return 0

# ── Mark gap as resolved ───────────────────────────────────────────────────────
def _mark_resolved(term: str):
    try:
        gaps = json.loads(GAPS_PATH.read_text())
        for g in gaps:
            if g.get("term") == term:
                g["resolved_at"] = time.time()
        GAPS_PATH.write_text(json.dumps(gaps, indent=2))
    except Exception:
        pass

# ── Main entry point ──────────────────────────────────────────────────────────
def run_tutor_cycle(cycle: int = 0, verbose: bool = True) -> dict:
    if cycle % TUTOR_INTERVAL != 0:
        return {}

    gaps = _get_top_gaps()
    if not gaps:
        if verbose:
            print("  [TUTOR] No unresolved gaps to teach")
        return {}

    seen = _load_seen()
    results = {}

    for gap in gaps:
        term    = gap["term"]
        context = gap.get("context", "general knowledge gap")

        if verbose:
            print(f"  [TUTOR] Teaching gap: '{term}'")

        related = _get_related_beliefs(term)
        response = _ask_claude(term, context, related)

        if not response:
            if verbose:
                print(f"  [TUTOR] No response from Claude for '{term}'")
            continue

        beliefs = _parse_beliefs(response, term)
        if not beliefs:
            if verbose:
                print(f"  [TUTOR] Could not parse beliefs for '{term}'")
            continue

        stored = _store_beliefs(beliefs, term, term)
        seen.add(term)
        _mark_resolved(term)

        if verbose:
            print(f"  [TUTOR] ✓ '{term}' → {stored} beliefs stored")

        results[term] = stored
        time.sleep(2)  # be gentle with the API

    _save_seen(seen)

    total = sum(results.values())
    if verbose and total > 0:
        print(f"  [TUTOR] Session complete — {total} beliefs from {len(results)} gaps")

    return results


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("[TUTOR] Running standalone test...")
    results = run_tutor_cycle(cycle=0, verbose=True)
    print(f"[TUTOR] Results: {results}")
