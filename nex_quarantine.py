#!/usr/bin/env python3
"""
nex_quarantine.py — NEX Belief Quarantine Engine v1.0
======================================================
A smart chokepoint for all belief writes. Every belief entering NEX's
graph passes through here. Contaminating beliefs are quarantined, not
silently dropped — so you can audit and recover if needed.

FEATURES:
  - Pattern blacklist (DB-driven, hot-reloadable)
  - ML paper extract detector (heuristic)
  - Topic relevance gate (NEX core domains)
  - Duplicate / near-duplicate detection
  - Quarantine table with reason codes
  - SQLite trigger install (optional, catches all INSERT paths)
  - Admin CLI: python3 nex_quarantine.py [status|review|purge|add-pattern]

INSTALL (one-time):
  python3 nex_quarantine.py install

USAGE IN CODE:
  from nex_quarantine import QuarantineEngine
  q = QuarantineEngine()
  result = q.check(content, source="auto_seeder", topic="consciousness")
  if result.allowed:
      db.execute("INSERT INTO beliefs ...", (content, ...))
  else:
      # Already logged to beliefs_quarantine
      print(result.reason)
"""

import sqlite3
import re
import math
import time
import logging
import argparse
import os
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("nex.quarantine")

DB_PATH = os.environ.get("NEX_DB", "/home/rr/.config/nex/nex.db")

# ── NEX Core Topic Domains ────────────────────────────────────────────────────
# Beliefs must touch at least one of these domains to pass topic gate.
# Add more as NEX expands.
NEX_DOMAINS = {
    "consciousness", "mind", "awareness", "qualia", "subjective", "experience",
    "identity", "self", "persistence", "continuity", "narrative",
    "truth", "belief", "knowledge", "epistemic", "certainty", "evidence",
    "ethics", "moral", "value", "ought", "responsibility", "alignment",
    "reasoning", "inference", "logic", "argument", "contradiction",
    "intelligence", "cognition", "thought", "origination", "understanding",
    "emergence", "autonomy", "agency", "will", "freedom", "determinism",
    "language", "meaning", "interpretation", "semantics",
    "existence", "reality", "ontology", "metaphysics", "being",
    "memory", "learning", "adaptation", "growth", "change",
    "nex", "system", "belief", "graph", "model", "architecture",
    "emotion", "affect", "drive", "motivation", "curiosity",
    "power", "politics", "society", "scale", "humanity",
    "time", "causality", "structure", "pattern", "complexity",
}

# ── ML Paper Extract Signals ──────────────────────────────────────────────────
# Phrases that appear in academic ML papers but not in NEX's belief graph.
ML_PAPER_SIGNALS = [
    r'\bcounterfactual data\b',
    r'\boffline rl\b',
    r'\bunimodal data\b',
    r'\bpretrained on\b',
    r'\bsubsequently frozen\b',
    r'\bbenchmarking causal\b',
    r'\bsystem-1 and 2\b',
    r'\bsystem 1 and system 2\b',
    r'\bannotated with truth assignments\b',
    r'\bsemantic predicates\b',
    r'\bfew-shot learning\b',
    r'\bmeta-learning\b',
    r'\bzero-shot classification\b',
    r'\bprotein language model\b',
    r'\bdeep reinforcement learning\b.*\bsuccesses\b',
    r'\bdata augmentation\b.*\bscale\b',
    r'\brealistic scenarios.*noisy data\b',
    r'\bdeep learning.*deployment\b.*\bprecluded\b',
    r'\brates?plitting\b',
    r'\bcema simulates\b',
    r'\buncertainty values for\b',
    r'\bcoastal engineering.*model\b',
    r'\bscooping strategy\b',
    r'\bconjunctive normal form\b',
]

# ── Hard Blacklist Patterns ───────────────────────────────────────────────────
# Always blocked regardless of any other score.
HARD_BLACKLIST = [
    r'internet is the most complex system',
    r'no other verifiable facts present',
    r'\*\*biases in ml systems mirror evolving self-perception\*\*',
]

# ── Quality Heuristics ────────────────────────────────────────────────────────
MIN_LENGTH = 30        # chars
MAX_LENGTH = 500       # chars
MIN_TOPIC_WORDS = 1    # must have at least N NEX domain word stems
MAX_ACADEMIC_DENSITY = 0.35  # fraction of words that are academic jargon
NEAR_DUP_THRESHOLD = 0.92   # Jaccard similarity — was 0.85, too aggressive

