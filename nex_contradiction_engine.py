#!/usr/bin/env python3
"""nex_contradiction_engine.py — detects conflicting beliefs and resolves them."""
import sqlite3, os, time, json
from pathlib import Path

DB_PATH = Path.home() / ".config" / "nex" / "nex.db"

def run_contradiction_cycle(cycle: int = 0, llm_fn=None) -> int:
    if cycle % 5 != 0:
        return 0
    if not llm_fn:
        return 0
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT topic, content, confidence FROM beliefs WHERE confidence > 0.3 ORDER BY topic, confidence DESC")
        rows = cur.fetchall()
        buckets = {}
        for topic, content, conf in rows:
            buckets.setdefault(topic, []).append((content, conf))
        resolved = 0
        for topic, beliefs in buckets.items():
            if len(beliefs) < 2:
                continue
            if topic.startswith("[") or topic.startswith("{") or len(topic) > 60:
                continue
            if topic in ("None", "general", "unknown", "auto_learn"):
                continue
            sample = beliefs[:6]
            texts = "\n".join(f"- {b[0][:120]}" for b in sample)
            prompt = f"Do any of these beliefs about '{topic}' directly contradict each other? If yes, write one synthesized resolution belief in one sentence. If no contradictions, reply NONE.\n\n{texts}"
            try:
                result = llm_fn(prompt, task_type="synthesis")
                if result and result.strip().upper() != "NONE" and len(result) > 20:
                    cur.execute(
                        "INSERT OR IGNORE INTO beliefs (content, confidence, topic, origin, timestamp) VALUES (?,?,?,?,?)",
                        (result.strip()[:500], 0.82, topic, "contradiction_engine", time.strftime("%Y-%m-%dT%H:%M:%S"))
                    )
                    conn.commit()
                    print(f"  [CONTRA] resolved conflict in '{topic}'")
                    resolved += 1
            except Exception:
                pass
        conn.close()
        return resolved
    except Exception as e:
        print(f"  [CONTRA] error: {e}")
        return 0
