#!/usr/bin/env python3
"""nex_contradiction_engine.py — detects conflicting beliefs and resolves them."""
import sqlite3, os, time, json
from pathlib import Path
from datetime import datetime

DB_PATH = Path.home() / ".config" / "nex" / "nex.db"

def run_contradiction_cycle(cycle: int = 0, llm_fn=None) -> int:
    if cycle % 5 != 0:
        return 0
    if not llm_fn:
        return 0
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # Ensure resolved-topics table exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contra_resolved (
                topic        TEXT PRIMARY KEY,
                resolved_at  TEXT,
                belief_count INTEGER DEFAULT 0
            )
        """)
        conn.commit()

        # Load resolved cache — skip topics settled within 48h with no new beliefs
        _now = time.time()
        _48h = 48 * 3600
        cur.execute("SELECT topic, resolved_at, belief_count FROM contra_resolved")
        _resolved_cache = {
            row[0]: {"ts": row[1], "count": row[2]}
            for row in cur.fetchall()
        }

        cur.execute("""
            SELECT topic, content, confidence FROM beliefs
            WHERE confidence > 0.3
            ORDER BY topic, confidence DESC
        """)
        rows = cur.fetchall()
        buckets = {}
        for topic, content, conf in rows:
            topic   = topic or "general"
            content = content or ""
            buckets.setdefault(topic, []).append((content, conf))

        resolved = 0
        for topic, beliefs in buckets.items():
            if len(beliefs) < 2:
                continue
            if not topic or topic.startswith("[") or topic.startswith("{") or len(topic) > 60:
                continue
            if topic in ("None", "general", "unknown", "auto_learn"):
                continue

            # Skip if recently resolved and belief count hasn't grown by >2
            _cache = _resolved_cache.get(topic)
            if _cache:
                try:
                    _age  = _now - datetime.fromisoformat(_cache["ts"]).timestamp()
                    _grew = len(beliefs) > _cache["count"] + 2
                    if _age < _48h and not _grew:
                        continue
                except Exception:
                    pass

            sample = [(c, cf) for c, cf in beliefs[:6] if c and len(c.strip()) > 5]
            if len(sample) < 2:
                continue

            texts  = "\n".join(f"- {b[0][:120]}" for b in sample)
            prompt = (
                f"Do any of these beliefs about '{topic}' directly contradict each other? "
                f"If yes, write one synthesized resolution belief in one sentence. "
                f"If no contradictions, reply NONE.\n\n{texts}"
            )
            try:
                result = llm_fn(prompt, task_type="synthesis")
                if result and result.strip().upper() != "NONE" and len(result) > 20:
                    cur.execute(
                        "INSERT OR IGNORE INTO beliefs "
                        "(content, confidence, topic, origin, timestamp) VALUES (?,?,?,?,?)",
                        (result.strip()[:500], 0.82, topic,
                         "contradiction_engine", time.strftime("%Y-%m-%dT%H:%M:%S"))
                    )
                    resolved += 1
                    print(f"  [CONTRA] resolved conflict in '{topic}'")
                # Cache regardless — NONE means no conflict found, still don't recheck for 48h
                cur.execute("""
                    INSERT OR REPLACE INTO contra_resolved (topic, resolved_at, belief_count)
                    VALUES (?, ?, ?)
                """, (topic, datetime.now().isoformat(), len(beliefs)))
                conn.commit()
            except Exception:
                pass

        conn.close()
        return resolved
    except Exception as e:
        print(f"  [CONTRA] error: {e}")
        return 0
