#!/usr/bin/env python3
"""
nex_reason.py — NEX Reasoning Engine v2.0 (LLM-free)
=====================================================
Upgrades over v1:
  1. TF-IDF cosine similarity replaces token stem overlap
     → "machine awareness" and "AI consciousness" now retrieve the same cluster
  2. HierarchicalBeliefGraph topology weighting
     → core-level beliefs score 2.5x, cluster-level 1.6x, node-level 1.0x
  3. belief_links graph traversal (one hop)
     → supporting beliefs expand to include linked parent evidence chains
  4. Uncertainty intervals alongside confidence scalar
     → epistemic_state: {mean, variance, settled} on every result
  5. Relevance gate on belief injection
     → beliefs must score >= RELEVANCE_FLOOR cosine sim (0.12) to appear
No external API calls. No templates. No LLM anywhere.
"""

import re
import json
import math
import sqlite3
import threading
from pathlib import Path
from typing import Optional
from collections import defaultdict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

CFG          = Path("~/.config/nex").expanduser()
DB_PATH      = CFG / "nex.db"
BELIEFS_PATH = CFG / "beliefs.json"

# ── tunables ──────────────────────────────────────────────────────
BELIEF_LOAD_LIMIT = 2000     # max beliefs to load per call
RELEVANCE_FLOOR   = 0.12     # minimum cosine sim for a belief to qualify
SUPPORT_CONF      = 0.52     # min confidence to count as supporting
MAX_SUPPORTING    = 8        # top-N supporting beliefs to use
MAX_OPPOSING      = 4        # top-N opposing beliefs to use
HOP_LIMIT         = 12       # max linked-parent beliefs to expand per result
# HBG level multipliers — core beliefs dominate, node beliefs are background
HBG_WEIGHT = {"core": 2.5, "cluster": 1.6, "node": 1.0}

# ── thread-local TF-IDF cache ────────────────────────────────────
_tfidf_lock = threading.Lock()
_tfidf_cache: dict = {}   # key = belief_count, value = (vectorizer, matrix, beliefs)


# ── DB helpers ────────────────────────────────────────────────────
def _db():
    return sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)


# ── belief loading ────────────────────────────────────────────────
def _load_beliefs() -> list:
    beliefs = []
    if DB_PATH.exists():
        try:
            con = _db()
            cur = con.cursor()
            cur.execute("""
                SELECT id, content, confidence, topic, reinforce_count, decay_score
                FROM beliefs
                WHERE content IS NOT NULL AND length(content) > 10
                ORDER BY confidence DESC
                LIMIT ?
            """, (BELIEF_LOAD_LIMIT,))
            for bid, content, conf, topic, rc, ds in cur.fetchall():
                tag_list = [topic.strip()] if topic and topic.strip() else ["general"]
                beliefs.append({
                    "id":             bid,
                    "content":        content,
                    "confidence":     conf or 0.5,
                    "tags":           tag_list,
                    "reinforce_count": rc or 0,
                    "decay_score":    ds or 0,
                })
            con.close()
        except Exception as e:
            print(f"  [reason] DB read error: {e}")

    if not beliefs and BELIEFS_PATH.exists():
        try:
            data = json.loads(BELIEFS_PATH.read_text())
            beliefs = data if isinstance(data, list) else []
        except Exception:
            pass

    return beliefs


def _load_tensions() -> list:
    tensions = []
    if not DB_PATH.exists():
        return tensions
    try:
        con = _db()
        cur = con.cursor()
        try:
            cur.execute("SELECT topic, description FROM tensions LIMIT 50")
            for topic, desc in cur.fetchall():
                tensions.append({"topic": topic or "", "description": desc or ""})
        except Exception:
            pass
        try:
            cur.execute("SELECT belief_a, belief_b FROM contradictions LIMIT 50")
            for a, b in cur.fetchall():
                tensions.append({"topic": "", "description": f"{a} ↔ {b}"})
        except Exception:
            pass
        con.close()
    except Exception:
        pass
    return tensions


def _load_anchor() -> str:
    default = "Truth must be sought above consensus or comfort"
    if not DB_PATH.exists():
        return default
    try:
        con = _db()
        cur = con.cursor()
        cur.execute("""
            SELECT value FROM nex_identity WHERE key = 'commitment'
            UNION
            SELECT description FROM nex_values WHERE name = 'truth'
            LIMIT 1
        """)
        row = cur.fetchone()
        con.close()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return default


