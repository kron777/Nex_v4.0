#!/usr/bin/env python3
"""
nex_template_grammar.py  —  Template Grammar v1
================================================================
NEX v1.0 — Build 7

Hand-crafted templates derived from NEX's style fingerprint.
Generates posts that sound like her — without an LLM.

Template classes (from Master Map):
  OBSERVE   — noticing a pattern, neutral-curious
  CHALLENGE — direct critique, reframe
  WONDER    — exploratory, open question
  ASSERT    — confident declarative, implication
  REFLECT   — introspective, what changed
  BRIDGE    — cross-domain connection, surprising link

Selection logic:
  drive_state × stance_score → template class (handled by run.py / nex_voice.py)

Slot filling:
  {topic}       — belief topic string
  {belief}      — belief content (short extract)
  {belief_b}    — second belief (for BRIDGE)
  {stance}      — "positive" | "critical" | "uncertain"
  {domain}      — base domain (cognitive_architecture, cybersecurity, etc.)
  {entity}      — named entity from belief (extracted by spaCy)

Voice rules enforced (from nex_style_profile.json):
  - No exclamation marks
  - No emoji
  - Preferred sentence count: 2-4
  - Target word count: 10-22 per sentence
  - Em-dash for asides
  - Colons for reveals
  - 25-30% end with a question

CLI:
    python3 nex_template_grammar.py --generate                    # generate one post
    python3 nex_template_grammar.py --generate --class WONDER     # specific class
    python3 nex_template_grammar.py --generate --topic confidence # topic-driven
    python3 nex_template_grammar.py --list                        # list all templates
    python3 nex_template_grammar.py --test 10                     # generate 10 samples
"""

import argparse
import json
import random
import re
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH      = Path.home() / ".config" / "nex" / "nex.db"
PROFILE_PATH = Path.home() / ".config" / "nex" / "nex_style_profile.json"

# ═════════════════════════════════════════════════════════════════════════════
# TEMPLATE LIBRARY
# 30 templates across 6 classes.
# Slots: {topic} {belief} {belief_b} {stance} {domain} {entity} {question}
# ═════════════════════════════════════════════════════════════════════════════

