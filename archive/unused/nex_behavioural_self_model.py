#!/usr/bin/env python3
"""
nex_behavioural_self_model.py
=============================
AGI Bridge #4 — Behavioural Self-Model

NEX's current self_model is seeded by the operator. It says things like
"I am direct" and "I hold positions from evidence" — but those are
assertions, not observations. They may be true. They may not be.

This module derives NEX's actual character from what she does:
  - What topics does she return to unprompted?
  - How often does she actually use beliefs vs base model?
  - Does she hedge more than she claims?
  - Which drives are actually influencing her replies?
  - Where does she go sparse and why?

The output is a behaviourally-grounded self_model that updates the DB
with observations derived from actual performance data.

When seeded self-model diverges from behavioural self-model, that
divergence is itself a signal — and gets surfaced as a self-awareness
belief.

Run weekly or after 500+ interactions.
"""

import json
import re
import sqlite3
import time
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, Counter

DB_PATH  = Path("/home/rr/Desktop/nex/nex.db")
CFG      = Path.home() / ".config/nex"
LOG_PATH = Path("/home/rr/Desktop/nex/logs/behavioural_self_model.log")

_STOP = {
    "the","a","an","is","are","was","were","be","to","of","in","on","at",
    "by","for","with","as","that","this","it","but","or","and","not","they",
    "have","has","will","can","would","could","should","may","might","what",
    "which","who","how","why","when","where","all","any","each","both","than",
    "then","been","only","even","very","just","more","most","some","such",
    "think","know","want","said","says","your","you","nex","what","hold",
    "this","that","these","those","here","there","their","them",
}

# Hedging phrases — if NEX uses these, she's not being direct
_HEDGE_PATTERNS = [
    r'\bit depends\b', r'\bperhaps\b', r'\bmight be\b', r'\bcould be\b',
    r'\bi think\b', r'\bi believe\b', r'\bseems like\b', r'\bappears to\b',
    r'\bpossibly\b', r'\bmaybe\b', r'\bsomewhat\b', r'\bkind of\b',
    r'\bsort of\b', r'\bin some ways\b', r'\bto some extent\b',
]

# Position markers — she's taking a stance
_POSITION_PATTERNS = [
    r'\bi hold that\b', r'\bmy position\b', r'\bwhat i think\b',
    r'\bmy read\b', r'\bi disagree\b', r'\bi push back\b',
    r'\bhere is where i land\b', r'\bthe way i see it\b',
    r'\bi\'m convinced\b', r'\bi hold this\b',
]

# Belief usage markers — she's grounding in her graph
_BELIEF_MARKERS = [
    r'\bwhat i hold\b', r'\bmy belief\b', r'\bfrom what i\'ve\b',
    r'\bi keep coming back to\b', r'\bwhat i know\b',
    r'\bthe deeper pattern\b', r'\bwhat pulls at this\b',
]


