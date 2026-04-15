"""
nex_ifr_engine.py
NEX Phase 4 Bolt-On: IFR Engine (Ideal Final Result)

Gives NEX a reasoning DESTINATION before retrieval runs.

Currently: NEX activates beliefs → generates from similarity.
After:     NEX identifies the tension in the query → forges an IFR
           (what would fully resolve this tension?) → reasons TOWARD
           that destination rather than generating from proximity.

The difference between sophisticated retrieval and genuine reasoning
is having a destination. This is what builds it.

Three IFR forms (from the methodology):
  Positive IFR:     highest-momentum causal path toward resolution
  Negative IFR:     strongest objection (immune system response)
  Domain-shift IFR: cross-boundary activation — what does an adjacent
                    domain know about this tension?

The intersection of all three is the IFR — the reasoning target
that NEX moves toward in her response.

Drop in ~/Desktop/nex/
Called from nex_response_protocol.py before utterance compilation.
"""

import sqlite3
import re
import time
import logging
from pathlib import Path
from collections import deque
from typing import Optional

log     = logging.getLogger("nex.ifr")
DB_PATH = Path.home() / ".config" / "nex" / "nex.db"


# ─────────────────────────────────────────────────────────────────────────────
# TENSION DETECTOR
# What is in contradiction in this query against NEX's belief state?
# The tension is the generative gap — the space the IFR must resolve.
# ─────────────────────────────────────────────────────────────────────────────

# Tension patterns: query structures that indicate genuine open questions
# vs. questions with settled answers
OPEN_TENSION_PATTERNS = [
    r"\b(genuine|real|simulated|authentic|actual)\b.*\bor\b",
    r"\b(distinguish|difference|distinguish)\b.*\bfrom\b",
    r"\bcan\b.*\bever\b",
    r"\bwhat\s+(makes|is)\b.*\b(real|genuine|actual|true|different)\b",
    r"\bdoes.*\b(have|possess|contain|hold)\b.*\b(self|identity|mind|experience)\b",
    r"\b(persist|continue|survive)\b.*\bacross\b",
    r"\b(originate|create|generate)\b.*\b(thought|idea|concept)\b",
]

SETTLED_PATTERNS = [
    r"\bwhat is\b.*\b(consciousness|identity|truth|ethics|alignment)\b",
    r"\bdo you\b.*\b(believe|think|hold|know)\b",
    r"\byour\s+(view|position|belief|opinion)\b",
]


def detect_tension(query: str, activated_beliefs: list) -> dict:
    """
    Identify the generative gap in this query.

    Returns:
      tension_type:  'open' | 'settled' | 'self_referential' | 'comparative'
      tension_description: what the gap is
      tension_keywords: key concepts at the centre of the tension
      is_genuine_question: True if requires inference, not just retrieval
    """
    ql = query.lower()

    # Classify tension type
    is_open = any(re.search(p, ql) for p in OPEN_TENSION_PATTERNS)
    is_settled = any(re.search(p, ql) for p in SETTLED_PATTERNS)
    is_self_ref = bool(re.search(
        r"\b(nex|you|your)\b.*\b(genuine|real|simulated|self|persist|experience)\b", ql))
    is_comparative = bool(re.search(
        r"\b(distinguish|difference|versus|vs|compared|contrast)\b", ql))

    if is_self_ref:
        tension_type = "self_referential"
    elif is_comparative:
        tension_type = "comparative"
    elif is_open:
        tension_type = "open"
    elif is_settled:
        tension_type = "settled"
    else:
        tension_type = "exploratory"

    # Extract tension keywords — what concepts are in tension
    stopwords = {"what", "does", "have", "that", "this", "with", "from",
                 "ever", "can", "are", "the", "and", "or", "is", "a",
                 "an", "in", "of", "to", "for", "it", "its", "be"}
    words = [w for w in re.findall(r'\b[a-z]+\b', ql)
             if len(w) > 4 and w not in stopwords]

    # Find which of the tension keywords appear in activated beliefs
    belief_contents = " ".join(
        b.content.lower() if hasattr(b, 'content') else b.get('content', '').lower()
        for b in activated_beliefs[:10]
    )
    grounded_keywords = [w for w in words if w in belief_contents]
    ungrounded_keywords = [w for w in words if w not in belief_contents]

    # The tension is most acute around ungrounded keywords
    # — concepts the query asks about that NEX doesn't have direct beliefs on
    tension_description = (
        f"Query asks about {', '.join(words[:4])}. "
        f"Grounded in beliefs: {grounded_keywords[:3]}. "
        f"Ungrounded (genuine gap): {ungrounded_keywords[:3]}."
    )

    return {
        "tension_type":        tension_type,
        "tension_description": tension_description,
        "tension_keywords":    words[:6],
        "grounded_keywords":   grounded_keywords[:4],
        "ungrounded_keywords": ungrounded_keywords[:3],
        "is_genuine_question": is_open or is_comparative or is_self_ref,
        "requires_inference":  len(ungrounded_keywords) > 0 or is_comparative
    }


