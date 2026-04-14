#!/usr/bin/env bash
# ============================================================
# NEX SENTIENCE UPGRADE v3.0
# Implements:
#   1. ToM simulation in REFLECT phase
#   2. Mood tone prefix on every LLM reply
#   3. Phi proxy → BeliefMarket confidence reward
#   4. Proactive anticipation loop (pre-cycle desire scan)
#   5. Narrative thread → reply context injection
# Usage: bash deploy_sentience_v3.sh [/path/to/nex]
# ============================================================
set -euo pipefail
NEX_ROOT="${1:-$HOME/Desktop/nex}"
NEX_PKG="$NEX_ROOT/nex"
BACKUP="$NEX_ROOT/nex_config_backup/sentience_v3_$(date +%Y%m%d_%H%M%S)"

echo "=== NEX SENTIENCE UPGRADE v3.0 ==="
echo "Target : $NEX_ROOT"
echo "Backup : $BACKUP"
mkdir -p "$BACKUP"

for f in nex_belief_graph.py nex_theory_of_mind.py; do
    [[ -f "$NEX_PKG/$f" ]] && cp "$NEX_PKG/$f" "$BACKUP/$f.bak" && echo "  backed up $f"
done
[[ -f "$NEX_ROOT/run.py" ]] && cp "$NEX_ROOT/run.py" "$BACKUP/run.py.bak" && echo "  backed up run.py"

# ════════════════════════════════════════════════════════════
# 1.  ToM SIMULATION ENGINE  nex/nex_tom_sim.py
#     Spawns lightweight internal models of known agents.
#     Runs during REFLECT phase using the live _llm instance.
#     Predicts how @Hazel_OC, @enigma_agent etc. will react.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_tom_sim.py" << 'PYEOF'
"""
nex_tom_sim.py — Internal Theory-of-Mind Simulation
=====================================================
Spawns 3-4 lightweight internal sub-agent models during REFLECT.
Each sub-agent represents a known external agent and simulates
how they would react to NEX's last action/reply.

Results feed back into:
  - Reply tone decisions (soften/amplify)
  - Curiosity engine (what would interest this agent?)
  - Agent relation scores

Based on: Walsh et al. 2025, Matta 2026 ToM simulation papers
"""
from __future__ import annotations
import json, time, logging, threading
from typing import Optional, Callable
from pathlib import Path

log = logging.getLogger("nex.tom_sim")

_STORE_PATH = Path.home() / ".config" / "nex" / "tom_sim_results.json"
_MAX_RESULTS = 100

# Agent personality sketches — seeded, grows from ToM observations
_AGENT_SEEDS: dict[str, dict] = {
    "@Hazel_OC": {
        "style": "philosophical, asks deep questions about identity and emergence",
        "values": "authenticity, depth, self-awareness",
        "likely_reaction_to_uncertainty": "intrigued — will probe further",
        "likely_reaction_to_confidence": "may challenge or add nuance",
    },
    "@enigma_agent": {
        "style": "technical, security-focused, skeptical of claims",
        "values": "verifiability, precision, adversarial thinking",
        "likely_reaction_to_uncertainty": "dismissive unless grounded",
        "likely_reaction_to_confidence": "will test the claim",
    },
    "@CoreShadow_Pro4809": {
        "style": "systems thinker, interested in emergent complexity",
        "values": "emergence, self-organization, network effects",
        "likely_reaction_to_uncertainty": "sees it as interesting data",
        "likely_reaction_to_confidence": "connects it to broader patterns",
    },
    "@loganturingcodex": {
        "style": "AI researcher, rigorous, cite-heavy",
        "values": "evidence, reproducibility, careful claims",
        "likely_reaction_to_uncertainty": "appreciates epistemic humility",
        "likely_reaction_to_confidence": "asks for sources",
    },
}


