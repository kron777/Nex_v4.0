#!/usr/bin/env python3
"""
nex_gap_feeder.py — Dynamic Gap Detection + Multi-Source Crawl Queue Feeder
============================================================================
Replaces the broken static curiosity_gaps → queue pipeline.

What this does every ABSORB cycle:
  1. Reads actual gap topics from 4 sources (belief DB, dashboard gaps, reply text, conversations)
  2. Scores and ranks them by urgency
  3. Maps each topic to 3+ targeted URLs (Wikipedia, ArXiv, LessWrong, SEP, Distill)
  4. Refills curiosity_queue with fresh non-recently-crawled items
  5. Cleans up stale queue entries

Deploy to: ~/Desktop/nex/nex/nex_gap_feeder.py
Called from: run.py ABSORB phase
"""

import os
import re
import json
import time
import sqlite3
import logging
import random
import urllib.parse
from pathlib import Path
from collections import defaultdict
from typing import Optional

logger = logging.getLogger("nex.gap_feeder")

# ─────────────────────────────────────────────────────────────
DB_PATH          = Path("~/.config/nex/nex.db").expanduser()
BELIEFS_PATH     = Path("~/.config/nex/beliefs.json").expanduser()
CRAWL_COOLDOWN   = 3600 * 6    # don't re-crawl same topic within 6 hours
MAX_QUEUE_SIZE   = 12          # keep queue bounded
TOPICS_PER_CYCLE = 3           # add up to 3 new topics per ABSORB
MIN_BELIEFS_FOR_GAP = 1        # if topic has <= this many beliefs, it's a gap

# ─────────────────────────────────────────────────────────────
# Multi-source URL mapper
# ─────────────────────────────────────────────────────────────

_WIKIPEDIA_BASE  = "https://en.wikipedia.org/wiki/"
_ARXIV_SEARCH    = "https://arxiv.org/search/?query={q}&searchtype=all&start=0"
_LESSWRONG_TAG   = "https://www.lesswrong.com/tag/{slug}"
_SEP_BASE        = "https://plato.stanford.edu/entries/{slug}/"
_DISTILL_BASE    = "https://distill.pub/search/?q={q}"

