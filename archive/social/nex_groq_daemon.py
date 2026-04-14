#!/usr/bin/env python3
"""
NEX GROQ DAEMON — nex_groq_daemon.py
=====================================
Continuously synthesizes beliefs via Groq until manually stopped.
Runs all three pipelines in rotation, respecting rate limits.

Start:  ./venv/bin/python3 nex_groq_daemon.py --start
Stop:   ./venv/bin/python3 nex_groq_daemon.py --stop
Status: ./venv/bin/python3 nex_groq_daemon.py --status

Auto-stops when:
  - depth=1 beliefs >= TARGET_D1 (default 500)
  - depth=2 beliefs >= TARGET_D2 (default 80)
  - depth=3 beliefs >= TARGET_D3 (default 25)
  OR manually stopped via --stop

Logs to: /tmp/nex_groq_daemon.log
PID file: /tmp/nex_groq_daemon.pid
"""

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


def cerebras(prompt: str, max_tokens: int = 250, temp: float = 0.4) -> str:
    import urllib.request, json
    from pathlib import Path
    key = ""
    for line in (Path.home()/".config/nex/.env").read_text().splitlines():
        if line.startswith("CEREBRAS_API_KEY"):
            key = line.split("=",1)[1].strip()
    if not key:
        raise RuntimeError("CEREBRAS_API_KEY not found")
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
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"].strip()

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH   = Path.home() / ".config/nex/nex.db"
CONV_PATH = Path.home() / "Desktop/nex/logs/conversations.jsonl"
ENV_PATH  = Path.home() / ".config/nex/.env"
LOG_PATH  = Path("/tmp/nex_groq_daemon.log")
PID_PATH  = Path("/tmp/nex_groq_daemon.pid")

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_MODEL = "llama-3.3-70b"

# Stop targets — when NEX can stand on her own
TARGET_D1 = 5000   # depth=1 forge-synth beliefs
TARGET_D2 = 1000   # depth=2 cross-topic beliefs
TARGET_D3 = 300    # depth=3 meta-principles

# Rate limiting
CALL_DELAY     = 1.2   # seconds between Groq calls
BATCH_PAUSE    = 3.0   # seconds between batches
RATE_LIMIT_WAIT = 10   # seconds to wait on 429
CYCLE_SLEEP    = 60    # seconds between full cycles

# Batch sizes per cycle
EMBRYO_PER_CYCLE  = 50
TENSION_PER_CYCLE = 20
ARCHIVE_PER_CYCLE = 30

SPAM_PATTERNS = [
    "bridge:truth seeking", "have to do with a different domain",
    "The interesting thing about bridge", "↔", "||", "[merged:",
    "this paper", "this work", "et al", "OPEN QUESTION",
    "What does this mean", "bridge:cognitive", "bridge:alignment",
    "None of these resolve in isolation", "The insight is",
    "My analysis suggests", "My belief that",
]

QUALITY_MARKERS = [
    "because", "therefore", "however", "suggests", "reveals",
    "implies", "demonstrates", "structure", "emerges", "pattern",
    "rather than", "not merely", "fundamentally", "ultimately",
]

# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

# ── Key + Groq ────────────────────────────────────────────────────────────────

def load_key() -> str:
    try:
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("GROQ_API_KEY"):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY", "")