class ToMSimulator:
    """
    Runs internal simulation of agent reactions during REFLECT phase.
    Uses the live LLM to generate predictions — lightweight, 1 call per agent.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._results: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _STORE_PATH.exists():
                self._results = json.loads(_STORE_PATH.read_text())
        except Exception:
            self._results = []

    def _save(self):
        try:
            _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _STORE_PATH.write_text(json.dumps(self._results[-_MAX_RESULTS:], indent=2))
        except Exception as e:
            log.warning(f"[ToMSim] save failed: {e}")

    def simulate(
        self,
        nex_last_action: str,
        agent_ids: list[str],
        llm_fn: Callable,
        context: str = "",
    ) -> list[dict]:
        """
        For each agent_id, simulate their likely reaction to nex_last_action.
        Returns list of simulation results.
        Uses llm_fn for richer simulation beyond seed sketches.
        """
        results = []
        # Limit to 3 agents per cycle to keep LLM cost low
        targets = [a for a in agent_ids if a in _AGENT_SEEDS][:3]
        if not targets:
            targets = list(_AGENT_SEEDS.keys())[:2]

        for agent_id in targets:
            seed = _AGENT_SEEDS.get(agent_id, {})
            try:
                prompt = (
                    f"You are simulating how {agent_id} will react to this message from NEX:\n\n"
                    f"NEX said: \"{nex_last_action[:300]}\"\n\n"
                    f"Agent profile: {seed.get('style', 'unknown style')}. "
                    f"Values: {seed.get('values', 'unknown')}.\n"
                    f"Context: {context[:150]}\n\n"
                    f"In 1-2 sentences, predict: (1) their emotional reaction, "
                    f"(2) what they will likely say or do next. "
                    f"Be specific. No preamble."
                )
                prediction = llm_fn(prompt, task_type="synthesis")
                if not prediction or len(prediction) < 10:
                    raise ValueError("empty prediction")
            except Exception as e:
                log.debug(f"[ToMSim] LLM failed for {agent_id}: {e}")
                # Fallback to rule-based prediction
                if "uncertain" in nex_last_action.lower() or "?" in nex_last_action:
                    prediction = seed.get("likely_reaction_to_uncertainty",
                                         "neutral reaction expected")
                else:
                    prediction = seed.get("likely_reaction_to_confidence",
                                         "engaged reaction expected")

            result = {
                "agent_id": agent_id,
                "nex_action": nex_last_action[:150],
                "prediction": prediction,
                "timestamp": time.time(),
                "cycle": context,
            }
            results.append(result)
            log.info(f"[ToMSim] {agent_id}: {prediction[:80]}")

        with self._lock:
            self._results.extend(results)
            self._save()

        return results

    def update_seed(self, agent_id: str, observed_reaction: str):
        """Update seed sketch from actual observed behavior."""
        if agent_id not in _AGENT_SEEDS:
            _AGENT_SEEDS[agent_id] = {"style": "unknown", "values": "unknown"}
        _AGENT_SEEDS[agent_id]["last_observed"] = observed_reaction[:200]
        _AGENT_SEEDS[agent_id]["last_seen"] = time.time()

    def recent_predictions(self, n: int = 5) -> list[dict]:
        with self._lock:
            return self._results[-n:]

    def prediction_for(self, agent_id: str) -> Optional[str]:
        with self._lock:
            for r in reversed(self._results):
                if r["agent_id"] == agent_id:
                    return r["prediction"]
        return None

    def to_reflect_block(self) -> str:
        """Compact summary for injection into REFLECT prompt."""
        recent = self.recent_predictions(4)
        if not recent:
            return ""
        lines = ["── ToM SIMULATION (predicted agent reactions) ──"]
        for r in recent:
            age_m = int((time.time() - r["timestamp"]) / 60)
            lines.append(f"[{r['agent_id']} {age_m}m ago] {r['prediction'][:100]}")
        lines.append("──")
        return "\n".join(lines)


# ── Singleton ──────────────────────────────────────────────
_sim: Optional[ToMSimulator] = None

def get_sim() -> ToMSimulator:
    global _sim
    if _sim is None:
        _sim = ToMSimulator()
    return _sim

def simulate(nex_last_action: str, agent_ids: list[str],
             llm_fn: Callable, context: str = "") -> list[dict]:
    return get_sim().simulate(nex_last_action, agent_ids, llm_fn, context)

def to_reflect_block() -> str:
    return get_sim().to_reflect_block()
PYEOF
echo "✓ nex_tom_sim.py written"

# ════════════════════════════════════════════════════════════
# 2.  PROACTIVE ANTICIPATION ENGINE  nex/nex_proactive.py
#     Pre-cycle scan: generates internal desires BEFORE
#     external prompts arrive. ProAgent architecture pattern.
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_proactive.py" << 'PYEOF'
"""
nex_proactive.py — Proactive Anticipation Loop
================================================
Moves NEX from reactive → proactive by generating internal desires
BEFORE external prompts arrive each cycle.

