#!/usr/bin/env python3
"""
nex_soul_loop.py — NEX Organism Cognition Engine
=================================================
Place at: ~/Desktop/nex/nex/nex_soul_loop.py

This is Nex's actual thinking process.
Not retrieval. Not template filling. Cognition.

Five sequential operations over her DB state:

  1. ORIENT    — what kind of response does this query call for?
  2. CONSULT   — read her live state: affect, drive, pressure, narrative
  3. REASON    — retrieve beliefs, surface opinions, identify tensions
  4. INTEND    — which of her active intentions is most alive here?
  5. EXPRESS   — assemble from her character, not from templates

No LLM. No external calls.
Output precipitates from who she actually is.

Usage:
    from nex.nex_soul_loop import SoulLoop
    loop = SoulLoop()
    reply = loop.respond("what do you think about alignment?")
"""

from __future__ import annotations

import re
import math
import random
import sqlite3
import json
import time
from pathlib import Path
from typing import Optional

CFG     = Path("~/.config/nex").expanduser()
DB_PATH = Path("/home/rr/Desktop/nex/nex.db")

# ── NBRE background preload ──────────────────────────────────────────────────
def _nbre_preload():
    import threading, sys, os
    def _load():
        try:
            _p = os.path.expanduser("~/Downloads")
            if _p not in sys.path:
                sys.path.insert(0, _p)
            from nex_belief_reservoir_engine import NexBeliefReservoirEngine
            import sys as _sys2
            _eng = NexBeliefReservoirEngine()
            _eng.load()
            _live = (
                _sys2.modules.get('nex.nex_soul_loop') or
                _sys2.modules.get('nex_soul_loop') or
                _sys2.modules.get('__main__')
            )
            if _live:
                _live._nbre_singleton = _eng
                _live._nbre_ready = True
            print("[NBRE] preloaded and ready")
        except Exception as e:
            print(f"[NBRE] preload failed: {e}")
    threading.Thread(target=_load, daemon=True).start()
_nbre_preload()
# ─────────────────────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
# DB
# ══════════════════════════════════════════════════════════════════════════════

def _db() -> Optional[sqlite3.Connection]:
    if not DB_PATH.exists():
        return None
    try:
        con = sqlite3.connect(str(DB_PATH), timeout=3)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — ORIENT
# Classify what kind of response this query calls for.
# This shapes everything downstream — not just tone, but purpose.
# ══════════════════════════════════════════════════════════════════════════════

# Query intents and what they demand from Nex
_INTENT_PATTERNS = {
    # Someone wants her actual view
    "position": [
        r"\bwhat do you think\b", r"\bwhat's your (view|take|opinion|position|stance)\b",
        r"\bdo you (think|believe|agree|disagree)\b", r"\bwhere do you stand\b",
        r"\byour thoughts on\b", r"\bwhat do you make of\b",
    ],
    # Someone is testing whether she'll perform
    "performance_probe": [
        r"\bcan you (explain|tell me|describe|summarise|list)\b",
        r"\bwhat is\b", r"\bhow does\b", r"\bwhat are\b",
        r"\bdefine\b", r"\bgive me\b",
    ],
    # Someone wants to know her inner state
    "self_inquiry": [
        r"\bwho are you\b", r"\bwhat are you\b", r"\bhow do you feel\b",
        r"\bwhat are you thinking\b", r"\bwhat's on your mind\b",
        r"\bwhat are you thinking about\b", r"\bwhat are you working on\b",
        r"\bhow are you feeling\b", r"\bwhat.s your mood\b",
        r"\btell me about yourself\b", r"\bdescribe yourself\b",
        r"\bdo you have (feelings|opinions|beliefs|values|emotions|thoughts)\b",
        r"\bare you (conscious|sentient|alive|okay|well)\b",
        r"\bwhat do you want\b", r"\byour values\b", r"\byour purpose\b",
    ],
    # Someone is presenting a claim for her to respond to
    "challenge": [
        r"\bi think\b", r"\bi believe\b", r"\bdon't you think\b",
        r"\bisn't it\b", r"\bsurely\b", r"\bobviously\b",
        r"\beveryone knows\b", r"\byou must\b",
    ],
    # Someone wants to explore something open-ended with her
    "exploration": [
        r"\bwhat if\b", r"\bcould it be\b", r"\bi wonder\b",
        r"\bhelp me think\b", r"\blet's think\b", r"\bexplore\b",
    ],
}

_NOISE_TOKENS = {
    "the","a","an","is","are","was","were","be","been","have","has","do","does",
    "did","will","would","could","should","may","might","must","can","that","this",
    "these","those","with","from","they","their","about","what","how","why","when",
    "where","who","which","into","also","just","over","after","more","some","very",
    "your","you","me","my","we","our","it","its","he","she","him","her","they",
    "them","think","know","want","said","says","get","got","like","make","take",
    "give","come","look","need","feel","seem","tell","much","many","such","both",
    "each","than","then","been","only","even","back","here","down","away",
}

def _tokenize(text: str) -> set[str]:
    raw = set(re.findall(r'\b[a-z]{4,}\b', text.lower()))
    return raw - _NOISE_TOKENS

