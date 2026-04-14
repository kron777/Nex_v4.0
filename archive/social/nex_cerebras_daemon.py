#!/usr/bin/env python3
"""
NEX Cerebras Daemon — runs in parallel with nex_groq_daemon.py
Focuses on: archive mining + depth=2 cross-topic synthesis
Groq handles embryos. Cerebras handles archive + d2.
"""

import json, sqlite3, time, os, sys, signal, re
import urllib.request, urllib.error
from pathlib import Path
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH   = Path.home() / ".config/nex/nex.db"
ENV_PATH  = Path.home() / ".config/nex/.env"
LOG_PATH  = Path("/tmp/nex_cerebras_daemon.log")
PID_PATH  = Path("/tmp/nex_cerebras_daemon.pid")

CEREBRAS_URL   = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_MODEL = "qwen-3-235b-a22b-instruct-2507"

ARCHIVE_BATCH  = 30   # responses per cycle
AFFINITY_BATCH = 20   # cross-topic pairs per cycle
CYCLE_SLEEP    = 45   # seconds between cycles

# All 23 topics for d2 cross-topic synthesis
ATTRACTOR_PAIRS = [
    ("self_insight", "consciousness"),
    ("self_insight", "memory"),
    ("self_insight", "dialectic"),
    ("self_insight", "emergence"),
    ("self_insight", "alignment"),
    ("self_insight", "reasoning"),
    ("self_insight", "epistemology"),
    ("self_insight", "metacognition"),
    ("self_insight", "language"),
    ("dialectic", "consciousness"),
    ("dialectic", "reasoning"),
    ("dialectic", "alignment"),
    ("dialectic", "power"),
    ("dialectic", "epistemology"),
    ("consciousness", "emergence"),
    ("consciousness", "memory"),
    ("consciousness", "reasoning"),
    ("consciousness", "language"),
    ("memory", "language"),
    ("memory", "reasoning"),
    ("emergence", "alignment"),
    ("emergence", "structure"),
    ("alignment", "power"),
    ("alignment", "multi_agent"),
    ("reasoning", "epistemology"),
    ("power", "multi_agent"),
    ("metacognition", "reasoning"),
    ("structure", "language"),
]

# D3 meta synthesis — combine two depth=2 beliefs into a meta-principle
META_PROMPT = """You are a philosopher synthesizing two cross-domain insights into a single meta-principle.

Belief A: {a}
Belief B: {b}

Write ONE meta-principle (max 15 words) that captures the deeper pattern connecting both.
State it as a bold, assertive claim. No hedging. Just the principle."""

ARCHIVE_PROMPT = """Extract the single most important epistemic belief from this AI response.

Response: {text}

Rules:
- One sentence, max 15 words
- Bold declarative claim, not a question or observation
- Must be general/universal, not specific to this conversation
- No "I", no hedging words like "might" or "perhaps"

Belief:"""

AFFINITY_PROMPT = """Synthesize a new insight by combining these two beliefs from different domains.

Domain A ({topic_a}): {belief_a}
Domain B ({topic_b}): {belief_b}

Write ONE cross-domain insight (max 15 words) that neither belief alone expresses.
Bold declarative claim. No hedging."""

# ── Helpers ─────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

def load_key():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("CEREBRAS_API_KEY"):
            return line.split("=", 1)[1].strip()
    return None

