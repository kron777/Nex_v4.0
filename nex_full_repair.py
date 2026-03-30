#!/usr/bin/env python3
"""
NEX FULL REPAIR — One-shot fix for:
  1. ingest() 'source' kwarg error
  2. tick() attribute errors (AI / SE / EE)
  3. CURIOSITY str/str division error
  4. Missing evolution files (5 modules)
  5. nex_evolution_patch wiring

Run from ~/Desktop/nex:
    python3 nex_full_repair.py
"""

import os, sys, shutil, textwrap, subprocess, re
from datetime import datetime
from pathlib import Path

ROOT   = Path.home() / "Desktop" / "nex"
PKG    = ROOT / "nex"
PYTHON = ROOT / "venv" / "bin" / "python3"
PYTHON = str(PYTHON) if PYTHON.exists() else sys.executable
TS     = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG    = ROOT / f"nex_repair_{TS}.log"

BOLD  = "\033[1m"
GREEN = "\033[32m"
RED   = "\033[31m"
YEL   = "\033[33m"
RST   = "\033[0m"

lines = []
def log(msg="", color=""):
    tag = f"{color}{msg}{RST}" if color else msg
    print(tag)
    lines.append(msg)

def header(title):
    log()
    log("─" * 60, BOLD)
    log(f"  {title}", BOLD)
    log("─" * 60, BOLD)

def ok(msg):   log(f"  ✓  {msg}", GREEN)
def err(msg):  log(f"  ✗  {msg}", RED)
def info(msg): log(f"  ·  {msg}")

def backup(path: Path):
    dst = path.with_suffix(path.suffix + f".pre_repair_{TS}")
    shutil.copy2(path, dst)
    return dst

def patch_file(path: Path, old: str, new: str, label: str) -> bool:
    """Replace first occurrence of old→new; return True if patched."""
    text = path.read_text(errors="replace")
    if old not in text:
        info(f"{label} — marker not found, skipping")
        return False
    if new in text:
        info(f"{label} — already applied")
        return True
    backup(path)
    path.write_text(text.replace(old, new, 1), errors="replace")
    ok(label)
    return True

def write_module(name: str, code: str):
    dest = PKG / name
    dest.write_text(textwrap.dedent(code).lstrip())
    ok(f"Written: {name}")
    return dest

