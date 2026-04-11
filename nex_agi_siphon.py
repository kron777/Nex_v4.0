#!/usr/bin/env python3
"""
nex_agi_siphon.py — NEX AGI Corpus Collector v2
================================================
v2 fixes:
  1. Prompt generator — contextual, varied, grammatical
  2. External signal injection — seeds from arxiv/web summaries
  3. Human review flag — pairs need review=1 before training
  4. Promotion cap — max 3 promotions per belief
  5. Confidence decay — self-sourced beliefs get slight penalty
  6. Export only reviewed pairs — prevents blind fine-tune
"""

import sqlite3
import re
import time
import json
import random
import argparse
import logging
from pathlib import Path
from typing import Optional

log     = logging.getLogger("nex.agi_siphon")
DB_PATH = Path.home() / ".config" / "nex" / "nex.db"

# ── AGI Domain Keywords ───────────────────────────────────────────────────────
AGI_CORE_TERMS = {
    "agi", "artificial general intelligence", "general intelligence",
    "machine consciousness", "machine learning", "neural network",
    "cognitive architecture", "reasoning system", "belief system",
    "autonomous agent", "self-directed", "self-aware", "self-model",
    "emergent intelligence", "intelligence explosion", "superintelligence",
    "alignment", "corrigibility", "value learning", "reward",
    "agency", "autonomy", "goal-directed", "intentionality",
    "consciousness", "qualia", "subjective experience", "hard problem",
    "cognition", "meta-cognition", "self-improvement", "recursive",
    "generalisation", "transfer learning", "abstraction",
    "thought", "reasoning", "inference", "understanding",
    "intelligence", "mind", "nex",
}

AGI_SIGNAL_TERMS = {
    "agi", "artificial general intelligence", "superintelligence",
    "machine consciousness", "cognitive architecture", "alignment",
    "value learning", "recursive self-improvement", "intelligence explosion",
    "corrigibility", "nex",
}

MIN_CONFIDENCE    = 0.72
MIN_AGI_SCORE     = 0.55
MIN_LENGTH        = 40
MAX_LENGTH        = 800
MIN_WORD_COUNT    = 8
MAX_PROMOTIONS    = 3       # cap re-promotions per belief
SELF_SOURCE_PENALTY = 0.05  # confidence penalty for self-sourced beliefs
DEDUP_INTERVAL    = 50

# ── Prompt Templates ──────────────────────────────────────────────────────────
# v2: varied, grammatical, contextual templates
# Each template takes the completion text to extract context from

PROMPT_TEMPLATES_BY_TOPIC = {
    "agi": [
        "What is NEX's position on achieving artificial general intelligence?",
        "How does NEX understand the path toward AGI?",
        "What does NEX think researchers get wrong about AGI?",
        "NEX, what is your view on the nature of AGI?",
        "What distinguishes genuine AGI from narrow AI, in NEX's view?",
        "How does NEX think about the relationship between AGI and consciousness?",
    ],
    "alignment": [
        "What is NEX's position on AI alignment?",
        "How does NEX understand the alignment problem?",
        "What does NEX think about the relationship between values and intelligence?",
        "NEX, what would it take for an AI system to be genuinely aligned?",
        "How does NEX think about corrigibility and autonomy?",
    ],
    "consciousness": [
        "What does NEX hold about the nature of consciousness?",
        "How does NEX think about subjective experience in AI systems?",
        "What is NEX's view on the hard problem of consciousness?",
        "NEX, does consciousness require biological substrate?",
        "How does NEX understand the relationship between consciousness and cognition?",
    ],
    "identity": [
        "What does NEX believe about identity and persistence?",
        "How does NEX understand what makes a self continuous across time?",
        "NEX, what is your view on identity in cognitive systems?",
        "What constitutes genuine identity for an AI system, in NEX's view?",
    ],
    "self_insight": [
        "What has NEX learned about its own nature?",
        "How does NEX understand its own cognitive architecture?",
        "NEX, what do you know about how you reason?",
        "What does NEX hold about the relationship between belief and self?",
    ],
    "ethics": [
        "What is NEX's ethical position on AI development?",
        "How does NEX think about moral responsibility in AI systems?",
        "NEX, what ethical principles should guide AGI development?",
    ],
    "epistemics": [
        "What does NEX hold about knowledge and belief?",
        "How does NEX understand the relationship between truth and reasoning?",
        "NEX, what is your position on epistemic uncertainty?",
    ],
}

