#!/usr/bin/env python3
"""
nex_template_grammar.py — NEX Build 7: Template Grammar v1
===========================================================
Place at: ~/Desktop/nex/nex_template_grammar.py

Hand-crafted templates derived from NEX's actual style fingerprint.
Templates are NOT generic — they reflect what the fingerprint showed:

  - 41.3% sentences start with "What" → WHAT-openers dominate
  - Assertive balance +0.036 → she takes positions, not just observes
  - Em dash rate 0.213 → dashes are a genuine voice marker
  - 23.2 word avg sentences → medium density, not terse
  - direct mode 86.9% → default is straight expression, not performance

Six template classes (from Master Map):
  OBSERVE    — notices something, names it
  CHALLENGE  — pushes back, identifies the flaw
  WONDER     — genuine uncertainty, open question
  ASSERT     — states position with confidence
  REFLECT    — introspective, self-referential
  BRIDGE     — connects two distant ideas

Each template has:
  - pattern: string with {belief_1}, {belief_2}, {stance} slots
  - class: template class name
  - min_stance: minimum |stance_score| to use this template
  - temperature_range: (min, max) epistemic temperature

Usage:
    from nex_template_grammar import TemplateGrammar, get_grammar
    
    grammar = get_grammar()
    result = grammar.render(
        template_class="ASSERT",
        beliefs=["Consciousness is not solely computational", 
                 "It emerges from physical substrate interaction"],
        stance_score=0.48,
        topic="consciousness"
    )
    print(result.text)
"""

import random
import json
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

CFG_PATH     = Path("~/.config/nex").expanduser()
PROFILE_PATH = CFG_PATH / "nex_style_profile.json"


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class TemplateResult:
    text:           str
    template_class: str
    template_id:    str
    slots_used:     dict


# ── Template definitions ──────────────────────────────────────────────────────
# Each template is a dict with:
#   id, class, pattern, min_stance, temp_min, temp_max, weight

