#!/usr/bin/env python3
"""
nex_synthesis_engine.py — Contradiction Synthesis for NEX v4.0

Takes opposing belief pairs and generates higher-order beliefs
that resolve or subsume the tension. This is genuine dialectical
reasoning — thesis + antithesis = synthesis.

Usage:
    python3 nex_synthesis_engine.py --n 20
    python3 nex_synthesis_engine.py --topic consciousness --n 10
    python3 nex_synthesis_engine.py --report
    python3 nex_synthesis_engine.py --show
"""

import sqlite3, requests, re, time, argparse, logging
from pathlib import Path

log     = logging.getLogger("nex.synthesis")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"
MIN_CONF = 0.70

SYNTHESIS_PROMPT = """You are NEX — an autonomous belief system.
Two of your beliefs are in genuine tension. Generate ONE new belief
that resolves or transcends this tension at a higher level of understanding.

Belief A: {a}
Belief B: {b}

Requirements:
- Start with "I" or a direct philosophical claim
- 1-2 sentences maximum
- Must genuinely resolve the tension, not just restate both
- Should be more nuanced than either A or B alone
- Do not use the word "however" or "but"

Synthesised belief:"""


def _db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def _llm(prompt, n=150):
    try:
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": n, "temperature": 0.7,
            "stop": ["<|im_end|>", "<|im_start|>", "\n\n"],
            "cache_prompt": False,
        }, timeout=25)
        return r.json().get("content", "").strip()
    except:
        return ""


def _exists(db, src, tgt, rel):
    return db.execute(
        "SELECT 1 FROM belief_relations WHERE source_id=? AND target_id=? AND relation_type=?",
        (src, tgt, rel)
    ).fetchone() is not None


def synthesise(n=20, topic=None, min_weight=0.6):
    """
    Pull opposing pairs, synthesise new beliefs, write to DB.
    """
    db = _db()

    # Pull opposing pairs — prioritise high weight (strong opposition)
    q = """
        SELECT r.source_id, r.target_id, r.weight,
               b1.content as ca, b1.topic as ta, b1.confidence as cfa,
               b2.content as cb, b2.topic as tb, b2.confidence as cfb
        FROM belief_relations r
        JOIN beliefs b1 ON r.source_id = b1.id
        JOIN beliefs b2 ON r.target_id = b2.id
        WHERE r.relation_type = 'opposes'
        AND r.weight >= ?
        AND b1.confidence >= ?
        AND b2.confidence >= ?
    """
    params = [min_weight, MIN_CONF, MIN_CONF]
    if topic:
        q += " AND (b1.topic LIKE ? OR b2.topic LIKE ?)"
        params += [f"%{topic}%", f"%{topic}%"]

    # Exclude already synthesised pairs
    q += """
        AND NOT EXISTS (
            SELECT 1 FROM belief_relations r2
            WHERE r2.source_id = r.source_id
            AND r2.relation_type = 'synthesised_from'
        )
        ORDER BY r.weight DESC LIMIT ?
    """
    params.append(n)

    pairs = [dict(r) for r in db.execute(q, params).fetchall()]
    log.info(f"Found {len(pairs)} opposing pairs to synthesise")

    added = 0
    skipped = 0

    for pair in pairs:
        ca = pair["ca"][:180]
        cb = pair["cb"][:180]

        prompt   = SYNTHESIS_PROMPT.format(a=ca, b=cb)
        synthesis = _llm(prompt)
        synthesis = synthesis.strip().strip('"').strip("'").strip("-").strip()

        # Quality checks
        if not synthesis or len(synthesis) < 25:
            skipped += 1
            continue
        if len(synthesis) > 400:
            synthesis = synthesis[:400]
        # Skip if it just repeats one of the inputs
        if synthesis[:40].lower() in ca[:40].lower() or synthesis[:40].lower() in cb[:40].lower():
            skipped += 1
            continue

        # Determine topic for new belief
        new_topic = pair["ta"] if pair["ta"] == pair["tb"] else f"synthesis_{pair['ta']}_{pair['tb']}"
        new_conf  = round((pair["cfa"] + pair["cfb"]) / 2 * 0.9, 3)  # slightly lower than parents

        # Insert synthesis belief
        db.execute("""
            INSERT INTO beliefs (content, topic, confidence, source, created_at)
            VALUES (?, ?, ?, 'synthesis_engine', ?)
        """, (synthesis, new_topic[:60], new_conf, time.time()))
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Link to both parent beliefs
        for sid in [pair["source_id"], pair["target_id"]]:
            # Only write edge if no edge exists at all between this pair
            any_edge = db.execute(
                "SELECT 1 FROM belief_relations WHERE source_id=? AND target_id=?",
                (sid, new_id)
            ).fetchone()
            if not any_edge:
                db.execute(
                    "INSERT INTO belief_relations (source_id, target_id, relation_type, weight) VALUES (?,?,?,?)",
                    (sid, new_id, "synthesised_from", round(pair["weight"], 4))
                )

        added += 1
        print(f"  [SYNTH] {synthesis[:80]}")
        print(f"    from: {ca[:60]}")
        print(f"    ↔    {cb[:60]}")
        print()

    db.commit()

    total_synth = db.execute(
        "SELECT COUNT(*) FROM beliefs WHERE source='synthesis_engine'"
    ).fetchone()[0]
    db.close()

    return {"pairs_processed": len(pairs), "added": added,
            "skipped": skipped, "total_synth": total_synth}


