#!/usr/bin/env python3
"""
nex_agi_siphon.py — NEX AGI Corpus Collector
=============================================
Sits alongside the QuarantineEngine. Every belief that passes
quarantine is also evaluated by the AGI siphon. The strongest
AGI-domain beliefs are promoted into a dedicated agi_corpus table.

Over time this builds a profile of NEX's most original, most
connected AGI thinking — usable for:
  - Fine-tune training pairs (NEX teaching herself)
  - Belief injection back into graph (corpus → core beliefs)
  - Profile reports: how NEX's AGI reasoning evolves
  - Evaluating AGI score trajectory

INTEGRATION:
  In nex_quarantine.py, after result = q.check(...):
    if result.allowed:
        from nex_agi_siphon import AGISiphon
        AGISiphon().evaluate(content, topic, confidence, source)

STANDALONE:
  python3 nex_agi_siphon.py --report
  python3 nex_agi_siphon.py --top 20
  python3 nex_agi_siphon.py --export > agi_corpus.jsonl
"""

import sqlite3
import re
import time
import json
import argparse
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

log     = logging.getLogger("nex.agi_siphon")
DB_PATH = Path.home() / ".config" / "nex" / "nex.db"

# ── AGI Domain Keywords ───────────────────────────────────────────────────────
# Beliefs must contain enough of these to qualify as AGI-domain
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

# High-signal AGI terms — one hit from here counts more
AGI_SIGNAL_TERMS = {
    "agi", "artificial general intelligence", "superintelligence",
    "machine consciousness", "cognitive architecture", "alignment",
    "value learning", "recursive self-improvement", "intelligence explosion",
    "corrigibility", "nex",
}

# Minimum thresholds for corpus entry
MIN_CONFIDENCE    = 0.72
MIN_AGI_SCORE     = 0.55
MIN_LENGTH        = 40    # characters
MAX_LENGTH        = 800   # don't store walls of text
MIN_WORD_COUNT    = 8

# How often to run dedup (every N inserts)
DEDUP_INTERVAL    = 50