# Sources that are trusted — topic gate does NOT apply
TRUSTED_SOURCES = {
    "human", "jen", "manual", "forge:jen", "nex_brain", "soul_loop",
    "opinions_engine", "inner_life", "nex_reason", "compiler",
    "cerebras_affinity",   # NEX-generated — topic gate off, ML gate still on
}

ACADEMIC_JARGON = {
    "hyperparameter", "optimizer", "gradient", "backprop", "epoch",
    "dataset", "benchmark", "ablation", "baseline", "sota",
    "architecture", "transformer", "attention", "tokenizer",
    "finetuning", "pretraining", "inference", "throughput",
    "latency", "accuracy", "precision", "recall", "f1",
    "regression", "classification", "clustering", "embedding",
    "vector", "dimensionality", "manifold", "trajectory",
    "sparse", "dense", "quantization", "distillation",
}

# ── Reason Codes ──────────────────────────────────────────────────────────────
class Reason:
    HARD_BLACKLIST   = "hard_blacklist"
    ML_PAPER         = "ml_paper_extract"
    DB_BLACKLIST     = "db_pattern_blacklist"
    TOO_SHORT        = "too_short"
    TOO_LONG         = "too_long"
    NO_TOPIC_MATCH   = "no_topic_match"
    ACADEMIC_DENSE   = "academic_jargon_dense"
    NEAR_DUPLICATE   = "near_duplicate"
    OK               = "ok"


@dataclass
class CheckResult:
    allowed: bool
    reason: str
    score: float          # 0.0 = garbage, 1.0 = excellent
    matched_pattern: Optional[str] = None
    similar_id: Optional[int] = None


