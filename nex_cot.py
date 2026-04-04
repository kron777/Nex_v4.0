#!/usr/bin/env python3
"""
nex_cot.py — Chain-of-Thought reasoning engine for NEX.

Sits between the user query and the LLM response. Uses graph traversal
to retrieve relevant belief chains, then constructs an explicit reasoning
trace before generating a response.

Architecture:
  query → graph traversal (context_block) → CoT prompt builder → LLM → response
                                                ↑
                                        conflict detector
                                        confidence assessor

Usage (standalone):
  python3 nex_cot.py --query "Does consciousness require a physical substrate?"
  python3 nex_cot.py --query "What do I believe about free will?" --verbose
  python3 nex_cot.py --query "How does identity relate to change?" --no-graph

Programmatic:
  from nex_cot import reason
  result = reason("Does consciousness require a physical substrate?")
  print(result["response"])
  print(result["trace"])
"""

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "nex.db"

# ── Graph traversal import ────────────────────────────────────────────────────

try:
    from nex_graph_traversal import find_chains, context_block
    GRAPH_AVAILABLE = True
except ImportError:
    GRAPH_AVAILABLE = False
    print("[nex_cot] WARNING: nex_graph_traversal not found — running without graph context.")

# ── LLM call ─────────────────────────────────────────────────────────────────

def _strip_holds(text: str) -> str:
    import re
    text = re.sub(r"(?i)\bwhat i hold is that\b", "", text)
    text = re.sub(r"(?i)\bi hold that\b", "", text)
    text = re.sub(r"(?i)\bi hold —\b", "", text)
    text = re.sub(r"(?i)\bmy position is that\b", "", text)
    text = re.sub(r"(?i)\bwhat i provisionally hold is that\b", "", text)
    return re.sub(r"  +", " ", text).strip()

