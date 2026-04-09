#!/usr/bin/env python3
"""
nex_causal_extractor.py — Causal Edge Extractor
=================================================
Scans beliefs for causal language and creates directed
edges in belief_links with type='causes'|'enables'|'follows_from'.

No LLM needed. Pure pattern matching on existing belief content.
This is the minimal viable causal reasoning layer.

What this gives NEX:
- Directed belief graph (not just similarity links)
- Ability to traverse: "what does X cause?" 
- ThrowNet can use causal chains to resolve constraints
"""
import sqlite3
import re
import logging
from pathlib import Path

log     = logging.getLogger("nex.causal")
DB_PATH = Path("/home/rr/Desktop/nex/nex.db")

# Causal patterns — ordered by specificity
CAUSAL_PATTERNS = [
    # Strong causation
    (r'(.{10,80})\s+causes?\s+(.{15,80})',           'causes'),
    (r'(.{10,80})\s+leads?\s+to\s+(.{15,80})',        'causes'),
    (r'(.{10,80})\s+results?\s+in\s+(.{15,80})',      'causes'),
    (r'(.{10,80})\s+produces?\s+(.{15,80})',          'causes'),
    # Enablement
    (r'(.{10,80})\s+enables?\s+(.{15,80})',           'enables'),
    (r'(.{10,80})\s+allows?\s+(.{15,80})',            'enables'),
    (r'(.{10,80})\s+requires?\s+(.{15,80})',          'requires'),
    # Logical sequence
    (r'(.{10,80})\s+therefore\s+(.{15,80})',          'follows_from'),
    (r'(.{10,80})\s+because\s+(.{15,80})',            'follows_from'),
    (r'(.{10,80})\s+thus\s+(.{15,80})',               'follows_from'),
    (r'(.{10,80})\s+hence\s+(.{15,80})',              'follows_from'),
    # Contradiction
    (r'(.{10,80})\s+contradicts?\s+(.{15,80})',       'contradicts'),
    (r'(.{10,80})\s+despite\s+(.{15,80})',            'contradicts'),
]

STOP = {'the','and','for','with','from','that','this','have','not','are',
        'was','were','will','would','could','should','been','being'}


def _tokenize(text: str) -> set:
    return set(re.findall(r'\b[a-z]{4,}\b', text.lower())) - STOP


def _find_matching_belief(phrase: str, beliefs: list, min_overlap: int = 2) -> int:
    """Find belief ID whose content best matches a phrase."""
    p_tokens = _tokenize(phrase)
    best_score, best_id = 0, None
    for bid, content, _ in beliefs:
        overlap = len(p_tokens & _tokenize(content))
        if overlap > best_score and overlap >= min_overlap:
            best_score = overlap
            best_id = bid
    return best_id


def extract_causal_edges(verbose: bool = False) -> int:
    """
    Scan all beliefs for causal language.
    Create directed belief_links with causal type.
    Returns count of new edges created.
    """
    if not DB_PATH.exists():
        return 0

    try:
        con = sqlite3.connect(str(DB_PATH), timeout=5)
        con.row_factory = sqlite3.Row

        beliefs = con.execute("""
            SELECT id, content, topic FROM beliefs
            WHERE content IS NOT NULL AND length(content) > 40
            ORDER BY confidence DESC
        """).fetchall()
        beliefs = [(r['id'], r['content'], r['topic']) for r in beliefs]

        # Get existing causal links to avoid duplicates
        existing = set()
        for row in con.execute("""
            SELECT parent_id, child_id FROM belief_links
            WHERE link_type IN ('causes','enables','requires','follows_from','contradicts')
        """).fetchall():
            existing.add((row['parent_id'], row['child_id']))

    except Exception as e:
        log.error(f"causal extract DB error: {e}")
        return 0

    new_edges = 0
    for bid, content, topic in beliefs:
        text = content.lower()
        for pattern, link_type in CAUSAL_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                cause_phrase  = match.group(1).strip()
                effect_phrase = match.group(2).strip()

                # Find beliefs that match each phrase
                cause_id  = _find_matching_belief(cause_phrase, beliefs)
                effect_id = _find_matching_belief(effect_phrase, beliefs)

                if not cause_id or not effect_id:
                    continue
                if cause_id == effect_id:
                    continue
                if (cause_id, effect_id) in existing:
                    continue

                try:
                    con.execute("""
                        INSERT OR IGNORE INTO belief_links
                        (parent_id, child_id, link_type)
                        VALUES (?, ?, ?)
                    """, (cause_id, effect_id, link_type))
                    existing.add((cause_id, effect_id))
                    new_edges += 1
                    if verbose:
                        log.info(f"[{link_type}] {cause_phrase[:40]} → {effect_phrase[:40]}")
                except Exception:
                    pass

    con.commit()
    con.close()

    if verbose or new_edges:
        print(f"  [CausalExtractor] {new_edges} new causal edges from {len(beliefs)} beliefs")
    return new_edges


def get_causal_chain(belief_id: int, depth: int = 2) -> list:
    """
    Traverse causal graph from a belief.
    Returns list of (belief_content, link_type) tuples.
    """
    if not DB_PATH.exists():
        return []
    try:
        con = sqlite3.connect(str(DB_PATH), timeout=3)
        con.row_factory = sqlite3.Row
        results = []
        visited = {belief_id}
        queue   = [(belief_id, 0)]
        while queue:
            curr_id, curr_depth = queue.pop(0)
            if curr_depth >= depth:
                continue
            rows = con.execute("""
                SELECT bl.child_id, bl.link_type, b.content
                FROM belief_links bl
                JOIN beliefs b ON bl.child_id = b.id
                WHERE bl.parent_id = ?
                  AND bl.link_type IN ('causes','enables','follows_from')
            """, (curr_id,)).fetchall()
            for row in rows:
                if row['child_id'] not in visited:
                    visited.add(row['child_id'])
                    results.append({
                        'content':   row['content'][:120],
                        'link_type': row['link_type'],
                        'depth':     curr_depth + 1,
                    })
                    queue.append((row['child_id'], curr_depth + 1))
        con.close()
        return results
    except Exception as e:
        log.error(f"causal chain error: {e}")
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = extract_causal_edges(verbose=True)
    print(f"\nTotal new causal edges: {n}")
    con = sqlite3.connect(str(DB_PATH))
    counts = con.execute("""
        SELECT link_type, COUNT(*) as n
        FROM belief_links
        WHERE link_type IN ('causes','enables','requires','follows_from','contradicts')
        GROUP BY link_type
    """).fetchall()
    for row in counts:
        print(f"  {row[0]}: {row[1]}")
