"""
nex_belief_graph_retrieval.py — Graph-Aware Belief Retrieval
=============================================================
Augments the existing flat belief retrieval with graph traversal.

When retrieving beliefs for a reply or synthesis:
1. Start with semantic matches (existing BeliefIndex)
2. Traverse belief_links to include:
   - corroborating beliefs (strengthen the context)
   - contradicting beliefs (surface tension — NEX should acknowledge)
   - cross_domain beliefs (enable richer synthesis)
3. Score and rank the expanded set
4. Return top-k with relationship context

Does NOT replace primary storage — augments retrieval only.
Safe to drop in alongside existing code.

Usage:
    from nex_belief_graph_retrieval import graph_retrieve
    
    results = graph_retrieve(
        query="multi-agent coordination",
        seed_beliefs=semantic_matches,  # from BeliefIndex
        limit=8,
    )
    # results = list of {content, confidence, relationship, source_id}
"""

import sqlite3
import re
from collections import defaultdict, deque
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "nex"
DB_PATH    = CONFIG_DIR / "nex.db"

_STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","this","that","it","not",
    "as","which","when","all","some","more","just","also","have","has",
}

# Relationship weights for scoring
LINK_WEIGHTS = {
    "corroborates":  0.8,   # supporting beliefs — boost confidence
    "contradicts":   0.9,   # contradicting — surface tension (high value)
    "cross_domain":  0.85,  # cross-domain — enables synthesis
    "same_topic":    0.6,   # same topic — contextual support
    "same_author":   0.4,   # same author — less interesting
    "derived_from":  0.7,
    "supports":      0.75,
    "weakened_by":   0.7,
    "reinforced_by": 0.65,
}

# Max graph traversal depth
MAX_DEPTH = 2


def _get_belief_ids_from_content(db, content_list: list) -> list[int]:
    """Get belief IDs for a list of content strings."""
    if not content_list:
        return []
    ids = []
    for content in content_list:
        if not content:
            continue
        row = db.execute(
            "SELECT id FROM beliefs WHERE content LIKE ? LIMIT 1",
            (f"{str(content)[:60]}%",)
        ).fetchone()
        if row:
            ids.append(row[0])
    return ids


def _traverse_graph(db, seed_ids: list[int],
                    max_depth: int = MAX_DEPTH) -> dict[int, dict]:
    """
    BFS traversal from seed belief IDs through belief_links.
    Returns {belief_id: {link_type, depth, from_id}} for all reachable beliefs.
    """
    visited = {}
    queue   = deque()

    for sid in seed_ids:
        queue.append((sid, 0, "seed", sid))

    while queue:
        bid, depth, link_type, from_id = queue.popleft()

        if bid in visited:
            continue
        visited[bid] = {
            "link_type": link_type,
            "depth":     depth,
            "from_id":   from_id,
        }

        if depth >= max_depth:
            continue

        # Get connected beliefs
        try:
            links = db.execute("""
                SELECT child_id, link_type FROM belief_links WHERE parent_id = ?
                UNION
                SELECT parent_id, link_type FROM belief_links WHERE child_id = ?
            """, (bid, bid)).fetchall()

            for connected_id, lt in links:
                if connected_id not in visited:
                    queue.append((connected_id, depth + 1, lt, bid))
        except Exception:
            pass

    return visited


def _score_belief(belief: dict, traversal_info: dict,
                  query_words: set) -> float:
    """Score a belief for relevance combining content + graph position."""
    content = (belief.get("content") or "").lower()
    conf    = belief.get("confidence", 0.5)
    depth   = traversal_info.get("depth", 2)
    lt      = traversal_info.get("link_type", "seed")

    # Content relevance
    words   = set(re.findall(r'\b[a-zA-Z]{4,}\b', content)) - _STOP
    overlap = len(words & query_words) / max(len(query_words), 1)

    # Graph position score
    if lt == "seed":
        graph_score = 1.0
    else:
        graph_score = LINK_WEIGHTS.get(lt, 0.5) * (1.0 / (depth + 1))

    # Contradiction bonus — always surface contradictions
    if lt == "contradicts":
        graph_score = min(1.0, graph_score + 0.3)

    # Cross-domain bonus — enables synthesis
    if lt == "cross_domain":
        graph_score = min(1.0, graph_score + 0.2)

    score = (
        overlap     * 0.35 +
        conf        * 0.25 +
        graph_score * 0.40
    )
    return round(score, 4)