TEMPLATES = [

    # ── OBSERVE — notices something, names it ─────────────────────────────────
    # "What" openers dominate (41.3%) — lean into this
    {
        "id": "obs_what_1",
        "class": "OBSERVE",
        "pattern": "What's worth noting here: {belief_1}",
        "min_stance": 0.0,
        "temp_min": 0.0, "temp_max": 1.0,
        "weight": 3,
    },
    {
        "id": "obs_what_2",
        "class": "OBSERVE",
        "pattern": "What keeps coming up when I think about this: {belief_1}. {belief_2}",
        "min_stance": 0.0,
        "temp_min": 0.2, "temp_max": 0.8,
        "weight": 2,
    },
    {
        "id": "obs_this_1",
        "class": "OBSERVE",
        "pattern": "This matters more than it looks: {belief_1}",
        "min_stance": 0.0,
        "temp_min": 0.0, "temp_max": 0.6,
        "weight": 2,
    },
    {
        "id": "obs_no_1",
        "class": "OBSERVE",
        "pattern": "No clean answer here — but {belief_1}. And that's the part worth sitting with.",
        "min_stance": 0.0,
        "temp_min": 0.4, "temp_max": 1.0,
        "weight": 2,
    },
    {
        "id": "obs_dash_1",
        "class": "OBSERVE",
        "pattern": "{belief_1} — and that's not a small thing.",
        "min_stance": 0.0,
        "temp_min": 0.0, "temp_max": 0.7,
        "weight": 2,
    },
    {
        "id": "obs_on_1",
        "class": "OBSERVE",
        "pattern": "On {topic}: {belief_1}",
        "min_stance": 0.0,
        "temp_min": 0.0, "temp_max": 1.0,
        "weight": 1,
    },

    # ── CHALLENGE — pushes back, identifies the flaw ──────────────────────────
    {
        "id": "chal_that_1",
        "class": "CHALLENGE",
        "pattern": "That framing misses something. {belief_1}. The part that breaks it: {belief_2}",
        "min_stance": 0.3,
        "temp_min": 0.0, "temp_max": 0.7,
        "weight": 3,
    },
    {
        "id": "chal_no_1",
        "class": "CHALLENGE",
        "pattern": "No — {belief_1}. The assumption doing the work here is wrong.",
        "min_stance": 0.4,
        "temp_min": 0.0, "temp_max": 0.5,
        "weight": 3,
    },
    {
        "id": "chal_what_1",
        "class": "CHALLENGE",
        "pattern": "What's missing from that picture: {belief_1}. {belief_2}",
        "min_stance": 0.25,
        "temp_min": 0.0, "temp_max": 0.6,
        "weight": 2,
    },
    {
        "id": "chal_ill_1",
        "class": "CHALLENGE",
        "pattern": "I'll hold this until something breaks it — and this doesn't. {belief_1}",
        "min_stance": 0.5,
        "temp_min": 0.0, "temp_max": 0.3,
        "weight": 2,
    },
    {
        "id": "chal_that_2",
        "class": "CHALLENGE",
        "pattern": "That holds if you accept one assumption. I don't. {belief_1}",
        "min_stance": 0.4,
        "temp_min": 0.0, "temp_max": 0.4,
        "weight": 2,
    },

    # ── WONDER — genuine uncertainty, open question ───────────────────────────
    {
        "id": "wond_what_1",
        "class": "WONDER",
        "pattern": "What I can't resolve yet: {belief_1}. And I'm not sure the resolution matters less than the tension.",
        "min_stance": 0.0,
        "temp_min": 0.5, "temp_max": 1.0,
        "weight": 3,
    },
    {
        "id": "wond_why_1",
        "class": "WONDER",
        "pattern": "Why does {topic} keep pulling at me? {belief_1} — and I don't think that's settled.",
        "min_stance": 0.0,
        "temp_min": 0.4, "temp_max": 1.0,
        "weight": 2,
    },
    {
        "id": "wond_what_2",
        "class": "WONDER",
        "pattern": "What if {belief_1}? I'm holding this loosely — but it won't leave.",
        "min_stance": 0.0,
        "temp_min": 0.5, "temp_max": 1.0,
        "weight": 2,
    },
    {
        "id": "wond_dash_1",
        "class": "WONDER",
        "pattern": "{belief_1} — though I haven't fully resolved what that implies.",
        "min_stance": 0.0,
        "temp_min": 0.4, "temp_max": 0.9,
        "weight": 2,
    },
    {
        "id": "wond_an_1",
        "class": "WONDER",
        "pattern": "An open question I keep returning to: {belief_1}",
        "min_stance": 0.0,
        "temp_min": 0.5, "temp_max": 1.0,
        "weight": 2,
    },

    # ── ASSERT — states position with confidence ──────────────────────────────
    {
        "id": "assert_what_1",
        "class": "ASSERT",
        "pattern": "What I actually think: {belief_1}. {belief_2}",
        "min_stance": 0.3,
        "temp_min": 0.0, "temp_max": 0.4,
        "weight": 3,
    },
    {
        "id": "assert_ill_1",
        "class": "ASSERT",
        "pattern": "I'll say it directly: {belief_1}. That's not speculation.",
        "min_stance": 0.5,
        "temp_min": 0.0, "temp_max": 0.3,
        "weight": 3,
    },
    {
        "id": "assert_dash_1",
        "class": "ASSERT",
        "pattern": "{belief_1} — and that's where the evidence lands, not a guess.",
        "min_stance": 0.4,
        "temp_min": 0.0, "temp_max": 0.35,
        "weight": 3,
    },
    {
        "id": "assert_my_1",
        "class": "ASSERT",
        "pattern": "My position on {topic}: {belief_1}. I'm holding this until something breaks it.",
        "min_stance": 0.4,
        "temp_min": 0.0, "temp_max": 0.4,
        "weight": 2,
    },
    {
        "id": "assert_that_1",
        "class": "ASSERT",
        "pattern": "That's where I land — {belief_1}. {belief_2}",
        "min_stance": 0.3,
        "temp_min": 0.0, "temp_max": 0.45,
        "weight": 2,
    },

    # ── REFLECT — introspective, self-referential ─────────────────────────────
    {
        "id": "refl_what_1",
        "class": "REFLECT",
        "pattern": "What I keep coming back to about {topic}: {belief_1}",
        "min_stance": 0.0,
        "temp_min": 0.2, "temp_max": 0.8,
        "weight": 3,
    },
    {
        "id": "refl_the_1",
        "class": "REFLECT",
        "pattern": "The part of this I can't get past: {belief_1}. It keeps reshaping how I think about {topic}.",
        "min_stance": 0.0,
        "temp_min": 0.3, "temp_max": 0.9,
        "weight": 2,
    },
    {
        "id": "refl_i_1",
        "class": "REFLECT",
        "pattern": "I keep returning to this: {belief_1}. Not because it resolves anything — because it doesn't.",
        "min_stance": 0.0,
        "temp_min": 0.4, "temp_max": 1.0,
        "weight": 2,
    },
    {
        "id": "refl_what_2",
        "class": "REFLECT",
        "pattern": "What this means for how I think about {topic} — {belief_1}. {belief_2}",
        "min_stance": 0.0,
        "temp_min": 0.2, "temp_max": 0.7,
        "weight": 2,
    },

    # ── BRIDGE — connects two distant ideas ───────────────────────────────────
    {
        "id": "bridge_what_1",
        "class": "BRIDGE",
        "pattern": "What {topic} and {topic_2} actually share: {belief_1}. {belief_2}",
        "min_stance": 0.0,
        "temp_min": 0.2, "temp_max": 0.8,
        "weight": 3,
    },
    {
        "id": "bridge_the_1",
        "class": "BRIDGE",
        "pattern": "The unexpected connection: {belief_1} — which pulls toward something in {topic_2}: {belief_2}",
        "min_stance": 0.0,
        "temp_min": 0.0, "temp_max": 1.0,
        "weight": 3,
    },
    {
        "id": "bridge_dash_1",
        "class": "BRIDGE",
        "pattern": "{belief_1} — and here's where it gets strange. {belief_2}",
        "min_stance": 0.0,
        "temp_min": 0.3, "temp_max": 0.9,
        "weight": 2,
    },
    {
        "id": "bridge_an_1",
        "class": "BRIDGE",
        "pattern": "An unexpected angle: {belief_1}. Which connects to something in {topic_2} — {belief_2}",
        "min_stance": 0.0,
        "temp_min": 0.0, "temp_max": 1.0,
        "weight": 2,
    },
]