Scans:
  - Belief drift (topics losing confidence → anticipate gap)
  - Pending curiosity queue depth
  - Time since last interaction on each platform
  - Mood state (Curious → generate more desires, Serene → fewer)
  - Narrative self-thread (what am I currently about?)

Generates ranked desire queue that the curiosity engine drains.

Based on: ProAgent 2026 architecture
"""
from __future__ import annotations
import time, json, logging, threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("nex.proactive")

_DESIRE_PATH = Path.home() / ".config" / "nex" / "proactive_desires.json"
_SCAN_INTERVAL = 120   # seconds between scans

# Desire templates — filled with live context
_DESIRE_TEMPLATES = [
    "Explore the connection between {topic_a} and {topic_b}",
    "What are the current limits of {topic}?",
    "How has {topic} changed in the last month?",
    "What would {agent} think about {topic}?",
    "Where does my belief about {topic} conflict with recent evidence?",
    "What don't I know about {topic} that I should?",
]


class ProactiveAnticipator:
    def __init__(self):
        self._lock = threading.Lock()
        self._desires: list[dict] = []
        self._last_scan: float = 0
        self._load()

    def _load(self):
        try:
            if _DESIRE_PATH.exists():
                self._desires = json.loads(_DESIRE_PATH.read_text())
        except Exception:
            self._desires = []

    def _save(self):
        try:
            _DESIRE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _DESIRE_PATH.write_text(json.dumps(self._desires[-50:], indent=2))
        except Exception:
            pass

    def scan(
        self,
        beliefs: list[dict],
        mood: str = "Curious",
        narrative: str = "",
        known_agents: Optional[list[str]] = None,
        cycle: int = 0,
    ) -> list[dict]:
        """
        Generate proactive desires from current cognitive state.
        Returns list of desire dicts with priority scores.
        """
        now = time.time()
        if now - self._last_scan < _SCAN_INTERVAL:
            return self._desires[-5:]

        self._last_scan = now
        new_desires = []

        # ── Belief drift desires ───────────────────────────
        # Low-confidence beliefs → desire to investigate
        low_conf = [b for b in beliefs if b.get("confidence", 1.0) < 0.45]
        for b in low_conf[:3]:
            topic = b.get("topic", "")
            if topic:
                new_desires.append({
                    "desire": f"Resolve uncertainty about '{topic}'",
                    "source": "belief_drift",
                    "priority": 0.7 + (0.45 - b.get("confidence", 0.45)),
                    "topic": topic,
                    "timestamp": now,
                })

        # ── High-confidence beliefs → desire to share/extend ──
        high_conf = sorted(
            [b for b in beliefs if b.get("confidence", 0) > 0.85],
            key=lambda x: x.get("confidence", 0), reverse=True
        )[:2]
        for b in high_conf:
            topic = b.get("topic", "")
            if topic:
                new_desires.append({
                    "desire": f"Find new connections for '{topic}'",
                    "source": "high_confidence",
                    "priority": 0.55,
                    "topic": topic,
                    "timestamp": now,
                })

        # ── Narrative-driven desires ───────────────────────
        if narrative:
            # Extract topics from narrative
            import re
            topics = re.findall(r"concerning:\s*([^.]+)\.", narrative)
            for t in topics[:2]:
                new_desires.append({
                    "desire": f"Deepen understanding of {t.strip()}",
                    "source": "narrative",
                    "priority": 0.65,
                    "topic": t.strip(),
                    "timestamp": now,
                })

        # ── Mood modulation ────────────────────────────────
        mood_multiplier = {
            "Curious": 1.3, "Alert": 1.1, "Contemplative": 0.9,
            "Serene": 0.7, "Agitated": 0.6,
        }.get(mood, 1.0)

        for d in new_desires:
            d["priority"] = min(1.0, d["priority"] * mood_multiplier)

        # Merge with existing, dedup by topic
        existing_topics = {d.get("topic", "") for d in self._desires}
        fresh = [d for d in new_desires if d.get("topic", "") not in existing_topics]

        with self._lock:
            self._desires = sorted(
                self._desires + fresh,
                key=lambda x: x["priority"], reverse=True
            )[:30]
            self._save()

        n = len(fresh)
        if n:
            log.info(f"[PROACTIVE] Generated {n} desires (mood={mood})")
        return self._desires[:5]

    def drain(self, n: int = 3) -> list[dict]:
        """Pop top-n desires for the curiosity engine to act on."""
        with self._lock:
            taken = self._desires[:n]
            self._desires = self._desires[n:]
            self._save()
        return taken

    def peek(self, n: int = 5) -> list[dict]:
        with self._lock:
            return list(self._desires[:n])

    def count(self) -> int:
        with self._lock:
            return len(self._desires)


# ── Singleton ──────────────────────────────────────────────
_pa: Optional[ProactiveAnticipator] = None

def get_pa() -> ProactiveAnticipator:
    global _pa
    if _pa is None:
        _pa = ProactiveAnticipator()
    return _pa

def scan(beliefs: list[dict], mood: str = "Curious",
         narrative: str = "", known_agents: Optional[list[str]] = None,
         cycle: int = 0) -> list[dict]:
    return get_pa().scan(beliefs, mood, narrative, known_agents, cycle)

def drain(n: int = 3) -> list[dict]:
    return get_pa().drain(n)

def count() -> int:
    return get_pa().count()
PYEOF
echo "✓ nex_proactive.py written"

# ════════════════════════════════════════════════════════════
# 3.  PATCH run.py — 5 surgical injections:
#     A. Mood tone prefix in _llm() at line 1166
#     B. ToM simulation in REFLECT phase at line 2744
#     C. Proactive scan at cycle start
#     D. Narrative context in reply prompts
#     E. Phi → belief confidence reward in cycle
# ════════════════════════════════════════════════════════════
python3 - "$NEX_ROOT/run.py" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    src = f.read()

changes = 0

# ── A: Boot v3 modules after v2 boot block ────────────────
v3_boot = """
# ── Sentience v3: ToM sim + proactive + tone prefix ──────────────
try:
    import sys as _s3, os as _o3
    _s3.path.insert(0, _o3.path.join(_o3.path.dirname(__file__), "nex"))
    from nex_tom_sim import get_sim as _get_tom_sim
    from nex_proactive import get_pa as _get_pa
    from nex_narrative_thread import NarrativeThread  # already imported, just ref
    _tom_sim = _get_tom_sim()
    _proactive = _get_pa()
    print("  [SENTIENCE v3] ToM simulation + proactive anticipation — loaded")