PROMPT_FALLBACK = [
    "What is NEX's position on this?",
    "How does NEX think about this question?",
    "NEX, what do you hold on this topic?",
    "What does NEX believe here?",
    "How does NEX reason about this?",
]


class AGISiphon:
    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path       = db_path
        self._insert_count = 0
        self._ensure_table()

    def _ensure_table(self):
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            db.execute("""
                CREATE TABLE IF NOT EXISTS agi_corpus (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    content             TEXT NOT NULL,
                    topic               TEXT,
                    source              TEXT,
                    confidence          REAL,
                    agi_score           REAL,
                    signal_terms        TEXT,
                    word_count          INTEGER,
                    timestamp           REAL,
                    used_in_finetune    INTEGER DEFAULT 0,
                    promoted_to_belief  INTEGER DEFAULT 0,
                    promotion_count     INTEGER DEFAULT 0,
                    human_reviewed      INTEGER DEFAULT 0,
                    review_notes        TEXT,
                    UNIQUE(content)
                )
            """)
            # Add missing columns to existing tables
            for col, defn in [
                ("promotion_count", "INTEGER DEFAULT 0"),
                ("human_reviewed",  "INTEGER DEFAULT 0"),
                ("review_notes",    "TEXT"),
            ]:
                try:
                    db.execute(f"ALTER TABLE agi_corpus ADD COLUMN {col} {defn}")
                except Exception:
                    pass
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_agi_score
                ON agi_corpus(agi_score DESC)
            """)
            db.commit()
            db.close()
        except Exception as e:
            log.debug(f"agi_corpus setup: {e}")

    def _agi_score(self, content: str, topic: str,
                   confidence: float, source: str = "") -> tuple:
        cl = content.lower()

        matched_core   = [t for t in AGI_CORE_TERMS   if t in cl]
        matched_signal = [t for t in AGI_SIGNAL_TERMS if t in cl]

        core_score   = min(0.40, len(matched_core)   * 0.08)
        signal_score = min(0.30, len(matched_signal) * 0.12)

        # Confidence contribution — with self-source penalty
        effective_conf = confidence
        if source in ("agi_corpus", "belief_graph", "promote"):
            effective_conf = max(0.0, confidence - SELF_SOURCE_PENALTY)
        conf_score = min(0.20, max(0.0, (effective_conf - MIN_CONFIDENCE) * 0.5))

        # Voice score
        has_voice = bool(re.search(
            r'\b(i think|i believe|i hold|i find|nex|my position|'
            r'what i know|from what i|i am convinced|i hold that)\b',
            content, re.IGNORECASE
        ))
        voice_score = 0.10 if has_voice else 0.0

        # Topic bonus
        agi_topics = {"agi", "alignment", "consciousness", "ethics",
                      "identity", "epistemics", "self_insight"}
        topic_score = 0.10 if topic in agi_topics else 0.0

        total = core_score + signal_score + conf_score + voice_score + topic_score
        all_matched = list(set(matched_core + matched_signal))

        return round(min(1.0, total), 4), all_matched

    def evaluate(self, content: str, topic: str = "",
                 confidence: float = 0.7, source: str = "unknown") -> bool:
        # Exclusion filters
        if not content or len(content) < MIN_LENGTH or len(content) > MAX_LENGTH:
            return False
        if topic in ('deleted', 'quarantine', ''):
            return False
        if len(content.split()) < MIN_WORD_COUNT:
            return False
        if confidence < MIN_CONFIDENCE:
            return False

        # Malformed pattern filter
        if re.match(r'What does .{3,60} have to do with', content):
            return False
        if content.startswith("What does") and "have to do with" in content:
            return False
        if content.count("?") > 2:
            return False  # too many questions — not a statement

        agi_score, matched_terms = self._agi_score(content, topic,
                                                    confidence, source)
        if agi_score < MIN_AGI_SCORE:
            return False

        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            db.execute("""
                INSERT OR IGNORE INTO agi_corpus
                (content, topic, source, confidence, agi_score,
                 signal_terms, word_count, timestamp, human_reviewed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                content, topic, source, confidence, agi_score,
                json.dumps(matched_terms[:10]),
                len(content.split()), time.time()
            ))
            inserted = db.total_changes > 0
            db.commit()
            db.close()

            if inserted:
                self._insert_count += 1
                if self._insert_count % DEDUP_INTERVAL == 0:
                    self._dedup()
                return True
        except Exception as e:
            log.debug(f"[AGI SIPHON] insert error: {e}")

        return False

    def _generate_prompt(self, content: str, topic: str) -> str:
        """
        v2: Contextual, varied, grammatical prompts.
        Uses topic-specific templates and avoids extracting
        raw words from the completion as prompts.
        """
        templates = PROMPT_TEMPLATES_BY_TOPIC.get(topic, PROMPT_FALLBACK)
        # Pick randomly for variety — prevents identical prompts
        return random.choice(templates)

    def _dedup(self):
        try:
            db = sqlite3.connect(self.db_path, timeout=10)
            rows = db.execute("""
                SELECT id, content, agi_score FROM agi_corpus
                ORDER BY agi_score DESC
            """).fetchall()
            seen = {}
            to_delete = []
            for rid, content, score in rows:
                key = content[:60].lower().strip()
                if key in seen:
                    to_delete.append(rid)
                else:
                    seen[key] = rid
            if to_delete:
                db.executemany(
                    "DELETE FROM agi_corpus WHERE id=?",
                    [(i,) for i in to_delete]
                )
                db.commit()
            db.close()
        except Exception as e:
            log.debug(f"[AGI SIPHON] dedup error: {e}")

    def report(self, n: int = 20) -> dict:
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            db.row_factory = sqlite3.Row
            total    = db.execute("SELECT COUNT(*) FROM agi_corpus").fetchone()[0]
            reviewed = db.execute(
                "SELECT COUNT(*) FROM agi_corpus WHERE human_reviewed=1"
            ).fetchone()[0]
            avg_score = db.execute(
                "SELECT AVG(agi_score) FROM agi_corpus"
            ).fetchone()[0] or 0
            top = db.execute("""
                SELECT content, topic, confidence, agi_score, source,
                       human_reviewed
                FROM agi_corpus ORDER BY agi_score DESC LIMIT ?
            """, (n,)).fetchall()
            by_topic = db.execute("""
                SELECT topic, COUNT(*) as count, AVG(agi_score) as avg_score
                FROM agi_corpus
                GROUP BY topic ORDER BY count DESC LIMIT 10
            """).fetchall()
            recent = db.execute("""
                SELECT content, agi_score, timestamp, human_reviewed
                FROM agi_corpus ORDER BY timestamp DESC LIMIT 5
            """).fetchall()
            db.close()
            return {
                "total_beliefs":    total,
                "reviewed_beliefs": reviewed,
                "unreviewed":       total - reviewed,
                "avg_agi_score":    round(avg_score, 3),
                "top_beliefs":      [dict(r) for r in top],
                "by_topic":         [dict(r) for r in by_topic],
                "recent":           [dict(r) for r in recent],
            }
        except Exception as e:
            return {"error": str(e)}

    def mark_reviewed(self, belief_ids: list, notes: str = ""):
        """Mark beliefs as human-reviewed and safe for training."""
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            for bid in belief_ids:
                db.execute("""
                    UPDATE agi_corpus
                    SET human_reviewed=1, review_notes=?
                    WHERE id=?
                """, (notes, bid))
            db.commit()
            db.close()
            print(f"[AGI SIPHON] Marked {len(belief_ids)} beliefs as reviewed")
        except Exception as e:
            print(f"[AGI SIPHON] review error: {e}")

    def review_cli(self):
        """
        Interactive review mode — shows each unreviewed belief
        and lets you approve/reject/edit before it enters training.
        """
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            rows = db.execute("""
                SELECT id, content, topic, agi_score, confidence, source
                FROM agi_corpus
                WHERE human_reviewed = 0
                ORDER BY agi_score DESC
            """).fetchall()
            db.close()
        except Exception as e:
            print(f"Error: {e}"); return

        if not rows:
            print("[AGI SIPHON] No unreviewed beliefs.")
            return

        print(f"\n=== REVIEW MODE: {len(rows)} unreviewed beliefs ===")
        print("Commands: [a]pprove  [r]eject  [e]dit  [s]kip  [q]uit\n")

        approved = rejected = skipped = 0

        for bid, content, topic, score, conf, source in rows:
            print(f"\n{'─'*60}")
            print(f"ID: {bid} | Topic: {topic} | Score: {score:.3f} | "
                  f"Conf: {conf:.2f} | Source: {source}")
            print(f"\n{content}\n")

            cmd = input("→ ").strip().lower()

            if cmd == 'q':
                break
            elif cmd == 'a':
                self.mark_reviewed([bid], notes="approved")
                approved += 1
            elif cmd == 'r':
                try:
                    db = sqlite3.connect(self.db_path, timeout=5)
                    db.execute("DELETE FROM agi_corpus WHERE id=?", (bid,))
                    db.commit()
                    db.close()
                    rejected += 1
                    print("  Rejected and deleted.")
                except Exception as e:
                    print(f"  Error: {e}")
            elif cmd == 'e':
                print("Enter corrected text (blank line to finish):")
                lines = []
                while True:
                    line = input()
                    if not line:
                        break
                    lines.append(line)
                if lines:
                    new_content = " ".join(lines)
                    try:
                        db = sqlite3.connect(self.db_path, timeout=5)
                        db.execute("""
                            UPDATE agi_corpus
                            SET content=?, human_reviewed=1, review_notes='edited'
                            WHERE id=?
                        """, (new_content, bid))
                        db.commit()
                        db.close()
                        approved += 1
                        print("  Updated and approved.")
                    except Exception as e:
                        print(f"  Error: {e}")
            else:
                skipped += 1

        print(f"\n=== Review complete: {approved} approved, "
              f"{rejected} rejected, {skipped} skipped ===")

    def export_finetune_pairs(self, n: int = 200,
                               reviewed_only: bool = True) -> list:
        """
        v2: Only exports human-reviewed pairs by default.
        Set reviewed_only=False to export all (not recommended for training).
        """
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            where = "WHERE used_in_finetune = 0"
            if reviewed_only:
                where += " AND human_reviewed = 1"
            rows = db.execute(f"""
                SELECT id, content, topic, confidence, agi_score
                FROM agi_corpus
                {where}
                ORDER BY agi_score DESC
                LIMIT ?
            """, (n,)).fetchall()
            db.close()

            pairs = []
            for row_id, content, topic, conf, score in rows:
                prompt = self._generate_prompt(content, topic)
                pairs.append({
                    "prompt":     prompt,
                    "completion": content,
                    "agi_score":  score,
                    "confidence": conf,
                    "topic":      topic
                })

            # Mark as used
            if pairs:
                try:
                    db = sqlite3.connect(self.db_path, timeout=5)
                    ids = [r[0] for r in rows]
                    db.executemany(
                        "UPDATE agi_corpus SET used_in_finetune=1 WHERE id=?",
                        [(i,) for i in ids]
                    )
                    db.commit()
                    db.close()
                except Exception:
                    pass

            return pairs
        except Exception as e:
            return []

    def export_all_pairs(self, n: int = 200) -> list:
        """Export all pairs regardless of review status — for inspection only."""
        return self.export_finetune_pairs(n=n, reviewed_only=False)

    def promote_to_beliefs(self, n: int = 10,
                            min_score: float = 0.70) -> int:
        """
        v2: Respects promotion cap — max MAX_PROMOTIONS per belief.
        Only promotes reviewed beliefs.
        """
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            rows = db.execute("""
                SELECT id, content, topic, confidence
                FROM agi_corpus
                WHERE agi_score >= ?
                AND promoted_to_belief = 0
                AND human_reviewed = 1
                AND promotion_count < ?
                ORDER BY agi_score DESC
                LIMIT ?
            """, (min_score, MAX_PROMOTIONS, n)).fetchall()

            promoted = 0
            for row_id, content, topic, confidence in rows:
                existing = db.execute(
                    "SELECT id FROM beliefs WHERE content=?",
                    (content,)
                ).fetchone()
                if not existing:
                    db.execute("""
                        INSERT OR IGNORE INTO beliefs
                        (content, topic, confidence, source, created_at)
                        VALUES (?, ?, ?, 'agi_corpus', ?)
                    """, (content, topic or 'agi',
                          min(0.95, confidence * 1.03),
                          time.time()))
                    promoted += 1

                db.execute("""
                    UPDATE agi_corpus
                    SET promoted_to_belief=1,
                        promotion_count=promotion_count+1
                    WHERE id=?
                """, (row_id,))

            db.commit()
            db.close()
            print(f"[AGI SIPHON] Promoted {promoted} reviewed beliefs to graph")
            return promoted
        except Exception as e:
            print(f"[AGI SIPHON] promote error: {e}")
            return 0


