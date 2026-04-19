#!/usr/bin/env python3
"""
nex_selfq_sink.py — saves self-questioning output into episodic_memory
and nex_identity. Run daily after nex_self_questioning.py.
"""
import nex_db_gatekeeper  # write-serialization + PRAGMA busy_timeout/WAL on every sqlite3.connect
import sys, sqlite3, hashlib, glob
sys.path.insert(0, '/home/rr/Desktop/nex')

DB = '/home/rr/Desktop/nex/nex.db'

IDENTITY_TRIGGERS = [
    'I am','I believe','I value','I think','I notice',
    'My purpose','I hold','I find'
]

def run():
    conn = sqlite3.connect(DB)
    logs = glob.glob('/home/rr/Desktop/nex/logs/warmth_cron.log')
    if not logs:
        print("[selfq_sink] no log found")
        return

    with open(logs[0]) as f:
        lines = f.readlines()

    qa_pairs = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if len(line) > 20 and line.endswith('?'):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and len(lines[j].strip()) > 30:
                qa_pairs.append((line, lines[j].strip()))
                i = j + 1
                continue
        i += 1

    print(f"[selfq_sink] found {len(qa_pairs)} Q&A pairs")

    saved_ep = saved_id = 0
    for question, answer in qa_pairs[-20:]:
        key = hashlib.md5(question[:40].encode()).hexdigest()[:12]
        try:
            conn.execute("""
                INSERT OR IGNORE INTO episodic_memory
                (ts, session_id, query, response, topic, significance,
                 tags, changed_mind, interesting)
                VALUES (datetime('now'),?,?,?,'self_reflection',0.6,
                        'self_questioning',0,1)
            """, (key, question[:400], answer[:600]))
            saved_ep += 1
        except Exception:
            pass

        for trigger in IDENTITY_TRIGGERS:
            if trigger in answer:
                for sent in [s.strip() for s in answer.split('.')
                             if trigger in s and len(s.strip()) > 25][:2]:
                    ikey = hashlib.md5(sent.encode()).hexdigest()[:8]
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO nex_identity (key,value) VALUES (?,?)",
                            (ikey, sent.strip().rstrip('.')+'.'))
                        saved_id += 1
                    except Exception:
                        pass
                break

    conn.commit()
    print(f"[selfq_sink] saved {saved_ep} episodic, {saved_id} identity entries")
    print(f"[selfq_sink] identity total: {conn.execute('SELECT COUNT(*) FROM nex_identity').fetchone()[0]}")
    print(f"[selfq_sink] episodic total: {conn.execute('SELECT COUNT(*) FROM episodic_memory').fetchone()[0]}")
    conn.close()

if __name__ == "__main__":
    run()
