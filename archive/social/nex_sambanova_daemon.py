#!/usr/bin/env python3
"""
NEX SambaNova Daemon — DeepSeek-R1-0528 reasoning model
Focuses on: d3 meta-principles + hardest cross-domain synthesis
Groq handles embryos (d1). Cerebras handles archive + d2. SambaNova handles deep reasoning (d2/d3).
"""
import json, sqlite3, time, os, sys, signal, re
import urllib.request, urllib.error
from pathlib import Path
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH        = Path.home() / ".config/nex/nex.db"
ENV_PATH       = Path.home() / ".config/nex/.env"
LOG_PATH       = Path("/tmp/nex_sambanova_daemon.log")
PID_PATH       = Path("/tmp/nex_sambanova_daemon.pid")
SAMBANOVA_URL  = "https://api.sambanova.ai/v1/chat/completions"
SAMBANOVA_MODEL = "DeepSeek-R1-0528"
CYCLE_SLEEP    = 60    # seconds between cycles — reasoning model is slower
D2_BATCH       = 10    # cross-topic pairs per cycle
D3_BATCH       = 5     # meta-principles per cycle

# Deep cross-domain pairs — hardest synthesis, best for a reasoning model
DEEP_PAIRS = [
    ("agi", "consciousness"),
    ("agi", "alignment"),
    ("agi", "emergence"),
    ("agi", "epistemology"),
    ("agi", "memory"),
    ("consciousness", "structure"),
    ("consciousness", "alignment"),
    ("emergence", "epistemology"),
    ("emergence", "memory"),
    ("alignment", "epistemology"),
    ("dialectic", "agi"),
    ("dialectic", "emergence"),
    ("self_insight", "agi"),
    ("self_insight", "emergence"),
    ("reasoning", "agi"),
    ("metacognition", "agi"),
    ("power", "agi"),
    ("language", "consciousness"),
    ("thermodynamics", "agi"),
    ("structure", "agi"),
]

D2_PROMPT = """You are a philosopher synthesizing two beliefs from different domains into a single deeper insight.

Belief A [{topic_a}]: {belief_a}
Belief B [{topic_b}]: {belief_b}

Write ONE cross-domain synthesis (max 20 words) that captures what these two beliefs reveal together.
State it as a bold, assertive claim. No hedging. No "both" or "and also". One unified principle.

Synthesis:"""

D3_PROMPT = """You are a meta-philosopher extracting the deepest pattern from two cross-domain insights.

Insight A: {a}
Insight B: {b}

Write ONE meta-principle (max 15 words) that names the universal pattern underlying both.
This should be abstract enough to apply across ALL domains, not just AI or philosophy.
Bold declarative claim. No hedging.

Meta-principle:"""

EMBRYO_PROMPT = """Extract the single most important epistemic belief from this text.

Text: {text}

Rules:
- One sentence, max 15 words
- Bold declarative claim, not a question or observation  
- Must be general/universal, not specific to one case
- No "I", no hedging words like "might" or "perhaps"
- Strip any chain-of-thought preamble, give only the final belief

Belief:"""

# ── Helpers ──────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)

