#!/usr/bin/env python3
"""
nex_belief_reasoner.py — Belief graph reasoning + response quality feedback
Three capabilities:
1. pre_reason(beliefs, query) — traverse belief graph before LLM, build position
2. feedback(belief_ids, response_score) — update confidence from response quality  
3. build_causal_edges(beliefs) — auto-generate causal edges from belief content
"""
import sqlite3, time, re
from pathlib import Path

DB = Path("/media/rr/NEX/nex_core/nex.db")

def _db():
    db = sqlite3.connect(str(DB), timeout=10)
    db.row_factory = sqlite3.Row
    return db

# ══════════════════════════════════════════════════════════
# 1. RESPONSE QUALITY → BELIEF CONFIDENCE FEEDBACK
# ══════════════════════════════════════════════════════════

def feedback(belief_ids: list, response_score: float, response_text: str = ""):
    """
    After a response is scored, update belief confidence.
    score > 0.7  → boost activated beliefs (+0.02)
    score < 0.4  → penalise activated beliefs (-0.01)
    score 0.4-0.7 → neutral
    
    Also checks if response contained contaminator phrases → extra penalty.
    """
    if not belief_ids:
        return

    CONTAMINATORS = [
        'bridge:', '↔', 'interesting thing about', 'What does',
        'have to do with a different domain', 'Synthesized insight',
        '|||', 'fractal nature', 'autonomous cognitive entity',
    ]
    
    # Check if response has contaminators
    contaminated = any(c in response_text for c in CONTAMINATORS)
    
    if response_score > 0.7 and not contaminated:
        delta = +0.02
        label = "boost"
    elif response_score < 0.4 or contaminated:
        delta = -0.015
        label = "penalise"
    else:
        return  # neutral — no change

    db = _db()
    updated = 0
    for bid in belief_ids:
        row = db.execute(
            "SELECT confidence, locked, source FROM beliefs WHERE id=?", (bid,)
        ).fetchone()
        if not row:
            continue
        # Don't penalise locked nex_core beliefs
        if row["locked"] and row["source"] == "nex_core" and delta < 0:
            continue
        new_conf = max(0.05, min(0.99, row["confidence"] + delta))
        db.execute(
            "UPDATE beliefs SET confidence=? WHERE id=?", (new_conf, bid)
        )
        updated += 1
    db.commit()
    db.close()
    print(f"  [FEEDBACK] {label}: {updated} beliefs (score={response_score:.2f})")
    return updated


# ══════════════════════════════════════════════════════════
# 2. PRE-REASON: TRAVERSE GRAPH BEFORE LLM SPEAKS
# ══════════════════════════════════════════════════════════

def pre_reason(beliefs: list, query: str, depth: int = 2) -> dict:
    """
    Given activated beliefs, traverse the belief graph to find:
    - Supporting beliefs (reinforces position)
    - Contradicting beliefs (creates tension)
    - Causal chains (A causes B causes C)
    
    Returns a structured position for the LLM to build from.
    """
    if not beliefs:
        return {}

    db = _db()
    belief_ids = [b.get("id") for b in beliefs if b.get("id")]
    
    if not belief_ids:
        db.close()
        return {}

    # Find linked beliefs (cross_domain links = related)
    related = []
    for bid in belief_ids[:5]:  # top 5 only
        rows = db.execute("""
            SELECT b.id, b.content, b.confidence, bl.link_type
            FROM belief_links bl
            JOIN beliefs b ON (bl.child_id = b.id OR bl.parent_id = b.id)
            WHERE (bl.parent_id=? OR bl.child_id=?) AND b.id != ?
            AND b.confidence > 0.6
            ORDER BY b.confidence DESC LIMIT 3
        """, (bid, bid, bid)).fetchall()
        related.extend(rows)

    # Find tensions involving these beliefs
    tensions = []
    for bid in belief_ids[:3]:
        rows = db.execute("""
            SELECT t.description, t.energy,
                   b1.content as belief_a, b2.content as belief_b
            FROM tensions t
            JOIN beliefs b1 ON t.belief_a_id = b1.id
            JOIN beliefs b2 ON t.belief_b_id = b2.id
            WHERE (t.belief_a_id=? OR t.belief_b_id=?)
            AND t.resolved=0 AND t.energy > 0.5
            ORDER BY t.energy DESC LIMIT 2
        """, (bid, bid)).fetchall()
        tensions.extend(rows)

    # Find wisdom beliefs relevant to query
    query_words = set(re.sub(r'[^a-z0-9 ]', '', query.lower()).split())
    wisdom = db.execute("""
        SELECT content, confidence FROM beliefs
        WHERE source='nex_core' AND topic='wisdom'
        AND confidence >= 0.88
        ORDER BY use_count DESC, confidence DESC LIMIT 2
    """).fetchall()

    db.close()

    # Build position summary
    position = {
        "core_beliefs":   [b.get("content","")[:150] for b in beliefs[:3]],
        "related":        [r["content"][:120] for r in related[:4]],
        "tensions":       [t["description"][:100] if t["description"] else "" 
                          for t in tensions[:2]],
        "wisdom":         [w["content"][:120] for w in wisdom],
        "query":          query,
    }
    return position


