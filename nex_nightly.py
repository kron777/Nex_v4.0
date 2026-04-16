#!/usr/bin/env python3
"""
nex_nightly.py  —  NEX Nightly Belief-Graph Consolidation
══════════════════════════════════════════════════════════
Belief-graph-level consolidation. Runs after idle / on schedule.
Complements nex_consolidation.py (which handles conversation-level ops).

Pipeline:
  Phase 0  ASSESS      — homeostasis state, zone, aggressiveness
  Phase 1  CLUSTER     — group beliefs by tag + word-overlap
  Phase 2  SYNTHESIZE  — LLM meta-belief per cluster (zone-capped)
  Phase 3  CONTRADICT  — resolve graph conflicts; world_model always wins
  Phase 4  COMPRESS    — dedup + decay weak beliefs (world_model exempt)
  Phase 5  GRAPH       — rebuild BeliefGraph, update GoalSystem, log Episode
  Phase 6  EMERGE      — cross-cluster emergent insight
  Phase 7  REPORT      — write to consolidation_log + narrative thread

Protections:
  • world_model beliefs:  immune to decay, win all contradictions, anchor synthesis
  • zone=crisis:          compress + decay only — no new synthesis
  • zone=stressed:        synthesis capped at 25% of calm rate

Run:
  python3 ~/Desktop/nex/nex_nightly.py             # auto (skips if ran < 6h ago)
  python3 ~/Desktop/nex/nex_nightly.py --force     # run regardless
  python3 ~/Desktop/nex/nex_nightly.py --dry-run   # report only, no DB writes

Cron (3am daily):
  0 3 * * * /home/rr/Desktop/nex/venv/bin/python3 /home/rr/Desktop/nex/nex_nightly.py
"""

from __future__ import annotations
import argparse, json, math, os, re, sqlite3, sys, time, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── paths ─────────────────────────────────────────────────────────────────────
NEX_DIR   = Path.home() / "Desktop" / "nex"
DB_PATH   = NEX_DIR / "nex.db"
LOG_DIR   = NEX_DIR / "logs"
LLAMA_URL = "http://127.0.0.1:8080"
LOG_DIR.mkdir(parents=True, exist_ok=True)

MIN_HOURS_BETWEEN_RUNS = 6      # skip if ran recently
WORLD_MODEL_TAG        = "world_model"
WORLD_MODEL_SRC_PREFIX = "world_model:"

# ── colour ────────────────────────────────────────────────────────────────────
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    C = {
        "purple": Fore.MAGENTA + Style.BRIGHT,
        "cyan":   Fore.CYAN    + Style.BRIGHT,
        "green":  Fore.GREEN   + Style.BRIGHT,
        "yellow": Fore.YELLOW  + Style.BRIGHT,
        "red":    Fore.RED     + Style.BRIGHT,
        "grey":   Fore.WHITE   + Style.DIM,
        "white":  Fore.WHITE   + Style.BRIGHT,
        "reset":  Style.RESET_ALL,
    }
except ImportError:
    C = {k: "" for k in ["purple","cyan","green","yellow","red","grey","white","reset"]}

def _hdr(title):
    print(f"\n{C['purple']}  ┌{'─'*46}┐{C['reset']}")
    print(f"{C['purple']}  │  {title:<44}│{C['reset']}")
    print(f"{C['purple']}  └{'─'*46}┘{C['reset']}")

def _ok(msg):   print(f"  {C['green']}✓{C['reset']}  {msg}")
def _info(msg): print(f"  {C['grey']}→{C['reset']}  {msg}")
def _warn(msg): print(f"  {C['yellow']}⚠{C['reset']}  {msg}")
def _err(msg):  print(f"  {C['red']}✗{C['reset']}  {msg}")

# ── llama ─────────────────────────────────────────────────────────────────────
def _llm(prompt: str, max_tokens: int = 600, temperature: float = 0.3) -> str:
    payload = json.dumps({
        "prompt":      prompt,
        "n_predict":   max_tokens,
        "temperature": temperature,
        "stop":        ["</beliefs>", "---END---", "<|user|>", "<|system|>", "||"],
    }).encode()
    req = urllib.request.Request(
        f"{LLAMA_URL}/completion",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read()).get("content", "").strip()
    except Exception:
        return ""

def _llm_reachable() -> bool:
    try:
        urllib.request.urlopen(f"{LLAMA_URL}/health", timeout=3)
        return True
    except Exception:
        return False

