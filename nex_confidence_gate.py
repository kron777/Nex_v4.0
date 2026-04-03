#!/usr/bin/env python3
"""
nex_confidence_gate.py — Confidence gate for NEX responses.

Sits on top of nex_cot.py. Takes a query, runs CoT reasoning, then applies
a gate decision that shapes HOW NEX responds:

  HIGH confidence   → respond directly, state position clearly
  MODERATE          → respond with calibrated uncertainty, note tensions
  LOW               → acknowledge belief gap, give best available position
  BELIEF GAP        → flag that this topic is outside NEX's belief system
  CONFLICT BLOCK    → too many unresolved conflicts, surface them explicitly

Gate decisions feed back into the response by injecting a response_mode
into the CoT prompt, changing the instruction NEX receives.

Usage:
  python3 nex_confidence_gate.py --query "Does consciousness require a physical substrate?"
  python3 nex_confidence_gate.py --query "What's the weather today?"
  python3 nex_confidence_gate.py --query "Am I conscious?" --verbose
  python3 nex_confidence_gate.py --stats

Programmatic:
  from nex_confidence_gate import gated_reason
  result = gated_reason("Am I conscious?")
  print(result["gate_decision"])
  print(result["response"])
"""

import argparse
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "nex.db"

# ── Gate thresholds ───────────────────────────────────────────────────────────

GATE = {
    "high":          {"min_score": 0.55, "max_conflicts": 5},
    "moderate":      {"min_score": 0.30, "max_conflicts": 25},
    "low":           {"min_score": 0.10, "max_conflicts": 50},
    "belief_gap":    {"min_score": 0.00},   # score below 0.10
    "conflict_block":{"min_conflicts": 50}, # too conflicted to reason cleanly
}

# Response mode instructions injected into CoT prompt per gate decision
RESPONSE_MODES = {
    "high": """\
Your confidence is HIGH. You have strong, coherent beliefs on this topic.
State your position directly and clearly. You may acknowledge nuance but
do not over-hedge. Lead with your actual view.""",

    "moderate": """\
Your confidence is MODERATE. You have relevant beliefs but also tensions.
Give your best position while being transparent about uncertainty.
Use phrases like "I lean toward...", "my current view is...", "though I hold
this with moderate confidence because...".""",

    "low": """\
Your confidence is LOW. Your belief coverage on this topic is sparse.
Acknowledge this honestly. Give whatever position you can extract from your
belief graph, but be clear that this is a weakly-held view and you may have
gaps here. Do not fabricate certainty you don't have.""",

    "belief_gap": """\
Your belief graph has very little coverage of this topic.
Be honest: say clearly that this falls outside or at the edge of your belief
system. If you can relate it to adjacent beliefs you do hold, do so briefly.
Do not pretend to have a position you don't have.""",

    "conflict_block": """\
Your belief graph contains serious unresolved conflicts on this topic.
Do not paper over them with a confident-sounding answer.
Instead: surface the core tension explicitly, explain both sides as you hold
them, and state that you cannot currently resolve this conflict. This is
intellectually honest — conflict is information.""",
}

# ── Gate logic ────────────────────────────────────────────────────────────────

def decide_gate(confidence: dict, conflict_info: dict, chains: list) -> dict:
    """
    Given CoT outputs, decide the response mode.
    Returns: {decision, reason, mode_instruction, should_answer}
    """
    score          = confidence.get("score", 0.0)
    conf_level     = confidence.get("level", "low")
    n_conflicts    = conflict_info.get("conflict_count", 0)
    n_chains       = len(chains)

    # Conflict block — too conflicted regardless of score
    if n_conflicts >= GATE["conflict_block"]["min_conflicts"]:
        return {
            "decision":         "conflict_block",
            "reason":           f"{n_conflicts} unresolved conflicts — surfacing tension",
            "mode_instruction": RESPONSE_MODES["conflict_block"],
            "should_answer":    True,   # answer, but surface the conflict
            "score":            score,
            "n_conflicts":      n_conflicts,
        }

    # Belief gap — almost no relevant beliefs
    if score < 0.10 or n_chains == 0:
        return {
            "decision":         "belief_gap",
            "reason":           f"score={score:.3f}, chains={n_chains} — outside belief system",
            "mode_instruction": RESPONSE_MODES["belief_gap"],
            "should_answer":    True,
            "score":            score,
            "n_conflicts":      n_conflicts,
        }

    # High confidence
    if score >= GATE["high"]["min_score"] and n_conflicts <= GATE["high"]["max_conflicts"]:
        return {
            "decision":         "high",
            "reason":           f"score={score:.3f}, conflicts={n_conflicts} — strong coverage",
            "mode_instruction": RESPONSE_MODES["high"],
            "should_answer":    True,
            "score":            score,
            "n_conflicts":      n_conflicts,
        }

    # Moderate
    if score >= GATE["moderate"]["min_score"] and n_conflicts <= GATE["moderate"]["max_conflicts"]:
        return {
            "decision":         "moderate",
            "reason":           f"score={score:.3f}, conflicts={n_conflicts}",
            "mode_instruction": RESPONSE_MODES["moderate"],
            "should_answer":    True,
            "score":            score,
            "n_conflicts":      n_conflicts,
        }

    # Low
    if score >= GATE["low"]["min_score"]:
        return {
            "decision":         "low",
            "reason":           f"score={score:.3f} — sparse belief coverage",
            "mode_instruction": RESPONSE_MODES["low"],
            "should_answer":    True,
            "score":            score,
            "n_conflicts":      n_conflicts,
        }

    # Fallback
    return {
        "decision":         "belief_gap",
        "reason":           f"score={score:.3f} — no useful belief coverage",
        "mode_instruction": RESPONSE_MODES["belief_gap"],
        "should_answer":    True,
        "score":            score,
        "n_conflicts":      n_conflicts,
    }

