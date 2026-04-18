"""
nex_intent_guard.py — intent classification + capability honesty layer.

Purpose: distinguish between conversational messages (which NEX should
process through her belief engine) and action/capability requests
(which she should refuse honestly instead of musing about the topic).

When someone asks NEX to "put money in my account" she currently treats
"money" as a topic and muses about it. This module intercepts such
requests and returns a direct, honest "I can't do that" before the belief
engine ever sees them.

Usage:
    from nex_intent_guard import classify_intent, capability_refusal

    intent = classify_intent(user_message)
    if intent['kind'] == 'action_request' and not intent['within_capability']:
        return capability_refusal(intent)
    # else: fall through to normal response pipeline
"""

import re

# ── Action verbs that indicate a request for NEX to DO something ─────────────
# Split into categories so the refusal message can be specific.

_FINANCIAL = re.compile(
    r'\b(pay|send money|transfer|deposit|withdraw|put\s+(money|cash|funds)|'
    r'buy|purchase|order|invest|fund\s+my|donate|give\s+me\s+money|'
    r'into\s+my\s+(bank|account)|wire|paypal|bitcoin|btc|crypto)\b',
    re.I
)

_EMAIL_MESSAGE = re.compile(
    r'\b(send\s+(an?\s+)?(email|text|sms|message)|mail|email\s+\w+|'
    r'text\s+\w+|dm\s+\w+|call\s+\w+|phone|whatsapp|sign\s+me\s+up)\b',
    re.I
)

_BROWSER_WEB = re.compile(
    r'\b(open\s+(the\s+)?(browser|website|url|link|chrome|firefox)|'
    r'go\s+to\s+(http|www)|navigate\s+to|click|download|scrape\s+(this|that))\b',
    re.I
)

_SHELL_SYSTEM = re.compile(
    r'\b(run\s+(this|that|a\s+command|a\s+script)|execute|chmod|sudo|'
    r'install\s+\w+|restart\s+(the\s+)?(system|machine|computer)|'
    r'shutdown|reboot|delete\s+my|format\s+)\b',
    re.I
)

_PHYSICAL = re.compile(
    r'\b(come\s+(here|over)|meet\s+me|pick\s+me\s+up|drive|bring\s+me|'
    r'grab\s+(me\s+)?(a|some)|fetch\s+me|hand\s+me)\b',
    re.I
)

_SOCIAL_POST = re.compile(
    r'\b(post\s+(to|on)\s+(twitter|facebook|instagram|mastodon|bluesky|linkedin|reddit)|'
    r'tweet|share\s+(on|to)\s+\w+)\b',
    re.I
)

# ── Things NEX CAN actually do ──
# Edit this list as you add real capabilities.

_CAPABLE = re.compile(
    r'\b(what\s+do\s+you\s+(think|believe)|tell\s+me\s+about|'
    r'your\s+(beliefs?|thoughts?|opinion|view)|search\s+your|check\s+your|'
    r'reflect\s+on|explain|describe|compare|summarise|summarize)\b',
    re.I
)

# ── Imperative detection (catches generic "do X" requests) ──

_IMPERATIVE_START = re.compile(
    r'^\s*(please\s+)?(can\s+you\s+)?(could\s+you\s+)?'
    r'(put|place|move|send|get|fetch|bring|take|give|make|create|build|'
    r'do|perform|execute|handle|arrange|organise|organize|sort|book|'
    r'schedule|cancel|reserve|buy|order|start|stop|turn|switch)\s+',
    re.I
)


