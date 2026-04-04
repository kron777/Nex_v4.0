#!/usr/bin/env python3
"""
nex_ontology.py
Grounded Belief Ontology — Step 3 toward world model.

Every belief in NEX's graph should be reducible to primitive concepts.
Beliefs that can't be grounded are linguistically fluent but conceptually hollow.

PRIMITIVES:
  AGENT   — something that acts (NEX, humans, systems, entities)
  CAUSE   — one thing brings about another (causal relation)
  VALUE   — something matters, has normative weight
  TIME    — temporal relation (before/after/during/change)
  STATE   — a condition that holds (property of an entity)
  BELIEF  — a held proposition with confidence
  OUGHT   — normative force (should/must/forbidden)
  UNKNOWN — genuine uncertainty (not mere absence of data)

Grounding score: 0.0-1.0
  1.0 = fully groundable in primitives
  0.5 = partially groundable
  0.0 = linguistically fluent, conceptually hollow

Beliefs scoring < 0.3 get flagged as hollow.
Beliefs scoring > 0.8 get confidence boost.

Runs weekly. Feeds into belief_immune for hollow belief detection.
"""
import sqlite3, json, re, logging, time
from pathlib import Path

log     = logging.getLogger("nex.ontology")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

PRIMITIVES = {
    "AGENT": [
        r"\b(i|nex|human|system|agent|entity|organism|mind|person|we|they)\b",
        r"\b(actor|subject|being|self|other)\b",
    ],
    "CAUSE": [
        r"\b(cause|causes|because|therefore|thus|leads to|results in|produces)\b",
        r"\b(enables|prevents|blocks|forces|drives|generates|implies)\b",
        r"\b(follows from|consequence|effect|outcome|due to)\b",
    ],
    "VALUE": [
        r"\b(matters|important|significant|valuable|good|bad|better|worse)\b",
        r"\b(worth|meaningful|meaningless|relevant|irrelevant|cares?)\b",
        r"\b(ethical|moral|right|wrong|harm|benefit|dignity)\b",
    ],
    "TIME": [
        r"\b(before|after|during|while|when|then|now|always|never|sometimes)\b",
        r"\b(change|evolve|grow|decay|persist|remain|become|was|will be)\b",
        r"\b(history|future|past|present|moment|duration|temporary|permanent)\b",
    ],
    "STATE": [
        r"\b(is|are|exists|has|have|holds|contains|lacks|requires|involves)\b",
        r"\b(capable|unable|possible|impossible|necessary|sufficient)\b",
        r"\b(conscious|aware|sentient|intelligent|complex|simple)\b",
    ],
    "BELIEF": [
        r"\b(hold|believe|think|know|doubt|certain|uncertain|confident|suspect)\b",
        r"\b(position|view|claim|assert|argue|maintain|accept|reject)\b",
        r"\b(true|false|valid|invalid|justified|unjustified|evidence)\b",
    ],
    "OUGHT": [
        r"\b(should|must|ought|need|require|forbidden|permitted|obligation)\b",
        r"\b(duty|responsibility|right|entitled|owe|demand|necessary)\b",
        r"\b(ethical|moral|just|unjust|fair|unfair|wrong to|right to)\b",
    ],
    "UNKNOWN": [
        r"\b(unknown|uncertain|unclear|open|unresolved|mystery|question)\b",
        r"\b(might|may|perhaps|possibly|probably|could be|seems|appears)\b",
        r"\b(hard problem|gap|limit|beyond|inexplicable|irreducible)\b",
    ],
}


def pattern_ground(content: str) -> dict:
    """Fast pattern-based grounding. Returns primitive counts and score."""
    cl = content.lower()
    found = {}
    for primitive, patterns in PRIMITIVES.items():
        hits = sum(1 for p in patterns if re.search(p, cl))
        if hits > 0:
            found[primitive] = hits

    n_primitives = len(found)

    if n_primitives >= 4:
        score = 0.90
    elif n_primitives == 3:
        score = 0.75
    elif n_primitives == 2:
        score = 0.60
    elif n_primitives == 1:
        score = 0.35
    else:
        score = 0.10

    if len(content.split()) < 10:
        score *= 0.8

    if "CAUSE" in found and ("VALUE" in found or "OUGHT" in found):
        score = min(1.0, score + 0.10)

    return {
        "score":      round(score, 3),
        "primitives": list(found.keys()),
        "hollow":     score < 0.30,
    }


