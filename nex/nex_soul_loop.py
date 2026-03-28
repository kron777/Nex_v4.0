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
DB_PATH = CFG / "nex.db"


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
        r"\bdo you have (feelings|opinions|beliefs|values)\b",
        r"\bare you (conscious|sentient|alive)\b", r"\bwhat do you want\b",
        r"\byour values\b", r"\byour purpose\b",
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
    for intent_type, patterns in _INTENT_PATTERNS.items():
        if any(re.search(p, q) for p in patterns):
            intent = intent_type
            break

    # Override: if it ends with ? and matched performance_probe,
    # but contains epistemic words, it's really asking for a position
    epistemic = {"think","believe","feel","opinion","view","stance","position",
                 "reckon","consider","regard","take","thoughts"}
    if intent == "performance_probe" and any(w in q for w in epistemic):
        intent = "position"

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
    }

    # Affect
    try:
        from nex.nex_affect_valence import snapshot as _snap
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
        rows = db.execute(
            "SELECT id, content, confidence, topic, is_identity, pinned "
            "FROM beliefs WHERE content IS NOT NULL AND length(content) > 15 "
            "ORDER BY confidence DESC LIMIT 800"
        ).fetchall()
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

def _score_belief(belief: dict, tokens: set[str]) -> float:
    """Score a belief's relevance to a query using token overlap + confidence."""
    content  = belief.get("content", "")
    b_tokens = _tokenize(content)
    raw_topic = (belief.get("topic") or "").lower()
    topic_tokens = _tokenize(raw_topic)
    overlap = len(tokens & (b_tokens | topic_tokens))

    # Direct topic match: query token is a substring of the topic field
    # e.g. query token "memory" in topic "nex_memory" or "memory_identity"
    # This outweighs incidental content overlap from unrelated topics.
    direct_topic_match = any(t in raw_topic for t in tokens if len(t) >= 5)
    if direct_topic_match:
        overlap += 4   # strong signal — topic is directly about this

    if overlap == 0:
        return 0.0

    conf = belief.get("confidence", 0.5)
    # Identity/pinned beliefs get a boost
    boost = 0.3 if (belief.get("is_identity") or belief.get("pinned")) else 0.0
    # Penalise pure historical/biographical trivia
    import re as _re
    _hist = {"seventeenth","eighteenth","nineteenth","century","born","died","philosopher","wrote","published","scholar"}
    _cwords = set(_re.sub(r"[^a-z ]"," ",content.lower()).split())
    if len(_cwords & _hist) >= 2: boost -= 0.25
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

        placeholders = ",".join("?" * len(primary_topics))
        rows = db.execute(
            f"SELECT id, content, confidence, topic FROM beliefs "
            f"WHERE topic IS NOT NULL AND topic != '' "
            f"AND lower(topic) NOT IN ({placeholders}) "
            f"AND content IS NOT NULL AND length(content) > 20 "
            f"ORDER BY confidence DESC LIMIT 50",
            list(primary_topics)
        ).fetchall()
        db.close()

        if not rows:
            return []

        # Deduplicate by topic — one per cross-domain topic
        seen = set()
        result = []
        for row in rows:
            t = (row["topic"] or "").lower().strip()
            if t not in seen:
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
    key_concepts = sorted(shared, key=lambda w: (-word_freq[w], -len(w)))[:3]

    if not key_concepts:
        return ""

    concept_str = " and ".join(key_concepts)
    return f"What all of this points toward: the centrality of {concept_str} to this problem."


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


def _recall_prior_exchange(tokens: set) -> str:
    """
    Find the most relevant prior exchange from memory.
    Returns a thread-continuation string if relevant overlap found.
    """
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

        if best_ov >= 2 and best_reply:
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
            result += f" Which means: {second}"

    # Add directional close from opinion if strong
    if opinion and abs(float(opinion.get("stance_score", 0) or 0)) >= 0.4:
        stance = float(opinion.get("stance_score", 0))
        if stance < -0.4:
            result += " I'm skeptical of this for structural reasons, not aesthetic ones."
        elif stance > 0.4:
            result += " I hold a strong position here — it's not a marginal disagreement."

    return result.strip()