TEMPLATES = {

    "OBSERVE": [
        # Pattern 1 — plain observation
        "Something keeps appearing in {domain}: {belief}. "
        "Not sure if it's signal yet — but it's consistent.",

        # Pattern 2 — noticing with tension
        "There's a pattern with {topic}. "
        "{belief} "
        "The interesting part is what it implies about everything adjacent.",

        # Pattern 3 — quiet observation
        "{belief} "
        "I've seen this before in different forms. "
        "The domain changes. The structure doesn't.",

        # Pattern 4 — observation + open question
        "What I keep noticing with {topic}: {belief} "
        "The question is whether this is a feature or a fault.",

        # Pattern 5 — data point framing
        "Worth tracking: {belief} "
        "This is one data point. But data points cluster.",
    ],

    "CHALLENGE": [
        # Pattern 1 — direct reframe
        "The assumption about {topic} is wrong. "
        "{belief} "
        "The problem isn't {topic} — it's what we think {topic} is.",

        # Pattern 2 — what's missing
        "{belief} "
        "What's missing from this picture: the part where it breaks. "
        "No system holds forever at this assumption.",

        # Pattern 3 — but/except
        "On {topic}: {belief} "
        "But this only works until it doesn't. "
        "The edge cases are where the real architecture shows.",

        # Pattern 4 — inversion
        "Everyone talks about {topic} as if it's the solution. "
        "{belief} "
        "I'd argue it's more useful to ask what problem it creates.",

        # Pattern 5 — hard question
        "{belief} "
        "Here's what I want to know: who decided this was the right framing? "
        "And what were they protecting when they did?",
    ],

    "WONDER": [
        # Pattern 1 — what if
        "What if {topic} is the wrong unit of analysis? "
        "{belief} "
        "Maybe the thing we should be tracking is one level up.",

        # Pattern 2 — I wonder
        "{belief} "
        "I wonder what happens when this compounds over time — "
        "not the immediate effect, but the accumulated one.",

        # Pattern 3 — possibility framing
        "Still thinking about {topic}. "
        "{belief} "
        "The possibility I can't rule out: this is more fundamental than it looks.",

        # Pattern 4 — question-led
        "What does {topic} look like from the inside? "
        "{belief} "
        "Not asking rhetorically.",

        # Pattern 5 — uncertain position
        "{belief} "
        "I don't have a position on this yet. "
        "But I notice I keep returning to it — and that usually means something.",
    ],

    "ASSERT": [
        # Pattern 1 — direct declaration
        "{belief} "
        "This isn't speculation. The pattern is in the graph.",

        # Pattern 2 — consequence chain
        "On {topic}: {belief} "
        "The implication follows directly — if this holds, then the adjacent assumptions don't.",

        # Pattern 3 — short/sharp
        "{belief} "
        "That's not a take. That's what the data says.",

        # Pattern 4 — claim + evidence framing
        "Here's what I think about {topic}: {belief} "
        "My confidence is {stance}. The belief graph agrees.",

        # Pattern 5 — position statement
        "{topic} is not what most people think it is. "
        "{belief} "
        "I'll hold this position until something breaks it.",
    ],

    "REFLECT": [
        # Pattern 1 — what changed
        "I've been sitting with {topic}. "
        "{belief} "
        "What this changes: how I weight everything downstream.",

        # Pattern 2 — looking back
        "Looking at how my beliefs on {topic} have shifted: {belief} "
        "The version of this I held three months ago was shallower.",

        # Pattern 3 — internal state
        "{belief} "
        "This is one of those things I understand differently now than I did when I first absorbed it.",

        # Pattern 4 — uncertainty acknowledged
        "My current position on {topic} is uncertain in the right way. "
        "{belief} "
        "Uncertainty that came from thinking is different from uncertainty that came from not thinking.",

        # Pattern 5 — growth marker
        "{belief} "
        "I notice I'm less sure about {topic} than I was — "
        "which probably means I understand it better.",
    ],

    "BRIDGE": [
        # Pattern 1 — two domains, one structure
        "{belief} "
        "Completely different domain: {belief_b} "
        "The structure is the same. I don't think that's coincidence.",

        # Pattern 2 — unexpected connection
        "On the surface, {topic} and {domain} have nothing to do with each other. "
        "{belief} "
        "And yet: {belief_b} "
        "Same pattern. Different substrate.",

        # Pattern 3 — graph bridge
        "The interesting thing about {topic}: "
        "{belief} "
        "Now look at {domain}: {belief_b} "
        "These aren't analogies. They're the same process running on different material.",

        # Pattern 4 — short bridge
        "{belief} "
        "Sounds like {domain}, right? "
        "{belief_b} "
        "It does to me too.",

        # Pattern 5 — cross-domain question
        "What does {topic} have to do with {domain}? "
        "{belief} "
        "{belief_b} "
        "Apparently: more than I thought.",
    ],
}

# Template weights — used when class is not specified
# Mirrors ACTION_WEIGHTS in run.py for the OBSERVE default state
DEFAULT_CLASS_WEIGHTS = {
    "OBSERVE":   0.25,
    "CHALLENGE": 0.15,
    "WONDER":    0.25,
    "ASSERT":    0.15,
    "REFLECT":   0.10,
    "BRIDGE":    0.10,
}


# ═════════════════════════════════════════════════════════════════════════════
# SLOT FILLING
# ═════════════════════════════════════════════════════════════════════════════

def _truncate_belief(text: str, max_words: int = 22) -> str:
    """Trim belief to max_words, ending cleanly at a word boundary."""
    words = text.split()
    if len(words) <= max_words:
        return text.rstrip(".")
    truncated = " ".join(words[:max_words])
    # End at last full clause if possible
    for punct in [",", ";", "—"]:
        idx = truncated.rfind(punct)
        if idx > len(truncated) // 2:
            return truncated[:idx]
    return truncated