# ── DB helpers ────────────────────────────────────────────────────────────────
def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def _text_col(conn: sqlite3.Connection) -> str:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
    return "content" if "content" in cols else ("belief" if "belief" in cols else "text")

def _load_beliefs(conn: sqlite3.Connection) -> list[dict]:
    tc = _text_col(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
    extra = []
    if "tags"       in cols: extra.append("tags")
    if "momentum"   in cols: extra.append("momentum")
    if "source"     in cols: extra.append("source")
    if "created_at" in cols: extra.append("created_at")
    sel = f"SELECT id, {tc}, confidence, {', '.join(extra)} FROM beliefs"
    rows = conn.execute(sel).fetchall()
    beliefs = []
    for r in rows:
        d = {
            "id":         r["id"],
            "content":    r[tc],
            "confidence": r["confidence"] or 0.5,
            "tags":       (r["tags"] if "tags" in extra else "") or "",
            "momentum":   float(r["momentum"] if "momentum" in extra else 0.5),
            "source":     (r["source"] if "source" in extra else "") or "",
        }
        beliefs.append(d)
    return beliefs

def _is_world_model(b: dict) -> bool:
    return (
        WORLD_MODEL_TAG in (b.get("tags") or "") or
        (b.get("source") or "").startswith(WORLD_MODEL_SRC_PREFIX)
    )

# ── similarity ────────────────────────────────────────────────────────────────
_STOP = {"that","this","with","from","have","been","they","what","when",
         "were","their","there","would","could","should","which","about"}

def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOP}

def _sim(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    if not wa or not wb: return 0.0
    return len(wa & wb) / max(len(wa | wb), 1)

# ── last-run guard ────────────────────────────────────────────────────────────
def _last_run_hours(conn: sqlite3.Connection) -> float:
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nightly_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                report    TEXT
            )
        """)
        row = conn.execute(
            "SELECT MAX(timestamp) FROM nightly_log"
        ).fetchone()[0]
        if row:
            return (time.time() - float(row)) / 3600
        return 9999.0
    except Exception:
        return 9999.0

# ── prompts ───────────────────────────────────────────────────────────────────
SYNTH_PROMPT = """<|system|>
You are a belief synthesis engine. Output ONLY valid JSON. No prose, no markdown.
<|user|>
These beliefs share a common theme. Synthesize them into ONE higher-order meta-belief that captures the deeper principle unifying them all.

The meta-belief must be:
- 20-60 words
- A generalization, not a summary — find the underlying principle
- A standalone complete sentence
- Not starting with "These beliefs" or "The common theme"

BELIEFS:
{beliefs}