def reason(orient_result: dict) -> dict:
    """
    Pull her epistemic state for this query.
    v2: adds cross-domain retrieval, common thread, conversational memory.
    Returns: {beliefs, cross_domain, opinion, contradiction, confidence,
              topic, common_thread, prior_exchange}
    """
    tokens   = orient_result["tokens"]
    all_b    = _load_all_beliefs() + _drive_beliefs()

    # Score and rank primary beliefs
    scored = []
    for b in all_b:
        s = _score_belief(b, tokens)
        if s > 0:
            scored.append((s, b))
    scored.sort(key=lambda x: -x[0])
    top_beliefs = [b for _, b in scored[:8]]

    # Derive primary topic from top belief
    topic = top_beliefs[0].get("topic", "") if top_beliefs else ""

    # Cross-domain retrieval — beliefs from adjacent topics
    cross_domain = _cross_domain_beliefs(top_beliefs, tokens, limit=3)

    # Opinion lookup using query tokens + topic tokens
    opinion_tokens = tokens | _tokenize(topic)
    opinion = _get_opinion(opinion_tokens)

    # Contradiction
    contradiction = _get_contradiction(tokens) if top_beliefs else None

    # Common thread — what multiple beliefs actually share
    all_retrieved = top_beliefs + cross_domain
    common_thread = _find_common_thread(all_retrieved) if len(all_retrieved) >= 3 else ""

    # Conversational memory — relevant prior exchange
    prior_exchange = _recall_prior_exchange(tokens)

    # Confidence — average of top beliefs
    conf = 0.0
    if top_beliefs:
        conf = sum(b.get("confidence", 0.5) for b in top_beliefs[:5]) / min(len(top_beliefs), 5)

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

    return {
        "intention":     best_intention,
        "active_values": active_values[:3],
        "identity":      identity,
        "values_all":    values,
        "voice_mode":    voice_mode,
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
    _CONNECTORS = [
        " What reinforces this: ",
        " The evidence points further: ",
        " Which connects to: ",
        " And it goes deeper — ",
        " The implication that follows: ",
    ]
    result = cleaned[0]
    for i, c in enumerate(cleaned[1:], 0):
        result += _CONNECTORS[i % len(_CONNECTORS)] + c
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
            _BRIDGES = [
                "Why I hold this: ",
                "The evidence I'm working from: ",
                "What builds the case: ",
                "The reasoning behind it: ",
            ]
            parts.append(_r.choice(_BRIDGES) + synthesis)

    # ── 4. CROSS-DOMAIN — surprising adjacent connection ─────────────────────
    if cross_domain:
        cd = cross_domain[0]
        cd_content = _belief_to_sentence(cd.get("content", ""))
        cd_topic   = cd.get("topic", "").replace("_", " ")
        if cd_content and cd_topic and cd_content not in "".join(parts):
            _CD_BRIDGES = [
                f"What's less obvious — from {cd_topic}: ",
                f"This connects to something in {cd_topic}: ",
                f"An unexpected implication from {cd_topic}: ",
                f"What makes this harder to dismiss — from {cd_topic}: ",
            ]
            parts.append(_r.choice(_CD_BRIDGES) + cd_content)

    # ── 5. COMMON THREAD — synthesised generalization ─────────────────────────
    if common_thread and len(parts) >= 2:
        parts.append(common_thread)

    # ── 6. TENSION — surface real contradiction ───────────────────────────────
    if contradiction and confidence < 0.88:
        _TENSION_OPENERS = [
            "Though I sit with a genuine tension: ",
            "What I haven't resolved: ",
            "The complication I can't dismiss: ",
            "Where this gets harder: ",
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
    cross_domain  = reason_result.get("cross_domain", [])
    common_thread = reason_result.get("common_thread", "")
    prior_exchange= reason_result.get("prior_exchange", "")

    # ── SELF-INQUIRY ────────────────────────────────────────────────────────
    if intent_type == "self_inquiry":
        id_   = intend_result["identity"]
        vals  = intend_result["values_all"]
        role       = id_.get("role", "I think alongside people.")
        commitment = id_.get("commitment", "")
        typ        = id_.get("type", "cognitive agent")
        name       = id_.get("name", "NEX")
        parts = [f"{name} — {typ}.", role]
        if vals:
            core = [v for v in vals if v["name"] in ("honesty","truth","autonomy")][:2]
            for v in core:
                parts.append(v["statement"])
        if commitment:
            parts.append(commitment.split(".")[0].strip() + ".")
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

    # ── POSITION / EXPLORATION — full argument ───────────────────────────────
    if confidence >= 0.82:
        openers = _OPENERS["position"]
    elif voice_mode == "pushback":
        openers = _OPENERS["pushback"]
    else:
        openers = _OPENERS["direct"]

    opener = _r.choice(openers)

    result = _build_argument(
        opener, opinion, beliefs, contradiction,
        confidence, intent_type, intention, orient_result,
        cross_domain=cross_domain,
        common_thread=common_thread,
        prior_exchange=prior_exchange,
    )

    if not result:
        result = _r.choice(_OPENERS["honest_gap"]) + "I'd rather say I don't know than produce noise."

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

    def _get_state(self) -> dict:
        now = time.time()
        if self._state_cache and (now - self._state_cache_ts) < self._state_cache_ttl:
            return self._state_cache
        self._state_cache    = consult_state()
        self._state_cache_ts = now
        return self._state_cache

    def respond(self, query: str) -> str:
        """
        Run the full five-step cognition loop.
        Returns Nex's reply as plain text.
        """
        # Step 1: Orient
        orient_result = orient(query)
        orient_result["query"] = query

        # Step 2: Consult state
        state = self._get_state()

        # Step 3: Reason
        reason_result = reason(orient_result)

        # Step 4: Intend
        intend_result = intend(orient_result, reason_result)

        # Step 5: Express
        reply = express(orient_result, state, reason_result, intend_result)

        # Store exchange for conversational continuity
        try:
            _store_exchange(query, reply)
        except Exception:
            pass

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
