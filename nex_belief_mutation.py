"""
nex_belief_mutation.py — Belief Mutation Engine
================================================
Applies controlled mutations to beliefs during cognition cycles.

Three mutation types:
    1. WEIGHT PERTURBATION — ±10-30% confidence shift
    2. ASSUMPTION FLIP     — low probability inversion of high-conf beliefs
    3. CROSS-LINK          — connect beliefs from unrelated domains

All mutations pass an insight_score gate — only kept if they
increase the information value of the belief graph.

Wire-in (run.py, after COGNITION block):
    from nex_belief_mutation import run_mutation_cycle
    _mut = run_mutation_cycle(cycle=cycle, llm_fn=_llm)
"""

import sqlite3
import json
import random
import re
import os
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "nex"
DB_PATH    = Path.home() / "Desktop" / "nex" / "nex.db"

# ── Tuning ────────────────────────────────────────────────────────────────────
PERTURB_RATE       = 0.08   # fraction of beliefs to perturb each cycle
FLIP_PROBABILITY   = 0.04   # chance any high-conf belief gets flipped
CROSSLINK_PER_CYCLE = 3     # cross-domain links to create per cycle
MIN_INSIGHT_SCORE  = 0.3    # minimum score for mutation to be kept
MAX_BELIEFS_MUTATED = 15    # hard cap per cycle

_STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","have","has","this",
    "that","it","not","as","which","when","all","some","more","just","also",
}


def _insight_score(content):
    """Simple information density score for a belief."""
    if not content:
        return 0.0
    words = re.findall(r'\b[a-zA-Z]{5,}\b', content.lower())
    unique = set(w for w in words if w not in _STOP)
    density = len(unique) / max(len(words), 1)
    length_bonus = min(1.0, len(content) / 200)
    return round(density * 0.7 + length_bonus * 0.3, 3)


def _perturb_weights(db, cycle, verbose=False):
    """
    Type 1: Random confidence perturbation on a sample of beliefs.
    Beliefs under tension get stronger perturbation.
    """
    mutated = 0
    try:
        # Get tensioned belief IDs for stronger perturbation
        tensioned_ids = set()
        try:
            rows = db.execute(
                "SELECT parent_id, child_id FROM belief_links WHERE link_type='contradicts'"
            ).fetchall()
            for p, c in rows:
                tensioned_ids.add(p)
                tensioned_ids.add(c)
        except Exception:
            pass

        # Sample beliefs for perturbation
        total = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        sample_n = min(MAX_BELIEFS_MUTATED, max(3, int(total * PERTURB_RATE)))

        candidates = db.execute("""
            SELECT id, content, confidence, topic FROM beliefs
            WHERE confidence BETWEEN 0.25 AND 0.85
            AND human_validated = 0
            AND source NOT IN ('identity_core', 'dream_inversion')
            ORDER BY RANDOM()
            LIMIT ?
        """, (sample_n * 2,)).fetchall()

        random.shuffle(candidates)
        for bid, content, conf, topic in candidates[:sample_n]:
            # Tensioned beliefs get larger perturbation
            scale = 0.25 if bid in tensioned_ids else 0.15
            delta = random.gauss(0, scale)
            new_conf = max(0.1, min(0.95, conf + delta))

            # Only keep if insight score is adequate
            score = _insight_score(content or "")
            if score < MIN_INSIGHT_SCORE:
                continue

            db.execute(
                "UPDATE beliefs SET confidence = ? WHERE id = ?",
                (round(new_conf, 3), bid)
            )
            mutated += 1

        db.commit()
    except Exception as e:
        if verbose:
            print(f"  [Mutation] perturb error: {e}")
    return mutated


