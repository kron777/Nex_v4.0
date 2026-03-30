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