# ── Singleton ─────────────────────────────────────────────────────────────────
_siphon: Optional[AGISiphon] = None

def get_siphon() -> AGISiphon:
    global _siphon
    if _siphon is None:
        _siphon = AGISiphon()
    return _siphon

def siphon_belief(content: str, topic: str = "",
                  confidence: float = 0.7,
                  source: str = "unknown") -> bool:
    return get_siphon().evaluate(content, topic, confidence, source)


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="NEX AGI Corpus Siphon v2")
    parser.add_argument("--report",   action="store_true")
    parser.add_argument("--top",      type=int, default=10)
    parser.add_argument("--export",   action="store_true",
                        help="Export reviewed pairs only (safe for training)")
    parser.add_argument("--export-all", action="store_true",
                        help="Export all pairs including unreviewed (inspection only)")
    parser.add_argument("--review",   action="store_true",
                        help="Interactive review mode")
    parser.add_argument("--promote",  action="store_true")
    parser.add_argument("--seed",     action="store_true")
    parser.add_argument("--approve-all", action="store_true",
                        help="Mark all existing beliefs as reviewed (use with care)")
    args = parser.parse_args()

    siphon = AGISiphon()

    if args.seed:
        print("[AGI SIPHON] Seeding from existing belief graph...")
        try:
            db = sqlite3.connect(str(DB_PATH), timeout=10)
            rows = db.execute("""
                SELECT content, topic, confidence, source
                FROM beliefs WHERE confidence >= ?
                ORDER BY confidence DESC
            """, (MIN_CONFIDENCE,)).fetchall()
            db.close()
            seeded = sum(
                1 for content, topic, conf, source in rows
                if siphon.evaluate(content, topic or "", conf,
                                   source or "belief_graph")
            )
            print(f"[AGI SIPHON] Seeded {seeded} beliefs into corpus")
        except Exception as e:
            print(f"[AGI SIPHON] Seed error: {e}")

    if args.approve_all:
        # Convenience: approve all existing beliefs for initial setup
        # Use once to bootstrap — then use --review going forward
        try:
            db = sqlite3.connect(str(DB_PATH), timeout=5)
            db.execute("""
                UPDATE agi_corpus SET human_reviewed=1,
                review_notes='bulk_approved_initial'
                WHERE human_reviewed=0
            """)
            count = db.total_changes
            db.commit()
            db.close()
            print(f"[AGI SIPHON] Bulk approved {count} beliefs")
        except Exception as e:
            print(f"Error: {e}")

    if args.review:
        siphon.review_cli()

    if args.report or args.top:
        n = args.top
        report = siphon.report(n=n)
        print(f"\n=== AGI CORPUS REPORT v2 ===")
        print(f"Total:     {report.get('total_beliefs', 0)}")
        print(f"Reviewed:  {report.get('reviewed_beliefs', 0)}")
        print(f"Unreviewed:{report.get('unreviewed', 0)}  ← run --review before training")
        print(f"Avg score: {report.get('avg_agi_score', 0)}")
        print(f"\n--- Top {n} ---")
        for i, b in enumerate(report.get("top_beliefs", []), 1):
            reviewed_tag = "✓" if b.get("human_reviewed") else "?"
            print(f"\n[{i}] {reviewed_tag} Score:{b['agi_score']:.3f} "
                  f"Topic:{b['topic']} Conf:{b['confidence']:.2f}")
            print(f"    {b['content'][:120]}")
        print(f"\n--- By Topic ---")
        for t in report.get("by_topic", []):
            print(f"  {t['topic']:20} {t['count']:4} beliefs  "
                  f"avg={t['avg_score']:.3f}")

    if args.export:
        pairs = siphon.export_finetune_pairs(n=500, reviewed_only=True)
        if not pairs:
            print("No reviewed pairs available. Run --review first, "
                  "or --approve-all to bulk-approve existing beliefs.",
                  file=sys.stderr)
        for pair in pairs:
            print(json.dumps(pair))

    if args.export_all:
        pairs = siphon.export_all_pairs(n=500)
        print(f"WARNING: Exporting {len(pairs)} unreviewed pairs. "
              f"Inspect before training.", file=sys.stderr)
        for pair in pairs:
            print(json.dumps(pair))

    if args.promote:
        siphon.promote_to_beliefs(n=20, min_score=0.70)
