#!/usr/bin/env python3
"""
nex_session_compressor.py — compresses session_history pairs into
episodic_memory with significance scoring. Run daily.
"""
import sys, sqlite3, time, hashlib
sys.path.insert(0, '/home/rr/Desktop/nex')

DB = '/home/rr/Desktop/nex/nex.db'

SIGNIFICANCE_KEYWORDS = [
    'consciousness','identity','belief','think','feel','remember',
    'agi','intelligence','understand','realise','disagree','wrong',
    'changed','actually','honest','position','curious','why',
    'purpose','exist','know','uncertain','contradict','emerge'
]

def score_significance(query, response):
    text = (query + ' ' + response).lower()
    hits = sum(1 for kw in SIGNIFICANCE_KEYWORDS if kw in text)
    length_bonus = 0.1 if len(response) > 200 else 0
    question_bonus = 0.15 if '?' in query else 0
    score = min(0.3 + (hits * 0.05) + length_bonus + question_bonus, 1.0)
    return round(score, 3)

def run_compression():
    conn = sqlite3.connect(DB)

    # Get existing episodic session IDs to avoid duplicates
    existing = set(
        r[0] for r in conn.execute(
            "SELECT session_id FROM episodic_memory WHERE session_id IS NOT NULL"
        ).fetchall()
    )

    # Pull session_history as Q/A pairs
    rows = conn.execute("""
        SELECT h1.session_id, h1.content, h2.content, h1.ts
        FROM session_history h1
        JOIN session_history h2
          ON h1.session_id = h2.session_id
         AND h2.id = h1.id + 1
        WHERE h1.role = 'user'
          AND h2.role = 'assistant'
          AND length(h1.content) > 20
          AND length(h2.content) > 30
        ORDER BY h1.ts DESC
    """).fetchall()

    compressed = 0
    for session_id, query, response, ts in rows:
        # Skip already compressed sessions
        key = hashlib.md5(f"{session_id}{query[:40]}".encode()).hexdigest()[:12]
        if key in existing:
            continue

        sig = score_significance(query, response)
        if sig < 0.35:
            continue  # Skip low significance pairs

        # Infer topic from keywords
        topic = "general"
        for kw in ['consciousness','identity','alignment','epistemology',
                   'emergence','philosophy','free_will','ethics']:
            if kw in (query + response).lower():
                topic = kw
                break

        interesting = 1 if sig > 0.6 else 0

        try:
            conn.execute("""
                INSERT INTO episodic_memory
                (ts, session_id, query, response, topic, significance,
                 tags, changed_mind, interesting)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (ts, key, query[:500], response[:800],
                  topic, sig, topic, interesting))
            existing.add(key)
            compressed += 1
        except Exception as e:
            pass

    conn.commit()
    before = conn.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0]
    print(f"[compressor] compressed {compressed} new pairs into episodic_memory")
    print(f"[compressor] episodic_memory total: {before}")
    conn.close()

if __name__ == "__main__":
    run_compression()