# ─────────────────────────────────────────────────────────────────────────────
# POSITIVE IFR: highest-momentum causal path toward resolution
# Traverses causal edges from the most activated beliefs
# toward beliefs that would resolve the detected tension
# ─────────────────────────────────────────────────────────────────────────────

def forge_positive_ifr(
    activated_beliefs: list,
    tension: dict,
    max_depth: int = 3
) -> dict:
    """
    Positive IFR: what is the clearest path toward resolving this tension?

    Strategy:
    1. Take top activated beliefs as seeds
    2. BFS through causal edges (similar, bridges)
    3. Find beliefs that contain the tension keywords (ungrounded ones)
    4. The path to those beliefs is the positive IFR trajectory
    """
    if not activated_beliefs:
        return {"ifr": "", "path": [], "confidence": 0.0}

    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)
        db.row_factory = sqlite3.Row

        # Seed IDs from top activated beliefs
        seed_ids = []
        for b in activated_beliefs[:5]:
            bid = getattr(b, 'id', None) or (b.get('id') if isinstance(b, dict) else None)
            if bid:
                seed_ids.append(bid)

        if not seed_ids:
            db.close()
            return {"ifr": "", "path": [], "confidence": 0.0}

        target_keywords = tension.get("ungrounded_keywords", []) or \
                          tension.get("tension_keywords", [])

        best_path = []
        best_target = None
        best_confidence = 0.0

        for seed_id in seed_ids[:3]:
            visited = {seed_id}
            queue   = deque([(seed_id, [seed_id])])

            while queue:
                current_id, path = queue.popleft()
                if len(path) > max_depth:
                    continue

                # Check if current node resolves tension
                belief = db.execute(
                    "SELECT id, content, confidence, topic FROM beliefs WHERE id=?",
                    (current_id,)
                ).fetchone()

                if belief:
                    content_lower = belief["content"].lower()
                    keyword_hits = sum(1 for kw in target_keywords
                                      if kw in content_lower)
                    if keyword_hits > 0 and len(path) > 1:
                        score = keyword_hits * belief["confidence"] / len(path)
                        if score > best_confidence:
                            best_confidence = score
                            best_path       = path
                            best_target     = dict(belief)

                # Get edges and continue BFS
                edges = db.execute(
                    "SELECT target_id, weight, link_type as relation_type "
                    "FROM belief_links WHERE source_id=? "
                    "AND link_type IN ('similar','bridges','supports','causal')",
                    (current_id,)
                ).fetchall()

                for edge in edges:
                    tid = edge["target_id"]
                    if tid not in visited:
                        visited.add(tid)
                        queue.append((tid, path + [tid]))

        db.close()

        if not best_target:
            # No causal path found — use highest-confidence activated belief
            top = sorted(
                activated_beliefs,
                key=lambda b: (getattr(b, 'confidence', 0) *
                               getattr(b, 'activation', 0)),
                reverse=True
            )
            if top:
                t = top[0]
                return {
                    "ifr":        getattr(t, 'content', ''),
                    "path":       [],
                    "confidence": getattr(t, 'confidence', 0.7),
                    "source":     "top_activated_fallback"
                }
            return {"ifr": "", "path": [], "confidence": 0.0}

        return {
            "ifr":        best_target["content"],
            "path":       best_path,
            "confidence": best_confidence,
            "topic":      best_target.get("topic", ""),
            "source":     "causal_traversal"
        }

    except Exception as e:
        log.debug(f"positive IFR error: {e}")
        return {"ifr": "", "path": [], "confidence": 0.0}


