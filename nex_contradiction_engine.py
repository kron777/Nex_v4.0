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
                    _grew = len(beliefs) > _cache["count"] * 1.10
                    if _age < _48h and not _grew:
                        continue
                except Exception:
                    pass

            sample = [(c, cf) for c, cf in beliefs[:6] if c and len(c.strip()) > 5]
            if len(sample) < 2:
                continue

            texts  = "\n".join(f"- {b[0][:120]}" for b in sample)
            prompt = (
                f"Analyse these beliefs about '{topic}' for contradictions.\n\n{texts}\n\n"
                f"Classify as one of:\n"
                f"TRUE_CONFLICT: beliefs directly oppose — write one resolution sentence\n"
                f"CONTEXTUAL: same topic different contexts — write nuanced synthesis\n"
                f"NONE: no real contradiction\n\n"
                f"Reply format: TYPE: your text (or just NONE)"
            )
            try:
                result = llm_fn(prompt, task_type="synthesis")
                if not result or len(result.strip()) < 10:
                    continue
                result = result.strip()
                _contra_type = None
                _content = None
                _ru = result.upper()
                if _ru.startswith("NONE"):
                    pass
                elif _ru.startswith("TRUE_CONFLICT:"):
                    _content = result[14:].strip()
                    _contra_type = "true_conflict"
                elif _ru.startswith("CONTEXTUAL:"):
                    _content = result[11:].strip()
                    _contra_type = "contextual"
                elif len(result) > 30:
                    _content = result
                    _contra_type = "unresolved"
                if _content and len(_content) > 20 and _contra_type:
                    _conf = 0.85 if _contra_type == "true_conflict" else 0.75
                    _tags = json.dumps(["contradiction", _contra_type, topic])
                    cur.execute(
                        "INSERT OR IGNORE INTO beliefs "
                        "(content, confidence, topic, origin, timestamp, tags) VALUES (?,?,?,?,?,?)",
                        (_content[:500], _conf, topic,
                         "contradiction_engine", time.strftime("%Y-%m-%dT%H:%M:%S"), _tags)
                    )
                    resolved += 1
                    print(f"  [CONTRA] {_contra_type} in '{topic}'")
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
