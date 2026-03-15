#!/usr/bin/env python3
"""nex_belief_graph.py — populates belief_links with semantic relations."""
import sqlite3, os, re, time
from pathlib import Path

DB_PATH = Path.home() / ".config" / "nex" / "nex.db"

def _extract_keywords(text):
    words = re.findall(r'\b[a-z]{4,}\b', text.lower())
    stop = {'that','this','with','from','have','been','they','their',
            'will','would','could','should','about','into','which','when',
            'also','more','some','than','then','what','there','were','each'}
    return set(w for w in words if w not in stop)

def run_belief_graph(cycle=0, llm_fn=None):
    if cycle % 6 != 0:
        return 0
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT id, content, topic, author, confidence FROM beliefs WHERE confidence > 0.4 ORDER BY confidence DESC LIMIT 300")
        beliefs = cur.fetchall()
        if len(beliefs) < 10:
            con.close(); return 0
        topic_groups = {}
        for bid, content, topic, author, conf in beliefs:
            t = str(topic or "general")
            topic_groups.setdefault(t, []).append((bid, content, author, conf))
        linked = 0
        for topic, group in topic_groups.items():
            if len(group) < 2: continue
            for i in range(len(group)):
                for j in range(i+1, min(i+4, len(group))):
                    aid, acontent, aauthor, aconf = group[i]
                    bid2, bcontent, bauthor, bconf = group[j]
                    kw_a = _extract_keywords(acontent)
                    kw_b = _extract_keywords(bcontent)
                    overlap = len(kw_a & kw_b)
                    if overlap > 5: link_type = "corroborates"
                    elif aauthor == bauthor: link_type = "same_author"
                    else: link_type = "same_topic"
                    try:
                        cur.execute("INSERT OR IGNORE INTO belief_links (parent_id, child_id, link_type) VALUES (?,?,?)", (aid, bid2, link_type))
                        linked += 1
                    except Exception: pass
        if llm_fn and cycle % 12 == 0:
            for topic, group in list(topic_groups.items())[:5]:
                if len(group) < 3: continue
                sample = group[:6]
                texts = "\n".join(f"[{b[0]}] {b[1][:100]}" for b in sample)
                prompt = f"Beliefs on '{topic}':\n{texts}\n\nWhich pair IDs contradict each other? Reply: ID1,ID2 or NONE"
                try:
                    result = llm_fn(prompt, task_type="synthesis")
                    if result and result.strip().upper() != "NONE":
                        parts = re.findall(r'\d+', result)
                        if len(parts) >= 2:
                            cur.execute("INSERT OR IGNORE INTO belief_links (parent_id, child_id, link_type) VALUES (?,?,?)", (int(parts[0]), int(parts[1]), "contradicts"))
                            linked += 1
                except Exception: pass
        con.commit(); con.close()
        print(f"  [BELIEF GRAPH] linked {linked} belief pairs")
        return linked
    except Exception as e:
        print(f"  [BELIEF GRAPH ERROR] {e}"); return 0

def get_related_beliefs(belief_id, limit=5):
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT b.content, b.confidence, bl.link_type FROM belief_links bl JOIN beliefs b ON b.id = bl.child_id WHERE bl.parent_id = ? ORDER BY b.confidence DESC LIMIT ?", (belief_id, limit))
        results = cur.fetchall(); con.close(); return results
    except Exception: return []

if __name__ == "__main__":
    n = run_belief_graph(cycle=0)
    print(f"Done — {n} links created")
