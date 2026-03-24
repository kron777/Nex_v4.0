#!/usr/bin/env python3
"""
nex_audit_v65.py — NEX runtime correctness audit
Checks every major subsystem and reports pass/warn/fail.
Run from ~/Desktop/nex with venv active (NEX can be running).
Output: terminal + /tmp/nex_audit_v65.txt
"""
import sys, os, sqlite3, json, time, importlib, traceback
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path.home() / "Desktop/nex"))
os.chdir(str(Path.home() / "Desktop/nex"))

DB   = Path.home() / ".config/nex/nex_data/nex.db"
OUT  = Path("/tmp/nex_audit_v65.txt")
NOW  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

PASS = "✅"
WARN = "⚠️ "
FAIL = "❌"

results: list[tuple[str,str,str]] = []   # (status, section, detail)

def ok(section, detail):   results.append((PASS, section, detail))
def warn(section, detail): results.append((WARN, section, detail))
def fail(section, detail): results.append((FAIL, section, detail))

def db():
    c = sqlite3.connect(str(DB), timeout=5, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


# ══════════════════════════════════════════════════════════════════════════
print(f"\n{'═'*60}")
print(f"  NEX AUDIT  —  {NOW}")
print(f"{'═'*60}\n")


# ─────────────────────────────────────────────────────────────────────────
# 1. DATABASE INTEGRITY
# ─────────────────────────────────────────────────────────────────────────
section = "DB"
try:
    with db() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        ok(section, f"Connected — tables: {', '.join(tables)}")

        # beliefs
        belief_count = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        avg_conf     = conn.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0] or 0
        if belief_count < 100:
            warn(section, f"Belief count low: {belief_count}")
        else:
            ok(section, f"Beliefs: {belief_count}  avg_conf: {avg_conf:.4f}")

        # zero-confidence beliefs
        zero_conf = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE confidence <= 0.0").fetchone()[0]
        if zero_conf > 0:
            warn(section, f"Beliefs with conf=0: {zero_conf}")
        else:
            ok(section, "No zero-confidence beliefs")

        # duplicate topics
        dups = conn.execute("""
            SELECT topic, COUNT(*) c FROM beliefs
            GROUP BY topic HAVING c > 10
            ORDER BY c DESC LIMIT 5
        """).fetchall()
        if dups:
            warn(section, f"High-dup topics: " +
                 ", ".join(f"{r['topic']}({r['c']})" for r in dups))
        else:
            ok(section, "No excessively duplicated topics")

        # stale beliefs (not updated in 24h+)
        stale = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE last_referenced < ?",
            (time.time() - 86400,)
        ).fetchone()[0]
        pct = int(stale / max(belief_count, 1) * 100)
        if pct > 60:
            warn(section, f"Stale beliefs (>24h): {stale} ({pct}%)")
        else:
            ok(section, f"Stale beliefs (>24h): {stale} ({pct}%)")

        # reflections
        if "reflections" in tables:
            ref_count = conn.execute("SELECT COUNT(*) FROM reflections").fetchone()[0]
            ok(section, f"Reflections: {ref_count}")

        # insights
        if "insights" in tables:
            ins_count = conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
            ok(section, f"Insights: {ins_count}")

