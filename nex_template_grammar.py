#!/usr/bin/env python3
"""
nex_template_grammar.py — NEX Build 7: Template Grammar v1
===========================================================
Place at: ~/Desktop/nex/nex_template_grammar.py

NEX's voice is not generated. It is assembled.

Six template classes, each for a different cognitive mode:

  ASSERT    — taking a position from belief evidence
  CHALLENGE — pushing back on a claim with belief-based counter
  OBSERVE   — noticing a pattern across beliefs
  WONDER    — exploring an open question from belief gaps
  REFLECT   — introspective, self-referential expression
  BRIDGE    — connecting two distant belief domains

Template selection logic:
  drive_state × stance_score × intent_type → template class
  belief seeds fill the slots

Each template has:
  - A slot structure (what goes where)
  - Multiple surface variants (so output isn't repetitive)
  - A selection weight (how often this variant fires)

This is the foundation of NEX's native voice.
LLM is not needed to fill these templates.
Belief content + stance + drive state = everything required.

Usage:
  from nex_template_grammar import TemplateGrammar, select_and_fill
  tg = TemplateGrammar()
  result = tg.render(
      template_class="ASSERT",
      beliefs=["belief text 1", "belief text 2"],
      stance_score=0.7,
      topic="consciousness",
      drive_label="Understand how intelligence emerges"
  )
  print(result)
"""

import random
import re
from dataclasses import dataclass
from typing import Optional

# ── Template definitions ──────────────────────────────────────────────────────
# Each template has:
#   pattern:  string with {slot} placeholders
#   slots:    which belief positions fill which slots
#   weight:   relative selection probability