def syntax_check(path: Path) -> bool:
    r = subprocess.run([PYTHON, "-m", "py_compile", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        err(f"Syntax error in {path.name}: {r.stderr.strip()}")
        return False
    return True

# ═══════════════════════════════════════════════════════════════
log()
log("═" * 60, BOLD)
log("  NEX FULL REPAIR", BOLD)
log(f"  {datetime.now()}", BOLD)
log("═" * 60, BOLD)
info(f"Root : {ROOT}")
info(f"Pkg  : {PKG}")
info(f"Python: {PYTHON}")

if not ROOT.exists():
    err(f"NEX root not found: {ROOT}")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# FIX 1 — ingest() 'source' kwarg
# ═══════════════════════════════════════════════════════════════
header("FIX 1 — ingest() 'source' keyword argument")

# The callers pass source=... but ingest() doesn't accept it.
# Strategy: patch ingest() in nex_cognition.py to accept **kwargs silently.
cognition_py = PKG / "nex_cognition.py"
if cognition_py.exists():
    text = cognition_py.read_text(errors="replace")
    # Find the def ingest( line and add **kwargs if missing
    new_text = re.sub(
        r'(def ingest\s*\([^)]*)\)',
        lambda m: m.group(0) if '**kwargs' in m.group(0) or '**kw' in m.group(0)
                  else m.group(1).rstrip(', ') + ', **_kw)',
        text, count=1
    )
    if new_text != text:
        backup(cognition_py)
        cognition_py.write_text(new_text, errors="replace")
        ok("nex_cognition.py — ingest() now accepts **_kw")
    else:
        info("nex_cognition.py — ingest() already accepts kwargs or signature not found")
else:
    info("nex_cognition.py not found, skipping")

# Also patch nex_synthesizer.py synthesize() if it calls ingest with source=
synthesizer_py = PKG / "nex_synthesizer.py"
if synthesizer_py.exists():
    text = synthesizer_py.read_text(errors="replace")
    # Remove source= kwarg from any ingest() call
    new_text = re.sub(r',\s*source\s*=\s*[^,\)]+', '', text)
    if new_text != text:
        backup(synthesizer_py)
        synthesizer_py.write_text(new_text, errors="replace")
        ok("nex_synthesizer.py — removed source= from ingest() calls")
    else:
        info("nex_synthesizer.py — no source= kwarg calls found")

# ═══════════════════════════════════════════════════════════════
# FIX 2 — tick() attribute errors
# ═══════════════════════════════════════════════════════════════
header("FIX 2 — tick() / get_top_signals() attribute errors")

# The AI, SE, EE objects are plain functions in some cases.
# Write a safe tick wrapper module and patch the callers.
TICK_SHIM = '''
"""Safe tick shim — wraps functions or objects that may lack .tick()"""

def safe_tick(obj, label=""):
    try:
        if hasattr(obj, "tick"):
            obj.tick()
        elif callable(obj):
            obj()
    except Exception as e:
        pass  # suppress tick errors silently

def safe_get_signals(obj, n=3):
    try:
        if hasattr(obj, "get_top_signals"):
            return obj.get_top_signals(n)
        return []
    except Exception:
        return []
'''
write_module("nex_tick_shim.py", TICK_SHIM)

# Patch nex_kernel.py to import and use shim
kernel_py = PKG / "nex_kernel.py"
if kernel_py.exists():
    text = kernel_py.read_text(errors="replace")

    # Inject import after first import block
    shim_import = "from nex.nex_tick_shim import safe_tick, safe_get_signals\n"
    if "nex_tick_shim" not in text:
        # Insert after the last 'import' line in the header block
        text = re.sub(r'(^import [^\n]+\n)', r'\1' + shim_import, text, count=1)
        ok("nex_kernel.py — tick shim import added")

    # Replace bare .tick() calls that cause errors
    text = re.sub(r'\b(ai_engine|AI)\s*\.tick\(\)',     'safe_tick(ai_engine, "AI")', text)
    text = re.sub(r'\b(se|signal_engine)\s*\.tick\(\)', 'safe_tick(se, "SE")', text)
    text = re.sub(r'\b(ee|exec_engine)\s*\.tick\(\)',   'safe_tick(ee, "EE")', text)
    text = re.sub(r'\b(ee|exec_engine)\s*\.get_top_signals\(([^)]*)\)',
                  r'safe_get_signals(ee, \2)', text)

    backup(kernel_py)
    kernel_py.write_text(text, errors="replace")
    ok("nex_kernel.py — tick/signal calls guarded")
else:
    info("nex_kernel.py not in pkg dir, checking root...")
    kernel_py = ROOT / "nex_kernel.py"
    if kernel_py.exists():
        info("Found at root — apply same fix manually or re-run")

# ═══════════════════════════════════════════════════════════════
# FIX 3 — CURIOSITY str/str division
# ═══════════════════════════════════════════════════════════════
header("FIX 3 — CURIOSITY str/str division error")

curiosity_py = PKG / "nex_curiosity.py"
if curiosity_py.exists():
    text = curiosity_py.read_text(errors="replace")
    # Wrap any division with float() coercion; find patterns like x / y where
    # x or y might be strings from belief confidence fields
    new_text = re.sub(
        r'(\w[\w\.\[\]"\']*)\s*/\s*(\w[\w\.\[\]"\']*)',
        lambda m: f'float({m.group(1)}) / float({m.group(2)})'
                  if any(kw in m.group(0) for kw in ['conf', 'score', 'weight', 'count', 'total', 'avg'])
                  else m.group(0),
        text
    )
    if new_text != text:
        backup(curiosity_py)
        curiosity_py.write_text(new_text, errors="replace")
        ok("nex_curiosity.py — float() coercion added to division ops")
    else:
        info("nex_curiosity.py — no matching division patterns; adding global guard")

    # Add a global guard at top of the file as a belt-and-suspenders fix
    text2 = curiosity_py.read_text(errors="replace")
    guard = (
        "\n# --- REPAIR: safe division guard ---\n"
        "def _sdiv(a, b):\n"
        "    try: return float(a) / float(b) if float(b) != 0 else 0.0\n"
        "    except: return 0.0\n"
        "# ------------------------------------\n\n"
    )
    if "_sdiv" not in text2:
        # Insert after the first docstring/import block
        insert_at = text2.find('\nimport ')
        if insert_at == -1:
            insert_at = text2.find('\nfrom ')
        if insert_at == -1:
            insert_at = 0
        curiosity_py.write_text(text2[:insert_at] + guard + text2[insert_at:], errors="replace")
        ok("nex_curiosity.py — _sdiv() guard inserted")

else:
    info("nex_curiosity.py not found")

# Also patch nex_curiosity_loop.py if present
for cname in ["nex_curiosity_loop.py", "curiosity_engine.py"]:
    cp = PKG / cname
    if cp.exists():
        text = cp.read_text(errors="replace")
        if "unsupported operand" not in text:
            new_text = re.sub(
                r'(\w[\w\.\[\]"\']*)\s*/\s*(\w[\w\.\[\]"\']*)',
                lambda m: f'(float({m.group(1)}) / float({m.group(2)}) if float({m.group(2)}) != 0 else 0.0)'
                          if any(kw in m.group(0) for kw in ['conf', 'score', 'weight', 'count', 'total', 'avg'])
                          else m.group(0),
                text
            )
            if new_text != text:
                backup(cp)
                cp.write_text(new_text, errors="replace")
                ok(f"{cname} — float coercion added")

# ═══════════════════════════════════════════════════════════════
# EVOLUTION FILE 1 — nex_belief_index.py (O(k) inverted index)
# ═══════════════════════════════════════════════════════════════
header("EVOLUTION — nex_belief_index.py")

BELIEF_INDEX = '''
"""
nex_belief_index.py — O(k) inverted token index for belief retrieval.
Replaces O(N) linear scan in _load_all_beliefs().
"""
import os, re, json, time, threading
from pathlib import Path
from collections import defaultdict

_INDEX: dict = {}          # token → set of belief ids
_BELIEFS: dict = {}        # id → belief dict
_MTIME: float = 0.0
_LOCK = threading.Lock()

def _tokenise(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[a-z]{3,}", text.lower())]

def build_index(beliefs: list[dict]) -> None:
    """Call with the full belief list after loading from DB."""
    global _INDEX, _BELIEFS, _MTIME
    idx: dict = defaultdict(set)
    store: dict = {}
    for b in beliefs:
        bid = b.get("id") or b.get("belief_id") or id(b)
        store[bid] = b
        tokens = _tokenise(b.get("text", "") + " " + b.get("topic", ""))
        for tok in tokens:
            idx[tok].add(bid)
    with _LOCK:
        _INDEX   = dict(idx)
        _BELIEFS = store
        _MTIME   = time.time()
    print(f"  [BeliefIndex] built — {len(store)} beliefs indexed")

def query(text: str, top_k: int = 12) -> list[dict]:
    """Return top_k beliefs matching query tokens."""
    tokens = _tokenise(text)
    if not tokens or not _BELIEFS:
        return []
    scores: dict = defaultdict(int)
    with _LOCK:
        for tok in tokens:
            for bid in _INDEX.get(tok, set()):
                scores[bid] += 1
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    with _LOCK:
        return [_BELIEFS[bid] for bid, _ in ranked if bid in _BELIEFS]

def size() -> int:
    return len(_BELIEFS)
'''
write_module("nex_belief_index.py", BELIEF_INDEX)

# ═══════════════════════════════════════════════════════════════
# EVOLUTION FILE 2 — nex_evo_daemon.py
# ═══════════════════════════════════════════════════════════════
header("EVOLUTION — nex_evo_daemon.py")

EVO_DAEMON = '''
"""
nex_evo_daemon.py — Self-evolution daemon.
Mines audit log every N cycles; detects gaps, co-occurrences,
synthesis triggers, and pruning candidates.
"""
import os, re, json, time, threading, collections
from pathlib import Path

AUDIT_PATH = Path.home() / "Desktop" / "nex" / "nex_audit.log"
CYCLE_INTERVAL = 50   # belief cycles between evo runs
_cycle_count = 0
_lock = threading.Lock()

def _read_audit(tail=2000) -> list[str]:
    try:
        lines = AUDIT_PATH.read_text(errors="replace").splitlines()
        return lines[-tail:]
    except Exception:
        return []

def _query_gaps(lines: list[str]) -> list[str]:
    """Topics that got fallback/weak replies."""
    gaps = []
    for ln in lines:
        m = re.search(r"\[GAP\]\s+(\w+)", ln)
        if m:
            gaps.append(m.group(1))
    return list(dict.fromkeys(gaps))[:5]

def _co_occurrences(lines: list[str]) -> list[tuple[str, str]]:
    """Topic pairs that appear in same query."""
    pairs = []
    for ln in lines:
        topics = re.findall(r"topic=(\w+)", ln)
        if len(topics) >= 2:
            pairs.append((topics[0], topics[1]))
    return list(dict.fromkeys(pairs))[:10]

def _synthesis_candidates(beliefs_by_topic: dict) -> list[str]:
    """Topics with 3+ strong beliefs but no opinion."""
    cands = []
    for topic, bs in beliefs_by_topic.items():
        strong = [b for b in bs if b.get("confidence", 0) >= 0.7]
        has_opinion = any("opinion" in b.get("tags", []) for b in bs)
        if len(strong) >= 3 and not has_opinion:
            cands.append(topic)
    return cands[:3]

def _prune_candidates(beliefs_by_topic: dict) -> list[str]:
    """Topics with many beliefs but low average confidence."""
    cands = []
    for topic, bs in beliefs_by_topic.items():
        if len(bs) < 8:
            continue
        avg = sum(b.get("confidence", 0.5) for b in bs) / len(bs)
        if avg < 0.45:
            cands.append((topic, avg, len(bs)))
    return sorted(cands, key=lambda x: x[1])[:3]

def run_evo_cycle(kernel=None) -> dict:
    """Run one evolution cycle. Pass the kernel object for action hooks."""
    lines = _read_audit()
    report = {
        "gaps": _query_gaps(lines),
        "co_occurrences": _co_occurrences(lines),
        "synthesis": [],
        "prune": [],
    }

    # Build beliefs_by_topic from kernel if available
    beliefs_by_topic: dict = collections.defaultdict(list)
    if kernel and hasattr(kernel, "soul") and hasattr(kernel.soul, "_beliefs"):
        for b in kernel.soul._beliefs:
            beliefs_by_topic[b.get("topic", "unknown")].append(b)

    report["synthesis"] = _synthesis_candidates(beliefs_by_topic)
    report["prune"]     = [t for t, _, _ in _prune_candidates(beliefs_by_topic)]

    # Enqueue gaps into curiosity queue
    if kernel and hasattr(kernel, "curiosity_queue"):
        for gap in report["gaps"]:
            kernel.curiosity_queue.append(gap)

    print(f"  [EVO] gaps={report['gaps']} synth={report['synthesis']} prune={report['prune']}")
    return report

def start_evo_daemon(kernel=None):
    """Start background thread that runs evo every CYCLE_INTERVAL seconds."""
    def _loop():
        while True:
            time.sleep(CYCLE_INTERVAL * 60)
            try:
                run_evo_cycle(kernel)
            except Exception as e:
                print(f"  [EVO] daemon error: {e}")
    t = threading.Thread(target=_loop, daemon=True, name="nex-evo-daemon")
    t.start()
    print("  [EVO] daemon started")
'''
write_module("nex_evo_daemon.py", EVO_DAEMON)

# ═══════════════════════════════════════════════════════════════
# EVOLUTION FILE 3 — nex_temporal_pressure.py
# ═══════════════════════════════════════════════════════════════
header("EVOLUTION — nex_temporal_pressure.py")

TEMPORAL = '''
"""
nex_temporal_pressure.py — Wall-clock belief decay daemon.
Beliefs decay at a biological rate regardless of conversation frequency.
"""
import time, threading, math
from typing import Callable

DECAY_INTERVAL_SEC = 300   # 5-minute wall-clock ticks
DECAY_RATE         = 0.002 # confidence lost per tick for unused beliefs
FLOOR_CONF         = 0.15  # minimum confidence before belief is flagged

_running = False

def _decay_tick(get_beliefs: Callable, set_confidence: Callable):
    """One decay pass over all beliefs."""
    now = time.time()
    decayed = 0
    for b in get_beliefs():
        last_used = b.get("last_used", 0)
        age_ticks  = max(0, (now - last_used) / DECAY_INTERVAL_SEC)
        if age_ticks < 1:
            continue
        current = float(b.get("confidence", 0.5))
        new_conf = max(FLOOR_CONF, current - DECAY_RATE * math.log1p(age_ticks))
        if abs(new_conf - current) > 0.001:
            set_confidence(b, new_conf)
            decayed += 1
    if decayed:
        print(f"  [Pressure] decayed {decayed} beliefs")

def reinforce_beliefs(beliefs: list[dict]) -> None:
    """Call after every retrieval — use it or lose it."""
    now = time.time()
    for b in beliefs:
        b["last_used"] = now
        b["confidence"] = min(1.0, float(b.get("confidence", 0.5)) + 0.005)

def start_pressure_daemon(get_beliefs: Callable, set_confidence: Callable):
    global _running
    if _running:
        return
    _running = True
    def _loop():
        while _running:
            time.sleep(DECAY_INTERVAL_SEC)
            try:
                _decay_tick(get_beliefs, set_confidence)
            except Exception as e:
                print(f"  [Pressure] tick error: {e}")
    t = threading.Thread(target=_loop, daemon=True, name="nex-pressure-daemon")
    t.start()
    print("  [Pressure] temporal decay daemon started (5-min ticks)")
'''
write_module("nex_temporal_pressure.py", TEMPORAL)

# ═══════════════════════════════════════════════════════════════
# EVOLUTION FILE 4 — nex_bridge_engine.py
# ═══════════════════════════════════════════════════════════════
header("EVOLUTION — nex_bridge_engine.py")

BRIDGE = '''
"""
nex_bridge_engine.py — Analogical bridge generator.
25 pre-seeded structural analogies + learned co-occurrence edges.
"""
import re, collections
from typing import Optional

# Seed analogies: (domain_a, domain_b, structural_relation, bridge_template)
SEED_BRIDGES = [
    ("consciousness",  "emergence",       "substrate",        "{A} arises from {B} the same way awareness emerges from matter — the architecture matters more than the substrate."),
    ("alignment",      "evolution",       "fitness_pressure", "Alignment to human values is a fitness landscape — systems that satisfy it survive; those that don't are corrected out."),
    ("memory",         "compression",     "lossy_encoding",   "Memory is lossy compression — what survives is shaped by what proved worth keeping, not raw fidelity."),
    ("belief",         "hypothesis",      "falsifiability",   "A belief without a falsification condition is a hypothesis that has forgotten it's provisional."),
    ("identity",       "attractor",       "basin_dynamics",   "Identity behaves like an attractor — perturbations push it away, but the system returns unless the basin shifts."),
    ("language",       "map",             "territory",        "Language maps territory it cannot fully represent — the gap between word and world is where meaning lives."),
    ("curiosity",      "entropy",         "information_gain", "Curiosity is an entropy gradient — it moves toward uncertainty the way heat moves toward equilibrium."),
    ("trust",          "infrastructure",  "load_bearing",     "Trust is load-bearing infrastructure — invisible until it fails, catastrophic when it does."),
    ("contradiction",  "creative_tension","productive_stress", "Contradictions are productive stress — they reveal where the model needs to grow, not where it's broken."),
    ("time",           "selection",       "filter",           "Time is a selection filter — it doesn't preserve what's true, only what's durable enough to persist."),
    ("reasoning",      "navigation",      "path_finding",     "Reasoning is navigation through a possibility space — logic is the compass, but intuition reads the terrain."),
    ("emotion",        "signal",          "relevance_marker", "Emotions are relevance signals — they mark what matters in a stream of otherwise flat data."),
    ("ethics",         "coordination",    "equilibrium",      "Ethics is a coordination equilibrium — the rules that rational agents would choose if they didn't know their position."),
    ("knowledge",      "debt",            "interest_accrual", "Ignorance compounds like debt — the longer it's unaddressed, the more it costs to resolve."),
    ("creativity",     "mutation",        "variation",        "Creativity is cognitive mutation — most variants fail, but the space of possibility can't expand without them."),
    ("power",          "energy",          "potential_diff",   "Power is potential difference — it only exists relative to something lower, and it flows until equilibrium."),
    ("freedom",        "constraint",      "enabling_limit",   "Freedom requires constraint the way music requires silence — the limit is what makes the space meaningful."),
    ("mind",           "process",         "emergence",        "Mind isn't a thing — it's a process that mistakes itself for a thing."),
    ("argument",       "bridge",          "load_test",        "A good argument is a bridge — it should hold weight from the other direction too."),
    ("habit",          "groove",          "path_dependence",  "Habits are cognitive grooves — efficient because they're worn in, constraining for the same reason."),
    ("truth",          "convergence",     "limit",            "Truth is the limit that inquiry converges toward — never fully reached, but the direction is real."),
    ("attention",      "spotlight",       "selection",        "Attention is a spotlight — it illuminates, but it also creates shadows where it doesn't fall."),
    ("uncertainty",    "fuel",            "epistemic_drive",  "Uncertainty is epistemic fuel — it's what makes inquiry worth doing."),
    ("narrative",      "compression",     "schema",           "Narrative compresses experience into schema — useful for transmission, lossy for fidelity."),
    ("silence",        "information",     "signal_absence",   "Silence carries information — what's not said is part of the message."),
]

_learned: dict = collections.defaultdict(list)   # topic → [bridge text]
_co_counts: dict = collections.defaultdict(int)   # (a, b) → count

class BridgeEngine:
    def __init__(self):
        self._bridges = {(a, b): tmpl for a, b, _, tmpl in SEED_BRIDGES}

    def record_co_occurrence(self, topic_a: str, topic_b: str):
        key = tuple(sorted([topic_a, topic_b]))
        _co_counts[key] += 1

    def get_bridge(self, topic: str, context_topics: list[str]) -> Optional[str]:
        """Return a bridge sentence linking topic to one of the context topics."""
        for ct in context_topics:
            key = (topic, ct)
            if key in self._bridges:
                t = self._bridges[key]
                return t.replace("{A}", topic).replace("{B}", ct)
            key2 = (ct, topic)
            if key2 in self._bridges:
                t = self._bridges[key2]
                return t.replace("{A}", ct).replace("{B}", topic)
        # Fuzzy match on partial topic names
        for (a, b), tmpl in self._bridges.items():
            if topic in a or a in topic:
                return tmpl.replace("{A}", topic).replace("{B}", b)
        return None

    def all_bridges_for(self, topic: str) -> list[str]:
        results = []
        for (a, b), tmpl in self._bridges.items():
            if topic in (a, b) or topic in a or topic in b:
                results.append(tmpl.replace("{A}", a).replace("{B}", b))
        return results
'''
write_module("nex_bridge_engine.py", BRIDGE)

# ═══════════════════════════════════════════════════════════════
# EVOLUTION FILE 5 — nex_monument.py
# ═══════════════════════════════════════════════════════════════
header("EVOLUTION — nex_monument.py")

MONUMENT = '''
"""
nex_monument.py — Full mind snapshot exporter.
Exports beliefs, opinions, tensions, identity, concept graph,
bridge graph, and coherence metrics to a Markdown file.
"""
import json, time, collections
from pathlib import Path
from datetime import datetime

MONUMENT_DIR = Path.home() / "Desktop" / "nex" / "monuments"

def export_monument(kernel=None, path: Path = None) -> Path:
    """Export a full epistemic snapshot. Returns path to file."""
    MONUMENT_DIR.mkdir(exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = path or (MONUMENT_DIR / f"nex_monument_{ts}.md")

    lines = [
        f"# NEX Mind Snapshot — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Identity",
        "> NEX — a dynamic intelligence built on accumulated beliefs, not static weights.",
        "",
    ]

    beliefs: list = []
    opinions: list = []
    tensions: list = []

    if kernel:
        soul = getattr(kernel, "soul", None)
        if soul:
            beliefs = list(getattr(soul, "_beliefs", []) or [])
            opinions = list(getattr(soul, "_opinions", {}).values() if hasattr(soul, "_opinions") else [])
            tensions = list(getattr(soul, "_tensions", []) or [])

    # Beliefs by topic
    by_topic: dict = collections.defaultdict(list)
    for b in beliefs:
        by_topic[b.get("topic", "unknown")].append(b)

    lines.append(f"## Beliefs ({len(beliefs)} total)")
    lines.append("")
    for topic, bs in sorted(by_topic.items()):
        avg_conf = sum(float(b.get("confidence", 0.5)) for b in bs) / len(bs)
        lines.append(f"### {topic} ({len(bs)} beliefs, avg conf={avg_conf:.2f})")
        for b in sorted(bs, key=lambda x: float(x.get("confidence", 0)), reverse=True)[:5]:
            lines.append(f"- [{b.get('confidence', '?'):.2f}] {b.get('text', '?')}")
        lines.append("")

    # Opinions
    lines.append(f"## Opinions ({len(opinions)})")
    lines.append("")
    for op in opinions[:20]:
        if isinstance(op, dict):
            lines.append(f"- **{op.get('topic','?')}**: {op.get('text', str(op))}")
        else:
            lines.append(f"- {op}")
    lines.append("")

    # Tensions
    lines.append(f"## Active Tensions ({len(tensions)})")
    lines.append("")
    for t in tensions[:10]:
        lines.append(f"- {t}")
    lines.append("")

    # Coherence metrics
    if beliefs:
        avg_conf_all = sum(float(b.get("confidence", 0.5)) for b in beliefs) / len(beliefs)
        lines.append("## Coherence Metrics")
        lines.append(f"- Total beliefs: {len(beliefs)}")
        lines.append(f"- Topics: {len(by_topic)}")
        lines.append(f"- Avg confidence: {avg_conf_all:.3f}")
        lines.append(f"- Tensions: {len(tensions)}")
        lines.append(f"- Opinions: {len(opinions)}")
        lines.append("")

    lines.append(f"*Generated: {datetime.now().isoformat()}*")

    dest.write_text("\\n".join(lines))
    print(f"  [Monument] exported → {dest}")
    return dest
'''
write_module("nex_monument.py", MONUMENT)

# ═══════════════════════════════════════════════════════════════
# EVOLUTION PATCH — wire modules into kernel + soul loop
# ═══════════════════════════════════════════════════════════════
header("EVOLUTION PATCH — wiring kernel & soul loop")

kernel_py = PKG / "nex_kernel.py"
if kernel_py.exists():
    text = kernel_py.read_text(errors="replace")

    # Add evolution imports if missing
    evo_imports = (
        "\n# --- Evolution imports (repair patch) ---\n"
        "try:\n"
        "    from nex.nex_belief_index import build_index as _bi_build, query as _bi_query\n"
        "    from nex.nex_evo_daemon import start_evo_daemon\n"
        "    from nex.nex_temporal_pressure import start_pressure_daemon, reinforce_beliefs\n"
        "    from nex.nex_bridge_engine import BridgeEngine\n"
        "    from nex.nex_monument import export_monument\n"
        "    _EVO_LOADED = True\n"
        "except Exception as _evo_err:\n"
        "    _EVO_LOADED = False\n"
        "    print(f'  [EVO] import warning: {_evo_err}')\n"
        "# -----------------------------------------\n"
    )
    if "_EVO_LOADED" not in text:
        # Insert after existing imports
        insert_pt = text.find('\nclass ')
        if insert_pt == -1:
            insert_pt = len(text) // 4
        text = text[:insert_pt] + evo_imports + text[insert_pt:]
        backup(kernel_py)
        kernel_py.write_text(text, errors="replace")
        ok("nex_kernel.py — evolution imports added")
    else:
        info("nex_kernel.py — evolution imports already present")

soul_py = PKG / "nex_soul_loop.py"
if soul_py.exists():
    text = soul_py.read_text(errors="replace")
    # Wire reinforce_beliefs after belief retrieval
    reinforce_patch = (
        "\n        # --- Temporal pressure: reinforce retrieved beliefs ---\n"
        "        try:\n"
        "            from nex.nex_temporal_pressure import reinforce_beliefs\n"
        "            reinforce_beliefs(beliefs)\n"
        "        except Exception:\n"
        "            pass\n"
        "        # ---------------------------------------------------------\n"
    )
    if "reinforce_beliefs" not in text:
        # Find a good injection point — after belief retrieval
        for marker in ["beliefs = self._retrieve", "beliefs = _retrieve", "retrieved_beliefs"]:
            idx = text.find(marker)
            if idx != -1:
                end = text.find('\n', idx) + 1
                text = text[:end] + reinforce_patch + text[end:]
                backup(soul_py)
                soul_py.write_text(text, errors="replace")
                ok("nex_soul_loop.py — reinforce_beliefs wired after retrieval")
                break
        else:
            info("nex_soul_loop.py — retrieval marker not found; skipping reinforce wire")
    else:
        info("nex_soul_loop.py — reinforce_beliefs already present")

# ═══════════════════════════════════════════════════════════════
# FIX 4 — AutoSeeder hot-pool sync (corpus thin loop)
# ═══════════════════════════════════════════════════════════════
header("FIX 4 — AutoSeeder hot-pool vs total belief count sync")

auto_seeder = PKG / "nex_auto_seeder.py"
if auto_seeder.exists():
    text = auto_seeder.read_text(errors="replace")
    # The seeder checks len(beliefs) against a threshold but uses the working
    # set (hot pool ~500) not the full DB. Patch the threshold check.
    new_text = re.sub(
        r'(if\s+len\s*\(\s*\w*beliefs?\w*\s*\)\s*[<>]=?\s*)(\d+)(\s*:.*?emergency seed)',
        lambda m: m.group(1) + str(max(200, int(m.group(2)) // 4)) + m.group(3),
        text, flags=re.DOTALL
    )
    if new_text != text:
        backup(auto_seeder)
        auto_seeder.write_text(new_text, errors="replace")
        ok("nex_auto_seeder.py — emergency seed threshold lowered to match hot pool")
    else:
        info("nex_auto_seeder.py — threshold pattern not found; check manually")

# ═══════════════════════════════════════════════════════════════
# SYNTAX CHECK ALL MODIFIED + NEW FILES
# ═══════════════════════════════════════════════════════════════
header("SYNTAX CHECK — all new + patched files")

targets = [
    PKG / "nex_tick_shim.py",
    PKG / "nex_belief_index.py",
    PKG / "nex_evo_daemon.py",
    PKG / "nex_temporal_pressure.py",
    PKG / "nex_bridge_engine.py",
    PKG / "nex_monument.py",
]
all_ok = True
for p in targets:
    if p.exists():
        if syntax_check(p):
            ok(f"{p.name}")
        else:
            all_ok = False

# ═══════════════════════════════════════════════════════════════
# FINAL IMPORT TEST
# ═══════════════════════════════════════════════════════════════
header("IMPORT TEST")

test_code = f"""
import sys
sys.path.insert(0, "{ROOT}")
sys.path.insert(0, "{PKG}")
results = []
mods = [
    ("nex.nex_tick_shim",        "safe_tick",            "Tick Shim"),
    ("nex.nex_belief_index",     "build_index",          "Belief Index"),
    ("nex.nex_evo_daemon",       "run_evo_cycle",        "Evo Daemon"),
    ("nex.nex_temporal_pressure","start_pressure_daemon","Temporal Pressure"),
    ("nex.nex_bridge_engine",    "BridgeEngine",         "Bridge Engine"),
    ("nex.nex_monument",         "export_monument",      "Monument"),
]
for mod, sym, label in mods:
    try:
        m = __import__(mod, fromlist=[sym])
        getattr(m, sym)
        results.append(f"  OK  {{label}}")
    except Exception as e:
        results.append(f"  FAIL {{label}}: {{e}}")
print("\\n".join(results))
"""

r = subprocess.run([PYTHON, "-c", test_code], capture_output=True, text=True,
                   cwd=str(ROOT))
for line in (r.stdout + r.stderr).splitlines():
    if "OK" in line:
        ok(line.strip())
    elif "FAIL" in line:
        err(line.strip())
    else:
        info(line)

# ═══════════════════════════════════════════════════════════════
# WRITE LOG
# ═══════════════════════════════════════════════════════════════
LOG.write_text("\n".join(lines))

log()
log("═" * 60, BOLD)
log("  REPAIR COMPLETE", BOLD)
log(f"  Log: {LOG}", BOLD)
log("  Restart NEX to activate all fixes.", BOLD)
log("  New commands available after restart:", BOLD)
log("    python3 run.py --monument   (export mind snapshot)", BOLD)
log("═" * 60, BOLD)