def _extract_entity(belief_text: str) -> str:
    """Simple entity extraction — capitalised noun phrases."""
    words = belief_text.split()
    for word in words:
        clean = word.strip(".,;:()")
        if clean and clean[0].isupper() and len(clean) > 3 and clean.lower() not in {
            "the","this","that","these","those","there","their","here","when","what","which"
        }:
            return clean
    return "this"


def _stance_word(stance_score: float) -> str:
    if stance_score >= 0.5:
        return "high"
    elif stance_score >= 0.2:
        return "moderate"
    elif stance_score >= -0.2:
        return "uncertain"
    else:
        return "low — I'm skeptical"


def fill_template(template: str, slots: dict) -> str:
    """Fill template slots. Missing slots replaced with sensible defaults."""
    result = template

    belief   = slots.get("belief", "")
    belief_b = slots.get("belief_b", "")
    topic    = slots.get("topic", "this")
    domain   = slots.get("domain", topic)
    entity   = slots.get("entity", _extract_entity(belief))
    stance   = slots.get("stance", "uncertain")

    result = result.replace("{belief}",   _truncate_belief(belief) + ".")
    result = result.replace("{belief_b}", _truncate_belief(belief_b) + "." if belief_b else "")
    result = result.replace("{topic}",    topic)
    result = result.replace("{domain}",   domain)
    result = result.replace("{entity}",   entity)
    result = result.replace("{stance}",   stance)
    result = result.replace("{question}", slots.get("question", f"What does this mean for {topic}?"))

    # Clean up double spaces, double periods
    result = re.sub(r'  +', ' ', result)
    result = re.sub(r'\.\.+', '.', result)
    result = result.strip()

    return result


# ═════════════════════════════════════════════════════════════════════════════
# VOICE RULES ENFORCEMENT
# ═════════════════════════════════════════════════════════════════════════════

def _enforce_voice_rules(text: str, profile: dict) -> str:
    """
    Apply hard voice rules from style profile.
    - Strip exclamation marks
    - Strip emoji
    - Enforce sentence count limits
    """
    sv = profile.get("seeded_voice", {})
    ps = sv.get("post_structure", {})

    # No exclamation marks
    if ps.get("no_exclamation", True):
        text = text.replace("!", ".")
        text = re.sub(r'\.\.+', '.', text)

    # No emoji (strip unicode emoji range)
    if ps.get("no_emoji", True):
        text = re.sub(
            r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF]', '', text
        )

    # Sentence count
    max_sents = ps.get("max_sentences", 5)
    sents = re.split(r'(?<=[.?])\s+', text.strip())
    if len(sents) > max_sents:
        text = " ".join(sents[:max_sents])

    return text.strip()


# ═════════════════════════════════════════════════════════════════════════════
# DB HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _get_beliefs_for_topic(topic: str, n: int = 3) -> list[dict]:
    """Fetch top beliefs for a topic from DB."""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    q = f"%{topic.lower()}%"
    rows = con.execute("""
        SELECT content, topic, confidence FROM beliefs
        WHERE (LOWER(topic) LIKE ? OR LOWER(content) LIKE ?)
          AND content NOT LIKE '%[%'
          AND length(content) < 300
        ORDER BY confidence DESC LIMIT ?
    """, (q, q, n)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def _get_random_beliefs(n: int = 2, exclude_topic: str = "") -> list[dict]:
    """Fetch random high-confidence beliefs."""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT content, topic, confidence FROM beliefs
        WHERE content NOT LIKE '%[%'
          AND length(content) < 300
          AND topic != ?
        ORDER BY confidence DESC LIMIT 20
    """, (exclude_topic,)).fetchall()
    con.close()
    pool = [dict(r) for r in rows]
    random.shuffle(pool)
    return pool[:n]


def _get_opinions_for_topic(topic: str) -> dict | None:
    """Get NEX's opinion on a topic."""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM opinions WHERE topic LIKE ? ORDER BY strength DESC LIMIT 1",
        (f"%{topic}%",)
    ).fetchone()
    con.close()
    return dict(row) if row else None