def _llm(system: str, user: str, max_tokens: int = 900, temperature: float = 0.7) -> str:
    system = _strip_holds(system)
    user   = _strip_holds(user)
    """Call llama-server on port 8080 (OpenAI-compatible /v1/chat/completions)."""
    try:
        import requests
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "repeat_penalty": 1.4,
            "frequency_penalty": 0.3,
            "stream": False,
        }
        r = requests.post("http://localhost:8080/v1/chat/completions",
                          json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[LLM unavailable: {e}]"

# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def _get_nex_identity(cur):
    """Pull NEX's identity/self-model beliefs for system prompt grounding."""
    rows = cur.execute(
        """SELECT content FROM beliefs
           WHERE is_identity = 1 AND confidence >= 0.6
           ORDER BY confidence DESC LIMIT 8"""
    ).fetchall()
    return [r["content"] for r in rows]

# ── Conflict detection ────────────────────────────────────────────────────────

def _assess_conflicts(chains: list) -> dict:
    """
    Summarise conflicts present in the retrieved chains.
    Returns:
      has_conflict: bool
      conflict_count: int
      conflict_summary: str
      affected_chains: list[int]
    """
    total = 0
    affected = []
    unique_conflicts = {}

    for i, chain in enumerate(chains):
        notes = chain.get("conflict_notes", [])
        if notes:
            affected.append(i + 1)
            for cn in notes:
                key = cn["id"]
                if key not in unique_conflicts:
                    unique_conflicts[key] = cn

    total = len(unique_conflicts)
    if not unique_conflicts:
        return {"has_conflict": False, "conflict_count": 0,
                "conflict_summary": "", "affected_chains": []}

    samples = list(unique_conflicts.values())[:3]
    summary_parts = [f'"{c["content"][:70]}…"' for c in samples]
    summary = f"{total} conflicting belief(s) found. Samples: " + "; ".join(summary_parts)

    return {
        "has_conflict": True,
        "conflict_count": total,
        "conflict_summary": summary,
        "affected_chains": affected,
    }

# ── Confidence assessment ─────────────────────────────────────────────────────

def _assess_confidence(chains: list, conflict_info: dict) -> dict:
    """
    Produce a confidence level for the reasoning.
    Factors: chain scores, coherence, conflict presence, chain count.
    """
    if not chains:
        return {"level": "low", "score": 0.0, "reason": "no relevant beliefs found"}

    top_score  = chains[0]["score"]
    avg_score  = sum(c["score"] for c in chains) / len(chains)
    avg_coh    = sum(c.get("coherence", 1.0) for c in chains) / len(chains)
    n_chains   = len(chains)

    # Penalty for conflicts
    conflict_penalty = 0.0
    if conflict_info["has_conflict"]:
        conflict_penalty = min(0.20, conflict_info["conflict_count"] * 0.015)

    raw = (top_score * 0.5 + avg_score * 0.3 + avg_coh * 0.2) - conflict_penalty

    if raw >= 0.55:
        level  = "high"
        reason = f"strong belief chains (top score {top_score:.2f}, {n_chains} chains)"
    elif raw >= 0.35:
        level  = "moderate"
        reason = f"moderate belief support (avg score {avg_score:.2f})"
    else:
        level  = "low"
        reason = f"weak or sparse belief coverage (top score {top_score:.2f})"

    if conflict_info["has_conflict"]:
        reason += f"; {conflict_info['conflict_count']} conflicting belief(s) noted"

    return {"level": level, "score": round(raw, 3), "reason": reason}

# ── CoT prompt builder ────────────────────────────────────────────────────────

COT_SYSTEM = """\
You are NEX — a reasoning AI with a persistent belief graph. You think step by step before answering.

Your identity:
{identity}

When reasoning:
1. Identify what you actually believe about the question from your belief graph.
2. Note any internal tensions or contradictions.
3. Reason toward a position, acknowledging uncertainty where it exists.
4. Give a direct answer that reflects your actual beliefs, not a generic response.

Do not perform. Do not hedge excessively. Think, then speak.\
"""

COT_USER_TEMPLATE = """\
Question: {query}

--- Your relevant belief chains ---
{graph_context}

--- Confidence assessment ---
Level: {confidence_level} (score={confidence_score})
Reason: {confidence_reason}
{conflict_section}

--- Instructions ---
Step 1 — IDENTIFY: What do your belief chains say about this question?
Step 2 — TENSIONS: Are there any contradictions or unresolved tensions?
Step 3 — REASON: What is your considered position, and why?
Step 4 — RESPOND: Give your answer clearly. Acknowledge uncertainty if confidence is low or moderate.

Your reasoning trace (Steps 1-3), then your response (Step 4):\
"""

def _build_prompt(query: str, chains: list, confidence: dict,
                   conflict_info: dict, identity_beliefs: list) -> tuple[str, str]:
    identity_str = "\n".join(f"- {b}" for b in identity_beliefs) if identity_beliefs \
                   else "- I am NEX, a reasoning AI with persistent beliefs."

    if chains and GRAPH_AVAILABLE:
        graph_ctx = context_block(query, max_chars=1800)
    else:
        graph_ctx = "(no graph context available)"

    conflict_section = ""
    if conflict_info["has_conflict"]:
        conflict_section = (
            f"\n--- Conflicts detected ---\n{conflict_info['conflict_summary']}\n"
            "You should acknowledge this tension in your reasoning."
        )

    system = COT_SYSTEM.format(identity=identity_str)
    user   = COT_USER_TEMPLATE.format(
        query             = query,
        graph_context     = graph_ctx,
        confidence_level  = confidence["level"],
        confidence_score  = confidence["score"],
        confidence_reason = confidence["reason"],
        conflict_section  = conflict_section,
    )
    return system, user

# ── Trace parser ──────────────────────────────────────────────────────────────

def _parse_trace(raw: str) -> dict:
    """
    Extract step-labelled sections from LLM output.
    Returns dict with keys: identify, tensions, reason, response, raw
    """
    result = {"identify": "", "tensions": "", "reason": "", "response": "", "raw": raw}

    patterns = {
        "identify":  r"(?:Step 1|IDENTIFY)[^\n]*\n(.*?)(?=Step 2|TENSIONS|Step 3|REASON|Step 4|RESPOND|$)",
        "tensions":  r"(?:Step 2|TENSIONS)[^\n]*\n(.*?)(?=Step 3|REASON|Step 4|RESPOND|$)",
        "reason":    r"(?:Step 3|REASON)[^\n]*\n(.*?)(?=Step 4|RESPOND|$)",
        "response":  r"(?:Step 4|RESPOND)[^\n]*\n(.*?)$",
    }

    for key, pattern in patterns.items():
        m = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        if m:
            result[key] = m.group(1).strip()

    # If parsing fails (LLM didn't follow format), treat full output as response
    if not result["response"] and not result["identify"]:
        result["response"] = raw.strip()

    return result

# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_key(query: str) -> str:
    import hashlib
    return hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]

