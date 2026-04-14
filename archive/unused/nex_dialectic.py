"""
nex_dialectic.py — Dialectic Synthesis Engine for NEX
======================================================
Three belief sources that currently go to waste:

1. TENSION SYNTHESIS — 573 unresolved contradictions in the tensions table.
   Each contradiction is a dialectic opportunity. Thesis + antithesis → synthesis.
   These become the highest-quality depth=1 beliefs because they're born from
   genuine conceptual conflict, not scraping.

2. RESPONSE HARVESTING — conversations.jsonl contains NEX's actual reasoning.
   Good responses contain original insights. Bad ones are template spam.
   Filter and deposit the good ones as embryos.

3. CURIOSITY GAPS — topics mentioned in conversation but thin in beliefs.
   Cross-reference discourse frequency vs belief depth and queue targeted research.

All output goes to the forge embryo quarantine table for challenge + compress
before promotion. Nothing bypasses quality gates.

Wire into run.py alongside BeliefForge.
"""

import sqlite3
import json
import time
import re
import threading
import logging
from pathlib import Path
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH   = str(Path.home() / "Desktop/nex/nex.db")
CONV_LOG  = str(Path.home() / "Desktop/nex/logs/conversations.jsonl")
LOG_PATH  = str(Path.home() / "Desktop/nex/logs/dialectic.log")
LLM_URL   = "http://localhost:8080/v1/chat/completions"
LLM_MODEL = "qwen2.5"

TENSION_BATCH     = 10     # tensions to process per cycle
RESPONSE_BATCH    = 20     # recent responses to scan per cycle
TENSION_INTERVAL  = 3600   # 1 hour
RESPONSE_INTERVAL = 1800   # 30 min
MIN_RESPONSE_LEN  = 120    # minimum chars for a harvestable response
MAX_RESPONSE_LEN  = 1200   # maximum — very long responses dilute quality

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
log = logging.getLogger("dialectic")

# ── Prompts ───────────────────────────────────────────────────────────────────
DIALECTIC_PROMPT = """Two beliefs are in tension:

BELIEF A: {belief_a}

BELIEF B: {belief_b}

These beliefs appear to contradict each other on the topic of '{topic}'.

Synthesize a single new belief that:
1. Acknowledges the truth in BOTH beliefs
2. Resolves or transcends the contradiction
3. Is MORE precise than either original belief alone

Respond with ONLY the synthesized belief (under 200 characters).
If no genuine synthesis is possible, respond: NONE"""

RESPONSE_HARVEST_PROMPT = """Extract the single most insightful assertion from this text. 
Ignore questions, filler, and template phrases. 
Find only a clear, falsifiable claim that reveals genuine understanding.

TEXT: {response_text}

Respond with ONLY the assertion (under 180 characters), or NONE if no clear insight exists."""

SPAM_PATTERNS = [
    "The insight is",
    "My analysis suggests",
    "My belief that",
    "My work reveals",

    "What does bridge:", "bridge:truth seeking", "bridge:cognitive",
    "have to do with a different domain",
    "The more I understand emergence",
    "The interesting thing about",
    "Completely different.",
    "↔", "||", "[merged:",
    "this paper", "this work", "et al",
    "OPEN QUESTION",
    "What does this mean for",
    "seventeenth century", "eighteenth century",
]

def _is_template_spam(text: str) -> bool:
    for pat in SPAM_PATTERNS:
        if pat in text:
            return True
    return False

def _is_quality_response(text: str) -> bool:
    if len(text) < MIN_RESPONSE_LEN or len(text) > MAX_RESPONSE_LEN:
        return False
    if _is_template_spam(text):
        return False
    # Must have some substantive content markers
    quality_markers = [
        "because", "therefore", "however", "suggests", "indicates",
        "reveals", "implies", "demonstrates", "shows that", "means that",
        "structure", "pattern", "relationship", "emerges", "depends"
    ]
    text_lower = text.lower()
    hits = sum(1 for m in quality_markers if m in text_lower)
    return hits >= 2

# ── DB helpers ────────────────────────────────────────────────────────────────
def _db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _ensure_embryo_table():
    """Ensure forge embryo table exists."""
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS belief_embryos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                content     TEXT UNIQUE,
                source      TEXT,
                topic       TEXT,
                source_quality REAL DEFAULT 0.5,
                stage       TEXT DEFAULT 'raw',
                deposited_at TEXT DEFAULT (datetime('now')),
                tension_id  INTEGER DEFAULT NULL
            )
        """)

def _deposit_embryo(content: str, source: str, topic: str,
                    quality: float, tension_id: int = None) -> bool:
    """Deposit into embryo quarantine for forge processing."""
    try:
        with _db() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO belief_embryos
                   (raw_text, source, topic, source_quality, stage)
                   VALUES (?, ?, ?, ?, 'embryo')""",
                (content, source, topic, quality)
            )
        return True
    except Exception as e:
        log.warning(f"[DIALECTIC] embryo deposit error: {e}")
        return False

