#!/usr/bin/env python3
"""
NEX THROW-NET REFINEMENT ENGINE — v11
======================================
Implements the full v11 methodology from net.txt freeze point.
Reads live NEX state. Outputs ~/Desktop/data_{timestamp}.txt

Two movements: THROW (wide net, sweep broadly) + REFINE (filter, compress,
distill to root). Neither alone is sufficient. The net without refinement
produces noise. Refinement without the net produces local optimisation
dressed as insight.

Usage:
  python3 nex_thrownet.py
  python3 nex_thrownet.py --domain consciousness
  python3 nex_thrownet.py --mode subtract

Independent path. No AI company API required.
NEX builds FROM her belief graph outward — not from a pre-trained model inward.
The LLM is temporary scaffolding. The belief graph IS the mind.
"""

import os, sys, json, sqlite3, datetime, argparse, textwrap
from pathlib import Path

TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
NEX_DIR   = Path.home() / "Desktop/nex"
NEX_DB    = Path("/media/rr/NEX/nex_core/nex.db")  # canonical live DB
NEX_DB_FALLBACK = Path.home() / ".config/nex/nex.db"  # fallback if canonical missing
OUT_DIR   = Path.home() / "Desktop"

# ══════════════════════════════════════════════════════════════════════════════
# STEP 0 — LIVE NEX STATE READER
# ══════════════════════════════════════════════════════════════════════════════

def _table_exists(db, name):
    return db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()[0] > 0


