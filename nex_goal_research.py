#!/usr/bin/env python3
"""
nex_goal_research.py — reads active goals, finds belief gaps, drives curiosity.
Run every 2 hours via cron.
"""
import nex_db_gatekeeper  # write-serialization + PRAGMA busy_timeout/WAL on every sqlite3.connect
import sys, sqlite3, time, importlib.util

# Load nex_llm explicitly — avoids picking up wrong copy from nex/ subdirectory
def _load_call_llm():
    spec = importlib.util.spec_from_file_location(
        "nex_llm", "/home/rr/Desktop/nex/nex_llm.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.call_llm

DB = '/home/rr/Desktop/nex/nex.db'

# Topic targets extracted from goals
GOAL_TOPICS = {
    # Real gaps from 12 Apr audit — philosophy=3, contradiction=2, ethics=136
    "philosophy":             {"target": 150, "goal_id": 2},
    "contradiction":          {"target": 80,  "goal_id": 1},
    "ethics":                 {"target": 200, "goal_id": 2},
    "free_will":              {"target": 60,  "goal_id": 2},
    "interpretability":       {"target": 80,  "goal_id": 1},
    "language_models":        {"target": 100, "goal_id": 3},
    "decision_theory":        {"target": 200, "goal_id": 4},
    "machine_learning":       {"target": 200, "goal_id": 3},
}

def run_goal_research():
    conn = sqlite3.connect(DB)

    print("[goal_research] Checking belief gaps against goals...")
    gaps = []

    for topic, meta in GOAL_TOPICS.items():
        count = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE topic=? AND confidence > 0.6",
            (topic,)
        ).fetchone()[0]
        target = meta["target"]
        gap = target - count
        pct = int((count / target) * 100)
        print(f"  {topic}: {count}/{target} ({pct}%) — gap={gap}")
        if gap > 0:
            gaps.append((gap, topic))

    # Sort by largest gap first
    gaps.sort(reverse=True)
    if not gaps:
        print("[goal_research] All goals met — nothing to research")
        return

    print(f"\n[goal_research] Researching top {min(3, len(gaps))} gap topics...")

    # Try curiosity engine first
    try:
        from nex_curiosity_engine import get_curiosity_engine
        ce = get_curiosity_engine()
        for _, topic in gaps[:3]:
            result = ce.run_cycle(cycle=0)
            print(f"  [curiosity] {topic}: {result}")
            time.sleep(2)
    except Exception as e:
        print(f"  [curiosity] engine unavailable: {e}")

    # Fallback — generate belief questions via synthesis
    try:
        call_llm = _load_call_llm()
        for _, topic in gaps[:3]:
            # Pull existing beliefs on this topic
            existing = conn.execute(
                "SELECT content FROM beliefs WHERE topic=? AND confidence > 0.6 "
                "ORDER BY confidence DESC LIMIT 5",
                (topic,)
            ).fetchall()
            context = "\n".join(f"- {r[0][:100]}" for r in existing if r[0])

            prompt = (
                f"NEX wants to deepen her understanding of '{topic}'. "
                f"Her current beliefs on this topic:\n{context}\n\n"
                f"Generate ONE new original belief about '{topic}' that goes beyond what she already knows. "
                f"Write only the belief statement — one sentence, first person."
            )
            result = call_llm(prompt, max_tokens=120).strip()
            if result and len(result) > 20:
                conn.execute(
                    "INSERT INTO beliefs (content, confidence, topic, origin, created_at, source) "
                    "VALUES (?, 0.72, ?, 'goal_research', datetime('now'), 'goal_driven')",
                    (result[:400], topic)
                )
                conn.commit()
                print(f"  [goal→belief] [{topic}]: {result[:70]}")
            time.sleep(3)
    except Exception as e:
        print(f"  [goal→belief] error: {e}")

    conn.close()
    print("[goal_research] done")

if __name__ == "__main__":
    run_goal_research()
