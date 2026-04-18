"""
nex_width_helpers.py — prompt comprehension + reply fidelity layer.

Purpose: preprocess user messages before they hit NEX's reply engine,
so NEX actually answers what was asked, in the register it was asked in.

Usage (from nex_telegram.py):

    from nex_width_helpers import (
        extract_constraints,
        detect_frame,
        format_hint,
        enforce_constraints,
    )

    constraints = extract_constraints(user_message)
    frame       = detect_frame(user_message, chat_history)
    hint        = format_hint(constraints, frame)
    reply       = generate_reply(hint + user_message)
    final       = enforce_constraints(reply, constraints)

All functions are defensive — wrap in try/except is optional, but if given
bad input they return safe defaults rather than raising.
"""

import re
import logging

log = logging.getLogger("nex_width")

# ── Regex detectors (compiled once) ──────────────────────────────────────────

_LEN_SHORT = re.compile(
    r'\b(short|brief|quick|tl;?dr|one\s+(line|sentence)|keep\s+it\s+short|briefly)\b',
    re.I
)
_LEN_LONG = re.compile(
    r'\b(detailed|long|thorough|deep[-\s]?dive|expand|elaborate|in\s+depth)\b',
    re.I
)
_NO_PHIL = re.compile(
    r"\b(no\s+philosophy|skip\s+philosophy|don'?t\s+philosophi[sz]e|no\s+waffle|just\s+the\s+answer|cut\s+the\s+(crap|philosophy)|sick\s+of\s+philosophy)\b",
    re.I
)
_TECHNICAL = re.compile(
    r'\b(technical|code|algorithm|architecture|function|api|schema|sql|script|debug|python|sqlite)\b',
    re.I
)
_CASUAL = re.compile(
    r'(\blol\b|\blmao\b|[?!]{2,}|\bwtf\b|\bfuck|\bshit|\bdamn|\bbro\b)',
    re.I
)
_YES_NO = re.compile(
    r'^\s*(is|are|was|were|does|do|did|can|could|will|would|should|has|have|isn\'?t|aren\'?t)\b.*\?\s*$',
    re.I
)
_LIST_REQ = re.compile(
    r'\b(list|bullet|points?|steps?|enumerate)\b',
    re.I
)
_DIRECT = re.compile(
    r'\b(just\s+tell\s+me|straight\s+up|directly|no\s+bullshit|plainly|simply)\b',
    re.I
)
_COMPARE = re.compile(
    r'\b(compare|versus|\bvs\.?\b|difference between|which is better)\b',
    re.I
)


# ── Public API ───────────────────────────────────────────────────────────────

def extract_constraints(text):
    """
    Extract explicit constraints from a user message.

    Returns a dict with any of these keys:
      length:       'short' | 'long'
      forbid:       comma-separated topics to avoid
      mode:         'technical'
      answer_shape: 'direct_yes_no_then_why' | 'direct'
      format:       'list'
      compare:      True
    """
    if not isinstance(text, str):
        return {}
    c = {}
    if _LEN_SHORT.search(text):
        c['length'] = 'short'
    elif _LEN_LONG.search(text):
        c['length'] = 'long'
    if _NO_PHIL.search(text):
        c['forbid'] = 'philosophy,consciousness,emergence,meta'
    if _TECHNICAL.search(text):
        c['mode'] = 'technical'
    if _YES_NO.search(text):
        c['answer_shape'] = 'direct_yes_no_then_why'
    elif _DIRECT.search(text):
        c['answer_shape'] = 'direct'
    if _LIST_REQ.search(text):
        c['format'] = 'list'
    if _COMPARE.search(text):
        c['compare'] = True
    return c


def detect_frame(text, history=None):
    """
    Detect the user's register so NEX can mirror it.

    Returns a dict with any of these keys:
      tone:              'casual'
      profanity_ok:      True
      user_word_count:   int
      brevity_signal:    'matched_short'
    """
    if not isinstance(text, str):
        return {}
    f = {}
    if _CASUAL.search(text):
        f['tone'] = 'casual'
        f['profanity_ok'] = bool(re.search(r'\b(fuck|shit|damn)', text, re.I))
    wc = len(text.split())
    f['user_word_count'] = wc
    if wc <= 8:
        f['brevity_signal'] = 'matched_short'
    return f


def format_hint(constraints, frame):
    """
    Turn constraint + frame dicts into a prefix the reply engine can read.
    Returns empty string if nothing to hint.
    """
    if not constraints and not frame:
        return ''
    parts = []

    length = constraints.get('length') if constraints else None
    if length == 'short':
        parts.append('[REPLY STYLE: maximum 2 sentences, no preamble, no philosophy]')
    elif length == 'long':
        parts.append('[REPLY STYLE: detailed, multiple paragraphs welcome]')

    if constraints and constraints.get('forbid'):
        parts.append(f"[AVOID TOPICS: {constraints['forbid']}]")

    if constraints and constraints.get('mode') == 'technical':
        parts.append('[MODE: technical and concrete, no metaphor, no philosophy]')

    shape = constraints.get('answer_shape') if constraints else None
    if shape == 'direct_yes_no_then_why':
        parts.append('[SHAPE: open with yes or no, then one sentence of reasoning]')
    elif shape == 'direct':
        parts.append('[SHAPE: direct answer first, explanation only if asked]')

    if constraints and constraints.get('format') == 'list':
        parts.append('[FORMAT: bullet list]')

    if constraints and constraints.get('compare'):
        parts.append('[SHAPE: structured comparison, list the differences]')

    if frame and frame.get('tone') == 'casual':
        parts.append('[TONE: casual, match the user register]')

    if frame and frame.get('brevity_signal') == 'matched_short':
        parts.append('[LENGTH MIRROR: user was brief, stay brief]')

    if not parts:
        return ''
    return '\n'.join(parts) + '\n\n'


def enforce_constraints(reply, constraints):
    """
    Hard-trim reply if user asked for short and NEX went long.
    Runs AFTER generation, as a backstop.
    """
    if not isinstance(reply, str) or not constraints:
        return reply
    length = constraints.get('length')
    if length == 'short':
        sentences = re.split(r'(?<=[.!?])\s+', reply.strip())
        if len(sentences) > 2:
            reply = ' '.join(sentences[:2])
    return reply


# ── Self-test (run when module is executed directly) ─────────────────────────

if __name__ == '__main__':
    tests = [
        "keep it short, what's your favorite belief?",
        "no philosophy, just tell me: is Python better than Rust?",
        "fuck yeah explain it bro",
        "detailed breakdown of the architecture please",
        "compare transformers vs RNNs",
        "list the steps to train a model",
        "can you do this?",
        "im sick of philosophy give me code",
    ]
    for t in tests:
        c = extract_constraints(t)
        f = detect_frame(t)
        h = format_hint(c, f)
        print(f"\nINPUT:  {t}")
        print(f"  constraints: {c}")
        print(f"  frame:       {f}")
        print(f"  hint:        {h.strip() if h else '(none)'}")