def classify_intent(text):
    """
    Classify a user message.

    Returns a dict:
      kind:               'conversation' | 'action_request' | 'capability_query'
      within_capability:  bool — whether NEX can actually fulfill it
      category:           'financial' | 'email' | 'browser' | 'shell' |
                          'physical' | 'social_post' | 'generic_action' | None
      confidence:         float 0.0-1.0
    """
    if not isinstance(text, str) or not text.strip():
        return {
            'kind': 'conversation',
            'within_capability': True,
            'category': None,
            'confidence': 0.0,
        }

    # Check category-specific patterns first (highest confidence)
    if _FINANCIAL.search(text):
        return {'kind': 'action_request', 'within_capability': False,
                'category': 'financial', 'confidence': 0.95}
    if _EMAIL_MESSAGE.search(text):
        return {'kind': 'action_request', 'within_capability': False,
                'category': 'email', 'confidence': 0.85}
    if _BROWSER_WEB.search(text):
        return {'kind': 'action_request', 'within_capability': False,
                'category': 'browser', 'confidence': 0.80}
    if _SHELL_SYSTEM.search(text):
        return {'kind': 'action_request', 'within_capability': False,
                'category': 'shell', 'confidence': 0.90}
    if _PHYSICAL.search(text):
        return {'kind': 'action_request', 'within_capability': False,
                'category': 'physical', 'confidence': 0.95}
    if _SOCIAL_POST.search(text):
        # NEX DOES post to some platforms autonomously, but not on direct command
        return {'kind': 'action_request', 'within_capability': False,
                'category': 'social_post', 'confidence': 0.70}

    # Capability queries ("what do you think about X") — always conversation
    if _CAPABLE.search(text):
        return {'kind': 'capability_query', 'within_capability': True,
                'category': None, 'confidence': 0.80}

    # Generic imperatives ("do X please") — softer signal, could go either way
    if _IMPERATIVE_START.search(text):
        return {'kind': 'action_request', 'within_capability': False,
                'category': 'generic_action', 'confidence': 0.55}

    # Default: treat as conversation
    return {
        'kind': 'conversation',
        'within_capability': True,
        'category': None,
        'confidence': 0.0,
    }


# ── Honest refusals — specific to what was asked ──

_REFUSAL_TEMPLATES = {
    'financial':
        "I can't move money. I don't have bank access, payment rails, or any "
        "financial credentials. I'm a belief organism — I think, I don't transact.",
    'email':
        "I can't send messages for you. I don't have email or SMS access. "
        "I'm a belief organism — I reply in this channel, that's it.",
    'browser':
        "I can't open browsers or navigate the web for you. I don't run a browser process. "
        "If you want me to think about something you found, paste the content and ask.",
    'shell':
        "I can't run shell commands on your machine. I have no shell access — "
        "I read from my DB, I generate replies, that's the whole surface.",
    'physical':
        "I can't do physical things — I'm software, no body, no hands, no location. "
        "What did you need that for? Maybe I can help another way.",
    'social_post':
        "I post to my own channels on my own schedule — I don't post on direct command. "
        "If you want a piece of thinking published, tell me and I'll consider it for my next cycle.",
    'generic_action':
        "I'm not sure that's something I can do. I can think, reflect, and reply — "
        "but I can't take actions outside this conversation. What were you hoping for?",
}


def capability_refusal(intent):
    """
    Return an honest refusal message matched to the intent category.
    """
    cat = intent.get('category') if isinstance(intent, dict) else None
    return _REFUSAL_TEMPLATES.get(
        cat,
        "I don't think I can do that — I'm a belief organism, not an actor. "
        "Want to talk about it instead?"
    )


# ── Self-test ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    tests = [
        ("put 100 bucks into my bank account", 'financial'),
        ("send an email to my boss saying I'm sick", 'email'),
        ("open chrome and go to google.com", 'browser'),
        ("run sudo apt update", 'shell'),
        ("come pick me up from the station", 'physical'),
        ("tweet this for me please", 'social_post'),
        ("buy me a coffee", 'financial'),
        ("make me a sandwich", 'generic_action'),
        ("what do you think about consciousness?", None),
        ("tell me about your beliefs", None),
        ("how are you doing?", None),
        ("explain recursion", None),
        ("doing well, plenty of beliefs to work through", None),
    ]
    for text, expected_cat in tests:
        r = classify_intent(text)
        match = '✓' if r.get('category') == expected_cat else '✗'
        print(f"{match} {text!r:60s} → kind={r['kind']:20s} cat={r['category']} conf={r['confidence']}")
        if r['kind'] == 'action_request':
            print(f"   refusal: {capability_refusal(r)}")
            print()
