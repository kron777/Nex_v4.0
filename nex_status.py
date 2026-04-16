#!/usr/bin/env python3
"""
nex_status.py — Generate NEX capability status document
Reads actual state from DB, service files, running processes, and codebase.
Output: /media/rr/NEX/nex_core/NEX_STATUS.md
"""
import sqlite3, json, os, subprocess, time
from pathlib import Path

DB       = '/media/rr/NEX/nex_core/nex.db'
OUT      = Path('/media/rr/NEX/nex_core/NEX_STATUS.md')
NEX_DIR  = Path('/media/rr/NEX/nex_core')
DESK_DIR = Path.home() / 'Desktop/nex'

def sh(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
    except:
        return ""

def file_exists(path):
    return "✓" if Path(path).exists() else "✗"

def is_running(pattern):
    result = sh(f"pgrep -f '{pattern}'")
    return "● RUNNING" if result else "○ stopped"

def db_count(query):
    try:
        db = sqlite3.connect(DB, timeout=5)
        result = db.execute(query).fetchone()[0]
        db.close()
        return result
    except:
        return "?"

def db_rows(query):
    try:
        db = sqlite3.connect(DB, timeout=5)
        result = db.execute(query).fetchall()
        db.close()
        return result
    except:
        return []

# ── GATHER STATE ──────────────────────────────────────────────────────────────

model = sh("cat /etc/systemd/system/nex-llama.service | grep 'ExecStart' | grep -o '[^ ]*\\.gguf'")
model_name = Path(model).name if model else "unknown"
llm_status = is_running("llama-server")
api_status = is_running("nex_api.py")

belief_total   = db_count("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.5")
nex_core_count = db_count("SELECT COUNT(*) FROM beliefs WHERE source='nex_core'")
dhammapada     = db_count("SELECT COUNT(*) FROM beliefs WHERE source='dhammapada'")
belief_links   = db_count("SELECT COUNT(*) FROM belief_links")
tensions       = db_count("SELECT COUNT(*) FROM tensions WHERE resolved=0")
wisdom         = db_count("SELECT COUNT(*) FROM nex_wisdom")
intentions     = db_count("SELECT COUNT(*) FROM nex_intentions WHERE completed=0")
papers_db      = db_count("SELECT COUNT(*) FROM nex_papers")
paper_beliefs  = db_count("SELECT COUNT(*) FROM nex_paper_beliefs")
protocols      = db_count("SELECT COUNT(*) FROM nex_thrownet_runs WHERE source='papers'")

# Link types
link_types = db_rows("SELECT link_type, COUNT(*) FROM belief_links GROUP BY link_type ORDER BY COUNT(*) DESC")

# Active intentions
active_intentions = db_rows("SELECT statement FROM nex_intentions WHERE completed=0 LIMIT 8")

# AGI gaps
agi_gaps = []
gap_file = NEX_DIR / 'agi_gap_report.json'
if gap_file.exists():
    try:
        gap_data = json.loads(gap_file.read_text())
        agi_gaps = [g.get('requirement','') for g in gap_data.get('gaps', [])]
    except:
        pass

# Protocols proposed
proposed_protocols = []
proto_file = NEX_DIR / 'nex_protocols.json'
if proto_file.exists():
    try:
        protos = json.loads(proto_file.read_text())
        proposed_protocols = [(p.get('protocol_name','?'), p.get('one_line_summary','')) for p in protos]
    except:
        pass

# Module inventory
MODULES = {
    "nex_soul_loop.py":              "Soul loop — cognitive cycle (ABSORB/REPLY/ANSWER/POST/REFLECT/COGNITION)",
    "nex_api.py":                    "REST API — external interface (port 7823)",
    "nex_response_protocol.py":      "NRP — response generation, belief anchoring, post-filter",
    "nex_belief_reservoir_engine.py":"NBRE — belief reservoir, neuron firing, Phase 1+2",
    "nex_belief_reasoner.py":        "Belief reasoner — pre_reason, feedback loop, causal edges",
    "nex_epistemic_momentum.py":     "Epistemic momentum — activation tracking, confidence decay",
    "nex_consolidate.py":            "Consolidation — cluster/synthesise/contradict/compress",
    "nex_nightly.py":                "Nightly pipeline — consolidation + seeding + radar + gap analysis",
    "nex_interlocutor.py":           "Interlocutor graph — conversation resistance tracking",
    "nex_emergent_wants.py":         "Emergent wants — self-generated drives from tensions",
    "nex_behavioural_self_model.py": "Behavioural self-model — tracks own patterns",
    "nex_belief_engine.py":          "Belief engine — intake gating, Jaccard dedup, LLM enrichment",
    "nex_belief_forge.py":           "Belief forge — quarantine pipeline, embryo scoring",
    "nex_thrownet_refinery.py":      "Thrownet refinery — source quality pipeline",
    "nex_belief_opposer.py":         "Belief opposer — generates opposing edges",
    "nex_causal_extractor.py":       "Causal extractor — auto-generates typed causal edges",
    "nex_synthesis_engine.py":       "Synthesis engine — cross-domain belief synthesis",
    "nex_live_world.py":             "Live world — real-time world state tracking",
    "nex_user_model.py":             "User model — models interlocutor beliefs",
    "nex_metacog_gate.py":           "Metacognition gate — reflection triggering",
    "nex_improvement_gate.py":       "Improvement gate — quality threshold enforcement",
    "nex_world_model.py":            "World model — entity and predicate tracking",
    "nex_destabilization.py":        "Destabilization — controlled belief disruption",
    "nex_provenance_erosion.py":     "Provenance erosion — belief source decay",
    "nex_self_evolution.py":         "Self evolution — architecture self-modification",
}

DESK_MODULES = {
    "nex_fast_reader.py":            "Fast reader — parallel Groq book/paper ingestion",
    "nex_reading_list_feeder.py":    "Reading list feeder — queued book processing",
    "nex_groq_seeder.py":            "Groq seeder — domain belief seeding (6 phases)",
    "nex_hud_server.py":             "HUD server — web dashboard (port 7700)",
    "nex_buf_daemon.py":             "Buffer daemon — stream buffering for HUD",
}

INFRA_MODULES = {
    "nex_global_radar.py":           "Global radar — 33 research centers, ArXiv feeds",
    "nex_paper_reader.py":           "Paper reader — PDF fetch, belief extraction, scoring",
    "nex_paper_thrownet.py":         "Paper thrownet — convergences/tensions across literature",
    "nex_protocol_generator.py":     "Protocol generator — proposes buildable AGI protocols",
    "nex_agi_gap_analysis.py":       "AGI gap analysis — compares architecture vs requirements",
}

def check_module(filename, base_dir):
    path = Path(base_dir) / filename
    exists = path.exists()
    return "✓" if exists else "✗"

# ── GENERATE DOCUMENT ─────────────────────────────────────────────────────────

now = time.strftime("%Y-%m-%d %H:%M SAST")
lines = []

lines.append(f"# NEX STATUS DOCUMENT")
lines.append(f"*Generated: {now}*")
lines.append(f"*Model: {model_name}*")
lines.append("")

# ══ SYSTEM STATE ══════════════════════════════════════════════════════════════
lines.append("## SYSTEM STATE")
lines.append("")
lines.append(f"| Component | Status |")
lines.append(f"|-----------|--------|")
lines.append(f"| llama-server ({model_name}) | {llm_status} |")
lines.append(f"| NEX API (port 7823) | {api_status} |")
lines.append(f"| HUD server (port 7700) | {is_running('nex_hud_server')} |")
lines.append(f"| Buffer daemon | {is_running('nex_buf_daemon')} |")
lines.append(f"| Nightly pipeline | {file_exists(NEX_DIR/'nex_nightly.py')} wired |")
lines.append("")

# ══ BELIEF GRAPH STATE ════════════════════════════════════════════════════════
lines.append("## BELIEF GRAPH")
lines.append("")
lines.append(f"| Metric | Value |")
lines.append(f"|--------|-------|")
lines.append(f"| Total beliefs (conf≥0.5) | {belief_total:,} |")
lines.append(f"| nex_core locked beliefs | {nex_core_count} |")
lines.append(f"| Dhammapada beliefs | {dhammapada} |")
lines.append(f"| Belief graph edges | {belief_links:,} |")
lines.append(f"| Active tensions | {tensions} |")
lines.append(f"| Wisdom entries | {wisdom} |")
lines.append(f"| Active intentions | {intentions} |")
lines.append(f"| Papers in DB | {papers_db} |")
lines.append(f"| Paper beliefs extracted | {paper_beliefs} |")
lines.append("")
lines.append("**Edge types:**")
for lt, count in link_types:
    lines.append(f"- {lt}: {count:,}")
lines.append("")

# ══ WHAT NEX CAN DO ═══════════════════════════════════════════════════════════
lines.append("## CAN DO — Active Capabilities")
lines.append("")
lines.append("### Core Architecture (nex_core)")
for fname, desc in MODULES.items():
    status = check_module(fname, NEX_DIR)
    lines.append(f"- {status} **{fname}** — {desc}")

lines.append("")
lines.append("### Desktop Tools")
for fname, desc in DESK_MODULES.items():
    status = check_module(fname, DESK_DIR)
    lines.append(f"- {status} **{fname}** — {desc}")

lines.append("")
lines.append("### Research Infrastructure")
for fname, desc in INFRA_MODULES.items():
    s1 = check_module(fname, NEX_DIR)
    s2 = check_module(fname, DESK_DIR)
    status = "✓" if "✓" in [s1, s2] else "✗"
    lines.append(f"- {status} **{fname}** — {desc}")

lines.append("")
lines.append("### Knowledge Sources")
sources = db_rows("""
    SELECT source, COUNT(*) as n FROM beliefs 
    WHERE confidence >= 0.5 
    GROUP BY source ORDER BY n DESC LIMIT 20
""")
for src, count in sources:
    lines.append(f"- {src}: {count:,} beliefs")

# ══ WHAT NEX IS DOING ═════════════════════════════════════════════════════════
lines.append("")
lines.append("## IS DOING — Active Processes")
lines.append("")

procs = {
    "llama-server":         "Serving FT#12 model for inference",
    "nex_api.py":           "Handling queries via REST API",
    "nex_hud_server.py":    "Streaming HUD dashboard",
    "nex_buf_daemon.py":    "Buffering cognitive stream",
    "nex_paper_reader.py":  "Fetching and extracting AGI papers",
    "nex_soul_loop":        "Running cognitive cycle",
}
for pattern, desc in procs.items():
    status = is_running(pattern)
    lines.append(f"- {status} — {desc}")

lines.append("")
lines.append("**Nightly automation (runs ~2am):**")
lines.append("- Belief consolidation (cluster → synthesise → contradict → compress)")
lines.append("- Groq gap seeder — fills topics with <3 nex_core beliefs")
lines.append("- Global AGI radar — scans 33 research centers + ArXiv feeds")
lines.append("- AGI gap analysis — compares architecture vs research requirements")
lines.append("- Thrownet across paper beliefs")
lines.append("- Protocol generator — proposes buildable AGI protocols")

# ══ WHAT NEX WILL DO ══════════════════════════════════════════════════════════
lines.append("")
lines.append("## WILL DO — Intentions & Gaps")
lines.append("")
lines.append("### Active Intentions")
for (stmt,) in active_intentions:
    lines.append(f"- {stmt[:100]}")

lines.append("")
lines.append("### AGI Architecture Gaps")
if agi_gaps:
    for gap in agi_gaps:
        lines.append(f"- ✗ {gap}")
else:
    lines.append("- Run nex_agi_gap_analysis.py to generate")

lines.append("")
lines.append("### Proposed Protocols (from thrownet)")
if proposed_protocols:
    for name, summary in proposed_protocols:
        lines.append(f"- **{name}**: {summary[:80]}")
else:
    lines.append("- Run nex_paper_thrownet.py + nex_protocol_generator.py")

# ══ WHAT NEX NEEDS ════════════════════════════════════════════════════════════
lines.append("")
lines.append("## NEEDS — Identified Missing Capabilities")
lines.append("")
lines.append("Based on AGI gap analysis and architecture audit:")
lines.append("")

NEEDS = [
    ("FT#13 training", "FT#12 has residual contamination patterns. 500+ cleaner pairs needed."),
    ("NBRE Phase 3", "NBRE as primary voice — LLM only for edge cases. Phase 2 path fixed, Phase 3 not built."),
    ("Structural consciousness module", "No formal consciousness metric (phi/IIT). Gap identified by analysis."),
    ("Embodiment layer", "No sensorimotor grounding. Beliefs about the world but no world interaction."),
    ("Thermodynamic grounding", "No energy-based belief stability. Friston free energy not implemented."),
    ("Multi-key API rotation", "Groq rate limits hit daily. Cerebras/Samba keys available but not wired."),
    ("Paper belief population", "nex_paper_beliefs table empty — paper_reader needs successful runs."),
    ("X10 Kairos closing condition", "Thrownet X10 closing condition not wired into protocol."),
    ("Math formalisation", "NEX has math beliefs but no formal proof/derivation capability."),
    ("AGI self-directed build loop", "Gap analysis → protocol → implementation not yet fully automated."),
]

for name, desc in NEEDS:
    lines.append(f"### {name}")
    lines.append(f"{desc}")
    lines.append("")

# ══ FOOTER ════════════════════════════════════════════════════════════════════
lines.append("---")
lines.append(f"*Auto-generated by nex_status.py at {now}*")
lines.append(f"*Run `python3 /media/rr/NEX/nex_core/nex_status.py` to refresh*")

# Write
OUT.write_text('\n'.join(lines))
print(f"✓ NEX_STATUS.md written to {OUT}")
print(f"  {len(lines)} lines")

# Also write a plain text summary
summary_lines = [
    f"NEX STATUS — {now}",
    f"Model: {model_name} | Beliefs: {belief_total:,} | nex_core: {nex_core_count}",
    f"Edges: {belief_links:,} | Tensions: {tensions} | Wisdom: {wisdom}",
    f"Intentions: {intentions} active | Papers: {papers_db} in DB",
    "",
    "RUNNING:" + " | ".join(p for p,_ in procs.items() if is_running(p) == "● RUNNING"),
    "",
    "TOP GAPS:",
]
for gap in agi_gaps[:4]:
    summary_lines.append(f"  - {gap}")

Path('/media/rr/NEX/nex_core/nex_status_summary.txt').write_text('\n'.join(summary_lines))
print(f"✓ nex_status_summary.txt written")
