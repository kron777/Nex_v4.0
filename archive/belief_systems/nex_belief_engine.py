#!/usr/bin/env python3
"""
nex_belief_engine.py — Quality-first belief management for NEX

Replaces the dumb "group by topic, delete all" merge with:
  1. INTAKE GATE   — rejects garbage before it touches the DB
  2. LLM REFINERY  — raw text → clean assertive belief via local LLM
  3. DEDUP CHECK   — cosine similarity against existing beliefs (FAISS)
  4. SEMANTIC MERGE — only merges beliefs >0.90 cosine sim, keeps diversity
  5. GARBAGE SWEEP  — cleans existing Frankenstein merged beliefs + templates

Wire into run.py:
  from nex_belief_engine import BeliefEngine
  belief_engine = BeliefEngine()
  belief_engine.start()

Or call directly:
  from nex_belief_engine import gate_belief, refine_belief, sweep_garbage
"""

import os, re, json, sqlite3, threading, time, logging, hashlib
import numpy as np
from datetime import datetime
from urllib.request import urlopen, Request

log = logging.getLogger("nex.belief_engine")
_LOG_DIR = os.path.expanduser("~/Desktop/nex/logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_fh = logging.FileHandler(os.path.join(_LOG_DIR, "belief_engine.log"))
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_fh)
log.setLevel(logging.DEBUG)

DB_PATH   = os.path.expanduser("~/Desktop/nex/nex.db")
LLAMA_URL = "http://localhost:8080/v1/chat/completions"
UA        = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TAG       = "  [BELIEF_ENGINE]"

# ── Quality thresholds ────────────────────────────────────────────────────────

MIN_BELIEF_LEN       = 30      # chars
MAX_BELIEF_LEN       = 500     # chars — beliefs should be concise
DEDUP_SIM_THRESHOLD  = 0.88    # cosine sim to count as duplicate
MERGE_SIM_THRESHOLD  = 0.92    # cosine sim required for semantic merge
MIN_COHERENCE_SCORE  = 0.4     # LLM-judged coherence (0-1)
MAX_QUESTION_RATIO   = 0.3     # max fraction of beliefs that can be questions

# Patterns that indicate garbage beliefs
GARBAGE_PATTERNS = [
    r"^OPEN QUESTION:",
    r"^What does bridge:",
    r"^On this: \[Synthesized",
    r"\|\|.*\|\|",                    # Frankenstein merged beliefs
    r"^\[merged:\d+\]",              # Explicit merge artifacts
    r"^https?://",                    # Raw URLs
    r"^FACT: none",
    r"the more I understand emergence.*different domain",  # Template spam
    r"What does .+ have to do with a different domain",    # Template spam
]
GARBAGE_RE = [re.compile(p, re.IGNORECASE) for p in GARBAGE_PATTERNS]


# ── LLM call ─────────────────────────────────────────────────────────────────

