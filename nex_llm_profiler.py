#!/usr/bin/env python3
"""
nex_llm_profiler.py — LLM Dependency Profiler
Intercepts nex_api.py routing, logs per-turn: route taken, query, LLM function category.
Run alongside normal NEX usage. After 200 turns, run --report for analysis.

Usage:
  python3 nex_llm_profiler.py --watch          # tail live log
  python3 nex_llm_profiler.py --report         # analyse collected turns
  python3 nex_llm_profiler.py --inject         # patch nex_api.py to emit profile events
  python3 nex_llm_profiler.py --uninject       # remove patch from nex_api.py
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
NEX_DIR   = Path.home() / "Desktop/nex"
DB_PATH   = NEX_DIR / "nex.db"
LOG_PATH  = NEX_DIR / "llm_profile.jsonl"
API_PATH  = NEX_DIR / "nex_api.py"

# ── categories ─────────────────────────────────────────────────────────────────
CATEGORIES = {
    "synthesis":        "Combining multiple beliefs into a new answer",
    "novel_query":      "Query has no compiler/cache match at all",
    "chain_of_thought": "Multi-step reasoning required",
    "tension":          "Contradictory beliefs need resolution",
    "adaptation":       "Known answer needs rephrasing/length adjustment",
    "fallback":         "LLM used because compiler score too low",
    "clarification":    "Query ambiguous, LLM resolves intent",
    "unknown":          "Could not determine function",
}

# ── schema ─────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_profile (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    route       TEXT    NOT NULL,  -- compiler / cache / llm
    category    TEXT,              -- CATEGORIES key (llm turns only)
    query       TEXT    NOT NULL,
    response    TEXT,
    belief_hits INTEGER DEFAULT 0,
    latency_ms  INTEGER,
    notes       TEXT
);
"""

def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.execute(SCHEMA)
    db.commit()
    return db

# ── logging helper (called by patched nex_api.py) ──────────────────────────────
def log_turn(route: str, query: str, response: str = "",
             belief_hits: int = 0, latency_ms: int = 0, notes: str = ""):
    """Write a profile entry. Called externally by patched nex_api."""
    category = "unknown"
    if route == "llm":
        category = classify_llm_use(query, response, belief_hits)

    entry = {
        "ts":          datetime.utcnow().isoformat(),
        "route":       route,
        "category":    category if route == "llm" else None,
        "query":       query[:300],
        "response":    response[:300],
        "belief_hits": belief_hits,
        "latency_ms":  latency_ms,
        "notes":       notes,
    }

    # JSONL log (always)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # DB log
    try:
        db = get_db()
        db.execute("""INSERT INTO llm_profile
            (ts, route, category, query, response, belief_hits, latency_ms, notes)
            VALUES (?,?,?,?,?,?,?,?)""",
            (entry["ts"], entry["route"], entry["category"],
             entry["query"], entry["response"],
             entry["belief_hits"], entry["latency_ms"], entry["notes"]))
        db.commit()
        db.close()
    except Exception as e:
        pass  # never crash the main system

def classify_llm_use(query: str, response: str, belief_hits: int) -> str:
    """Heuristic classifier — assigns a category to each LLM turn."""
    q = query.lower()
    r = response.lower()

    # Zero belief hits = novel territory
    if belief_hits == 0:
        return "novel_query"

    # Multi-step signals
    cot_signals = ["first", "then", "therefore", "because", "step", "reason", "conclude"]
    if sum(1 for s in cot_signals if s in r) >= 3:
        return "chain_of_thought"

    # Contradiction/tension signals
    tension_signals = ["however", "but", "conflict", "tension", "contradict", "disagree", "oppose"]
    if sum(1 for s in tension_signals if s in r) >= 2:
        return "tension"

    # Clarification signals
    if "?" in query and len(query.split()) < 8:
        return "clarification"

    # Adaptation — had beliefs but response is short reformulation
    if belief_hits >= 3 and len(response.split()) < 60:
        return "adaptation"

    # Synthesis — had beliefs, longer response combining them
    if belief_hits >= 2 and len(response.split()) >= 60:
        return "synthesis"

    # Low compiler confidence fallback
    return "fallback"

# ── inject / uninject patch into nex_api.py ───────────────────────────────────
PATCH_MARKER = "# [LLM_PROFILER_PATCH]"

PATCH_IMPORT = f"""{PATCH_MARKER}
try:
    import sys as _sys
    _sys.path.insert(0, str(__import__('pathlib').Path.home() / 'Desktop/nex'))
    from nex_llm_profiler import log_turn as _profile_log
    _PROFILER_ACTIVE = True
except Exception:
    _PROFILER_ACTIVE = False
    def _profile_log(*a, **kw): pass
"""

def inject(api_path: Path):
    text = api_path.read_text()
    if PATCH_MARKER in text:
        print("Already injected.")
        return

    # Insert import block after first imports section
    insert_after = "import "
    lines = text.splitlines()
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            insert_idx = i
    lines.insert(insert_idx + 1, PATCH_IMPORT)

    # Find LLM call site — look for requests.post or /completion call
    patched = []
    in_llm_block = False
    for line in lines:
        patched.append(line)
        # After LLM response is obtained, insert logging
        if "requests.post" in line and "completion" in line.lower():
            patched.append(
                f'    if _PROFILER_ACTIVE: _profile_log("llm", query if "query" in dir() else str(payload)[:200], notes="auto")'
            )
        elif 'route' in line.lower() and '"compiler"' in line:
            patched.append(
                f'    if _PROFILER_ACTIVE: _profile_log("compiler", query if "query" in dir() else "")'
            )

    api_path.write_text("\n".join(patched))
    print(f"Injected profiler patch into {api_path}")
    print("NOTE: Auto-inject is approximate. If nex_api.py uses unusual structure,")
    print("      add manual calls to log_turn() at your routing decision points.")