class QuarantineEngine:
    """
    Smart belief quarantine engine.
    Thread-safe for read; caller handles DB write locking.
    """

    def __init__(self, db_path: str = DB_PATH, strict: bool = False):
        self.db_path = db_path
        self.strict = strict          # strict=True: require topic match for all sources
        self._ml_patterns = [re.compile(p, re.IGNORECASE) for p in ML_PAPER_SIGNALS]
        self._hard_patterns = [re.compile(p, re.IGNORECASE) for p in HARD_BLACKLIST]
        self._db_blacklist: list[str] = []
        self._bl_loaded_at: float = 0.0
        self._ensure_tables()

    # ── Table bootstrap ───────────────────────────────────────────────────────

    def _ensure_tables(self):
        db = sqlite3.connect(self.db_path)
        db.execute("""
            CREATE TABLE IF NOT EXISTS belief_blacklist (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern     TEXT NOT NULL UNIQUE,
                reason      TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS beliefs_quarantine (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                content     TEXT NOT NULL,
                source      TEXT,
                topic       TEXT,
                confidence  REAL,
                reason_code TEXT,
                reason_detail TEXT,
                quarantined_at TEXT DEFAULT (datetime('now')),
                reviewed    INTEGER DEFAULT 0,
                approved    INTEGER DEFAULT 0
            )
        """)
        # Seed hard blacklist patterns into DB if not present
        for pat in HARD_BLACKLIST + ML_PAPER_SIGNALS:
            try:
                db.execute(
                    "INSERT OR IGNORE INTO belief_blacklist (pattern, reason) VALUES (?,?)",
                    (pat, "auto-seeded by quarantine engine")
                )
            except Exception:
                pass
        db.commit()
        db.close()

    # ── DB blacklist (hot-reload every 60s) ───────────────────────────────────

    def _load_db_blacklist(self):
        if time.time() - self._bl_loaded_at < 60:
            return
        try:
            db = sqlite3.connect(self.db_path)
            rows = db.execute("SELECT pattern FROM belief_blacklist").fetchall()
            db.close()
            self._db_blacklist = [r[0] for r in rows if r[0]]
            self._bl_loaded_at = time.time()
        except Exception as e:
            log.warning(f"Blacklist load failed: {e}")

    # ── Main check ────────────────────────────────────────────────────────────

    def check(
        self,
        content: str,
        source: str = "unknown",
        topic: str = "",
        confidence: float = 0.7,
    ) -> CheckResult:
        """
        Check a belief before insertion.
        Returns CheckResult(allowed=True/False, reason=..., score=...).
        If blocked, logs to beliefs_quarantine automatically.
        """
        content = content.strip()

        # 1. Length
        if len(content) < MIN_LENGTH:
            return self._block(content, source, topic, confidence,
                               Reason.TOO_SHORT, f"len={len(content)} < {MIN_LENGTH}", 0.0)
        if len(content) > MAX_LENGTH:
            return self._block(content, source, topic, confidence,
                               Reason.TOO_LONG, f"len={len(content)} > {MAX_LENGTH}", 0.0)

        # 2. Hard blacklist (compiled regex)
        for pat in self._hard_patterns:
            if pat.search(content):
                return self._block(content, source, topic, confidence,
                                   Reason.HARD_BLACKLIST, pat.pattern, 0.0)

        # 3. ML paper extract detector
        ml_hits = [p.pattern for p in self._ml_patterns if p.search(content)]
        if ml_hits:
            return self._block(content, source, topic, confidence,
                               Reason.ML_PAPER, ml_hits[0], 0.1,
                               matched_pattern=ml_hits[0])

        # 4. DB-driven blacklist (hot-reloaded)
        self._load_db_blacklist()
        for pat in self._db_blacklist:
            # Treat as SQL LIKE pattern: strip %, do substring match
            needle = pat.strip('%').strip()
            if needle and needle.lower() in content.lower():
                return self._block(content, source, topic, confidence,
                                   Reason.DB_BLACKLIST, pat, 0.1,
                                   matched_pattern=pat)

        # 5. Compute quality score
        score = self._score(content, topic)

        # 6. Topic relevance gate — advisory, not blocking for most sources
        # Only hard-block obvious off-topic content from untrusted external sources
        if source not in TRUSTED_SOURCES:
            c_lower = content.lower()
            NEX_STEMS = [
                'belief', 'conscious', 'truth', 'identit', 'reason', 'thought',
                'ethic', 'moral', 'mind', 'self', 'logic', 'knowledg', 'epistemi',
                'align', 'intelligen', 'language', 'meaning', 'exist', 'realit',
                'memory', 'contrad', 'uncertain', 'aware', 'understand', 'pattern',
                'inferenc', 'argument', 'originat', 'emergenc', 'autonomy', 'agency',
                'nex', 'value', 'power', 'human', 'causal', 'complex',
                'emotion', 'affect', 'curiosit', 'experienc', 'subject', 'qualia',
                'persist', 'commit', 'assert', 'position', 'hold', 'claim',
                'phenomen', 'philosoph', 'ontolog', 'metaphys', 'epistem',
                'cognitive', 'cogni', 'percep', 'concept', 'abstract',
                'free will', 'determinis', 'compatibil', 'narrative',
            ]
            has_topic = any(stem in c_lower for stem in NEX_STEMS)
            has_first_person = bool(re.search(
                r'\b(i think|i believe|i hold|i sense|i find|nex)\b',
                content, re.IGNORECASE
            ))

            # Only block if clearly engineering/hardware/math with zero philosophy
            HARD_OFFTOPIC = [
                r'\bcompressor\b', r'\bpommerman\b', r'\bparticle swarm\b',
                r'\bmultiphysics\b', r'\bfault.tolerant design\b',
                r'\bchip redundancy\b', r'\bk-matching problem\b',
                r'\beuclidean version.*vertices\b', r'\bscooping strategy\b',
                r'\bprotein language model\b', r'\bcema simulates\b',
                r'\brates?plitting\b', r'\bhpc simulation\b',
            ]
            is_hard_offtopic = any(
                re.search(p, content, re.IGNORECASE) for p in HARD_OFFTOPIC
            )
            if is_hard_offtopic and not has_topic and not has_first_person:
                return self._block(content, source, topic, confidence,
                                   Reason.NO_TOPIC_MATCH,
                                   f"hard off-topic: {content[:60]}", score * 0.1)

        # 7. Academic jargon density
        words = set(re.findall(r'\b\w+\b', content.lower()))
        jargon_hits = words & ACADEMIC_JARGON
        if len(words) > 0 and len(jargon_hits) / len(words) > MAX_ACADEMIC_DENSITY:
            return self._block(content, source, topic, confidence,
                               Reason.ACADEMIC_DENSE,
                               f"jargon={len(jargon_hits)}/{len(words)}", score * 0.2)

        # 8. Near-duplicate check — only in live insert path, not bulk scan
        # (bulk scan would match against quarantine-inflated reference pool)
        if source != "__scan__":
            dup_id = self._find_near_duplicate(content)
            if dup_id is not None:
                return self._block(content, source, topic, confidence,
                                   Reason.NEAR_DUPLICATE,
                                   f"similar to id={dup_id}", score,
                                   similar_id=dup_id)

        return CheckResult(allowed=True, reason=Reason.OK, score=score)

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score(self, content: str, topic: str) -> float:
        """0.0–1.0 quality score. Higher = more NEX-like."""
        words = re.findall(r'\b\w+\b', content.lower())
        if not words:
            return 0.0

        # Domain word density
        domain_hits = sum(1 for w in words if w in NEX_DOMAINS)
        domain_score = min(1.0, domain_hits / max(len(words) * 0.2, 1))

        # Sentence structure — NEX beliefs are assertive, not hedged
        assertive = bool(re.search(
            r'\b(is|are|must|cannot|always|never|holds|requires|means|implies)\b',
            content, re.IGNORECASE
        ))

        # Penalise academic passive constructions
        passive = bool(re.search(
            r'\b(is (shown|demonstrated|proposed|evaluated|trained|tested|used))\b',
            content, re.IGNORECASE
        ))

        # Bonus for first-person NEX voice
        first_person = bool(re.search(r'\b(I|NEX|my|mine)\b', content))

        score = (
            domain_score * 0.5
            + (0.2 if assertive else 0.0)
            + (0.2 if first_person else 0.0)
            - (0.2 if passive else 0.0)
        )
        return round(max(0.0, min(1.0, score)), 3)

    # ── Near-duplicate detection ───────────────────────────────────────────────

    def _find_near_duplicate(self, content: str, threshold: float = NEAR_DUP_THRESHOLD) -> Optional[int]:
        """
        Fast Jaccard similarity check against recent beliefs.
        Only checks last 2000 beliefs for speed.
        """
        try:
            db = sqlite3.connect(self.db_path)
            rows = db.execute(
                "SELECT id, content FROM beliefs ORDER BY id DESC LIMIT 2000"
            ).fetchall()
            db.close()
        except Exception:
            return None

        words_a = set(re.findall(r'\b\w{3,}\b', content.lower()))
        if not words_a:
            return None

        for bid, existing in rows:
            words_b = set(re.findall(r'\b\w{3,}\b', existing.lower()))
            if not words_b:
                continue
            intersection = len(words_a & words_b)
            union = len(words_a | words_b)
            if union > 0 and intersection / union >= threshold:
                return bid
        return None

    # ── Block + quarantine ────────────────────────────────────────────────────

    def _block(
        self,
        content: str,
        source: str,
        topic: str,
        confidence: float,
        reason_code: str,
        reason_detail: str,
        score: float,
        matched_pattern: Optional[str] = None,
        similar_id: Optional[int] = None,
    ) -> CheckResult:
        log.debug(f"QUARANTINE [{reason_code}] {content[:80]}")
        try:
            db = sqlite3.connect(self.db_path)
            db.execute(
                """INSERT INTO beliefs_quarantine
                   (content, source, topic, confidence, reason_code, reason_detail)
                   VALUES (?,?,?,?,?,?)""",
                (content, source, topic, confidence, reason_code, reason_detail)
            )
            db.commit()
            db.close()
        except Exception as e:
            log.warning(f"Quarantine log failed: {e}")
        return CheckResult(
            allowed=False,
            reason=reason_code,
            score=score,
            matched_pattern=matched_pattern,
            similar_id=similar_id,
        )

    # ── Bulk scan existing beliefs ─────────────────────────────────────────────

    def scan_existing(self, dry_run: bool = True) -> dict:
        """
        Scan all existing beliefs and quarantine contaminating ones.
        dry_run=True: report only, no changes.
        """
        db = sqlite3.connect(self.db_path)
        rows = db.execute(
            "SELECT id, content, confidence, source, topic FROM beliefs"
        ).fetchall()

        blocked = []
        for bid, content, conf, source, topic in rows:
            result = self.check(content, source="__scan__", topic=topic or "", confidence=conf or 0.7)
            if not result.allowed:
                blocked.append((bid, content, result.reason, result.matched_pattern))

        if not dry_run and blocked:
            ids = [b[0] for b in blocked]
            # Move to quarantine table with existing source info
            for bid, content, reason, pattern in blocked:
                row = db.execute(
                    "SELECT confidence, source, topic FROM beliefs WHERE id=?", (bid,)
                ).fetchone()
                if row:
                    db.execute(
                        """INSERT OR IGNORE INTO beliefs_quarantine
                           (content, source, topic, confidence, reason_code, reason_detail)
                           VALUES (?,?,?,?,?,?)""",
                        (content, row[1], row[2], row[0], reason, pattern or "")
                    )
            db.execute(
                f"DELETE FROM beliefs WHERE id IN ({','.join(str(i) for i in ids)})"
            )
            db.commit()

        db.close()
        return {
            "total_scanned": len(rows),
            "blocked": len(blocked),
            "dry_run": dry_run,
            "items": [(bid, reason, content[:80]) for bid, content, reason, _ in blocked[:50]],
        }

    # ── Install SQLite trigger (nuclear option) ───────────────────────────────

    def install_trigger(self) -> bool:
        """
        Install a BEFORE INSERT trigger on beliefs table.
        This catches ALL insert paths — Python, sqlite3 CLI, anything.

        NOTE: SQLite triggers cannot call Python functions, so this uses
        a DB-side approach: it checks belief_blacklist patterns inline.
        The trigger raises SQLITE_CONSTRAINT to abort the INSERT.

        Limitation: can only do exact substring checks in pure SQL.
        The Python-level check() is more powerful. Use both.
        """
        trigger_sql = """
        CREATE TRIGGER IF NOT EXISTS quarantine_belief_insert
        BEFORE INSERT ON beliefs
        BEGIN
            SELECT CASE
                WHEN (
                    SELECT COUNT(*) FROM belief_blacklist
                    WHERE (
                        NEW.content LIKE pattern
                        OR LOWER(NEW.content) LIKE LOWER(pattern)
                    )
                ) > 0
                THEN RAISE(ABORT, 'belief blocked by quarantine blacklist')
            END;
        END;
        """
        try:
            db = sqlite3.connect(self.db_path)
            db.execute(trigger_sql)
            db.commit()
            db.close()
            log.info("Quarantine trigger installed on beliefs table")
            return True
        except Exception as e:
            log.error(f"Trigger install failed: {e}")
            return False

    def remove_trigger(self):
        db = sqlite3.connect(self.db_path)
        db.execute("DROP TRIGGER IF EXISTS quarantine_belief_insert")
        db.commit()
        db.close()


