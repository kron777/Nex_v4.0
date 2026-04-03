"""
nex_causal_engine.py
Causal reasoning over the belief graph.
Instead of flat similarity search, traverses edges to find:
- Belief chains: A supports B supports C
- Causal paths: what beliefs lead to a conclusion
- Contradiction chains: where belief A conflicts with B via path
Uses belief_relations edges (similar, bridges, opposes).
"""
import sqlite3, json, logging, time
from pathlib import Path
from collections import deque

log     = logging.getLogger("nex.causal")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

class CausalEngine:
    def __init__(self, db_path=DB_PATH):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row

    def get_belief(self, bid: int) -> dict:
        row = self.db.execute(
            "SELECT id, content, topic, confidence FROM beliefs WHERE id=?",
            (bid,)).fetchone()
        if not row: return {}
        return dict(row)

    def get_edges(self, bid: int, relation_types=None) -> list:
        """Get all edges from a belief node."""
        q = "SELECT target_id, weight, relation_type FROM belief_relations WHERE source_id=?"
        rows = self.db.execute(q, (bid,)).fetchall()
        edges = [dict(r) for r in rows]
        if relation_types:
            edges = [e for e in edges if e["relation_type"] in relation_types]
        return edges

    def causal_chain(self, start_id: int, max_depth=3,
                     relation_types=("similar","bridges")) -> list:
        """
        BFS from start_id following edges.
        Returns list of belief chains (paths through graph).
        """
        visited = {start_id}
        queue   = deque([[start_id]])
        chains  = []

        while queue and len(chains) < 10:
            path = queue.popleft()
            if len(path) > max_depth:
                continue

            current_id = path[-1]
            edges = self.get_edges(current_id, relation_types)

            for edge in edges:
                tid = edge["target_id"]
                if tid in visited:
                    continue
                visited.add(tid)
                new_path = path + [tid]

                # Only collect paths of length >= 2
                if len(new_path) >= 2:
                    beliefs = [self.get_belief(bid) for bid in new_path]
                    if all(b.get("confidence", 0) >= 0.6 for b in beliefs):
                        chains.append({
                            "path": new_path,
                            "beliefs": beliefs,
                            "depth": len(new_path),
                            "relation": edge["relation_type"]
                        })

                queue.append(new_path)

        return chains

    def find_support_chain(self, belief_id: int, topic: str) -> list:
        """Find beliefs that support a given belief via edges."""
        # Find beliefs pointing TO this one
        rows = self.db.execute("""
            SELECT source_id, weight, relation_type
            FROM belief_relations
            WHERE target_id=? AND relation_type='similar'
            ORDER BY weight DESC LIMIT 5
        """, (belief_id,)).fetchall()

        supporters = []
        for r in rows:
            b = self.get_belief(r["source_id"])
            if b and b.get("confidence", 0) >= 0.6:
                supporters.append({
                    "belief": b,
                    "weight": r["weight"],
                    "relation": r["relation_type"]
                })
        return supporters

    def find_opposition_chain(self, belief_id: int) -> list:
        """Find beliefs that oppose a given belief."""
        rows = self.db.execute("""
            SELECT target_id, weight FROM belief_relations
            WHERE source_id=? AND relation_type='opposes'
        """, (belief_id,)).fetchall()

        opposing = []
        for r in rows:
            b = self.get_belief(r["target_id"])
            if b:
                opposing.append({"belief": b, "weight": r["weight"]})
        return opposing

    def reason_from_query(self, query_belief_ids: list,
                          max_hops=2) -> dict:
        """
        Given seed belief IDs from FAISS, expand via causal traversal.
        Returns enriched context for LLM prompt injection.
        """
        all_beliefs = {}
        chains      = []
        oppositions = []

        for bid in query_belief_ids[:3]:  # limit seeds
            b = self.get_belief(bid)
            if not b: continue
            all_beliefs[bid] = b

            # Expand via edges
            c = self.causal_chain(bid, max_depth=max_hops)
            chains.extend(c)

            # Find oppositions
            opp = self.find_opposition_chain(bid)
            oppositions.extend(opp)

            # Find supporters
            sup = self.find_support_chain(bid, b.get("topic",""))
            for s in sup:
                all_beliefs[s["belief"]["id"]] = s["belief"]

        return {
            "seed_beliefs":  list(all_beliefs.values()),
            "chains":        chains[:5],
            "oppositions":   oppositions[:3],
            "total_beliefs": len(all_beliefs)
        }

    def format_for_prompt(self, reasoning: dict) -> str:
        """Format causal reasoning result for LLM prompt injection."""
        lines = []

        if reasoning["seed_beliefs"]:
            lines.append("RELEVANT BELIEFS:")
            for b in reasoning["seed_beliefs"][:5]:
                lines.append(f"  - [{b['topic']}] {b['content'][:100]}")

        if reasoning["chains"]:
            lines.append("\nBELIEF CHAINS (connected reasoning):")
            for c in reasoning["chains"][:3]:
                chain_text = " → ".join(
                    b["content"][:60] for b in c["beliefs"])
                lines.append(f"  {chain_text}")

        if reasoning["oppositions"]:
            lines.append("\nKNOWN COUNTERARGUMENTS:")
            for o in reasoning["oppositions"]:
                lines.append(f"  - {o['belief']['content'][:80]}")

        return "\n".join(lines)

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    sys.path.insert(0, "/home/rr/Desktop/nex")

    engine = CausalEngine()

    # Test: find a high-conf consciousness belief and traverse
    row = engine.db.execute("""
        SELECT id, content FROM beliefs
        WHERE topic='consciousness' AND confidence >= 0.80
        LIMIT 1""").fetchone()

    if row:
        print(f"Seed belief: {row['content'][:80]}")
        chains = engine.causal_chain(row["id"], max_depth=2)
        print(f"Found {len(chains)} causal chains")
        for c in chains[:3]:
            print(f"\nChain (depth {c['depth']}):")
            for b in c["beliefs"]:
                print(f"  → [{b['topic']}] {b['content'][:70]}")

        reasoning = engine.reason_from_query([row["id"]])
        print(f"\n--- Prompt block ---")
        print(engine.format_for_prompt(reasoning))
