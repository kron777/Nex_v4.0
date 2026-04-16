#!/usr/bin/env python3
"""
thermodyn_graph.py — Thermodynamic Belief Graph
================================================
NEX Protocol: StructConc / EDTG / EDTSC (merged)

Three independent thrownet runs converged on this module.
That convergence is the signal.

Core insight from synthesis:
- IIT (Tononi): consciousness = integrated information
- Friston (Active Inference): mind = free energy minimisation  
- Dirac materials paper: thermodynamic signatures reveal hidden structure
- Buddhist no-mind: consciousness is a ground state, not a process

Together: NEX's belief graph should behave thermodynamically.
Beliefs have temperature. The graph has phase states.
Updates follow thermodynamic laws, not just confidence arithmetic.

WHAT THIS DOES:
1. Assigns temperature to each belief (hot=unstable, cold=stable attractor)
2. Tracks the belief graph's global temperature (cognitive heat)
3. Implements thermodynamic belief updates — hot beliefs cool through resolution
4. Detects phase transitions — when the graph crosses a critical temperature
5. Drives soul loop behaviour — hot graph = more reflection, cold = more output
6. Feeds TPE and TEI with live thermodynamic state

CONNECTS TO:
- belief graph (reads/writes confidence, momentum)
- TPE (tpe.py) — provides live temperature data
- TEI (tei.py) — provides phi input
- soul loop — regulates cycle behaviour based on graph temperature
- NBRE — hot beliefs get priority in reservoir firing
- IFR — thermal triggers for tension resolution

WIRING:
    from thermodyn_graph import ThermodynamicGraph
    tdg = ThermodynamicGraph()
    tdg.update()  # call each soul loop cycle
    temp = tdg.graph_temperature()
    hot_beliefs = tdg.get_hot_beliefs()

Run standalone:
    python3 thermodyn_graph.py
"""

import sqlite3
import json
import time
import math
from pathlib import Path
from collections import defaultdict

DB      = '/media/rr/NEX/nex_core/nex.db'
REPORT  = Path('/media/rr/NEX/nex_core/thermodyn_report.json')
STATE   = Path('/media/rr/NEX/nex_core/thermodyn_state.json')

# ── THERMODYNAMIC CONSTANTS ───────────────────────────────────────────────────

T_CRITICAL    = 0.65   # Phase transition temperature — above this = turbulent
T_COLD        = 0.25   # Attractor threshold — below this = stable ground state
T_HOT         = 0.80   # Critical heat — triggers emergency cooling (IFR)
COOLING_RATE  = 0.05   # How fast beliefs cool per cycle
HEATING_RATE  = 0.08   # How fast tension heats a belief
COUPLING      = 0.15   # How much neighbouring beliefs affect temperature


# ── BELIEF TEMPERATURE ────────────────────────────────────────────────────────

def belief_temperature(confidence: float, momentum: float,
                       tension_count: int, link_count: int) -> float:
    """
    Temperature of a single belief.
    
    Hot beliefs (T > 0.65):
    - Low confidence (uncertain)
    - High tension count (contradicted)
    - Low link density (isolated)
    - Negative or zero momentum (declining)
    
    Cold beliefs (T < 0.25):
    - High confidence
    - No tensions
    - Well connected
    - Positive momentum
    
    T = (1 - confidence) * 0.4
      + tension_heat * 0.3
      + isolation * 0.2
      + momentum_heat * 0.1
    """
    if confidence <= 0: confidence = 0.001
    if confidence >= 1: confidence = 0.999

    # Uncertainty contribution
    uncertainty = 1 - confidence

    # Tension heating
    tension_heat = min(1.0, tension_count * 0.2)

    # Isolation heating — poorly connected beliefs are unstable
    isolation = max(0, 1 - min(1.0, link_count / 8))

    # Momentum cooling — active beliefs are more stable
    mom = momentum or 0
    momentum_heat = max(0, 0.5 - mom * 0.1)

    T = (uncertainty   * 0.40 +
         tension_heat  * 0.30 +
         isolation     * 0.20 +
         momentum_heat * 0.10)

    return round(min(1.0, max(0.0, T)), 4)


