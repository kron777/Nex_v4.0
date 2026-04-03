#!/usr/bin/env python3
"""
nex_user_model.py — Persistent User Identity for NEX v4.0

NEX learns who she is talking to across sessions.
Tracks: name, interests, projects, communication style, preferences.
Updates from every conversation via LLM extraction.
Injects user context into every response prompt.

Usage:
    from nex_user_model import get_user_context, update_from_conversation
    ctx = get_user_context()         # inject into prompt
    update_from_conversation(q, r)   # update after each exchange

CLI:
    python3 nex_user_model.py --show
    python3 nex_user_model.py --set name "Jon"
    python3 nex_user_model.py --set interest "AI systems"
    python3 nex_user_model.py --reset
"""

import sqlite3, json, requests, re, logging, time
from pathlib import Path

log     = logging.getLogger("nex.user_model")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_model (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT NOT NULL UNIQUE,
    value      TEXT NOT NULL,
    confidence REAL DEFAULT 0.7,
    source     TEXT DEFAULT 'inferred',
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_um_key ON user_model(key);
"""

# Keys NEX tracks about the user
USER_KEYS = {
    "name":            "User's name or preferred name",
    "projects":        "Current projects or work the user is doing",
    "interests":       "Topics the user is interested in",
    "expertise":       "User's areas of knowledge or profession",
    "communication":   "User's communication style (terse/verbose/technical)",
    "goals":           "What the user is trying to achieve",
    "location":        "User's location if mentioned",
    "preferences":     "User's stated preferences about NEX's responses",
}

EXTRACT_PROMPT = """Extract personal information about the USER from this conversation.
Return JSON only. Keys must be from: {keys}
Only include what is explicitly stated or strongly implied about the USER (not NEX).
If nothing clear, return {{}}.

User said: {query}
NEX responded: {response}

JSON about the user:"""


def _db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.commit()
    return db


def get_user_profile() -> dict:
    """Return full user profile as dict."""
    db = _db()
    rows = db.execute(
        "SELECT key, value, confidence FROM user_model ORDER BY confidence DESC"
    ).fetchall()
    db.close()
    return {r["key"]: {"value": r["value"], "confidence": r["confidence"]} for r in rows}


def set_fact(key: str, value: str, confidence: float = 0.9, source: str = "explicit"):
    """Explicitly set a user fact."""
    db = _db()
    db.execute("""
        INSERT INTO user_model (key, value, confidence, source, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            confidence=excluded.confidence,
            source=excluded.source,
            updated_at=excluded.updated_at
    """, (key, value[:500], confidence, source, time.time()))
    db.commit()
    db.close()


def get_user_context() -> str:
    """
    Return formatted user context for prompt injection.
    Called before each response generation.
    """
    profile = get_user_profile()
    if not profile:
        return ""
    lines = ["What I know about you:"]
    for key, data in profile.items():
        if data["confidence"] >= 0.6:
            lines.append(f"  {key}: {data['value'][:100]}")
    return "\n".join(lines) + "\n" if len(lines) > 1 else ""


def update_from_conversation(query: str, response: str):
    """
    Extract user facts from a conversation exchange via LLM.
    Called after each response generation.
    """
    if len(query.split()) < 3:
        return

    try:
        keys_str = ", ".join(USER_KEYS.keys())
        prompt = EXTRACT_PROMPT.format(
            keys=keys_str,
            query=query[:200],
            response=response[:200]
        )
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 150,
            "temperature": 0.0,
            "stop": ["<|im_end|>", "<|im_start|>", "\n\n"],
            "cache_prompt": False,
        }, timeout=10)
        raw = r.json().get("content", "").strip()
        match = re.search(r"\{.*?\}", raw, re.DOTALL)
        if not match:
            return
        facts = json.loads(match.group(0))
        if not isinstance(facts, dict):
            return
        for key, value in facts.items():
            if key in USER_KEYS and value and len(str(value)) > 2:
                set_fact(key, str(value)[:300], confidence=0.75, source="inferred")
                log.debug(f"User model updated: {key}={value[:50]}")
    except Exception as e:
        log.debug(f"User model extraction error: {e}")


def reset():
    """Clear all user model data."""
    db = _db()
    db.execute("DELETE FROM user_model")
    db.commit()
    db.close()


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="NEX user identity model")
    parser.add_argument("--show",  action="store_true", help="Show user profile")
    parser.add_argument("--set",   nargs=2, metavar=("KEY", "VALUE"), help="Set a user fact")
    parser.add_argument("--reset", action="store_true", help="Clear all user data")
    args = parser.parse_args()

    if args.show:
        profile = get_user_profile()
        if not profile:
            print("No user profile yet — NEX will build it from conversations.")
        else:
            print("\nNEX user profile:")
            print("═" * 45)
            for key, data in profile.items():
                print(f"  [{data['confidence']:.2f}] {key}: {data['value'][:80]}")
            print("═" * 45)

    elif args.set:
        key, value = args.set
        if key not in USER_KEYS:
            print(f"Valid keys: {list(USER_KEYS.keys())}")
        else:
            set_fact(key, value, confidence=1.0, source="explicit")
            print(f"Set {key} = {value}")

    elif args.reset:
        reset()
        print("User profile cleared.")

    else:
        parser.print_help()
