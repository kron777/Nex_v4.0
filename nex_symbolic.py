"""
nex_symbolic.py  —  NEX Neurosymbolic Reasoning Layer
══════════════════════════════════════════════════════
Sits between pass3_retrieve and pass4_relate in nex_cognition.py.

The neural side (pass3) retrieves beliefs by semantic scoring.
This layer validates them symbolically before they reach the response.

What it does:
  Rule 1  ANCHOR      — world_model beliefs get top-slot priority
  Rule 2  CONTRADICT  — removes contradictions before they reach compose
  Rule 3  CONF GATE   — low-confidence beliefs can't drive the primary slot
  Rule 4  PREDICATE   — world_model predicates flag beliefs that violate them
  Rule 5  STANCE      — signals ctx.symbolic_verdict for pass5/pass6 to use

Design constraints:
  • No LLM calls — must be fast (hot path)
  • Graceful fallback — if anything fails, beliefs pass through unchanged
  • World-model cache — loaded once, reused every call
  • Adds ctx.symbolic_verdict and ctx.symbolic_flags to the residual stream

Wire-in (nex_cognition.py):
    from nex_symbolic import symbolic_pass, init_symbolic
    init_symbolic()          # call once at module load
    # between pass3 and pass4:
    pass3b_symbolic(ctx)     # defined in cognition as a one-liner
"""

from __future__ import annotations
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

# ── paths ─────────────────────────────────────────────────────────────────────
_DB_CANDIDATES = [
    Path.home() / "Desktop" / "nex" / "nex.db",
    Path.home() / ".config" / "nex" / "nex.db",
]

def _find_db() -> Optional[Path]:
    for p in _DB_CANDIDATES:
        if p.exists():
            return p
    return None

# ── world-model cache ─────────────────────────────────────────────────────────
_WM_BELIEFS:    list[dict] = []   # {content, confidence, words}
_WM_PREDICATES: list[dict] = []   # {subject, pred_type, object, source}
_WM_LOADED_AT:  float      = 0.0
_WM_TTL:        float      = 3600.0   # reload every hour

_STOP = {
    "that","this","with","from","have","been","they","what","when","were",
    "their","there","would","could","should","which","about","into","onto",
    "also","very","some","only","more","most","just","will","does","like",
}

def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOP}

def _sim(a_words: set, b: str) -> float:
    bw = _words(b)
    if not a_words or not bw: return 0.0
    return len(a_words & bw) / max(len(a_words | bw), 1)

# ── predicate extraction ──────────────────────────────────────────────────────
# Simple patterns: "X is Y", "X are Y", "X cannot Y", "X always Y", "X never Y"
_PRED_PATTERNS = [
    (r"(\w[\w\s]{2,20}?)\s+(?:is|are)\s+(?:not\s+)?(\w[\w\s]{1,20})",  "is"),
    (r"(\w[\w\s]{2,20}?)\s+cannot\s+(\w[\w\s]{1,20})",                  "cannot"),
    (r"(\w[\w\s]{2,20}?)\s+always\s+(\w[\w\s]{1,20})",                  "always"),
    (r"(\w[\w\s]{2,20}?)\s+never\s+(\w[\w\s]{1,20})",                   "never"),
    (r"(\w[\w\s]{2,20}?)\s+requires?\s+(\w[\w\s]{1,20})",               "requires"),
    (r"(\w[\w\s]{2,20}?)\s+causes?\s+(\w[\w\s]{1,20})",                 "causes"),
]

def _extract_predicates(text: str) -> list[dict]:
    predicates = []
    tl = text.lower()
    for pattern, pred_type in _PRED_PATTERNS:
        for m in re.finditer(pattern, tl):
            subj = m.group(1).strip()
            obj  = m.group(2).strip()
            if len(subj) > 3 and len(obj) > 3:
                predicates.append({
                    "subject":   subj,
                    "pred_type": pred_type,
                    "object":    obj,
                    "source":    text[:80],
                })
    return predicates[:3]   # cap per belief

def _negate(pred_type: str) -> str:
    """Return the logical negation of a predicate type."""
    return {
        "is":       "is_not",
        "cannot":   "can",
        "always":   "never",
        "never":    "always",
        "requires": "blocks",
        "causes":   "prevents",
    }.get(pred_type, "not_" + pred_type)