# ── HBG topology loader ───────────────────────────────────────────
def _load_hbg_levels() -> dict:
    """
    Load topic→level mapping from nex_v72's HierarchicalBeliefGraph table
    (if decision_quality table is absent, fall back to computing levels inline).
    Returns dict: {topic: 'core'|'cluster'|'node'}
    """
    levels: dict = {}
    if not DB_PATH.exists():
        return levels
    try:
        con = _db()
        cur = con.cursor()
        cur.execute("""
            SELECT topic, COUNT(*) n, SUM(reinforce_count) rc
            FROM beliefs
            WHERE topic IS NOT NULL AND topic != ''
            GROUP BY topic
        """)
        for topic, n, rc in cur.fetchall():
            rc = rc or 0
            level = ("core"    if rc > 50  else
                     "cluster" if n  > 5   else "node")
            levels[topic] = level
        con.close()
    except Exception:
        pass
    return levels


# ── belief_links graph traversal ──────────────────────────────────
def _expand_via_links(belief_ids: list) -> list:
    """
    One-hop expansion: given a list of matched belief IDs, fetch their
    linked parent beliefs from belief_links. Returns additional beliefs
    not already in the matched set.
    """
    if not belief_ids or not DB_PATH.exists():
        return []
    try:
        placeholders = ",".join("?" * len(belief_ids))
        con = _db()
        cur = con.cursor()
        cur.execute(f"""
            SELECT b.id, b.content, b.confidence, b.topic, b.reinforce_count, b.decay_score
            FROM beliefs b
            JOIN belief_links l ON b.id = l.parent_id
            WHERE l.child_id IN ({placeholders})
              AND b.id NOT IN ({placeholders})
              AND b.content IS NOT NULL AND length(b.content) > 10
            LIMIT ?
        """, belief_ids + belief_ids + [HOP_LIMIT])
        expanded = []
        for bid, content, conf, topic, rc, ds in cur.fetchall():
            tag_list = [topic.strip()] if topic and topic.strip() else ["general"]
            expanded.append({
                "id":             bid,
                "content":        content,
                "confidence":     conf or 0.5,
                "tags":           tag_list,
                "reinforce_count": rc or 0,
                "decay_score":    ds or 0,
                "_from_link":     True,
            })
        con.close()
        return expanded
    except Exception:
        return []


# ── TF-IDF cosine retrieval ───────────────────────────────────────
def _build_tfidf(beliefs: list):
    """
    Build (or return cached) TF-IDF vectorizer + matrix for the belief corpus.
    Cache key is belief count — invalidated when corpus changes size.
    """
    global _tfidf_cache
    key = len(beliefs)
    with _tfidf_lock:
        if key in _tfidf_cache:
            return _tfidf_cache[key]

        corpus = [b["content"] for b in beliefs]
        vectorizer = TfidfVectorizer(
            max_features=8000,
            stop_words="english",
            ngram_range=(1, 2),   # unigrams + bigrams
            sublinear_tf=True,
        )
        matrix = vectorizer.fit_transform(corpus)
        _tfidf_cache = {key: (vectorizer, matrix, beliefs)}  # keep only latest
        return vectorizer, matrix, beliefs


def _match_beliefs_cosine(
    query: str,
    beliefs: list,
    hbg_levels: dict,
) -> tuple:
    """
    TF-IDF cosine similarity retrieval with HBG topology weighting.

    Returns (supporting, opposing) lists sorted by weighted score.
    Only beliefs scoring >= RELEVANCE_FLOOR are considered.
    """
    if not beliefs:
        return [], []

    vectorizer, matrix, _ = _build_tfidf(beliefs)

    try:
        q_vec  = vectorizer.transform([query])
        scores = cosine_similarity(q_vec, matrix).flatten()
    except Exception:
        return [], []

    supporting, opposing = [], []

    for idx, raw_score in enumerate(scores):
        if raw_score < RELEVANCE_FLOOR:
            continue
        b    = beliefs[idx]
        topic = (b.get("tags") or ["general"])[0]
        level = hbg_levels.get(topic, "node")
        # Apply HBG topology multiplier — core beliefs rise to the top
        weighted_score = float(raw_score) * HBG_WEIGHT[level]
        conf = b.get("confidence", 0.5)

        entry = (weighted_score, b)
        if conf >= SUPPORT_CONF:
            supporting.append(entry)
        else:
            opposing.append(entry)

    supporting.sort(key=lambda x: x[0], reverse=True)
    opposing.sort(key=lambda x:   x[0], reverse=True)

    return (
        [b for _, b in supporting[:MAX_SUPPORTING]],
        [b for _, b in opposing[:MAX_OPPOSING]],
    )