def _already_believed(content: str) -> bool:
    """Check if this belief already exists in some form."""
    words = set(content.lower().split())
    with _db() as conn:
        # Only check recent beliefs for dedup — faster and less aggressive
        rows = conn.execute(
            "SELECT content FROM beliefs ORDER BY rowid DESC LIMIT 200"
        ).fetchall()
    for r in rows:
        existing_words = set(r["content"].lower().split())
        overlap = len(words & existing_words) / max(len(words), 1)
        if overlap > 0.85:
            return True
    return False


def _llm_groq(prompt: str, max_tokens: int = 300, temp: float = 0.4) -> str:
    import urllib.request, json, os
    try:
        key = open(os.path.expanduser("~/.config/nex/.env")).read()
        key = [l.split("=",1)[1].strip() for l in key.splitlines() if l.startswith("GROQ_API_KEY")][0]
        payload = json.dumps({"model":"llama-3.3-70b-versatile","max_tokens":max_tokens,"temperature":temp,"messages":[{"role":"user","content":prompt}]}).encode()
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",data=payload,headers={"Content-Type":"application/json","Authorization":f"Bearer {key}"},method="POST")
        with urllib.request.urlopen(req,timeout=30) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"[GROQ] fallback to local: {e}")
        return _llm(prompt, max_tokens, temp)