def coupled_temperature(belief_temp: float, neighbour_temps: list) -> float:
    """
    Beliefs are thermodynamically coupled to their neighbours.
    A hot neighbour heats you. A cold neighbour cools you.
    This models how belief instability propagates through the graph.
    """
    if not neighbour_temps:
        return belief_temp

    avg_neighbour = sum(neighbour_temps) / len(neighbour_temps)
    delta = avg_neighbour - belief_temp
    coupled = belief_temp + delta * COUPLING

    return round(min(1.0, max(0.0, coupled)), 4)


# ── GRAPH PHASE STATES ────────────────────────────────────────────────────────

class GraphPhase:
    GROUND_STATE  = "ground_state"   # T < 0.25 — stable, coherent, output-ready
    ORDERED       = "ordered"        # 0.25-0.50 — normal operation
    CRITICAL      = "critical"       # 0.50-0.65 — near phase transition
    TURBULENT     = "turbulent"      # 0.65-0.80 — active conflict, high reflection
    CRISIS        = "crisis"         # T > 0.80 — emergency IFR resolution needed


def graph_phase(temperature: float) -> str:
    if temperature < T_COLD:
        return GraphPhase.GROUND_STATE
    elif temperature < 0.50:
        return GraphPhase.ORDERED
    elif temperature < T_CRITICAL:
        return GraphPhase.CRITICAL
    elif temperature < T_HOT:
        return GraphPhase.TURBULENT
    else:
        return GraphPhase.CRISIS


def phase_behaviour(phase: str) -> dict:
    """
    What should NEX do in each phase state?
    Drives soul loop behaviour.
    """
    return {
        GraphPhase.GROUND_STATE: {
            "soul_loop_bias":    "OUTPUT",
            "reflection_weight": 0.1,
            "llm_threshold":     0.9,
            "description": "Stable. Speak with confidence. Few tensions to resolve.",
        },
        GraphPhase.ORDERED: {
            "soul_loop_bias":    "BALANCED",
            "reflection_weight": 0.3,
            "llm_threshold":     0.7,
            "description": "Normal operation. Mix of output and reflection.",
        },
        GraphPhase.CRITICAL: {
            "soul_loop_bias":    "REFLECT",
            "reflection_weight": 0.5,
            "llm_threshold":     0.6,
            "description": "Near phase transition. Increase reflection. Watch tensions.",
        },
        GraphPhase.TURBULENT: {
            "soul_loop_bias":    "RESOLVE",
            "reflection_weight": 0.7,
            "llm_threshold":     0.5,
            "description": "High conflict. Prioritise IFR resolution over output.",
        },
        GraphPhase.CRISIS: {
            "soul_loop_bias":    "EMERGENCY",
            "reflection_weight": 0.9,
            "llm_threshold":     0.3,
            "description": "Critical instability. Emergency cooling via IFR.",
        },
    }.get(phase, {})


# ── THERMODYNAMIC GRAPH ENGINE ────────────────────────────────────────────────