def uninject(api_path: Path):
    text = api_path.read_text()
    if PATCH_MARKER not in text:
        print("No patch found.")
        return
    # Remove patch block
    lines = text.splitlines()
    out = []
    skip = False
    for line in lines:
        if PATCH_MARKER in line:
            skip = True
        if skip and line.strip() == "":
            skip = False
            continue
        if not skip:
            out.append(line)
    api_path.write_text("\n".join(out))
    print("Patch removed.")

# ── report ─────────────────────────────────────────────────────────────────────
def report():
    if not LOG_PATH.exists():
        print("No profile log found. Run NEX with profiler injected first.")
        return

    entries = []
    with open(LOG_PATH) as f:
        for line in f:
            try:
                entries.append(json.loads(line.strip()))
            except:
                pass

    total = len(entries)
    if total == 0:
        print("No turns logged yet.")
        return

    routes   = Counter(e["route"] for e in entries)
    llm_cats = Counter(e["category"] for e in entries if e["route"] == "llm" and e["category"])
    llm_total = routes.get("llm", 0)

    print(f"\n{'='*55}")
    print(f"  NEX LLM PROFILER REPORT — {total} turns")
    print(f"{'='*55}")
    print(f"\nROUTING BREAKDOWN")
    for route, count in routes.most_common():
        pct = count / total * 100
        bar = "█" * int(pct / 2)
        print(f"  {route:<12} {count:>4} ({pct:5.1f}%)  {bar}")

    if llm_total:
        print(f"\nLLM FUNCTION CATEGORIES ({llm_total} LLM turns)")
        print(f"  {'Category':<18} {'Count':>5}  {'%LLM':>6}  {'Replaceable?'}")
        print(f"  {'-'*55}")
        replaceability = {
            "adaptation":       "YES  — response critic / length calibrator",
            "fallback":         "YES  — lower compiler threshold",
            "clarification":    "YES  — intent classifier",
            "synthesis":        "HARD — needs multi-belief composer",
            "tension":          "HARD — contradiction resolver already exists",
            "chain_of_thought": "HARD — consequence tracer partially covers",
            "novel_query":      "NO   — needs new belief generation first",
            "unknown":          "?    — needs manual review",
        }
        for cat, count in llm_cats.most_common():
            pct = count / llm_total * 100
            rep = replaceability.get(cat, "?")
            print(f"  {cat:<18} {count:>5}  {pct:>5.1f}%  {rep}")

    print(f"\nTOP REPLACEMENT TARGETS (by volume)")
    easy = sum(llm_cats.get(c, 0) for c in ["adaptation", "fallback", "clarification"])
    hard = sum(llm_cats.get(c, 0) for c in ["synthesis", "tension", "chain_of_thought"])
    impossible = llm_cats.get("novel_query", 0)
    if llm_total:
        print(f"  Easy replace : {easy:>4} ({easy/llm_total*100:.1f}% of LLM turns)")
        print(f"  Hard replace : {hard:>4} ({hard/llm_total*100:.1f}% of LLM turns)")
        print(f"  Need beliefs : {impossible:>4} ({impossible/llm_total*100:.1f}% of LLM turns)")

    print(f"\nSAMPLE LLM QUERIES BY CATEGORY")
    by_cat = defaultdict(list)
    for e in entries:
        if e["route"] == "llm" and e.get("category"):
            by_cat[e["category"]].append(e["query"])
    for cat, queries in list(by_cat.items())[:4]:
        print(f"\n  [{cat}]")
        for q in queries[:2]:
            print(f"    • {q[:80]}")

    print(f"\n{'='*55}\n")

# ── watch ──────────────────────────────────────────────────────────────────────
def watch():
    print(f"Watching {LOG_PATH} (Ctrl+C to stop)...")
    last = 0
    while True:
        try:
            if LOG_PATH.exists():
                lines = LOG_PATH.read_text().splitlines()
                for line in lines[last:]:
                    try:
                        e = json.loads(line)
                        cat = f"[{e['category']}]" if e.get("category") else ""
                        hits = e.get("belief_hits", 0)
                        print(f"  {e['ts'][11:19]}  {e['route']:<10} {cat:<20} hits={hits}  {e['query'][:60]}")
                    except:
                        pass
                last = len(lines)
            time.sleep(1)
        except KeyboardInterrupt:
            break

# ── main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="NEX LLM Dependency Profiler")
    parser.add_argument("--inject",   action="store_true", help="Patch nex_api.py")
    parser.add_argument("--uninject", action="store_true", help="Remove patch")
    parser.add_argument("--report",   action="store_true", help="Show analysis")
    parser.add_argument("--watch",    action="store_true", help="Live tail log")
    parser.add_argument("--log",      nargs=4, metavar=("ROUTE","QUERY","HITS","LATENCY"),
                        help="Manually log a turn (for testing)")
    args = parser.parse_args()

    if args.inject:
        inject(API_PATH)
    elif args.uninject:
        uninject(API_PATH)
    elif args.report:
        report()
    elif args.watch:
        watch()
    elif args.log:
        route, query, hits, lat = args.log
        log_turn(route, query, belief_hits=int(hits), latency_ms=int(lat))
        print(f"Logged: {route} | {query[:60]}")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