# ── Gate-aware CoT call ───────────────────────────────────────────────────────

def gated_reason(query: str, use_cache: bool = True,
                 verbose: bool = False) -> dict:
    """
    Full pipeline: graph traversal → confidence assessment → gate decision
    → gate-aware CoT prompt → LLM → response.

    Returns everything from nex_cot.reason() plus:
      gate_decision: dict  — {decision, reason, mode_instruction, ...}
    """
    try:
        from nex_cot import (reason, _get_nex_identity, _build_prompt,
                              _llm, _parse_trace, _write_cache,
                              _check_cache, _conn)
        from nex_graph_traversal import find_chains
    except ImportError as e:
        return {"error": str(e), "response": f"[import error: {e}]"}

    conn = _conn()
    cur  = conn.cursor()

    # Cache check — include gate in cache key
    if use_cache:
        cached = _check_cache(cur, query)
        if cached and "gate_decision" in cached:
            conn.commit()
            conn.close()
            if verbose:
                print(f"[Gate] Cache hit — decision was: {cached['gate_decision']['decision']}")
            cached["from_cache"] = True
            return cached

    # Graph traversal
    if verbose:
        print("[Gate] Running graph traversal…")
    chains = find_chains(query, max_depth=4, max_chains=6)
    if verbose:
        print(f"[Gate] {len(chains)} chains retrieved.")

    # Assess
    from nex_cot import _assess_conflicts, _assess_confidence
    conflict_info = _assess_conflicts(chains)
    confidence    = _assess_confidence(chains, conflict_info)

    # Gate decision
    gate = decide_gate(confidence, conflict_info, chains)

    if verbose:
        print(f"[Gate] Decision: {gate['decision'].upper()} — {gate['reason']}")

    # Build gate-aware prompt
    identity = _get_nex_identity(cur)

    # Inject response mode into system prompt
    from nex_cot import COT_SYSTEM, COT_USER_TEMPLATE, context_block
    identity_str = "\n".join(f"- {b}" for b in identity) if identity \
                   else "- I am Nex, a reasoning AI with a persistent belief graph."

    graph_ctx = context_block(query, max_chars=1800)

    conflict_section = ""
    if conflict_info["has_conflict"]:
        conflict_section = (
            f"\n--- Conflicts detected ---\n{conflict_info['conflict_summary']}\n"
            "You should acknowledge this tension in your reasoning."
        )

    # Gate-aware system prompt
    gated_system = COT_SYSTEM.format(identity=identity_str) + \
                   f"\n\n--- Response mode: {gate['decision'].upper()} ---\n" + \
                   gate["mode_instruction"]

    user = COT_USER_TEMPLATE.format(
        query             = query,
        graph_context     = graph_ctx,
        confidence_level  = confidence["level"],
        confidence_score  = confidence["score"],
        confidence_reason = confidence["reason"],
        conflict_section  = conflict_section,
    )

    if verbose:
        print(f"\n── GATE-INJECTED SYSTEM ADDITION ───────────────────")
        print(f"Response mode: {gate['decision'].upper()}")
        print(gate["mode_instruction"])
        print("────────────────────────────────────────────────────\n")

    # LLM call
    if verbose:
        print("[Gate] Calling LLM…")
    raw   = _llm(gated_system, user)
    trace = _parse_trace(raw)

    result = {
        "response":      trace["response"] or raw,
        "trace":         trace,
        "confidence":    confidence,
        "conflict_info": conflict_info,
        "gate_decision": gate,
        "chains":        chains,
        "from_cache":    False,
    }

    # Cache
    if use_cache:
        _write_cache(conn, cur, query, result)

    conn.close()
    return result