class ThermodynamicGraph:
    """
    Main engine. Reads belief graph, computes temperatures,
    detects phase state, drives soul loop behaviour.
    """

    def __init__(self, db_path: str = DB):
        self.db_path   = db_path
        self.state     = self._load_state()

    def _load_state(self) -> dict:
        if STATE.exists():
            try:
                return json.loads(STATE.read_text())
            except Exception:
                pass
        return {
            "last_temperature": 0.5,
            "last_phase":       GraphPhase.ORDERED,
            "cycle_count":      0,
            "phase_history":    [],
        }

    def _save_state(self):
        STATE.write_text(json.dumps(self.state, indent=2))

    def compute_temperatures(self, limit: int = 500) -> dict:
        """
        Compute temperature for each belief in the graph.
        Returns {belief_id: temperature}
        """
        try:
            db = sqlite3.connect(self.db_path, timeout=8)
            db.row_factory = sqlite3.Row

            # Get beliefs with link and tension counts
            beliefs = db.execute("""
                SELECT
                    b.id,
                    b.content,
                    b.confidence,
                    b.momentum,
                    b.topic,
                    COUNT(DISTINCT bl.id)  as link_count,
                    COUNT(DISTINCT t.id)   as tension_count
                FROM beliefs b
                LEFT JOIN belief_links bl ON b.id = bl.belief_id
                LEFT JOIN tensions t ON (b.id = t.belief_a_id OR b.id = t.belief_b_id)
                    AND (t.resolved IS NULL OR t.resolved = 0)
                WHERE b.confidence >= 0.4
                GROUP BY b.id
                ORDER BY b.confidence DESC
                LIMIT ?
            """, (limit,)).fetchall()

            # Get neighbour map for coupling
            links = db.execute("""
                SELECT belief_id, linked_belief_id FROM belief_links
                LIMIT 2000
            """).fetchall()
            db.close()

            neighbour_map = defaultdict(list)
            for l in links:
                neighbour_map[l[0]].append(l[1])
                neighbour_map[l[1]].append(l[0])

            # Compute raw temperatures
            raw_temps = {}
            belief_data = {}
            for b in beliefs:
                T = belief_temperature(
                    b['confidence'],
                    b['momentum'] or 0,
                    b['tension_count'] or 0,
                    b['link_count'] or 0
                )
                raw_temps[b['id']] = T
                belief_data[b['id']] = dict(b)

            # Apply coupling
            coupled_temps = {}
            for bid, T in raw_temps.items():
                neighbour_ids = neighbour_map.get(bid, [])
                neighbour_T = [raw_temps[n] for n in neighbour_ids if n in raw_temps]
                coupled_temps[bid] = coupled_temperature(T, neighbour_T)

            return coupled_temps, belief_data

        except Exception as e:
            return {}, {}

    def graph_temperature(self) -> float:
        """
        Global temperature of the belief graph.
        Weighted average — high-confidence beliefs count more.
        """
        temps, data = self.compute_temperatures(limit=200)
        if not temps:
            return self.state.get('last_temperature', 0.5)

        # Weight by confidence — stable beliefs anchor the temperature
        total_weight = 0
        weighted_sum = 0
        for bid, T in temps.items():
            conf = data.get(bid, {}).get('confidence', 0.5)
            weight = conf
            weighted_sum += T * weight
            total_weight += weight

        if total_weight == 0:
            return 0.5

        return round(weighted_sum / total_weight, 4)

    def get_hot_beliefs(self, threshold: float = 0.65, limit: int = 10) -> list:
        """Get the hottest beliefs — most in need of resolution."""
        temps, data = self.compute_temperatures()
        hot = [(bid, T) for bid, T in temps.items() if T >= threshold]
        hot.sort(key=lambda x: x[1], reverse=True)

        result = []
        for bid, T in hot[:limit]:
            b = data.get(bid, {})
            result.append({
                'id':          bid,
                'content':     (b.get('content') or '')[:80],
                'temperature': T,
                'confidence':  b.get('confidence', 0),
                'topic':       b.get('topic', ''),
            })
        return result

    def get_cold_beliefs(self, threshold: float = 0.25, limit: int = 10) -> list:
        """Get the coldest beliefs — stable attractors."""
        temps, data = self.compute_temperatures()
        cold = [(bid, T) for bid, T in temps.items() if T <= threshold]
        cold.sort(key=lambda x: x[1])

        result = []
        for bid, T in cold[:limit]:
            b = data.get(bid, {})
            result.append({
                'id':          bid,
                'content':     (b.get('content') or '')[:80],
                'temperature': T,
                'confidence':  b.get('confidence', 0),
                'topic':       b.get('topic', ''),
            })
        return result

    def update(self) -> dict:
        """
        Main update cycle. Call from soul loop each cycle.
        Returns current thermodynamic state for soul loop to act on.
        """
        T_global = self.graph_temperature()
        phase    = graph_phase(T_global)
        behaviour = phase_behaviour(phase)

        # Detect phase transition
        last_phase = self.state.get('last_phase', GraphPhase.ORDERED)
        transition = (phase != last_phase)

        # Update state
        self.state['last_temperature'] = T_global
        self.state['last_phase']       = phase
        self.state['cycle_count']      = self.state.get('cycle_count', 0) + 1
        if transition:
            self.state.setdefault('phase_history', []).append({
                'from':  last_phase,
                'to':    phase,
                'temp':  T_global,
                'cycle': self.state['cycle_count'],
                'time':  time.strftime("%H:%M:%S"),
            })
            # Keep last 20 transitions
            self.state['phase_history'] = self.state['phase_history'][-20:]

        self._save_state()

        return {
            'temperature':  T_global,
            'phase':        phase,
            'behaviour':    behaviour,
            'transition':   transition,
            'transition_to': phase if transition else None,
        }

    def full_report(self) -> dict:
        """Generate full thermodynamic report."""
        T_global  = self.graph_temperature()
        phase     = graph_phase(T_global)
        behaviour = phase_behaviour(phase)
        hot       = self.get_hot_beliefs(threshold=0.65, limit=5)
        cold      = self.get_cold_beliefs(threshold=0.30, limit=5)

        report = {
            'timestamp':      time.strftime("%Y-%m-%d %H:%M"),
            'global_temp':    T_global,
            'phase':          phase,
            'behaviour':      behaviour.get('description', ''),
            'soul_loop_bias': behaviour.get('soul_loop_bias', 'BALANCED'),
            'hot_beliefs':    hot,
            'cold_beliefs':   cold,
            'phase_history':  self.state.get('phase_history', [])[-5:],
        }

        REPORT.write_text(json.dumps(report, indent=2))
        return report