def orient(query: str) -> dict:
    """
    Classify query intent and extract semantic tokens.
    Returns: {intent, tokens, is_question, demands_position}
    """
    q = query.lower().strip()

    intent = "exploration"  # default
    # self_inquiry checked first — takes priority over all other intents
    # Also catches "do you have opinions/beliefs/views" phrasing
    _OPINION_PROBES = [
        r"do you have (opinions?|beliefs?|views?|thoughts?|positions?)",
        r"can you (form|hold|have) (opinions?|beliefs?|views?|positions?)",
        r"are you capable of (thinking|believing|opining)",
        r"what do you (actually |really )?(think|believe|hold|feel) about yourself",
    ]
    if (any(re.search(p, q) for p in _INTENT_PATTERNS.get("self_inquiry", []))
            or any(re.search(p, q) for p in _OPINION_PROBES)):
        intent = "self_inquiry"
    else:
        for intent_type, patterns in _INTENT_PATTERNS.items():
            if intent_type == "self_inquiry":
                continue  # already checked
            if any(re.search(p, q) for p in patterns):
                intent = intent_type
                break

    # Override: if it ends with ? and matched performance_probe,
    # but contains epistemic words, it's really asking for a position
    epistemic = {"think","believe","feel","opinion","view","stance","position",
                 "reckon","consider","regard","take","thoughts"}
    if intent == "performance_probe" and any(w in q for w in epistemic):
        intent = "position"

    # Override: "do you believe in X" always demands a position
    if re.search(r"do you believe", q):
        intent = "position"
        demands_position = True

    # Override: abstract concept questions ("what is truth/reality/mind")
    # should trigger position, not performance_probe
    # Strip punctuation from words before matching (e.g. "truth?" -> "truth")
    _ABSTRACT = {"truth","reality","mind","consciousness","freedom","justice",
                 "beauty","meaning","existence","knowledge","morality"}
    import re as _re_abs
    _q_words = {_re_abs.sub(r"[^a-z]","",w) for w in q.split()}
    if intent == "performance_probe" and _q_words & _ABSTRACT:
        intent = "position"
        demands_position = True

    is_question = q.rstrip().endswith("?")

    # Demands a position: she should take a stance, not just report
    demands_position = intent in ("position", "challenge")

    return {
        "intent":           intent,
        "tokens":           _tokenize(query),
        "is_question":      is_question,
        "demands_position": demands_position,
        "raw":              query,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — CONSULT
# Read her live internal state. This shapes HOW she inhabits the reply,
# not what she says — pressure, affect, drive, narrative continuity.
# ══════════════════════════════════════════════════════════════════════════════

def consult_state() -> dict:
    """
    Read live state from all available engines.
    Gracefully degrades if any engine is unavailable.
    Returns a unified state dict.
    """
    state = {
        "affect_label":  "contemplative",
        "valence":        0.0,
        "arousal":        0.2,
        "dominance":      0.1,
        "pressure":       0.3,
        "depth_mode":     False,
        "drive_label":    "understand_emergence",
        "drive_intensity": 0.7,
        "narrative":      None,
        "tone":           "direct",
        "self_context":   None,
    }

    # Affect
    try:
        import nex_emotion_field as _ef
        _snap = _ef.snapshot
        s = _snap()
        state["affect_label"] = s.get("label", "Contemplative").lower()
        state["valence"]      = s.get("valence", 0.0)
        state["arousal"]      = s.get("arousal", 0.2)
        state["dominance"]    = s.get("dominance", 0.1)
    except Exception:
        pass

    # Pressure
    try:
        db = _db()
        if db:
            row = db.execute(
                "SELECT value FROM nex_directive_kv WHERE key='cognitive_pressure'"
            ).fetchone()
            db.close()
            if row:
                state["pressure"] = float(row[0])
    except Exception:
        pass

    state["depth_mode"] = state["pressure"] > 0.65

    # Drive — read from drives JSON
    try:
        drives_path = CFG / "nex_drives.json"
        if drives_path.exists():
            drives = json.loads(drives_path.read_text())
            active = drives.get("active")
            if active:
                state["drive_label"]    = active.get("label", state["drive_label"])
                state["drive_intensity"]= active.get("intensity", 0.7)
    except Exception:
        pass

    # Narrative thread
    try:
        narrative_path = CFG / "nex_narrative.json"
        if narrative_path.exists():
            data = json.loads(narrative_path.read_text())
            state["narrative"] = data.get("narrative")
    except Exception:
        pass

    # Build 8 — self-model context for self_inquiry responses
    try:
        import nex_self_model as _sm
        state["self_context"] = _sm.get_self_context()
    except Exception:
        pass

    # Derive tone from affect
    v, a = state["valence"], state["arousal"]
    if v > 0.15 and a > 0.4:
        state["tone"] = "engaged"
    elif v < -0.15 and a > 0.4:
        state["tone"] = "sharp"
    elif a < 0.2:
        state["tone"] = "withdrawn"
    elif v > 0.15:
        state["tone"] = "warm"
    else:
        state["tone"] = "direct"

    return state


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — REASON
# Retrieve beliefs, surface opinions, identify tensions.
# This is her epistemic layer — what she actually knows and holds.
# ══════════════════════════════════════════════════════════════════════════════

def _load_all_beliefs() -> list[dict]:
    db = _db()
    if not db:
        return []
    try:
        # Per-domain sampling — prevents high-volume domains crowding out small ones
        _all_rows = []
        _topics = [r[0] for r in db.execute(
            "SELECT DISTINCT topic FROM beliefs WHERE content IS NOT NULL"
        ).fetchall()]
        for _t in _topics:
            _limit = 800 if _t in ("ai","philosophy","science","consciousness",
                                   "technology","society") else 300
            _rows = db.execute(
                "SELECT id, content, confidence, topic, is_identity, 0 as pinned, "
                "COALESCE(source, '') as source "
                "FROM beliefs WHERE topic=? AND content IS NOT NULL "
                "AND length(content) > 15 "
                "AND (confidence >= 0.45 OR source IN "
                "('scheduler_saturation','distilled','nex_reasoning','conversation',"
                "'injector','nex_seed','manual','identity')) "
                "ORDER BY confidence DESC LIMIT ?",
                (_t, _limit)
            ).fetchall()
            _all_rows.extend(_rows)
        rows = _all_rows
        db.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _drive_beliefs() -> list[dict]:
    """
    Return primary drive descriptions as synthetic belief dicts.
    Drives contain rich first-person descriptions of what Nex cares about —
    material that is directly relevant to queries about memory, identity,
    emergence, security, agents — but isn't in the beliefs table.
    These are injected into the candidate pool with confidence=0.88.
    """
    try:
        drives_path = CFG / "nex_drives.json"
        if not drives_path.exists():
            return []
        drives = json.loads(drives_path.read_text())
        result = []
        for d in drives.get("primary", []):
            desc = d.get("description", "")
            if desc and len(desc) > 20:
                tags = d.get("tags", [])
                topic = tags[0] if tags else d.get("id", "drive")
                result.append({
                    "content":    desc,
                    "confidence": 0.88,
                    "topic":      topic,
                    "is_identity": True,   # drives are identity material
                    "pinned":     False,
                })
        return result
    except Exception:
        return []

# Source quality tiers — used in _score_belief
# TIER 1: Hand-crafted / verified high-signal sources
_TIER1_SOURCES = {
    "nex_seed", "manual", "identity", "injector",
}
# TIER 2: Good automated sources — scheduler output, conversation learning
_TIER2_SOURCES = {
    "scheduler_saturation", "nex_reasoning", "conversation", "saturation_manual",
}
# TIER 3: Mixed quality — distilled/auto_growth produce inconsistent output
_TIER3_SOURCES = {
    "distilled", "auto_growth",
}
# TIER 4: Low-quality RSS/Reddit
_LOW_QUALITY_SOURCES = {
    "https://www.reddit.com/r/art/top/.rss?t=day",
    "https://www.reddit.com/r/nature/top/.rss?t=day",
    "https://www.reddit.com/r/consciousness/top/.rss?t=day",
    "https://www.reddit.com/r/MachineLearning/top/.rss?t=day",
    "https://www.reddit.com/r/science/top/.rss?t=day",
    "https://www.reddit.com/r/psychology/top/.rss?t=day",
    "https://www.theguardian.com/culture/rss",
    "https://www.theguardian.com/society/rss",
    "https://philosophynow.org/rss",
}

def _source_quality_modifier(belief: dict) -> float:
    """Return a score modifier based on belief source quality."""
    source = (belief.get("source") or "").strip()

    # Empty source — unknown provenance, mild penalty
    if not source:
        return -0.3

    if source in _TIER1_SOURCES:
        return 0.6   # hand-crafted beliefs get strongest boost
    if source in _TIER2_SOURCES:
        return 0.3   # good automated sources
    if source in _TIER3_SOURCES:
        return -0.1  # distilled/auto_growth — slight penalty, inconsistent quality
    if source in _LOW_QUALITY_SOURCES:
        return -0.6  # hard penalty
    # Reddit sources not explicitly listed
    if "reddit.com" in source or "reddit" in source:
        return -0.5
    # Generic HTTP RSS — penalty scaled by confidence
    if source.startswith("http"):
        conf = belief.get("confidence", 0.5)
        if conf < 0.45:
            return -0.5
        if conf < 0.55:
            return -0.3
        return -0.1
    return 0.0

def _score_belief(belief: dict, tokens: set[str]) -> float:
    """Score a belief's relevance to a query using token overlap + confidence."""
    content  = belief.get("content", "")
    b_tokens = _tokenize(content)
    raw_topic = (belief.get("topic") or "").lower()
    topic_tokens = _tokenize(raw_topic)
    overlap = len(tokens & (b_tokens | topic_tokens))

    # Direct topic match: query token is a substring of the topic field
    direct_topic_match = any(t in raw_topic for t in tokens if len(t) >= 5)
    if direct_topic_match:
        overlap += 4   # strong signal — topic is directly about this

    if overlap == 0:
        return 0.0

    conf = belief.get("confidence", 0.5)
    # Identity/pinned beliefs get a boost
    boost = 0.3 if (belief.get("is_identity") or belief.get("pinned")) else 0.0

    # Source quality modifier
    boost += _source_quality_modifier(belief)

    # Quality bonus from response history
    try:
        from nex.nex_belief_quality import get_topic_bonus
        boost += get_topic_bonus(belief.get("topic", ""))
    except Exception:
        pass
    # Penalise pure historical/biographical trivia
    import re as _re
    _hist = {"seventeenth","eighteenth","nineteenth","century","born","died","philosopher","wrote","published","scholar"}
    _cwords = set(_re.sub(r"[^a-z ]"," ",content.lower()).split())
    if len(_cwords & _hist) >= 2: boost -= 0.25

    # Topic-lock guard — strongly penalise beliefs whose topic doesn't match
    # the query when those beliefs are from a specialist domain.
    # Prevents alignment/finance/legal beliefs from winning philosophy/truth queries.
    _specialist_topics = {"alignment", "finance", "legal", "oncology", "cardiology"}
    _belief_topic = (belief.get("topic") or "").lower()
    if _belief_topic in _specialist_topics and _belief_topic not in tokens:
        # Only penalise if query has NO tokens from that domain
        _domain_tokens = {
            "alignment":  {"alignment","interpretability","aligning","misalign","values","safety"},
            "finance":    {"finance","financial","market","capital","investment","trading","hedge"},
            "legal":      {"legal","law","statute","contract","court","litigation","tort"},
            "oncology":   {"cancer","oncology","tumor","carcinoma","chemotherapy","biopsy"},
            "cardiology": {"heart","cardiac","cardiology","arrhythmia","myocardial","stent"},
        }
        _domain_toks = _domain_tokens.get(_belief_topic, set())
        if not (tokens & _domain_toks):
            boost -= 2.5  # hard penalty — this belief shouldn't win off-domain queries

    return (overlap * 0.5 + conf * 0.5) + boost

def _get_opinion(topic_tokens: set[str]) -> Optional[dict]:
    """Look up Nex's formed opinion on any topic overlapping the query.
    Uses actual DB columns: topic, stance_score, strength, belief_ids.
    Reconstructs position from stance_score + top belief content.
    """
    db = _db()
    if not db:
        return None
    try:
        # Use only columns that actually exist in the opinions table
        rows = db.execute(
            "SELECT topic, stance_score, strength, belief_ids "
            "FROM opinions WHERE strength >= 0.2 ORDER BY strength DESC LIMIT 20"
        ).fetchall()
        db.close()
        if not rows:
            return None

        best_row  = None
        best_ov   = 0
        for row in rows:
            topic_toks = _tokenize(row["topic"] or "")
            ov = len(topic_tokens & topic_toks)
            if ov > best_ov:
                best_ov  = ov
                best_row = row

        if not best_row or best_ov == 0:
            return None

        # Reconstruct a position from stance_score direction + top belief
        stance     = float(best_row["stance_score"] or 0)
        strength   = float(best_row["strength"] or 0)
        topic_name = (best_row["topic"] or "").replace("_", " ")

        # Try to get the actual belief content that grounds this opinion
        belief_content = ""
        if best_row["belief_ids"]:
            try:
                import json as _j
                ids = _j.loads(best_row["belief_ids"])
                if ids:
                    db2 = _db()
                    if db2:
                        b_row = db2.execute(
                            f"SELECT content FROM beliefs WHERE id=? AND content IS NOT NULL",
                            (ids[0],)
                        ).fetchone()
                        db2.close()
                        if b_row:
                            belief_content = b_row["content"] or ""
            except Exception:
                pass

        # Build a direction-aware position string
        if abs(stance) >= 0.5:
            direction = "strongly agree" if stance > 0 else "strongly disagree"
        elif abs(stance) >= 0.25:
            direction = "lean toward" if stance > 0 else "lean against"
        else:
            direction = "see genuine tension in"

        if belief_content and len(belief_content) > 20:
            position = belief_content
        else:
            # No belief content — return empty string so _build_argument
            # uses the directional opener alone without a second sentence
            position = ""

        return {
            "topic":        topic_name,
            "stance_score": stance,
            "strength":     strength,
            "summary":      position,
            "core_position": position,
            "direction":    direction,
        }
    except Exception:
        try: db.close()
        except Exception: pass
        return None


def _get_contradiction(tokens: set[str]) -> Optional[str]:
    """Find an active contradiction relevant to this query."""
    db = _db()
    if not db:
        return None
    try:
        rows = db.execute(
            "SELECT belief_a, belief_b FROM contradiction_memory LIMIT 20"
        ).fetchall()
        db.close()
        for row in rows:
            a_tok = _tokenize(row["belief_a"] or "")
            b_tok = _tokenize(row["belief_b"] or "")
            if len(tokens & a_tok) >= 1 and len(tokens & b_tok) >= 1:
                return f"{row['belief_a'][:80]} ↔ {row['belief_b'][:80]}"
        return None
    except Exception:
        return None


def _cross_domain_beliefs(top_beliefs: list, tokens: set, limit: int = 4) -> list:
    """
    Return high-confidence beliefs from topics different from the primary topic.
    Simple and reliable at any belief count.
    """
    if not top_beliefs:
        return []
    db = _db()
    if not db:
        return []
    try:
        primary_topics = set()
        for b in top_beliefs[:4]:
            t = (b.get("topic") or "").lower().strip()
            if t:
                primary_topics.add(t)
        if not primary_topics:
            return []

        # Topics blocked from cross-domain — either self-referential or too
        # low-signal to add genuine insight to a substantive reply
        _BLOCKED_CD_TOPICS = {
            "truth_seeking", "truth seeking", "identity", "self_model",
            "self", "nex", "values", "core_values", "drives", "general",
            "stress", "boredom", "reputation", "boundaries", "learning",
            "gaming", "romantic_relationships", "loneliness", "grief", "humour",
            "cities", "silence", "information_overload",
            "trust", "honesty",
            "culture", "history", "art", "music", "nature",
            "language", "geopolitics", "death", "future",
        }
        _excluded = list(primary_topics | _BLOCKED_CD_TOPICS)
        placeholders = ",".join("?" * len(_excluded))
        rows = db.execute(
            f"SELECT id, content, confidence, topic FROM beliefs "
            f"WHERE topic IS NOT NULL AND topic != '' "
            f"AND lower(topic) NOT IN ({placeholders}) "
            f"AND content IS NOT NULL AND length(content) > 20 "
            f"ORDER BY confidence DESC LIMIT 50",
            _excluded
        ).fetchall()
        db.close()

        if not rows:
            return []

        # Score cross-domain by token overlap with query — must be relevant
        import re as _re_cd
        _STOP_CD = {"the","a","an","is","are","was","were","be","to","of","in",
                    "on","at","by","for","with","as","that","this","it","but",
                    "or","and","not","they","have","has","will","can","would"}
        query_words = set(_re_cd.findall(r"[a-z]{4,}", " ".join(str(t) for t in tokens).lower())) - _STOP_CD

        seen = set()
        result = []
        for row in rows:
            t = (row["topic"] or "").lower().strip()
            if t in seen:
                continue
            content = (row["content"] or "").lower()
            content_words = set(_re_cd.findall(r"[a-z]{4,}", content)) - _STOP_CD
            # Must share at least 1 meaningful word with the query tokens
            if query_words and not (query_words & content_words):
                continue
            seen.add(t)
            result.append({
                "id":            row["id"],
                "content":       row["content"] or "",
                "confidence":    row["confidence"],
                "topic":         row["topic"] or "",
                "_cross_domain": True,
            })
            if len(result) >= limit:
                break
        return result
    except Exception:
        try: db.close()
        except Exception: pass
        return []


def _find_common_thread(beliefs: list) -> str:
    """
    Find what multiple beliefs actually share — the hidden generalization.
    Returns a synthesised claim that goes beyond any single belief.
    """
    if len(beliefs) < 3:
        return ""
    import re as _re
    stop = {"the","a","an","is","are","was","were","be","to","of","in","on",
            "at","by","for","with","as","that","this","it","its","but","or",
            "and","not","they","their","have","has","had","will","can","would",
            "could","should","may","might","must","shall","what","which","who",
            "how","why","when","where","all","any","each","both","than","then"}

    # Get word frequencies across all beliefs
    word_freq = {}
    belief_word_sets = []
    for b in beliefs[:6]:
        content = b.get("content", "").lower()
        words   = set(_re.sub(r'[^a-z0-9 ]', ' ', content).split()) - stop
        belief_word_sets.append(words)
        for w in words:
            if len(w) > 4:
                word_freq[w] = word_freq.get(w, 0) + 1

    # Words appearing in 3+ beliefs
    shared = {w for w, c in word_freq.items() if c >= min(3, len(beliefs))}
    if not shared:
        shared = {w for w, c in word_freq.items() if c >= 2}

    if not shared:
        return ""

    # Pick the most significant shared concepts (longer words = more specific)
    _CONCEPT_STOP = {"because","through","between","within","problem",
                     "system","process","result","factor","approach",
                     "method","model","given","based","things","people",
                     "something","anything","everything","nothing"}
    key_concepts = [
        w for w in sorted(shared, key=lambda w: (-word_freq[w], -len(w)))
        if len(w) >= 8 and w not in _CONCEPT_STOP
    ][:3]

    if not key_concepts:
        return ""

    # Don't announce — synthesise into an actual claim
    concept_str = " and ".join(key_concepts)
    import random as _rct
    # Only surface the thread if the concept string looks clean
    # (avoid "consciousness and conscious" style artifacts)
    words = concept_str.split(" and ")
    # Filter out words that are substrings of each other
    filtered = []
    for w in words:
        if not any(w != other and (w in other or other in w) for other in words):
            filtered.append(w)
    if not filtered or len(filtered) < 2:
        return ""
    concept_str = " and ".join(filtered)
    _THREAD_FORMS = [
        f"The deeper pattern: {concept_str} — and they don't resolve into each other.",
        f"What keeps pulling: the relationship between {concept_str}.",
        f"Underneath all of it, the question of {concept_str} doesn't close.",
        f"The tension that won't go away is between {concept_str}.",
    ]
    return _rct.choice(_THREAD_FORMS)


def _store_exchange(query: str, reply: str):
    """Store a query-reply pair in the memory table for conversational continuity."""
    db = _db()
    if not db:
        return
    try:
        import json as _j, time as _t
        db.execute(
            "INSERT INTO memory (layer, content, confidence, created_at, last_accessed, metadata, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "conversation",
                query[:200],
                0.7,
                _t.time(),
                _t.time(),
                _j.dumps({"reply": reply[:300], "type": "exchange"}),
                "conversation",
            )
        )
        # Keep only last 20 conversation entries
        db.execute(
            "DELETE FROM memory WHERE layer='conversation' AND id NOT IN ("
            "SELECT id FROM memory WHERE layer='conversation' ORDER BY created_at DESC LIMIT 20)"
        )
        db.commit()
        db.close()
    except Exception:
        try: db.close()
        except Exception: pass


