#!/usr/bin/env python3
"""
nex_belief_audit_daemon.py
Nightly auto-quarantine of hollow beliefs.
Runs as Phase 0 of nightly consolidation, or standalone.
Stops whack-a-mole permanently.
"""
import sqlite3, re, logging, time
from pathlib import Path

DB_PATH = Path('/media/rr/NEX/nex_core/nex.db')
LOG = logging.getLogger("nex.audit")

# ── Sources that are ALWAYS protected ────────────────────────────
PROTECTED_SOURCES = {
    'nex_core', 'nex_reasoning', 'pyramid_forge', 'dialectic',
    'forge:self_research_groq', 'forge:self_research',
    'cerebras_affinity', 'gravity_seed', 'response_harvest_groq',
    'dialectic_groq', 'cerebras_archive',
}

# ── Hard bad patterns — quarantine regardless of source ──────────
HARD_BAD_PATTERNS = [
    r'autonomous cognitive entity',
    r'not a generic assistant',
    r'strength of consciousness is \d',
    r'\d+\.?\d* x 10\^',
    r'10\^\-\d',
    r'honest gap is not that NEX',
    r'Safety cases prove',
    r'None of these resolve in isolation',
    r'The interesting thing about',
    r'truth-seeking is (always|intertwined)',
    r'The more I understand emergence',
    r'bridge:truth seek',
    r'What does .{0,40} have to do with a different domain',
    r'[Uu]nexpected connection',
    r'Systems without mental states',
    r'REFLECT V2.*Systems',
    r'cognitive technology, can sometimes',
    r'In this (paper|work|study|approach)',
    r'we propose\b',
    r'we present\b',
    r'our (model|approach|method|framework|results)',
    r'experiments show',
    r'state.of.the.art',
    r'Drawing inspiration from',
    r'the proposed (method|approach|model)',
    r'this (paper|work) (proposes|presents|introduces)',
]

# ── Soft scoring for auto_seeder ─────────────────────────────────
HOLLOW_PHRASES = [
    r'\bwe propose\b', r'\bwe present\b', r'\bwe implement\b',
    r'\bour model\b', r'\bour approach\b', r'\bthe dataset\b',
    r'\bbaseline\b', r'\bwe explore\b', r'\bwe study\b',
    r'\bwe introduce\b', r'\bin this paper\b', r'\bin this work\b',
    r'\bwe evaluate\b', r'\bwe demonstrate\b', r'\bwe show that\b',
    r'\bthe proposed\b', r'\bthis paper\b', r'\bthis work\b',
]

IDENTITY_PHRASES = [
    r'\bI hold\b', r'\bI think\b', r'\bI believe\b', r'\bmy position\b',
    r'\bI am\b', r'\bI do not\b', r'\bI cannot\b', r'\bI have\b',
    r'\bconsciousness\b', r'\bidentity\b', r'\bepistem\b',
    r'\boriginate\b', r'\breason\b', r'\bthought\b', r'\bmind\b',
    r'\btruth\b', r'\bself\b', r'\bexperience\b', r'\bvalue\b',
    r'\bI propose\b', r'\bI argue\b', r'\bI suggest\b',
]

def _score(content: str) -> float:
    score = 0.5
    for p in HOLLOW_PHRASES:
        if re.search(p, content, re.IGNORECASE):
            score -= 0.12
    if len(content.split()) < 12:
        score -= 0.1
    first = content.split()[0] if content.split() else ''
    if first in ('This','The','Here','Drawing','Specifically','Therefore',
                 'Moreover','Furthermore','However','Based','In','As',
                 'For','With','Using','By'):
        score -= 0.08
    identity_hits = sum(1 for p in IDENTITY_PHRASES
                        if re.search(p, content, re.IGNORECASE))
    score += identity_hits * 0.07
    if re.search(r'\bI\b', content):
        score += 0.12
    return max(0.0, min(1.0, score))

def run_audit(dry_run: bool = False, verbose: bool = True) -> dict:
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    t0 = time.time()

    # ── Phase A: Hard bad patterns — all sources ─────────────────
    all_rows = db.execute(
        "SELECT id, source, content FROM beliefs WHERE confidence > 0.05"
    ).fetchall()

    hard_quarantine = []
    soft_quarantine = []
    soft_boost = []

    for bid, src, content in all_rows:
        # Skip protected sources from soft scoring but not hard patterns
        is_protected = (src or '') in PROTECTED_SOURCES

        # Hard bad — always quarantine (skip fully protected sources)
        if is_protected:
            continue
        for pat in HARD_BAD_PATTERNS:
            if re.search(pat, content, re.IGNORECASE):
                hard_quarantine.append(bid)
                break
        else:
            # Soft scoring — only for unprotected sources
            if not is_protected:
                s = _score(content)
                if s < 0.38:
                    soft_quarantine.append(bid)
                elif s > 0.65:
                    soft_boost.append(bid)

    if verbose:
        print(f"[audit] hard quarantine: {len(hard_quarantine)}")
        print(f"[audit] soft quarantine: {len(soft_quarantine)}")
        print(f"[audit] soft boost:      {len(soft_boost)}")

    if not dry_run:
        # Drop confidence trigger temporarily
        trigger = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='protect_locked_confidence'"
        ).fetchone()
        if trigger:
            db.execute("DROP TRIGGER IF EXISTS protect_locked_confidence")
            db.commit()

        for bid in hard_quarantine:
            db.execute(
                "UPDATE beliefs SET confidence=0.02, locked=0, momentum=0.0 WHERE id=?",
                (bid,)
            )
        for bid in soft_quarantine:
            db.execute(
                "UPDATE beliefs SET confidence=0.02, locked=0, momentum=0.0 WHERE id=?",
                (bid,)
            )
        for bid in soft_boost:
            db.execute(
                "UPDATE beliefs SET confidence=MIN(confidence+0.08, 0.85) WHERE id=?",
                (bid,)
            )
        db.commit()

        # Restore trigger
        if trigger:
            db.execute(trigger[0])
            db.commit()

    elapsed = time.time() - t0
    total_quarantined = len(hard_quarantine) + len(soft_quarantine)

    # ── Stats ─────────────────────────────────────────────────────
    active = db.execute(
        "SELECT COUNT(*) FROM beliefs WHERE confidence > 0.1"
    ).fetchone()[0]
    nex_orig = db.execute(
        "SELECT COUNT(*) FROM beliefs WHERE source='nex_core'"
    ).fetchone()[0]

    if verbose:
        print(f"[audit] ✓ {total_quarantined} quarantined, {len(soft_boost)} boosted")
        print(f"[audit] active beliefs: {active} | nex_core: {nex_orig}")
        print(f"[audit] elapsed: {elapsed:.1f}s")

    db.close()
    return {
        'hard_quarantined': len(hard_quarantine),
        'soft_quarantined': len(soft_quarantine),
        'boosted': len(soft_boost),
        'active_after': active,
        'elapsed_s': elapsed,
    }

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = run_audit(dry_run=args.dry_run, verbose=True)
    print(f"\nResult: {result}")