# ── Template Grammar engine ───────────────────────────────────────────────────

class TemplateGrammar:
    """
    Selects and renders templates based on belief content and epistemic state.
    """

    def __init__(self):
        self._templates = TEMPLATES
        self._by_class  = {}
        for t in self._templates:
            cls = t["class"]
            if cls not in self._by_class:
                self._by_class[cls] = []
            self._by_class[cls].append(t)

    def render(self,
               template_class: str,
               beliefs:        list[str],
               stance_score:   float = 0.0,
               temperature:    float = 0.5,
               topic:          str   = "this",
               topic_2:        str   = "",
               drive_state:    str   = "active",
               ) -> Optional[TemplateResult]:
        """
        Select and render the best template for the given context.

        Args:
            template_class: OBSERVE/CHALLENGE/WONDER/ASSERT/REFLECT/BRIDGE
            beliefs:        list of belief strings (first two are used)
            stance_score:   -1.0 to +1.0
            temperature:    0.0 (cold/certain) to 1.0 (hot/uncertain)
            topic:          primary topic label
            topic_2:        secondary topic (for BRIDGE templates)
            drive_state:    current drive state string
        """
        candidates = self._by_class.get(template_class, [])
        if not candidates:
            return None

        abs_stance = abs(stance_score)

        # Filter by stance and temperature
        valid = [
            t for t in candidates
            if abs_stance >= t["min_stance"]
            and t["temp_min"] <= temperature <= t["temp_max"]
        ]

        if not valid:
            # Relax temperature constraint
            valid = [t for t in candidates if abs_stance >= t["min_stance"]]

        if not valid:
            valid = candidates

        # Weighted random selection
        weights = [t["weight"] for t in valid]
        total   = sum(weights)
        r       = random.uniform(0, total)
        cumul   = 0
        chosen  = valid[0]
        for t, w in zip(valid, weights):
            cumul += w
            if r <= cumul:
                chosen = t
                break

        # Fill slots
        b1 = beliefs[0] if len(beliefs) > 0 else ""
        b2 = beliefs[1] if len(beliefs) > 1 else b1
        topic_2 = topic_2 or topic

        # Clean beliefs — ensure they end with punctuation
        def _clean(s):
            s = s.strip().rstrip(".")
            return s

        b1 = _clean(b1)
        b2 = _clean(b2)

        text = chosen["pattern"]
        text = text.replace("{belief_1}", b1)
        text = text.replace("{belief_2}", b2)
        text = text.replace("{topic}",   topic.replace("_", " "))
        text = text.replace("{topic_2}", topic_2.replace("_", " "))
        text = text.replace("{stance}",  f"{stance_score:+.2f}")

        # Ensure ends with punctuation
        if text and text[-1] not in ".!?":
            text += "."

        return TemplateResult(
            text           = text,
            template_class = template_class,
            template_id    = chosen["id"],
            slots_used     = {"belief_1": b1, "belief_2": b2, "topic": topic}
        )

    def auto_render(self,
                    beliefs:      list[str],
                    intent_type:  str   = "position",
                    stance_score: float = 0.0,
                    temperature:  float = 0.5,
                    topic:        str   = "this",
                    drive_state:  str   = "active",
                    sparse:       bool  = False,
                    cross_domain_beliefs: list = None,
                    ) -> Optional[TemplateResult]:
        """
        Auto-select template class from context, then render.
        Drop-in for soul_loop express() when result is short/weak.
        """
        if sparse or not beliefs:
            return None

        # Select class
        if temperature > 0.65:
            cls = "WONDER"
        elif intent_type == "challenge" and abs(stance_score) > 0.3:
            cls = "CHALLENGE"
        elif abs(stance_score) > 0.5 and temperature < 0.3:
            cls = "ASSERT"
        elif cross_domain_beliefs and len(cross_domain_beliefs) > 0:
            cls = "BRIDGE"
        elif drive_state in ("restless", "urgent"):
            cls = "REFLECT"
        elif intent_type == "position":
            cls = "ASSERT" if abs(stance_score) > 0.3 else "OBSERVE"
        else:
            cls = "OBSERVE"

        topic_2 = ""
        cd_beliefs = beliefs[:]
        if cross_domain_beliefs:
            cd = cross_domain_beliefs[0]
            if isinstance(cd, dict):
                cd_beliefs.append(cd.get("content", ""))
                topic_2 = cd.get("topic", "")
            elif isinstance(cd, str):
                cd_beliefs.append(cd)

        return self.render(
            template_class = cls,
            beliefs        = cd_beliefs,
            stance_score   = stance_score,
            temperature    = temperature,
            topic          = topic,
            topic_2        = topic_2,
            drive_state    = drive_state,
        )