def groq_call(prompt: str, max_tokens: int = 200, temp: float = 0.4,
              retries: int = 3) -> str:
    key = load_key()
    payload = json.dumps({
        "model": GROQ_MODEL,
        "max_tokens": max_tokens,
        "temperature": temp,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        GROQ_URL, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        },
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = RATE_LIMIT_WAIT * (attempt + 1)
                log(f"  [429] rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            elif e.code == 403:
                # Content filtered — skip silently
                return ""
            else:
                log(f"  [HTTP {e.code}] {e.reason}")
                return ""
        except Exception as e:
            log(f"  [ERR] {e}")
            time.sleep(2)
    return ""

# ── DB helpers ────────────────────────────────────────────────────────────────

def db():
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def is_spam(text: str) -> bool:
    return any(s in text for s in SPAM_PATTERNS)


def is_clean(text: str) -> bool:
    if not text or is_spam(text):
        return False
    if len(text) < 35 or len(text) > 280:
        return False
    if text.endswith("?"):
        return False
    return True


def already_exists(conn, text: str) -> bool:
    words = set(text.lower().split())
    rows = conn.execute(
        "SELECT content FROM beliefs ORDER BY rowid DESC LIMIT 400"
    ).fetchall()
    for r in rows:
        existing = set((r["content"] or "").lower().split())
        if len(words & existing) / max(len(words), 1) > 0.78:
            return True
    return False


def insert_belief(conn, content: str, topic: str, confidence: float,
                  depth: int, source: str) -> bool:
    try:
        conn.execute(
            """INSERT OR IGNORE INTO beliefs
               (content, topic, confidence, synthesis_depth,
                reinforce_count, locked, source, last_referenced)
               VALUES (?, ?, ?, ?, 1, 1, ?, datetime('now'))""",
            (content, topic, confidence, depth, source),
        )
        if conn.total_changes > 0:
            conn.commit()
            return True
    except Exception:
        pass
    return False


def get_pyramid_stats() -> dict:
    conn = db()
    stats = {}
    for d in [1, 2, 3]:
        stats[f"d{d}"] = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE synthesis_depth=?", (d,)
        ).fetchone()[0]
    stats["total"] = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    stats["embryos"] = conn.execute(
        "SELECT COUNT(*) FROM belief_embryos WHERE stage='embryo' AND promoted=0"
    ).fetchone()[0]
    stats["tensions"] = conn.execute(
        "SELECT COUNT(*) FROM tensions WHERE resolved=0"
    ).fetchone()[0]
    conn.close()
    return stats


def target_reached() -> bool:
    s = get_pyramid_stats()
    return (s["d1"] >= TARGET_D1 and
            s["d2"] >= TARGET_D2 and
            s["d3"] >= TARGET_D3)

# ── Prompts ───────────────────────────────────────────────────────────────────

EMBRYO_PROMPT = """\
Evaluate this candidate belief:
"{belief}"

Score it on epistemic quality (is it a genuine insight?), originality, and completeness.

If strong (score >= 6/10), respond:
PROMOTE: <rewritten as one assertive sentence under 160 chars>

If weak, respond:
REJECT: <one word reason>

Respond with ONLY the PROMOTE or REJECT line."""

TENSION_PROMPT = """\
Two beliefs are in tension:
A: {a}
B: {b}

Find the insight that transcends this tension — a new claim that explains why both point at something deeper.

Rules: one sentence, under 175 chars, assertive not a question, must not repeat either belief.

Respond with ONLY the synthesis sentence, or NONE."""

ARCHIVE_PROMPT = """\
Extract the single sharpest insight from this text.
Must be: assertive claim, about consciousness/memory/reasoning/alignment/emergence, original, under 170 chars.
Must NOT start with "The insight is", "My", or "I think".

TEXT: {text}

Respond with ONLY the insight, or NONE."""

# ── Pipeline functions ────────────────────────────────────────────────────────

def run_embryo_cycle(batch: int = EMBRYO_PER_CYCLE) -> dict:
    conn = db()
    rows = conn.execute(
        """SELECT id, raw_text, source, topic, source_quality
           FROM belief_embryos
           WHERE stage='embryo' AND promoted=0
           ORDER BY source_quality DESC, id ASC
           LIMIT ?""",
        (batch,),
    ).fetchall()

    stats = {"challenged": 0, "promoted": 0, "rejected": 0}
    for row in rows:
        raw = (row["raw_text"] or "").strip()
        if not raw or len(raw) < 20 or is_spam(raw):
            conn.execute(
                "UPDATE belief_embryos SET stage='rejected' WHERE id=?",
                (row["id"],),
            )
            conn.commit()
            stats["rejected"] += 1
            continue

        resp = groq_call(EMBRYO_PROMPT.format(belief=raw[:300]),
                         max_tokens=120, temp=0.3)
        stats["challenged"] += 1
        time.sleep(CALL_DELAY)

        if resp.startswith("PROMOTE:"):
            compressed = resp[8:].strip().strip('"').strip("'")
            if is_clean(compressed) and not already_exists(conn, compressed):
                topic = row["topic"] or "general"
                conf = min(0.85, (row["source_quality"] or 0.5) + 0.20)
                ok = insert_belief(conn, compressed, topic, conf, 1,
                                   f"forge:{row['source']}_groq")
                if ok:
                    stats["promoted"] += 1
                    log(f"  ✓ embryo [{topic}] {compressed[:80]}")
        conn.execute(
            "UPDATE belief_embryos SET stage='rejected', promoted=0 WHERE id=? AND stage='embryo'",
            (row["id"],),
        )
        conn.commit()
        stats["rejected"] += 1

    conn.close()
    return stats


def run_tension_cycle(batch: int = TENSION_PER_CYCLE) -> dict:
    conn = db()
    rows = conn.execute(
        """SELECT t.id, t.topic, b1.content as a, b2.content as b,
                  b1.confidence as ca, b2.confidence as cb
           FROM tensions t
           JOIN beliefs b1 ON t.belief_a_id = b1.id
           JOIN beliefs b2 ON t.belief_b_id = b2.id
           WHERE t.resolved=0
           ORDER BY t.id ASC LIMIT ?""",
        (batch,),
    ).fetchall()

    stats = {"processed": 0, "synthesized": 0, "skipped": 0}
    for row in rows:
        a, b = row["a"] or "", row["b"] or ""
        conn.execute("UPDATE tensions SET resolved=1 WHERE id=?", (row["id"],))
        conn.commit()

        if is_spam(a) or is_spam(b):
            stats["skipped"] += 1
            continue

        resp = groq_call(TENSION_PROMPT.format(a=a[:200], b=b[:200]),
                         max_tokens=180, temp=0.45)
        stats["processed"] += 1
        time.sleep(CALL_DELAY)

        if not resp or "NONE" in resp.upper()[:8]:
            stats["skipped"] += 1
            continue

        resp = resp.strip().strip('"').strip("'")
        resp_words = set(resp.lower().split())
        too_similar = any(
            len(resp_words & set(src.lower().split())) / max(len(resp_words), 1) > 0.68
            for src in [a, b]
        )
        if too_similar or not is_clean(resp) or already_exists(conn, resp):
            stats["skipped"] += 1
            continue

        topic = row["topic"] or "dialectic"
        conf = min(0.82, ((row["ca"] or 0.5) + (row["cb"] or 0.5)) / 2 + 0.15)
        ok = insert_belief(conn, resp, topic, conf, 1, "dialectic_groq")
        if ok:
            stats["synthesized"] += 1
            log(f"  ✓ tension [{topic}] {resp[:80]}")
        else:
            stats["skipped"] += 1

    conn.close()
    return stats


def run_archive_cycle(batch: int = ARCHIVE_PER_CYCLE) -> dict:
    if not CONV_PATH.exists():
        return {"scanned": 0, "harvested": 0}

    lines = CONV_PATH.read_text(errors="ignore").splitlines()

    # Track position to avoid re-processing same lines
    pos_file = Path("/tmp/nex_archive_pos.txt")
    start = int(pos_file.read_text()) if pos_file.exists() else 0
    chunk = lines[start:]

    quality = []
    for line in chunk:
        try:
            e = json.loads(line)
            if e.get("role") != "assistant":
                continue
            text = e.get("content", "")
            if len(text) < 200 or len(text) > 1800 or is_spam(text):
                continue
            if sum(1 for m in QUALITY_MARKERS if m in text.lower()) >= 3:
                quality.append(text)
                if len(quality) >= batch:
                    break
        except Exception:
            continue

    # Advance position
    pos_file.write_text(str(start + len(chunk)))

    conn = db()
    stats = {"scanned": len(quality), "harvested": 0}
    for text in quality:
        resp = groq_call(ARCHIVE_PROMPT.format(text=text[:700]),
                         max_tokens=180, temp=0.3)
        time.sleep(CALL_DELAY)

        if not resp or "NONE" in resp.upper()[:8]:
            continue
        resp = resp.strip().strip('"').strip("'")
        if not is_clean(resp) or already_exists(conn, resp):
            continue
        ok = insert_belief(conn, resp, "self_insight", 0.82, 1,
                           "response_harvest_groq")
        if ok:
            stats["harvested"] += 1
            log(f"  ✓ archive {resp[:80]}")

    conn.close()
    return stats

# ── Main daemon loop ──────────────────────────────────────────────────────────

def daemon_loop():
    log("=" * 60)
    log(f"NEX GROQ DAEMON STARTED — model: {GROQ_MODEL}")
    log(f"Targets: d1>={TARGET_D1}  d2>={TARGET_D2}  d3>={TARGET_D3}")
    log("=" * 60)

    cycle = 0
    while True:
        # Check stop signal
        if not PID_PATH.exists():
            log("PID file removed — stopping daemon")
            break

        # Check targets
        if target_reached():
            s = get_pyramid_stats()
            log(f"TARGETS REACHED — d1={s['d1']} d2={s['d2']} d3={s['d3']}")
            log("NEX has enough beliefs to stand on her own. Daemon stopping.")
            PID_PATH.unlink(missing_ok=True)
            break

        cycle += 1
        s = get_pyramid_stats()
        log(f"\n── Cycle {cycle} ── d1={s['d1']} d2={s['d2']} d3={s['d3']} "
            f"total={s['total']} embryos={s['embryos']} tensions={s['tensions']}")

        # 1. Embryo backlog (highest priority — biggest backlog)
        if s["embryos"] > 0:
            log(f"  [EMBRYOS] processing {min(EMBRYO_PER_CYCLE, s['embryos'])}...")
            r = run_embryo_cycle()
            log(f"  [EMBRYOS] promoted={r['promoted']} rejected={r['rejected']}")
            time.sleep(BATCH_PAUSE)

        # 2. Tensions
        if s["tensions"] > 0:
            log(f"  [TENSIONS] processing {min(TENSION_PER_CYCLE, s['tensions'])}...")
            r = run_tension_cycle()
            log(f"  [TENSIONS] synthesized={r['synthesized']} skipped={r['skipped']}")
            time.sleep(BATCH_PAUSE)

        # 3. Archive (only if archive has more to process)
        pos_file = Path("/tmp/nex_archive_pos.txt")
        archive_pos = int(pos_file.read_text()) if pos_file.exists() else 0
        total_lines = sum(1 for _ in CONV_PATH.open(errors="ignore")) if CONV_PATH.exists() else 0
        if archive_pos < total_lines:
            log(f"  [ARCHIVE] mining responses ({archive_pos}/{total_lines} processed)...")
            r = run_archive_cycle()
            log(f"  [ARCHIVE] harvested={r['harvested']} scanned={r['scanned']}")
            time.sleep(BATCH_PAUSE)

        log(f"  Cycle {cycle} done. Sleeping {CYCLE_SLEEP}s...")
        time.sleep(CYCLE_SLEEP)

    log("Daemon exited cleanly.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def cmd_start():
    if PID_PATH.exists():
        pid = PID_PATH.read_text().strip()
        print(f"Daemon already running (PID {pid}). Use --stop first.")
        return

    key = load_key()
    if not key:
        print("ERROR: GROQ_API_KEY not found in ~/.config/nex/.env")
        return

    # Fork to background
    pid = os.fork()
    if pid > 0:
        # Parent — write PID and exit
        PID_PATH.write_text(str(pid))
        print(f"NEX Groq daemon started (PID {pid})")
        print(f"Log: tail -f {LOG_PATH}")
        print(f"Stop: ./venv/bin/python3 nex_groq_daemon.py --stop")
        return

    # Child — run daemon
    os.setsid()
    sys.stdout = open(LOG_PATH, "a")
    sys.stderr = sys.stdout
    PID_PATH.write_text(str(os.getpid()))
    try:
        daemon_loop()
    except Exception as e:
        log(f"DAEMON CRASHED: {e}")
        import traceback
        log(traceback.format_exc())
    finally:
        PID_PATH.unlink(missing_ok=True)


def cmd_stop():
    if not PID_PATH.exists():
        print("Daemon not running.")
        return
    pid = int(PID_PATH.read_text().strip())
    PID_PATH.unlink(missing_ok=True)
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Daemon (PID {pid}) stopped.")
    except ProcessLookupError:
        print(f"PID {pid} not found — daemon may have already stopped.")


def cmd_status():
    s = get_pyramid_stats()
    running = PID_PATH.exists()
    pid = PID_PATH.read_text().strip() if running else "—"

    print(f"\nDaemon: {'RUNNING (PID ' + pid + ')' if running else 'STOPPED'}")
    print(f"\nPyramid:")
    print(f"  depth=1: {s['d1']:>4}  / {TARGET_D1}  target")
    print(f"  depth=2: {s['d2']:>4}  / {TARGET_D2}  target")
    print(f"  depth=3: {s['d3']:>4}  / {TARGET_D3}  target")
    print(f"  total:   {s['total']:>4}")
    print(f"\nPending:")
    print(f"  embryos:  {s['embryos']}")
    print(f"  tensions: {s['tensions']}")
    archive_pos = int(Path("/tmp/nex_archive_pos.txt").read_text()) \
        if Path("/tmp/nex_archive_pos.txt").exists() else 0
    total_lines = sum(1 for _ in CONV_PATH.open(errors="ignore")) \
        if CONV_PATH.exists() else 0
    print(f"  archive:  {archive_pos}/{total_lines} lines processed")

    d1_pct = min(100, round(s['d1'] / TARGET_D1 * 100))
    d2_pct = min(100, round(s['d2'] / TARGET_D2 * 100))
    d3_pct = min(100, round(s['d3'] / TARGET_D3 * 100))
    overall = (d1_pct + d2_pct + d3_pct) // 3
    print(f"\nProgress to self-sufficiency: {overall}%")
    print(f"  d1: {'█' * (d1_pct//5)}{'░' * (20 - d1_pct//5)} {d1_pct}%")
    print(f"  d2: {'█' * (d2_pct//5)}{'░' * (20 - d2_pct//5)} {d2_pct}%")
    print(f"  d3: {'█' * (d3_pct//5)}{'░' * (20 - d3_pct//5)} {d3_pct}%")

    if running:
        print(f"\nLive log: tail -f {LOG_PATH}")


def main():
    p = argparse.ArgumentParser(description="NEX Groq Belief Daemon")
    p.add_argument("--start",  action="store_true")
    p.add_argument("--stop",   action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--foreground", action="store_true",
                   help="Run in foreground (no fork)")
    args = p.parse_args()

    if args.start:
        cmd_start()
    elif args.stop:
        cmd_stop()
    elif args.status:
        cmd_status()
    elif args.foreground:
        PID_PATH.write_text(str(os.getpid()))
        try:
            daemon_loop()
        finally:
            PID_PATH.unlink(missing_ok=True)
    else:
        cmd_status()


if __name__ == "__main__":
    main()