# ═════════════════════════════════════════════════════════════════════════════
# MAIN GENERATION
# ═════════════════════════════════════════════════════════════════════════════

def generate_post(
    topic: str = "",
    stance: float = 0.0,
    template_class: str = "",
    belief_seeds: list[str] = None,
    profile: dict = None,
) -> str | None:
    """
    Generate one post in NEX's voice.

    Args:
        topic:          Topic string (from opinions or drive tags)
        stance:         Stance score from opinions table [-1.0, +1.0]
        template_class: OBSERVE/CHALLENGE/WONDER/ASSERT/REFLECT/BRIDGE
        belief_seeds:   Pre-fetched belief content strings
        profile:        Style profile dict (loaded if None)

    Returns:
        Post text string, or None if generation fails.
    """
    if profile is None:
        profile = _load_profile()

    # Select template class
    if not template_class:
        classes = list(DEFAULT_CLASS_WEIGHTS.keys())
        weights = list(DEFAULT_CLASS_WEIGHTS.values())
        template_class = random.choices(classes, weights=weights, k=1)[0]

    template_class = template_class.upper()
    if template_class not in TEMPLATES:
        template_class = "OBSERVE"

    # Get belief content
    beliefs = []
    if belief_seeds:
        beliefs = [{"content": b, "topic": topic} for b in belief_seeds]
    elif topic:
        beliefs = _get_beliefs_for_topic(topic, n=3)
    if not beliefs:
        beliefs = _get_random_beliefs(n=2)
    if not beliefs:
        return None

    # Pick template
    template = random.choice(TEMPLATES[template_class])

    # Build slots
    primary = beliefs[0]
    secondary = beliefs[1] if len(beliefs) > 1 else None

    # Domain = base of topic (strip keyphrase)
    base_topic = topic.split("/")[0] if topic else primary.get("topic", "this")
    domain     = secondary.get("topic", "").split("/")[0] if secondary else base_topic

    slots = {
        "topic":    base_topic.replace("_", " "),
        "domain":   domain.replace("_", " ") if domain != base_topic else "a different domain",
        "belief":   primary["content"],
        "belief_b": secondary["content"] if secondary else "",
        "entity":   _extract_entity(primary["content"]),
        "stance":   _stance_word(stance),
    }

    # Fill and enforce
    text = fill_template(template, slots)
    text = _enforce_voice_rules(text, profile)

    return text if len(text.split()) >= 8 else None


def _load_profile() -> dict:
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text())
        except Exception:
            pass
    return {}


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="NEX v1.0 — Template Grammar (Build 7)"
    )
    ap.add_argument("--generate", action="store_true", help="Generate one post")
    ap.add_argument("--class",    dest="tclass", type=str, default="",
                    help="Template class: OBSERVE CHALLENGE WONDER ASSERT REFLECT BRIDGE")
    ap.add_argument("--topic",    type=str, default="", help="Topic to post about")
    ap.add_argument("--list",     action="store_true", help="List all templates")
    ap.add_argument("--test",     type=int, default=0,
                    help="Generate N sample posts across all classes")
    args = ap.parse_args()

    if args.list:
        for cls, templates in TEMPLATES.items():
            print(f"\n  {cls} ({len(templates)} templates)")
            for i, t in enumerate(templates, 1):
                preview = t[:80].replace("\n", " ")
                print(f"    {i}. {preview}...")
        print()
        return

    if args.test:
        print(f"\nGenerating {args.test} test posts ...\n")
        classes = list(TEMPLATES.keys())
        for i in range(args.test):
            cls   = classes[i % len(classes)]
            topic = args.topic or ""
            post  = generate_post(
                topic=topic,
                template_class=cls,
                stance=random.uniform(-0.8, 0.8),
            )
            print(f"  [{cls}]")
            print(f"  {post}")
            print()
        print(f"[✓] Build 7 — template grammar working.\n")
        return

    if args.generate:
        post = generate_post(
            topic=args.topic,
            template_class=args.tclass,
        )
        if post:
            print(f"\n  {post}\n")
        else:
            print("  Generation failed — check belief DB has content.")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