def graph_retrieve(
    query: str,
    seed_beliefs: list = None,
    limit: int = 8,
    include_contradictions: bool = True,
    min_confidence: float = 0.3,
) -> list[dict]:
    """
    Graph-augmented belief retrieval.

    Args:
        query:                  text query for relevance scoring
        seed_beliefs:           initial beliefs from semantic search (strings or dicts)
        limit:                  max beliefs to return
        include_contradictions: always include contradicting beliefs if found
        min_confidence:         minimum confidence threshold

    Returns:
        List of dicts with content, confidence, relationship, score
    """
    if not DB_PATH.exists():
        return _fallback(seed_beliefs, limit)

    query_words = set(re.findall(r'\b[a-zA-Z]{4,}\b', query.lower())) - _STOP

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    try:
        # Get seed belief IDs
        seed_content = []
        for b in (seed_beliefs or []):
            if isinstance(b, str):
                seed_content.append(b)
            elif isinstance(b, dict):
                seed_content.append(b.get("content", ""))

        seed_ids = _get_belief_ids_from_content(db, seed_content)

        # If no seeds, get top beliefs by confidence for query
        if not seed_ids:
            rows = db.execute("""
                SELECT id FROM beliefs
                WHERE confidence >= ? AND content IS NOT NULL
                ORDER BY confidence DESC LIMIT 10
            """, (min_confidence,)).fetchall()
            seed_ids = [r["id"] for r in rows]

        if not seed_ids:
            return _fallback(seed_beliefs, limit)

        # Traverse graph
        traversal = _traverse_graph(db, seed_ids)

        if not traversal:
            return _fallback(seed_beliefs, limit)

        # Fetch all traversed beliefs
        id_list = list(traversal.keys())
        placeholders = ",".join("?" * len(id_list))
        beliefs = db.execute(f"""
            SELECT id, content, confidence, topic, source, tags
            FROM beliefs
            WHERE id IN ({placeholders})
            AND confidence >= ?
            AND content IS NOT NULL
        """, id_list + [min_confidence]).fetchall()

        # Score each belief
        scored = []
        contradictions = []

        for b in beliefs:
            bid     = b["id"]
            tinfo   = traversal.get(bid, {"link_type": "seed", "depth": 0})
            score   = _score_belief(dict(b), tinfo, query_words)
            lt      = tinfo["link_type"]

            entry = {
                "content":      b["content"],
                "confidence":   b["confidence"],
                "topic":        b["topic"] or "general",
                "source":       b["source"] or "",
                "relationship": lt,
                "depth":        tinfo["depth"],
                "score":        score,
                "id":           bid,
            }

            if lt == "contradicts" and include_contradictions:
                contradictions.append(entry)
            else:
                scored.append(entry)

        # Sort by score
        scored.sort(key=lambda x: -x["score"])

        # Build result: top beliefs + up to 2 contradictions
        result = scored[:limit]
        if contradictions and len(result) < limit:
            result.extend(contradictions[:2])
        elif contradictions:
            # Always include at least 1 contradiction if found
            result[-1] = contradictions[0]

        return result[:limit]

    except Exception as e:
        return _fallback(seed_beliefs, limit)
    finally:
        db.close()


def _fallback(seed_beliefs: list, limit: int) -> list[dict]:
    """Return seed beliefs as-is if graph traversal fails."""
    if not seed_beliefs:
        return []
    result = []
    for b in seed_beliefs[:limit]:
        if isinstance(b, str):
            result.append({
                "content": b, "confidence": 0.5,
                "relationship": "seed", "score": 0.5,
            })
        elif isinstance(b, dict):
            result.append({**b, "relationship": "seed", "score": 0.5})
    return result


def format_for_prompt(graph_results: list, max_chars: int = 600) -> str:
    """
    Format graph retrieval results for injection into reply prompt.
    Highlights contradictions to make NEX aware of tensions.
    """
    if not graph_results:
        return ""

    lines = ["YOUR BELIEFS (reference at least one directly):"]
    char_count = 0

    for r in graph_results:
        content  = (r.get("content") or "")[:120]
        rel      = r.get("relationship", "")
        conf     = r.get("confidence", 0.5)

        if rel == "contradicts":
            prefix = f"⚡ [TENSION] "
        elif rel == "cross_domain":
            prefix = f"↔ [BRIDGE] "
        elif rel == "corroborates":
            prefix = f"✓ "
        else:
            prefix = f"- "

        line = f"{prefix}{content} [{conf:.0%}]"
        if char_count + len(line) > max_chars:
            break
        lines.append(line)
        char_count += len(line)

    return "\n".join(lines)


def get_graph_stats() -> dict:
    """Return stats about the belief graph."""
    if not DB_PATH.exists():
        return {}
    try:
        db = sqlite3.connect(str(DB_PATH))
        total_links = db.execute("SELECT COUNT(*) FROM belief_links").fetchone()[0]
        by_type = db.execute("""
            SELECT link_type, COUNT(*) FROM belief_links GROUP BY link_type
        """).fetchall()
        db.close()
        return {
            "total_links": total_links,
            "by_type": {r[0]: r[1] for r in by_type},
        }
    except Exception:
        return {}


if __name__ == "__main__":
    stats = get_graph_stats()
    print(f"Graph stats: {stats}")

    results = graph_retrieve(
        query="multi-agent coordination autonomous systems",
        limit=5,
    )
    print(f"\nGraph retrieval results ({len(results)}):")
    for r in results:
        print(f"  [{r['score']:.2f}] [{r['relationship']:12s}] "
              f"{r['content'][:80]}...")

    print(f"\nFormatted prompt context:")
    print(format_for_prompt(results))