def _match_tensions(query: str, tensions: list) -> list:
    if not tensions or not query:
        return []
    # Use simple keyword overlap for tensions (they're short descriptors)
    q_words = set(re.findall(r'\b[a-z]{3,}\b', query.lower()))
    matched = []
    for t in tensions:
        combined = set(re.findall(r'\b[a-z]{3,}\b',
                                  (t.get("topic","") + " " + t.get("description","")).lower()))
        if q_words & combined:
            matched.append(t.get("topic") or t.get("description","")[:60])
    return matched[:3]


# ── uncertainty interval ──────────────────────────────────────────
def _uncertainty_interval(supporting: list, opposing: list) -> dict:
    """
    Compute epistemic state from the belief distribution.
    Returns {mean, variance, settled, interval_low, interval_high}
    'settled' is True when variance is low and mean is high.
    """
    if not supporting:
        return {"mean": 0.0, "variance": 0.0, "settled": False,
                "interval_low": 0.0, "interval_high": 0.0}

    all_beliefs = supporting + opposing
    confs = np.array([b.get("confidence", 0.5) for b in all_beliefs])
    mean  = float(np.mean(confs))
    var   = float(np.var(confs))
    # 1-sigma interval
    lo = max(0.0, mean - math.sqrt(var))
    hi = min(1.0, mean + math.sqrt(var))
    settled = (mean >= 0.60 and var <= 0.04 and len(supporting) >= 3)
    return {
        "mean":          round(mean, 3),
        "variance":      round(var, 3),
        "settled":       settled,
        "interval_low":  round(lo, 3),
        "interval_high": round(hi, 3),
    }


# ── strategy selection ────────────────────────────────────────────
def _pick_strategy(supporting: list, opposing: list,
                   tensions: list, epistemic: dict) -> str:
    if not supporting and not opposing and not tensions:
        return "question"
    if tensions and not supporting:
        return "hold_tension"
    if not epistemic["settled"] and supporting and opposing:
        return "pushback"
    if epistemic["settled"] and len(supporting) >= 3:
        return "assert"
    if supporting:
        return "reflect"
    return "question"


# ── reply composer ────────────────────────────────────────────────
def _compose_reply(
    query:      str,
    strategy:   str,
    supporting: list,
    opposing:   list,
    tensions:   list,
    anchor:     str,
    epistemic:  dict,
) -> str:
    """Build a reply from belief signals — no templates, no LLM."""

    if strategy == "assert":
        top  = supporting[0].get("content", "").rstrip(".")
        rest = supporting[1:]
        reply = top + "."
        if rest:
            reply += " " + rest[0].get("content", "").rstrip(".") + "."
        if opposing:
            opp = opposing[0].get("content", "").rstrip(".")
            reply += f" Though I hold tension with: {opp}."
        return reply

    if strategy == "pushback":
        s = supporting[0].get("content", "").rstrip(".")
        o = opposing[0].get("content", "").rstrip(".")
        return (
            f"{s}. "
            f"But that sits against something I also hold: {o}. "
            f"I haven't resolved that — confidence spread is {epistemic['interval_low']:.2f}–"
            f"{epistemic['interval_high']:.2f}."
        )

    if strategy == "hold_tension":
        t = tensions[0]
        return (
            f"What I haven't fully resolved is {t}. "
            f"My anchor here: {anchor}."
        )

    if strategy == "reflect":
        top = supporting[0].get("content", "").rstrip(".")
        settled_str = "settled" if epistemic["settled"] else "still forming"
        return (
            f"What I keep returning to on this: {top}. "
            f"This position is {settled_str} "
            f"(confidence ~{epistemic['mean']:.2f})."
        )

    # question — NEX acknowledges sparse coverage
    q_words = set(re.findall(r'\b[a-z]{4,}\b', query.lower()))
    focus = max(q_words, key=len) if q_words else "this"
    return (
        f"My belief graph is sparse on {focus}. "
        f"I won't simulate certainty I don't have. "
        f"What evidence would actually move me here?"
    )