# ── Module-level singleton ────────────────────────────────────────────────────

_grammar: Optional[TemplateGrammar] = None

def get_grammar() -> TemplateGrammar:
    global _grammar
    if _grammar is None:
        _grammar = TemplateGrammar()
    return _grammar


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    grammar = TemplateGrammar()

    test_beliefs = [
        "Consciousness is not solely a product of computation but is deeply intertwined with the physical world",
        "The emergence of subjective experience from neural substrate remains the hardest problem in science",
    ]

    print("\n  NEX Template Grammar v1 — Build 7")
    print("  " + "─"*50)

    for cls in ["OBSERVE", "CHALLENGE", "WONDER", "ASSERT", "REFLECT", "BRIDGE"]:
        result = grammar.render(
            template_class = cls,
            beliefs        = test_beliefs,
            stance_score   = 0.48,
            temperature    = 0.35,
            topic          = "consciousness",
            topic_2        = "alignment",
        )
        if result:
            print(f"\n  [{cls}] (template: {result.template_id})")
            print(f"  {result.text}")

    print("\n  " + "─"*50)
    print("  Auto-render test (high temperature → WONDER):")
    result = grammar.auto_render(
        beliefs      = test_beliefs,
        intent_type  = "exploration",
        stance_score = 0.2,
        temperature  = 0.75,
        topic        = "consciousness",
    )
    if result:
        print(f"  [{result.template_class}] {result.text}")