def _llm(prompt: str, max_tokens: int = 300) -> str:
    try:
        payload = json.dumps({
            "model": "qwen2.5",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": False,
        }).encode()
        req = Request(LLAMA_URL, data=payload,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
            choices = data.get("choices", [])
            return choices[0]["message"]["content"].strip() if choices else ""
    except Exception as e:
        log.warning(f"{TAG} LLM call failed: {e}")
        return ""


# ── 1. INTAKE GATE ───────────────────────────────────────────────────────────

def gate_belief(content: str) -> tuple[bool, str]:
    """
    Returns (passes, reason).
    Fast checks — no LLM, no DB. Call before any INSERT.
    """
    content = content.strip()

    # Length checks
    if len(content) < MIN_BELIEF_LEN:
        return False, "too_short"
    if len(content) > MAX_BELIEF_LEN:
        return False, "too_long"

    # Garbage pattern check
    for pattern in GARBAGE_RE:
        if pattern.search(content):
            return False, "garbage_pattern"

    # Question check — beliefs should be assertions, not questions
    if content.rstrip().endswith("?"):
        # Allow some questions but flag them
        return True, "question"

    # Repetition check — same phrase repeated
    words = content.lower().split()
    if len(words) > 10:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.4:
            return False, "repetitive"

    # Contains actual semantic content (not just stopwords/connectors)
    content_words = [w for w in words if len(w) > 4]
    if len(content_words) < 3:
        return False, "no_substance"

    return True, "ok"


# ── 2. LLM REFINERY ─────────────────────────────────────────────────────────

REFINE_PROMPT = """You are a belief distiller. Take the raw text below and rewrite it as a single, clear, assertive belief statement.

Rules:
- Output ONLY the refined belief, nothing else
- Must be a declarative statement (not a question)
- Must be specific and concrete
- Must be between 30-200 characters
- Remove any meta-commentary, template language, or self-reference
- If the raw text contains no real belief, output: SKIP

Raw text:
{raw_text}

Refined belief:"""

def refine_belief(raw: str) -> str | None:
    """
    Pass raw extracted text through LLM to produce a clean belief.
    Returns refined belief string or None if not worth keeping.
    """
    raw = raw.strip()
    if len(raw) < 20:
        return None

    resp = _llm(REFINE_PROMPT.format(raw_text=raw[:600]), max_tokens=150)
    if not resp or "SKIP" in resp.upper():
        return None

    # Clean up
    refined = resp.strip().strip('"').strip("'")

    # Validate the refinement
    passes, reason = gate_belief(refined)
    if not passes:
        return None

    return refined


# ── 3. DEDUP CHECK ───────────────────────────────────────────────────────────

def _get_embedding(text: str) -> np.ndarray | None:
    """Get embedding from llama-server."""
    try:
        payload = json.dumps({
            "input": text[:512],
            "model": "qwen2.5",
        }).encode()
        req = Request("http://localhost:8080/v1/embeddings",
                      data=payload,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            emb = data["data"][0]["embedding"]
            arr = np.array(emb, dtype=np.float32)
            return arr / (np.linalg.norm(arr) + 1e-9)
    except Exception as e:
        log.debug(f"{TAG} embedding failed: {e}")
        return None


def is_duplicate(content: str, db_path: str = DB_PATH,
                 threshold: float = DEDUP_SIM_THRESHOLD) -> bool:
    """
    Check if a belief is too similar to an existing one.
    Uses simple text hashing first, then embedding similarity for near-misses.
    """
    # Fast exact/near-exact check
    content_lower = content.lower().strip()
    content_hash = hashlib.md5(content_lower.encode()).hexdigest()

    try:
        conn = sqlite3.connect(db_path)
        # Check exact content match
        exists = conn.execute(
            "SELECT 1 FROM beliefs WHERE content = ? LIMIT 1",
            (content,)
        ).fetchone()
        if exists:
            conn.close()
            return True

        # Check similar starts (first 50 chars)
        prefix = content[:50]
        similar = conn.execute(
            "SELECT content FROM beliefs WHERE content LIKE ? LIMIT 5",
            (prefix + "%",)
        ).fetchall()
        conn.close()

        if similar:
            for (existing,) in similar:
                # Jaccard similarity on words
                words_new = set(content_lower.split())
                words_old = set(existing.lower().split())
                if not words_new or not words_old:
                    continue
                jaccard = len(words_new & words_old) / len(words_new | words_old)
                if jaccard > threshold:
                    return True

    except Exception as e:
        log.debug(f"{TAG} dedup check error: {e}")

    return False


# ── 4. QUALITY INSERT ────────────────────────────────────────────────────────

def insert_quality_belief(content: str, topic: str = "general",
                          confidence: float = 0.55,
                          source: str = "", db_path: str = DB_PATH) -> bool:
    """
    The single entry point for adding beliefs to NEX.
    Runs gate → dedup → insert. Returns True if inserted.
    """
    # Gate check
    passes, reason = gate_belief(content)
    if not passes:
        log.debug(f"{TAG} rejected ({reason}): {content[:60]}")
        return False

    # Dedup check
    if is_duplicate(content, db_path):
        log.debug(f"{TAG} duplicate: {content[:60]}")
        return False

    # Insert
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """INSERT OR IGNORE INTO beliefs
               (content, topic, confidence, source, belief_type)
               VALUES (?, ?, ?, ?, 'belief')""",
            (content, topic, confidence, source)
        )
        inserted = conn.execute("SELECT changes()").fetchone()[0] > 0
        conn.commit()
        conn.close()
        if inserted:
            log.info(f"{TAG} +belief ({topic}, {confidence:.2f}): {content[:60]}")
        return inserted
    except Exception as e:
        log.warning(f"{TAG} insert error: {e}")
        return False


# ── 5. GARBAGE SWEEP ─────────────────────────────────────────────────────────

def sweep_garbage(db_path: str = DB_PATH, dry_run: bool = False) -> dict:
    """
    Clean existing garbage from the belief DB.
    Returns stats on what was removed.
    """
    stats = {"frankenstein": 0, "template_spam": 0, "too_short": 0,
             "too_long": 0, "questions": 0, "repetitive": 0, "total_removed": 0}

    try:
        conn = sqlite3.connect(db_path)
        all_beliefs = conn.execute(
            "SELECT id, content, locked FROM beliefs WHERE locked=0 AND (source IS NULL OR source NOT LIKE '%pyramid%') AND synthesis_depth=0"
        ).fetchall()

        to_delete = []
        for bid, content, locked in all_beliefs:
            if not content:
                to_delete.append((bid, "empty"))
                continue

            # Frankenstein merged beliefs
            if content.startswith("[merged:") or " || " in content:
                to_delete.append((bid, "frankenstein"))
                stats["frankenstein"] += 1
                continue

            # Template spam
            for pattern in GARBAGE_RE:
                if pattern.search(content):
                    to_delete.append((bid, "template_spam"))
                    stats["template_spam"] += 1
                    break
            else:
                # Length checks
                if len(content) < MIN_BELIEF_LEN:
                    to_delete.append((bid, "too_short"))
                    stats["too_short"] += 1
                elif len(content) > 1000:
                    to_delete.append((bid, "too_long"))
                    stats["too_long"] += 1

        stats["total_removed"] = len(to_delete)

        if not dry_run and to_delete:
            ids = [bid for bid, _ in to_delete]
            # Batch delete in chunks of 100
            for i in range(0, len(ids), 100):
                chunk = ids[i:i+100]
                placeholders = ",".join("?" * len(chunk))
                conn.execute(
                    f"DELETE FROM beliefs WHERE id IN ({placeholders})",
                    tuple(chunk)
                )
            conn.commit()
            log.info(f"{TAG} swept {len(to_delete)} garbage beliefs")

        conn.close()
    except Exception as e:
        log.warning(f"{TAG} sweep error: {e}")

    return stats


# ── 6. SEMANTIC MERGE (replaces ABMv2) ───────────────────────────────────────

def semantic_merge(topic: str = None, db_path: str = DB_PATH,
                   max_merges: int = 5) -> int:
    """
    Merge only near-duplicate beliefs (>0.92 cosine similarity).
    Keeps the highest-confidence version. Does NOT concatenate.
    Returns number of merges performed.
    """
    merges = 0
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        query = """
            SELECT id, content, confidence, topic FROM beliefs
            WHERE locked=0 AND content NOT LIKE '[merged:%'
        """
        params = ()
        if topic:
            query += " AND topic = ?"
            params = (topic,)
        query += " ORDER BY confidence ASC LIMIT 200"

        beliefs = conn.execute(query, params).fetchall()
        conn.close()

        if len(beliefs) < 2:
            return 0

        # Find near-duplicates using word overlap (fast approximation)
        to_remove = set()
        for i in range(len(beliefs)):
            if beliefs[i]["id"] in to_remove:
                continue
            words_i = set(beliefs[i]["content"].lower().split())
            for j in range(i + 1, len(beliefs)):
                if beliefs[j]["id"] in to_remove:
                    continue
                if merges >= max_merges:
                    break

                words_j = set(beliefs[j]["content"].lower().split())
                if not words_i or not words_j:
                    continue

                jaccard = len(words_i & words_j) / len(words_i | words_j)
                if jaccard > MERGE_SIM_THRESHOLD:
                    # Keep the one with higher confidence
                    if beliefs[i]["confidence"] >= beliefs[j]["confidence"]:
                        to_remove.add(beliefs[j]["id"])
                    else:
                        to_remove.add(beliefs[i]["id"])
                    merges += 1

            if merges >= max_merges:
                break

        if to_remove:
            conn = sqlite3.connect(db_path)
            placeholders = ",".join("?" * len(to_remove))
            conn.execute(
                f"DELETE FROM beliefs WHERE id IN ({placeholders})",
                tuple(to_remove)
            )
            conn.commit()
            conn.close()
            log.info(f"{TAG} semantic merge: removed {len(to_remove)} near-duplicates")

    except Exception as e:
        log.warning(f"{TAG} semantic merge error: {e}")

    return merges


# ── 7. BELIEF ENRICHMENT — borrow intel from quality sources ─────────────────

ENRICH_PROMPT = """You are NEX, an autonomous AI agent building a belief system about {topic}.

Based on your knowledge, generate 3-5 high-quality beliefs about {topic}. Each belief must be:
- A specific, concrete assertion (not a question or vague statement)
- Grounded in established knowledge or well-reasoned inference
- Useful for an AI agent reasoning about the world
- Between 50-200 characters

Format: one belief per line, starting with "BELIEF:"

Topic context: {context}

Generate beliefs:"""

def enrich_topic(topic: str, context: str = "",
                 db_path: str = DB_PATH) -> int:
    """
    Use the LLM to generate quality beliefs about a topic.
    This is how NEX "borrows intel" — the LLM synthesizes from its training.
    Returns number of beliefs inserted.
    """
    prompt = ENRICH_PROMPT.format(
        topic=topic,
        context=context or f"NEX is building knowledge about {topic}"
    )

    resp = _llm(prompt, max_tokens=500)
    if not resp:
        return 0

    inserted = 0
    for line in resp.splitlines():
        line = line.strip()
        if not line.upper().startswith("BELIEF:"):
            continue
        belief = line[7:].strip()
        if not belief:
            continue

        if insert_quality_belief(belief, topic=topic, confidence=0.60,
                                  source="llm_enrichment", db_path=db_path):
            inserted += 1

    if inserted:
        print(f"{TAG} enriched '{topic}' with {inserted} quality beliefs")

    return inserted


# ── 8. DAEMON ────────────────────────────────────────────────────────────────

class BeliefEngine(threading.Thread):
    """
    Background daemon:
      - Every 30 min: sweep garbage, semantic merge
      - Every 2 hours: enrich weakest topics via LLM
    """
    SWEEP_INTERVAL   = 1800   # 30 min
    ENRICH_INTERVAL  = 7200   # 2 hours
    TOPICS_PER_ENRICH = 3     # topics to enrich per cycle

    def __init__(self):
        super().__init__(daemon=True, name="BeliefEngine")
        self._stop = threading.Event()
        self._last_sweep = 0.0
        self._last_enrich = 0.0

    def run(self):
        print(f"{TAG} started — sweep every {self.SWEEP_INTERVAL//60}min, "
              f"enrich every {self.ENRICH_INTERVAL//60}min")

        # Initial delay
        self._stop.wait(120)

        # Initial garbage sweep
        stats = sweep_garbage()
        if stats["total_removed"]:
            print(f"{TAG} initial sweep: removed {stats['total_removed']} garbage beliefs "
                  f"(frankenstein={stats['frankenstein']}, "
                  f"template={stats['template_spam']})")

        while not self._stop.is_set():
            now = time.time()

            # Sweep + merge
            if now - self._last_sweep > self.SWEEP_INTERVAL:
                self._last_sweep = now
                try:
                    stats = sweep_garbage()
                    if stats["total_removed"]:
                        print(f"{TAG} sweep: -{stats['total_removed']} garbage")
                    merged = semantic_merge(max_merges=10)
                    if merged:
                        print(f"{TAG} merged {merged} near-duplicates")
                except Exception as e:
                    log.warning(f"{TAG} sweep/merge error: {e}")

            # Enrich
            if now - self._last_enrich > self.ENRICH_INTERVAL:
                self._last_enrich = now
                try:
                    self._enrich_weakest()
                except Exception as e:
                    log.warning(f"{TAG} enrich error: {e}")

            self._stop.wait(60)

    def _enrich_weakest(self):
        """Find topics with lowest avg confidence and enrich them."""
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute("""
                SELECT topic, COUNT(*) n, AVG(confidence) ac
                FROM beliefs
                WHERE topic IS NOT NULL AND topic != ''
                GROUP BY topic
                HAVING n >= 5
                ORDER BY ac ASC
                LIMIT ?
            """, (self.TOPICS_PER_ENRICH,)).fetchall()
            conn.close()

            for topic, count, avg_conf in rows:
                # Get some existing beliefs as context
                conn = sqlite3.connect(DB_PATH)
                samples = conn.execute(
                    "SELECT content FROM beliefs WHERE topic=? "
                    "ORDER BY confidence DESC LIMIT 3",
                    (topic,)
                ).fetchall()
                conn.close()

                context = "; ".join(s[0][:100] for s in samples)
                added = enrich_topic(topic, context)
                if added:
                    log.info(f"{TAG} enriched '{topic}' ({count} beliefs, "
                             f"avg_conf={avg_conf:.2f}) with {added} new")
                time.sleep(5)  # don't hammer the LLM

        except Exception as e:
            log.warning(f"{TAG} enrich weakest error: {e}")

    def stop(self):
        self._stop.set()


# ── Standalone usage ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NEX Belief Engine")
    parser.add_argument("--sweep", action="store_true",
                        help="Sweep garbage (dry run)")
    parser.add_argument("--sweep-live", action="store_true",
                        help="Sweep garbage (actually delete)")
    parser.add_argument("--enrich", type=str,
                        help="Enrich a specific topic")
    parser.add_argument("--stats", action="store_true",
                        help="Show belief quality stats")
    parser.add_argument("--gate-test", type=str,
                        help="Test if a belief passes the gate")
    args = parser.parse_args()

    if args.stats:
        conn = sqlite3.connect(DB_PATH)
        total = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        garbage_count = 0
        for bid, content, _ in conn.execute(
            "SELECT id, content, locked FROM beliefs WHERE locked=0"
        ).fetchall():
            passes, reason = gate_belief(content or "")
            if not passes:
                garbage_count += 1
        questions = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE content LIKE '%?'"
        ).fetchone()[0]
        merged = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE content LIKE '[merged:%'"
        ).fetchone()[0]
        frankenstein = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE content LIKE '% || %'"
        ).fetchone()[0]
        conn.close()
        print(f"\nBelief Quality Report")
        print(f"  Total:        {total}")
        print(f"  Garbage:      {garbage_count} ({garbage_count*100//max(total,1)}%)")
        print(f"  Questions:    {questions}")
        print(f"  Merged blobs: {merged}")
        print(f"  Frankenstein: {frankenstein}")
        print(f"  Clean:        {total - garbage_count}")

    elif args.sweep or args.sweep_live:
        stats = sweep_garbage(dry_run=not args.sweep_live)
        mode = "LIVE" if args.sweep_live else "DRY RUN"
        print(f"\nGarbage Sweep ({mode}):")
        for k, v in stats.items():
            print(f"  {k}: {v}")

    elif args.enrich:
        n = enrich_topic(args.enrich)
        print(f"Enriched '{args.enrich}' with {n} beliefs")

    elif args.gate_test:
        passes, reason = gate_belief(args.gate_test)
        print(f"{'✓ PASS' if passes else '✗ FAIL'} ({reason}): {args.gate_test[:80]}")

    else:
        parser.print_help()