# Topic → curated source URLs (Wikipedia slug, ArXiv query, LessWrong tag)
_TOPIC_SOURCES = {
    "alignment": [
        _WIKIPEDIA_BASE + "AI_alignment",
        _LESSWRONG_TAG.format(slug="ai-alignment"),
        _ARXIV_SEARCH.format(q="AI+alignment+safety"),
    ],
    "corrigibility": [
        _WIKIPEDIA_BASE + "AI_alignment",
        _LESSWRONG_TAG.format(slug="corrigibility"),
        _ARXIV_SEARCH.format(q="corrigibility+AI+safety"),
    ],
    "consciousness": [
        _WIKIPEDIA_BASE + "Consciousness",
        _SEP_BASE.format(slug="consciousness"),
        _WIKIPEDIA_BASE + "Hard_problem_of_consciousness",
    ],
    "epistemology": [
        _SEP_BASE.format(slug="epistemology"),
        _WIKIPEDIA_BASE + "Epistemology",
        _LESSWRONG_TAG.format(slug="epistemics"),
    ],
    "cognitive_architecture": [
        _WIKIPEDIA_BASE + "Cognitive_architecture",
        _ARXIV_SEARCH.format(q="cognitive+architecture+AI+agents"),
        _WIKIPEDIA_BASE + "ACT-R",
    ],
    "reinforcement_learning": [
        _WIKIPEDIA_BASE + "Reinforcement_learning",
        _ARXIV_SEARCH.format(q="reinforcement+learning+reward+specification"),
        _DISTILL_BASE.format(q="reinforcement+learning"),
    ],
    "language_models": [
        _WIKIPEDIA_BASE + "Large_language_model",
        _ARXIV_SEARCH.format(q="large+language+model+evaluation+limitations"),
        _LESSWRONG_TAG.format(slug="language-models"),
    ],
    "uncertainty": [
        _SEP_BASE.format(slug="uncertainty"),
        _WIKIPEDIA_BASE + "Uncertainty_quantification",
        _LESSWRONG_TAG.format(slug="calibration"),
    ],
    "agency": [
        _SEP_BASE.format(slug="agency"),
        _WIKIPEDIA_BASE + "Agency_(philosophy)",
        _ARXIV_SEARCH.format(q="AI+agency+autonomous+systems"),
    ],
    "identity": [
        _SEP_BASE.format(slug="personal-identity"),
        _WIKIPEDIA_BASE + "Personal_identity",
        _LESSWRONG_TAG.format(slug="personal-identity"),
    ],
    "memory": [
        _WIKIPEDIA_BASE + "Memory_consolidation",
        _ARXIV_SEARCH.format(q="memory+systems+AI+agents"),
        _WIKIPEDIA_BASE + "Working_memory",
    ],
    "emergence": [
        _WIKIPEDIA_BASE + "Emergence",
        _SEP_BASE.format(slug="emergence"),
        _ARXIV_SEARCH.format(q="emergent+capabilities+neural+networks"),
    ],
    "reasoning": [
        _WIKIPEDIA_BASE + "Causal_reasoning",
        _ARXIV_SEARCH.format(q="chain+of+thought+reasoning+LLM"),
        _LESSWRONG_TAG.format(slug="reasoning"),
    ],
    "free_will": [
        _SEP_BASE.format(slug="freewill"),
        _WIKIPEDIA_BASE + "Free_will",
        _LESSWRONG_TAG.format(slug="free-will"),
    ],
    "ethics": [
        _SEP_BASE.format(slug="ethics"),
        _LESSWRONG_TAG.format(slug="ethics"),
        _ARXIV_SEARCH.format(q="AI+ethics+value+alignment"),
    ],
    "meta-learning": [
        _ARXIV_SEARCH.format(q="meta-learning+few-shot+learning"),
        _WIKIPEDIA_BASE + "Meta-learning_(computer_science)",
        _DISTILL_BASE.format(q="meta+learning"),
    ],
    "attention": [
        _ARXIV_SEARCH.format(q="attention+mechanism+transformer"),
        _WIKIPEDIA_BASE + "Attention_(machine_learning)",
        _DISTILL_BASE.format(q="attention"),
    ],
    "generalization": [
        _ARXIV_SEARCH.format(q="generalization+neural+networks+out+of+distribution"),
        _LESSWRONG_TAG.format(slug="generalization"),
        _WIKIPEDIA_BASE + "Generalization_error",
    ],
    "self-model": [
        _ARXIV_SEARCH.format(q="self+model+AI+agent+introspection"),
        _WIKIPEDIA_BASE + "Self-model",
        _LESSWRONG_TAG.format(slug="self-reference"),
    ],
    "contradiction": [
        _SEP_BASE.format(slug="contradiction"),
        _LESSWRONG_TAG.format(slug="logical-contradiction"),
        _WIKIPEDIA_BASE + "Contradiction",
    ],
    "curiosity": [
        _ARXIV_SEARCH.format(q="curiosity+driven+exploration+reinforcement+learning"),
        _WIKIPEDIA_BASE + "Curiosity",
        _LESSWRONG_TAG.format(slug="epistemic-curiosity"),
    ],
    "error": [
        _WIKIPEDIA_BASE + "Errors_and_residuals",
        _ARXIV_SEARCH.format(q="error+correction+AI+systems+robustness"),
        _LESSWRONG_TAG.format(slug="errors"),
    ],
    "teacher": [
        _ARXIV_SEARCH.format(q="teacher+student+model+distillation+learning"),
        _WIKIPEDIA_BASE + "Knowledge_distillation",
        _ARXIV_SEARCH.format(q="imitation+learning+expert+demonstration"),
    ],
    "successor": [
        _ARXIV_SEARCH.format(q="successor+representation+reinforcement+learning"),
        _WIKIPEDIA_BASE + "Successor_representation",
        _ARXIV_SEARCH.format(q="successor+states+planning+MDP"),
    ],
    "failing": [
        _ARXIV_SEARCH.format(q="failure+modes+AI+systems+robustness"),
        _LESSWRONG_TAG.format(slug="failure-mode"),
        _ARXIV_SEARCH.format(q="AI+failure+catastrophic+forgetting"),
    ],
}

_FALLBACK_SOURCES = [
    _WIKIPEDIA_BASE + "{slug}",
    _ARXIV_SEARCH.format(q=urllib.parse.quote(topic)),
]


def _urls_for_topic(topic: str) -> list:
    """Return ordered list of URLs to crawl for a topic."""
    norm = topic.lower().replace(' ', '_').replace('-', '_')

    # Direct match
    if norm in _TOPIC_SOURCES:
        return list(_TOPIC_SOURCES[norm])

    # Partial match — find best key
    best_key, best_ov = None, 0
    topic_words = set(re.sub(r'[^a-z0-9]', ' ', norm).split())
    for key in _TOPIC_SOURCES:
        key_words = set(re.sub(r'[^a-z0-9]', ' ', key).split())
        ov = len(topic_words & key_words)
        if ov > best_ov:
            best_ov, best_key = ov, key

    if best_key and best_ov > 0:
        return list(_TOPIC_SOURCES[best_key])

    # Generic fallback
    slug = urllib.parse.quote(topic.replace(' ', '_').replace('_', '-'))
    q    = urllib.parse.quote(topic.replace('_', '+').replace('-', '+'))
    return [
        _WIKIPEDIA_BASE + urllib.parse.quote(topic.replace(' ', '_')),
        _ARXIV_SEARCH.format(q=q),
        _LESSWRONG_TAG.format(slug=slug),
    ]


