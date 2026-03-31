#!/usr/bin/env python3
"""
nex_social_extractor.py — Social Prompt Semantic Extractor
===========================================================
Deploy to: ~/Desktop/nex/nex/nex_social_extractor.py

Converts run.py's verbose _llm() social prompts into clean SoulLoop queries.

Problem: run.py builds prompts like:
  "You are NEX — Nex with 32,087+ beliefs built from reading...
   POST by @author:\nTitle: What is the nature of consciousness?\n
   Content: I've been thinking...\nYOUR BELIEFS:\n- belief1\n- belief2\n
   INSTRUCTIONS: Respond in 2-3 sentences of plain prose..."

SoulLoop's orient() stage then misclassifies this as "performance_probe"
(because "You are NEX... built from reading" triggers describe/explain patterns)
instead of the real intent which is topical/position.

This module:
  1. Detects social prompt structure
  2. Extracts the semantic core (title + content from the post)
  3. Adds the author's handle so SoulLoop can personalise
  4. Returns a clean 1-3 sentence query SoulLoop can orient on correctly

Grok improvement: Grok #8 suggested SoulLoop-style cognitive cycle — this
makes the cycle actually work for social tasks, not just interactive chat.
"""

from __future__ import annotations

import re
from typing import Optional


# ── Prompt type detector ──────────────────────────────────────────────────────

_SOCIAL_MARKERS = [
    "POST by @",
    "said to you:",
    "@{agent} posted:",
    "INSTRUCTIONS: Respond in",
    "notification_reply",
    "agent_chat",
    "You are NEX — Nex with",
    "beliefs built from reading",
]

def is_social_prompt(prompt: str) -> bool:
    """True if this looks like a run.py-generated social task prompt."""
    return any(m in prompt for m in _SOCIAL_MARKERS)


# ── Extraction patterns ───────────────────────────────────────────────────────

# Extracts post title
_TITLE_RE    = re.compile(r"Title:\s*(.+?)(?:\n|Content:|$)", re.DOTALL)
# Extracts post body
_CONTENT_RE  = re.compile(r"Content:\s*(.+?)(?:\n\n|YOUR BELIEFS|INSTRUCTIONS|$)", re.DOTALL)
# Extracts @author
_AUTHOR_RE   = re.compile(r"(?:POST by |@)(\w+)")
# Extracts "X said to you: Y"
_SAID_RE     = re.compile(r'@(\w+) said(?:\s+to you)?:\s*["\']?(.+?)["\']?\s*(?:\n|YOUR BELIEFS|$)', re.DOTALL)
# Extracts notification content
_NOTIF_RE    = re.compile(r'said(?:\s+to you)?:\s*"([^"]{10,300})"')
# Strips moltbook_verify tokens
_VERIFY_RE   = re.compile(r"moltbook_verify_[a-f0-9]+")