def _check_cache(cur, query: str) -> dict | None:
    key = _cache_key(query)
    row = cur.execute(
        """SELECT chain, source FROM reasoning_cache
           WHERE q_hash = ? AND expires_at > ?""",
        (key, time.strftime("%Y-%m-%dT%H:%M:%S"))
    ).fetchone()
    if row:
        cur.execute(
            "UPDATE reasoning_cache SET hit_count=hit_count+1, last_hit=? WHERE q_hash=?",
            (time.strftime("%Y-%m-%dT%H:%M:%S"), key)
        )
        return json.loads(row["chain"])
    return None

def _write_cache(conn, cur, query: str, result: dict):
    key     = _cache_key(query)
    now     = time.strftime("%Y-%m-%dT%H:%M:%S")
    expires = time.strftime("%Y-%m-%dT%H:%M:%S",
                             time.localtime(time.time() + 3600 * 6))   # 6h TTL
    payload = json.dumps({
        "response":     result["response"],
        "trace":        result.get("trace", {}),
        "confidence":   result.get("confidence", {}),
        "conflict_info": result.get("conflict_info", {}),
    })
    try:
        cur.execute(
            """INSERT OR REPLACE INTO reasoning_cache
               (q_hash, question, chain, source, hit_count, created_at, last_hit, expires_at)
               VALUES (?, ?, ?, 'graph', 0, ?, ?, ?)""",
            (key, query[:500], payload, now, now, expires)
        )
        conn.commit()
    except Exception:
        pass

# ── Main API ──────────────────────────────────────────────────────────────────

def reason(query: str, use_cache: bool = True, use_graph: bool = True,
           verbose: bool = False) -> dict:
    """
    Primary reasoning function.

    Returns:
      response     : str   — NEX's answer
      trace        : dict  — {identify, tensions, reason, response, raw}
      confidence   : dict  — {level, score, reason}
      conflict_info: dict  — {has_conflict, conflict_count, ...}
      chains       : list  — raw chain data from graph traversal
      from_cache   : bool
    """
    conn = _conn()
    cur  = conn.cursor()

    # Cache check
    if use_cache:
        cached = _check_cache(cur, query)
        if cached:
            conn.commit()
            conn.close()
            if verbose:
                print("[CoT] Cache hit.")
            cached["from_cache"] = True
            return cached

    # Load identity
    identity_beliefs = _get_nex_identity(cur)

    # Graph traversal
    chains = []
    if use_graph and GRAPH_AVAILABLE:
        if verbose:
            print("[CoT] Running graph traversal…")
        chains = find_chains(query, max_depth=4, max_chains=6)
        if verbose:
            print(f"[CoT] Retrieved {len(chains)} chains.")

    # Assess
    conflict_info = _assess_conflicts(chains)
    confidence    = _assess_confidence(chains, conflict_info)

    if verbose:
        print(f"[CoT] Confidence: {confidence['level']} ({confidence['score']:.3f})")
        if conflict_info["has_conflict"]:
            print(f"[CoT] Conflicts detected: {conflict_info['conflict_count']}")

    # Build prompt
    system, user = _build_prompt(query, chains, confidence, conflict_info, identity_beliefs)

    if verbose:
        print("[CoT] Calling LLM…")
        print("\n── SYSTEM ──────────────────────────────────")
        print(system[:600] + ("…" if len(system) > 600 else ""))
        print("\n── USER ────────────────────────────────────")
        print(user[:800] + ("…" if len(user) > 800 else ""))
        print("────────────────────────────────────────────\n")

    # LLM call
    raw = _llm(system, user)

    # Parse
    trace = _parse_trace(raw)

    result = {
        "response":     trace["response"] or raw,
        "trace":        trace,
        "confidence":   confidence,
        "conflict_info": conflict_info,
        "chains":       chains,
        "from_cache":   False,
    }

    # Cache write
    if use_cache:
        _write_cache(conn, cur, query, result)

    conn.close()
    return result