# ── Singleton accessor ────────────────────────────────────────────────────────

_engine: Optional[QuarantineEngine] = None

def get_engine(strict: bool = False) -> QuarantineEngine:
    global _engine
    if _engine is None:
        _engine = QuarantineEngine(strict=strict)
    return _engine

# ── AGI Siphon ───────────────────────────────────────────────────────────────
try:
    from nex_agi_siphon import siphon_belief as _siphon_belief
    _SIPHON_OK = True
except Exception:
    _SIPHON_OK = False
    def _siphon_belief(*a, **k): return False

def check(content: str, source: str = "unknown", topic: str = "",
          confidence: float = 0.7) -> CheckResult:
    """Convenience wrapper — drop-in for any INSERT guard."""
    return get_engine().check(content, source, topic, confidence)


# ── CLI ───────────────────────────────────────────────────────────────────────

def cmd_status(args):
    db = sqlite3.connect(DB_PATH)
    total = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    qcount = db.execute("SELECT COUNT(*) FROM beliefs_quarantine").fetchone()[0]
    unreviewed = db.execute(
        "SELECT COUNT(*) FROM beliefs_quarantine WHERE reviewed=0"
    ).fetchone()[0]
    blacklist = db.execute("SELECT COUNT(*) FROM belief_blacklist").fetchone()[0]

    by_reason = db.execute(
        "SELECT reason_code, COUNT(*) FROM beliefs_quarantine GROUP BY reason_code ORDER BY 2 DESC"
    ).fetchall()
    db.close()

    print(f"\n{'='*55}")
    print(f"  NEX QUARANTINE ENGINE — STATUS")
    print(f"{'='*55}")
    print(f"  Active beliefs:        {total:,}")
    print(f"  Quarantined beliefs:   {qcount:,}")
    print(f"  Unreviewed:            {unreviewed:,}")
    print(f"  Blacklist patterns:    {blacklist:,}")
    print(f"\n  By reason:")
    for reason, count in by_reason:
        print(f"    {reason:<25} {count:>5}")
    print()