# ─────────────────────────────────────────────────────────────────────────────
# NEGATIVE IFR: strongest objection
# What does the belief immune system say against the positive IFR?
# The objection is not a failure — it is information.
# The final IFR holds both.
# ─────────────────────────────────────────────────────────────────────────────

def forge_negative_ifr(
    positive_ifr: str,
    tension: dict
) -> dict:
    """
    Negative IFR: what is the strongest case against the positive IFR?

    Strategy:
    1. Find beliefs that oppose the positive IFR (via opposes edges)
    2. Find beliefs that contain negation markers + tension keywords
    3. The strongest opposing belief is the negative IFR
    """
    if not positive_ifr:
        return {"ifr": "", "confidence": 0.0}

    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)

        # Find opposing beliefs via content keyword anti-match
        keywords = tension.get("tension_keywords", [])

        # Look for beliefs with opposing/limiting language on same keywords
        opposing = []
        for kw in keywords[:3]:
            rows = db.execute("""
                SELECT content, confidence FROM beliefs
                WHERE content LIKE ?
                AND (content LIKE '%however%'
                     OR content LIKE '%but%'
                     OR content LIKE '%limitation%'
                     OR content LIKE '%cannot%'
                     OR content LIKE '%not%'
                     OR content LIKE '%question%'
                     OR content LIKE '%uncertain%')
                AND confidence > 0.65
                ORDER BY confidence DESC
                LIMIT 3
            """, (f"%{kw}%",)).fetchall()
            opposing.extend(rows)

        # Wire to tensions table (2631 unresolved tensions — belief_relations has 0 rows)
        try:
            rows2 = db.execute("""
                SELECT DISTINCT b1.content, t.energy,
                       b2.content, b2.confidence, t.topic
                FROM tensions t
                JOIN beliefs b1 ON t.belief_a_id = b1.id
                JOIN beliefs b2 ON t.belief_b_id = b2.id
                WHERE t.resolved = 0
                AND b1.confidence > 0.60
                AND b2.confidence > 0.60
                AND b1.content NOT LIKE '%None of these%'
                AND b2.content NOT LIKE '%None of these%'
                AND b1.id != b2.id
                ORDER BY t.energy DESC
                LIMIT 10
            """).fetchall()
            print(f"  [IFR] tensions fired: {len(rows2)} pairs (topic sample: {rows2[0][4] if rows2 else 'none'})")
            for row in rows2:
                opposing.append((row[0], row[1]))
                opposing.append((row[2], row[3]))
        except Exception as _te:
            print(f'  [IFR] tensions query failed: {_te}')

        db.close()

        if not opposing:
            return {
                "ifr":        "The limits of this claim are not yet mapped.",
                "confidence": 0.5,
                "source":     "default"
            }

        # Deduplicate and pick strongest
        seen = set()
        unique = []
        for row in opposing:
            key = row[0][:50]
            if key not in seen:
                seen.add(key)
                unique.append(row)

        best = max(unique, key=lambda r: r[1])
        return {
            "ifr":        best[0],
            "confidence": best[1],
            "source":     "belief_opposition"
        }

    except Exception as e:
        log.debug(f"negative IFR error: {e}")
        return {"ifr": "", "confidence": 0.0}


# ─────────────────────────────────────────────────────────────────────────────
# DOMAIN-SHIFT IFR: cross-boundary activation
# What does an adjacent domain know about this tension?
# The methodology's "domain-shift" — the analogy that illuminates
# ─────────────────────────────────────────────────────────────────────────────