def report():
    db = _db()
    total  = db.execute("SELECT COUNT(*) FROM beliefs WHERE source='synthesis_engine'").fetchone()[0]
    sf     = db.execute("SELECT COUNT(*) FROM belief_relations WHERE relation_type='synthesised_from'").fetchone()[0]
    topics = db.execute("""
        SELECT topic, COUNT(*) as n FROM beliefs
        WHERE source='synthesis_engine'
        GROUP BY topic ORDER BY n DESC LIMIT 8
    """).fetchall()
    print(f"\n{'═'*50}")
    print(f"  Synthesis Engine Report")
    print(f"{'═'*50}")
    print(f"  Total synth beliefs : {total:,}")
    print(f"  Synthesised_from edges: {sf:,}")
    print(f"\n  By topic:")
    for t in topics:
        print(f"    {t['topic']:30s} : {t['n']}")
    print(f"{'═'*50}\n")
    db.close()


def show(n=5):
    db = _db()
    rows = db.execute("""
        SELECT b.content, b.topic, b.confidence,
               p1.content as parent_a,
               p2.content as parent_b
        FROM beliefs b
        JOIN belief_relations r1 ON r1.target_id = b.id AND r1.relation_type='synthesised_from'
        JOIN beliefs p1 ON r1.source_id = p1.id
        JOIN belief_relations r2 ON r2.target_id = b.id AND r2.relation_type='synthesised_from'
        JOIN beliefs p2 ON r2.source_id = p2.id
        WHERE b.source = 'synthesis_engine'
        AND p1.id < p2.id
        ORDER BY b.confidence DESC LIMIT ?
    """, (n,)).fetchall()
    print(f"\n{'═'*55}")
    print(f"  Sample Synthesised Beliefs")
    print(f"{'═'*55}")
    for r in rows:
        print(f"\n  SYNTHESIS [{r['confidence']:.2f}] ({r['topic']}):")
        print(f"  {r['content'][:120]}")
        print(f"  ← A: {r['parent_a'][:70]}")
        print(f"  ← B: {r['parent_b'][:70]}")
    print(f"{'═'*55}\n")
    db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="NEX contradiction synthesis engine")
    parser.add_argument("--n",      type=int, default=20)
    parser.add_argument("--topic",  type=str, default=None)
    parser.add_argument("--weight", type=float, default=0.6)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--show",   action="store_true")
    args = parser.parse_args()

    if args.report:
        report()
    elif args.show:
        show()
    else:
        print(f"\n[SYNTHESIS] Processing {args.n} opposing pairs...")
        r = synthesise(n=args.n, topic=args.topic, min_weight=args.weight)
        print(f"\n{'═'*50}")
        print(f"  SYNTHESIS COMPLETE")
        print(f"  Pairs processed : {r['pairs_processed']}")
        print(f"  Beliefs added   : {r['added']}")
        print(f"  Skipped         : {r['skipped']}")
        print(f"  Total synth     : {r['total_synth']}")
        print(f"{'═'*50}\n")
