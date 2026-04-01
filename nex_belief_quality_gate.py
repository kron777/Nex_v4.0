"""
nex_belief_quality_gate.py — Pre-insertion quality filter for beliefs.
Call before inserting any belief into the DB.
LLM-free — pure pattern matching. Fast.
"""
import re

# Celebrity/pop culture blocklist
_CELEBRITY_NAMES = {
    "taylor swift", "beyonce", "rihanna", "kanye", "drake", "megan thee",
    "kardashian", "bieber", "lady gaga", "ariana grande", "billie eilish",
    "cardi b", "nicki minaj", "post malone", "the weeknd", "doja cat",
    "harry styles", "olivia rodrigo", "dua lipa", "bad bunny", "shakira",
    "ed sheeran", "selena gomez", "miley cyrus", "katy perry", "adele",
}

# Code/technical garbage patterns
_CODE_PATTERNS = re.compile(
    r'(import\s+\w+\s+from|function\s*\(|\.min\.js|\.css\?|'
    r'localStorage\.|document\.getElementById|window\.|console\.log|'
    r'<script|<\/div>|className=|onClick=)',
    re.IGNORECASE
)

# URL patterns
_URL_PATTERN = re.compile(r'https?://\S+|www\.\S+\.\w{2,}')

# Cookie/tracking garbage
_TRACKING_PATTERN = re.compile(
    r'(cookie policy|privacy policy|subscribe.*newsletter|'
    r'click here to|terms of service|all rights reserved|'
    r'©\s*\d{4}|follow us on|sign up for)',
    re.IGNORECASE
)

# Repetitive ingestion patterns (same lawsuit/event mentioned repeatedly)
_REPETITIVE_PATTERNS = re.compile(
    r'(as evidenced by|as shown by|as demonstrated by|as seen in the case of)\s+'
    r'(Taylor Swift|Beyonce|Megan|Drake|Kanye)',
    re.IGNORECASE
)

def is_quality_belief(content: str, topic: str = "") -> tuple[bool, str]:
    """
    Check if a belief meets quality standards.
    Returns (is_quality, reason_if_rejected).
    """
    if not content or not content.strip():
        return False, "empty content"

    content = content.strip()

    # Too short
    if len(content) < 45:
        return False, f"too short ({len(content)} chars)"

    # Too long (likely a paragraph dump)
    if len(content) > 500:
        return False, f"too long ({len(content)} chars)"

    # Contains URL
    if _URL_PATTERN.search(content):
        return False, "contains URL"

    # Contains code
    if _CODE_PATTERNS.search(content):
        return False, "contains code/markup"

    # Tracking/cookie garbage
    if _TRACKING_PATTERN.search(content):
        return False, "tracking/cookie content"

    # Celebrity garbage
    content_lower = content.lower()
    for name in _CELEBRITY_NAMES:
        if name in content_lower:
            # Allow if it's a genuine philosophical point, not just a mention
            if not any(word in content_lower for word in
                       ['consciousness', 'philosophy', 'ethics', 'emergence',
                        'alignment', 'belief', 'truth', 'knowledge', 'paradox']):
                return False, f"celebrity content ({name})"

    # Repetitive lawsuit/event pattern
    if _REPETITIVE_PATTERNS.search(content):
        return False, "repetitive celebrity event pattern"

    # Must have some substantive content (at least 6 meaningful words)
    words = re.findall(r'\b[a-z]{4,}\b', content_lower)
    stopwords = {'that', 'this', 'with', 'from', 'have', 'been', 'their',
                 'they', 'which', 'were', 'also', 'more', 'than', 'some',
                 'when', 'what', 'will', 'would', 'could', 'should'}
    meaningful = [w for w in words if w not in stopwords]
    if len(meaningful) < 4:
        return False, f"insufficient meaningful words ({len(meaningful)})"

    return True, ""


def filter_beliefs(beliefs: list, topic: str = "") -> list:
    """Filter a list of belief strings, returning only quality ones."""
    return [b for b in beliefs if is_quality_belief(b, topic)[0]]


if __name__ == "__main__":
    # Test
    test_cases = [
        ("Consciousness is not solely a product of computation.", "consciousness"),
        ("Taylor Swift was sued over a song title.", "music"),
        ("http://example.com/article", "ai"),
        ("Short.", "philosophy"),
        ("function() { return false; }", "science"),
        ("The hard problem of consciousness deepens under scrutiny and cannot be dissolved by functional accounts alone.", "consciousness"),
        ("As evidenced by Taylor Swift being sued, artists face legal challenges.", "music"),
    ]
    print("Quality gate test:")
    for content, topic in test_cases:
        ok, reason = is_quality_belief(content, topic)
        status = "✅" if ok else f"❌ ({reason})"
        print(f"  {status} | {content[:70]}")