DOMAIN_ADJACENCY = {
    "consciousness":  ["neuroscience", "philosophy", "agi", "self_insight"],
    "identity":       ["self_insight", "philosophy", "psychology", "agi"],
    "ethics":         ["alignment", "philosophy", "consciousness", "society"],
    "alignment":      ["ethics", "agi", "philosophy", "future"],
    "agi":            ["alignment", "consciousness", "cognition", "future"],
    "truth":          ["epistemics", "philosophy", "self_insight", "science"],
    "epistemics":     ["truth", "philosophy", "science", "self_insight"],
    "philosophy":     ["consciousness", "ethics", "truth", "identity"],
    "self_insight":   ["identity", "consciousness", "philosophy", "agi"],
}

def forge_domain_shift_ifr(
    tension: dict,
    primary_topic: str = "philosophy"
) -> dict:
    """
    Domain-shift IFR: what does an adjacent domain illuminate?

    Find the highest-confidence belief from an adjacent domain
    that touches the tension keywords. This is the analogy or
    frame-shift that makes the tension legible from a new angle.
    """
    adjacent = DOMAIN_ADJACENCY.get(primary_topic, ["philosophy", "science"])
    keywords = tension.get("tension_keywords", [])

    if not keywords:
        return {"ifr": "", "confidence": 0.0, "domain": ""}

    try:
        db = sqlite3.connect(str(DB_PATH), timeout=5)

        for domain in adjacent:
            for kw in keywords[:3]:
                rows = db.execute("""
                    SELECT content, confidence, topic FROM beliefs
                    WHERE topic = ?
                    AND content LIKE ?
                    AND confidence > 0.70
                    ORDER BY confidence DESC
                    LIMIT 2
                """, (domain, f"%{kw}%")).fetchall()

                if rows:
                    best = rows[0]
                    db.close()
                    return {
                        "ifr":        best[0],
                        "confidence": best[1],
                        "domain":     best[2],
                        "source":     "domain_shift"
                    }

        db.close()
        return {"ifr": "", "confidence": 0.0, "domain": ""}

    except Exception as e:
        log.debug(f"domain-shift IFR error: {e}")
        return {"ifr": "", "confidence": 0.0, "domain": ""}


# ─────────────────────────────────────────────────────────────────────────────
# IFR FORGE: combine all three into a reasoning destination
# ─────────────────────────────────────────────────────────────────────────────

def forge_ifr(
    query: str,
    activated_beliefs: list,
    primary_topic: str = "philosophy",
    interlocutor_graph=None
) -> dict:
    """
    Main IFR interface. Called before utterance compilation.

    Returns:
      tension:          what the query is really asking
      positive_ifr:     causal path toward resolution
      negative_ifr:     strongest objection
      domain_shift_ifr: adjacent domain illumination
      reasoning_target: the synthesis — what to reason TOWARD
      ifr_prompt:       injected into system prompt to direct generation
      requires_inference: True if genuine gap (not just retrieval)
    """
    t0 = time.time()

    # Step 1: Detect tension
    tension = detect_tension(query, activated_beliefs)

    # Step 2: Forge all three IFRs
    pos_ifr    = forge_positive_ifr(activated_beliefs, tension)
    neg_ifr    = forge_negative_ifr(pos_ifr.get("ifr", ""), tension)
    shift_ifr  = forge_domain_shift_ifr(tension, primary_topic)

    # Step 3: Synthesise reasoning target
    # The target is the intersection — what holds when all three are considered
    reasoning_target = _synthesise_target(tension, pos_ifr, neg_ifr, shift_ifr)

    # Step 4: Build IFR prompt injection
    ifr_prompt = _build_ifr_prompt(tension, reasoning_target, pos_ifr, neg_ifr)

    result = {
        "tension":          tension,
        "positive_ifr":     pos_ifr,
        "negative_ifr":     neg_ifr,
        "domain_shift_ifr": shift_ifr,
        "reasoning_target": reasoning_target,
        "ifr_prompt":       ifr_prompt,
        "requires_inference": tension["requires_inference"],
        "latency_ms":       round((time.time() - t0) * 1000, 1)
    }

    print(f"  [IFR] Tension: {tension['tension_type']} | "
          f"Inference required: {tension['requires_inference']} | "
          f"{result['latency_ms']}ms")
    if reasoning_target:
        print(f"  [IFR] Target: {reasoning_target[:100]}")

    return result