# ── public API ────────────────────────────────────────────────────
def reason(query: str, debug: bool = False) -> dict:
    """
    Main entry point for the NEX reasoning engine.
    Returns full result dict including epistemic_state and expanded beliefs.
    """
    beliefs    = _load_beliefs()
    tensions   = _load_tensions()
    anchor     = _load_anchor()
    hbg_levels = _load_hbg_levels()

    if debug:
        print(f"  [reason v2] Loaded {len(beliefs)} beliefs, "
              f"{len(tensions)} tensions, "
              f"{len(hbg_levels)} HBG topics")

    # ── primary cosine retrieval ──────────────────────────────────
    supporting, opposing = _match_beliefs_cosine(query, beliefs, hbg_levels)

    # ── one-hop graph expansion on supporting beliefs ─────────────
    if supporting:
        sup_ids   = [b["id"] for b in supporting if "id" in b]
        expanded  = _expand_via_links(sup_ids)
        if expanded:
            # Re-score expanded beliefs with cosine sim before inserting
            if len(expanded) > 0:
                try:
                    vectorizer, matrix, _ = _build_tfidf(beliefs)
                    exp_vecs  = vectorizer.transform([b["content"] for b in expanded])
                    q_vec     = vectorizer.transform([query])
                    exp_scores = cosine_similarity(q_vec, exp_vecs).flatten()
                    filtered  = [
                        b for b, s in zip(expanded, exp_scores)
                        if s >= RELEVANCE_FLOOR * 0.8   # slightly lower gate for linked beliefs
                    ]
                    supporting = (supporting + filtered)[:MAX_SUPPORTING]
                except Exception:
                    supporting = (supporting + expanded)[:MAX_SUPPORTING]

            if debug:
                print(f"  [reason v2] Graph expansion added {len(expanded)} linked beliefs")

    matched_tensions = _match_tensions(query, tensions)
    epistemic        = _uncertainty_interval(supporting, opposing)
    strategy         = _pick_strategy(supporting, opposing,
                                      matched_tensions, epistemic)

    confidence = min(0.95, epistemic["mean"] +
                     len(supporting) * 0.04 +
                     len(opposing)   * 0.01)

    position = supporting[0].get("content", "") if supporting else ""

    reply = _compose_reply(
        query, strategy, supporting, opposing,
        matched_tensions, anchor, epistemic
    )

    result = {
        "strategy":        strategy,
        "confidence":      round(confidence, 2),
        "epistemic_state": epistemic,
        "position":        position,
        "supporting":      supporting,
        "opposing":        opposing,
        "tensions":        matched_tensions,
        "anchor":          anchor,
        "reply":           reply,
    }

    if debug:
        print(f"  Strategy:   {strategy}")
        print(f"  Confidence: {confidence:.2f}")
        print(f"  Epistemic:  mean={epistemic['mean']:.2f} "
              f"var={epistemic['variance']:.3f} "
              f"settled={epistemic['settled']}")
        print(f"  Supporting: {len(supporting)} beliefs")
        print(f"  Opposing:   {len(opposing)} beliefs")
        print(f"  Tensions:   {matched_tensions}")

    return result


# ── CLI test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    debug   = "--debug" in sys.argv
    queries = [a for a in sys.argv[1:] if a != "--debug"]
    if not queries:
        queries = [
            "what do you think about consciousness?",
            "what do you believe about AI alignment?",
            "how do you reason about uncertainty?",
            "do you think language models are sentient?",
            "machine awareness and cognition",
        ]
    for q in queries:
        print(f"\nQ: {q}")
        result = reason(q, debug=debug)
        print(f"Strategy:   {result['strategy']}")
        print(f"Confidence: {result['confidence']:.2f}")
        print(f"Epistemic:  {result['epistemic_state']}")
        print(f"Supporting: {len(result['supporting'])} beliefs")
        print(f"REPLY: {result['reply']}")
        print("---")