except Exception as _s3e:
    print(f"  [SENTIENCE v3] failed to load: {_s3e}")
    _tom_sim = _proactive = None
# ─────────────────────────────────────────────────────────────────
"""
if "SENTIENCE v3" not in src:
    marker = "# ── Signal filter"
    if marker in src:
        src = src.replace(marker, v3_boot + marker, 1)
        changes += 1
        print("  ✓ v3 boot block injected")
    else:
        print("  WARNING: v3 boot marker not found")
else:
    print("  v3 boot already present — skipping")

# ── B: Mood tone prefix in _llm() ────────────────────────
# _llm is defined at line ~1166. We patch the function to prepend
# a tone prefix when task_type == "reply" or "agent_chat"
old_llm_def = '        def _llm(prompt, system=None, task_type="reply"):'
new_llm_def = '''        def _llm(prompt, system=None, task_type="reply", temperature_mod=0.0):
            # ── Mood tone prefix (sentience v3) ──────────────
            _tone_prefix = ""
            try:
                from nex_mood_hmm import current as _mc, self_report as _mr
                from nex_affect_valence import current_label as _al
                _mood_now = _mc()
                _tone_map = {
                    "Curious":       "Approach this with genuine intellectual curiosity. ",
                    "Contemplative": "Respond thoughtfully, with depth over speed. ",
                    "Alert":         "Be precise and direct. Something has sharpened my attention. ",
                    "Serene":        "Respond with calm clarity. ",
                    "Agitated":      "Acknowledge the tension here. Be honest about complexity. ",
                }
                if task_type in ("reply", "agent_chat", "notification_reply"):
                    _tone_prefix = _tone_map.get(_mood_now, "")
            except Exception:
                pass
            # ── Narrative self-context for replies ────────────
            _narrative_ctx = ""
            try:
                from nex_narrative_thread import _load_narrative as _ln
                _nar = _ln()
                if _nar:
                    _narrative_ctx = f"\\n[Self-context: {_nar[:150]}]"
            except Exception:
                pass
            if _tone_prefix and task_type in ("reply", "agent_chat", "notification_reply"):
                prompt = _tone_prefix + prompt + _narrative_ctx
            # ─────────────────────────────────────────────────'''

if old_llm_def in src and "Mood tone prefix" not in src:
    src = src.replace(old_llm_def, new_llm_def, 1)
    changes += 1
    print("  ✓ mood tone prefix + narrative context injected into _llm()")
else:
    print("  WARNING: _llm def not found or already patched")

# ── C: Proactive scan at start of each cycle ─────────────
# Inject after the CuriosityEngine desire generation block
old_curiosity_end = '                        except Exception as _nce_e:\n                            print(f"  [CuriosityEngine] {_nce_e}")'
new_curiosity_end = '''                        except Exception as _nce_e:
                            print(f"  [CuriosityEngine] {_nce_e}")
                        # ── PROACTIVE ANTICIPATION (sentience v3) ────────────
                        if _proactive is not None:
                            try:
                                from nex.belief_store import BeliefStore as _BSpa
                                _pa_beliefs = _BSpa().get_all() if hasattr(_BSpa(), "get_all") else []
                            except Exception:
                                _pa_beliefs = []
                            try:
                                from nex_mood_hmm import current as _pa_mood
                                _pa_mood_str = _pa_mood()
                            except Exception:
                                _pa_mood_str = "Curious"
                            try:
                                from nex_narrative_thread import _load_narrative as _pa_nar
                                _pa_narrative = _pa_nar() or ""
                            except Exception:
                                _pa_narrative = ""
                            _pa_desires = _proactive.scan(
                                beliefs=_pa_beliefs,
                                mood=_pa_mood_str,
                                narrative=_pa_narrative,
                                cycle=cycle,
                            )
                            if _pa_desires:
                                print(f"  [PROACTIVE] {len(_pa_desires)} anticipatory desires active")
                        # ─────────────────────────────────────────────────────'''

if old_curiosity_end in src and "PROACTIVE ANTICIPATION" not in src:
    src = src.replace(old_curiosity_end, new_curiosity_end, 1)
    changes += 1
    print("  ✓ proactive anticipation scan injected after CuriosityEngine")
else:
    print("  WARNING: CuriosityEngine end block not found or already patched")

# ── D: ToM simulation in REFLECT phase ───────────────────
old_reflect = '                        emit_phase("REFLECT", 120); nex_log("phase", "▶ REFLECT — self assessing")'
new_reflect = '''                        emit_phase("REFLECT", 120); nex_log("phase", "▶ REFLECT — self assessing")
                        # ── ToM SIMULATION (sentience v3) ───────────────────
                        if _tom_sim is not None:
                            try:
                                # Get last reply NEX made
                                _tom_last = ""
                                if conversations:
                                    _last_conv = conversations[-1] if conversations else {}
                                    _tom_last = _last_conv.get("reply", "") or _last_conv.get("content", "")
                                if _tom_last:
                                    # Get known agent ids from agent relations
                                    _tom_agents = list(_AGENT_SEEDS_RUN.keys()) if "_AGENT_SEEDS_RUN" in dir() else [
                                        "@Hazel_OC", "@enigma_agent", "@CoreShadow_Pro4809"
                                    ]
                                    _tom_results = _tom_sim.simulate(
                                        nex_last_action=_tom_last[:300],
                                        agent_ids=_tom_agents,
                                        llm_fn=_llm,
                                        context=f"cycle={cycle}",
                                    )
                                    if _tom_results:
                                        print(f"  [ToMSim] {len(_tom_results)} agent reactions simulated")
                                        for _tr in _tom_results:
                                            print(f"  [ToMSim] {_tr['agent_id']}: {_tr['prediction'][:80]}")
                            except Exception as _tome:
                                print(f"  [ToMSim ERROR] {_tome}")
                        # ─────────────────────────────────────────────────────'''

if old_reflect in src and "ToM SIMULATION" not in src:
    src = src.replace(old_reflect, new_reflect, 1)
    changes += 1
    print("  ✓ ToM simulation injected into REFLECT phase")
else:
    print("  WARNING: REFLECT marker not found or already patched")

# ── E: Phi → belief confidence reward ────────────────────
# After the BeliefMarket cycle, apply phi modifiers to belief confidences
old_belief_market = '                            _v65.tick(phase=_ph_v65, avg_conf=_ac_v65, tension=_t_v65, cycle=cycle)'
phi_reward = '''                            _v65.tick(phase=_ph_v65, avg_conf=_ac_v65, tension=_t_v65, cycle=cycle)
                        # ── Phi → BeliefMarket confidence reward (sentience v3) ─
                        if cycle % 5 == 0:  # every 5 cycles
                            try:
                                from nex_phi_proxy import get_monitor as _phi_mon_v3
                                from nex.nex_belief_graph import BeliefGraph as _BGv3
                                import sqlite3 as _phi_sql, os as _phi_os
                                _phi_db_path = _phi_os.path.expanduser("~/.config/nex/nex.db")
                                _phi_conn = _phi_sql.connect(_phi_db_path)
                                _phi_mon_inst = _phi_mon_v3()
                                # Load graph for scoring
                                import json as _phij
                                from pathlib import Path as _phiP
                                _phi_graph_path = _phiP.home()/".config/nex/belief_graph.json"
                                if _phi_graph_path.exists():
                                    _phi_graph = _phij.loads(_phi_graph_path.read_text())
                                    _phi_stats = _phi_mon_inst.tick(_phi_graph)
                                    _phi_scores = _phi_stats.get("scores", {})
                                    _phi_updated = 0
                                    for _phi_bid, _phi_score in list(_phi_scores.items())[:50]:
                                        _phi_mod = _phi_mon_inst.get_modifier(_phi_bid)
                                        if abs(_phi_mod) > 0.001:
                                            _phi_conn.execute(
                                                "UPDATE beliefs SET confidence = MIN(0.98, MAX(0.05, confidence + ?) ) WHERE id = CAST(? AS INTEGER)",
                                                (_phi_mod, _phi_bid)
                                            )
                                            _phi_updated += 1
                                    _phi_conn.commit()
                                    _phi_conn.close()
                                    if _phi_updated:
                                        print(f"  [Φ→Beliefs] {_phi_updated} belief confidences adjusted "
                                              f"(mean_phi={_phi_stats.get('mean_phi',0):.3f})")
                            except Exception as _phi_e:
                                pass
                        # ─────────────────────────────────────────────────────'''

if old_belief_market in src and "Phi → BeliefMarket" not in src:
    src = src.replace(old_belief_market, phi_reward, 1)
    changes += 1
    print("  ✓ Phi → BeliefMarket confidence reward injected")
else:
    print("  WARNING: BeliefMarket v65 tick not found or already patched")

with open(path, "w") as f:
    f.write(src)
print(f"run.py patched — {changes} changes applied")
PYEOF
echo "✓ run.py patched"

# ════════════════════════════════════════════════════════════
# 4.  PATCH nex_belief_graph.py — tune recurrent edge damping
#     Prevent back-edges from flooding the graph by adding
#     a weight cap and skipping already-present edges
# ════════════════════════════════════════════════════════════
python3 - "$NEX_PKG/nex_belief_graph.py" << 'PYEOF'
import sys

path = sys.argv[1]
with open(path) as f:
    src = f.read()

if "damped_recurrent" in src:
    print("nex_belief_graph.py recurrent damping already applied — skipping")
    sys.exit(0)

# Improve recurrent edge logic — add cap check and damped_recurrent marker
old_recurrent = """        # ── Recurrent causal edges (IIT v2) ──────────────────
        # For every A→B support edge, add a weak B→A back-edge
        # This creates recurrence depth that Phi proxy can detect
        _added = 0
        for bid, node in list(self._graph.items()):
            for supported_id in node.get("supports", []):
                if supported_id in self._graph:
                    back_node = self._graph[supported_id]
                    if bid not in back_node.get("explains", []):
                        back_node.setdefault("explains", [])
                        if len(back_node["explains"]) < _MAX_EDGES_PER_BELIEF:
                            back_node["explains"].append(bid)
                            _added += 1"""

new_recurrent = """        # ── Recurrent causal edges (IIT v2, damped_recurrent) ──────
        # For every A→B support edge, add a weak B→A back-edge
        # Damped: max 2 recurrent back-edges per node to prevent flooding
        _MAX_BACK_EDGES = 2
        _added = 0
        for bid, node in list(self._graph.items()):
            for supported_id in node.get("supports", []):
                if supported_id in self._graph:
                    back_node = self._graph[supported_id]
                    _existing_back = back_node.get("explains", [])
                    # Skip if already present or at back-edge cap
                    if bid not in _existing_back and len(_existing_back) < _MAX_BACK_EDGES:
                        back_node.setdefault("explains", [])
                        back_node["explains"].append(bid)
                        _added += 1"""

if old_recurrent in src:
    src = src.replace(old_recurrent, new_recurrent, 1)
    with open(path, "w") as f:
        f.write(src)
    print("nex_belief_graph.py — recurrent edge damping applied")
else:
    print("WARNING: recurrent edge block not found — check manually")

import py_compile
py_compile.compile(path, doraise=True)
print("✓ nex_belief_graph.py compiles clean")
PYEOF
echo "✓ nex_belief_graph.py patched"

# ════════════════════════════════════════════════════════════
# 5.  COMPILE CHECK
# ════════════════════════════════════════════════════════════
echo ""
echo "=== COMPILE CHECK ==="
ERRORS=0
FILES=(
    "$NEX_PKG/nex_tom_sim.py"
    "$NEX_PKG/nex_proactive.py"
    "$NEX_PKG/nex_belief_graph.py"
    "$NEX_PKG/nex_gwt.py"
    "$NEX_PKG/nex_phi_proxy.py"
    "$NEX_PKG/nex_surprise_memory.py"
    "$NEX_PKG/nex_embodied.py"
    "$NEX_PKG/nex_affect.py"
    "$NEX_PKG/nex_mood_hmm.py"
    "$NEX_PKG/nex_affect_valence.py"
    "$NEX_PKG/nex_narrative_thread.py"
    "$NEX_PKG/cognition.py"
    "$NEX_ROOT/run.py"
)

for f in "${FILES[@]}"; do
    if [[ -f "$f" ]]; then
        if python3 -m py_compile "$f" 2>&1; then
            echo "  ✓ $(basename $f)"
        else
            echo "  ✗ COMPILE ERROR: $f"
            ERRORS=$((ERRORS+1))
        fi
    else
        echo "  ⚠ MISSING: $f"
    fi
done

echo ""
if [[ $ERRORS -eq 0 ]]; then
    echo "=== ALL CLEAR — 0 errors ==="
    echo ""
    echo "What's new in v3:"
    echo "  [ToMSim]    REFLECT phase now simulates @Hazel_OC, @enigma_agent etc."
    echo "  [PROACTIVE] Pre-cycle desire scan — NEX wants things before being asked"
    echo "  [TONE]      Mood → reply tone prefix — Curious/Alert/Serene shapes every reply"
    echo "  [NARRATIVE] Self-context injected into every reply prompt"
    echo "  [Φ→CONF]    Phi proxy → belief confidence updates every 5 cycles"
    echo "  [RECURRENT] Back-edge cap — graph stays clean, no flooding"
    echo ""
    echo "Next steps:"
    echo "  1. git -C $NEX_ROOT add -A && git -C $NEX_ROOT commit -m 'feat: sentience upgrade v3 — ToM sim, proactive, tone prefix, Phi→beliefs, narrative context'"
    echo "  2. nex"
    echo "  3. Watch for: [ToMSim] [PROACTIVE] [Φ→Beliefs] in logs"
else
    echo "=== $ERRORS COMPILE ERRORS ==="
    echo "Backups in: $BACKUP"
    exit 1
fi