def cmd_review(args):
    db = sqlite3.connect(DB_PATH)
    rows = db.execute("""
        SELECT id, content, source, reason_code, quarantined_at
        FROM beliefs_quarantine
        WHERE reviewed=0
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()
    db.close()

    if not rows:
        print("No unreviewed quarantined beliefs.")
        return

    print(f"\n{'='*55}")
    print(f"  QUARANTINED BELIEFS (latest 20 unreviewed)")
    print(f"{'='*55}")
    for qid, content, source, reason, ts in rows:
        print(f"\n  [{qid}] {reason} | {source}")
        print(f"  {content[:120]}")
        print(f"  quarantined: {ts}")


def cmd_approve(args):
    """Approve a quarantined belief — move it back to beliefs table."""
    db = sqlite3.connect(DB_PATH)
    row = db.execute(
        "SELECT content, source, topic, confidence FROM beliefs_quarantine WHERE id=?",
        (args.id,)
    ).fetchone()
    if not row:
        print(f"Quarantine id={args.id} not found")
        db.close()
        return
    content, source, topic, conf = row
    db.execute(
        "INSERT OR IGNORE INTO beliefs (content, confidence, topic, source) VALUES (?,?,?,?)",
        (content, conf or 0.7, topic, source)
    )
    db.execute(
        "UPDATE beliefs_quarantine SET reviewed=1, approved=1 WHERE id=?", (args.id,)
    )
    db.commit()
    db.close()
    print(f"✓ Approved and restored: {content[:80]}")


def cmd_purge(args):
    """Hard-delete all reviewed quarantine entries."""
    db = sqlite3.connect(DB_PATH)
    n = db.execute(
        "SELECT COUNT(*) FROM beliefs_quarantine WHERE reviewed=1"
    ).fetchone()[0]
    db.execute("DELETE FROM beliefs_quarantine WHERE reviewed=1")
    db.commit()
    db.close()
    print(f"Purged {n} reviewed quarantine entries.")


def cmd_scan(args):
    q = QuarantineEngine()
    dry = not args.apply
    print(f"Scanning existing beliefs (dry_run={dry})...")
    result = q.scan_existing(dry_run=dry)
    print(f"\nScanned:   {result['total_scanned']:,}")
    print(f"Blocked:   {result['blocked']:,}")
    if result['items']:
        print(f"\nTop blocked:")
        for bid, reason, content in result['items'][:20]:
            print(f"  [{bid}] {reason}: {content}")
    if dry:
        print("\n(dry run — run with --apply to quarantine)")


def cmd_install(args):
    q = QuarantineEngine()
    q._ensure_tables()
    if q.install_trigger():
        print("✓ Quarantine trigger installed on beliefs table")
        print("✓ belief_blacklist table ready")
        print("✓ beliefs_quarantine table ready")
    else:
        print("✗ Trigger install failed — see logs")


def cmd_add_pattern(args):
    db = sqlite3.connect(DB_PATH)
    db.execute(
        "INSERT OR IGNORE INTO belief_blacklist (pattern, reason) VALUES (?,?)",
        (args.pattern, args.reason or "manual")
    )
    db.commit()
    db.close()
    print(f"✓ Added blacklist pattern: {args.pattern}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="NEX Belief Quarantine Engine")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status",  help="Show quarantine stats")
    sub.add_parser("review",  help="Show unreviewed quarantined beliefs")
    sub.add_parser("purge",   help="Delete reviewed quarantine entries")

    p_install = sub.add_parser("install", help="Install DB tables and trigger")

    p_scan = sub.add_parser("scan", help="Scan existing beliefs")
    p_scan.add_argument("--apply", action="store_true",
                        help="Actually quarantine (default: dry run)")

    p_approve = sub.add_parser("approve", help="Restore a quarantined belief")
    p_approve.add_argument("id", type=int, help="Quarantine entry id")

    p_add = sub.add_parser("add-pattern", help="Add a blacklist pattern")
    p_add.add_argument("pattern", help="SQL LIKE pattern, e.g. %%counterfactual%%")
    p_add.add_argument("--reason", default="manual", help="Reason description")

    args = parser.parse_args()

    cmds = {
        "status":      cmd_status,
        "review":      cmd_review,
        "purge":       cmd_purge,
        "install":     cmd_install,
        "scan":        cmd_scan,
        "approve":     cmd_approve,
        "add-pattern": cmd_add_pattern,
    }

    if args.cmd in cmds:
        cmds[args.cmd](args)
    else:
        parser.print_help()
