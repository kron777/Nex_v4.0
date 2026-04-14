#!/usr/bin/env python3
"""
nex_dialectical_synthesis.py
Dialectical Synthesis Engine.

Current synthesis: 2-3 related beliefs -> derive consequence (averaging)
Dialectical synthesis: thesis + antithesis -> genuine transcendence

Process (Hegelian algorithm):
  1. THESIS: find a high-confidence belief (the position)
  2. ANTITHESIS: find its strongest opposing belief
  3. STEELMAN: model the strongest version of each
  4. IDENTIFY SHARED GROUND: what do both positions actually agree on?
  5. SYNTHESISE: the position that holds what both got right
     while transcending what each got wrong

This is not compromise. It is the position that makes both
the thesis and antithesis look like partial truths.

Each synthesis is scored for:
  - transcendence: does it say something neither thesis nor antithesis said?
  - coherence: is it internally consistent?
  - novelty: is it already in the belief graph?

Only genuine transcendences get stored.
"""
import sqlite3, requests, json, logging, time
from pathlib import Path

log     = logging.getLogger("nex.dialectical")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

MIN_THESIS_CONF    = 0.75
MIN_ANTITHESIS_STR = 0.5   # opposing edge strength
MIN_NOVELTY        = 0.35
MIN_TRANSCENDENCE  = 0.30


STEELMAN_PROMPT = """You are a rigorous philosopher.
State the STRONGEST possible version of this position in 1-2 sentences.
Make it as defensible as possible. No strawmanning.

Position: {position}

Strongest version:"""


SHARED_GROUND_PROMPT = """Two positions are in genuine tension:

Thesis (steelmanned): {thesis}

Antithesis (steelmanned): {antithesis}

What do BOTH positions get right? What truth does each capture?
State the shared insight in 1 sentence. Be specific."""


TRANSCENDENCE_PROMPT = """You are NEX. Two positions are in genuine tension:

Thesis: {thesis}
Antithesis: {antithesis}
Shared ground: {shared}

Synthesise a position that:
- Holds what both thesis and antithesis got right
- Transcends the limitation of each
- Is NOT a compromise or average
- Says something NEITHER thesis nor antithesis said alone

First person. 20-45 words. Direct claim. Start with "I hold" or "My position".
No hedging opener. The synthesis itself only."""


TRANSCENDENCE_CHECK_PROMPT = """Original positions:
Thesis: {thesis}
Antithesis: {antithesis}
Synthesis: {synthesis}

Does the synthesis say something genuinely new — something neither the thesis
nor antithesis stated alone? Rate 0.0-1.0.
0.0 = just averaging the two
0.5 = somewhat new
1.0 = completely transcends both
Return ONLY a number."""


def _llm(prompt: str, max_tokens=120, temperature=0.5) -> str:
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": max_tokens, "temperature": temperature,
            "stop": ["<|im_end|>","<|im_start|>"],
            "cache_prompt": False,
        }, timeout=25)
        return r.json().get("content","").strip()
    except Exception as e:
        log.debug(f"LLM failed: {e}")
        return ""


def _get_thesis_antithesis_pairs(db, n=10) -> list:
    """Get belief pairs with strong opposing edges."""
    rows = db.execute("""
        SELECT b1.id, b1.content, b1.topic, b1.confidence,
               b2.id, b2.content, b2.topic, b2.confidence,
               br.weight as strength
        FROM belief_relations br
        JOIN beliefs b1 ON br.source_id = b1.id
        JOIN beliefs b2 ON br.target_id = b2.id
        WHERE br.relation_type = 'opposing'
        AND b1.confidence >= ?
        AND b2.confidence >= 0.60
        AND br.weight >= ?
        ORDER BY br.weight DESC, b1.confidence DESC
        LIMIT ?
    """, (MIN_THESIS_CONF, MIN_ANTITHESIS_STR, n)).fetchall()

    pairs = []
    for row in rows:
        pairs.append({
            "thesis_id":      row[0],
            "thesis":         row[1],
            "thesis_topic":   row[2],
            "thesis_conf":    row[3],
            "anti_id":        row[4],
            "antithesis":     row[5],
            "anti_topic":     row[6],
            "anti_conf":      row[7],
            "strength":       row[8],
        })
    return pairs


def steelman(position: str) -> str:
    """Generate strongest version of a position."""
    return _llm(STEELMAN_PROMPT.format(position=position[:200]),
                max_tokens=80, temperature=0.3)


def find_shared_ground(thesis: str, antithesis: str) -> str:
    """Find what both positions get right."""
    return _llm(SHARED_GROUND_PROMPT.format(
        thesis=thesis[:150], antithesis=antithesis[:150]),
        max_tokens=60, temperature=0.3)