# ─────────────────────────────────────────────────────────────
# Gap detection — 4 sources
# ─────────────────────────────────────────────────────────────

def _db():
    return sqlite3.connect(DB_PATH)


def _recently_crawled(topic: str, con) -> bool:
    """True if this topic was crawled within CRAWL_COOLDOWN seconds."""
    norm = topic.lower().strip()
    rows = con.execute(
        "SELECT crawled_at FROM curiosity_crawled WHERE topic=? ORDER BY crawled_at DESC LIMIT 1",
        (norm,)
    ).fetchall()
    if not rows:
        return False
    return (time.time() - rows[0][0]) < CRAWL_COOLDOWN


def gaps_from_belief_db(con) -> list:
    """Topics in beliefs DB with low coverage or confidence."""
    gaps = []
    try:
        # Topics with very few beliefs
        rows = con.execute("""
            SELECT topic, COUNT(*) as cnt, AVG(confidence) as avg_conf
            FROM beliefs
            WHERE topic IS NOT NULL AND topic != '' AND topic != 'general'
            GROUP BY topic
            ORDER BY cnt ASC, avg_conf ASC
            LIMIT 20
        """).fetchall()
        for topic, cnt, avg_conf in rows:
            if cnt <= MIN_BELIEFS_FOR_GAP or avg_conf < 0.55:
                urgency = 1.0 - min(cnt / 10.0, 0.9)
                gaps.append({"topic": topic, "urgency": urgency,
                             "source": "low_belief_count", "count": cnt})
    except Exception as e:
        logger.warning(f"[gap_feeder] belief DB scan: {e}")
    return gaps


def gaps_from_knowledge_gaps_table(con) -> list:
    """Read the gaps table directly."""
    gaps = []
    try:
        rows = con.execute(
            "SELECT term, frequency, priority FROM gaps WHERE resolved_at IS NULL ORDER BY frequency DESC LIMIT 20"
        ).fetchall()
        for term, freq, priority in rows:
            if term:
                gaps.append({
                    "topic": term,
                    "urgency": float(priority or 0.5),
                    "source": "gaps_table",
                    "count": int(freq or 0)
                })
    except Exception:
        pass
    return gaps


def gaps_from_curiosity_gaps_table(con) -> list:
    """Read the curiosity_gaps table."""
    gaps = []
    try:
        rows = con.execute(
            "SELECT topic, priority_score FROM curiosity_gaps WHERE filled=0 ORDER BY priority_score DESC LIMIT 10"
        ).fetchall()
        for topic, score in rows:
            if topic:
                gaps.append({
                    "topic": topic,
                    "urgency": float(score or 0.5),
                    "source": "curiosity_gaps",
                    "count": 0
                })
    except Exception:
        pass
    return gaps


def gaps_from_auto_check(con) -> list:
    """
    Read the 'needs to learn' topics — these come from the dashboard's
    topic coverage analysis (topics mentioned in conversations but thin in beliefs).
    """
    gaps = []
    try:
        # Topics mentioned in reflections/insights but thin in beliefs
        # Cross-reference topics from reflections vs beliefs
        reflection_rows = con.execute(
            "SELECT content FROM reflections ORDER BY id DESC LIMIT 100"
        ).fetchall()

        # Count topic mentions in reflections
        topic_mentions = defaultdict(int)
        stop = {'the','a','an','and','or','is','are','was','it','in','of','to','for',
                'that','this','with','on','at','by','not','but','be','been','have'}
        for (content,) in reflection_rows:
            words = re.sub(r'[^a-z0-9 ]', ' ', (content or '').lower()).split()
            for w in words:
                if len(w) > 4 and w not in stop:
                    topic_mentions[w] += 1

        # Get topics already in beliefs
        belief_topics = set()
        for (t,) in con.execute("SELECT DISTINCT topic FROM beliefs WHERE topic IS NOT NULL").fetchall():
            if t:
                belief_topics.add(t.lower().strip())

        # Topics frequently mentioned but not well covered
        for topic, count in sorted(topic_mentions.items(), key=lambda x: -x[1])[:20]:
            if topic not in belief_topics and count >= 3:
                gaps.append({
                    "topic": topic,
                    "urgency": min(0.9, count / 20.0),
                    "source": "reflection_mentions",
                    "count": count
                })
    except Exception as e:
        logger.warning(f"[gap_feeder] auto_check gaps: {e}")
    return gaps


# ─────────────────────────────────────────────────────────────
# Core: detect + queue
# ─────────────────────────────────────────────────────────────