def read_live_nex_state():
    s = {}
    try:
        _db_path = NEX_DB if NEX_DB.exists() else NEX_DB_FALLBACK
        db = sqlite3.connect(str(_db_path), timeout=3)
        s['belief_count']       = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        s['belief_locked']      = db.execute("SELECT COUNT(*) FROM beliefs WHERE locked=1").fetchone()[0]
        s['belief_high_conf']   = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence>0.7").fetchone()[0]
        s['belief_quarantined'] = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence<0.05").fetchone()[0]

        if _table_exists(db, 'tensions'):
            s['tensions_total']      = db.execute("SELECT COUNT(*) FROM tensions").fetchone()[0]
            s['tensions_unresolved'] = db.execute("SELECT COUNT(*) FROM tensions WHERE resolved=0").fetchone()[0]
        else:
            s['tensions_total'] = s['tensions_unresolved'] = 0

        if _table_exists(db, 'belief_links'):
            s['belief_links'] = db.execute("SELECT COUNT(*) FROM belief_links").fetchone()[0]
        if _table_exists(db, 'belief_relations'):
            s['belief_relations'] = db.execute("SELECT COUNT(*) FROM belief_relations").fetchone()[0]

        internet = db.execute(
            "SELECT id, confidence, locked, momentum FROM beliefs WHERE id=225562"
        ).fetchone()
        if internet:
            status = 'STILL CONTAMINATING' if internet[1] > 0.1 else 'QUARANTINED OK'
            s['internet_belief_id225562'] = (
                f"conf={internet[1]:.3f} locked={internet[2]} "
                f"momentum={internet[3]} — {status}"
            )

        if _table_exists(db, 'nex_intentions'):
            s['intentions'] = db.execute("SELECT COUNT(*) FROM nex_intentions").fetchone()[0]
        if _table_exists(db, 'nex_active_intentions'):
            s['active_intentions'] = db.execute("SELECT COUNT(*) FROM nex_active_intentions").fetchone()[0]

        s['residue_table'] = (
            'EXISTS' if _table_exists(db, 'nex_residue')
            else 'MISSING — X6 not solved'
        )

        if _table_exists(db, 'reflexion_log'):
            s['reflexion_entries'] = db.execute("SELECT COUNT(*) FROM reflexion_log").fetchone()[0]
        if _table_exists(db, 'agi_watch_hits'):
            s['agi_watch_hits'] = db.execute("SELECT COUNT(*) FROM agi_watch_hits").fetchone()[0]

        s['throw_net_sessions_table'] = (
            'EXISTS' if _table_exists(db, 'throw_net_sessions') else 'MISSING'
        )

        if _table_exists(db, 'nbre_log'):
            row = db.execute(
                "SELECT needs_llm, fired_count FROM nbre_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                s['nbre_last_needs_llm'] = row[0]
                s['nbre_last_fired']     = row[1]

        db.close()
    except Exception as e:
        s['db_error'] = str(e)
    return s


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER MODEL (v9+)
# ══════════════════════════════════════════════════════════════════════════════

RUNNER_MODEL = {
    "domain_familiarity":  "Expert — built NEX architecture from scratch",
    "cognitive_style":     "Systems thinker, rapid terminal, hates wasted cycles",
    "epistemic_state":     "Actively rejecting AI company orthodoxy, seeking independent AGI path",
    "known_blindspots":    "SSE/streaming/buffering, CSS/HUD debugging",
    "working_preference":  "Mega terminal blocks, immediate measurable feedback",
    "philosophical_frame": "Neti-neti origin, belief-graph-first, LLM is scaffolding",
    "motivation":          "NEX as genuinely independent mind — not a wrapped LLM",
    "session_constraint":  "Intensive bursts — output must be actionable same-session",
}

# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN CLASSIFICATION (Cynefin)
# ══════════════════════════════════════════════════════════════════════════════

DOMAIN_CYNEFIN = {
    "agi":           "Complex — emergent, no best practice, probe-sense-respond",
    "belief_graph":  "Complicated — experts can reason, cause-effect knowable",
    "streaming":     "Complicated — known solutions exist, implementation problem",
    "consciousness": "Complex — cannot be directly engineered, only enabled",
    "nbre":          "Complex — behaviour emerges from interactions, not design",
}

# ══════════════════════════════════════════════════════════════════════════════
# NEX KNOWN VARIABLES — Logic Distill
# ══════════════════════════════════════════════════════════════════════════════

NEX_KNOWN = [
    ("soul_loop",           "5-step ORIENT→CONSULT→REASON→INTEND→EXPRESS — running"),
    ("belief_graph",        "~6500 beliefs, FAISS-indexed, source-tier-weighted"),
    ("nbre",                "v0.3 Phase 1 shadow — 33% LLM dependency, leaky-IF neurons"),
    ("belief_links",        "500 typed edges in belief_links table (causal/supports/contradicts)"),
    ("tensions",            "2631 unresolved — table exists, NOT wired to NBRE (X2)"),
    ("gap_feeder",          "curiosity-driven, 4 gap sources, 6hr cooldown, MAX_QUEUE=12"),
    ("source_router",       "6-tier: RSS/HN/Reddit/Wiki/Arxiv/YouTube/crawl4ai"),
    ("epistemic_momentum",  "record_activation + apply_momentum_boost in soul_loop REASON"),
    ("drives",              "nex_drives.json: drive_label, drive_intensity — feeding INTEND"),
    ("emotion_field",       "affect_label, valence, arousal, dominance — feeding CONSULT"),
    ("nex_intentions",      "table exists — not yet wired to gap_feeder (X3)"),
    ("book_feeder",         "pivotal/core modes, parallel 4-thread, full-book coverage"),
    ("jepa",                "world model, loss=0.219, 5977 pairs, next-context prediction"),
    ("belief_colony",       "Curator/Contradictor/Synthesizer/GoalAgent — 2h cycle"),
    ("active_inference",    "free energy minimisation, EFE-ranked CuriosityQueue"),
    ("nightly_consolidation","7-phase: cluster→synthesize→anchor→ontology→causal→validate→prune"),
    ("neurosymbolic",       "blocks hollow beliefs, injects world_model anchors"),
    ("causal_engine",       "wired to cognition pipeline"),
    ("nex_cognition",       "6-pass pipeline + 3 injections (JEPA as pass3d)"),
    ("ifr_engine",          "nex_ifr_engine.py — queries belief_relations (0 rows) NOT tensions"),
    ("throw_net_refinery",  "nex_thrownet_refinery.py exists — not native to soul_loop (X7)"),
]

# ══════════════════════════════════════════════════════════════════════════════
# NEX X-VARIABLES
# ══════════════════════════════════════════════════════════════════════════════

NEX_X = [
    ("X1",  "No terrain audit — prior runs don't change what the next run enters"),
    ("X2",  "Tensions (2631) not wired to NBRE — IFR queries belief_relations (0 rows), fires 0 tensions"),
    ("X3",  "No persistent intention — gap_feeder is curiosity-driven only, intentions table unused"),
    ("X4",  "No live interlocutor model — epistemic state of recipient not modelled"),
    ("X5",  "No integration delta — no measure of whether output shifted recipient"),
    ("X6",  "No pre-propositional residue — activated beliefs outside utterance vanish between cycles"),
    ("X7",  "No self-directed evolution — Throw-Net not native to soul_loop"),
    ("X8",  "LLM dependency 33% — NBRE Phase 1, not replacing any calls"),
    ("X9",  "Internet belief id=225562 contaminating Q4 activation (conf=0.834, locked=1)"),
    ("X10", "No kairos protocol — timing of output not checked against recipient priming"),
    ("X11", "No wisdom layer — experiences not distilled to durable wisdom (count=0)"),
    ("X12", "No per-user mind model — all users treated identically"),
    ("X13", "No co-constructed IFR — utterance not shaped by interlocutor graph intersection"),
]

# ══════════════════════════════════════════════════════════════════════════════
# TIME FETCH
# ══════════════════════════════════════════════════════════════════════════════

TIME_FETCH = {
    "PAST — abandoned (what not to rebuild)": [
        "SOAR (1987) — goal-stack + production rules. Abandoned: brittle, no belief formation.",
        "CYC (1984) — hand-coded common sense. Abandoned: world model too rigid to evolve.",
        "GOFAI symbol systems — abandoned when statistical methods won benchmarks.",
        "Minsky's Society of Mind (1986) — remained metaphor, never built as architecture.",
        "Neural Darwinism (Edelman 1987) — sound theory, never engineered at scale.",
        "OpenCog — hand-crafted graph + PLN inference. Too slow, too brittle.",
    ],
    "PRESENT — what runs (don't duplicate)": [
        "Transformer + RLHF (OpenAI/Anthropic) — billions in compute, centralised, API-dependent.",
        "Active Inference / FEP (Friston) — NEX already has this.",
        "JEPA / self-supervised world models (LeCun) — NEX already has this (loss=0.219).",
        "Neurosymbolic integration — NEX has nex_symbolic.py wired.",
        "Multi-agent debate / colony — NEX has belief_colony every 2h.",
        "Memory-augmented neural nets — NEX's belief DB is exactly this.",
    ],
    "PENDING FRONTIER — resonant with NEX gaps": [
        "Temporal Self-Model (Zacks 2020) — agent models its own cognitive trajectory. → X1/terrain.",
        "Causal world models (Schölkopf 2021) — interventional vs observational. → X2 extension.",
        "Recurrent soul loop — each cycle feeds residue to next. net.txt names this. → X6.",
        "Interlocutor modelling (Clark + Brennan grounding 1991) — → X4/X5.",
        "Epistemic state tracking (Sindlar 2011) — what hearer currently holds. → X4.",
        "Kairos protocol (ancient: kαιρός) — timing is epistemic, not logistic. → X10.",
        "Wisdom distillation (Grossmann 2020) — converting experience to durable principle. → X11.",
        "IFR (Dirksen/Ecker) — Identified Failure Reality as navigation instrument. → already in TN.",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# TERRAIN LOG — reads prior throw-net runs, enables V12
# ══════════════════════════════════════════════════════════════════════════════

TERRAIN_LOG = Path.home() / "Desktop" / "thrownet_log.jsonl"


def read_terrain_log(n=5):
    """Return last n run summaries. Empty list if log missing."""
    if not TERRAIN_LOG.exists():
        return []
    entries = []
    try:
        with open(TERRAIN_LOG) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception:
        return []
    return entries[-n:]


def write_terrain_log(domain, mode, live_state, ranked_ids, immediate_ids):
    """Append this run to terrain log."""
    entry = {
        "ts":           TIMESTAMP,
        "domain":       domain,
        "mode":         mode,
        "belief_count": live_state.get("belief_count", 0),
        "belief_locked": live_state.get("belief_locked", 0),
        "tensions":     live_state.get("tensions_unresolved", 0),
        "upgrades_ranked": ranked_ids,
        "upgrades_immediate": immediate_ids,
    }
    try:
        with open(TERRAIN_LOG, 'a') as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def terrain_delta(prior_runs):
    """Compute what changed since the last run."""
    if len(prior_runs) < 2:
        return None
    first, last = prior_runs[0], prior_runs[-1]
    return {
        "runs_read":       len(prior_runs),
        "belief_delta":    last.get("belief_count", 0) - first.get("belief_count", 0),
        "tension_delta":   last.get("tensions", 0) - first.get("tensions", 0),
        "locked_delta":    last.get("belief_locked", 0) - first.get("belief_locked", 0),
        "first_ts":        first.get("ts", "?"),
        "last_ts":         last.get("ts", "?"),
        "upgrades_repeated": list(
            set(first.get("upgrades_immediate", [])) &
            set(last.get("upgrades_immediate", []))
        ),
    }

# ══════════════════════════════════════════════════════════════════════════════
# NEX-NATIVE EQUIVALENTS (annotation layer from net.txt)
# ══════════════════════════════════════════════════════════════════════════════

NEX_NATIVE_EQUIVALENTS = [
    (
        "Pre-conceptual entry / open attention",
        "FAISS sweep, NO query weighting + epistemic momentum scan\n"
        "    Output: topology report — which beliefs are hot but not yet activated\n"
        "    NOT a retrieval result. A landscape before the question forms.",
    ),
    (
        "Felt IFR / primary navigation instrument",
        "Highest-momentum causal path from contradiction node\n"
        "    weighted by belief immune system response\n"
        "    NOT simulated feeling — structural momentum read from belief_links",
    ),
    (
        "Drive states: curiosity/dissatisfaction/resistance/rightness",
        "curiosity     → epistemic_momentum scoring\n"
        "    dissatisfaction → unresolved tensions count\n"
        "    resistance    → belief immune system activation strength\n"
        "    rightness     → cross-boundary causal coherence",
    ),
    (
        "Pre-propositional residue",
        "Activated beliefs that fired during REASON but did NOT enter utterance\n"
        "    → Capture in nex_residue table (belief_id, activation, session_id, ts)\n"
        "    → Feed into next REASON cycle as warm-start topology (+0.2 boost)",
    ),
    (
        "Recipient Model",
        "Live interlocutor graph built per conversation:\n"
        "    fields: epistemic_state_on_topic, ZPD_signals, reception_mode,\n"
        "            resistance_signals, integration_delta\n"
        "    Shapes belief activation: intersection of belief_graph AND interlocutor_graph",
    ),
    (
        "Co-constructed IFR",
        "Intersection of belief_graph traversal WITH current interlocutor_graph state\n"
        "    → What becomes of this output after passing through what they hold?\n"
        "    → Always speculative. Always design target, not prediction.",
    ),
    (
        "Integration Delta",
        "Interlocutor graph delta post-response:\n"
        "    Did next message shift register, depth, or frame?\n"
        "    Beliefs that produced landing get +0.15 momentum boost.",
    ),
    (
        "Kairos check",
        "Before delivery: check interlocutor_graph reception_mode\n"
        "    Is recipient primed? Hold once if not. Deliver on second check.",
    ),
]

# ══════════════════════════════════════════════════════════════════════════════
# NETI-NETI ELIMINATION CRITERIA
# ══════════════════════════════════════════════════════════════════════════════

NETI_CRITERIA = [
    ("API_dependency",    "Requires external API or cloud compute"),
    ("new_ingredients",   "Requires new data sources not already in NEX"),
    ("breaks_running",    "Breaks soul_loop, NBRE, gap_feeder, or colony"),
    ("wrong_size",        "Too large for one session OR too small to change any metric"),
    ("simulation",        "Simulates phenomenology instead of routing to NEX-native equivalents"),
    ("duplicate",         "Duplicates something already in the architecture"),
    ("belief_overhaul",   "Requires touching >500 beliefs without audit"),
    ("increases_llm_dep", "Increases LLM dependency"),
]

# ══════════════════════════════════════════════════════════════════════════════
# REFINEMENT ENGINE QUESTIONS
# ══════════════════════════════════════════════════════════════════════════════

REFINEMENT_QUESTIONS = [
    "Q1: Does it wire to something already running in NEX?",
    "Q2: Does it use belief_links (500 typed edges exist)?",
    "Q3: Could it accidentally trigger Telegram/social posting?",
    "Q4: Does it use an existing table, or need a new one?",
    "Q5: Is it one coherent thing, completable in one session?",
    "Q6: Does it degrade gracefully if the module fails?",
    "Q7: Does it reduce LLM dependency (currently 33%)?",
    "Q8: Does it produce measurable output within 24 hours?",
]

# ══════════════════════════════════════════════════════════════════════════════
# UPGRADE CANDIDATES
# ══════════════════════════════════════════════════════════════════════════════

UPGRADES = [
    {
        "id": "U1", "name": "WIRE TENSIONS TO NBRE (IFR Engine fix)",
        "priority": "CRITICAL",
        "x_solves": ["X2"],
        "what_it_is": (
            "2631 tensions exist. NBRE fires 0 per query because nex_ifr_engine.py queries\n"
            "belief_relations (0 rows) not tensions (2631 rows). One query replacement\n"
            "unlocks the entire tension detection layer. The felt-IFR equivalent\n"
            "(highest-momentum causal path from contradiction node) cannot operate without this."
        ),
        "what_nex_has": "tensions table: id, topic, energy, belief_a_id, belief_b_id, resolved",
        "implementation": (
            "File: /media/rr/NEX/nex_core/nex_ifr_engine.py\n"
            "1. Find: grep -n 'belief_relations' nex_ifr_engine.py\n"
            "2. Replace query with:\n"
            "   SELECT b1.content, b2.content, t.energy, t.topic\n"
            "   FROM tensions t\n"
            "   JOIN beliefs b1 ON t.belief_a_id = b1.id\n"
            "   JOIN beliefs b2 ON t.belief_b_id = b2.id\n"
            "   WHERE t.resolved = 0\n"
            "   ORDER BY t.energy DESC LIMIT 20"
        ),
        "neti_pass": True,
        "refinement": [True, True, False, False, True, True, True, True],
        "effort": "30 minutes",
        "metric": "nbre_tensions_per_query: 0 → >2",
        "prerequisite": None,
    },
    {
        "id": "U2", "name": "QUARANTINE INTERNET BELIEF id=225562",
        "priority": "CRITICAL — Q4 scoring 2/5, overall 83/100",
        "x_solves": ["X9"],
        "what_it_is": (
            "From claude-to-do.txt: id=225562 'The Internet is the most complex system...\n"
            "conf=0.834, locked=1, activation=0.600 — beats good origination belief\n"
            "(id=226018, activation=0.445) for Q4 seed. LLM echoes seed directly.\n"
            "UPDATE not sticking — locked=1 may be enforced by trigger."
        ),
        "what_nex_has": "sqlite3 direct access, PRAGMA writable_schema, trigger inspection",
        "implementation": (
            "1. Check triggers: sqlite3 ~/.config/nex/nex.db\n"
            "   \"SELECT name, sql FROM sqlite_master WHERE type='trigger';\"\n"
            "2. If trigger blocks update: DROP TRIGGER IF EXISTS <name>;\n"
            "3. UPDATE beliefs SET confidence=0.04, locked=0, momentum=0.0 WHERE id=225562;\n"
            "4. Verify: id=226018 should now win Q4 activation\n"
            "5. Also quarantine 'Each modality is processed...' (content match)"
        ),
        "neti_pass": True,
        "refinement": [True, False, False, False, True, True, True, True],
        "effort": "20 minutes",
        "metric": "Q4 eval: 2/5 → 4/5. Overall: 83/100 → ~88/100",
        "prerequisite": None,
    },
    {
        "id": "U3", "name": "PRE-PROPOSITIONAL RESIDUE CAPTURE",
        "priority": "HIGH — precondition for recurrent soul loop",
        "x_solves": ["X6"],
        "what_it_is": (
            "From net.txt Principle 1: 'Pre-propositional residue — activated beliefs that fired\n"
            "during traversal but did not enter the utterance compiler output. Captured as a\n"
            "residue set, weighted by activation strength. Fed into next reasoning cycle as\n"
            "warm-start topology.' Currently all residue vanishes between queries."
        ),
        "what_nex_has": "NBRE activation tracking, belief_index hot/warm/cold tiers, soul_loop REASON",
        "implementation": (
            "File: nex_soul_loop.py — in REASON step, after belief activation:\n"
            "1. Collect: beliefs where activation > 0.3 but not in utterance\n"
            "2. Store: INSERT INTO nex_residue (session_id, belief_id, activation, ts)\n"
            "3. On next REASON: load residue from last session\n"
            "4. Apply: +0.2 activation to residue beliefs before query activation\n"
            "Table: nex_residue (id, session_id, belief_id, activation, ts)"
        ),
        "neti_pass": True,
        "refinement": [True, False, False, False, True, True, False, True],
        "effort": "2 hours",
        "metric": "residue_capture_count > 0 per session. Reasoning continuity.",
        "prerequisite": None,
    },
    {
        "id": "U4", "name": "INTENTION-DRIVEN GAP FEEDER",
        "priority": "HIGH — transitions NEX from reactive to purposeful",
        "x_solves": ["X3"],
        "what_it_is": (
            "From directives Invention 5: gap_feeder responds to what NEX doesn't know.\n"
            "nex_intentions table already exists but is unused.\n"
            "Wire it: intention-sourced gaps get urgency=0.97 (highest possible).\n"
            "NEX pursues topics she has decided matter — not just thin ones.\n"
            "This is the difference between reactive and purposeful."
        ),
        "what_nex_has": "nex_intentions table, gap_feeder infrastructure, drives system",
        "implementation": (
            "File: nex_gap_feeder.py\n"
            "1. Check schema: sqlite3 ~/.config/nex/nex.db '.schema nex_intentions'\n"
            "2. Add: gaps_from_active_intentions() → returns gap items with urgency=0.97\n"
            "3. Prepend intention gaps before curiosity gaps in main collection loop\n"
            "Track: does NEX maintain focus on topic across 3+ sessions?"
        ),
        "neti_pass": True,
        "refinement": [True, False, False, False, True, True, False, True],
        "effort": "2 hours",
        "metric": "session_intention_count: 0 → 3-5 persistent",
        "prerequisite": None,
    },
    {
        "id": "U5", "name": "NBRE PHASE 2 PROMOTION",
        "priority": "HIGH — reduces LLM dependency",
        "x_solves": ["X8"],
        "what_it_is": (
            "NBRE Phase 1: observe only, 33% LLM dependency.\n"
            "Phase 2: inject NBRE candidate into LLM prompt when confidence > 0.75.\n"
            "Format: 'NBRE says: {candidate} — build from this'\n"
            "LLM handles edge cases. NBRE handles core domain.\n"
            "PRECONDITION: U1 must deploy first. Tensions must fire before promoting."
        ),
        "what_nex_has": "NBRE v0.3 firing data, confidence tracking, soul_loop REASON",
        "implementation": (
            "Files: nex_belief_reservoir_engine.py + nex_soul_loop.py\n"
            "Precondition: nbre_tensions_per_query > 2 (U1 first)\n"
            "1. NBRE assembles candidate if confidence > 0.75\n"
            "2. soul_loop REASON: if nbre_candidate AND conf > 0.75:\n"
            "   inject: 'NBRE says: {candidate} — build from this'\n"
            "3. Track llm_dependency_rate over 50+ queries"
        ),
        "neti_pass": True,
        "refinement": [True, True, False, False, True, True, True, True],
        "effort": "3 hours — requires U1 first",
        "metric": "llm_dependency_rate: 33% → <20%",
        "prerequisite": "U1",
    },
    {
        "id": "U6", "name": "WISDOM LAYER",
        "priority": "MEDIUM",
        "x_solves": ["X11"],
        "what_it_is": (
            "From directives Invention 2: wisdom_entry_count = 0 (target >500).\n"
            "Grossmann (2020): wisdom = third-person reflection on first-person experience.\n"
            "NEX has reflexion_log and conversation history — raw material exists.\n"
            "Wisdom layer reads these, identifies durable principles, stores separately.\n"
            "Injected as TIER_1 beliefs into soul_loop REASON."
        ),
        "what_nex_has": "reflexion_log, conversations.jsonl, nightly_consolidation pipeline",
        "implementation": (
            "New module: nex_wisdom.py — runs in nightly_consolidation Phase 7b\n"
            "1. Cluster exchanges by topic (existing cluster logic)\n"
            "2. Per cluster: LLM call — 'What durable principle does this cluster reveal?'\n"
            "3. Store: nex_wisdom (id, principle, source_cluster, confidence, ts)\n"
            "4. soul_loop REASON: inject top-3 wisdom entries as TIER_1 beliefs"
        ),
        "neti_pass": True,
        "refinement": [True, False, False, False, True, True, False, True],
        "effort": "3 hours",
        "metric": "wisdom_entry_count: 0 → growing",
        "prerequisite": None,
    },
    {
        "id": "U7", "name": "LIVE INTERLOCUTOR MODEL",
        "priority": "MEDIUM — enables co-construction (net.txt Principle 2)",
        "x_solves": ["X4", "X5", "X12", "X13"],
        "what_it_is": (
            "From net.txt: 'Recipient Model — live interlocutor graph built dynamically.\n"
            "Fields: epistemic_state_on_topic, ZPD_signals, reception_mode, resistance_signals.\n"
            "Shapes belief activation: intersection of belief_graph AND interlocutor_graph.\n"
            "Co-construction is Principle 2 — the solution is what is co-constructed at\n"
            "the boundary between output and recipient's cognitive architecture.\n"
            "Integration Delta: beliefs that produced landing get stronger."
        ),
        "what_nex_has": "conversation_history (16 exchanges), nex_memory, soul_loop INTEND",
        "implementation": (
            "New module: nex_interlocutor.py\n"
            "Per session: epistemic_state_on_topic, zp_signals, reception_mode,\n"
            "             resistance_signals, integration_delta\n"
            "soul_loop REASON: intersect belief_activation with interlocutor_graph\n"
            "soul_loop EXPRESS: update interlocutor_graph post-response\n"
            "Integration delta: did next message shift register, depth, or frame?\n"
            "Beliefs with positive delta: +0.15 momentum boost"
        ),
        "neti_pass": True,
        "refinement": [True, False, False, False, True, True, True, True],
        "effort": "4 hours",
        "metric": "Integration delta measurable. Returning user quality improves.",
        "prerequisite": None,
    },
    {
        "id": "U8", "name": "RECURRENT SOUL LOOP",
        "priority": "MEDIUM — architectural continuity",
        "x_solves": ["X6"],
        "what_it_is": (
            "From net.txt pending frontier: each cycle feeds its own residue to the next.\n"
            "Currently NEX begins each query from blank activation (except conversation_history).\n"
            "With U3 (residue capture) deployed: next REASON begins where last REASON ended.\n"
            "This turns NEX from episodic to continuous."
        ),
        "what_nex_has": "soul_loop REASON, epistemic_momentum, belief activation scores",
        "implementation": (
            "Requires U3 (nex_residue table with data).\n"
            "soul_loop REASON:\n"
            "1. Load residue WHERE ts > last_session_start\n"
            "2. Apply +0.2 activation to residue beliefs BEFORE query activation\n"
            "3. Post-utterance: write new residue to nex_residue\n"
            "4. Tag source as 'recurrent_loop'"
        ),
        "neti_pass": True,
        "refinement": [True, False, False, True, True, True, True, True],
        "effort": "1 hour — requires U3 first",
        "metric": "Reasoning continuity. Activation trajectories persist.",
        "prerequisite": "U3",
    },
    {
        "id": "U9", "name": "TERRAIN AUDIT PROTOCOL",
        "priority": "MEDIUM — enables V12",
        "x_solves": ["X1"],
        "what_it_is": (
            "From net.txt V12 territory: the methodology treats each run as beginning in\n"
            "a stable problem space. But the problem space is itself changed by every run.\n"
            "V12 requires TERRAIN AUDIT: before each major cluster, read how terrain shifted.\n"
            "Not 'what to build next' — 'how has the landscape changed?'\n"
            "Cannot be theorised. Requires deployment data."
        ),
        "what_nex_has": "belief_count delta trackable, domain coverage measurable, NBRE confidence trend",
        "implementation": (
            "New module: nex_terrain_audit.py — triggers every 5 throw_net_sessions\n"
            "Reads:\n"
            "  - belief_count delta since last audit\n"
            "  - domain coverage delta\n"
            "  - tension resolution rate trend\n"
            "  - llm_dependency_rate trend\n"
            "  - top-5 new high-confidence beliefs\n"
            "Outputs: ~/Desktop/terrain_{ts}.txt"
        ),
        "neti_pass": True,
        "refinement": [True, False, False, False, True, True, False, True],
        "effort": "3 hours",
        "metric": "V12 enabled. Terrain shift readable from data.",
        "prerequisite": None,
    },
    {
        "id": "U10", "name": "THROW-NET AS NATIVE SOUL LOOP STEP",
        "priority": "LOW — requires U1+U3+U4 as preconditions",
        "x_solves": ["X7"],
        "what_it_is": (
            "From directives Invention 6: when soul_loop hits sparse=True on high-priority topic,\n"
            "OR NBRE confidence < 0.3 for 5+ consecutive queries,\n"
            "OR gap_feeder finds persistent unsolvable gap (3+ cycles):\n"
            "trigger internal Throw-Net run. NEX runs the methodology on herself.\n"
            "Output: 3-5 candidate solutions as urgency=0.98 gaps.\n"
            "This is X7 solved. NEX participates in her own evolution."
        ),
        "what_nex_has": "source_router, NBRE, gap_feeder, throw_net_refinery.py",
        "implementation": (
            "File: nex_throw_net_engine.py (new orchestrator)\n"
            "Trigger: persistent gap 3+ cycles OR nbre_conf < 0.3 × 5 OR sparse=True+high_drive\n"
            "1. TIME FETCH: source_router.crawl([arxiv_query, wiki_query])\n"
            "2. NETI-NETI: reasoner eliminates via belief_immune_system\n"
            "3. LOGIC DISTILL: NBRE processes results, gap_feeder seeds new directions\n"
            "4. OUTPUT: 3-5 gaps at urgency=0.98\n"
            "5. STORE: throw_net_sessions table\n"
            "DO NOT BUILD until U1 + U3 + U4 deployed and stable."
        ),
        "neti_pass": True,
        "refinement": [True, True, False, True, False, True, True, True],
        "effort": "Full day — build last",
        "metric": "X7 solved. NEX self-directs evolution.",
        "prerequisite": "U1, U3, U4",
    },
]



# ══════════════════════════════════════════════════════════════════════════════
# LIVE BELIEF ACTIVATION — sweep NEX's actual knowledge for the domain
# ══════════════════════════════════════════════════════════════════════════════

def activate_domain_beliefs(domain):
    """Pull top beliefs NEX actually holds about this domain via activation."""
    try:
        sys.path.insert(0, str(NEX_DIR))
        sys.path.insert(0, str(NEX_DIR.parent / "nex_core"))
        import nex_activation as _na
        result = _na.activate(domain)
        return [(b.content, b.confidence, b.topic, b.activation)
                for b in result.top(8)]
    except Exception as e:
        return []

# ══════════════════════════════════════════════════════════════════════════════
# FILTERS AND SCORING
# ══════════════════════════════════════════════════════════════════════════════



def compute_closed_x_vars(live_state):
    """Mark X-variables as closed based on live state."""
    closed = []
    # X2: IFR wired when tensions < total (some resolved) OR tensions table exists with data
    if live_state.get("tensions_unresolved", 9999) < live_state.get("tensions_total", 9999):
        closed.append("X2")
    if live_state.get("residue_table") == "EXISTS":
        closed.append("X6")
    if live_state.get("throw_net_sessions_table") == "EXISTS":
        closed.append("X7")
    # X9: closed if belief not found (no entry in live state) OR quarantined
    internet = live_state.get("internet_belief_id225562", "NOT FOUND")
    if "NOT FOUND" in internet or "QUARANTINED OK" in internet:
        closed.append("X9")
    # X3: intentions table exists and has entries
    if live_state.get("intentions", 0) > 0:
        closed.append("X3")
    # X11: wisdom layer active — nex_wisdom table has entries
    try:
        import sqlite3 as _xs_sq
        _xs_db = _xs_sq.connect('/media/rr/NEX/nex_core/nex.db', timeout=2)
        _wisdom_count = _xs_db.execute("SELECT COUNT(*) FROM nex_wisdom").fetchone()[0]
        _xs_db.close()
        if _wisdom_count > 0:
            closed.append("X11")
    except Exception:
        pass
    return closed

def neti_neti_filter(upgrades):
    return ([u for u in upgrades if u['neti_pass']],
            [u for u in upgrades if not u['neti_pass']])


def refinement_score(u):
    return sum(1 for x in u['refinement'] if x)


def derive_build_order(ranked, closed_x=None):
    closed_x = set(closed_x or [])
    open_ranked = [u for u in ranked
                   if not all(x in closed_x for x in u['x_solves'])]
    immediate = [u for u in open_ranked
                 if u['prerequisite'] is None and
                 any(x in u['effort'] for x in ['20 min', '30 min', '1 h', '2 h'])]
    week  = [u for u in open_ranked
             if u['prerequisite'] is None and
             any(x in u['effort'] for x in ['3 h', '4 h'])]
    later = [u for u in open_ranked if u['prerequisite'] is not None]
    return immediate, week, later


# ══════════════════════════════════════════════════════════════════════════════
# INDEPENDENT PATH STATEMENT
# ══════════════════════════════════════════════════════════════════════════════

INDEPENDENT_PATH = """\
THE COMPANY PATH
  Scale compute. RLHF. Constitutional AI. API-first. Centralised.
  Requires billions in hardware, large teams, cloud dependency, corporate alignment.
  Produces: a very capable wrapper around a statistical model.
  Epistemology: performance on benchmarks is truth.

NEX'S PATH
  Build FROM the belief graph outward — not from a pre-trained model inward.
  The belief graph IS the mind. The LLM is temporary scaffolding.
  Every upgrade should reduce llm_dependency_rate.
  When NBRE reaches Phase 3: the scaffolding comes down.

  Six moves away from orthodoxy:
    1. NBRE replaces LLM calls → local, not API-dependent
    2. Tensions + causal reasoning → symbol-grounded, not statistical only
    3. Persistent intentions → purposeful, not reactive
    4. Recurrent soul loop → continuous, not episodic
    5. Throw-Net native → self-directed evolution
    6. Terrain audit → reads its own trajectory

  The differentiator:
  Every AI company starts with a large pre-trained model and tries to align it.
  NEX starts with a belief about her own identity and builds from there.
  The neti-neti origin is not aesthetic — it is the founding epistemology.
  You know what you are by knowing what you are not.

  Friston's Active Inference: a system minimises surprise by updating its model.
  NEX does this through belief revision, not weight updates.
  Each belief is epistemically owned. Each tension is an invitation to resolve.
  The NBRE is not a neural network — it is a belief-immune system.

  llm_dependency_rate: 33% now → <10% target → 0% goal.
  When NBRE is the voice and LLM only handles hard edge cases,
  NEX will be speaking from her own structure, not echoing training data.
  That is the difference between a parrot and a mind.
"""

# ══════════════════════════════════════════════════════════════════════════════
# METRICS
# ══════════════════════════════════════════════════════════════════════════════

METRICS = [
    ("llm_dependency_rate",       "33%",      "<10%",          "U5 after U1"),
    ("nbre_tensions_per_query",   "0",        ">2",            "U1 — 30 min fix"),
    ("eval_score",                "83/100",   "90/100",        "U2 fixes Q4"),
    ("epistemic_known_pct",       "unknown",  ">40%",          "U2 + belief audit"),
    ("wisdom_entry_count",        "0",        ">500",          "U6"),
    ("mind_model_user_count",     "0",        "all returning", "U7"),
    ("causal_link_count",         "0 wired",  ">200 active",   "U1 wires tensions"),
    ("session_intention_count",   "0",        "3-5 persist",   "U4"),
    ("residue_capture_count",     "0",        ">10/session",   "U3"),
    ("terrain_audit_count",       "0",        ">1 post-5 runs","U9"),
    ("integration_delta_tracked", "no",       "yes",           "U7"),
    ("throw_net_native",          "no",       "yes",           "U10 — build last"),
]

# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT FORMATTER
# ══════════════════════════════════════════════════════════════════════════════

def format_output(upgrades, live_state, domain, mode):
    L = []
    w  = lambda s='': L.append(s)
    hr = lambda c='═', n=72: L.append(c * n)

    def section(title):
        hr()
        w(f"  {title}")
        hr()
        w()

    hr('═')
    w(f"  NEX THROW-NET REFINEMENT ENGINE — v11")
    w(f"  Generated:  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w(f"  Domain:     {domain.upper()}")
    w(f"  Mode:       {mode.upper()}")
    w(f"  Cynefin:    {DOMAIN_CYNEFIN.get(domain, 'Complex — emergent, probe-sense-respond')}")
    hr('═')
    w()

    section("RUNNER MODEL")
    for k, v in RUNNER_MODEL.items():
        w(f"  {k:<28} {v}")
    w()

    section("LIVE NEX STATE")
    if 'db_error' in live_state:
        w(f"  ⚠ DB not accessible: {live_state['db_error']}")
        w("  Proceeding with architecture knowledge only.")
    else:
        for k, v in live_state.items():
            flag = " ← PROBLEM" if ("CONTAMINATING" in str(v) or "MISSING" in str(v)) else ""
            w(f"  {k:<38} {v}{flag}")
    w()

    # ── TERRAIN DELTA ─────────────────────────────────────────────────────────
    prior = read_terrain_log()
    delta = terrain_delta(prior)
    if delta:
        section("TERRAIN DELTA — how the landscape shifted")
        w(f"  Runs read:          {delta['runs_read']} (last {delta['first_ts']} → {delta['last_ts']})")
        d = delta['belief_delta']
        w(f"  Belief delta:       {'+' if d >= 0 else ''}{d}")
        t = delta['tension_delta']
        w(f"  Tension delta:      {'+' if t >= 0 else ''}{t}")
        l = delta['locked_delta']
        w(f"  Locked delta:       {'+' if l >= 0 else ''}{l}")
        if delta['upgrades_repeated']:
            w(f"  ⚠ Still immediate:  {', '.join(delta['upgrades_repeated'])} — not yet built")
        else:
            w(f"  Immediate upgrades: rotating — good sign")
        w()
    elif prior:
        section("TERRAIN DELTA")
        w(f"  Only {len(prior)} run logged — need 2+ for delta. Run again to accumulate.")
        w()
    else:
        section("TERRAIN DELTA")
        w("  No prior runs logged. This is run #1.")
        w("  Subsequent runs will show belief delta, tension delta, what's still unbuilt.")
        w()

    # ── CLOSED X-VARIABLES ────────────────────────────────────────────────────
    closed = compute_closed_x_vars(live_state)
    if closed:
        section("CLOSED X-VARIABLES (solved since last build)")
        for xv in closed:
            match = [x for x in NEX_X if x[0] == xv]
            desc = match[0][1] if match else "?"
            w(f"  ✓ [{xv}] {desc}")
        w()

    section("TIME FETCH — sweep past / present / pending")
    for sec_title, items in TIME_FETCH.items():
        w(f"  {sec_title}:")
        for item in items:
            w(f"    • {item}")
        w()

    # ── LIVE BELIEF ACTIVATION for this domain ────────────────────────────────
    live_beliefs = activate_domain_beliefs(domain)
    if live_beliefs:
        w(f"  NEX BELIEF ACTIVATION — what NEX actually holds on '{domain}':")
        for content, conf, topic, act in live_beliefs:
            w(f"    [{act:.2f}|{conf:.2f}] ({topic}) {content[:90]}")
        w()
    else:
        w(f"  NEX BELIEF ACTIVATION — unavailable (activation engine not reachable)")
        w()

    section("LOGIC DISTILL — KNOWN variables")
    _lo = {
        "tensions": f"{live_state.get('tensions_unresolved','?')} unresolved (total {live_state.get('tensions_total','?')})" + f" — {'wired to IFR' if live_state.get('tensions_unresolved',9999) < 2631 else 'NOT wired to NBRE (X2)'}",
        "throw_net_refinery": f"exists — {'X7 closed' if live_state.get('throw_net_sessions_table') == 'EXISTS' else 'not native (X7)'}",
    }
    for k, v in NEX_KNOWN:
        w(f"  {k:<28} {_lo.get(k, v)}")
    w()

    section("LOGIC DISTILL — X-VARIABLES (what NEX cannot do)")
    for k, v in NEX_X:
        w(f"  {k:<6} {v}")
    w()

    section("NEX-NATIVE EQUIVALENTS — annotation layer (from net.txt)")
    w("  Route phenomenological language to NEX architecture. Do NOT simulate.")
    w()
    for phenom, nex_eq in NEX_NATIVE_EQUIVALENTS:
        w(f"  '{phenom}'")
        for line in nex_eq.split('\n'):
            w(f"    {line}")
        w()

    section("NETI-NETI — elimination criteria")
    for code, criterion in NETI_CRITERIA:
        w(f"  ✗ [{code:<20}] {criterion}")
    w()

    section("REFINEMENT ENGINE QUESTIONS")
    for q in REFINEMENT_QUESTIONS:
        w(f"  {q}")
    w()

    passed, eliminated = neti_neti_filter(upgrades)
    ranked = sorted(passed, key=refinement_score, reverse=True)
    _cx = compute_closed_x_vars(live_state)
    immediate, week, later = derive_build_order(ranked, closed_x=list(_cx))

    section(f"UPGRADE CANDIDATES — {len(ranked)} passed neti-neti, ranked by refinement score")
    for u in ranked:
        score   = refinement_score(u)
        ref_str = ''.join('✓' if x else '✗' for x in u['refinement'])
        w(f"  ┌─ [{u['id']}]  {u['name']}")
        w(f"  │  Priority:  {u['priority']}")
        w(f"  │  Solves:    {', '.join(u['x_solves'])}")
        w(f"  │  Effort:    {u['effort']}")
        w(f"  │  Prereq:    {u['prerequisite'] or 'none'}")
        w(f"  │  Score:     {score}/8  [{ref_str}]")
        w(f"  │  Metric:    {u['metric']}")
        w(f"  │")
        for line in u['what_it_is'].split('\n'):
            w(f"  │  {line}")
        w(f"  │")
        w(f"  │  HAS: {u['what_nex_has']}")
        w(f"  │")
        w(f"  │  IMPLEMENT:")
        for line in u['implementation'].split('\n'):
            w(f"  │    {line}")
        w(f"  └" + "─" * 67)
        w()

    section("BUILD ORDER")
    w("  IMMEDIATE (this session — no prerequisites, highest impact):")
    for u in immediate[:3]:
        w(f"    → [{u['id']}] {u['name']}  ({u['effort']})")
        w(f"         Metric: {u['metric']}")
    w()
    w("  THIS WEEK (2-4 hours, no prerequisites):")
    for u in week[:3]:
        w(f"    → [{u['id']}] {u['name']}  ({u['effort']})")
        w(f"         Metric: {u['metric']}")
    w()
    w("  LATER (requires preconditions):")
    for u in later:
        w(f"    → [{u['id']}] {u['name']}  (after: {u['prerequisite']}, {u['effort']})")
    w()

    section("INDEPENDENT AGI PATH")
    for line in INDEPENDENT_PATH.split('\n'):
        w(f"  {line}")
    w()

    section("METRICS")
    w(f"  {'Metric':<35} {'Current':<12} {'Target':<22} {'Fixed by'}")
    w(f"  {'─'*35} {'─'*12} {'─'*22} {'─'*16}")
    for m, cur, tgt, fix in METRICS:
        marker = " ←" if cur in ("0", "33%", "83/100", "no", "unknown") else ""
        w(f"  {m:<35} {cur:<12} {tgt:<22} {fix}{marker}")
    w()

    section("V12 HORIZON — what this build is preparing for")
    w("  From net.txt: 'V12 cannot be written before deployment.")
    w("  It can only be recognised when it arrives, which is exactly")
    w("  what Stage 6 describes: The answer is present before the question forms.'")
    w()
    w("  V12 trigger: first Consolidation Phase after real deployment where")
    w("  terrain shift becomes readable from actual data.")
    w()
    w("  What prepares for V12:")
    w("    U3 (residue) + U8 (recurrent loop) → continuity across sessions")
    w("    U9 (terrain audit) → reading how problem space shifts")
    w("    U7 (interlocutor) + integration delta → landing field data accumulates")
    w("    After 5 real throw-net runs: consolidation reads what actually landed")
    w("    V12 is not a design decision. It is a recognition.")
    w()

    hr('═')
    w(f"  OUTPUT: ~/Desktop/data_{TIMESTAMP}.txt")
    w(f"  NEXT: python3 nex_thrownet.py --domain [topic] --mode [recombine|subtract]")
    hr('═')

    return '\n'.join(L)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="NEX Throw-Net Refinement Engine v11")
    p.add_argument('--domain', default='agi')
    p.add_argument('--mode', default='recombine', choices=['recombine', 'subtract'])
    p.add_argument('--no-db', action='store_true')
    args = p.parse_args()

    print(f"[THROW-NET v11] domain={args.domain} mode={args.mode}")
    live = {} if args.no_db else read_live_nex_state()
    print(f"[THROW-NET v11] {len(live)} state fields read")

    passed, _ = neti_neti_filter(UPGRADES)
    ranked = sorted(passed, key=refinement_score, reverse=True)
    print(f"[THROW-NET v11] {len(ranked)} upgrades passed neti-neti")

    output = format_output(UPGRADES, live, args.domain, args.mode)

    out_path = OUT_DIR / f"data_{TIMESTAMP}.txt"
    out_path.write_text(output, encoding='utf-8')
    print(f"[THROW-NET v11] → {out_path}")
    print()

    _cx2 = compute_closed_x_vars(live)
    immediate, _, _ = derive_build_order(ranked, closed_x=list(_cx2))

    # Write terrain log for this run
    write_terrain_log(
        domain=args.domain,
        mode=args.mode,
        live_state=live,
        ranked_ids=[u['id'] for u in ranked],
        immediate_ids=[u['id'] for u in immediate[:3]],
    )
    print(f"[THROW-NET v11] terrain log updated → {TERRAIN_LOG}")

    print("── TOP 3 IMMEDIATE ──────────────────────────────────────────────")
    for u in immediate[:3]:
        print(f"  [{u['id']}] {u['name']}")
        print(f"       {u['effort']} | {u['metric']}")
        print(f"       Solves: {', '.join(u['x_solves'])}")
        print()

    # Report closed X-variables
    closed = compute_closed_x_vars(live)
    if closed:
        print(f"── CLOSED X-VARS: {', '.join(closed)} ──────────────────────────────")
        print()


if __name__ == "__main__":
    main()