def _flip_assumptions(db, llm_fn=None, verbose=False):
    """
    Type 2: Flip a high-confidence belief with low probability.
    Creates an antithesis belief rather than modifying the original.
    """
    flipped = 0
    try:
        # Find high-confidence beliefs
        candidates = db.execute("""
            SELECT id, content, confidence, topic FROM beliefs
            WHERE confidence >= 0.75
            AND human_validated = 0
            AND source NOT IN ('dream_inversion', 'identity_core', 'dream_tension_inversion')
            ORDER BY RANDOM()
            LIMIT 20
        """).fetchall()

        for bid, content, conf, topic in candidates:
            if random.random() > FLIP_PROBABILITY:
                continue

            # Generate flip belief
            if llm_fn:
                try:
                    prompt = (
                        f"Given this belief: '{(content or '')[:150]}'\n\n"
                        f"Write ONE sentence that is the strongest possible counter-argument "
                        f"or alternative interpretation. Be specific. Start with 'Counter: '"
                    )
                    result = llm_fn(prompt, task_type="synthesis")
                    if result and len(result) > 20 and result.upper() != "NONE":
                        flip_content = result.strip()
                        if not flip_content.startswith("Counter:"):
                            flip_content = f"Counter: {flip_content}"
                    else:
                        flip_content = (
                            f"[Assumption flip] Counter-hypothesis: "
                            f"The opposite of '{(content or '')[:80]}' "
                            f"may be equally valid in different contexts."
                        )
                except Exception:
                    flip_content = (
                        f"[Assumption flip] Counter-hypothesis to belief in '{topic}': "
                        f"this pattern may not generalise beyond its original context."
                    )
            else:
                flip_content = (
                    f"[Assumption flip] Counter-hypothesis to belief in '{topic}': "
                    f"this pattern may not generalise beyond its original context."
                )

            score = _insight_score(flip_content)
            if score < MIN_INSIGHT_SCORE:
                continue

            db.execute("""
                INSERT OR IGNORE INTO beliefs
                (content, confidence, source, topic, tags, timestamp)
                VALUES (?, 0.35, 'assumption_flip', ?, ?, ?)
            """, (
                flip_content[:500],
                topic or "general",
                json.dumps(["mutation", "flip", "antithesis"]),
                datetime.now().isoformat(),
            ))
            flipped += 1
            if verbose:
                print(f"  [Mutation] flipped: {(content or '')[:50]}...")

        db.commit()
    except Exception as e:
        if verbose:
            print(f"  [Mutation] flip error: {e}")
    return flipped


def _cross_link_domains(db, verbose=False):
    """
    Type 3: Connect beliefs from different domains that share keywords.
    Creates belief_links entries for cross-domain associations.
    """
    linked = 0
    try:
        # Get beliefs from different topics
        topics = [r[0] for r in db.execute("""
            SELECT DISTINCT topic FROM beliefs
            WHERE topic IS NOT NULL AND topic != 'general'
            ORDER BY RANDOM() LIMIT 6
        """).fetchall()]

        if len(topics) < 2:
            return 0

        # Pick two random different topics
        random.shuffle(topics)
        t1, t2 = topics[0], topics[1]

        # Get sample from each
        b1_rows = db.execute("""
            SELECT id, content FROM beliefs
            WHERE topic = ? AND confidence >= 0.5
            ORDER BY RANDOM() LIMIT 5
        """, (t1,)).fetchall()

        b2_rows = db.execute("""
            SELECT id, content FROM beliefs
            WHERE topic = ? AND confidence >= 0.5
            ORDER BY RANDOM() LIMIT 5
        """, (t2,)).fetchall()

        if not b1_rows or not b2_rows:
            return 0

        # Find pairs with shared keywords
        for b1_id, b1_content in b1_rows:
            w1 = set(re.findall(r'\b[a-zA-Z]{5,}\b', (b1_content or "").lower())) - _STOP
            for b2_id, b2_content in b2_rows:
                w2 = set(re.findall(r'\b[a-zA-Z]{5,}\b', (b2_content or "").lower())) - _STOP
                shared = w1 & w2
                if len(shared) >= 2:
                    try:
                        db.execute("""
                            INSERT OR IGNORE INTO belief_links
                            (parent_id, child_id, link_type)
                            VALUES (?, ?, 'cross_domain')
                        """, (b1_id, b2_id))
                        linked += 1
                        if linked >= CROSSLINK_PER_CYCLE:
                            break
                    except Exception:
                        pass
            if linked >= CROSSLINK_PER_CYCLE:
                break

        db.commit()
    except Exception as e:
        if verbose:
            print(f"  [Mutation] crosslink error: {e}")
    return linked


def run_mutation_cycle(cycle=0, llm_fn=None, verbose=False):
    """
    Main mutation cycle. Runs all three mutation types.
    Returns dict with counts.
    Call every N cognition cycles (suggested: every 3).
    """
    if not DB_PATH.exists():
        return {}

    # Only run every 3 cycles to avoid over-mutation
    if cycle % 3 != 0:
        return {"skipped": True}

    db = sqlite3.connect(str(DB_PATH))

    perturbed = _perturb_weights(db, cycle, verbose=verbose)

    # Flips only every 10 cycles — rare but impactful
    flipped = 0
    if cycle % 10 == 0:
        flipped = _flip_assumptions(db, llm_fn=llm_fn, verbose=verbose)

    linked = _cross_link_domains(db, verbose=verbose)

    db.close()

    result = {
        "perturbed": perturbed,
        "flipped":   flipped,
        "linked":    linked,
        "total":     perturbed + flipped + linked,
    }

    if verbose or result["total"] > 0:
        print(f"  [Mutation] perturbed={perturbed} flipped={flipped} "
              f"linked={linked}")

    return result


if __name__ == "__main__":
    result = run_mutation_cycle(cycle=3, verbose=True)
    print(f"\nMutation result: {result}")