Return ONLY a JSON object: {{"meta": "your meta-belief here"}}
<|assistant|>
{{"""

CONTRADICT_PROMPT = """<|system|>
You are a contradiction resolver. Output ONLY valid JSON. No prose, no markdown.
<|user|>
Two beliefs conflict. Determine which is more likely to be true given your reasoning.

BELIEF A: {a}
BELIEF B: {b}
{anchor_note}

Return ONLY: {{"winner": "A" or "B", "reason": "one sentence"}}
<|assistant|>
{{"""

EMERGE_PROMPT = """<|system|>
You are an insight emergence engine. Output ONLY valid JSON. No prose, no markdown.
<|user|>
These beliefs come from different domains of knowledge. Find a non-obvious emergent insight that bridges them — something that couldn't be seen from any single domain alone.

The emergent insight must be:
- 25-70 words
- Genuinely surprising — not just a summary
- A new claim, not a restatement

BELIEFS:
{beliefs}

Return ONLY: {{"insight": "your emergent insight here"}}
<|assistant|>
{{"""

# ── Phase 0: ASSESS ───────────────────────────────────────────────────────────
def phase_assess(conn: sqlite3.Connection) -> dict:
    _hdr("Phase 0/7  ·  ASSESS  —  reading system state")

    # Try homeostasis
    zone = "active"
    dominant_drive = "coherence"
    synthesis_cap  = 60
    try:
        sys.path.insert(0, str(NEX_DIR))
        from nex_homeostasis import get_homeostasis, gradient_responses
        hm   = get_homeostasis()
        snap = hm.tick(cycle=0, avg_conf=0.7, tension=0.1)
        zone           = snap["zone"]
        dominant_drive = snap["dominant_drive"]
        synthesis_cap  = gradient_responses(zone)["synthesis_cap"]
        _ok(f"Homeostasis: zone={zone}  drive={dominant_drive}  cap={synthesis_cap}")
    except Exception as e:
        _warn(f"Homeostasis unavailable ({e}) — using defaults")

    # DB stats
    tc = _text_col(conn)
    total   = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    high_c  = conn.execute(
        "SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.75"
    ).fetchone()[0]
    wm_count = 0
    try:
        wm_count = conn.execute(
            f"SELECT COUNT(*) FROM beliefs WHERE source LIKE 'world_model:%' OR tags LIKE '%world_model%'"
        ).fetchone()[0]
    except Exception:
        pass

    _info(f"Beliefs: {total} total  ·  {high_c} high-conf  ·  {wm_count} world_model")

    return {
        "zone":          zone,
        "dominant_drive": dominant_drive,
        "synthesis_cap": synthesis_cap,
        "total_beliefs": total,
        "high_conf":     high_c,
        "wm_count":      wm_count,
    }

# ── Phase 1: CLUSTER ──────────────────────────────────────────────────────────
def phase_cluster(beliefs: list[dict]) -> dict[str, list[dict]]:
    _hdr("Phase 1/7  ·  CLUSTER  —  grouping beliefs by theme")

    clusters: dict[str, list[dict]] = defaultdict(list)
    for b in beliefs:
        tags = [t.strip() for t in (b.get("tags") or "").split(",") if t.strip()]
        primary = tags[0] if tags else "general"
        clusters[primary].append(b)

    # Sub-cluster within large groups by word overlap
    final: dict[str, list[dict]] = {}
    for tag, group in clusters.items():
        if len(group) <= 30:
            final[tag] = group
            continue
        # Split into sub-clusters by similarity — greedy
        sub_id = 0
        assigned = [-1] * len(group)
        sub_centres: list[str] = []
        for i, b in enumerate(group):
            if assigned[i] >= 0:
                continue
            best_sub = -1
            best_sim = 0.4   # min sim to join existing sub-cluster
            for sc_i, centre in enumerate(sub_centres):
                s = _sim(b["content"], centre)
                if s > best_sim:
                    best_sim = s
                    best_sub = sc_i
            if best_sub == -1:
                sub_centres.append(b["content"])
                assigned[i] = sub_id
                sub_id += 1
            else:
                assigned[i] = best_sub
        for i, b in enumerate(group):
            key = f"{tag}_{assigned[i]}"
            final.setdefault(key, []).append(b)

    total_clusters = len(final)
    total_beliefs  = sum(len(v) for v in final.values())
    _ok(f"{total_clusters} clusters  ·  {total_beliefs} beliefs")
    for tag, grp in sorted(final.items(), key=lambda x: -len(x[1]))[:8]:
        wm = sum(1 for b in grp if _is_world_model(b))
        _info(f"  [{tag}]  {len(grp)} beliefs" + (f"  ({wm} world_model anchors)" if wm else ""))
    return final

# ── Phase 2: SYNTHESIZE ───────────────────────────────────────────────────────
def phase_synthesize(
    clusters: dict[str, list[dict]],
    conn: sqlite3.Connection,
    synthesis_cap: int,
    dry_run: bool,
    zone: str,
) -> int:
    _hdr("Phase 2/7  ·  SYNTHESIZE  —  meta-belief generation")

    if zone == "crisis":
        _warn("Zone=crisis — synthesis skipped")
        return 0

    # Sort clusters by size (biggest first), cap total
    sorted_clusters = sorted(clusters.items(), key=lambda x: -len(x[1]))
    max_synth = max(2, int(synthesis_cap * 0.7))
    written   = 0

    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta_beliefs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            topic        TEXT,
            meta_belief  TEXT,
            confidence   REAL,
            belief_count INTEGER,
            source       TEXT,
            created_at   TEXT
        )
    """)

    for tag, group in sorted_clusters[:max_synth]:
        if len(group) < 3:
            continue

        # Anchor world_model beliefs at top of list for synthesis context
        wm_beliefs  = [b for b in group if _is_world_model(b)]
        reg_beliefs = [b for b in group if not _is_world_model(b)]
        ordered     = wm_beliefs + reg_beliefs

        # Pick best representatives (highest conf)
        sample = sorted(ordered, key=lambda x: x["confidence"], reverse=True)[:12]
        belief_block = "\n".join(f"- {b['content']}" for b in sample)

        raw = _llm(SYNTH_PROMPT.format(beliefs=belief_block), max_tokens=200)
        if not raw:
            continue

        # Parse
        meta = ""
        try:
            to_parse = "{" + raw if not raw.strip().startswith("{") else raw
            if not to_parse.rstrip().endswith("}"): to_parse += "}"
            meta = json.loads(to_parse).get("meta", "")
        except Exception:
            m = re.search(r'"meta"\s*:\s*"([^"]{20,300})"', raw)
            if m: meta = m.group(1)

        if not meta or len(meta.split()) < 8:
            continue

        avg_conf = sum(b["confidence"] for b in sample) / len(sample)
        # Boost if anchored by world_model beliefs
        if wm_beliefs:
            avg_conf = min(0.95, avg_conf + 0.05)

        if not dry_run:
            conn.execute(
                "INSERT INTO meta_beliefs (topic, meta_belief, confidence, belief_count, source, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (tag, meta, round(avg_conf, 3), len(group),
                 f"nightly_synth:{tag}", datetime.now(timezone.utc).isoformat())
            )
        written += 1
        _info(f"  [{tag}]  {meta[:70]}…")

    if not dry_run:
        conn.commit()
    _ok(f"{written} meta-beliefs written")
    return written

# ── Phase 3: CONTRADICT ───────────────────────────────────────────────────────
def phase_contradict(
    beliefs: list[dict],
    conn: sqlite3.Connection,
    dry_run: bool,
) -> int:
    _hdr("Phase 3/7  ·  CONTRADICT  —  conflict resolution")

    # Try to use BeliefGraph for known contradictions
    known_pairs: list[tuple[dict, dict]] = []
    try:
        sys.path.insert(0, str(NEX_DIR))
        from nex_belief_graph import BeliefGraph
        bg = BeliefGraph()
        if bg._graph:
            id_to_belief = {b["id"]: b for b in beliefs}
            content_to_b = {b["content"][:80]: b for b in beliefs}
            for node_id, node in bg._graph.items():
                for contra_id in node.get("contradicts", []):
                    b_node  = bg._graph.get(contra_id)
                    if not b_node: continue
                    ba = content_to_b.get(node["content"][:80])
                    bb = content_to_b.get(b_node["content"][:80])
                    if ba and bb and (ba["id"], bb["id"]) not in [(p[0]["id"], p[1]["id"]) for p in known_pairs]:
                        known_pairs.append((ba, bb))
    except Exception as e:
        _warn(f"BeliefGraph unavailable ({e}) — detecting contradictions by pattern")

    # Fallback: simple negation heuristic on sample
    if not known_pairs:
        neg_pairs = [("always","never"), ("everything","nothing"),
                     ("all","none"), ("possible","impossible")]
        sample = beliefs[:500]
        for i, a in enumerate(sample):
            for b in sample[i+1:i+20]:
                al, bl = a["content"].lower(), b["content"].lower()
                for pos, neg in neg_pairs:
                    if (pos in al and neg in bl) or (neg in al and pos in bl):
                        known_pairs.append((a, b))
                        break
            if len(known_pairs) >= 20:
                break

    if not known_pairs:
        _ok("0 contradictions found")
        return 0

    _info(f"{len(known_pairs)} contradiction pairs detected")
    resolved = 0
    tc = _text_col(conn)

    for a, b in known_pairs[:15]:
        a_wm = _is_world_model(a)
        b_wm = _is_world_model(b)

        # world_model always wins without LLM call
        if a_wm and not b_wm:
            loser, reason = b, "world_model anchor takes precedence"
        elif b_wm and not a_wm:
            loser, reason = a, "world_model anchor takes precedence"
        else:
            anchor_note = "NOTE: Both are world_model anchors — resolve carefully." if (a_wm and b_wm) else ""
            raw = _llm(CONTRADICT_PROMPT.format(
                a=a["content"], b=b["content"], anchor_note=anchor_note
            ), max_tokens=120)
            winner_id = "A"
            try:
                to_parse = "{" + raw if not raw.strip().startswith("{") else raw
                if not to_parse.rstrip().endswith("}"): to_parse += "}"
                winner_id = json.loads(to_parse).get("winner", "A").upper()
            except Exception:
                m = re.search(r'"winner"\s*:\s*"([AB])"', raw)
                if m: winner_id = m.group(1)
            loser  = b if winner_id == "A" else a
            reason = "LLM resolution"

        # Soft decay loser — don't delete, just reduce confidence
        new_conf = max(0.30, loser["confidence"] * 0.80)
        if not dry_run:
            conn.execute(
                f"UPDATE beliefs SET confidence=? WHERE id=?",
                (round(new_conf, 3), loser["id"])
            )
        _info(f"  resolved: kept [{a['content'][:40]}…] | decayed loser ({reason})")
        resolved += 1

    if not dry_run:
        conn.commit()
    _ok(f"{resolved} contradictions resolved")
    return resolved

# ── Phase 4: COMPRESS ─────────────────────────────────────────────────────────
def phase_compress(
    beliefs: list[dict],
    conn: sqlite3.Connection,
    zone: str,
    dry_run: bool,
) -> tuple[int, int]:
    _hdr("Phase 4/7  ·  COMPRESS  —  dedup + weak belief decay")

    tc = _text_col(conn)

    # ── Dedup: find near-duplicate pairs ─────────────────────────────────────
    dropped_ids: set[int] = set()
    dedup_count = 0
    sample = [b for b in beliefs if not _is_world_model(b)][:1000]

    for i, a in enumerate(sample):
        if a["id"] in dropped_ids:
            continue
        for b in sample[i+1:i+30]:
            if b["id"] in dropped_ids or a["id"] == b["id"]:
                continue
            if _sim(a["content"], b["content"]) > 0.85:
                # Keep higher confidence
                loser = b if a["confidence"] >= b["confidence"] else a
                dropped_ids.add(loser["id"])
                dedup_count += 1

    if dropped_ids and not dry_run:
        conn.execute(
            f"DELETE FROM beliefs WHERE id IN ({','.join('?'*len(dropped_ids))})",
            list(dropped_ids)
        )

    # ── Decay: weak non-world_model beliefs ──────────────────────────────────
    # Zone modulates decay rate
    decay_rates = {"calm": 0.97, "active": 0.95, "stressed": 0.92, "crisis": 0.88}
    decay_rate  = decay_rates.get(zone, 0.95)

    # Only decay beliefs that are: low momentum + low confidence + not world_model
    decay_candidates = [
        b for b in beliefs
        if not _is_world_model(b)
        and b["id"] not in dropped_ids
        and b["confidence"] < 0.65
        and b["momentum"] < 0.35
    ]

    decayed_count = 0
    for b in decay_candidates:
        new_conf = max(0.20, b["confidence"] * decay_rate)
        if new_conf < b["confidence"] - 0.005:
            if not dry_run:
                conn.execute(
                    "UPDATE beliefs SET confidence=? WHERE id=?",
                    (round(new_conf, 3), b["id"])
                )
            decayed_count += 1

    if not dry_run:
        conn.commit()

    _ok(f"{dedup_count} duplicates removed  ·  {decayed_count} beliefs decayed  "
        f"(rate={decay_rate}  zone={zone})")
    return dedup_count, decayed_count

# ── Phase 5: GRAPH + GOALS ────────────────────────────────────────────────────
def phase_graph(beliefs: list[dict], report: dict, dry_run: bool):
    _hdr("Phase 5/7  ·  GRAPH  —  rebuild graph + update goals")

    # Rebuild belief graph
    try:
        sys.path.insert(0, str(NEX_DIR))
        from nex_belief_graph import BeliefGraph, EpisodicMemory, GoalSystem

        bg = BeliefGraph()
        bg.build(beliefs, cycle_num=0, force=True)
        stats = bg.stats()
        _ok(f"BeliefGraph: {stats['nodes']} nodes  ·  {stats['edges']} edges  "
            f"·  {stats['contradictions']} contradictions  "
            f"·  avg_attention={stats['avg_attention']}")
        report["graph_stats"] = stats

        # Update goal progress
        gs = GoalSystem()
        gs.update_progress("expand_belief_network",
                           min(1.0, report.get("total_beliefs_before", 0) / 10000))
        gs.update_progress("reduce_contradictions",
                           max(0.0, 1.0 - report.get("contradictions_resolved", 0) / max(stats.get("contradictions",1),1)))
        _ok(f"GoalSystem updated")

        # Log as episode
        em = EpisodicMemory()
        em.store(
            situation  = f"Nightly consolidation — {report.get('total_beliefs_before',0)} beliefs",
            beliefs_used = bg.top_attention(5),
            outcome    = (f"compressed={report.get('dedup_count',0)} "
                         f"decayed={report.get('decayed_count',0)} "
                         f"meta={report.get('meta_written',0)}"),
            lesson     = (f"World-model anchors: {report.get('wm_count',0)}. "
                         f"Zone was {report.get('zone','?')} — "
                         f"drive={report.get('dominant_drive','?')}"),
            score      = 0.75,
        )
        _ok("Episode logged to EpisodicMemory")

    except Exception as e:
        _warn(f"Graph/Goals integration unavailable: {e}")

# ── Phase 6: EMERGE ───────────────────────────────────────────────────────────
def phase_emerge(
    clusters: dict[str, list[dict]],
    conn: sqlite3.Connection,
    dry_run: bool,
) -> int:
    _hdr("Phase 6/7  ·  EMERGE  —  cross-domain insight")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS emergent_insights (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            insight    TEXT,
            source     TEXT,
            confidence REAL,
            created_at TEXT
        )
    """)

    # Pick top-confidence belief from each of 4-6 different clusters
    cluster_reps: list[str] = []
    cluster_tags: list[str] = []
    sorted_clusters = sorted(clusters.items(), key=lambda x: -len(x[1]))
    for tag, group in sorted_clusters:
        if len(group) < 3: continue
        top = max(group, key=lambda b: b["confidence"])
        cluster_reps.append(top["content"])
        cluster_tags.append(tag)
        if len(cluster_reps) >= 6: break

    if len(cluster_reps) < 3:
        _warn("Not enough clusters for emergence")
        return 0

    belief_block = "\n".join(
        f"[{t}] {b}" for t, b in zip(cluster_tags, cluster_reps)
    )
    raw = _llm(EMERGE_PROMPT.format(beliefs=belief_block), max_tokens=200, temperature=0.5)
    if not raw:
        return 0

    insight = ""
    try:
        to_parse = "{" + raw if not raw.strip().startswith("{") else raw
        if not to_parse.rstrip().endswith("}"): to_parse += "}"
        insight = json.loads(to_parse).get("insight", "")
    except Exception:
        m = re.search(r'"insight"\s*:\s*"([^"]{25,400})"', raw)
        if m: insight = m.group(1)

    if not insight or len(insight.split()) < 10:
        return 0

    if not dry_run:
        conn.execute(
            "INSERT INTO emergent_insights (insight, source, confidence, created_at) VALUES (?,?,?,?)",
            (insight, f"nightly:{','.join(cluster_tags[:4])}", 0.82,
             datetime.now(timezone.utc).isoformat())
        )
        conn.commit()

    _ok(f"Emergent insight: {insight[:80]}…")
    return 1

# ── Phase 7: REPORT ───────────────────────────────────────────────────────────
def phase_report(report: dict, conn: sqlite3.Connection, dry_run: bool, elapsed: float):
    _hdr("Phase 7/7  ·  REPORT")

    report["elapsed_s"]   = round(elapsed, 1)
    report["datetime"]    = datetime.now(timezone.utc).isoformat()
    report["dry_run"]     = dry_run

    # Narrative thread
    try:
        sys.path.insert(0, str(NEX_DIR))
        from nex_homeostasis import get_homeostasis
        hm = get_homeostasis()
        hm.narrative.log(
            "nightly_consolidation",
            (f"zone={report['zone']} meta={report.get('meta_written',0)} "
             f"compress={report.get('dedup_count',0)} "
             f"emerge={report.get('emerged',0)}"),
            cycle=0,
        )
    except Exception:
        pass

    if not dry_run:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nightly_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                report    TEXT
            )
        """)
        conn.execute(
            "INSERT INTO nightly_log (timestamp, report) VALUES (?,?)",
            (time.time(), json.dumps(report, default=str))
        )
        conn.commit()

    # Summary box
    dr = "  [DRY RUN — no writes]" if dry_run else ""
    lines = [
        f"NIGHTLY CONSOLIDATION{dr}",
        "",
        f"  Zone           {report['zone'].upper()}",
        f"  Beliefs before {report.get('total_beliefs_before', '?')}",
        f"  World-model    {report.get('wm_count', 0)} anchors (immune)",
        "",
        f"  Meta-beliefs   +{report.get('meta_written', 0)}",
        f"  Contradictions  {report.get('contradictions_resolved', 0)} resolved",
        f"  Compressed     -{report.get('dedup_count', 0)} dupes",
        f"  Decayed         {report.get('decayed_count', 0)} weak beliefs",
        f"  Emerged        +{report.get('emerged', 0)} cross-domain insights",
        "",
        f"  Time           {elapsed:.1f}s",
    ]
    width = max(len(l) for l in lines) + 4
    print(f"\n{C['green']}  ╔{'═'*width}╗{C['reset']}")
    for l in lines:
        print(f"{C['green']}  ║{C['reset']}  {l:<{width-2}}{C['green']}║{C['reset']}")
    print(f"{C['green']}  ╚{'═'*width}╝{C['reset']}\n")

    log_path = LOG_DIR / f"nightly_{int(time.time())}.json"
    try:
        log_path.write_text(json.dumps(report, indent=2, default=str))
        _info(f"Log → {log_path.name}")
    except Exception:
        pass

# ── MAIN ──────────────────────────────────────────────────────────────────────
def run_nightly(force: bool = False, dry_run: bool = False) -> dict:
    t0 = time.time()
    # Phase 0a — Belief quality audit (auto-quarantine hollow beliefs)
    try:
        from nex_belief_audit_daemon import run_audit as _run_audit
        _audit_result = _run_audit(dry_run=dry_run, verbose=True)
        report['audit_quarantined'] = _audit_result.get('hard_quarantined', 0) + _audit_result.get('soft_quarantined', 0)
        report['audit_boosted'] = _audit_result.get('boosted', 0)
    except Exception as _ae:
        print(f'  [audit] skipped: {_ae}')
        report['audit_quarantined'] = 0


    print(f"\n{C['purple']}  ══════════════════════════════════════════════════{C['reset']}")
    print(f"{C['purple']}  ◆  NEX NIGHTLY CONSOLIDATION{C['reset']}")
    print(f"{C['grey']}  {'DRY RUN — ' if dry_run else ''}belief-graph-level pass{C['reset']}")
    print(f"{C['purple']}  ══════════════════════════════════════════════════{C['reset']}")

    if not DB_PATH.exists():
        _err(f"nex.db not found at {DB_PATH}")
        return {"error": "no db"}

    if not _llm_reachable():
        _warn("llama-server not reachable — synthesis/emergence phases will be skipped")

    conn = _open_db()

    # Run guard
    hours_since = _last_run_hours(conn)
    if not force and hours_since < MIN_HOURS_BETWEEN_RUNS:
        _warn(f"Last run was {hours_since:.1f}h ago (min={MIN_HOURS_BETWEEN_RUNS}h). "
              f"Use --force to override.")
        conn.close()
        return {"skipped": True, "hours_since_last": round(hours_since, 1)}

    report: dict = {}

    # Phase 0
    assess      = phase_assess(conn)
    zone        = assess["zone"]
    synth_cap   = assess["synthesis_cap"]
    report.update(assess)
    report["total_beliefs_before"] = assess["total_beliefs"]

    # Load all beliefs
    beliefs = _load_beliefs(conn)

    # Phase 1
    clusters = phase_cluster(beliefs)

    # Phase 2
    meta_written = phase_synthesize(clusters, conn, synth_cap, dry_run, zone)
    report["meta_written"] = meta_written

    # Phase 3
    contradictions_resolved = phase_contradict(beliefs, conn, dry_run)
    report["contradictions_resolved"] = contradictions_resolved

    # Phase 4
    dedup_count, decayed_count = phase_compress(beliefs, conn, zone, dry_run)
    report["dedup_count"]   = dedup_count
    report["decayed_count"] = decayed_count

    # Reload beliefs for graph phase (post-compression)
    beliefs_updated = _load_beliefs(conn)

    # ── Phase 4b: ONTOLOGY — score hollow beliefs ─────────────────────────────
    ontology_scored = 0
    try:
        sys.path.insert(0, str(NEX_DIR))
        from nex_ontology import run_grounding
        result = run_grounding(n=300, dry_run=dry_run)
        ontology_scored = result.get("scored", 0)
        report["ontology_hollow"] = result.get("hollow", 0)
        report["ontology_grounded"] = result.get("grounded", 0)
        _ok(f"Ontology: {ontology_scored} scored  "
            f"·  {result.get('hollow',0)} hollow  "
            f"·  {result.get('grounded',0)} grounded")
    except Exception as e:
        _warn(f"Ontology pass unavailable: {e}")
    # ─────────────────────────────────────────────────────────────────────────

    # Phase 5
    phase_graph(beliefs_updated, report, dry_run)

    # Phase 6
    emerged = phase_emerge(clusters, conn, dry_run)
    report["emerged"] = emerged

    # Phase 7
    elapsed = time.time() - t0
    phase_report(report, conn, dry_run, elapsed)

    # Phase 7b — Wisdom distillation
    try:
        import sys as _ws
        _ws.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
        from nex_wisdom import run_wisdom_distillation
        _wn = run_wisdom_distillation(verbose=not dry_run)
        report["wisdom_new"] = _wn
    except Exception as _we:
        report["wisdom_new"] = 0
    # ── Phase 7d: AGI gap analysis ────────────────────────────────────
    try:
        import subprocess
        subprocess.run(
            ["python3", "/media/rr/NEX/nex_core/nex_agi_gap_analysis.py"],
            capture_output=True, timeout=180,
            env={**__import__("os").environ, "GROQ_API_KEY": __import__("os").environ.get("GROQ_API_KEY","")}
        )
        print("  [agi_gap] analysis complete")
    except Exception as _ag_e:
        print(f"  [agi_gap] skipped: {_ag_e}")
    # ── Phase 7c: Groq gap seeder (runs if gaps detected) ────────────
    try:
        import subprocess
        result = subprocess.run(
            ["python3", "/home/rr/Desktop/nex/nex_groq_seeder.py", "--phase", "gaps"],
            capture_output=True, timeout=120
        )
        print(f"  [groq_seeder] {result.stdout.decode()[-200:]}")
    except Exception as _gs_e:
        print(f"  [groq_seeder] skipped: {_gs_e}")
        print(f"  [wisdom] skipped: {_we}")
    conn.close()
    return report


# ── DAEMON — background thread for run.py ────────────────────────────────────
import threading as _threading

class NightlyDaemon:
    """
    Background daemon that schedules nex_nightly automatically.
    Fires when EITHER condition is met:
      - Current hour is 3am (local) and hasn't run in > 6h
      - 6h have elapsed since last run (catch-up if 3am was missed)

    Wire-in (run.py):
        from nex_nightly import NightlyDaemon as _ND
        _nightly = _ND()
        _nightly.start()
    """

    CHECK_INTERVAL_S = 3600   # check every hour
    TARGET_HOUR      = 3      # preferred run hour (3am)

    def __init__(self):
        self._thread = _threading.Thread(
            target=self._loop, daemon=True, name="nex-nightly"
        )
        self._stop = _threading.Event()

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        import time as _time
        from datetime import datetime as _dt

        # Stagger first check by 5 min so startup doesn't collide with other daemons
        _time.sleep(300)

        while not self._stop.is_set():
            try:
                now = _dt.now()
                is_target_hour = (now.hour == self.TARGET_HOUR)

                # Check hours since last run (open own connection — don't share)
                conn = _open_db()
                hours_since = _last_run_hours(conn)
                conn.close()

                should_run = (
                    (is_target_hour and hours_since >= self.CHECK_INTERVAL_S / 3600) or
                    (hours_since >= MIN_HOURS_BETWEEN_RUNS)
                )

                if should_run:
                    print(f"  [NIGHTLY] triggering — {hours_since:.1f}h since last run  "
                          f"hour={now.hour}", flush=True)
                    try:
                        run_nightly(force=True)
                    except Exception as _e:
                        print(f"  [NIGHTLY] run error: {_e}", flush=True)
                else:
                    print(f"  [NIGHTLY] idle — {hours_since:.1f}h since last run  "
                          f"next check in {self.CHECK_INTERVAL_S//60}min", flush=True)

            except Exception as _loop_err:
                print(f"  [NIGHTLY] loop error: {_loop_err}", flush=True)

            self._stop.wait(self.CHECK_INTERVAL_S)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NEX Nightly Consolidation")
    parser.add_argument("--force",   action="store_true",
                        help="Run regardless of time since last run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only — no DB writes")
    args = parser.parse_args()

    try:
        run_nightly(force=args.force, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print(f"\n  {C['grey']}Interrupted.{C['reset']}\n")