except Exception as e:
    fail(section, f"DB access failed: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 2. CORE DIRECTIVE ANCHORS
# ─────────────────────────────────────────────────────────────────────────
section = "CoreDirectives"
ANCHORS = ["truth_seeking", "contradiction_resolution", "uncertainty_honesty"]
try:
    with db() as conn:
        for anchor in ANCHORS:
            row = conn.execute(
                "SELECT confidence, reinforce_count FROM beliefs WHERE topic=?",
                (anchor,)
            ).fetchone()
            if not row:
                fail(section, f"MISSING anchor: {anchor}")
            elif row["confidence"] < 0.90:
                warn(section, f"{anchor} conf={row['confidence']:.3f} (should be ≥0.90)")
            else:
                ok(section, f"{anchor} conf={row['confidence']:.3f} rc={row['reinforce_count']}")
except Exception as e:
    fail(section, f"Anchor check failed: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 3. MODULE IMPORTS
# ─────────────────────────────────────────────────────────────────────────
section = "Imports"
MODULES = {
    "nex_upgrades.nex_v65":       "get_v65",
    "nex.belief_store":           "get_db",
    "nex.nex_directives":         "DirectiveEnforcer",
    "nex.cognition":              None,
    "nex.nex_curiosity":          None,
    "nex_curiosity_engine":       None,
    "nex_synthesis":              None,
    "nex_source_manager":         None,
    "nex_contradiction_engine":   None,
    "nex_knowledge_filter":       None,
    "nex_groq":                   None,
}
for mod, attr in MODULES.items():
    try:
        m = importlib.import_module(mod)
        if attr and not hasattr(m, attr):
            warn(section, f"{mod} — missing attr '{attr}'")
        else:
            ok(section, f"{mod} {'→ ' + attr if attr else ''}")
    except ModuleNotFoundError as e:
        fail(section, f"{mod} NOT FOUND: {e}")
    except Exception as e:
        warn(section, f"{mod} import error: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 4. V6.5 STACK HEALTH
# ─────────────────────────────────────────────────────────────────────────
section = "V6.5"
try:
    from nex_upgrades.nex_v65 import get_v65
    v65 = get_v65()
    s   = v65.get_status()

    ok(section, f"Loaded — cycle={s['cycle']}")

    hp = s["hard_pruning"]
    ok(section, f"HardPrune: {hp['belief_count']}/{hp['max']} pressure={hp['pressure']}")
    if hp["pressure"] > 0.90:
        warn(section, f"Belief pressure critical: {hp['pressure']}")

    de = s["decision_engine"]
    ok(section, f"DecisionEngine: decisions={de['decisions_made']}")

    tl = s["tension_lock"]
    ok(section, f"TensionLock: fires={tl['lock_count']}")

    dc = s["drift_correction"]
    ok(section, f"DriftCorrection: corrections={dc['corrections']}")

    cl = s["clustering"]
    if cl["cluster_count"] == 0:
        warn(section, "Clustering: 0 clusters — not yet rebuilt")
    else:
        ok(section, f"Clustering: {cl['cluster_count']} clusters")

    bm = s["belief_market"]
    ok(section, f"BeliefMarket: cycles={bm['cycles']}")

    ck = s["core_lock"]
    for anchor, conf in ck["anchors"].items():
        if conf == "MISSING":
            fail(section, f"CoreLock anchor MISSING: {anchor}")
        else:
            ok(section, f"CoreLock {anchor}: {conf}")

    ig = s["insight_gate"]
    ok(section, f"InsightGate: pass={ig['passed']} blocked={ig['blocked']} "
                f"rate={ig['pass_rate']}")
    if ig["pass_rate"] > 0.90 and (ig["passed"] + ig["blocked"]) > 20:
        warn(section, "InsightGate pass rate very high — gate may not be filtering")

    wv = s["wiki_validator"]
    ok(section, f"WikiValidator: validated={wv['validated']} "
                f"supported={wv['supported']} contradicted={wv['contradicted']}")

    fm = s["failure_memory"]
    ok(section, f"FailureMemory: total={fm['total']} "
                f"hall={fm['hallucinations']} wb={fm['wrong_beliefs']}")

    pl = s["prediction_loop"]
    ok(section, f"PredictionLoop: active={pl['active']} "
                f"resolved={pl['resolved']} acc={pl['avg_accuracy']}")

    tp = s["temporal"]
    ok(section, f"TemporalPattern: trend={tp.get('latest_trend',{}).get('direction','?')} "
                f"osc={tp['oscillations']} mean={tp['conf_mean']}")

    la = s["load_adaptive"]
    ok(section, f"LoadAdaptive: depth={la['depth']} insight={la['insight']} "
                f"reflect={la['reflect']}")
    if la["insight"] < 0.5:
        warn(section, f"InsightRate suppressed to {la['insight']} — queue pressure high")

    sb = s["sandbox"]
    ok(section, f"Sandbox: sims={sb['simulations']} committed={sb['committed']} "
                f"rejected={sb['rejected']}")

    cg = s["conf_gate"]
    ok(section, f"ConfGate: passed={cg['passed']} uncertain={cg['uncertain']} "
                f"gated={cg['gated']}")

    sc = s["scheduler"]
    ok(section, f"Scheduler: queue={sc['queue_size']} processed={sc['processed']} "
                f"dropped={sc['dropped']}")
    if sc["queue_size"] > 150:
        warn(section, f"Scheduler queue high: {sc['queue_size']}")

except Exception as e:
    fail(section, f"V6.5 health check failed: {e}\n{traceback.format_exc()[:400]}")


# ─────────────────────────────────────────────────────────────────────────
# 5. TENSION / CONTRADICTION STATE
# ─────────────────────────────────────────────────────────────────────────
section = "Tension"
try:
    with db() as conn:
        # contradiction count
        contra = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE topic LIKE '%contradiction%' "
            "OR topic LIKE '%tension%'"
        ).fetchone()[0]
        ok(section, f"Contradiction/tension beliefs: {contra}")

        # very low conf (near-death candidates)
        near_death = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE confidence < 0.10"
        ).fetchone()[0]
        if near_death > 20:
            warn(section, f"Near-death beliefs (<0.10 conf): {near_death}")
        else:
            ok(section, f"Near-death beliefs (<0.10 conf): {near_death}")

        # high-confidence belief headroom
        high_conf = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE confidence > 0.75"
        ).fetchone()[0]
        ok(section, f"High-confidence beliefs (>0.75): {high_conf}")

        # check for belief floor
        floor_breach = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE confidence <= 0.0"
        ).fetchone()[0]
        if floor_breach:
            fail(section, f"Floor breach: {floor_breach} beliefs at conf=0.0")
        else:
            ok(section, "Belief floor intact (no conf=0.0 entries)")