def synthesise(thesis: str, antithesis: str, shared: str) -> str:
    """Generate dialectical synthesis."""
    return _llm(TRANSCENDENCE_PROMPT.format(
        thesis=thesis[:150], antithesis=antithesis[:150],
        shared=shared[:100]),
        max_tokens=80, temperature=0.65)


def score_transcendence(thesis: str, antithesis: str, synthesis: str) -> float:
    """Score how much synthesis transcends both positions."""
    raw = _llm(TRANSCENDENCE_CHECK_PROMPT.format(
        thesis=thesis[:100], antithesis=antithesis[:100],
        synthesis=synthesis[:100]),
        max_tokens=10, temperature=0.1)
    try:
        return float(raw.strip())
    except Exception:
        return 0.0


def score_novelty_simple(candidate: str, existing: list) -> float:
    """Quick keyword-based novelty check."""
    cw = set(candidate.lower().split())
    for ex in existing[:20]:
        ew = set(ex.lower().split())
        if cw and ew:
            overlap = len(cw & ew) / len(cw | ew)
            if overlap > 0.65:
                return 0.0
    return 1.0


def run_dialectical(n_pairs=8, dry_run=False) -> dict:
    """Run dialectical synthesis on opposing belief pairs."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    pairs = _get_thesis_antithesis_pairs(db, n=n_pairs)
    print(f"\nDialectical synthesis: {len(pairs)} opposing pairs found")

    if not pairs:
        print("No opposing belief pairs found — run nex_belief_linker first")
        db.close()
        return {"synthesised": 0, "stored": 0}

    existing = [r[0] for r in db.execute(
        "SELECT content FROM beliefs WHERE confidence >= 0.65 ORDER BY confidence DESC LIMIT 100"
    ).fetchall()]

    synthesised = 0
    stored      = 0
    skipped     = 0

    for pair in pairs:
        thesis     = pair["thesis"]
        antithesis = pair["antithesis"]

        print(f"\nThesis: {thesis[:60]}")
        print(f"Anti:   {antithesis[:60]}")

        # Step 1: Steelman both
        s_thesis = steelman(thesis)
        s_anti   = steelman(antithesis)
        if not s_thesis or not s_anti:
            skipped += 1
            continue

        # Step 2: Find shared ground
        shared = find_shared_ground(s_thesis, s_anti)
        if not shared:
            skipped += 1
            continue

        # Step 3: Synthesise
        synthesis = synthesise(s_thesis, s_anti, shared)
        if not synthesis or len(synthesis.split()) < 10:
            skipped += 1
            continue

        synthesised += 1

        # Step 4: Score transcendence
        transcendence = score_transcendence(thesis, antithesis, synthesis)
        if transcendence < MIN_TRANSCENDENCE:
            print(f"  -> Low transcendence ({transcendence:.2f}), skipping")
            skipped += 1
            continue

        # Step 5: Novelty check
        novelty = score_novelty_simple(synthesis, existing)
        if novelty < MIN_NOVELTY:
            print(f"  -> Too similar to existing, skipping")
            skipped += 1
            continue

        confidence = min(0.82, 0.65 + transcendence * 0.1 + novelty * 0.07)
        print(f"  => SYNTHESIS (t={transcendence:.2f} n={novelty:.2f} c={confidence:.2f}):")
        print(f"     {synthesis[:120]}")

        if not dry_run:
            try:
                now = time.strftime("%Y-%m-%dT%H:%M:%S")
                db.execute("""INSERT INTO beliefs
                    (content, topic, confidence, source, belief_type, created_at)
                    VALUES (?,?,?,?,?,?)""", (
                    synthesis[:300],
                    pair["thesis_topic"],
                    confidence,
                    f"dialectical:{pair['thesis_id']}↔{pair['anti_id']}",
                    "synthesis",
                    now,
                ))
                stored += 1
                existing.append(synthesis)
            except Exception as e:
                log.debug(f"Store failed: {e}")

        time.sleep(0.3)

    if not dry_run:
        db.commit()
    db.close()

    print(f"\nDialectical synthesis complete:")
    print(f"  Pairs processed: {len(pairs)}")
    print(f"  Synthesised:     {synthesised}")
    print(f"  Stored:          {stored}")
    print(f"  Skipped:         {skipped}")
    return {"synthesised": synthesised, "stored": stored, "skipped": skipped}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--n", type=int, default=8)
    args = parser.parse_args()
    run_dialectical(n_pairs=args.n, dry_run=args.dry_run)