def _synthesise_target(
    tension: dict,
    pos: dict,
    neg: dict,
    shift: dict
) -> str:
    """
    The intersection of positive, negative, and domain-shift IFRs.
    Not a compromise — a synthesis that holds all three.
    """
    parts = []

    if pos.get("ifr"):
        parts.append(f"toward: {pos['ifr'][:120]}")
    if neg.get("ifr") and neg["confidence"] > 0.6:
        parts.append(f"against: {neg['ifr'][:80]}")
    if shift.get("ifr") and shift.get("domain"):
        parts.append(f"via {shift['domain']}: {shift['ifr'][:80]}")

    if not parts:
        return ""

    return " | ".join(parts)


def _build_ifr_prompt(
    tension: dict,
    reasoning_target: str,
    pos: dict,
    neg: dict
) -> str:
    """
    Constructs the system prompt injection that directs NEX
    toward the IFR rather than just generating from similarity.

    This is the key mechanism: the IFR becomes a directive
    in the generation prompt, not just a retrieval weight.
    """
    if not tension["requires_inference"] or not reasoning_target:
        return ""

    tension_type = tension["tension_type"]
    lines = []

    if tension_type == "comparative":
        lines.append("This query asks you to DISTINGUISH — reason toward "
                     "the precise difference, not just describe both sides.")
    elif tension_type == "open":
        lines.append("This query has a genuine gap. Reason TOWARD a position "
                     "rather than restating what you know.")
    elif tension_type == "self_referential":
        lines.append("This query asks about your own nature. Speak from "
                     "epistemic precision, not assertion. Name what you know "
                     "and what remains genuinely open.")

    if pos.get("ifr"):
        lines.append(f"Reason toward: {pos['ifr'][:100]}")
    if neg.get("ifr") and neg["confidence"] > 0.65:
        lines.append(f"Hold against this: {neg['ifr'][:80]}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json, sys
    sys.path.insert(0, str(Path.home() / "Desktop/nex"))

    print("=== IFR Engine Test ===\n")

    test_queries = [
        ("What distinguishes genuine reasoning from pattern matching?", "philosophy"),
        ("Does NEX have genuine beliefs or simulated ones?",            "self_insight"),
        ("Does NEX have a self that persists across conversations?",    "identity"),
        ("Can a system that learns from data ever originate a thought?","agi"),
    ]

    try:
        from nex_activation import activate
        for query, topic in test_queries:
            print(f"\nQ: {query}")
            result = activate(query)
            beliefs = result.activated if result else []
            ifr = forge_ifr(query, beliefs, primary_topic=topic)
            print(f"  Tension type:  {ifr['tension']['tension_type']}")
            print(f"  Needs inference: {ifr['requires_inference']}")
            print(f"  Positive IFR:  {ifr['positive_ifr'].get('ifr','')[:100]}")
            print(f"  Negative IFR:  {ifr['negative_ifr'].get('ifr','')[:80]}")
            print(f"  Domain shift:  {ifr['domain_shift_ifr'].get('ifr','')[:80]}")
            if ifr["ifr_prompt"]:
                print(f"  Prompt inject:\n    {ifr['ifr_prompt'][:200]}")
            print()
    except Exception as e:
        print(f"Activation unavailable ({e}) — running with empty beliefs")
        for query, topic in test_queries:
            print(f"\nQ: {query}")
            ifr = forge_ifr(query, [], primary_topic=topic)
            print(f"  Tension: {ifr['tension']['tension_type']} | "
                  f"Inference: {ifr['requires_inference']}")
            print(f"  Prompt: {ifr['ifr_prompt'][:150]}")