# ── loader ────────────────────────────────────────────────────────────────────
def _load_world_model():
    global _WM_BELIEFS, _WM_PREDICATES, _WM_LOADED_AT

    db_path = _find_db()
    if not db_path:
        return

    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
        tc   = "content" if "content" in cols else ("belief" if "belief" in cols else "text")

        rows = conn.execute(f"""
            SELECT {tc}, confidence
            FROM beliefs
            WHERE (source LIKE 'world_model:%' OR tags LIKE '%world_model%')
            AND confidence >= 0.70
            ORDER BY confidence DESC
            LIMIT 200
        """).fetchall()
        conn.close()

        _WM_BELIEFS = [
            {"content": r[0], "confidence": r[1] or 0.8, "words": _words(r[0])}
            for r in rows if r[0] and len(r[0]) > 15
        ]

        # Extract predicates from all world_model beliefs
        _WM_PREDICATES = []
        for b in _WM_BELIEFS:
            _WM_PREDICATES.extend(_extract_predicates(b["content"]))

        _WM_LOADED_AT = time.time()
        print(f"  [Symbolic] world_model loaded: {len(_WM_BELIEFS)} anchors  "
              f"{len(_WM_PREDICATES)} predicates", flush=True)

    except Exception as e:
        print(f"  [Symbolic] load error: {e}", flush=True)

def init_symbolic():
    """Call once at module load to prime the world-model cache."""
    _load_world_model()

def _ensure_fresh():
    if time.time() - _WM_LOADED_AT > _WM_TTL:
        _load_world_model()

# ── contradiction detection ───────────────────────────────────────────────────
_NEG_PAIRS = [
    ("always",    "never"),
    ("everything","nothing"),
    ("all ",      "none "),
    ("possible",  "impossible"),
    ("can ",      "cannot "),
    ("is real",   "is not real"),
    ("exists",    "does not exist"),
    ("must ",     "must not "),
    ("true",      "false"),
]

def _contradicts_pair(a: str, b: str) -> bool:
    al, bl = a.lower(), b.lower()
    for pos, neg in _NEG_PAIRS:
        if (pos in al and neg in bl) or (neg in al and pos in bl):
            return True
    # High word-overlap + opposing sentiment is also a contradiction signal
    wa, wb = _words(a), _words(b)
    if not wa or not wb: return False
    overlap = len(wa & wb) / max(len(wa | wb), 1)
    _pos_words = {"always","proven","true","confirms","demonstrates","enables"}
    _neg_words = {"never","false","wrong","disproves","contradicts","prevents"}
    if overlap > 0.55:
        if (wa & _pos_words and wb & _neg_words) or (wb & _pos_words and wa & _neg_words):
            return True
    return False

# ── predicate violation check ─────────────────────────────────────────────────
def _violates_predicates(belief_text: str) -> list[str]:
    """
    Return list of world_model predicates that this belief appears to violate.
    Only fires if word overlap with the predicate's subject is high (> 0.5).
    """
    violations = []
    bl = belief_text.lower()
    bw = _words(belief_text)

    for pred in _WM_PREDICATES:
        subj_words = _words(pred["subject"])
        if not subj_words: continue
        subj_overlap = len(subj_words & bw) / max(len(subj_words), 1)
        if subj_overlap < 0.5: continue

        # Check if the belief uses the negation of the predicate
        obj_words = _words(pred["object"])
        negated = _negate(pred["pred_type"])

        # Simple check: does the belief contain negation signal near the object?
        for ow in obj_words:
            if ow in bl:
                for pos, neg in _NEG_PAIRS:
                    if pred["pred_type"] in ("is","always","can") and neg.strip() in bl:
                        violations.append(pred["source"][:50])
                        break

    return violations[:2]

# ── Rule 1: world-model anchor injection ──────────────────────────────────────
def _rule_anchor(beliefs: list[tuple], query_words: set) -> tuple[list[tuple], bool]:
    """
    If a world_model belief is relevant to the query, inject it at position 0.
    Returns (beliefs, anchored).
    """
    if not _WM_BELIEFS:
        return beliefs, False

    best_wm = None
    best_sim = 0.30   # min relevance threshold

    for wm in _WM_BELIEFS:
        s = _sim(query_words, wm["content"])
        if s > best_sim:
            best_sim = s
            best_wm  = wm

    if not best_wm:
        return beliefs, False

    # Check if already present (first 80 chars match)
    already = any(b[0][:60] == best_wm["content"][:60] for b in beliefs)
    if already:
        return beliefs, True

    # Inject at position 0, score boosted
    injected = (best_wm["content"], best_sim * 15.0)
    return [injected] + beliefs[:5], True