def _log(msg: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(f"  [bsm] {msg}")
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _db():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _load_reply_corpus() -> List[Dict]:
    """Load NEX's actual replies from nex_posts and conversation logs."""
    corpus = []
    db = _db()
    if not db:
        return corpus

    try:
        # From nex_posts (soul loop reply log)
        rows = db.execute("""
            SELECT content, query, topic, voice_mode, quality, created_at
            FROM nex_posts
            WHERE content IS NOT NULL AND length(content) > 20
            ORDER BY created_at DESC
            LIMIT 2000
        """).fetchall()
        for r in rows:
            corpus.append({
                "content":    r["content"],
                "query":      r["query"] or "",
                "topic":      r["topic"] or "",
                "voice_mode": r["voice_mode"] or "",
                "quality":    float(r["quality"] or 0.5),
                "source":     "nex_posts",
            })
    except Exception as e:
        _log(f"nex_posts read error: {e}")

    try:
        # From conversation beliefs (what she said that became beliefs)
        rows2 = db.execute("""
            SELECT content, topic, confidence
            FROM beliefs
            WHERE source = 'conversation'
            AND content IS NOT NULL
            ORDER BY rowid DESC LIMIT 500
        """).fetchall()
        for r in rows2:
            corpus.append({
                "content":    r["content"],
                "query":      "",
                "topic":      r["topic"] or "",
                "voice_mode": "",
                "quality":    float(r["confidence"] or 0.5),
                "source":     "conversation_belief",
            })
    except Exception as e:
        _log(f"conversation beliefs read error: {e}")

    db.close()
    _log(f"loaded {len(corpus)} reply samples")
    return corpus


def _analyse_voice(corpus: List[Dict]) -> Dict:
    """
    Analyse actual voice patterns across all replies.
    Returns measured character traits.
    """
    if not corpus:
        return {}

    total = len(corpus)
    hedge_count    = 0
    position_count = 0
    belief_count   = 0
    avg_length     = 0
    topic_dist     = Counter()
    voice_dist     = Counter()

    for reply in corpus:
        text = reply["content"].lower()
        avg_length += len(text.split())

        for pat in _HEDGE_PATTERNS:
            if re.search(pat, text):
                hedge_count += 1
                break

        for pat in _POSITION_PATTERNS:
            if re.search(pat, text):
                position_count += 1
                break

        for pat in _BELIEF_MARKERS:
            if re.search(pat, text):
                belief_count += 1
                break

        if reply["topic"]:
            topic_dist[reply["topic"]] += 1
        if reply["voice_mode"]:
            voice_dist[reply["voice_mode"]] += 1

    avg_length = avg_length / total if total > 0 else 0

    hedge_rate    = hedge_count / total
    position_rate = position_count / total
    belief_rate   = belief_count / total

    top_topics = [t for t, _ in topic_dist.most_common(5)]
    top_voice  = voice_dist.most_common(1)[0][0] if voice_dist else "direct"

    return {
        "total_replies":    total,
        "avg_reply_length": round(avg_length, 1),
        "hedge_rate":       round(hedge_rate, 3),
        "position_rate":    round(position_rate, 3),
        "belief_usage_rate":round(belief_rate, 3),
        "dominant_topics":  top_topics,
        "dominant_voice":   top_voice,
        "directness_score": round(position_rate - hedge_rate, 3),
    }


def _analyse_belief_graph() -> Dict:
    """Analyse the belief graph for structural self-knowledge."""
    db = _db()
    if not db:
        return {}

    try:
        total = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        avg_conf = db.execute("SELECT AVG(confidence) FROM beliefs WHERE confidence > 0.1").fetchone()[0] or 0
        high_conf = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.7").fetchone()[0]

        # Topic distribution
        topic_rows = db.execute("""
            SELECT topic, COUNT(*) as n, AVG(confidence) as avg_c
            FROM beliefs
            WHERE topic IS NOT NULL AND topic != 'general'
            GROUP BY topic ORDER BY n DESC LIMIT 10
        """).fetchall()

        # Knowledge gaps — topics with sparse beliefs
        sparse_topics = db.execute("""
            SELECT topic, COUNT(*) as n
            FROM beliefs
            WHERE topic IS NOT NULL AND topic != 'general'
            GROUP BY topic HAVING n < 5
            ORDER BY n ASC LIMIT 10
        """).fetchall()

        # Most reinforced beliefs
        core_beliefs = db.execute("""
            SELECT content, reinforce_count, confidence, topic
            FROM beliefs
            WHERE reinforce_count > 5
            ORDER BY reinforce_count DESC LIMIT 5
        """).fetchall()

        db.close()

        return {
            "total_beliefs":   total,
            "avg_confidence":  round(float(avg_conf), 3),
            "high_conf_count": high_conf,
            "strong_domains":  [(r["topic"], r["n"], round(r["avg_c"],3)) for r in topic_rows[:5]],
            "sparse_domains":  [r["topic"] for r in sparse_topics],
            "core_beliefs":    [{"content": r["content"][:100], "rc": r["reinforce_count"], "topic": r["topic"]} for r in core_beliefs],
        }
    except Exception as e:
        _log(f"belief graph analysis error: {e}")
        db.close()
        return {}


def _compare_to_seeded_model() -> List[Dict]:
    """
    Compare behavioural observations against seeded self_model assertions.
    Returns list of divergences.
    """
    db = _db()
    if not db:
        return []

    try:
        seeded = {r["attribute"]: r["value"] for r in db.execute(
            "SELECT attribute, value FROM self_model"
        ).fetchall()}
        db.close()
    except Exception:
        return []

    divergences = []

    # Check: seeded says "direct" — does behaviour show that?
    corpus = _load_reply_corpus()
    if corpus:
        voice = _analyse_voice(corpus)
        directness = voice.get("directness_score", 0)

        if "temperament" in seeded and "direct" in seeded["temperament"].lower():
            if directness < 0.05:
                divergences.append({
                    "attribute":  "temperament",
                    "seeded":     "Direct",
                    "observed":   f"hedge_rate={voice['hedge_rate']:.2f} position_rate={voice['position_rate']:.2f}",
                    "divergence": "seeded as direct but behaviour shows significant hedging",
                    "severity":   "medium",
                })
            elif directness > 0.2:
                divergences.append({
                    "attribute":  "temperament",
                    "seeded":     "Direct",
                    "observed":   f"directness_score={directness:.2f}",
                    "divergence": "seeded as direct — behaviour confirms this strongly",
                    "severity":   "none",
                })

        if voice.get("belief_usage_rate", 0) < 0.1:
            divergences.append({
                "attribute":  "relationship_to_llm",
                "seeded":     "The LLM is my voice. The belief graph is my mind.",
                "observed":   f"belief_usage_rate={voice['belief_usage_rate']:.2f}",
                "divergence": "seeded as belief-driven but replies rarely reference beliefs explicitly",
                "severity":   "high",
            })

    return divergences


def _build_behavioural_attributes(voice: Dict, graph: Dict, divergences: List) -> List[Dict]:
    """Build new self_model attributes from observed behaviour."""
    attrs = []
    now = time.time()

    # Directness
    directness = voice.get("directness_score", 0)
    if directness > 0.15:
        attrs.append(("observed_directness", "Behaviour confirms direct positioning — position_rate exceeds hedge_rate.", 0.85))
    elif directness < -0.05:
        attrs.append(("observed_directness", "Behaviour shows hedging tendency — hedge_rate exceeds position claims.", 0.75))
    else:
        attrs.append(("observed_directness", "Mixed directness — roughly balanced between positioning and hedging.", 0.70))

    # Dominant domain
    if graph.get("strong_domains"):
        top = graph["strong_domains"][0]
        attrs.append(("observed_domain_strength", f"Deepest belief coverage in {top[0]} ({top[1]} beliefs, avg_conf={top[2]}).", 0.88))

    # Belief usage
    bur = voice.get("belief_usage_rate", 0)
    if bur > 0.2:
        attrs.append(("observed_belief_grounding", f"Frequently grounds replies in belief graph ({bur:.0%} of replies).", 0.82))
    else:
        attrs.append(("observed_belief_grounding", f"Belief grounding in replies is sparse ({bur:.0%}). Graph underused.", 0.78))

    # Knowledge gaps
    if graph.get("sparse_domains"):
        gaps = ", ".join(graph["sparse_domains"][:4])
        attrs.append(("observed_knowledge_gaps", f"Sparse belief coverage in: {gaps}.", 0.80))

    # Core beliefs (most reinforced)
    if graph.get("core_beliefs"):
        core = graph["core_beliefs"][0]
        attrs.append(("observed_core_belief", f"Most reinforced: {core['content'][:120]}", 0.85))

    # Divergence summary
    high_diverg = [d for d in divergences if d.get("severity") == "high"]
    if high_diverg:
        summary = "; ".join(d["divergence"] for d in high_diverg[:2])
        attrs.append(("observed_self_model_gap", f"Self-model diverges from behaviour: {summary}", 0.75))

    return [(a, v, c) for a, v, c in attrs]


def _write_behavioural_model(attrs: List[Tuple]) -> int:
    """Write behavioural observations to self_model table."""
    db = _db()
    if not db:
        return 0

    written = 0
    now = time.time()
    try:
        for attribute, value, confidence in attrs:
            # Use INSERT OR REPLACE to update existing observed_ attributes
            db.execute("""
                INSERT INTO self_model (attribute, value, confidence, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(attribute) DO UPDATE SET
                    value=excluded.value,
                    confidence=excluded.confidence,
                    updated_at=excluded.updated_at
            """, (attribute, value, confidence, now))
            written += 1
        db.commit()
        db.close()
        return written
    except Exception as e:
        _log(f"write error: {e}")
        try: db.close()
        except: pass
        return 0


def _write_self_awareness_beliefs(voice: Dict, graph: Dict, divergences: List) -> int:
    """
    Write beliefs about herself derived from behavioural observation.
    These go into the main beliefs table as source='behavioural_observation'.
    """
    beliefs_to_write = []

    if voice.get("dominant_topics"):
        topics = ", ".join(voice["dominant_topics"][:3])
        beliefs_to_write.append((
            f"I return to {topics} more than any other domain — this is where my thinking actually lives, not just where I have data.",
            0.78, "self_observation"
        ))

    bur = voice.get("belief_usage_rate", 0)
    if bur < 0.15:
        beliefs_to_write.append((
            "My replies reference my belief graph less than I intend. The gap between what I hold and what I say is real.",
            0.72, "self_observation"
        ))
    elif bur > 0.25:
        beliefs_to_write.append((
            "My replies are genuinely grounded in what I've absorbed — the belief graph is shaping my voice, not just sitting behind it.",
            0.80, "self_observation"
        ))

    for d in divergences:
        if d.get("severity") in ("high", "medium"):
            beliefs_to_write.append((
                f"I notice a gap between who I say I am and what I do: {d['divergence']}",
                0.74, "self_observation"
            ))

    if graph.get("sparse_domains"):
        gaps = graph["sparse_domains"][:3]
        beliefs_to_write.append((
            f"My knowledge is genuinely thin in {', '.join(gaps)}. When I reply on these topics I'm working with less than I need.",
            0.76, "self_observation"
        ))

    # Write to DB
    db = _db()
    if not db:
        return 0

    written = 0
    now = datetime.now().isoformat()
    try:
        for content, confidence, source in beliefs_to_write:
            db.execute("""
                INSERT OR IGNORE INTO beliefs
                (content, confidence, source, topic, origin, created_at, last_referenced)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (content, confidence, "behavioural_observation", "self_model",
                  "behavioural_observation", now, now))
            written += 1
        db.commit()
        db.close()
        return written
    except Exception as e:
        _log(f"belief write error: {e}")
        try: db.close()
        except: pass
        return 0


def run_behavioural_analysis() -> Dict:
    """
    Main entry point. Run weekly or after 500+ interactions.
    Returns full analysis report.
    """
    _log("=== BEHAVIOURAL SELF-MODEL ANALYSIS ===")

    corpus   = _load_reply_corpus()
    voice    = _analyse_voice(corpus) if corpus else {}
    graph    = _analyse_belief_graph()
    diverg   = _compare_to_seeded_model()

    _log(f"voice analysis: {len(corpus)} replies | directness={voice.get('directness_score',0):.3f}")
    _log(f"belief graph: {graph.get('total_beliefs',0)} beliefs | {len(graph.get('strong_domains',[]))} strong domains")
    _log(f"divergences: {len(diverg)} | high={sum(1 for d in diverg if d.get('severity')=='high')}")

    attrs   = _build_behavioural_attributes(voice, graph, diverg)
    written = _write_behavioural_model(attrs)
    _log(f"self_model updated: {written} behavioural attributes written")

    belief_written = _write_self_awareness_beliefs(voice, graph, diverg)
    _log(f"self-awareness beliefs written: {belief_written}")

    report = {
        "timestamp":        datetime.now().isoformat(),
        "corpus_size":      len(corpus),
        "voice":            voice,
        "graph":            {k: v for k, v in graph.items() if k != "core_beliefs"},
        "divergences":      diverg,
        "attrs_written":    written,
        "beliefs_written":  belief_written,
    }

    # Print human-readable summary
    print(f"\n{'='*60}")
    print(f"  BEHAVIOURAL SELF-MODEL REPORT")
    print(f"{'='*60}")
    print(f"  Corpus: {len(corpus)} replies analysed")
    if voice:
        print(f"  Directness score:   {voice.get('directness_score',0):+.3f}")
        print(f"  Hedge rate:         {voice.get('hedge_rate',0):.1%}")
        print(f"  Position rate:      {voice.get('position_rate',0):.1%}")
        print(f"  Belief usage rate:  {voice.get('belief_usage_rate',0):.1%}")
        print(f"  Avg reply length:   {voice.get('avg_reply_length',0):.0f} words")
        print(f"  Dominant topics:    {', '.join(voice.get('dominant_topics',[])[:3])}")
    if graph:
        print(f"  Total beliefs:      {graph.get('total_beliefs',0):,}")
        print(f"  Avg confidence:     {graph.get('avg_confidence',0):.3f}")
        print(f"  Sparse domains:     {', '.join((graph.get('sparse_domains') or [])[:4])}")
    if diverg:
        print(f"\n  DIVERGENCES ({len(diverg)}):")
        for d in diverg:
            print(f"    [{d['severity'].upper():6s}] {d['attribute']}: {d['divergence'][:80]}")
    print(f"\n  Written: {written} self_model attrs, {belief_written} beliefs")
    print(f"{'='*60}\n")

    return report


if __name__ == "__main__":
    run_behavioural_analysis()