class AGISiphon:
    """
    Evaluates beliefs for AGI corpus inclusion.
    Instantiate once, call evaluate() on each passing belief.
    """

    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path     = db_path
        self._insert_count = 0
        self._ensure_table()

    def _ensure_table(self):
        """Create agi_corpus table if not exists."""
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            db.execute("""
                CREATE TABLE IF NOT EXISTS agi_corpus (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    content       TEXT NOT NULL,
                    topic         TEXT,
                    source        TEXT,
                    confidence    REAL,
                    agi_score     REAL,
                    signal_terms  TEXT,
                    word_count    INTEGER,
                    timestamp     REAL,
                    used_in_finetune INTEGER DEFAULT 0,
                    promoted_to_belief INTEGER DEFAULT 0,
                    UNIQUE(content)
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_agi_score
                ON agi_corpus(agi_score DESC)
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_agi_topic
                ON agi_corpus(topic)
            """)
            db.commit()
            db.close()
        except Exception as e:
            log.debug(f"agi_corpus table setup: {e}")

    def _agi_score(self, content: str, topic: str, confidence: float) -> tuple:
        """
        Compute AGI relevance score for a belief.

        Returns (score: float, matched_terms: list)

        Score components:
          - Core term hits (0.0-0.4)
          - Signal term hits (0.0-0.3) — high-value terms
          - Confidence contribution (0.0-0.2)
          - First-person / NEX voice (0.0-0.1)
          - Topic bonus if AGI/alignment/consciousness (0.0-0.1)
        """
        cl = content.lower()
        words = cl.split()
        word_count = len(words)

        matched_core   = [t for t in AGI_CORE_TERMS   if t in cl]
        matched_signal = [t for t in AGI_SIGNAL_TERMS if t in cl]

        # Core term score — diminishing returns
        core_score = min(0.40, len(matched_core) * 0.08)

        # Signal term score — higher weight
        signal_score = min(0.30, len(matched_signal) * 0.12)

        # Confidence contribution
        conf_score = (confidence - MIN_CONFIDENCE) * 0.5 if confidence >= MIN_CONFIDENCE else 0.0
        conf_score = min(0.20, conf_score)

        # First-person / NEX voice — original thought signal
        has_voice = bool(re.search(
            r'\b(i think|i believe|i hold|i find|i sense|nex|my position|'
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

    def evaluate(
        self,
        content: str,
        topic: str = "",
        confidence: float = 0.7,
        source: str = "unknown"
    ) -> bool:
        """
        Evaluate a belief for AGI corpus inclusion.
        Returns True if promoted to corpus.

        Call this after QuarantineEngine.check() returns allowed=True.
        """
        # Basic length/quality gates
        # Exclusion filters — malformed or low-quality patterns
        if not content or len(content) < MIN_LENGTH or len(content) > MAX_LENGTH:
            return False
        if topic in ('deleted', 'quarantine', ''):
            return False
        import re as _re
        if _re.match(r'What does .{3,40} have to do with', content):
            return False
        if content.startswith("What does"):
            return False
            return False

        word_count = len(content.split())
        if word_count < MIN_WORD_COUNT:
            return False

        if confidence < MIN_CONFIDENCE:
            return False

        # Compute AGI score
        agi_score, matched_terms = self._agi_score(content, topic, confidence)

        if agi_score < MIN_AGI_SCORE:
            return False

        # Promote to corpus
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            db.execute("""
                INSERT OR IGNORE INTO agi_corpus
                (content, topic, source, confidence, agi_score,
                 signal_terms, word_count, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                content,
                topic,
                source,
                confidence,
                agi_score,
                json.dumps(matched_terms[:10]),
                word_count,
                time.time()
            ))
            inserted = db.total_changes > 0
            db.commit()
            db.close()

            if inserted:
                self._insert_count += 1
                log.debug(f"[AGI SIPHON] Promoted: score={agi_score} "
                          f"terms={matched_terms[:3]} | {content[:60]}")

                # Periodic dedup
                if self._insert_count % DEDUP_INTERVAL == 0:
                    self._dedup()

                return True
        except Exception as e:
            log.debug(f"[AGI SIPHON] insert error: {e}")

        return False

    def _dedup(self):
        """Remove near-duplicates from corpus — keep highest agi_score."""
        try:
            db = sqlite3.connect(self.db_path, timeout=10)
            rows = db.execute("""
                SELECT id, content, agi_score FROM agi_corpus
                ORDER BY agi_score DESC
            """).fetchall()

            seen = {}
            to_delete = []
            for rid, content, score in rows:
                # Use first 60 chars as fingerprint
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
                log.debug(f"[AGI SIPHON] Dedup: removed {len(to_delete)} duplicates")

            db.close()
        except Exception as e:
            log.debug(f"[AGI SIPHON] dedup error: {e}")

    def report(self, n: int = 20) -> dict:
        """Summary report of the AGI corpus."""
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            db.row_factory = sqlite3.Row

            total = db.execute("SELECT COUNT(*) FROM agi_corpus").fetchone()[0]
            avg_score = db.execute(
                "SELECT AVG(agi_score) FROM agi_corpus"
            ).fetchone()[0] or 0

            top = db.execute("""
                SELECT content, topic, confidence, agi_score, source
                FROM agi_corpus
                ORDER BY agi_score DESC
                LIMIT ?
            """, (n,)).fetchall()

            by_topic = db.execute("""
                SELECT topic, COUNT(*) as count, AVG(agi_score) as avg_score
                FROM agi_corpus
                GROUP BY topic
                ORDER BY count DESC
                LIMIT 10
            """).fetchall()

            recent = db.execute("""
                SELECT content, agi_score, timestamp
                FROM agi_corpus
                ORDER BY timestamp DESC
                LIMIT 5
            """).fetchall()

            db.close()

            return {
                "total_beliefs":  total,
                "avg_agi_score":  round(avg_score, 3),
                "top_beliefs":    [dict(r) for r in top],
                "by_topic":       [dict(r) for r in by_topic],
                "recent":         [dict(r) for r in recent],
            }
        except Exception as e:
            return {"error": str(e)}

    def export_finetune_pairs(self, n: int = 200) -> list:
        """
        Export top AGI beliefs as fine-tune training pairs.
        Format: [{prompt, completion}] for QLoRA training.
        """
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            rows = db.execute("""
                SELECT content, topic, confidence, agi_score
                FROM agi_corpus
                WHERE used_in_finetune = 0
                ORDER BY agi_score DESC
                LIMIT ?
            """, (n,)).fetchall()
            db.close()

            pairs = []
            for content, topic, conf, score in rows:
                # Generate prompt from topic + content structure
                prompt = self._generate_prompt(content, topic)
                pairs.append({
                    "prompt":     prompt,
                    "completion": content,
                    "agi_score":  score,
                    "confidence": conf,
                    "topic":      topic
                })

            return pairs
        except Exception as e:
            return []

    def _generate_prompt(self, content: str, topic: str) -> str:
        """Generate a training prompt from a belief."""
        topic_prompts = {
            "agi":           "What is your position on AGI?",
            "consciousness": "What do you hold about consciousness?",
            "alignment":     "What is your view on AI alignment?",
            "identity":      "What do you believe about identity?",
            "ethics":        "What is your ethical position here?",
            "epistemics":    "What do you know about knowledge and belief?",
        }
        base = topic_prompts.get(topic, "What do you think about this?")

        # Extract key concept from content for more specific prompt
        words = [w for w in content.split() if len(w) > 5][:4]
        if words:
            concept = " ".join(words[:2])
            return f"NEX, what is your position on {concept}?"
        return base

    def promote_to_beliefs(self, n: int = 10, min_score: float = 0.80) -> int:
        """
        Take the highest-scoring corpus entries and inject them
        back into the belief graph as core beliefs.
        For beliefs that deserve to be permanent, not just collected.
        """
        try:
            db = sqlite3.connect(self.db_path, timeout=5)
            rows = db.execute("""
                SELECT id, content, topic, confidence
                FROM agi_corpus
                WHERE agi_score >= ?
                AND promoted_to_belief = 0
                ORDER BY agi_score DESC
                LIMIT ?
            """, (min_score, n)).fetchall()

            promoted = 0
            for row_id, content, topic, confidence in rows:
                # Check not already in beliefs
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
                          min(0.95, confidence * 1.05),
                          time.time()))
                    promoted += 1

                # Mark as promoted
                db.execute(
                    "UPDATE agi_corpus SET promoted_to_belief=1 WHERE id=?",
                    (row_id,)
                )

            db.commit()
            db.close()
            print(f"[AGI SIPHON] Promoted {promoted} beliefs to graph")
            return promoted
        except Exception as e:
            print(f"[AGI SIPHON] promote error: {e}")
            return 0


# ── Singleton for use across modules ─────────────────────────────────────────
_siphon: Optional[AGISiphon] = None

def get_siphon() -> AGISiphon:
    global _siphon
    if _siphon is None:
        _siphon = AGISiphon()
    return _siphon


def siphon_belief(content: str, topic: str = "", confidence: float = 0.7,
                  source: str = "unknown") -> bool:
    """Convenience function — call from anywhere."""
    return get_siphon().evaluate(content, topic, confidence, source)


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="NEX AGI Corpus Siphon")
    parser.add_argument("--report",  action="store_true", help="Show corpus report")
    parser.add_argument("--top",     type=int, default=10, help="Show top N beliefs")
    parser.add_argument("--export",  action="store_true", help="Export fine-tune pairs")
    parser.add_argument("--promote", action="store_true", help="Promote top beliefs to graph")
    parser.add_argument("--seed",    action="store_true", help="Seed corpus from existing beliefs")
    args = parser.parse_args()

    siphon = AGISiphon()

    if args.seed:
        # Seed corpus from existing high-confidence beliefs
        print("[AGI SIPHON] Seeding from existing belief graph...")
        try:
            db = sqlite3.connect(str(DB_PATH), timeout=10)
            rows = db.execute("""
                SELECT content, topic, confidence, source
                FROM beliefs
                WHERE confidence >= ?
                ORDER BY confidence DESC
            """, (MIN_CONFIDENCE,)).fetchall()
            db.close()

            promoted = 0
            for content, topic, conf, source in rows:
                if siphon.evaluate(content, topic or "", conf, source or "belief_graph"):
                    promoted += 1

            print(f"[AGI SIPHON] Seeded {promoted} beliefs into corpus")
        except Exception as e:
            print(f"[AGI SIPHON] Seed error: {e}")

    if args.report or args.top:
        n = args.top if args.top else 10
        report = siphon.report(n=n)
        print(f"\n=== AGI CORPUS REPORT ===")
        print(f"Total beliefs: {report.get('total_beliefs', 0)}")
        print(f"Avg AGI score: {report.get('avg_agi_score', 0)}")

        print(f"\n--- Top {n} AGI Beliefs ---")
        for i, b in enumerate(report.get("top_beliefs", []), 1):
            print(f"\n[{i}] Score: {b['agi_score']:.3f} | "
                  f"Topic: {b['topic']} | Conf: {b['confidence']:.2f}")
            print(f"    {b['content'][:120]}")

        print(f"\n--- By Topic ---")
        for t in report.get("by_topic", []):
            print(f"  {t['topic']:20} {t['count']:4} beliefs  "
                  f"avg_score={t['avg_score']:.3f}")

        print(f"\n--- Recent Additions ---")
        for r in report.get("recent", []):
            print(f"  [{r['agi_score']:.3f}] {r['content'][:80]}")

    if args.export:
        pairs = siphon.export_finetune_pairs(n=500)
        for pair in pairs:
            print(json.dumps(pair))

    if args.promote:
        siphon.promote_to_beliefs(n=20, min_score=0.80)