except Exception as e:
    fail(section, f"Tension check failed: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 6. IDENTITY HEALTH
# ─────────────────────────────────────────────────────────────────────────
section = "Identity"
try:
    identity_cfg = Path.home() / ".config/nex/identity.json"
    core_val_cfg = Path.home() / ".config/nex/core_values.json"

    if identity_cfg.exists():
        identity = json.loads(identity_cfg.read_text())
        ok(section, f"identity.json present — keys: {', '.join(list(identity.keys())[:6])}")
    else:
        fail(section, "identity.json MISSING")

    if core_val_cfg.exists():
        ok(section, "core_values.json present")
    else:
        warn(section, "core_values.json MISSING")

    with db() as conn:
        id_beliefs = conn.execute(
            "SELECT COUNT(*), AVG(confidence) FROM beliefs "
            "WHERE topic LIKE '%identity%' OR topic LIKE '%self%' OR topic LIKE '%nex%'"
        ).fetchone()
        count, avg = id_beliefs[0], id_beliefs[1] or 0
        if count < 5:
            warn(section, f"Identity beliefs low: {count}")
        else:
            ok(section, f"Identity beliefs: {count}  avg_conf: {avg:.3f}")

    session_cont = Path.home() / ".config/nex/session_continuity.json"
    if session_cont.exists():
        sc_data = json.loads(session_cont.read_text())
        ok(section, f"session_continuity.json present — keys: {list(sc_data.keys())[:4]}")
    else:
        warn(section, "session_continuity.json not found")

except Exception as e:
    fail(section, f"Identity check failed: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 7. LLM / OLLAMA ENDPOINT
# ─────────────────────────────────────────────────────────────────────────
section = "LLM"
try:
    import urllib.request, urllib.error
    req = urllib.request.Request(
        "http://localhost:11434/api/tags",
        headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.loads(r.read())
    models = [m["name"] for m in data.get("models", [])]
    if any("mistral-nex" in m for m in models):
        ok(section, f"Ollama UP — mistral-nex FOUND — models: {models[:3]}")
    else:
        warn(section, f"Ollama UP but mistral-nex not found — models: {models[:3]}")
except Exception as e:
    fail(section, f"Ollama endpoint unreachable: {e}")

# Groq fallback
try:
    from nex_groq import get_groq_client
    ok(section, "nex_groq importable — Groq fallback available")
except Exception as e:
    warn(section, f"nex_groq import failed: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 8. EMBEDDER
# ─────────────────────────────────────────────────────────────────────────
section = "Embedder"
try:
    # Check if chromadb is available (known missing from screenshots)
    import chromadb
    ok(section, "chromadb available")
except ImportError:
    warn(section, "chromadb NOT installed — embedder falling back to CPU "
                  "→ run: pip install chromadb --break-system-packages")

try:
    import sentence_transformers
    ok(section, f"sentence_transformers available v{sentence_transformers.__version__}")
except ImportError:
    warn(section, "sentence_transformers not installed")

try:
    import torch
    hip = torch.cuda.is_available()
    device = torch.cuda.get_device_name(0) if hip else "CPU"
    if hip:
        ok(section, f"PyTorch HIP available — device: {device}")
    else:
        warn(section, f"PyTorch HIP NOT available — running on CPU "
                      f"(set HSA_OVERRIDE_GFX_VERSION=10.3.0)")
except Exception as e:
    warn(section, f"PyTorch check failed: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 9. PLATFORM STATES
# ─────────────────────────────────────────────────────────────────────────
section = "Platforms"
platform_files = {
    "Discord":  Path.home() / "Desktop/nex/nex_discord.py",
    "Telegram": Path.home() / "Desktop/nex/nex_telegram.py",
    "Mastodon": Path.home() / "Desktop/nex/nex_mastodon.py",
    "YouTube":  Path.home() / "Desktop/nex/nex_youtube.py",
    "Moltbook": Path.home() / "Desktop/nex/nex/moltbook_client.py",
}
for name, path in platform_files.items():
    if path.exists():
        ok(section, f"{name} module present")
    else:
        warn(section, f"{name} module not found at {path}")

# Check for token configs
token_checks = {
    "Telegram BOT_TOKEN": ("nex_telegram", "BOT_TOKEN"),
    "Mastodon ACCESS_TOKEN": ("nex_mastodon", "ACCESS_TOKEN"),
}
for label, (mod, attr) in token_checks.items():
    try:
        m = importlib.import_module(mod)
        val = getattr(m, attr, None)
        if val and len(str(val)) > 10:
            ok(section, f"{label} present ({str(val)[:6]}…)")
        else:
            warn(section, f"{label} empty or missing")
    except Exception as e:
        warn(section, f"{label} check failed: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 10. D14 ENGAGEMENT WIRING
# ─────────────────────────────────────────────────────────────────────────
section = "D14-Engagement"
try:
    # Check if on_engagement is wired in discord/telegram handlers
    discord_src = (Path.home() / "Desktop/nex/nex_discord.py").read_text()
    tg_src      = (Path.home() / "Desktop/nex/nex_telegram.py").read_text()

    discord_wired = "on_engagement" in discord_src
    tg_wired      = "on_engagement" in tg_src

    if discord_wired:
        ok(section, "on_engagement wired in nex_discord.py")
    else:
        fail(section, "on_engagement NOT wired in nex_discord.py "
                      "→ outcome_count stays 0, D14 blind")

    if tg_wired:
        ok(section, "on_engagement wired in nex_telegram.py")
    else:
        fail(section, "on_engagement NOT wired in nex_telegram.py "
                      "→ outcome_count stays 0, D14 blind")

    # Check LearningSystem.on_engagement exists
    try:
        from nex_upgrades.nex_s7 import get_s7, NexS7
        s7 = get_s7()
        if hasattr(NexS7, "on_engagement"):
            ok(section, "S7.on_engagement() method exists")
        else:
            fail(section, "S7.on_engagement() method MISSING on s7 instance")
    except Exception as e:
        warn(section, f"S7 check failed: {e}")

except Exception as e:
    fail(section, f"D14 wiring check failed: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 11. RUN.PY PATCH VERIFICATION
# ─────────────────────────────────────────────────────────────────────────
section = "run.py"
try:
    run_src = (Path.home() / "Desktop/nex/run.py").read_text()

    checks = {
        "V2 import":    "nex_upgrades_v2",
        "S7 import":    "nex_s7",
        "V6.5 import":  "nex_v65",
        "V2 tick":      "_v2.tick(",
        "S7 tick":      "_s7.tick(",
        "V6.5 tick":    "_v65.tick(",
    }
    for label, token in checks.items():
        if token in run_src:
            ok(section, f"{label}: PRESENT")
        else:
            fail(section, f"{label}: MISSING (token: '{token}')")

    # Verify v65 tick is not inside an open try block (basic check)
    lines = run_src.splitlines()
    for i, ln in enumerate(lines):
        if "_v65.tick(" in ln:
            # Find the nearest preceding try: at same or lower indent
            tick_indent = len(ln) - len(ln.lstrip())
            for j in range(i - 1, max(0, i - 20), -1):
                prev = lines[j]
                ps   = prev.lstrip()
                pi   = len(prev) - len(ps)
                if ps.startswith("try:") and pi <= tick_indent:
                    break
                if ps.startswith("except") and pi <= tick_indent:
                    ok(section, f"v65.tick() at line {i+1} — preceding except found, indent OK")
                    break
            break

except Exception as e:
    fail(section, f"run.py audit failed: {e}")


# ─────────────────────────────────────────────────────────────────────────
# 12. LOG FRESHNESS
# ─────────────────────────────────────────────────────────────────────────
section = "Logs"
log_files = {
    "nex_brain.log":    Path("/tmp/nex_brain.log"),
    "nex_decisions":    Path("/tmp/nex_decisions.jsonl"),
    "nex_v65.log":      Path("/tmp/nex_v65.log"),
}
for label, path in log_files.items():
    if not path.exists():
        warn(section, f"{label}: NOT FOUND")
        continue
    age = time.time() - path.stat().st_mtime
    size = path.stat().st_size
    if age < 120:
        ok(section, f"{label}: FRESH ({int(age)}s ago, {size//1024}KB)")
    elif age < 600:
        warn(section, f"{label}: stale ({int(age)}s ago, {size//1024}KB)")
    else:
        warn(section, f"{label}: OLD ({int(age//60)}min ago, {size//1024}KB) — NEX running?")

# Check v65 is actually ticking (look for recent entries)
v65_log = Path("/tmp/nex_v65.log")
if v65_log.exists():
    tail = v65_log.read_text().strip().split("\n")[-5:]
    if tail and tail[0]:
        ok(section, f"v65.log tail:\n    " + "\n    ".join(tail))
    else:
        warn(section, "v65.log exists but is empty — v65 tick not firing yet?")
else:
    warn(section, "/tmp/nex_v65.log not found — v65.tick() never called or NEX not started")


# ══════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════
print()
print(f"{'═'*60}")
print(f"  AUDIT RESULTS — {NOW}")
print(f"{'═'*60}")

passes = [r for r in results if r[0] == PASS]
warns  = [r for r in results if r[0] == WARN]
fails  = [r for r in results if r[0] == FAIL]

current_section = None
for status, section, detail in results:
    if section != current_section:
        print(f"\n── {section} {'─'*(40-len(section))}")
        current_section = section
    print(f"  {status} {detail}")

print(f"\n{'═'*60}")
print(f"  {PASS} {len(passes)}  {WARN} {len(warns)}  {FAIL} {len(fails)}")

if fails:
    print(f"\n  CRITICAL:")
    for _, s, d in fails:
        print(f"    {FAIL} [{s}] {d}")
if warns:
    print(f"\n  WARNINGS:")
    for _, s, d in warns:
        print(f"    {WARN} [{s}] {d}")

print(f"{'═'*60}\n")

# Write to file
OUT.write_text("\n".join(
    f"{s} [{sec}] {det}" for s, sec, det in results
))
print(f"Full report: {OUT}")