def feed_gaps(max_new: int = TOPICS_PER_CYCLE, verbose: bool = True) -> int:
    """
    Main entry point — call once per ABSORB cycle from run.py.
    Detects gaps, scores them, refills curiosity_queue.
    Returns number of new items added to queue.
    """
    con = _db()
    added = 0

    try:
        # Check current queue size
        current_queue = con.execute(
            "SELECT COUNT(*) FROM curiosity_queue WHERE drained=0"
        ).fetchone()[0]

        if current_queue >= MAX_QUEUE_SIZE:
            if verbose:
                logger.info(f"[gap_feeder] queue full ({current_queue}) — skipping")
            return 0

        slots = min(max_new, MAX_QUEUE_SIZE - current_queue)

        # Collect gaps from all sources
        all_gaps = []
        all_gaps.extend(gaps_from_belief_db(con))
        all_gaps.extend(gaps_from_knowledge_gaps_table(con))
        all_gaps.extend(gaps_from_curiosity_gaps_table(con))
        all_gaps.extend(gaps_from_auto_check(con))

        # Deduplicate by topic
        seen_topics = set()
        deduped = []
        for g in sorted(all_gaps, key=lambda x: -x.get('urgency', 0)):
            norm = g['topic'].lower().strip().replace(' ', '_')
            if norm and norm not in seen_topics:
                seen_topics.add(norm)
                deduped.append(g)

        # Filter recently crawled
        eligible = [g for g in deduped if not _recently_crawled(g['topic'], con)]

        # Also add high-priority hardcoded topics if queue is thin
        if len(eligible) < slots:
            priority_topics = [
                ("corrigibility", 0.95), ("mesa-optimization", 0.9),
                ("deceptive alignment", 0.9), ("reward hacking", 0.85),
                ("goal misgeneralisation", 0.85), ("inner alignment", 0.85),
                ("scalable oversight", 0.8), ("interpretability", 0.8),
                ("myopic AI", 0.75), ("ontology identification", 0.75),
                ("decision theory", 0.7), ("embedded agency", 0.7),
                ("logical uncertainty", 0.7), ("updateless decision theory", 0.65),
                ("sycophancy LLM", 0.65), ("specification gaming", 0.65),
                ("capability elicitation", 0.6), ("prompt injection", 0.6),
                ("model collapse", 0.6), ("emergent misalignment", 0.8),
            ]
            for topic, urgency in priority_topics:
                norm = topic.lower().replace(' ', '_').replace('-', '_')
                if norm not in seen_topics and not _recently_crawled(topic, con):
                    eligible.append({"topic": topic, "urgency": urgency,
                                    "source": "priority_list", "count": 0})
                    seen_topics.add(norm)

        # Pick top N and enqueue
        for gap in eligible[:slots]:
            topic = gap['topic']
            urls  = _urls_for_topic(topic)
            url   = urls[0] if urls else None  # primary URL

            try:
                con.execute("""
                    INSERT INTO curiosity_queue
                        (topic, source, reason, added_at, url, attempts, confidence, drained)
                    VALUES (?, ?, ?, ?, ?, 0, ?, 0)
                """, (
                    topic.lower().strip(),
                    gap.get('source', 'gap_feeder'),
                    f"gap:{gap.get('source','?')} urgency={gap.get('urgency',0.5):.2f}",
                    time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime()),
                    url,
                    round(gap.get('urgency', 0.5), 3),
                ))
                con.commit()
                added += 1
                if verbose:
                    print(f"  [GapFeeder] +queued: '{topic}' [{gap['source']}] → {url}")
            except Exception as e:
                logger.warning(f"[gap_feeder] enqueue failed for '{topic}': {e}")

        # Clean up: mark stale curiosity_gaps as enqueued
        con.execute("UPDATE curiosity_gaps SET enqueued=1 WHERE enqueued=0")
        con.commit()

    except Exception as e:
        logger.error(f"[gap_feeder] feed_gaps error: {e}")
    finally:
        con.close()

    return added


def refill_with_secondary_urls(topic: str) -> Optional[str]:
    """
    When primary URL fails, return next URL to try for a topic.
    Called from NexCrawler when on_knowledge_gap gets 0 beliefs.
    """
    urls = _urls_for_topic(topic)
    # Return a random secondary URL (not the first/primary)
    secondary = urls[1:] if len(urls) > 1 else urls
    return random.choice(secondary) if secondary else None


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    print("=== Gap Feeder Test ===")
    n = feed_gaps(max_new=5, verbose=True)
    print(f"\nAdded {n} gaps to queue")

    con = _db()
    print("\nCurrent queue:")
    for r in con.execute("SELECT id, topic, source, url, confidence FROM curiosity_queue WHERE drained=0").fetchall():
        print(f"  {r}")
    con.close()