# ── Rule 2: contradiction guard ───────────────────────────────────────────────
def _rule_contradict(beliefs: list[tuple]) -> tuple[list[tuple], bool]:
    """
    If top-2 beliefs contradict, demote the lower-scored one.
    Returns (beliefs, contradiction_found).
    """
    if len(beliefs) < 2:
        return beliefs, False

    a_text, a_score = beliefs[0]
    b_text, b_score = beliefs[1]

    if _contradicts_pair(a_text, b_text):
        # Keep higher-scored, push lower to position 3
        if a_score >= b_score:
            reordered = [beliefs[0]] + beliefs[2:] + [beliefs[1]]
        else:
            reordered = [beliefs[1]] + beliefs[2:] + [beliefs[0]]
        return reordered, True

    return beliefs, False

# ── Rule 3: confidence gate ───────────────────────────────────────────────────
def _rule_conf_gate(beliefs: list[tuple], db_path: Optional[Path]) -> list[tuple]:
    """
    Retrieve actual confidence values and gate the primary slot.
    Demotes beliefs that are:
      - confidence < 0.35 (too uncertain to lead)
      - ontology_hollow = 1 (linguistically fluent but conceptually empty)
    """
    if not beliefs or not db_path:
        return beliefs

    primary_text = beliefs[0][0]
    try:
        conn = sqlite3.connect(str(db_path), timeout=3)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
        tc   = "content" if "content" in cols else ("belief" if "belief" in cols else "text")

        select_cols = "confidence"
        if "ontology_hollow" in cols:
            select_cols += ", ontology_hollow"

        row = conn.execute(
            f"SELECT {select_cols} FROM beliefs WHERE {tc} LIKE ? LIMIT 1",
            (primary_text[:60] + "%",)
        ).fetchone()
        conn.close()

        if row:
            conf   = row[0]
            hollow = row[1] if len(row) > 1 else 0

            if (conf is not None and conf < 0.35) or hollow:
                # Demote primary — too weak or ontologically hollow
                return beliefs[1:] + [beliefs[0]]
    except Exception:
        pass

    return beliefs

# ── Rule 4: predicate violation flagging ──────────────────────────────────────
def _rule_predicates(beliefs: list[tuple]) -> list[str]:
    """
    Check each belief against world_model predicates.
    Returns list of violation descriptions (for ctx.symbolic_flags).
    """
    flags = []
    if not _WM_PREDICATES:
        return flags

    for text, score in beliefs[:4]:
        violations = _violates_predicates(text)
        for v in violations:
            flags.append(f"predicate_violation: '{text[:40]}' vs world_model '{v}'")

    return flags

# ── MAIN SYMBOLIC PASS ────────────────────────────────────────────────────────
def symbolic_pass(
    beliefs:     list[tuple],
    query_words: set,
    intent:      str = "topical",
) -> tuple[list[tuple], str, list[str]]:
    """
    Run all 4 symbolic rules on the retrieved beliefs.

    Args:
        beliefs:     list of (content, score) from pass3_retrieve
        query_words: ctx.clean_words from pass1_parse
        intent:      ctx.intent from pass1_parse

    Returns:
        (filtered_beliefs, verdict, flags)
        verdict: "clean" | "anchored" | "flagged" | "bypass"
        flags:   list of symbolic flag strings for ctx.symbolic_flags
    """
    _ensure_fresh()

    if not beliefs:
        return beliefs, "bypass", []

    flags: list[str] = []
    verdict = "clean"

    try:
        db_path = _find_db()

        # Rule 1: world-model anchor
        if _WM_BELIEFS and intent not in ("casual",):
            beliefs, anchored = _rule_anchor(beliefs, query_words)
            if anchored:
                verdict = "anchored"
                flags.append("world_model_anchor_injected")

        # Rule 2: contradiction guard
        beliefs, contra_found = _rule_contradict(beliefs)
        if contra_found:
            flags.append("contradiction_resolved")
            if verdict == "clean":
                verdict = "flagged"

        # Rule 3: confidence gate
        beliefs = _rule_conf_gate(beliefs, db_path)

        # Rule 4: predicate violations
        pred_flags = _rule_predicates(beliefs)
        if pred_flags:
            flags.extend(pred_flags)
            verdict = "flagged"

    except Exception as e:
        # Never break cognition — pass through unchanged
        flags.append(f"symbolic_error: {e}")
        verdict = "bypass"

    return beliefs, verdict, flags


# ── STATUS ────────────────────────────────────────────────────────────────────
def symbolic_status() -> dict:
    return {
        "wm_anchors":    len(_WM_BELIEFS),
        "wm_predicates": len(_WM_PREDICATES),
        "cache_age_s":   round(time.time() - _WM_LOADED_AT, 0),
        "cache_ttl_s":   _WM_TTL,
    }
