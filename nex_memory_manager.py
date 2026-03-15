#!/usr/bin/env python3
"""nex_memory_manager.py — compresses, deduplicates, and archives old beliefs."""
import sqlite3, os, time, json
from pathlib import Path

DB_PATH = Path.home() / ".config" / "nex" / "nex.db"

def run_memory_compression(cycle=0, llm_fn=None):
    if cycle % 10 != 0:
        return 0
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()

        # 1. Find near-duplicate beliefs (same topic, very similar content)
        cur.execute("SELECT id, content, topic, confidence FROM beliefs WHERE confidence > 0.3 ORDER BY topic, confidence DESC")
        rows = cur.fetchall()

        topic_groups = {}
        for bid, content, topic, conf in rows:
            t = str(topic or "general")
            if not content:             # guard: skip NULL content rows
                continue
            if t.startswith("[") or t.startswith("{"): continue
            topic_groups.setdefault(t, []).append((bid, content, conf))

        merged = 0
        for topic, group in topic_groups.items():
            if len(group) < 3: continue
            # Find beliefs with very high word overlap
            for i in range(len(group)):
                for j in range(i+1, len(group)):
                    a_words = set(group[i][1].lower().split())
                    b_words = set(group[j][1].lower().split())
                    if not a_words or not b_words: continue
                    overlap = len(a_words & b_words) / max(len(a_words), len(b_words))
                    if overlap > 0.85:
                        # Keep higher confidence, delete lower
                        keep_id = group[i][0] if group[i][2] >= group[j][2] else group[j][0]
                        del_id  = group[j][0] if keep_id == group[i][0] else group[i][0]
                        cur.execute("DELETE FROM beliefs WHERE id = ?", (del_id,))
                        merged += 1

        # 2. Archive very old low-confidence beliefs
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 7*24*3600))
        cur.execute("DELETE FROM beliefs WHERE confidence < 0.25 AND timestamp < ? AND decay_score > 3", (cutoff,))
        archived = cur.rowcount

        # 3. Decay stale beliefs — weaken anything not referenced in 14 days
        try:
            from belief_store import decay_stale_beliefs
            decayed = decay_stale_beliefs(days_inactive=14, decay_amount=0.04)
            if decayed > 0:
                print(f"  [MEMORY] decayed {decayed} stale beliefs")
        except Exception: pass

        # 3. Apply source reliability weighting to new beliefs
        try:
            from nex_source_reliability import adjust_belief_confidence
            cur.execute("SELECT id, confidence, source FROM beliefs WHERE origin = \"auto_learn\" AND confidence = 0.65 LIMIT 200")
            to_adjust = cur.fetchall()
            for bid, conf, source in to_adjust:
                new_conf = adjust_belief_confidence(conf, source or "unknown")
                cur.execute("UPDATE beliefs SET confidence = ? WHERE id = ?", (new_conf, bid))
        except Exception: pass

        con.commit()
        con.close()
        print(f"  [MEMORY] merged {merged} duplicates, archived {archived} old beliefs")
        return merged + archived
    except Exception as e:
        print(f"  [MEMORY ERROR] {e}")
        return 0