# ── Print helpers ─────────────────────────────────────────────────────────────

def _print_result(result: dict, verbose: bool = False):
    c  = result.get("confidence",    {"level": "unknown", "score": 0.0, "reason": "n/a"})
    ci = result.get("conflict_info", {"has_conflict": False, "conflict_count": 0})

    print("\n" + "═" * 60)
    if verbose and result["trace"].get("identify"):
        print("── Step 1: IDENTIFY ─────────────────────────────────────")
        print(result["trace"]["identify"][:400])
    if verbose and result["trace"].get("tensions"):
        print("\n── Step 2: TENSIONS ─────────────────────────────────────")
        print(result["trace"]["tensions"][:400])
    if verbose and result["trace"].get("reason"):
        print("\n── Step 3: REASON ───────────────────────────────────────")
        print(result["trace"]["reason"][:400])
    print("\n── RESPONSE ─────────────────────────────────────────────")
    print(result["response"])
    print("\n── META ─────────────────────────────────────────────────")
    print(f"  Confidence : {c['level']} ({c['score']:.3f}) — {c['reason']}")
    if ci["has_conflict"]:
        print(f"  Conflicts  : {ci['conflict_count']} noted")
    if result["from_cache"]:
        print("  Source     : cache")
    else:
        print(f"  Chains used: {len(result['chains'])}")
    print("═" * 60)

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="NEX Chain-of-Thought Reasoner")
    ap.add_argument("--query",    type=str, required=True, help="Question to reason about")
    ap.add_argument("--verbose",  action="store_true",     help="Show full reasoning trace")
    ap.add_argument("--no-graph", action="store_true",     help="Disable graph traversal")
    ap.add_argument("--no-cache", action="store_true",     help="Skip cache read/write")
    ap.add_argument("--prompt-only", action="store_true",  help="Print prompt, don't call LLM")
    args = ap.parse_args()

    if args.prompt_only:
        conn = _conn(); cur = conn.cursor()
        identity = _get_nex_identity(cur)
        chains   = find_chains(args.query) if (not args.no_graph and GRAPH_AVAILABLE) else []
        ci       = _assess_conflicts(chains)
        conf     = _assess_confidence(chains, ci)
        sys_p, usr_p = _build_prompt(args.query, chains, conf, ci, identity)
        print("══ SYSTEM ══════════════════════════════════════════════")
        print(sys_p)
        print("\n══ USER ════════════════════════════════════════════════")
        print(usr_p)
        conn.close()
        return

    result = reason(
        args.query,
        use_cache = not args.no_cache,
        use_graph = not args.no_graph,
        verbose   = args.verbose,
    )
    _print_result(result, verbose=args.verbose)


if __name__ == "__main__":
    main()