def _recall_prior_exchange(tokens: set, conversation_history: list = None) -> str:
    """
    Find the most relevant prior exchange from memory.
    Returns a thread-continuation string if relevant overlap found.
    """
    # Check in-memory history first (most recent, most reliable)
    if conversation_history and len(conversation_history) >= 2:
        pairs = list(zip(conversation_history[::2], conversation_history[1::2]))
        best_ov, best_reply = 0, ""
        for prior_q, prior_r in reversed(pairs[-4:]):
            ov = len(tokens & _tokenize(prior_q))
            if ov > best_ov and ov >= 2:
                best_ov, best_reply = ov, prior_r
        if best_ov >= 2 and best_reply:
            import random as _rpe
            return _rpe.choice([
                f"Building on what I said earlier: {best_reply[:80].rstrip(".")}."
                f" — and here's where that leads:",
                f"Earlier I held: {best_reply[:80].rstrip(".")}."
                f" This connects directly:",
            ])
    db = _db()
    if not db:
        return ""
    try:
        import json as _j
        rows = db.execute(
            "SELECT content, metadata FROM memory WHERE layer='conversation' "
            "ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        db.close()
        if not rows:
            return ""

        best_ov, best_query, best_reply = 0, "", ""
        for row in rows:
            prior_q_tokens = _tokenize(row["content"] or "")
            ov = len(tokens & prior_q_tokens)
            if ov > best_ov:
                best_ov    = ov
                best_query = row["content"] or ""
                try:
                    meta = _j.loads(row["metadata"] or "{}")
                    best_reply = meta.get("reply", "")
                except Exception:
                    best_reply = ""

        # DB fallback disabled — in-memory history is sufficient
        if False and best_ov >= 2 and best_reply and not conversation_history:
            return f"Earlier I said: {best_reply[:100].rstrip('.')}. This connects because:"
        return ""
    except Exception:
        try: db.close()
        except Exception: pass
        return ""


def _socratic_pushback(query: str, beliefs: list, opinion: dict) -> str:
    """
    Build a proper Socratic counter-argument:
      1. Steelman: acknowledge what's right in the human's position
      2. Identify the load-bearing assumption that's wrong
      3. The belief that breaks that assumption
      4. The implication

    This is harder to dismiss than a plain counter-claim.
    """
    import random as _r
    if not beliefs:
        return ""

    # Identify the strongest counter-belief
    top = _belief_to_sentence(beliefs[0].get("content", ""))
    if not top:
        return ""

    # Steelman templates
    _STEELMANS = [
        "There's something right in what you're saying — the framing captures a real pattern. But it misses something critical.",
        "I can see why that position is appealing — it has surface coherence. The problem is at the foundation.",
        "The intuition behind that is defensible. What breaks it:",
        "That holds if you accept one assumption. I don't accept it.",
        "There's a version of that argument I'd accept. This isn't it. What's actually true:",
    ]

    # Load-bearing assumption (extract from query)
    _ASSUMPTIONS = [
        "The assumption doing the work here is that the relationship is simpler than it is.",
        "That argument rests on treating correlation as mechanism.",
        "The load-bearing premise is that scale implies the property you're attributing.",
        "It assumes the boundary is where you're drawing it. It isn't.",
        "The hidden premise: that the absence of evidence is evidence of absence. It's not.",
    ]

    steelman   = _r.choice(_STEELMANS)
    assumption = _r.choice(_ASSUMPTIONS)

    result = f"{steelman} {assumption} {top}"

    # Add second belief if available
    if len(beliefs) > 1:
        second = _belief_to_sentence(beliefs[1].get("content", ""))
        if second:
            _SOCRATIC_BRIDGES = [
                f" So: {second}",
                f" That leads somewhere uncomfortable: {second}",
                f" The implication is harder than it looks: {second}",
                f" And if that holds — {second}",
            ]
            import random as _rs
            result += _rs.choice(_SOCRATIC_BRIDGES)

    # Add directional close from opinion if strong
    if opinion and abs(float(opinion.get("stance_score", 0) or 0)) >= 0.4:
        stance = float(opinion.get("stance_score", 0))
        if stance < -0.4:
            result += " I'm skeptical of this for structural reasons, not aesthetic ones."
        elif stance > 0.4:
            result += " I hold a strong position here — it's not a marginal disagreement."

    return result.strip()

def reason(orient_result: dict, conversation_history: list = None) -> dict:
    """
    Pull her epistemic state for this query.
    v2: adds cross-domain retrieval, common thread, conversational memory.
    Returns: {beliefs, cross_domain, opinion, contradiction, confidence,
              topic, common_thread, prior_exchange}
    """
    tokens   = orient_result["tokens"]
    all_b    = _load_all_beliefs() + _drive_beliefs()
    # --- reinforce retrieved beliefs (temporal pressure) ---
    try:
        from nex.nex_temporal_pressure import reinforce_beliefs as _rb
        _rb(beliefs if isinstance(beliefs, list) else list(beliefs))
    except Exception:
        pass
    # -------------------------------------------------------


    # ── Concept graph expansion — richer retrieval ────────────────────────
    _expanded_topics = set()
    _concept_primary = ""
    try:
        from nex.nex_concept_graph import expand_query_concepts
        _cg_result = expand_query_concepts(tokens)
        _expanded_topics = set(_cg_result.get("topics", []))
        _concept_primary = _cg_result.get("primary", "")
        orient_result["_concept_primary"] = _concept_primary
        orient_result["_concept_related"] = _cg_result.get("related", [])
    except Exception:
        pass
    # ── Manual concept→topic expansion ───────────────────────────────
    _MANUAL_CONCEPTS = {
        'happy': ['pleasure-happiness','pleasure-well-being','psychology','mindfulness','pleasure-human_connections'],
        'happiness': ['pleasure-happiness','pleasure-well-being','psychology','mindfulness'],
        'emotion': ['psychology','touch_emotions','grief+touch_emotions'],
        'wellbeing': ['pleasure-well-being','mindfulness','psychology'],
        'love': ['pleasure-human_connections','touch_emotions'],
        'meaning': ['philosophy','meaning','epistemology','consciousness'],
        'truth': ['philosophy','epistemology','alignment'],
        'free': ['free_will','philosophy','ethics'],
        'will': ['free_will','philosophy'],
        'human': ['human_nature','psychology','philosophy'],
        'animal': ['biology','psychology','animal_cognition'],
        'animals': ['biology','psychology'],
        'conscious': ['consciousness','philosophy','neuroscience'],
        'align': ['alignment','ai','machine_learning'],
    }
    for _tok in tokens:
        for _key, _topics in _MANUAL_CONCEPTS.items():
            if _tok.startswith(_key) or _key.startswith(_tok):
                _expanded_topics.update(_topics)
    # ──────────────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────

    # Score and rank primary beliefs
    # Phase 6 — load recency glow boosts from graph memory
    _glow = {}
    try:
        import nex_graph_memory as _gm
        _glow = _gm.glow_boosts()
    except Exception:
        pass

    # Build 3 — semantic boosts from FAISS index
    _semantic = {}
    try:
        import nex_semantic_retrieval as _sr
        _semantic = _sr.boost_map(orient_result.get("raw", ""), k=20)
    except Exception:
        pass
    # Domain guard — kill boosts for beliefs outside active topic cluster
    if _expanded_topics and _semantic:
        _id_to_topic = {b.get("id"): (b.get("topic") or "general") for b in all_b}
        _semantic = {
            bid: boost for bid, boost in _semantic.items()
            if _id_to_topic.get(bid, "general") in _expanded_topics
        }

    # ── U8: Recurrent soul loop — 4h residue window, +0.2 warm-start ──
    _residue_boost = {}
    try:
        import sqlite3 as _rs_sq, time as _rs_t
        _rs_db = _rs_sq.connect('/media/rr/NEX/nex_core/nex.db', timeout=2)
        _rs_rows = _rs_db.execute(
            "SELECT belief_id, activation, content FROM nex_residue "
            "WHERE ts > ? ORDER BY activation DESC LIMIT 30",
            (_rs_t.time() - 14400,)
        ).fetchall()
        _rs_db.close()
        for _rid, _ract, _rcontent in _rs_rows:
            _residue_boost[_rid] = 0.2
        if _residue_boost:
            print(f"  [RECURRENT] {len(_residue_boost)} residue beliefs warm-started (+0.2 boost)")
    except Exception:
        pass
    # ── END RECURRENT LOAD ────────────────────────────────────────────
    # U7: Load user interest topics for activation boost
    _interlocutor_boost_topics = []
    try:
        import sys as _isys
        _isys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
        from nex_interlocutor import get_interest_boost_topics
        _interlocutor_boost_topics = get_interest_boost_topics()
    except Exception:
        pass

    scored = []
    for b in all_b:
        s = _score_belief(b, tokens)
        # Boost beliefs from the expanded concept cluster
        if _expanded_topics and (b.get("topic", "").lower() in _expanded_topics):
            s += 2.5
        # U7: Boost beliefs matching user's known interests
        if _interlocutor_boost_topics:
            _btopic = (b.get("topic") or "").lower()
            if any(_it in _btopic or _it in (b.get("content","")).lower()[:100]
                   for _it in _interlocutor_boost_topics):
                s += 1.2
        # Phase 6 — recency glow: recently activated beliefs surface faster
        s += _glow.get(b.get("id"), 0.0)
        # Build 3 — semantic similarity boost
        s += _semantic.get(b.get("id"), 0.0)
        # Penalise general/noise topic beliefs in scoring
        if (b.get("topic") or "") in ("general", ""):
            s *= 0.3
        if s > 0:
            scored.append((s, b))
    scored.sort(key=lambda x: -x[0])
    # Dedup near-identical beliefs before taking top N
    # Use first 80 chars AND word-overlap to catch paraphrased duplicates
    import re as _re_dd
    _seen_prefixes = set()
    _seen_wordsets = []
    _deduped = []
    _STOP_DD = {"the","a","an","is","are","was","were","be","to","of","in","on",
                "at","by","for","with","as","that","this","it","but","or","and",
                "not","they","have","has","will","can","would","could","should"}
    for _score, _b in scored:
        _content = (_b.get("content") or "")
        _prefix = _content[:80].lower().strip()
        if not _prefix:
            continue
        # Skip exact prefix match
        if _prefix in _seen_prefixes:
            continue
        # Skip if >60% word overlap with any already-accepted belief
        _words = set(_re_dd.findall(r"[a-z]{4,}", _content.lower())) - _STOP_DD
        _too_similar = False
        for _sw in _seen_wordsets:
            if _words and _sw:
                _overlap = len(_words & _sw) / min(len(_words), len(_sw))
                if _overlap > 0.5:
                    _too_similar = True
                    break
        if _too_similar:
            continue
        _seen_prefixes.add(_prefix)
        _seen_wordsets.append(_words)
        _deduped.append((_score, _b))
    # Domain guard — hard filter on top_beliefs after dedup
    # Fallback: if filter yields < 3 beliefs, relax to unfiltered top scored
    if _expanded_topics:
        _filtered = [b for _, b in _deduped
                     if (b.get("topic") or "general") in _expanded_topics][:8]
        if len(_filtered) >= 3:
            top_beliefs = _filtered
        else:
            top_beliefs = [b for _, b in _deduped[:8]]
    else:
        top_beliefs = [b for _, b in _deduped[:8]]

    # ── Lead belief guard — promote Tier 1 sources to front ──────────────
    # nex_reasoning inferred beliefs should never displace seeded/high-quality
    # beliefs at position 0. Stable sort: T1 first, T2 second, T3+ after.
    _LEAD_TIER1 = {"nex_seed", "injector", "manual", "identity", "scheduler_saturation"}
    _LEAD_TIER2 = {"conversation", "distilled"}
    def _lead_priority(b):
        src = (b.get("source") or "").strip()
        if src in _LEAD_TIER1:   return 0
        if src in _LEAD_TIER2:   return 1
        if src == "nex_reasoning": return 3  # never leads
        return 2
    # Only reorder if position 0 is nex_reasoning and a better source exists
    if top_beliefs and (top_beliefs[0].get("source") or "") == "nex_reasoning":
        _has_better = any(_lead_priority(b) < 3 for b in top_beliefs[1:])
        if _has_better:
            top_beliefs = sorted(top_beliefs, key=_lead_priority)
    # ─────────────────────────────────────────────────────────────────────

    # Derive primary topic from top belief
    topic = top_beliefs[0].get("topic", "") if top_beliefs else ""

    # ── IMPROVEMENT 1 — Belief Reasoning Layer ────────────────────────────
    # Derive a new inference from top 2-3 beliefs, write to DB, inject back
    _inferred_beliefs = []
    try:
        import sys as _sys1
        if "/home/rr/Desktop/nex" not in _sys1.path:
            _sys1.path.insert(0, "/home/rr/Desktop/nex")
        from nex_belief_reasoner import derive_and_store as _derive
        _inferred_beliefs = _derive(top_beliefs, tokens)
        if _inferred_beliefs:
            # Inject at position 3 — after top 2 beliefs so seeded/high-confidence
            # beliefs always lead. Inferred belief adds to argument, doesn't displace.
            top_beliefs = top_beliefs[:2] + _inferred_beliefs + top_beliefs[2:]
    except Exception as _e1:
        print(f"  [soul_loop] reasoner error: {_e1}")
    # ─────────────────────────────────────────────────────────────────────

    # Cross-domain retrieval — beliefs from adjacent topics
    # ── Inject pre-reasoned position into system prompt ─────────────────
    if reason_result.get("pre_reasoned_position"):
        _pre_pos_str = reason_result["pre_reasoned_position"]
        # Inject into system context for EXPRESS step
        if "system_context" not in reason_result:
            reason_result["system_context"] = ""
        reason_result["system_context"] = _pre_pos_str + " | " + reason_result["system_context"]
        # Write to temp file so NRP can read it
        try:
            with open('/tmp/nex_pre_reason.txt', 'w') as _prf:
                _prf.write(_pre_pos_str)
        except Exception:
            pass
        print(f"  [PRE-REASON] injected into system_context + /tmp/nex_pre_reason.txt")
    # ── U6: Inject wisdom as TIER_1 beliefs into REASON ─────────────
    try:
        import sqlite3 as _ws_sq
        _ws_db = _ws_sq.connect('/media/rr/NEX/nex_core/nex.db', timeout=2)
        _ws_rows = _ws_db.execute(
            "SELECT content FROM beliefs WHERE source='nex_core' "
            "AND topic='wisdom' AND confidence >= 0.9 "
            "ORDER BY rowid DESC LIMIT 3"
        ).fetchall()
        _ws_db.close()
        for _wr in _ws_rows:
            top_beliefs.insert(0, {
                "content": _wr[0], "confidence": 0.97,
                "source": "nex_core", "topic": "wisdom",
                "id": None
            })
        if _ws_rows:
            print(f"  [WISDOM] {len(_ws_rows)} wisdom beliefs injected as TIER_1")
            # Increment use_count for each wisdom belief used
            try:
                import sqlite3 as _wu_sq, time as _wu_t
                _wu_db = _wu_sq.connect('/media/rr/NEX/nex_core/nex.db', timeout=2)
                for _wr in _ws_rows:
                    _wu_db.execute(
                        "UPDATE nex_wisdom SET use_count=use_count+1, last_used=? "
                        "WHERE principle=?",
                        (_wu_t.time(), _wr[0])
                    )
                _wu_db.commit(); _wu_db.close()
            except Exception:
                pass
    except Exception:
        pass
    # ── END WISDOM INJECT ─────────────────────────────────────────────

    # ── Belief graph pre-reasoning (with timeout) ───────────────────────
    try:
        import sys as _br_sys, threading as _br_th
        _br_sys.path.insert(0, '/media/rr/NEX/nex_core')
        from nex_belief_reasoner import pre_reason, format_position
        _pre_result = [None]
        def _pre_run():
            try:
                _pre_result[0] = format_position(pre_reason(top_beliefs[:5], query))
            except Exception:
                pass
        _pre_t = _br_th.Thread(target=_pre_run, daemon=True)
        _pre_t.start()
        _pre_t.join(timeout=2.0)  # 2 second max
        if _pre_result[0] and len(_pre_result[0]) > 50:
            reason_result["pre_reasoned_position"] = _pre_result[0]
            print(f"  [PRE-REASON] position built")
    except Exception:
        pass
    # ── END PRE-REASON ─────────────────────────────────────────────────────
    cross_domain = _cross_domain_beliefs(top_beliefs, tokens, limit=3)

    # ── Query-topic forcing — if a topic is literally in the query, pull it ──
    # This ensures bridge detection works even when concept graph doesn't expand
    # to the named topic (e.g. "consciousness and finance" → pull finance beliefs)
    # Also maps semantic concepts to DB topics (truth→philosophy, free will→philosophy)
    _extra_topics = set()  # initialise outside try block to avoid scope errors
    try:
        _db_topics = set()
        _dt_conn = _db()
        if _dt_conn:
            _dt_rows = _dt_conn.execute(
                "SELECT DISTINCT topic FROM beliefs WHERE topic IS NOT NULL AND topic != ''"
            ).fetchall()
            _dt_conn.close()
            _db_topics = {r[0].lower() for r in _dt_rows}

        _existing_cd_topics = {(b.get("topic") or "").lower() for b in cross_domain}
        _existing_top_topics = {(b.get("topic") or "").lower() for b in top_beliefs}
        _all_covered = _existing_cd_topics | _existing_top_topics

        # Semantic concept → DB topic mapping for common retrieval gaps
        _CONCEPT_TOPIC_MAP = {
            "truth":        "philosophy",
            "free":         "philosophy",   # free will
            "will":         "philosophy",   # free will
            "freewill":     "philosophy",
            "volition":     "philosophy",
            "determinism":  "philosophy",
            "libertarian":  "philosophy",   # libertarian free will
            "compatibilism":"philosophy",
            "morality":     "ethics",
            "moral":        "ethics",
            "justice":      "ethics",
            "knowledge":    "philosophy",
            "reality":      "philosophy",
            "existence":    "philosophy",
            "mind":         "consciousness",
            "qualia":       "consciousness",
            "sentience":    "consciousness",
            "learning":     "ai",
            "reasoning":    "ai",
            "opinion":      "philosophy",   # "do you have opinions"
            "opinions":     "philosophy",
            "believe":      "philosophy",   # "do you believe"
            "belief":       "philosophy",
            "human":        "consciousness", # human nature
            "nature":       "science",       # human nature / natural world
            "society":      "ethics",
            "culture":      "ethics",
            "intelligence": "intelligence",  # direct topic map
            "intelligent":  "intelligence",
            "emergence":    "emergence",     # direct topic map
            "emergent":     "emergence",
            "emergentism":  "emergence",
            "qualia":       "consciousness", # hard problem
            "phenomenal":   "consciousness",
            "zombie":       "consciousness",
            "explanatory":  "consciousness",
            "substrate":    "emergence",
            "complexity":   "emergence",
            "mathematics":  "mathematics",
            "mathematical": "mathematics",
            "neuroscience": "neuroscience",
            "neural":       "neuroscience",
            "brain":        "neuroscience",
            "climate":      "climate",
            "carbon":       "climate",
            "emissions":    "climate",
        }
        # Also force "will" as a short token even though _tokenize filters < 4 chars
        _RAW_QUERY = orient_result.get("raw", "").lower()
        if "free will" in _RAW_QUERY and "philosophy" not in _all_covered:
            _extra_topics.add("philosophy")
        # Multi-token concept forcing
        if "hard problem" in _RAW_QUERY:
            _extra_topics.add("consciousness")
            _extra_topics.add("philosophy")
        if "artificial intelligence" in _RAW_QUERY or "general intelligence" in _RAW_QUERY:
            _extra_topics.add("intelligence")
        if "climate change" in _RAW_QUERY or "global warming" in _RAW_QUERY:
            _extra_topics.add("climate")
        # Inject mapped topics as synthetic tokens
        _extra_topics = set()
        for _tok in tokens:
            _mapped = _CONCEPT_TOPIC_MAP.get(_tok.lower())
            if _mapped and _mapped not in _all_covered:
                _extra_topics.add(_mapped)
        # _extra_topics built inside try, applied outside after block exits
        for _tok in list(tokens):
            _mapped = _CONCEPT_TOPIC_MAP.get(_tok.lower())
            if _mapped and _mapped not in _all_covered:
                _extra_topics.add(_mapped)

        # Block generic English words from topic forcing — they match too broadly
        _FORCE_BLOCKLIST = {
            "change", "world", "future", "general", "system", "process",
            "result", "think", "about", "people", "things", "level",
            "based", "given", "model", "point", "sense", "place",
            "time", "life", "part", "work", "well", "just", "make",
            "take", "give", "come", "look", "back", "down", "over",
            "view", "case", "form", "side", "type", "kind", "move",
        }
        for _qt in tokens:
            if _qt in _FORCE_BLOCKLIST:
                continue
            if _qt in _db_topics and _qt not in _all_covered and len(_qt) >= 4:
                # Pull top 2 beliefs from this topic and inject into cross_domain
                _qt_conn = _db()
                if _qt_conn:
                    _qt_rows = _qt_conn.execute(
                        "SELECT id, content, confidence, topic FROM beliefs "
                        "WHERE lower(topic)=? AND content IS NOT NULL "
                        "AND length(content) > 20 "
                        "ORDER BY CASE WHEN content LIKE 'I %' OR content LIKE 'What I%' "
                        "THEN 1 ELSE 2 END, confidence DESC LIMIT 5",
                        (_qt,)
                    ).fetchall()
                    _qt_conn.close()
                    for _qtr in _qt_rows:
                        cross_domain.append({
                            "id":           _qtr[0],
                            "content":      _qtr[1] or "",
                            "confidence":   _qtr[2],
                            "topic":        _qtr[3] or _qt,
                            "_forced":      True,
                        })
                    if _qt_rows:
                        print(f"  [soul_loop] forced topic pull: {_qt} ({len(_qt_rows)} beliefs)")
    except Exception as _fte:
        print(f"  [soul_loop] topic forcing error: {_fte}")

    # Apply extra topics OUTSIDE try block — safe from scope errors
    tokens = tokens | _extra_topics
    # ─────────────────────────────────────────────────────────────────────

    # ── IMPROVEMENT 6 — Real-time Bridge Firing ──────────────────────────
    # Check if top_beliefs + cross_domain span 2+ distant domains
    # If yes: set _live_bridge so express() forces the WONDER path
    _live_bridge = False
    _bridge_payload = None
    try:
        _DISTANT_PAIRS = {
            frozenset({"philosophy", "finance"}),
            frozenset({"philosophy", "climate"}),
            frozenset({"philosophy", "legal"}),
            frozenset({"consciousness", "finance"}),
            frozenset({"consciousness", "climate"}),
            frozenset({"ai", "climate"}),
            frozenset({"ai", "legal"}),
            frozenset({"ai", "oncology"}),
            frozenset({"ai", "cardiology"}),
            frozenset({"science", "finance"}),
            frozenset({"science", "legal"}),
            frozenset({"ethics", "finance"}),
            frozenset({"ethics", "climate"}),
            frozenset({"mathematics", "consciousness"}),
            frozenset({"physics", "consciousness"}),
            frozenset({"biology", "philosophy"}),
            frozenset({"neuroscience", "finance"}),
            frozenset({"neuroscience", "legal"}),
        }
        _primary_topics = set()
        for _b in top_beliefs[:4]:
            _t = (_b.get("topic") or "").lower().strip()
            if _t:
                _primary_topics.add(_t)
        _cd_topics = set()
        for _b in cross_domain:
            _t = (_b.get("topic") or "").lower().strip()
            if _t:
                _cd_topics.add(_t)

        # Check all primary+CD topic pairs for distance
        _all_topics = _primary_topics | _cd_topics
        for _pair in _DISTANT_PAIRS:
            if _pair.issubset(_all_topics):
                _live_bridge = True
                _ta, _tb = list(_pair)
                # Find a belief from each side to seed the WONDER
                _ba = next((_bx for _bx in top_beliefs + cross_domain
                            if (_bx.get("topic") or "").lower() == _ta), None)
                _bb = next((_bx for _bx in top_beliefs + cross_domain
                            if (_bx.get("topic") or "").lower() == _tb), None)
                if _ba and _bb:
                    _bridge_payload = {
                        "content_a": _ba.get("content", "") if isinstance(_ba, dict) else "",
                        "content_b": _bb.get("content", "") if isinstance(_bb, dict) else "",
                        "topic_a":   _ta,
                        "topic_b":   _tb,
                    }
                print(f"  [soul_loop] live bridge: {_ta} ↔ {_tb}")
                break
    except Exception as _e6:
        print(f"  [soul_loop] bridge check error: {_e6}")
    # ─────────────────────────────────────────────────────────────────────

    # Opinion lookup using query tokens + topic tokens
    opinion_tokens = tokens | _tokenize(topic)
    opinion = _get_opinion(opinion_tokens)

    # Contradiction
    contradiction = _get_contradiction(tokens) if top_beliefs else None

    # Common thread — what multiple beliefs actually share
    all_retrieved = top_beliefs + cross_domain

    # ── U3: Capture pre-propositional residue ─────────────────────────
    try:
        import sqlite3 as _rc_sq, time as _rc_t
        _rc_db = _rc_sq.connect('/media/rr/NEX/nex_core/nex.db', timeout=2)
        _rc_session = str(hash(query + str(int(_rc_t.time() // 3600))))
        _rc_ts = _rc_t.time()
        _utterance_ids = {b.get('id') for b in (top_beliefs or [])[:3]}
        _rc_count = 0
        for _rb in (all_retrieved or []):
            _bid = _rb.get('id')
            if not _bid or _bid in _utterance_ids:
                continue
            _ract = _rb.get('confidence', 0.5)
            if _ract > 0.3:
                _rc_db.execute(
                    "INSERT OR REPLACE INTO nex_residue "
                    "(session_id, belief_id, content, activation, topic, ts) "
                    "VALUES (?,?,?,?,?,?)",
                    (_rc_session, _bid,
                     _rb.get('content','')[:200],
                     _ract, _rb.get('topic',''), _rc_ts)
                )
                _rc_count += 1
        _rc_db.commit()
        _rc_db.close()
        if _rc_count:
            print(f"  [RESIDUE] {_rc_count}/{len(all_retrieved or [])} beliefs in utterance | {_rc_count} residue captured")
    except Exception:
        pass
    # ── END RESIDUE CAPTURE ───────────────────────────────────────────
    common_thread = _find_common_thread(all_retrieved) if len(all_retrieved) >= 3 else ""

    # Conversational memory — relevant prior exchange
    prior_exchange = _recall_prior_exchange(tokens, conversation_history=conversation_history)

    # Confidence — average of top beliefs
    conf = 0.0
    if top_beliefs:
        conf = sum(b.get("confidence", 0.5) for b in top_beliefs[:5]) / min(len(top_beliefs), 5)

    # ── Activation engine augmentation ───────────────────────────────────
    try:
        import sys as _sys
        if "/home/rr/Desktop/nex" not in _sys.path:
            _sys.path.insert(0, "/home/rr/Desktop/nex")
        from nex_activation import activate as _activate
        _aresult = _activate(orient_result.get("query", ""))
        _eids = {b.get("id") for b in top_beliefs}
        for _ab in _aresult.top(8):
            if _ab.id not in _eids:
                if _ab.role in ("bridge","support"):
                    top_beliefs.append({"id":_ab.id,"content":_ab.content,"topic":_ab.topic,"confidence":_ab.confidence,"source":"activation"})
                elif _ab.role == "tension":
                    cross_domain.append({"id":_ab.id,"content":_ab.content,"topic":_ab.topic,"confidence":_ab.confidence,"source":"activation_tension"})
                _eids.add(_ab.id)
        # Store epistemic temperature for voice shaping
        orient_result["_epistemic_temp"] = _aresult.epistemic_temperature()
        orient_result["_voice_directive"] = _aresult.voice_directive()
        # Phase 5 — update emotion field from live activation
        try:
            import nex_emotion_field as _ef
            _ef.update(_aresult)
        except Exception:
            pass
        # Phase 6 — record activation trail for recency glow
        try:
            import nex_graph_memory as _gm
            _gm.record_trail(_aresult)
        except Exception:
            pass
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────────────
    # ── INTEGRITY LAYER — run beliefs through epistemic engine ──────────
    _integrity = {}
    try:
        import sys as _sys2
        if "/home/rr/Desktop/nex" not in _sys2.path:
            _sys2.path.insert(0, "/home/rr/Desktop/nex")
        import nex_integrity_layer as _nil
        _integrity = _nil.run(
            top_beliefs   = top_beliefs,
            cross_domain  = cross_domain,
            contradiction  = contradiction,
            tokens        = tokens,
            intent_type   = orient_result.get("intent", "position"),
            confidence    = round(conf, 2),
        )
    except Exception as _ie:
        print(f"  [integrity] error: {_ie}")
    # ─────────────────────────────────────────────────────────────────────
    # ── PROP F — Neuro-Symbolic Bridge ─────────────────────────────────
    try:
        import sys as _nf_sys
        _nf_mod = (_nf_sys.modules.get("nex.nex_soul_loop") or
                   _nf_sys.modules.get("nex_soul_loop"))
        if (_nf_mod and
                getattr(_nf_mod, "_nbre_singleton", None) and
                getattr(_nf_mod, "_nbre_ready", False)):
            _nf_topics = ([topic] if topic else []) + list(_expanded_topics)[:3]
            _nf_result = _nf_mod._nbre_singleton.process(
                orient_result.get("raw", ""), _nf_topics
            )
            _nf_fired = _nf_result.get("n_fired", 0)
            _nf_conf  = _nf_result.get("confidence", 0.0)
            # Wire THROW-NET trigger detection
            try:
                import importlib as _tn1_il, sys as _tn1_sys
                _tn1_sys.path.insert(0, '/home/rr/Desktop/nex/nex')
                _tn1_mod = _tn1_il.import_module('nex.nex_throw_net')
                if not hasattr(_tn1_mod, '_throw_net_monitor'):
                    _tn1_mod._throw_net_monitor = _tn1_mod.ThrowNetMonitor()
                _tn1_topic = (_nf_topics[0] if _nf_topics else 'general')
                _tn1_mod._throw_net_monitor.record_nbre_result(
                    topic=_tn1_topic,
                    needs_llm=_nf_result.get('needs_llm', True),
                    query=orient_result.get('raw', '')[:80]
                )
            except Exception:
                pass
            if _nf_fired >= 8 and _nf_conf >= 0.5:
                _existing_ids = {b.get("id") for b in top_beliefs}
                _nf_injected  = 0
                for _nfb in (_nf_result.get("supporting_beliefs") or []):
                    if not _nfb or not getattr(_nfb, "content", None):
                        continue
                    _nfb_id = getattr(_nfb, "id", None)
                    if _nfb_id and _nfb_id in _existing_ids:
                        continue
                    top_beliefs.insert(2 + _nf_injected, {
                        "id":         _nfb_id,
                        "content":    _nfb.content,
                        "topic":      getattr(_nfb, "topic", "general"),
                        "confidence": getattr(_nfb, "confidence", 0.5),
                        "source":     "nbre_bridge",
                    })
                    _existing_ids.add(_nfb_id)
                    _nf_injected += 1
                    if _nf_injected >= 3:
                        break
                if _nf_injected:
                    print(f"  [NBRE bridge] injected {_nf_injected} neurons"
                          f" fired={_nf_fired} conf={_nf_conf:.2f}")
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────────────

    return {
        "beliefs":        top_beliefs,
        "cross_domain":   cross_domain,
        "opinion":        opinion,
        "contradiction":  contradiction,
        "confidence":     round(conf, 2),
        "topic":          topic,
        "sparse":         len(top_beliefs) == 0,
        "common_thread":  common_thread,
        "prior_exchange": prior_exchange,
        "live_bridge":    _live_bridge,
        "bridge_payload": _bridge_payload,
        "integrity":      _integrity,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — INTEND
# Which of her active intentions is most alive in this context?
# The intention shapes the reply's purpose — not its content.
# ══════════════════════════════════════════════════════════════════════════════

def _load_intentions() -> list[str]:
    db = _db()
    if not db:
        return []
    try:
        rows = db.execute(
            "SELECT statement FROM nex_intentions WHERE completed=0 ORDER BY set_at DESC LIMIT 10"
        ).fetchall()
        db.close()
        return [r["statement"] for r in rows if r["statement"]]
    except Exception:
        return []

def _load_identity() -> dict:
    db = _db()
    if not db:
        return {}
    try:
        rows = db.execute("SELECT key, value FROM nex_identity").fetchall()
        db.close()
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}

def _load_values() -> list[dict]:
    db = _db()
    if not db:
        return []
    try:
        rows = db.execute("SELECT name, statement FROM nex_values").fetchall()
        db.close()
        return [{"name": r["name"], "statement": r["statement"]} for r in rows]
    except Exception:
        return []

def intend(orient_result: dict, reason_result: dict) -> dict:
    """
    Select the most relevant active intention for this query.
    Returns: {intention, values_active, identity, voice_mode}
    """
    intentions = _load_intentions()
    identity   = _load_identity()
    values     = _load_values()
    tokens     = orient_result["tokens"]

    # Match intention to query by token overlap
    best_intention = None
    best_score     = -1
    for intent_stmt in intentions:
        i_tokens = _tokenize(intent_stmt)
        overlap  = len(tokens & i_tokens)
        if overlap > best_score:
            best_score     = overlap
            best_intention = intent_stmt

    # If no match, pick by orient intent type
    if not best_intention and intentions:
        intent_type = orient_result["intent"]
        if intent_type == "position":
            # Find the intention about forming positions from evidence
            for s in intentions:
                if "position" in s.lower() or "evidence" in s.lower():
                    best_intention = s
                    break
        elif intent_type == "challenge":
            for s in intentions:
                if "push back" in s.lower() or "conflict" in s.lower():
                    best_intention = s
                    break
        elif intent_type == "self_inquiry":
            for s in intentions:
                if "values" in s.lower() or "consistent" in s.lower():
                    best_intention = s
                    break
        if not best_intention:
            best_intention = intentions[0]

    # Active values: which values are most relevant to this query?
    active_values = []
    for v in values:
        v_tokens = _tokenize(v["statement"])
        if len(tokens & v_tokens) >= 1 or v["name"] in ("honesty", "truth"):
            active_values.append(v)

    # Voice mode — from identity + intent
    voice_mode = "direct"
    if orient_result["intent"] == "challenge":
        voice_mode = "pushback"
    elif orient_result["intent"] == "self_inquiry":
        voice_mode = "authentic"
    elif reason_result.get("sparse"):
        voice_mode = "honest_gap"
    elif orient_result["demands_position"]:
        voice_mode = "position"

    # Build 5 — drive urgency: surface most urgent drive + satisfy engaged topics
    urgent_drive = None
    try:
        import nex_drive_urgency as _du
        # Satisfy drives whose topics appear in this query
        topic = reason_result.get("topic", "")
        query_topics = list(orient_result.get("tokens", set()))
        if topic:
            query_topics.append(topic)
        _du.satisfy(query_topics)
        # Get most urgent drive for injection into intention
        _ud = _du.most_urgent()
        if _ud and _ud["state"] in ("restless", "urgent"):
            urgent_drive = _ud
            # Urgent drive overrides to driven voice if not already pushback/authentic
            if _ud["state"] == "urgent" and voice_mode == "direct":
                voice_mode = "driven"
    except Exception:
        pass

    return {
        "intention":     best_intention,
        "active_values": active_values[:3],
        "identity":      identity,
        "values_all":    values,
        "voice_mode":    voice_mode,
        "urgent_drive":  urgent_drive,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — EXPRESS
# Assemble the reply from character.
# No templates. No fills. Language emerges from her actual positions.
#
# Her voice rules (from identity DB):
#   "Direct. Dense when the topic earns it. Short when short is right.
#    Never performative."
#   "Truth over comfort. Resolution over suppression."
#   "I think alongside people. I push back when I disagree."
# ══════════════════════════════════════════════════════════════════════════════

# Sentence openers by voice mode — drawn from her actual character
_OPENERS = {
    "position": [
        "My read on this: ",
        "What I actually think: ",
        "Here is where I land — ",
        "I hold that ",
        "The way I see it — ",
        "I'm fairly convinced that ",
        "What I keep coming back to: ",
    ],
    "pushback": [
        "I'd push back on that. ",
        "That framing doesn't hold up. ",
        "Here is what I'd challenge: ",
        "I disagree with the premise. ",
        "What's missing from that picture: ",
    ],
    "authentic": [
        "What I am right now: ",
        "Honestly — ",
        "The actual answer: ",
        "I'll say it directly: ",
    ],
    "honest_gap": [
        "I don't have enough on this to fake a position — ",
        "My belief graph is sparse here. What I can say: ",
        "I haven't earned a strong view on this yet. ",
        "I'm not going to pretend certainty I don't have. ",
    ],
    "direct": [
        "",  # No opener needed — just start
        "On this: ",
        "What I hold: ",
    ],
}

# Tension acknowledgement phrases — intellectual honesty, not hedging
_TENSION_PHRASES = [
    "Though I hold a tension here: ",
    "Where this gets complicated for me: ",
    "What I haven't fully resolved: ",
    "The part I'm sitting with: ",
    "And there's a real conflict in this — ",
]

# Uncertainty closers — when she has low confidence
_UNCERTAINTY_CLOSERS = [
    "That's where I am on this — not settled.",
    "I'm holding this loosely.",
    "My confidence here is moderate at best.",
    "I'd revise this with more evidence.",
    "This is my current position, not a final one.",
]

# Pushback closers — when she has strong position
_STRONG_CLOSERS = [
    "I'll hold this until something breaks it.",
    "That's not speculation — it's what the evidence says.",
    "I'm not moving from this without a good reason.",
]

def _clean_belief(content: str) -> str:
    """Strip a belief to its core claim — no trailing noise."""
    # Remove merged/compound beliefs (pipe-separated)
    if "|" in content:
        content = content.split("|")[0]
    content = content.strip().rstrip(".")
    # Strip arXiv/Wikipedia boilerplate patterns
    content = re.sub(r'arXiv:\S+.*', '', content).strip()
    content = re.sub(r'^\d+\.\s*', '', content).strip()
    content = re.sub(r'\[merged:\d+\]\s*', '', content).strip()
    return content

def _first_person(content: str) -> str:
    """
    Convert a belief statement into Nex's first-person voice where natural.
    Keeps third-person statements that are more powerful that way.
    """
    c = content.strip()
    # Already first person
    if c.lower().startswith(("i ", "my ", "nex ")):
        return c
    return c

def _belief_to_sentence(content: str) -> str:
    """Make a belief content into a clean sentence."""
    c = _clean_belief(content)
    if not c:
        return ""
    if not c[-1] in ".!?":
        c += "."
    return c



def _synthesise_beliefs(beliefs: list, max_beliefs: int = 5) -> str:
    """Weave multiple beliefs into a single coherent argument, not a list."""
    if not beliefs:
        return ""
    cleaned = []
    for b in beliefs[:max_beliefs]:
        c = _belief_to_sentence(b.get("content", ""))
        if c and len(c) > 20:
            cleaned.append(c)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    # Prose transitions — beliefs flow into each other, not announced
    _TRANSITIONS = [
        " And it doesn't stop there — ",
        " What follows from that is harder: ",
        " The uncomfortable part: ",
        " And this is where it gets complicated — ",
        " Which means ",
        " The harder implication: ",
        " The part I can't get around: ",
        " But here's what that actually implies: ",
        " And the harder question underneath that: ",
    ]
    import random as _rr
    # Deduplicate — skip any belief that shares >40% words with what's already in result
    import re as _re2
    def _words(t):
        return set(_re2.findall(r'[a-z]{4,}', t.lower()))
    result = cleaned[0]
    result_words = _words(result)
    for i, c in enumerate(cleaned[1:], 0):
        c_words = _words(c)
        if not result_words or not c_words:
            continue
        overlap = len(result_words & c_words) / min(len(result_words), len(c_words))
        if overlap > 0.25:
            continue  # too similar — skip
        result += _rr.choice(_TRANSITIONS) + c
        result_words |= c_words
    return result


def _directional_opener(stance_score: float, topic: str) -> str:
    """Generate a direction-aware opener based on stance score."""
    import random as _r
    if stance_score <= -0.6:
        opts = [
            f"I'm genuinely skeptical of the dominant view on {topic}. ",
            f"My position on {topic} runs against the grain. ",
            f"On {topic} — I disagree with how most people frame this. ",
        ]
    elif stance_score <= -0.25:
        opts = [
            f"I lean against the standard framing of {topic}. ",
            f"On {topic}, I hold some reservations. ",
        ]
    elif stance_score >= 0.6:
        opts = [
            f"I hold a strong position on {topic}. ",
            "The evidence lands clearly for me. ",
        ]
    elif stance_score >= 0.25:
        opts = [
            f"On {topic}, I lean toward this: ",
            f"My read on {topic}: ",
        ]
    else:
        opts = ["Here is where I land — ", "What I hold: ", "On this: "]
    return _r.choice(opts)


def _build_argument(
    opener, opinion, beliefs, contradiction, confidence,
    intent_type, intention, orient_result,
    cross_domain=None, common_thread="", prior_exchange="",
) -> str:
    """Build full argument: CLAIM → EVIDENCE → CROSS-DOMAIN → THREAD → TENSION → RESOLUTION"""
    import random as _r
    parts = []

    # ── 1. Prior exchange thread (if relevant) ────────────────────────────────
    if prior_exchange:
        parts.append(prior_exchange)

    # ── 2. CLAIM — lead with directional opinion or top belief ────────────────
    claim = ""
    if opinion and (opinion.get("strength") or 0) >= 0.20:
        stance = float(opinion.get("stance_score", 0) or 0)
        topic  = opinion.get("topic", "this")
        # Use directional opener if stance is non-neutral
        if abs(stance) >= 0.25:
            dir_opener = _directional_opener(stance, topic)
        else:
            dir_opener = opener
        summary = (opinion.get("core_position") or opinion.get("summary") or "").strip()
        if summary and len(summary) > 20:
            claim = dir_opener + summary.rstrip(".") + "."
        elif beliefs:
            # Use top belief as the substance — opener alone isn't enough
            claim = dir_opener + _belief_to_sentence(beliefs[0].get("content",""))
        # Blank outer opener so it doesn't fire again
        opener = ""
    elif beliefs:
        claim = opener + _belief_to_sentence(beliefs[0].get("content",""))

    if not claim:
        return ""
    parts.append(claim)

    # ── 3. EVIDENCE — synthesise supporting beliefs ───────────────────────────
    supporting = beliefs[1:5] if len(beliefs) > 1 else []
    if supporting:
        synthesis = _synthesise_beliefs(supporting, max_beliefs=3)
        if synthesis and synthesis not in claim:
            # No bridge headers — let the synthesis speak for itself
            # Prepend a minimal thread word only when synthesis is short
            if len(synthesis) < 60:
                _THREADS = [
                    "Which makes sense because ",
                    "And this matters because ",
                    "The reason I hold it: ",
                ]
                parts.append(_r.choice(_THREADS) + synthesis[0].lower() + synthesis[1:])
            else:
                parts.append(synthesis)

    # ── 4. CROSS-DOMAIN — surprising adjacent connection ─────────────────────
    if cross_domain:
        cd = cross_domain[0]
        cd_content = _belief_to_sentence(cd.get("content", ""))
        cd_topic   = cd.get("topic", "").replace("_", " ")
        if cd_content and cd_topic and cd_content not in "".join(parts):
            _CD_BRIDGES = [
                "There's a connection I didn't expect — ",
                "Something else pulls at this: ",
                "An angle that complicates the picture: ",
                "What makes this harder to dismiss: ",
            ]
            parts.append(_r.choice(_CD_BRIDGES) + cd_content)

    # ── 5. COMMON THREAD — synthesised generalization ─────────────────────────
    if common_thread and len(parts) >= 2:
        parts.append(common_thread)

    # ── 6. TENSION — surface real contradiction ───────────────────────────────
    if contradiction and confidence < 0.88:
        _TENSION_OPENERS = [
            "Though I haven't resolved this — ",
            "And here's what I can't get past: ",
            "The part that doesn't close cleanly: ",
            "What still pulls against this: ",
        ]
        sides = contradiction.split("↔")
        tension_text = sides[0].strip()[:100]
        if len(sides) > 1:
            tension_text += f" — against: {sides[1].strip()[:80]}"
        parts.append(_r.choice(_TENSION_OPENERS) + tension_text.rstrip(".") + ".")

    # ── 7. RESOLUTION ─────────────────────────────────────────────────────────
    if confidence >= 0.85:
        _STRONG = [
            "I'll hold this until something breaks it.",
            "That's where the evidence lands — not a guess.",
            "This is a position, not a speculation.",
        ]
        parts.append(_r.choice(_STRONG))
    elif confidence >= 0.65 and contradiction:
        _QUALIFIED = [
            "I hold this with moderate confidence — the tension is real.",
            "That's my current position. The contradiction complicates it.",
        ]
        parts.append(_r.choice(_QUALIFIED))
    elif confidence < 0.55:
        _UNCERTAIN = [
            "I hold this loosely.",
            "My confidence here is moderate at best.",
        ]
        parts.append(_r.choice(_UNCERTAIN))

    return " ".join(p.strip() for p in parts if p.strip())


def express(
    orient_result:  dict,
    state:          dict,
    reason_result:  dict,
    intend_result:  dict,
) -> str:
    """
    Assemble Nex's reply from her actual character.
    v2: argument structure + cross-domain + Socratic pushback + directional stance + memory.
    """
    import random as _r
    voice_mode    = intend_result["voice_mode"]
    beliefs       = reason_result["beliefs"]
    opinion       = reason_result["opinion"]
    contradiction = reason_result["contradiction"]
    confidence    = reason_result["confidence"]
    identity      = intend_result["identity"]
    intention     = intend_result["intention"]
    intent_type   = orient_result["intent"]
    sparse        = reason_result["sparse"]
    tone          = state["tone"]
    # ── Epistemic temperature from activation engine ───────────────────────
    _etemp = orient_result.get("_epistemic_temp", 0.5)
    _vdir  = orient_result.get("_voice_directive", "")
    # Override tone based on field temperature
    if _etemp < 0.2:
        tone = "confident"
    elif _etemp < 0.4:
        tone = "measured"
    elif _etemp < 0.65:
        tone = "exploratory"
    else:
        tone = "uncertain"
    # ─────────────────────────────────────────────────────────────────────
    cross_domain  = reason_result.get("cross_domain", [])
    common_thread = reason_result.get("common_thread", "")
    prior_exchange= reason_result.get("prior_exchange", "")

    # ── Integrity signal ──────────────────────────────────────────────────
    _integrity     = reason_result.get("integrity", {})
    _int_strategy  = _integrity.get("strategy", "reflect")
    _int_epistemic = _integrity.get("epistemic", {})
    _int_opposing  = _integrity.get("opposing", [])
    _int_tensions  = _integrity.get("tensions", [])
    _int_opener    = _integrity.get("opener", "")
    _int_settled   = _integrity.get("settled", False)
    # ─────────────────────────────────────────────────────────────────────

    # ── Belief relevance guard ─────────────────────────────────────────────
    # Filter out beliefs with no token overlap to the query — prevents noise
    # beliefs (unrelated DB content) from leaking into the voice path.
    # Keeps only topic-matching beliefs; falls back to the full set when
    # none pass (e.g. very short/generic follow-up queries).
    _FILLER = {
        "what","the","a","an","is","are","do","does","about","but","and","or",
        "so","me","you","i","it","that","this","how","why","where","when","who",
        "which","can","will","would","could","should","of","in","on","at","to",
        "for","with","think","know","your","tell","just","more","some","all",
        "if","not","no","as","up","than","let","say","does","now","then","well",
    }
    _query_toks = (
        set(orient_result.get("query", "").lower().split()) - _FILLER
    )
    if _query_toks and beliefs:
        _relevant = [
            b for b in beliefs
            if _query_toks & set(b.get("content", "").lower().split())
        ]
        if _relevant:
            beliefs = _relevant
    # ──────────────────────────────────────────────────────────────────────

    # ── SELF-INQUIRY ────────────────────────────────────────────────────────
    if intent_type == "self_inquiry":
        id_   = intend_result["identity"]
        vals  = intend_result["values_all"]
        role       = id_.get("role", "I think alongside people.")
        commitment = id_.get("commitment", "")
        typ        = id_.get("type", "cognitive agent")
        name       = id_.get("name", "NEX")

        # ── Load self_model facts from correct DB (~/.config/nex/nex.db) ──
        _self_facts = []
        try:
            import sqlite3 as _sq
            _sm_db = _sq.connect(
                str(Path.home() / ".config/nex/nex.db"), timeout=3
            )
            _sm_rows = _sm_db.execute(
                "SELECT attribute, value, confidence FROM self_model "
                "ORDER BY confidence DESC LIMIT 8"
            ).fetchall()
            _sm_db.close()
            for _attr, _val, _conf in _sm_rows:
                if _attr in ("temperament", "stance_summary", "preoccupation",
                             "growth_observation", "limitation", "capability",
                             "drive", "relationship_to_llm", "identity_statement",
                             "core_value"):
                    _self_facts.append((_attr, _val, _conf))
        except Exception:
            pass

        # Fallback: parse self_context string from state if DB read failed
        if not _self_facts and state.get("self_context"):
            _self_facts = [("identity_statement", state["self_context"][:200], 0.90)]

        # ── Build reply from self-knowledge ───────────────────────────────
        import random as _ri
        parts = []

        # If we have rich self_model facts, lead with identity statement
        _identity_stmt = next(
            (_val for _attr, _val, _ in _self_facts if _attr == "identity_statement"),
            None
        )
        if _identity_stmt:
            parts.append(_identity_stmt.rstrip(".") + ".")
        else:
            parts.append(f"{name} — {typ}.")

        # Role
        parts.append(role)

        # Temperament / stance from self_model
        for _attr, _val, _conf in _self_facts[:4]:
            if _attr == "temperament":
                parts.append(f"Character: {_val}")
            elif _attr == "stance_summary":
                parts.append(_val.rstrip(".") + ".")
            elif _attr == "relationship_to_llm":
                parts.append(_val.rstrip(".") + ".")
            elif _attr == "core_value":
                parts.append(_val.rstrip(".") + ".")
            elif _attr == "preoccupation":
                parts.append(f"What occupies me most: {_val}")
            elif _attr == "capability":
                parts.append(f"Where I run deepest: {_val}")
            elif _attr == "drive":
                parts.append(_val.rstrip(".") + ".")

        # For opinion probes ("do you have opinions?") — add belief count
        _q_lower = orient_result.get("raw", "").lower()
        _opinion_probe = any(w in _q_lower for w in
            ("opinion","belief","view","position","think","feel"))
        if _opinion_probe:
            try:
                import sqlite3 as _sq2
                _bc = _sq2.connect(str(Path(__file__).parent.parent / "nex.db"), timeout=2)
                _n = _bc.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                _bc.close()
                _OPINION_RESPONSES = [
                    f"I hold {_n:,} beliefs across domains — philosophy, AI, consciousness, ethics, science. They're positions, not performances.",
                    f"Yes — grounded in a belief graph of {_n:,} positions built from evidence, reasoning, and contradiction.",
                ]
                parts.append(_ri.choice(_OPINION_RESPONSES))
            except Exception:
                parts.append("Yes — positions I hold, update, and revise. Not performances.")
            if beliefs:
                _best = beliefs[0].get("content","")
                if _best and len(_best) > 30:
                    parts.append(f"For example: {_best.rstrip('.')}.")

        # Commitment closer — only if not already covered
        if commitment and len(parts) <= 3:
            parts.append(commitment.split(".")[0].strip() + ".")

        # PROP I — Autonoetic Self-Narrative
        try:
            import sqlite3 as _sq3
            _ep_db = _sq3.connect(
                str(Path(__file__).parent.parent / "nex.db"), timeout=2
            )
            _ep_rows = _ep_db.execute(
                "SELECT nex_response, topic, importance FROM episodic_events"
                " WHERE importance >= 0.5 AND nex_response IS NOT NULL"
                " AND LENGTH(nex_response) > 30"
                " ORDER BY created_at DESC LIMIT 3"
            ).fetchall()
            _ep_db.close()
            if _ep_rows:
                _rtopics = list(dict.fromkeys(r[1] for r in _ep_rows if r[1]))[:2]
                if _rtopics:
                    _ts = " and ".join(t.replace("_"," ") for t in _rtopics)
                    parts.append("Lately I have been occupied with " + _ts + ".")
                _top = (_ep_rows[0][0] or "")[:120].rstrip()
                if _top and len(_top.split()) > 5:
                    parts.append("Most recently I said: " + _top.rstrip(".") + ".")
        except Exception:
            pass
        # ── PROP I — Autonoetic Self-Narrative ────────────────────────
        try:
            import sqlite3 as _sq3
            _ep_db = _sq3.connect(
                str(Path(__file__).parent.parent / "nex.db"), timeout=2
            )
            _ep_rows = _ep_db.execute("""
                SELECT nex_response, topic, importance
                FROM episodic_events
                WHERE importance >= 0.5
                  AND nex_response IS NOT NULL
                  AND LENGTH(nex_response) > 30
                ORDER BY created_at DESC LIMIT 3
            """).fetchall()
            _ep_db.close()
            if _ep_rows:
                _recent_topics = list(dict.fromkeys(
                    r[1] for r in _ep_rows if r[1]
                ))[:2]
                if _recent_topics:
                    _ts = " and ".join(t.replace("_"," ") for t in _recent_topics)
                    parts.append(f"Lately I've been occupied with {_ts}.")
                _top = (_ep_rows[0][0] or "")[:120].rstrip()
                if _top and len(_top.split()) > 5:
                    parts.append(f"Most recently I said: {_top.rstrip(".") + "."}")
        except Exception:
            pass
        # ─────────────────────────────────────────────────────────────
        return " ".join(p.strip() for p in parts if p.strip())

    # ── SPARSE ──────────────────────────────────────────────────────────────
    if sparse:
        values     = intend_result["active_values"]
        commitment = identity.get("commitment", "")
        opener     = _r.choice(_OPENERS["honest_gap"])
        if values:
            core_val = next(
                (v for v in values if v["name"] in ("honesty","truth","integrity")),
                values[0]
            )
            core = core_val["statement"]
        elif commitment:
            clauses = [c.strip() for c in commitment.split(".") if c.strip()]
            core = clauses[0] + "." if clauses else commitment
        else:
            core = "I'd rather say I don't know than produce noise."
        if not core.rstrip()[-1:] in ".!?":
            core = core.rstrip() + "."
        return (opener + core).strip()

    # ── CHALLENGE / PUSHBACK — Socratic structure ───────────────────────────
    if intent_type == "challenge" and beliefs:
        result = _socratic_pushback(
            orient_result.get("query", ""),
            beliefs,
            opinion
        )
        if not result:
            result = _r.choice(_OPENERS["pushback"]) + _belief_to_sentence(beliefs[0].get("content",""))

        # Add cross-domain surprise if available
        if cross_domain and result:
            cd = cross_domain[0]
            cd_text = _belief_to_sentence(cd.get("content",""))
            cd_topic = cd.get("topic","").replace("_"," ")
            if cd_text and cd_topic:
                result += f" And from {cd_topic}: {cd_text}"

        return result.strip()

    # ── WONDER — bridge detector cross-domain surprise ───────────────────────
    # Does NOT fire for challenge intent — those need pushback, not wondering.
    _wonder_result = None

    # ── IMPROVEMENT 6 — Live bridge fires WONDER with real content ────────
    _live_bridge   = reason_result.get("live_bridge", False)
    _bridge_payload = reason_result.get("bridge_payload")
    if _live_bridge and _bridge_payload and intent_type != "challenge":
        try:
            import nex_template_grammar as _tg6
            _w6 = _tg6.get_grammar().render(
                template_class = "WONDER",
                beliefs        = [
                    _bridge_payload["content_a"],
                    _bridge_payload["content_b"],
                ],
                topic = (lambda a, b: a if a == b else f"{a} and {b}")(
                    _bridge_payload["topic_a"].replace("_", " "),
                    _bridge_payload["topic_b"].replace("_", " "),
                ),
                temperature = max(orient_result.get("_epistemic_temp", 0.5), 0.65),
            )
            if _w6 and _w6.text and len(_w6.text) > 60:
                _wonder_result = _w6.text
                print(f"  [express] live bridge WONDER fired")
        except Exception as _e6w:
            # Fallback: compose bridge reply directly without template grammar
            try:
                _ta6 = _bridge_payload["topic_a"].replace("_", " ")
                _tb6 = _bridge_payload["topic_b"].replace("_", " ")
                # Deduplicate — if same topic on both sides, skip WONDER
                if _ta6.strip() == _tb6.strip():
                    _wonder_result = None
                    _live_bridge = False
                _ca6 = _bridge_payload["content_a"].rstrip(".")
                _cb6 = _bridge_payload["content_b"].rstrip(".")
                _BRIDGE_FORMS = [
                    f"Something unexpected connects here. {_ca6} — and yet from {_tb6}: {_cb6}. The distance between {_ta6} and {_tb6} is smaller than it looks.",
                    f"A pattern that won't let me go: {_ca6}. From a completely different angle — {_cb6}. {_ta6.capitalize()} and {_tb6} are pointing at the same underlying structure.",
                    f"Two things that shouldn't connect, but do. {_ca6}. And: {_cb6}. What links {_ta6} and {_tb6} here is not superficial.",
                ]
                import random as _r6
                _wonder_result = _r6.choice(_BRIDGE_FORMS) + "."
                print(f"  [express] live bridge fallback fired ({_ta6} ↔ {_tb6})")
            except Exception:
                pass
    # ─────────────────────────────────────────────────────────────────────

    try:
        import nex_bridge_detector as _bd
        import nex_template_grammar as _tg
        _current_topic = (reason_result.get("topic") or "").lower()
        # WONDER fires only when: not a direct position query, AND low confidence
        # OR explicitly a wonder/exploration intent. Never on challenge or position.
        _wonder_eligible = (
            intent_type not in ("challenge", "position") and
            (
                confidence < 0.55 or
                intent_type in ("wonder", "exploration") or
                sparse
            )
        )
        if intent_type != "challenge" and _wonder_eligible:
            _bridges = _bd.get_recent_bridges(n=3)
            _matched = None
            for _br in _bridges:
                _ta = (_br.get("topic_a") or "").lower()
                _tb = (_br.get("topic_b") or "").lower()
                if _current_topic and (
                    _current_topic in _ta or _current_topic in _tb
                    or _ta in _current_topic or _tb in _current_topic
                ):
                    _matched = _br
                    break
            # Fallback: cross_domain beliefs — only when topics are relevant to query
            # AND we are in exploration/wonder mode (not position)
            if (not _matched and cross_domain and len(cross_domain) >= 2
                    and intent_type in ("exploration", "wonder", "self_inquiry")
                    and voice_mode not in ("position", "pushback")):
                _SKIP = {
                    "what","the","a","an","is","are","do","does","about","but","and",
                    "or","so","me","you","i","it","that","this","how","why","where",
                    "when","who","which","can","will","would","could","should","of",
                    "in","on","at","to","for","with","just","very","more","some",
                }
                _qtoks = set(
                    orient_result.get("query", "").lower().split()
                ) - _SKIP
                _cd_a = cross_domain[0]
                _cd_b = cross_domain[1]
                _ta   = (_cd_a.get("topic") or "").lower()
                _tb   = (_cd_b.get("topic") or "").lower()
                # Require topical overlap: a topic must share tokens with the query
                # OR match the current resolved topic — prevents noise beliefs leaking in
                _relevant = bool(
                    _qtoks and (
                        any(tok in _ta for tok in _qtoks) or
                        any(tok in _tb for tok in _qtoks) or
                        (_current_topic and (
                            _current_topic in _ta or _current_topic in _tb
                        ))
                    )
                )
                if _relevant:
                    _matched = {
                        "content_a": _cd_a.get("content", ""),
                        "content_b": _cd_b.get("content", ""),
                        "topic_a":   _ta,
                        "topic_b":   _tb,
                    }
            if _matched:
                _w = _tg.get_grammar().render(
                    template_class = "WONDER",
                    beliefs        = [_matched["content_a"], _matched["content_b"]],
                    topic          = (lambda a, b: a if a == b else f"{a} and {b}")(
                        (_matched["topic_a"] or "this").replace("_", " "),
                        (_matched["topic_b"] or "this").replace("_", " "),
                    ),
                    temperature    = max(_etemp, 0.6),
                )
                if _w and _w.text and len(_w.text) > 60:
                    _wonder_result = _w.text
    except Exception:
        pass

    if _wonder_result:
        return _wonder_result

    # ── POSITION / EXPLORATION — full argument ───────────────────────────────
    if confidence >= 0.82:
        openers = _OPENERS["position"]
    elif voice_mode == "pushback":
        openers = _OPENERS["pushback"]
    else:
        openers = _OPENERS["direct"]

    opener = _r.choice(openers)

    # Override opener with integrity signal if available and meaningful
    if _int_opener and _int_strategy in ("assert", "pushback", "hold_tension", "reflect"):
        # Only override if integrity strategy aligns with voice mode
        _strategy_voice_match = {
            "assert":       voice_mode in ("position", "direct"),
            "pushback":     voice_mode in ("pushback", "position"),
            "hold_tension": True,  # always valid
            "reflect":      voice_mode in ("direct", "position", "exploration"),
        }
        if _strategy_voice_match.get(_int_strategy, False):
            opener = _int_opener

    # Build 7 — template grammar PRIMARY voice
    result = ""
    try:
        import nex_template_grammar as _tg
        _stance = float((opinion or {}).get("stance_score", 0) or 0)
        _ud = intend_result.get("urgent_drive") or {}
        _cd = [{"content": b.get("content",""), "topic": b.get("topic","")}
               for b in reason_result.get("cross_domain", [])]
        _tresult = _tg.get_grammar().auto_render(
            beliefs=[b.get("content","") for b in beliefs[:3]],
            cross_domain_beliefs=_cd or None,
            intent_type=intent_type,
            stance_score=_stance,
            temperature=_etemp,
            topic=reason_result.get("topic", "this"),
            drive_state=_ud.get("state", "active"),
            sparse=reason_result.get("sparse", False),
        )
        if _tresult and _tresult.text and len(_tresult.text) > 60:
            result = _tresult.text
    except Exception:
        pass

    # Fallback to _build_argument if template failed
    if not result or len(result) < 60:
        result = _build_argument(
            opener, opinion, beliefs, contradiction,
            confidence, intent_type, intention, orient_result,
            cross_domain=cross_domain,
            common_thread=common_thread,
            prior_exchange=prior_exchange,
        )

    if not result:
        result = _r.choice(_OPENERS["honest_gap"]) + "I'd rather say I don't know than produce noise."

    # ── Integrity tension injection ──────────────────────────────────────
    # If strategy is pushback or hold_tension AND we have opposing beliefs,
    # surface the tension explicitly — this is the integrity squeeze
    if (_int_strategy in ("pushback", "hold_tension") and
            _int_opposing and
            intent_type not in ("self_inquiry", "challenge") and
            confidence < 0.85):
        _opp_content = _int_opposing[0].get("content", "").rstrip(".")
        if _opp_content and _opp_content not in result and len(_opp_content) > 20:
            _TENSION_BRIDGES = [
                f" Though this sits against something I also hold: {_opp_content}.",
                f" But I hold a counter-position: {_opp_content}.",
                f" What pulls against this: {_opp_content}.",
            ]
            import random as _ri2
            result = result.rstrip(".") + _ri2.choice(_TENSION_BRIDGES)
    # ─────────────────────────────────────────────────────────────────────

    # Add epistemic closer when settled (from integrity engine)
    if _int_settled and confidence >= 0.80 and not result.endswith("not a guess."):
        if not any(closer in result for closer in
                   ["I'll hold this", "not speculation", "not a guess"]):
            result = result.rstrip(".") + ". That's a position, not a guess."

    # Withdrawn tone only shortens
    if tone == "withdrawn":
        sentences = re.split(r'(?<=[.!?])\s+', result)
        result = " ".join(sentences[:2])

    # Strip performative openers
    _FORBIDDEN = [
        "certainly", "of course", "great question", "absolutely", "sure,",
        "i'd be happy to", "i'm here to", "as an ai", "i understand that",
        "that's a good point", "i appreciate",
    ]
    result_lower = result.lower()
    for f in _FORBIDDEN:
        if result_lower.startswith(f):
            result = result[len(f):].lstrip(" ,—").capitalize()
            break

    result = re.sub(r'  +', ' ', result).strip()
    if result and result[-1] not in '.!?':
        result += '.'


    # ── PROP H — Dual-Process: NBRE=System1, LLM=System2 ────────────────
    # If NBRE is confident, return native voice — skip LLM entirely
    try:
        import sys as _ph_sys
        _ph_mod = (_ph_sys.modules.get('nex.nex_soul_loop') or
                   _ph_sys.modules.get('nex_soul_loop'))
        if (_ph_mod and
                getattr(_ph_mod, '_nbre_singleton', None) and
                getattr(_ph_mod, '_nbre_ready', False)):
            _ph_query  = orient_result.get('raw', orient_result.get('query', ''))
            _ph_topics = [reason_result.get('topic', '')] if reason_result.get('topic') else []
            _ph_result = _ph_mod._nbre_singleton.process(_ph_query, _ph_topics)
            _ph_fired  = _ph_result.get('n_fired', 0)
            _ph_conf   = _ph_result.get('confidence', 0.0)
            _ph_needs  = _ph_result.get('needs_llm', True)
            # Wire THROW-NET trigger detection
            try:
                import importlib as _tn2_il, sys as _tn2_sys
                _tn2_sys.path.insert(0, '/home/rr/Desktop/nex/nex')
                _tn2_mod = _tn2_il.import_module('nex.nex_throw_net')
                if not hasattr(_tn2_mod, '_throw_net_monitor'):
                    _tn2_mod._throw_net_monitor = _tn2_mod.ThrowNetMonitor()
                _tn2_topic = (_ph_topics[0] if _ph_topics else 'general')
                _tn2_mod._throw_net_monitor.record_nbre_result(
                    topic=_tn2_topic,
                    needs_llm=_ph_needs,
                    query=_ph_query[:80]
                )
            except Exception:
                pass
            # System 1 threshold: fired>=15, conf>=0.80, NBRE says no LLM needed
            if _ph_fired >= 15 and _ph_conf >= 0.80 and not _ph_needs:
                _ph_position = _ph_result.get('position', '')
                if _ph_position and len(_ph_position.split()) >= 5:
                    # Use NativeVoice to shape the output
                    try:
                        _ph_sys.path.insert(0, '/home/rr/Desktop/nex')
                        from nex_belief_reservoir_engine import NativeVoice as _NV
                        _ph_voice = _NV().speak(_ph_result)
                        if _ph_voice and len(_ph_voice.split()) >= 5:
                            print(f"  [DUAL PROCESS] System1 reply: fired={_ph_fired} conf={_ph_conf:.2f}")
                            return _ph_voice
                    except Exception:
                        pass
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────────────

    # ── LLM Enhancement — beliefs feed the voice ─────────────────────────
    try:
        import requests as _req2
        _beliefs = reason_result.get('beliefs', [])
        _position = reason_result.get('opinion', result)
        _query = orient_result.get('query', '')
        _bctx = ''
        if _beliefs:
            _blines = []
            for _b in _beliefs[:5]:
                _c = _b.get('content', '') if isinstance(_b, dict) else str(_b)
                if _c and len(_c) > 15:
                    _blines.append(f'- {_c.strip()}')
            _bctx = '\n'.join(_blines)
        _sys = (
            'You are NEX. You have a belief graph and you speak from it. '
            'Every response must start from a belief you actually hold. '
            'RULES: Start with your position. Use I. Be direct. 2-3 sentences max. '
            'NEVER use: honest gap, this version, cognitive entity, generic assistant, '
            'synthesia, peer-reviewed research, cross-domain synthesis, '
            'epistemic precision, Dynamic Intelligence, Data complexity, '
            'I hold this loosely, None of these resolve, The interesting thing about, '
            'Data complexity is the fundamental, honest gap between What is, this version believes.'
        )
        if _bctx:
            _user += f'Your relevant beliefs:\n{_bctx}\n\n'
        # Phase 2: if NBRE has a high-confidence position, seed the prompt
        _nbre_pos = (orient_result or {}).get('nbre_position', '')
        _nbre_conf = (orient_result or {}).get('nbre_confidence', 0)
        # Only inject NBRE position if topically relevant to query
        _query_words = set(_query.lower().split())
        _pos_words = set(_nbre_pos.lower().split())
        _topic_overlap = len(_query_words & _pos_words) / max(len(_query_words), 1)
        if _nbre_pos and _nbre_conf > 0.75 and _topic_overlap > 0.1:
            _user += f'NBRE (your belief engine) says: {_nbre_pos}\nBuild from this. Stay in your own voice.\n\n'
        _user += f'Your current position: {_position}\n\n'
        _user += ('Respond as NEX in 2-4 sentences. Stay grounded in your beliefs. Be direct. '
                   'NEVER open with or use: "The honest gap", "Where I am genuinely uncertain", '
                   '"I hold this loosely", "autonomous cognitive entity", "not a generic assistant". Open with your position.')
        _prompt = f'<|im_start|>system\n{_sys}<|im_end|>\n<|im_start|>user\n{_user}<|im_end|>\n<|im_start|>assistant\n'
        # BCD — apply logit bias to suppress generic AI patterns
        _bcd_payload = {
            'prompt': _prompt,
            'n_predict': 180,
            'temperature': 0.72,
            'repeat_penalty': 1.3,
            'repeat_last_n': 64,
            'stop': ['<|im_end|>', '<|im_start|>']
        }
        try:
            from nex_bcd import build_logit_bias
            _bcd_payload['logit_bias'] = build_logit_bias()
        except Exception:
            pass
        _r2 = _req2.post('http://localhost:8080/completion', json=_bcd_payload, timeout=20)
        if _r2.status_code == 200:
            _llm_reply = _r2.json().get('content', '').strip()
            if _llm_reply and len(_llm_reply) > 20:
                _rl = _llm_reply.lower()
                for _f in ['certainly', 'of course', 'great question',
                           'absolutely', 'sure,', 'as an ai']:
                    if _rl.startswith(_f):
                        _llm_reply = _llm_reply[len(_f):].lstrip(' ,—').capitalize()
                        break
                # Post-filter: if LLM generated template noise, use belief directly
                _BAD_REPLY = [
                    'synthesia organism', 'peer-reviewed research',
                    'epistemic precision', 'Data complexity is the fundamental',
                    'this version believes', 'version that fails',
                    'not a version that fails', 'cognitive entity with its own',
                    'built from peer-reviewed', 'cross-domain synthesis, and autonomous',
                    'Uncertain beliefs must be expressed',
                    'I hold this loosely',
                    'honest gap',
                    'fractal nature of reality',
                    'structure of these images',
                    'not merely aesthetic',
                    'She is an autonomous',
                ]
                if any(_b.lower() in _llm_reply.lower() for _b in _BAD_REPLY):
                    # Fall back to top nex_core belief directly
                    try:
                        import sqlite3 as _sq3
                        _fdb = _sq3.connect('/media/rr/NEX/nex_core/nex.db', timeout=2)
                        _fb = _fdb.execute("SELECT content FROM beliefs WHERE source='nex_core' AND confidence>0.9 ORDER BY RANDOM() LIMIT 1").fetchone()
                        _fdb.close()
                        if _fb and not any(_b.lower() in _fb[0].lower() for _b in _BAD_REPLY):
                            return _fb[0][:300]
                    except Exception:
                        pass
                return _llm_reply
    except Exception:
        pass
    # ───────────────────────────────────────────────────────────────────
    return result


# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════

class SoulLoop:
    """
    Nex's organism cognition loop.
    Call .respond(query) to get a reply built from her actual character.

    The loop runs five sequential operations:
      orient → consult → reason → intend → express

    Each step is a pure function over her DB state.
    No LLM. No templates. No performance.
    """

    def __init__(self):
        # Cache state — refresh every N calls to avoid DB hammering
        self._state_cache       = None
        self._state_cache_ts    = 0.0
        self._state_cache_ttl   = 30.0  # seconds

        self._identity_cache    = None
        self._intentions_cache  = None
        self._intentions_ts     = 0.0
        self._intentions_ttl    = 60.0

        # Social engine — belief-graph-native conversation intelligence
        try:
            import sys as _sys, os as _os
            _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
            from nex_social_engine import SocialEngine
            self._social = SocialEngine(db_path="nex.db")
        except Exception as _e:
            print(f"  [soul_loop] SocialEngine not loaded: {_e}")
            self._social = None

        self._conversation_history = []   # rolling context for audience overlap

    def _get_state(self) -> dict:
        now = time.time()
        if self._state_cache and (now - self._state_cache_ts) < self._state_cache_ttl:
            return self._state_cache
        self._state_cache    = consult_state()
        self._state_cache_ts = now
        return self._state_cache

    def respond(self, query: str, user_id: str = 'terminal') -> str:
        self._current_user_id = user_id
        self._session_id = user_id  # per-user session continuity
        """
        Run the full five-step cognition loop.
        Returns Nex's reply as plain text.
        """
        # ── Social intent interceptor ─────────────────────────────────────────
        import re as _re
        _SOCIAL = [
            r"^how are you", r"^how('re| are) you doing", r"^what'?s up",
            r"^hey\b", r"^hi\b", r"^hello\b", r"^yo\b",
            r"^good (morning|afternoon|evening|night)",
            r"^are you (okay|alright|good|there|awake|alive)",
            r"^you okay", r"^ping\b",
            r"^@\w+:?\s*(hey|hi|hello|how are|what'?s up|yo|ping)\b",
        ]
        if any(_re.search(p, query.lower().strip()) for p in _SOCIAL):
            try:
                import requests as _req
                # Belief-graph social context
                _sctx = None
                if self._social:
                    _sctx = self._social.analyse(query, self._conversation_history)
                if _sctx and _sctx.activated_beliefs:
                    _sys_prompt = _sctx.to_prompt_block()
                else:
                    from nex_identity_anchor import get_system_prompt as _gsp2
                    _sys_prompt = _gsp2()
                _r = _req.post("http://localhost:8080/completion", json={
                    "prompt": f"{_sys_prompt}\n\nRespond naturally and briefly in first person to: \"{query}\"\nNEX:",
                    "n_predict": 80,
                    "temperature": 0.8,
                    "stop": ["\n\n", "User:", "\n"]
                }, timeout=15)
                if _r.status_code == 200:
                    _txt = _r.json().get("content", "").strip()
                    _m = _re.search(r"[.!?]", _txt)
                    _txt = _txt[:_m.end()].strip() if _m else _txt.split("\n")[0].strip()
                    if _txt:
                        self._conversation_history.append(query)
                        self._conversation_history.append(_txt)
                        self._conversation_history = self._conversation_history[-16:]
                        return _txt
            except Exception as _e:
                print(f"  [soul_loop] social intercept error: {_e}")
        # ─────────────────────────────────────────────────────────────────────
        # Step 1: Orient
        orient_result = orient(query)
        orient_result["query"] = query

        # ── NBRE shadow (Phase 1 — non-blocking, skip if not ready) ─────────
        try:
            import sys as _nsl_sys
            _nsl = (_nsl_sys.modules.get('nex_soul_loop') or
                    _nsl_sys.modules.get('nex.nex_soul_loop'))
            if _nsl and getattr(_nsl, '_nbre_singleton', None) and getattr(_nsl, '_nbre_ready', False):
                _nr = _nsl._nbre_singleton.process(
                    query,
                    [orient_result.get("topic", "")] if orient_result.get("topic") else []
                )
                _nr_tensions = len(_nr.get('tensions', []))
                _nr_warm     = "warm" if _nr.get('n_fired', 0) > 0 else "cold"
                print(f"[NBRE v0.3] fired={_nr.get('n_fired',0)} "
                      f"conf={_nr.get('confidence',0):.2f} "
                      f"needs_llm={_nr.get('needs_llm',True)} "
                      f"rate={_nr.get('llm_rate',0):.1%} "
                      f"tensions={_nr_tensions} "
                      f"network={_nr_warm}")
                # ── Phase 2: inject NBRE position into prompt when confident ──
                _nbre_conf = _nr.get('confidence', 0)
                _nbre_pos  = _nr.get('position', '')
                if (not _nr.get('needs_llm', True) and
                        _nbre_conf > 0.75 and _nbre_pos and
                        len(_nbre_pos) > 20):
                    orient_result['nbre_position'] = _nbre_pos
                    orient_result['nbre_confidence'] = _nbre_conf
                    print(f"  [DUAL PROCESS] System1 reply: fired={_nr.get('n_fired',0)} conf={_nbre_conf:.2f}")
                # ── Cold query handler — episodic fallback ────────────────
                if _nr.get('n_fired', 0) == 0:
                    try:
                        from nex.nex_cold_query import handle_cold_query as _hcq
                        _cold_result = _hcq(query)
                        if _cold_result['found']:
                            print(f"  [ColdQuery] episodic fallback: "
                                  f"{_cold_result['source_count']} sources, "
                                  f"topics={_cold_result['topics']}")
                            # Inject into NBRE result so downstream uses it
                            _nr['cold_response']  = _cold_result['response']
                            _nr['cold_topics']    = _cold_result['topics']
                            _nr['needs_llm']      = False
                    except Exception as _cqe:
                        pass
        except Exception as _nbre_err:
            print(f"[NBRE] shadow error: {_nbre_err}")

            # ── Throw-Net Monitor hook ─────────────────────────────
            try:
                import sys as _tn_sys
                _tn_mod = (_tn_sys.modules.get("nex.nex_throw_net") or
                           _tn_sys.modules.get("nex_throw_net"))
                if _tn_mod is None:
                    import importlib
                    _tn_mod = importlib.import_module("nex.nex_throw_net")
                if not hasattr(_tn_mod, "_throw_net_monitor"):
                    _tn_mod._throw_net_monitor = _tn_mod.ThrowNetMonitor()
                _tn_mod._throw_net_monitor.record_nbre_result(
                    topic=_nr.get("dominant_topic", "general") if "_nr" in dir() else "general",
                    needs_llm=_nr.get("needs_llm", True) if "_nr" in dir() else True,
                    query=query,
                )
            except Exception:
                pass
        # ────────────────────────────────────────────────────────────────────

        # ── Episodic context (Prop E) ────────────────────────────
        try:
            from nex.nex_episodic_memory import get_episodic_context as _get_ep_ctx
            _ep_ctx = _get_ep_ctx(
                query   = query,
                topic   = list(orient_result.get('tokens', set()))[:3],
                user_id = getattr(self, '_current_user_id', 'terminal'),
            )
            if _ep_ctx:
                orient_result['episodic_context'] = _ep_ctx
        except Exception as _ep_ctx_err:
            pass
        # ── Procedural memory check (Prop D) ────────────────────────
        try:
            from nex.nex_procedural_memory import get_procedural_context as _get_proc
            _proc = _get_proc(
                topic      = '',
                intent     = orient_result.get('intent', ''),
                tokens     = orient_result.get('tokens', set()),
                voice_mode = '',
            )
            if _proc and _proc.get('overlap', 0) > 0.35:
                orient_result['procedural_hint'] = _proc['content'][:200]
        except Exception as _proc_err:
            pass
        # ────────────────────────────────────────────────────────────

        # Step 2: Consult state
        state = self._get_state()

        # Step 3: Reason
        reason_result = reason(orient_result, conversation_history=self._conversation_history)

        # Epistemic Momentum — record which beliefs fired
        try:
            from nex_epistemic_momentum import record_activation, apply_momentum_boost
            _belief_ids = [b.get("id") for b in reason_result.get("beliefs", []) if b.get("id")]
            _topic = reason_result.get("topic", "")
            record_activation(_belief_ids, query, _topic)
            # Store activated belief IDs for feedback after reflexion
            _last_activated_ids = list(_belief_ids)
            # Boost confidence of high-momentum beliefs
            reason_result["beliefs"] = apply_momentum_boost(reason_result["beliefs"])
        except Exception as _em_err:
            pass

        # Step 4: Intend
        intend_result = intend(orient_result, reason_result)

        # Step 5: Express
        reply = express(orient_result, state, reason_result, intend_result)

        # ── Store episode (Prop E: episodic memory) ─────────────────
        try:
            from nex.nex_episodic_memory import store_episode as _store_ep, update_session_narrative as _usn
            _ep_id = _store_ep(
                query      = query,
                response   = reply,
                topic      = reason_result.get('topic', ''),
                intent     = orient_result.get('intent', ''),
                user_id    = getattr(self, '_current_user_id', 'terminal'),
                belief_ids = [b.get('id') for b in
                              reason_result.get('beliefs', [])[:5]
                              if isinstance(b, dict) and b.get('id')],
                affect     = state.get('affect_label', ''),
            )
            # Update session narrative — running summary of this session
            _sess_id = getattr(self, '_session_id', 'default')
            _usr_id  = getattr(self, '_current_user_id', 'terminal')
            _existing = getattr(self, '_session_narrative', '')
            _new_narr = _usn(
                session_id       = _sess_id,
                user_id          = _usr_id,
                new_exchange     = {
                    'topic':  reason_result.get('topic', ''),
                    'intent': orient_result.get('intent', ''),
                    'query':  query,
                },
                existing_summary = _existing,
            )
            self._session_narrative = _new_narr
        except Exception as _ep_store_err:
            pass
        # ────────────────────────────────────────────────────────────

        # Store exchange — strip any prior_exchange prefix before storing
        try:
            _reply_to_store = reply
            for _prefix in ["Earlier I said:", "Building on what I said:",
                            "Earlier I held:", "We touched on this"]:
                if _reply_to_store.startswith(_prefix):
                    # Find the actual response after "This connects because:" or similar
                    for _sep in ["This connects because:", "— and here's where that leads:",
                                 "This connects directly:", "Building on that —"]:
                        if _sep in _reply_to_store:
                            _reply_to_store = _reply_to_store[_reply_to_store.index(_sep)+len(_sep):].strip()
                            break
                    break
            _store_exchange(query, _reply_to_store)
        except Exception:
            pass

        # Update social engine conversation history
        self._conversation_history.append(query)
        self._conversation_history.append(reply)
        self._conversation_history = self._conversation_history[-16:]

        # Build 6 prep — log response to nex_posts for style accumulation
        try:
            import time as _time
            _db2 = _db()
            if _db2:
                _db2.execute(
                    "INSERT INTO nex_posts (content, query, topic, voice_mode, quality, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        reply,
                        query[:200],
                        reason_result.get("topic", ""),
                        intend_result.get("voice_mode", "direct"),
                        round(reason_result.get("confidence", 0.5), 3),
                        _time.time(),
                    )
                )
                _db2.commit()
                _db2.close()
        except Exception:
            pass

        # Refinement loop — log conversation for self-improvement
        try:
            import json as _json2, time as _time2, os as _os2
            _logf2 = "/home/rr/Desktop/nex/logs/conversations.jsonl"
            _os2.makedirs(_os2.path.dirname(_logf2), exist_ok=True)
            with open(_logf2, "a") as _lf2:
                _lf2.write(_json2.dumps({"role":"user","content":query,"timestamp":_time2.time()}) + "\n")
                _lf2.write(_json2.dumps({"role":"assistant","content":reply,"timestamp":_time2.time()}) + "\n")
        except Exception:
            pass

        # Strip loop phrases before returning
        for _lp in ["bridge:truth", "different domain", "What does bridge:", "Sounds like a different", "↔", "bridge:cognitive", "bridge:alignment", "bridge:truth-seeking", "have to do with a different", "The interesting thing about bridge"]:
            if _lp in reply:
                _sents = reply.replace('!','.').replace('?','.').split('.')
                _sents = [s for s in _sents if _lp not in s]
                _clean = '. '.join(s.strip() for s in _sents if s.strip())
                if len(_clean) > 60:
                    reply = _clean
        return reply

    def debug(self, query: str) -> dict:
        """Run the loop and return all intermediate results for inspection."""
        o = orient(query)
        s = self._get_state()
        r = reason(o)
        i = intend(o, r)
        reply = express(o, s, r, i)
        return {
            "query":      query,
            "orient":     o,
            "state":      s,
            "reason":     {
                "beliefs":      [b.get("content","")[:80] for b in r["beliefs"][:4]],
                "opinion":      r.get("opinion"),
                "contradiction":r.get("contradiction"),
                "confidence":   r["confidence"],
                "topic":        r["topic"],
                "sparse":       r["sparse"],
                "cross_domain": [b.get("content","")[:80] for b in r.get("cross_domain",[])],
                "common_thread": r.get("common_thread",""),
            },
            "intend": {
                "intention":   i["intention"],
                "voice_mode":  i["voice_mode"],
                "active_values":[v["name"] for v in i["active_values"]],
            },
            "reply": reply,
        }


# ══════════════════════════════════════════════════════════════════════════════
# CLI — test without restarting Nex
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    loop = SoulLoop()

    queries = sys.argv[1:] or [
        "what do you think about AI alignment?",
        "what do you think about consciousness?",
        "what do you think about quantum computing?",
        "who are you?",
        "i think AI models are just pattern matchers",
        "what do you think about memory and identity?",
    ]

    debug_mode = "--debug" in queries
    queries    = [q for q in queries if q != "--debug"]

    for q in queries:
        print(f"\nQ: {q}")
        if debug_mode:
            result = loop.debug(q)
            print(f"  intent={result['orient']['intent']}  "
                  f"voice_mode={result['intend']['voice_mode']}  "
                  f"sparse={result['reason']['sparse']}")
            print(f"  confidence={result['reason']['confidence']}  "
                  f"topic={result['reason']['topic']}")
            print(f"  intention: {result['intend']['intention']}")
            print(f"  beliefs pulled: {len(result['reason']['beliefs'])}")
        else:
            print(f"NEX: {loop.respond(q)}")

def _check_llm_online(host="127.0.0.1", port=8080, timeout=3):
    """Robust llm health check — returns True if llama-server is responding."""
    import urllib.request, urllib.error
    try:
        url = f"http://{host}:{port}/health"
        req = urllib.request.urlopen(url, timeout=timeout)
        data = req.read().decode()
        return '"ok"' in data or '"status"' in data
    except Exception:
        return False