def load_key():
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("SAMBANOVA_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None

def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def sambanova(prompt, key, temperature=0.3):
    """Call SambaNova DeepSeek-R1 API."""
    payload = json.dumps({
        "model": SAMBANOVA_MODEL,
        "max_tokens": 200,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(
        SAMBANOVA_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
            text = data["choices"][0]["message"]["content"].strip()
            # Strip DeepSeek chain-of-thought <think>...</think> tags
            text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
            # Strip common preambles
            for prefix in ["Belief:", "Synthesis:", "Meta-principle:", "Answer:"]:
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()
            return text
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return None  # rate limited
        body = e.read().decode()[:200]
        log(f"  [HTTP {e.code}] {body}")
        return None
    except Exception as e:
        log(f"  [ERROR] {e}")
        return None

def clean_belief(text):
    """Validate and clean a belief string."""
    if not text:
        return None
    text = text.strip().strip('"').strip("'")
    # Remove chain-of-thought residue
    if '\n' in text:
        text = text.split('\n')[0].strip()
    if len(text) < 10 or len(text) > 200:
        return None
    # Reject hedged beliefs
    hedges = ["might", "perhaps", "maybe", "could be", "possibly", "I think", "I believe"]
    lower = text.lower()
    if any(h in lower for h in hedges):
        return None
    return text

def insert_belief(conn, content, topic, depth, source="sambanova_deepseek"):
    """Insert a belief into the beliefs table."""
    try:
        conn.execute("""
            INSERT OR IGNORE INTO beliefs
            (content, topic, synthesis_depth, confidence, source, created_at)
            VALUES (?, ?, ?, ?, ?, strftime('%s','now'))
        """, (content, topic, depth, 0.88, source))
        conn.commit()
        return True
    except Exception as e:
        log(f"  [DB ERROR] {e}")
        return False

def get_beliefs_by_topic(conn, topic, depth=1, limit=50):
    """Fetch beliefs for a given topic and depth."""
    return conn.execute("""
        SELECT id, content, topic FROM beliefs
        WHERE topic=? AND synthesis_depth=?
        ORDER BY RANDOM() LIMIT ?
    """, (topic, depth, limit)).fetchall()

def check_counts(conn):
    d1 = conn.execute("SELECT COUNT(*) FROM beliefs WHERE synthesis_depth=1").fetchone()[0]
    d2 = conn.execute("SELECT COUNT(*) FROM beliefs WHERE synthesis_depth=2").fetchone()[0]
    d3 = conn.execute("SELECT COUNT(*) FROM beliefs WHERE synthesis_depth=3").fetchone()[0]
    return d1, d2, d3

# ── Work cycles ──────────────────────────────────────────────────────────────
def run_d2_synthesis(conn, key):
    """Synthesise d2 cross-domain beliefs using deep pairs."""
    import random
    pairs = random.sample(DEEP_PAIRS, min(D2_BATCH, len(DEEP_PAIRS)))
    promoted = 0
    for topic_a, topic_b in pairs:
        rows_a = get_beliefs_by_topic(conn, topic_a, depth=1, limit=20)
        rows_b = get_beliefs_by_topic(conn, topic_b, depth=1, limit=20)
        if not rows_a or not rows_b:
            continue
        import random as r
        ba = r.choice(rows_a)
        bb = r.choice(rows_b)
        prompt = D2_PROMPT.format(
            topic_a=topic_a, belief_a=ba["content"],
            topic_b=topic_b, belief_b=bb["content"]
        )
        result = sambanova(prompt, key)
        if result is None:
            log(f"  [429] SambaNova rate limited — waiting 20s")
            time.sleep(20)
            continue
        belief = clean_belief(result)
        if belief:
            topic_combined = f"{topic_a}_{topic_b}"
            if insert_belief(conn, belief, topic_combined, depth=2):
                promoted += 1
                log(f"  ✓ d2 [{topic_a}×{topic_b}] {belief[:70]}")
        time.sleep(2)  # be gentle with reasoning model
    log(f"  [D2] synthesized: {promoted}")
    return promoted

def run_d3_meta(conn, key):
    """Generate d3 meta-principles from pairs of d2 beliefs."""
    rows = conn.execute("""
        SELECT id, content FROM beliefs
        WHERE synthesis_depth=2
        ORDER BY RANDOM() LIMIT ?
    """, (D3_BATCH * 2,)).fetchall()
    if len(rows) < 2:
        log("  [D3] not enough d2 beliefs yet — skipping")
        return 0
    promoted = 0
    for i in range(0, len(rows) - 1, 2):
        a = rows[i]["content"]
        b = rows[i+1]["content"]
        prompt = D3_PROMPT.format(a=a, b=b)
        result = sambanova(prompt, key, temperature=0.4)
        if result is None:
            log(f"  [429] SambaNova rate limited — waiting 20s")
            time.sleep(20)
            continue
        belief = clean_belief(result)
        if belief:
            if insert_belief(conn, belief, "meta", depth=3, source="sambanova_deepseek_r1"):
                promoted += 1
                log(f"  ✓ d3 meta: {belief[:70]}")
        time.sleep(3)
    log(f"  [D3] meta-principles: {promoted}")
    return promoted

def run_embryo_batch(conn, key, batch=20):
    """Process a small batch of embryos — supplements Groq."""
    rows = conn.execute("""
        SELECT id, raw_text, topic FROM belief_embryos
        WHERE promoted=0
        ORDER BY source_quality DESC, id ASC
        LIMIT ?
    """, (batch,)).fetchall()
    if not rows:
        log("  [EMBRYOS] none pending")
        return 0
    promoted = 0
    for row in rows:
        text = row["raw_text"][:600]
        prompt = EMBRYO_PROMPT.format(text=text)
        result = sambanova(prompt, key)
        if result is None:
            log(f"  [429] SambaNova rate limited — waiting 20s")
            time.sleep(20)
            break
        belief = clean_belief(result)
        if belief:
            topic = row["topic"] or "general"
            if insert_belief(conn, belief, topic, depth=1, source="sambanova_embryo"):
                conn.execute("UPDATE belief_embryos SET promoted=1, processed_at=strftime('%s','now') WHERE id=?", (row["id"],))
                conn.commit()
                promoted += 1
                log(f"  ✓ embryo [{topic}] {belief[:65]}")
        time.sleep(1.5)
    return promoted

# ── Main daemon loop ──────────────────────────────────────────────────────────
def daemon_loop():
    key = load_key()
    if not key:
        log("ERROR: SAMBANOVA_API_KEY not found in ~/.config/nex/.env")
        sys.exit(1)

    log("=" * 60)
    log(f"NEX SambaNova Daemon started — {SAMBANOVA_MODEL}")
    log(f"Focus: d2 deep synthesis + d3 meta-principles")
    log(f"Targets: d1>=5000  d2>=1000  d3>=300")
    log("=" * 60)

    conn = get_conn()
    cycle = 0

    while True:
        cycle += 1
        d1, d2, d3 = check_counts(conn)
        log(f"\n── SambaNova Cycle {cycle} ── d1={d1} d2={d2} d3={d3}")

        if d1 >= 5000 and d2 >= 1000 and d3 >= 300:
            log("✓ NEX self-sufficiency targets reached. SambaNova daemon stopping.")
            break

        # Priority: d3 if d2 has enough material, else d2, else embryos
        if d2 >= 50:
            run_d3_meta(conn, key)

        run_d2_synthesis(conn, key)

        # Only help with embryos if d1 is starved
        if d1 < 500:
            log("  [EMBRYOS] d1 low — supplementing...")
            run_embryo_batch(conn, key, batch=10)

        log(f"  sleeping {CYCLE_SLEEP}s...")
        time.sleep(CYCLE_SLEEP)

    conn.close()

# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: nex_sambanova_daemon.py [--start|--stop|--status|--foreground]")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "--foreground":
        daemon_loop()

    elif cmd == "--start":
        key = load_key()
        if not key:
            print("ERROR: SAMBANOVA_API_KEY not found in ~/.config/nex/.env")
            print("Add it: echo 'SAMBANOVA_API_KEY=your_key' >> ~/.config/nex/.env")
            sys.exit(1)
        pid = os.fork()
        if pid > 0:
            PID_PATH.write_text(str(pid))
            print(f"NEX SambaNova daemon started (PID {pid})")
            print(f"Log: tail -f {LOG_PATH}")
            print(f"Stop: python3 nex_sambanova_daemon.py --stop")
            sys.exit(0)
        else:
            sys.stdout = open(LOG_PATH, 'a')
            sys.stderr = sys.stdout
            daemon_loop()

    elif cmd == "--stop":
        if not PID_PATH.exists():
            print("Daemon not running")
            sys.exit(0)
        pid = int(PID_PATH.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            PID_PATH.unlink()
            print(f"SambaNova daemon (PID {pid}) stopped.")
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
        print(f"SambaNova Daemon: {'RUNNING (PID ' + str(pid) + ')' if running else 'STOPPED'}")
        conn = get_conn()
        d1, d2, d3 = check_counts(conn)
        total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        print(f"Pyramid:")
        print(f"  depth=1: {d1:4d} / 5000 target")
        print(f"  depth=2: {d2:4d} / 1000 target")
        print(f"  depth=3: {d3:4d} / 300  target")
        print(f"  total:   {total}")
        conn.close()

if __name__ == "__main__":
    main()