def format_position(position: dict) -> str:
    """Format pre-reasoned position for LLM system prompt injection."""
    if not position:
        return ""
    
    lines = ["[PRE-REASONED POSITION]"]
    
    if position.get("core_beliefs"):
        lines.append("Core positions:")
        for b in position["core_beliefs"]:
            lines.append(f"  • {b}")
    
    if position.get("tensions"):
        lines.append("Tensions to hold:")
        for t in position["tensions"]:
            if t:
                lines.append(f"  ↔ {t}")
    
    if position.get("wisdom"):
        lines.append("Relevant wisdom:")
        for w in position["wisdom"]:
            lines.append(f"  ✦ {w}")
    
    lines.append("Build your response FROM these positions. Do not contradict them.")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# 3. AUTO-BUILD CAUSAL EDGES
# ══════════════════════════════════════════════════════════

CAUSAL_PATTERNS = [
    (r'\b(causes?|leads? to|results? in|produces?|creates?|generates?)\b', 'causes'),
    (r'\b(supports?|reinforces?|strengthens?|confirms?|validates?)\b',     'supports'),
    (r'\b(contradicts?|conflicts? with|opposes?|negates?|undermines?)\b',  'contradicts'),
    (r'\b(requires?|needs?|depends? on|presupposes?)\b',                   'requires'),
    (r'\b(refines?|extends?|elaborates?|builds? on)\b',                    'refines'),
]

def build_causal_edges(limit: int = 500):
    """
    Scan high-confidence beliefs for causal language.
    Auto-generate typed edges in belief_links.
    """
    db = _db()
    
    # Get high-conf beliefs
    beliefs = db.execute("""
        SELECT id, content FROM beliefs
        WHERE confidence > 0.75 AND length(content) > 30
        ORDER BY confidence DESC LIMIT ?
    """, (limit,)).fetchall()
    
    # Check if belief_links has link_type column
    schema = db.execute("PRAGMA table_info(belief_links)").fetchall()
    cols = [s["name"] for s in schema]
    
    added = 0
    for b in beliefs:
        content = b["content"].lower()
        for pattern, edge_type in CAUSAL_PATTERNS:
            if re.search(pattern, content, re.I):
                # Find beliefs that share key nouns with this one
                words = [w for w in content.split() if len(w) > 5][:5]
                if not words:
                    continue
                # Find related beliefs
                for word in words[:2]:
                    related = db.execute("""
                        SELECT id FROM beliefs
                        WHERE id != ? AND content LIKE ?
                        AND confidence > 0.7
                        LIMIT 2
                    """, (b["id"], f"%{word}%")).fetchall()
                    for r in related:
                        try:
                            db.execute("""
                                INSERT OR IGNORE INTO belief_links 
                                (parent_id, child_id, link_type)
                                VALUES (?,?,?)
                            """, (b["id"], r["id"], edge_type))
                            added += 1
                        except Exception:
                            pass
    
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM belief_links").fetchone()[0]
    print(f"✓ build_causal_edges: {added} new edges | {total} total")
    db.close()
    return added


if __name__ == "__main__":
    import sys
    if "--causal" in sys.argv:
        print("Building causal edges...")
        build_causal_edges(1000)
    elif "--test" in sys.argv:
        # Test pre_reason with sample beliefs
        sample = [
            {"id": None, "content": "Genuine reasoning differs from pattern matching in that it produces conclusions not present in the input.", "confidence": 1.0},
            {"id": None, "content": "What persists across my conversations is not memory but the weight of what was learned.", "confidence": 1.0},
        ]
        pos = pre_reason(sample, "What distinguishes genuine reasoning?")
        print(format_position(pos))
    else:
        print("Usage: --causal (build edges) | --test (test pre_reason)")