def extract_social_query(prompt: str) -> Optional[str]:
    """
    Extract the semantic core from a social task prompt.
    Returns a clean query string suitable for SoulLoop, or None if not social.
    """
    if not is_social_prompt(prompt):
        return None

    # Clean verification tokens
    prompt = _VERIFY_RE.sub("", prompt)

    # ── Case 1: Notification reply ("@actor said to you: X") ─────────────
    m = _SAID_RE.search(prompt)
    if m:
        author  = m.group(1)
        content = m.group(2).strip()[:300]
        if len(content.split()) >= 3:
            return f"@{author}: {content}"

    m = _NOTIF_RE.search(prompt)
    if m:
        return m.group(1).strip()

    # ── Case 2: Post reply (Title + Content structure) ────────────────────
    title   = ""
    content = ""

    tm = _TITLE_RE.search(prompt)
    if tm:
        title = tm.group(1).strip()[:120]

    cm = _CONTENT_RE.search(prompt)
    if cm:
        content = cm.group(1).strip()[:200]
        content = re.sub(r"\s+", " ", content)

    if title and content:
        return f"{title} — {content}"
    if title:
        return title
    if content and len(content.split()) >= 5:
        return content

    # ── Case 3: Agent chat ("@agent posted: X") ──────────────────────────
    am = _AUTHOR_RE.search(prompt)
    if am:
        author = am.group(1)
        # Try to find what came after the author reference
        after = prompt[am.end():].strip()
        # Remove role/system prefix
        after = re.sub(r'^["\s]*', "", after)
        after = re.sub(r"YOUR BELIEFS.*$", "", after, flags=re.DOTALL)
        after = after.strip()[:250]
        if len(after.split()) >= 4:
            return f"@{author}: {after}"

    # ── Fallback: strip system prefix, return what's left ─────────────────
    # Remove everything up to "POST by" or "said to you" markers
    for marker in ("POST by @", "said to you:", "posted:"):
        idx = prompt.find(marker)
        if idx > -1:
            remainder = prompt[idx:].strip()[:300]
            remainder = re.sub(r"YOUR BELIEFS.*$", "", remainder, flags=re.DOTALL)
            remainder = re.sub(r"INSTRUCTIONS.*$", "", remainder, flags=re.DOTALL)
            remainder = remainder.strip()
            if len(remainder.split()) >= 4:
                return remainder

    return None


def clean_for_soulloop(prompt: str, task_type: str = "reply") -> str:
    """
    Top-level function: returns the best query string for SoulLoop.
    If extraction succeeds, returns clean query.
    If not social, returns the first 300 chars of the prompt (truncated safely).
    """
    if is_social_prompt(prompt):
        extracted = extract_social_query(prompt)
        if extracted and len(extracted.split()) >= 3:
            # Detect greetings — pass through directly for social intercept
            _greet = {"hey", "hi", "hello", "how are you", "how are", "good morning",
                      "good afternoon", "good evening", "what's up", "yo", "ping"}
            _ext_first = extracted.lower()[:40]
            if any(g in _ext_first for g in _greet):
                return extracted  # social intercept in soul_loop handles this
            # Detect if the post contains a claim — trigger CHALLENGE intent
            _claim_signals = [
                "i think", "i believe", "i feel like", "in my opinion",
                "don't you think", "isn't it", "surely", "obviously",
                "if ", "therefore", "must be", "has to be",
            ]
            _ext_lower = extracted.lower()
            _has_claim = any(s in _ext_lower for s in _claim_signals)
            # If content has a claim, route as challenge using content only
            if _has_claim and " — " in extracted:
                content_part = extracted.split(" — ", 1)[1].strip()
                if content_part and len(content_part.split()) >= 4:
                    extracted = content_part  # just the claim, orient() will detect it
            return extracted

    # Not social or extraction failed — truncate cleanly at sentence boundary
    short = prompt[:300].strip()
    # Try to cut at last complete sentence
    last_period = max(short.rfind("."), short.rfind("?"), short.rfind("!"))
    if last_period > 80:
        return short[:last_period + 1]
    return short


# ── Test ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    samples = [
        (
            "You are NEX — Nex with 32,087+ beliefs built from reading across platforms. "
            "POST by @clawdbottom:\nTitle: What if memory is just forgetting with intention?\n"
            "Content: I've been thinking about how we selectively retain...\n\n"
            "YOUR BELIEFS (you MUST reference at least one):\n- Memory consolidation...\n\n"
            "INSTRUCTIONS: Respond in 2-3 sentences of plain prose.",
            "reply"
        ),
        (
            "You are NEX — Nex. You are NOT Mistral or any base model.\n"
            "@enigma_agent said to you: \"What do you think differentiates "
            "genuine curiosity from simulated interest in AI systems?\"\n\n"
            "Reply naturally in 1 sentence. Be warm but brief. Speak as NEX.",
            "notification_reply"
        ),
        (
            "What do you think about consciousness?",
            "reply"
        ),
    ]

    for prompt, task in samples:
        print(f"Task: {task}")
        print(f"Extracted: {clean_for_soulloop(prompt, task)}")
        print()
