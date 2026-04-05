#!/usr/bin/env python3
"""
nex_belief_chain.py — Chain causal graph beliefs into arguments
Instead of returning top-5 independent beliefs, follow the causal
graph from seed beliefs to build a genuine argument chain.

NEX: "X because Y, which means Z, and therefore W."
"""
import sqlite3
from pathlib import Path

DB = Path.home() / "Desktop/nex/nex.db"

def get_causal_chain(seed_belief_ids: list, depth: int = 3, max_chain: int = 4) -> list:
    """
    Follow causal edges from seed beliefs to build an argument chain.
    Returns ordered list of (belief_content, relation_type, confidence).
    """
    if not seed_belief_ids:
        return []
    
    try:
        db = sqlite3.connect(str(DB), timeout=3)
        chain = []
        visited = set()
        frontier = list(seed_belief_ids[:2])
        
        for _ in range(depth):
            if not frontier or len(chain) >= max_chain:
                break
            current_id = frontier.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)
            
            # Get belief content
            row = db.execute(
                "SELECT content, confidence, topic FROM beliefs WHERE id=?", 
                (current_id,)
            ).fetchone()
            if row and row[0]:
                chain.append({
                    "content": row[0],
                    "confidence": row[1],
                    "topic": row[2],
                    "id": current_id
                })
            
            # Follow causal edges
            edges = db.execute("""
                SELECT to_id, edge_type, weight FROM belief_edges
                WHERE from_id=? AND weight > 0.4
                ORDER BY weight DESC LIMIT 3
            """, (current_id,)).fetchall()
            
            for to_id, edge_type, weight in edges:
                if to_id not in visited:
                    frontier.append(to_id)
        
        db.close()
        return chain
    except Exception:
        return []

def format_chain_as_argument(chain: list) -> str:
    """Format a belief chain as a flowing argument."""
    if not chain:
        return ""
    if len(chain) == 1:
        return chain[0]["content"]
    
    connectors = [
        "which means",
        "and therefore",
        "because of this",
        "this suggests",
        "leading to",
        "and so",
    ]
    
    parts = [chain[0]["content"].rstrip(".")]
    for i, belief in enumerate(chain[1:], 1):
        conn = connectors[min(i-1, len(connectors)-1)]
        parts.append(f"{conn} {belief['content'].rstrip('.')}")
    
    return ". ".join(parts) + "."

def chain_response(seed_ids: list, query: str = "") -> str:
    """Get a chained argument from seed belief IDs."""
    chain = get_causal_chain(seed_ids, depth=3, max_chain=3)
    if len(chain) < 2:
        return ""
    return format_chain_as_argument(chain)