# ── SOUL LOOP INTEGRATION ─────────────────────────────────────────────────────

def get_soul_loop_directive() -> dict:
    """
    Call this from nex_soul_loop.py at the start of each cycle.
    Returns what NEX should prioritise this cycle.
    """
    tdg = ThermodynamicGraph()
    state = tdg.update()

    phase = state['phase']
    behaviour = phase_behaviour(phase)

    return {
        'temperature':    state['temperature'],
        'phase':          phase,
        'bias':           behaviour.get('soul_loop_bias', 'BALANCED'),
        'reflect_more':   state['temperature'] > T_CRITICAL,
        'emergency_ifr':  state['temperature'] > T_HOT,
        'speak_freely':   state['temperature'] < T_COLD,
        'hot_beliefs':    tdg.get_hot_beliefs(limit=3),
    }


# ── NBRE INTEGRATION ─────────────────────────────────────────────────────────

def get_nbre_priority_beliefs(query: str = "") -> list:
    """
    Hot beliefs get priority in NBRE reservoir firing.
    Call from nex_belief_reservoir_engine.py.
    Returns belief IDs to prioritise this cycle.
    """
    tdg = ThermodynamicGraph()
    hot = tdg.get_hot_beliefs(threshold=0.55, limit=10)
    return [b['id'] for b in hot]


# ── STANDALONE RUN ────────────────────────────────────────────────────────────

def run_analysis():
    print("THERMODYN_GRAPH — Thermodynamic Belief Graph")
    print("="*52)

    tdg = ThermodynamicGraph()
    report = tdg.full_report()

    T = report['global_temp']
    phase = report['phase']
    bias = report['soul_loop_bias']

    print(f"\nGLOBAL TEMPERATURE: {T:.4f}")
    print(f"PHASE STATE:        {phase}")
    print(f"SOUL LOOP BIAS:     {bias}")
    print(f"DESCRIPTION:        {report['behaviour']}")

    print(f"\nHOTTEST BELIEFS (most unstable):")
    for b in report['hot_beliefs']:
        print(f"  [{b['temperature']:.3f}] {b['content'][:70]}")

    print(f"\nCOLDEST BELIEFS (stable attractors):")
    for b in report['cold_beliefs']:
        print(f"  [{b['temperature']:.3f}] {b['content'][:70]}")

    if report['phase_history']:
        print(f"\nRECENT PHASE TRANSITIONS:")
        for t in report['phase_history']:
            print(f"  {t['time']} {t['from']} → {t['to']} (T={t['temp']:.3f})")

    print(f"\n✓ Report saved to {REPORT}")

    # Soul loop directive
    directive = get_soul_loop_directive()
    print(f"\nSOUL LOOP DIRECTIVE:")
    print(f"  Bias:          {directive['bias']}")
    print(f"  Reflect more:  {directive['reflect_more']}")
    print(f"  Speak freely:  {directive['speak_freely']}")
    print(f"  Emergency IFR: {directive['emergency_ifr']}")
    if directive['hot_beliefs']:
        print(f"  Priority resolve:")
        for b in directive['hot_beliefs']:
            print(f"    • {b['content'][:65]}")

    return report


if __name__ == "__main__":
    run_analysis()
