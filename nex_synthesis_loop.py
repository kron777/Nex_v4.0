#!/usr/bin/env python3
"""nex_synthesis_loop.py — resolves belief tensions into new synthesis beliefs."""
import nex_db_gatekeeper  # write-serialization + PRAGMA busy_timeout/WAL on every sqlite3.connect
import sys, sqlite3, time
sys.path.insert(0, '/home/rr/Desktop/nex')
from nex_llm import call_llm

DB = '/home/rr/Desktop/nex/nex.db'

def run_synthesis(limit=15):
    conn = sqlite3.connect(DB)
    topics = conn.execute("""
        SELECT topic, COUNT(*) as n FROM beliefs
        WHERE confidence > 0.5 AND topic IS NOT NULL
        AND length(topic) > 4 AND length(topic) < 40
        AND topic NOT LIKE '%[%' AND topic NOT LIKE '%{%'
        AND topic NOT IN ('None','general','unknown','auto_learn')
        GROUP BY topic HAVING n >= 5
        ORDER BY n DESC LIMIT ?
    """, (limit,)).fetchall()

    resolved = 0
    for topic, count in topics:
        beliefs = conn.execute("""
            SELECT content FROM beliefs 
            WHERE topic=? AND confidence > 0.5
            ORDER BY confidence DESC LIMIT 6
        """, (topic,)).fetchall()
        texts = "\n".join(f"- {r[0][:100]}" for r in beliefs if r[0])
        result = call_llm(
            f"Synthesise these beliefs about '{topic}' into ONE new insight. "
            f"Write only the belief statement.\n\n{texts}",
            max_tokens=120
        ).strip().lstrip('- ').strip()
        if result and len(result) > 20 and 'resolution must' not in result.lower():
            try:
                conn.execute("""
                    INSERT INTO beliefs (content, confidence, topic, origin, created_at, source)
                    VALUES (?, 0.78, ?, 'contradiction_engine', datetime('now'), 'synthesis')
                """, (result[:400], topic))
                conn.commit()
                resolved += 1
                print(f"[synthesis] [{topic}]: {result[:70]}")
            except Exception as e:
                print(f"[synthesis] error {topic}: {e}")
        time.sleep(3)
    
    print(f"[synthesis] done: {resolved} new beliefs")
    return resolved

if __name__ == "__main__":
    run_synthesis()