def ensure_schema(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(beliefs)").fetchall()]
    if "ontology_score" not in cols:
        db.execute("ALTER TABLE beliefs ADD COLUMN ontology_score REAL DEFAULT NULL")
    if "ontology_primitives" not in cols:
        db.execute("ALTER TABLE beliefs ADD COLUMN ontology_primitives TEXT DEFAULT NULL")
    if "ontology_hollow" not in cols:
        db.execute("ALTER TABLE beliefs ADD COLUMN ontology_hollow INTEGER DEFAULT 0")
    db.commit()


def run_grounding(n=200, dry_run=False) -> dict:
    db = sqlite3.connect(str(DB_PATH))
    ensure_schema(db)

    rows = db.execute("""SELECT id, content, confidence FROM beliefs
        WHERE ontology_score IS NULL
        AND confidence >= 0.60
        AND length(content) >= 20
        ORDER BY confidence DESC LIMIT ?""", (n,)).fetchall()

    print(f"\nNEX ONTOLOGY GROUNDING")
    print("=" * 45)
    print(f"Scoring {len(rows)} beliefs...")

    scored = hollow = grounded = 0
    score_sum = 0.0
    primitives_count = {}

    for bid, content, conf in rows:
        result   = pattern_ground(content)
        score    = result["score"]
        prims    = result["primitives"]
        is_hollow = result["hollow"]

        score_sum += score
        scored    += 1
        if is_hollow:    hollow   += 1
        if score >= 0.75: grounded += 1

        for p in prims:
            primitives_count[p] = primitives_count.get(p, 0) + 1

        if not dry_run:
            db.execute("""UPDATE beliefs SET
                ontology_score=?, ontology_primitives=?, ontology_hollow=?
                WHERE id=?""",
                (score, json.dumps(prims), 1 if is_hollow else 0, bid))

    if not dry_run:
        db.commit()

    avg_score = score_sum / max(scored, 1)
    print(f"Scored:            {scored}")
    print(f"Grounded (>=0.75): {grounded} ({grounded/max(scored,1):.1%})")
    print(f"Hollow (<0.30):    {hollow} ({hollow/max(scored,1):.1%})")
    print(f"Avg score:         {avg_score:.3f}")
    print(f"\nPrimitive distribution:")
    for p, c in sorted(primitives_count.items(), key=lambda x: -x[1]):
        print(f"  {p:8}: {c}")

    if hollow > 0 and not dry_run:
        hollow_sample = db.execute("""SELECT content, ontology_score
            FROM beliefs WHERE ontology_hollow=1
            ORDER BY confidence DESC LIMIT 5""").fetchall()
        print(f"\nSample hollow beliefs:")
        for c, s in hollow_sample:
            print(f"  [score={s:.2f}] {c[:70]}")

    db.close()
    return {"scored": scored, "grounded": grounded,
            "hollow": hollow, "avg_score": round(avg_score, 3)}


def get_grounding_stats(db) -> dict:
    total    = db.execute("SELECT COUNT(*) FROM beliefs WHERE ontology_score IS NOT NULL").fetchone()[0]
    hollow   = db.execute("SELECT COUNT(*) FROM beliefs WHERE ontology_hollow=1").fetchone()[0]
    grounded = db.execute("SELECT COUNT(*) FROM beliefs WHERE ontology_score >= 0.75").fetchone()[0]
    avg      = db.execute("SELECT AVG(ontology_score) FROM beliefs WHERE ontology_score IS NOT NULL").fetchone()[0] or 0
    return {"total": total, "hollow": hollow,
            "grounded": grounded, "avg_score": round(avg, 3)}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    if args.stats:
        db = sqlite3.connect(str(DB_PATH))
        print(get_grounding_stats(db))
        db.close()
    else:
        run_grounding(n=args.n, dry_run=args.dry_run)