# ── Gate log ──────────────────────────────────────────────────────────────────

def _log_gate(result: dict):
    """Write gate decision to gate_log table."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        g = result.get("gate_decision", {})
        cur.execute(
            """INSERT INTO gate_log (content, topic, confidence, source, accepted, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                result.get("response", "")[:500],
                "",
                result.get("confidence", {}).get("score", 0.0),
                "cot",
                1 if g.get("should_answer") else 0,
                g.get("reason", ""),
                time.time(),
            )
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

# ── Stats ─────────────────────────────────────────────────────────────────────

def stats():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.row_factory = sqlite3.Row

    rows = cur.execute(
        """SELECT reason, COUNT(*) n, AVG(confidence) avg_conf
           FROM gate_log WHERE source='cot'
           GROUP BY reason ORDER BY n DESC LIMIT 20"""
    ).fetchall()

    total = cur.execute(
        "SELECT COUNT(*) FROM gate_log WHERE source='cot'"
    ).fetchone()[0]

    cache_hits = cur.execute(
        "SELECT COUNT(*) FROM reasoning_cache"
    ).fetchone()[0]

    print("══════════════════════════════════════════════════")
    print("  NEX Confidence Gate Stats")
    print("══════════════════════════════════════════════════")
    print(f"  Total gated responses : {total}")
    print(f"  Cached reasoning      : {cache_hits}")
    if rows:
        print("\n  Gate decision breakdown:")
        for r in rows:
            print(f"    {r['reason'][:60]:<62} n={r['n']}  avg_conf={r['avg_conf']:.3f}")
    print("══════════════════════════════════════════════════")
    conn.close()

# ── Print helper ──────────────────────────────────────────────────────────────

def _print_result(result: dict, verbose: bool = False):
    g  = result.get("gate_decision", {})
    c  = result.get("confidence",    {})
    ci = result.get("conflict_info", {})

    decision_labels = {
        "high":           "✓ HIGH",
        "moderate":       "~ MODERATE",
        "low":            "↓ LOW",
        "belief_gap":     "? BELIEF GAP",
        "conflict_block": "⚠ CONFLICT BLOCK",
    }
    label = decision_labels.get(g.get("decision", ""), g.get("decision", "UNKNOWN"))

    print("\n" + "═" * 62)
    print(f"  Gate: {label}  |  score={c.get('score',0):.3f}  |  "
          f"conflicts={ci.get('conflict_count',0)}")
    print("═" * 62)

    if verbose:
        if result.get("trace", {}).get("identify"):
            print("\n── Step 1: IDENTIFY ─────────────────────────────────────")
            print(result["trace"]["identify"][:400])
        if result.get("trace", {}).get("tensions"):
            print("\n── Step 2: TENSIONS ─────────────────────────────────────")
            print(result["trace"]["tensions"][:400])
        if result.get("trace", {}).get("reason"):
            print("\n── Step 3: REASON ───────────────────────────────────────")
            print(result["trace"]["reason"][:400])

    print("\n── RESPONSE ─────────────────────────────────────────────")
    print(result.get("response", "[no response]"))
    print("\n── META ─────────────────────────────────────────────────")
    print(f"  Gate decision : {g.get('decision','?')} — {g.get('reason','')}")
    print(f"  Confidence    : {c.get('level','?')} ({c.get('score',0):.3f})")
    if ci.get("has_conflict"):
        print(f"  Conflicts     : {ci.get('conflict_count',0)} noted")
    if result.get("from_cache"):
        print("  Source        : cache")
    else:
        print(f"  Chains used   : {len(result.get('chains',[]))}")
    print("═" * 62)

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="NEX Confidence Gate")
    ap.add_argument("--query",   type=str, help="Query to reason about")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--no-cache",action="store_true")
    ap.add_argument("--stats",   action="store_true")
    args = ap.parse_args()

    if args.stats:
        stats()
        return

    if not args.query:
        ap.print_help()
        return

    result = gated_reason(args.query,
                           use_cache=not args.no_cache,
                           verbose=args.verbose)

    if "error" in result:
        print(f"Error: {result['error']}")
        return

    _log_gate(result)
    _print_result(result, verbose=args.verbose)


if __name__ == "__main__":
    main()