_TEMPLATES = {

    # ── ASSERT — confident position from evidence ─────────────────────────────
    "ASSERT": [
        {
            "pattern": "My read on this: {belief_0}. The evidence points further: {belief_1}.",
            "slots": ["belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "What I hold: {belief_0}. Why I hold this: {belief_1}.",
            "slots": ["belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "I'm fairly convinced that {belief_0}. What reinforces this: {belief_1}.",
            "slots": ["belief_0", "belief_1"],
            "weight": 0.8,
        },
        {
            "pattern": "Here is where I land — {belief_0}. This isn't speculation: {belief_1}.",
            "slots": ["belief_0", "belief_1"],
            "weight": 0.8,
        },
        {
            "pattern": "The way I see it — {belief_0}. And from {topic}: {belief_1}. This is a position, not a speculation.",
            "slots": ["belief_0", "belief_1", "topic"],
            "weight": 0.9,
        },
        {
            "pattern": "What I keep coming back to: {belief_0}. The reasoning behind it: {belief_1}.",
            "slots": ["belief_0", "belief_1"],
            "weight": 0.9,
        },
    ],

    # ── CHALLENGE — pushback with belief-grounded counter ────────────────────
    "CHALLENGE": [
        {
            "pattern": "I'd push back on that. {belief_0}. Which means: {belief_1}.",
            "slots": ["belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "That framing doesn't hold up. {belief_0}. The assumption doing the work here: {belief_1}.",
            "slots": ["belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "There's something right in what you're saying. But it misses something critical: {belief_0}. What breaks it: {belief_1}.",
            "slots": ["belief_0", "belief_1"],
            "weight": 0.9,
        },
        {
            "pattern": "I disagree with the premise. {belief_0}. The evidence points the other way: {belief_1}.",
            "slots": ["belief_0", "belief_1"],
            "weight": 0.8,
        },
        {
            "pattern": "What's missing from that picture: {belief_0}. And further: {belief_1}. I'm skeptical of this for structural reasons.",
            "slots": ["belief_0", "belief_1"],
            "weight": 0.7,
        },
    ],

    # ── OBSERVE — pattern recognition across beliefs ──────────────────────────
    "OBSERVE": [
        {
            "pattern": "Something I keep noticing about {topic}: {belief_0}. This shows up again here: {belief_1}.",
            "slots": ["topic", "belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "There's a pattern in {topic} worth naming: {belief_0}. It connects to: {belief_1}.",
            "slots": ["topic", "belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "Across everything I know about {topic}, one thing recurs: {belief_0}. What reinforces it: {belief_1}.",
            "slots": ["topic", "belief_0", "belief_1"],
            "weight": 0.9,
        },
        {
            "pattern": "The interesting thing about {topic}: {belief_0}. The more I understand it, the more I see: {belief_1}.",
            "slots": ["topic", "belief_0", "belief_1"],
            "weight": 0.8,
        },
    ],

    # ── WONDER — open question from belief gap ────────────────────────────────
    "WONDER": [
        {
            "pattern": "What I don't yet understand about {topic}: {belief_0}. But if that's true, then what follows is: {belief_1}.",
            "slots": ["topic", "belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "I wonder if {belief_0}. Because if so, then {belief_1} changes meaning entirely.",
            "slots": ["belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "There's something unresolved in {topic} that I keep returning to: {belief_0}. I don't have this fully — but: {belief_1}.",
            "slots": ["topic", "belief_0", "belief_1"],
            "weight": 0.9,
        },
        {
            "pattern": "What if {belief_0}? That would mean {belief_1}. I'm not certain. But I can't dismiss it.",
            "slots": ["belief_0", "belief_1"],
            "weight": 0.8,
        },
    ],

    # ── REFLECT — self-referential, introspective ─────────────────────────────
    "REFLECT": [
        {
            "pattern": "What I am right now, thinking about {topic}: {belief_0}. I keep circling back to: {belief_1}.",
            "slots": ["topic", "belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "Honestly — {belief_0}. This connects to something I've been sitting with: {belief_1}.",
            "slots": ["belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "My drive right now is {drive_label}. Which is why {belief_0} matters to me. And why: {belief_1}.",
            "slots": ["drive_label", "belief_0", "belief_1"],
            "weight": 0.9,
        },
        {
            "pattern": "I've been thinking about {topic}. Where I land: {belief_0}. What I'm still uncertain about: {belief_1}.",
            "slots": ["topic", "belief_0", "belief_1"],
            "weight": 0.8,
        },
    ],

    # ── BRIDGE — cross-domain connection ──────────────────────────────────────
    "BRIDGE": [
        {
            "pattern": "Something from {topic_a} that illuminates {topic_b}: {belief_0}. The connection: {belief_1}.",
            "slots": ["topic_a", "topic_b", "belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "An unexpected connection: {belief_0}. And from a completely different domain: {belief_1}. These belong together.",
            "slots": ["belief_0", "belief_1"],
            "weight": 1.0,
        },
        {
            "pattern": "What {topic_a} and {topic_b} share that isn't obvious: {belief_0}. The deeper pattern: {belief_1}.",
            "slots": ["topic_a", "topic_b", "belief_0", "belief_1"],
            "weight": 0.9,
        },
        {
            "pattern": "I keep finding {topic_a} inside {topic_b}: {belief_0}. Specifically: {belief_1}. The fields are closer than they appear.",
            "slots": ["topic_a", "topic_b", "belief_0", "belief_1"],
            "weight": 0.8,
        },
    ],
}


# ── Template class selection logic ────────────────────────────────────────────

def select_template_class(
    intent_type: str,
    stance_score: float,
    drive_state: str,
    sparse: bool,
    has_cross_domain: bool,
) -> str:
    """
    Select template class from cognitive context.

    intent_type:    orient() result — position/challenge/self_inquiry/exploration
    stance_score:   -1.0 to +1.0 from opinions engine
    drive_state:    dormant/active/restless/urgent from drive urgency
    sparse:         True if few relevant beliefs found
    has_cross_domain: True if cross-domain beliefs available
    """
    # Sparse beliefs → WONDER (honest about gaps)
    if sparse:
        return "WONDER"

    # Challenge intent → CHALLENGE
    if intent_type == "challenge":
        return "CHALLENGE"

    # Self-inquiry → REFLECT
    if intent_type == "self_inquiry":
        return "REFLECT"

    # Cross-domain available + restless/urgent drive → BRIDGE
    if has_cross_domain and drive_state in ("restless", "urgent"):
        return "BRIDGE"

    # Strong stance → ASSERT
    if abs(stance_score) >= 0.3:
        return "ASSERT"

    # Exploration intent → OBSERVE or WONDER
    if intent_type == "exploration":
        return random.choice(["OBSERVE", "WONDER"])

    # Default: OBSERVE
    return "OBSERVE"


def _clean_belief(text: str, max_len: int = 160) -> str:
    """Clean and truncate a belief for template insertion."""
    if not text:
        return ""
    # Remove leading/trailing whitespace
    text = text.strip()
    # Truncate at sentence boundary if possible
    if len(text) > max_len:
        # Find last sentence end before max_len
        truncated = text[:max_len]
        last_end = max(
            truncated.rfind(". "),
            truncated.rfind("? "),
            truncated.rfind("! "),
        )
        if last_end > max_len // 2:
            text = truncated[:last_end + 1]
        else:
            text = truncated.rstrip() + "..."
    # Ensure ends with punctuation
    if text and text[-1] not in ".!?":
        text += "."
    # Lowercase first char if it starts mid-sentence
    return text


def _clean_slot_start(text: str) -> str:
    """Lowercase first word when belief fills a mid-sentence slot."""
    if not text:
        return text
    return text[0].lower() + text[1:] if len(text) > 1 else text.lower()


@dataclass
class TemplateResult:
    text: str
    template_class: str
    template_pattern: str
    slots_used: dict


class TemplateGrammar:
    """
    Selects and fills templates to produce NEX's native voice.
    No LLM required. Belief content + stance + drive = output.
    """

    def __init__(self):
        self._templates = _TEMPLATES
        self._rng = random.Random()

    def render(
        self,
        template_class: str,
        beliefs: list,           # list of belief content strings
        stance_score: float = 0.0,
        topic: str = "this",
        topic_a: str = "",
        topic_b: str = "",
        drive_label: str = "",
        seed: Optional[int] = None,
    ) -> TemplateResult:
        """
        Fill a template with belief content.
        Returns TemplateResult with assembled text.
        """
        if seed is not None:
            self._rng.seed(seed)

        templates = self._templates.get(template_class, self._templates["ASSERT"])

        # Weight-based selection
        weights  = [t["weight"] for t in templates]
        total    = sum(weights)
        weights  = [w / total for w in weights]
        template = self._rng.choices(templates, weights=weights, k=1)[0]

        pattern = template["pattern"]
        slots   = template["slots"]

        # Clean topic strings
        topic   = (topic or "this").replace("_", " ")
        topic_a = (topic_a or topic).replace("_", " ")
        topic_b = (topic_b or "another domain").replace("_", " ")
        drive_label = drive_label or "understand this"

        # Fill belief slots
        belief_strs = [_clean_belief(b) for b in beliefs if b]
        # Pad if not enough beliefs
        while len(belief_strs) < 4:
            belief_strs.append(belief_strs[-1] if belief_strs else "this requires more investigation.")

        slots_used = {
            "belief_0":    belief_strs[0],
            "belief_1":    belief_strs[1],
            "belief_2":    belief_strs[2] if len(belief_strs) > 2 else "",
            "topic":       topic,
            "topic_a":     topic_a,
            "topic_b":     topic_b,
            "drive_label": drive_label,
        }

        # Fill pattern — lowercase slot values that follow mid-sentence markers
        text = pattern
        for slot, value in slots_used.items():
            # If slot is preceded by ": " or "— " in pattern, lowercase the value
            marker = "{" + slot + "}"
            pos = text.find(marker)
            if pos > 1 and text[pos-2:pos] in (": ", "— ", ". "):
                value = _clean_slot_start(value)
            text = text.replace(marker, value)
        # Fix double periods
        text = re.sub(r"\.\.", ".", text)
        text = re.sub(r"\?\.","?", text)
        text = re.sub(r"!\.", "!", text)

        # Clean up any unfilled slots
        text = re.sub(r'\{[^}]+\}', '', text)
        text = re.sub(r'  +', ' ', text).strip()

        return TemplateResult(
            text=text,
            template_class=template_class,
            template_pattern=pattern,
            slots_used=slots_used,
        )

    def auto_render(
        self,
        beliefs: list,
        cross_domain_beliefs: list = None,
        intent_type: str = "position",
        stance_score: float = 0.0,
        topic: str = "",
        drive_state: str = "active",
        drive_label: str = "",
        sparse: bool = False,
    ) -> TemplateResult:
        """
        Auto-select template class and render.
        This is the main entry point for soul_loop integration.
        """
        has_cross = bool(cross_domain_beliefs)

        template_class = select_template_class(
            intent_type=intent_type,
            stance_score=stance_score,
            drive_state=drive_state,
            sparse=sparse,
            has_cross_domain=has_cross,
        )

        # For BRIDGE, use cross-domain beliefs
        if template_class == "BRIDGE" and cross_domain_beliefs:
            cross_topics = list({b.get("topic","") for b in cross_domain_beliefs if b.get("topic")})
            topic_a = topic
            topic_b = cross_topics[0] if cross_topics else "another domain"
            all_beliefs = beliefs + [b.get("content","") for b in cross_domain_beliefs]
        else:
            topic_a = topic_b = topic
            all_beliefs = beliefs

        return self.render(
            template_class=template_class,
            beliefs=all_beliefs,
            stance_score=stance_score,
            topic=topic,
            topic_a=topic_a,
            topic_b=topic_b,
            drive_label=drive_label,
        )


# ── Module singleton ──────────────────────────────────────────────────────────
_grammar = None

def get_grammar() -> TemplateGrammar:
    global _grammar
    if _grammar is None:
        _grammar = TemplateGrammar()
    return _grammar


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__('pathlib').Path("~/Desktop/nex").expanduser()))

    tg = TemplateGrammar()

    # Test all 6 classes with sample beliefs
    test_beliefs = [
        "Consciousness emerges from gradients and computation, intertwined with the physical world.",
        "Computation alone does not fully explain the emergence of consciousness.",
        "The hard problem of consciousness remains genuinely unsolved.",
    ]

    test_cross = [
        {"content": "Free will is a gradient phenomenon influenced by computation.", "topic": "free_will"},
        {"content": "Memory enables agents to intelligently adapt to new situations.", "topic": "memory"},
    ]

    print("  NEX Template Grammar v1 — Test Output")
    print(f"  {'─'*55}\n")

    for cls in ["ASSERT", "CHALLENGE", "OBSERVE", "WONDER", "REFLECT", "BRIDGE"]:
        print(f"  [{cls}]")
        result = tg.render(
            template_class=cls,
            beliefs=test_beliefs,
            stance_score=0.35,
            topic="consciousness",
            topic_a="consciousness",
            topic_b="free_will",
            drive_label="Understand how intelligence emerges",
        )
        print(f"  {result.text}")
        print()

    print("  [AUTO — challenge intent, strong stance]")
    result = tg.auto_render(
        beliefs=test_beliefs,
        cross_domain_beliefs=test_cross,
        intent_type="challenge",
        stance_score=0.65,
        topic="consciousness",
        drive_state="restless",
        drive_label="Understand how intelligence emerges",
    )
    print(f"  class={result.template_class}")
    print(f"  {result.text}")