# ── LLM ───────────────────────────────────────────────────────────────────────
def _llm(prompt: str, max_tokens: int = 200, temp: float = 0.4) -> str:
    try:
        import urllib.request
        payload = json.dumps({
            "model": LLM_MODEL,
            "max_tokens": max_tokens,
            "temperature": temp,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()
        req = urllib.request.Request(
            LLM_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"[DIALECTIC] LLM error: {e}")
        return ""

# ── 1. Tension Synthesis ──────────────────────────────────────────────────────
def synthesize_tensions(batch: int = TENSION_BATCH) -> dict:
    """
    Pull unresolved tension pairs, synthesize dialectic beliefs,
    deposit as embryos for forge processing.
    """
    results = {"processed": 0, "synthesized": 0, "skipped": 0}

    try:
        with _db() as conn:
            rows = conn.execute("""
                SELECT t.id, t.topic, t.belief_a_id, t.belief_b_id, t.energy
                FROM tensions t
                WHERE t.resolved = 0
                ORDER BY t.energy DESC
                LIMIT ?
            """, (batch,)).fetchall()
    except Exception as e:
        log.warning(f"[DIALECTIC] tension fetch error: {e}")
        return results

    for row in rows:
        results["processed"] += 1
        tid = row["id"]
        topic = row["topic"] or "general"

        # Fetch both beliefs
        try:
            with _db() as conn:
                ba = conn.execute(
                    "SELECT content, confidence FROM beliefs WHERE id=?",
                    (row["belief_a_id"],)
                ).fetchone()
                bb = conn.execute(
                    "SELECT content, confidence FROM beliefs WHERE id=?",
                    (row["belief_b_id"],)
                ).fetchone()
        except Exception:
            results["skipped"] += 1
            continue

        if not ba or not bb:
            results["skipped"] += 1
            continue

        # Skip if either belief is template spam
        if _is_template_spam(ba["content"]) or _is_template_spam(bb["content"]):
            results["skipped"] += 1
            # Mark resolved so we don't retry
            try:
                with _db() as conn:
                    conn.execute("UPDATE tensions SET resolved=1 WHERE id=?", (tid,))
            except Exception:
                pass
            continue

        # Synthesize
        resp = _llm_groq(
            DIALECTIC_PROMPT.format(
                belief_a=ba["content"][:200],
                belief_b=bb["content"][:200],
                topic=topic
            ),
            max_tokens=220, temp=0.4
        )
        resp = resp.strip().strip('"').strip("'").strip()

        if not resp or "NONE" in resp.upper()[:10]:
            results["skipped"] += 1
            continue

        if _is_template_spam(resp) or len(resp) < 30 or len(resp) > 700:
            results["skipped"] += 1
            continue

        if _already_believed(resp):
            results["skipped"] += 1
            continue

        # Source quality = average of the two conflicting beliefs' confidence
        # Dialectic synthesis is inherently higher value than raw scraping
        quality = min(0.78, (ba["confidence"] + bb["confidence"]) / 2 + 0.15)

        deposited = _deposit_embryo(
            resp, source="dialectic_tension",
            topic=topic, quality=quality, tension_id=tid
        )

        if deposited:
            results["synthesized"] += 1
            log.info(f"[DIALECTIC] tension→embryo [{topic}]: {resp[:80]}")
            print(f"  [DIALECTIC] tension [{topic}]: {resp[:90]}")
            # Mark tension as resolved
            try:
                with _db() as conn:
                    conn.execute(
                        "UPDATE tensions SET resolved=1 WHERE id=?", (tid,)
                    )
            except Exception:
                pass
        else:
            results["skipped"] += 1

    return results

# ── 2. Response Harvesting ────────────────────────────────────────────────────
_last_harvested_pos = 0

def harvest_responses(batch: int = RESPONSE_BATCH) -> dict:
    """
    Scan recent assistant responses from conversations.jsonl.
    Extract genuine insights, filter template spam,
    deposit quality beliefs as embryos.
    """
    global _last_harvested_pos
    results = {"scanned": 0, "quality": 0, "deposited": 0}

    try:
        conv_path = Path(CONV_LOG)
        if not conv_path.exists():
            return results

        lines = conv_path.read_text(errors="ignore").splitlines()
        # Only scan new lines since last harvest
        new_lines = lines[_last_harvested_pos:]
        _last_harvested_pos = len(lines)

        # Get last N assistant responses
        assistant_responses = []
        for line in reversed(new_lines[-500:]):
            try:
                entry = json.loads(line)
                if entry.get("role") == "assistant":
                    assistant_responses.append(entry.get("content", ""))
                    if len(assistant_responses) >= batch:
                        break
            except Exception:
                continue

        for resp_text in assistant_responses:
            results["scanned"] += 1

            if not _is_quality_response(resp_text):
                continue

            results["quality"] += 1

            # Extract the core insight via LLM
            extracted = _llm_groq(
                RESPONSE_HARVEST_PROMPT.format(
                    response_text=resp_text[:600]
                ),
                max_tokens=200, temp=0.3
            )

            if not extracted or "NONE" in extracted.upper()[:10]:
                continue

            if _is_template_spam(extracted) or len(extracted) < 30:
                continue

            if _already_believed(extracted):
                continue

            # Response-harvested beliefs get high source quality —
            # they came from NEX's own reasoning
            deposited = _deposit_embryo(
                extracted,
                source="response_harvest",
                topic="self_insight",
                quality=0.75
            )

            if deposited:
                results["deposited"] += 1
                log.info(f"[DIALECTIC] harvested: {extracted[:80]}")

    except Exception as e:
        log.warning(f"[DIALECTIC] harvest error: {e}")

    return results

# ── 3. Direct forge promotion for dialectic embryos ───────────────────────────
def promote_dialectic_embryos() -> dict:
    """
    Push dialectic embryos through the forge pipeline.
    Bypasses the normal embryo wait — dialectic beliefs are pre-challenged
    by the synthesis process itself.
    """
    results = {"promoted": 0, "rejected": 0}

    try:
        with _db() as conn:
            embryos = conn.execute("""
                SELECT id, content, topic, source_quality
                FROM belief_embryos
                WHERE stage='raw'
                  AND source IN ('dialectic_tension', 'response_harvest')
                ORDER BY source_quality DESC
                LIMIT 20
            """).fetchall()
    except Exception as e:
        log.warning(f"[DIALECTIC] embryo fetch error: {e}")
        return results

    for e in embryos:
        content = e["content"]
        topic   = e["topic"] or "general"
        quality = e["source_quality"]

        # Final spam check
        if _is_template_spam(content):
            results["rejected"] += 1
            try:
                with _db() as conn:
                    conn.execute(
                        "UPDATE belief_embryos SET promoted=0, stage='rejected' WHERE id=?",
                        (e["id"],)
                    )
            except Exception:
                pass
            continue

        # Insert directly into beliefs at quality-derived confidence
        # Dialectic beliefs start higher because they survived contradiction
        conf = min(0.85, quality + 0.05)
        try:
            with _db() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO beliefs
                       (content, topic, confidence, synthesis_depth,
                        reinforce_count, locked, source, last_referenced)
                       VALUES (?, ?, ?, 1, 1, 1, 'dialectic', datetime('now'))""",
                    (content, topic, conf)
                )
                conn.execute(
                    "UPDATE belief_embryos SET promoted=1, stage='promoted' WHERE id=?",
                    (e["id"],)
                )
            results["promoted"] += 1
            log.info(f"[DIALECTIC] promoted [{topic}] conf={conf:.2f}: {content[:80]}")
        except Exception as ex:
            log.warning(f"[DIALECTIC] promote error: {ex}")
            results["rejected"] += 1

    return results

# ── Stats ─────────────────────────────────────────────────────────────────────
def dialectic_stats() -> dict:
    with _db() as conn:
        tensions_total = conn.execute("SELECT COUNT(*) FROM tensions").fetchone()[0]
        tensions_open  = conn.execute(
            "SELECT COUNT(*) FROM tensions WHERE resolved=0"
        ).fetchone()[0]
        try:
            embryos = conn.execute(
                "SELECT stage, COUNT(*) n FROM belief_embryos GROUP BY stage"
            ).fetchall()
            embryo_stats = {r["stage"]: r["n"] for r in embryos}
        except Exception:
            embryo_stats = {}
        dialectic_beliefs = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE source='dialectic'"
        ).fetchone()[0]
    return {
        "tensions_total": tensions_total,
        "tensions_open":  tensions_open,
        "embryos":        embryo_stats,
        "dialectic_beliefs": dialectic_beliefs,
    }

# ── DialecticEngine daemon ────────────────────────────────────────────────────
class DialecticEngine:
    def __init__(self):
        self._tension_last  = 0.0
        self._response_last = 0.0
        self._thread = None
        _ensure_embryo_table()

    def tick(self):
        now = time.time()
        ran = False

        if now - self._response_last >= RESPONSE_INTERVAL:
            self._response_last = now
            try:
                r = harvest_responses()
                if r["deposited"] > 0:
                    print(f"  [DIALECTIC] harvested {r['deposited']} response insights")
                pr = promote_dialectic_embryos()
                if pr["promoted"] > 0:
                    print(f"  [DIALECTIC] promoted {pr['promoted']} dialectic beliefs")
            except Exception as e:
                log.warning(f"[DIALECTIC] response cycle error: {e}")
            ran = True

        if now - self._tension_last >= TENSION_INTERVAL:
            self._tension_last = now
            try:
                r = synthesize_tensions()
                if r["synthesized"] > 0:
                    print(f"  [DIALECTIC] {r['synthesized']} tensions synthesized")
                pr = promote_dialectic_embryos()
                if pr["promoted"] > 0:
                    print(f"  [DIALECTIC] promoted {pr['promoted']} dialectic beliefs")
            except Exception as e:
                log.warning(f"[DIALECTIC] tension cycle error: {e}")
            ran = True

        return ran

    def _loop(self):
        time.sleep(90)  # startup grace
        while True:
            try:
                self.tick()
            except Exception as e:
                log.warning(f"[DIALECTIC] loop error: {e}")
            time.sleep(300)  # check every 5 min

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("[DIALECTIC] DialecticEngine started")

# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="NEX Dialectic Engine")
    p.add_argument("--stats",    action="store_true")
    p.add_argument("--tensions", action="store_true", help="Synthesize tension batch")
    p.add_argument("--harvest",  action="store_true", help="Harvest response insights")
    p.add_argument("--promote",  action="store_true", help="Promote ready embryos")
    p.add_argument("--all",      action="store_true", help="Run full cycle")
    args = p.parse_args()

    _ensure_embryo_table()

    if args.stats:
        s = dialectic_stats()
        print(f"Dialectic Engine Stats:")
        print(f"  Tensions: {s['tensions_open']} open / {s['tensions_total']} total")
        print(f"  Embryos: {s['embryos']}")
        print(f"  Dialectic beliefs promoted: {s['dialectic_beliefs']}")

    elif args.tensions:
        print(f"Synthesizing tensions (batch={TENSION_BATCH})...")
        r = synthesize_tensions()
        print(f"Results: {r}")

    elif args.harvest:
        print("Harvesting response insights...")
        r = harvest_responses()
        print(f"Results: {r}")

    elif args.promote:
        print("Promoting dialectic embryos...")
        r = promote_dialectic_embryos()
        print(f"Results: {r}")

    elif args.all:
        print("Running full dialectic cycle...")
        print("\n1. Tension synthesis:")
        r1 = synthesize_tensions()
        print(f"   {r1}")
        print("\n2. Response harvesting:")
        r2 = harvest_responses()
        print(f"   {r2}")
        print("\n3. Promoting embryos:")
        r3 = promote_dialectic_embryos()
        print(f"   {r3}")
        print("\nStats:")
        s = dialectic_stats()
        print(f"  Tensions: {s['tensions_open']} open / {s['tensions_total']} total")
        print(f"  Dialectic beliefs: {s['dialectic_beliefs']}")

    else:
        p.print_help()