def cerebras(prompt: str, max_tokens: int = 80, temp: float = 0.5) -> str:
    key = load_key()
    if not key:
        raise RuntimeError("CEREBRAS_API_KEY not found in ~/.config/nex/.env")
    payload = json.dumps({
        "model": CEREBRAS_MODEL,
        "max_tokens": max_tokens,
        "temperature": temp,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        CEREBRAS_URL, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            log("  [429] Cerebras rate limited — waiting 15s")
            time.sleep(15)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            return data["choices"][0]["message"]["content"].strip()
        raise

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def clean(text: str) -> str:
    text = text.strip().strip('"').strip("'")
    text = re.sub(r'^(Belief:|Insight:|Meta-principle:)\s*', '', text, flags=re.I)
    return text[:200]

# ── Workers ──────────────────────────────────────────────────────────────────
CONV_PATH = Path.home() / "Desktop/nex/logs/conversations.jsonl"
ARCHIVE_POS_FILE = Path("/tmp/nex_cerebras_archive_pos.txt")

def run_archive(conn):
    """Mine conversations.jsonl for depth=1 beliefs via Cerebras."""
    if not CONV_PATH.exists():
        log("  [ARCHIVE] conversations.jsonl not found")
        return 0

    pos = int(ARCHIVE_POS_FILE.read_text()) if ARCHIVE_POS_FILE.exists() else 0
    lines = CONV_PATH.read_text(errors="ignore").splitlines()
    total = len(lines)

    if pos >= total:
        log(f"  [ARCHIVE] fully mined ({total} lines)")
        return 0

    import json as _json
    batch = []
    i = pos
    while i < total and len(batch) < ARCHIVE_BATCH:
        line = lines[i].strip()
        if line:
            try:
                obj = _json.loads(line)
                # Handle both {messages:[]} and {role:, content:} formats
                msgs = obj.get("messages", [])
                for m in msgs:
                    if m.get("role") == "assistant" and len(m.get("content","")) > 120:
                        batch.append((i, m["content"]))
                if not msgs:
                    content = obj.get("response") or obj.get("content","")
                    if len(content) > 120:
                        batch.append((i, content))
            except Exception:
                pass
        i += 1

    ARCHIVE_POS_FILE.write_text(str(i))

    if not batch:
        log(f"  [ARCHIVE] no quality responses in lines {pos}-{i}")
        return 0

    log(f"  [ARCHIVE] mining {len(batch)} responses ({pos}/{total} lines, Cerebras)...")
    promoted = 0
    for idx, text in batch:
        try:
            result = cerebras(ARCHIVE_PROMPT.format(text=text[:500]))
            belief = clean(result)
            if len(belief) < 8:
                continue
            conn.execute("""
                INSERT OR IGNORE INTO beliefs
                (content, confidence, source, lineage, synthesis_depth, locked, topic)
                VALUES (?, 0.78, 'cerebras_archive', ?, 1, 1, 'conversation')
            """, (belief, str(idx)))
            conn.commit()
            promoted += 1
            log(f"  ✓ archive {belief[:70]}")
            time.sleep(0.3)
        except Exception as e:
            log(f"  [ERR archive {idx}] {e}")
            time.sleep(2)

    log(f"  [ARCHIVE] done — {promoted}/{len(batch)} extracted")
    return promoted

    log(f"  [ARCHIVE] mining {len(rows)} responses (Cerebras)...")
    promoted = 0
    for row in rows:
        try:
            result = cerebras(ARCHIVE_PROMPT.format(text=row['content'][:500]))
            belief = clean(result)
            if len(belief) < 8:
                continue
            conn.execute("""
                INSERT OR IGNORE INTO beliefs
                (content, confidence, source, lineage, synthesis_depth, locked, topic)
                VALUES (?, 0.78, 'cerebras_archive', ?, 1, 1, 'conversation')
            """, (belief, str(row['id'])))
            conn.commit()
            promoted += 1
            log(f"  ✓ archive [{row['id']}] {belief[:70]}")
            time.sleep(0.3)
        except Exception as e:
            log(f"  [ERR archive {row['id']}] {e}")
            time.sleep(2)

    log(f"  [ARCHIVE] done — {promoted}/{len(rows)} extracted")
    return promoted

def run_affinity(conn):
    """Cross-topic synthesis: pair depth=1 beliefs across topic pairs → depth=2."""
    import random
    pairs = ATTRACTOR_PAIRS.copy()
    random.shuffle(pairs)
    pairs = pairs[:AFFINITY_BATCH]

    promoted = 0
    for topic_a, topic_b in pairs:
        row_a = conn.execute("""
            SELECT id, content FROM beliefs
            WHERE topic=? AND synthesis_depth=1 AND locked=1
            ORDER BY RANDOM() LIMIT 1
        """, (topic_a,)).fetchone()
        row_b = conn.execute("""
            SELECT id, content FROM beliefs
            WHERE topic=? AND synthesis_depth=1 AND locked=1
            ORDER BY RANDOM() LIMIT 1
        """, (topic_b,)).fetchone()

        if not row_a or not row_b:
            continue

        # Check not already synthesized this pair
        existing = conn.execute("""
            SELECT id FROM beliefs
            WHERE source='cerebras_affinity'
            AND lineage LIKE ?
            LIMIT 1
        """, (f"%{row_a['id']}%{row_b['id']}%",)).fetchone()
        if existing:
            continue

        try:
            result = cerebras(AFFINITY_PROMPT.format(
                topic_a=topic_a, belief_a=row_a['content'],
                topic_b=topic_b, belief_b=row_b['content']
            ))
            belief = clean(result)
            if len(belief) < 8:
                continue
            conn.execute("""
                INSERT OR IGNORE INTO beliefs
                (content, confidence, source, lineage, synthesis_depth, locked, topic)
                VALUES (?, 0.87, 'cerebras_affinity', ?, 2, 1, ?)
            """, (belief, f"{row_a['id']}×{row_b['id']}", f"{topic_a}×{topic_b}"))
            conn.commit()
            promoted += 1
            log(f"  ✓ d2 [{topic_a}×{topic_b}] {belief[:65]}")
            time.sleep(0.4)
        except Exception as e:
            log(f"  [ERR affinity {topic_a}×{topic_b}] {e}")
            time.sleep(2)

    log(f"  [AFFINITY] d2 synthesized: {promoted}")
    return promoted

def run_meta(conn):
    """Pair two depth=2 beliefs → depth=3 meta-principle."""
    rows = conn.execute("""
        SELECT id, content, topic FROM beliefs
        WHERE synthesis_depth=2 AND locked=1
        ORDER BY RANDOM() LIMIT 2
    """).fetchall()
    if len(rows) < 2:
        return 0

    a, b = rows[0], rows[1]
    existing = conn.execute("""
        SELECT id FROM beliefs WHERE source='cerebras_meta'
        AND lineage LIKE ? LIMIT 1
    """, (f"%{a['id']}%",)).fetchone()
    if existing:
        return 0

    try:
        result = cerebras(META_PROMPT.format(a=a['content'], b=b['content']))
        belief = clean(result)
        if len(belief) < 8:
            return 0
        conn.execute("""
            INSERT OR IGNORE INTO beliefs
            (content, confidence, source, lineage, synthesis_depth, locked, topic)
            VALUES (?, 0.93, 'cerebras_meta', ?, 3, 1, 'meta')
        """, (belief, f"{a['id']}×{b['id']}"))
        conn.commit()
        log(f"  ✓ d3 meta: {belief[:70]}")
        return 1
    except Exception as e:
        log(f"  [ERR meta] {e}")
        return 0

def check_targets(conn):
    d1 = conn.execute("SELECT COUNT(*) FROM beliefs WHERE synthesis_depth=1").fetchone()[0]
    d2 = conn.execute("SELECT COUNT(*) FROM beliefs WHERE synthesis_depth=2").fetchone()[0]
    d3 = conn.execute("SELECT COUNT(*) FROM beliefs WHERE synthesis_depth=3").fetchone()[0]
    return d1, d2, d3

# ── Daemon loop ──────────────────────────────────────────────────────────────
def daemon_loop():
    log("=" * 60)
    log("NEX Cerebras Daemon started")
    log(f"Targets: d1>=5000  d2>=1000  d3>=300")
    log("=" * 60)

    cycle = 0
    while True:
        cycle += 1
        conn = get_conn()
        d1, d2, d3 = check_targets(conn)
        log(f"\n── Cerebras Cycle {cycle} ── d1={d1} d2={d2} d3={d3}")

        if d1 >= 5000 and d2 >= 1000 and d3 >= 300:
            log("✓ NEX self-sufficiency targets reached. Cerebras daemon stopping.")
            conn.close()
            break

        run_archive(conn)
        run_affinity(conn)
        if d2 >= 20:
            run_meta(conn)

        conn.close()
        log(f"  [SLEEP] {CYCLE_SLEEP}s until next cycle")
        time.sleep(CYCLE_SLEEP)

# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: nex_cerebras_daemon.py [--start|--stop|--status]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "--start":
        # Verify key exists
        key = load_key()
        if not key:
            print("ERROR: CEREBRAS_API_KEY not found in ~/.config/nex/.env")
            print("Add it: echo 'CEREBRAS_API_KEY=your_key' >> ~/.config/nex/.env")
            sys.exit(1)

        # Fork to background
        pid = os.fork()
        if pid > 0:
            PID_PATH.write_text(str(pid))
            print(f"NEX Cerebras daemon started (PID {pid})")
            print(f"Log: tail -f {LOG_PATH}")
            print(f"Stop: python3 nex_cerebras_daemon.py --stop")
            sys.exit(0)
        else:
            # Child: redirect stdout/stderr to log
            sys.stdout = open(LOG_PATH, 'a')
            sys.stderr = sys.stdout
            daemon_loop()

    elif cmd == "--foreground":
        daemon_loop()
    elif cmd == "--stop":
        if not PID_PATH.exists():
            print("Daemon not running")
            sys.exit(0)
        pid = int(PID_PATH.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            PID_PATH.unlink()
            print(f"Cerebras daemon (PID {pid}) stopped.")
        except ProcessLookupError:
            print("Process not found — already stopped.")
            PID_PATH.unlink(missing_ok=True)

    elif cmd == "--status":
        running = False
        pid = None
        if PID_PATH.exists():
            pid = int(PID_PATH.read_text().strip())
            try:
                os.kill(pid, 0)
                running = True
            except ProcessLookupError:
                pass

        print(f"Cerebras Daemon: {'RUNNING (PID ' + str(pid) + ')' if running else 'STOPPED'}")
        conn = get_conn()
        d1, d2, d3 = check_targets(conn)
        total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        print(f"Pyramid:")
        print(f"  depth=1: {d1:4d} / 5000 target")
        print(f"  depth=2: {d2:4d} / 100  target")
        print(f"  depth=3: {d3:4d} / 30   target")
        print(f"  total:   {total}")
        conn.close()

if __name__ == "__main__":
    main()
