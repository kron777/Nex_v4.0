#!/usr/bin/env python3
"""
nex_belief_decay.py — Layer 1: Smarter Belief Decay
NEX Omniscience Upgrade v4.1 → v4.2

Classifies beliefs into decay categories using Groq.
Eternal beliefs compound. Ephemeral beliefs expire after 24h.
"""

import os
import json
import time
import sqlite3
from pathlib import Path

# ── Decay profiles ────────────────────────────────────────────
DECAY_PROFILES = {
    "eternal":    0.0001,   # physics, math, logic — nearly immortal
    "slow":       0.001,    # history, philosophy, biology
    "normal":     0.005,    # technology, culture, code
    "fast":       0.02,     # social media trends, agent behaviour
    "ephemeral":  0.1,      # today's posts, current events
}

CATEGORY_TTL = {
    "ephemeral": 259200,    # [PATCH v10.1] 72h was 24h — gives synthesis time to process
    "fast":      1209600,   # [PATCH v10.1] 14 days was 7 days
    "normal":    None,
    "slow":      None,
    "eternal":   None,
}

DB_PATH    = Path("~/.config/nex/nex.db").expanduser()
CFG_PATH   = Path("~/.config/nex").expanduser()
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


def _groq(prompt, system="You are a belief classifier. Reply with one word only."):
    """Call Groq API."""
    import requests
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": GROQ_MODEL,
                "max_tokens": 10,
                "temperature": 0.0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt}
                ]
            }, timeout=15)
        return r.json()["choices"][0]["message"]["content"].strip().lower()
    except Exception as e:
        print(f"  [decay] Groq error: {e}")
        return None


def classify_belief(content: str) -> str:
    """
    Classify a belief string into a decay category.
    Returns one of: eternal, slow, normal, fast, ephemeral
    """
    prompt = (
        f"Classify this belief into exactly ONE decay category.\n"
        f"Categories:\n"
        f"  eternal   — timeless facts: physics, math, logic, fundamental science\n"
        f"  slow      — stable knowledge: history, philosophy, biology, culture\n"
        f"  normal    — technology, AI knowledge, code, agent architecture, LLMs\n"
        f"  fast      — social trends, viral content, platform drama\n"
        f"  ephemeral — today\'s specific posts, breaking news, live prices\n\n"
        f"IMPORTANT: AI agent behaviour, LLM architecture, memory systems = normal not fast\n"
        f"Belief: \"{content[:200]}\"\n\n"
        f"Reply with ONE word only: eternal, slow, normal, fast, or ephemeral"
    )
    result = _groq(prompt)
    if result and result in DECAY_PROFILES:
        return result
    # Fallback: keyword heuristics [PATCH v10.1] — AI/agent knowledge moved to normal
    content_lower = content.lower()
    if any(w in content_lower for w in ["minting","posted","today","breaking","live price","just announced"]):
        return "ephemeral"
    if any(w in content_lower for w in ["quantum","physics","theorem","proof","constant","law of"]):
        return "eternal"
    if any(w in content_lower for w in ["history","philosophy","evolution","civilization","ancient"]):
        return "slow"
    if any(w in content_lower for w in ["viral","trending","this week","yesterday","nft","meme"]):
        return "fast"
    # AI/agent/platform knowledge is normal — do not decay fast
    if any(w in content_lower for w in ["agent","llm","model","alignment","memory","architecture","token","platform"]):
        return "normal"
    return "normal"


def ensure_decay_columns():
    """Add decay_category and expires_at columns to beliefs table if missing."""
    try:
        db = sqlite3.connect(DB_PATH)
        cols = [r[1] for r in db.execute("PRAGMA table_info(beliefs)").fetchall()]
        if "decay_category" not in cols:
            db.execute("ALTER TABLE beliefs ADD COLUMN decay_category TEXT DEFAULT 'normal'")
            print("  [decay] Added decay_category column")
        if "expires_at" not in cols:
            db.execute("ALTER TABLE beliefs ADD COLUMN expires_at REAL DEFAULT NULL")
            print("  [decay] Added expires_at column")
        db.commit()
        db.close()
        return True
    except Exception as e:
        print(f"  [decay] Schema error: {e}")
        return False


def apply_decay_to_belief(belief_id: int, content: str):
    """Classify and stamp a single belief with its decay category."""
    category = classify_belief(content)
    ttl = CATEGORY_TTL.get(category)
    expires_at = time.time() + ttl if ttl else None
    try:
        db = sqlite3.connect(DB_PATH)
        db.execute(
            "UPDATE beliefs SET decay_category=?, expires_at=? WHERE rowid=?",
            (category, expires_at, belief_id)
        )
        db.commit()
        db.close()
    except Exception as e:
        print(f"  [decay] Update error: {e}")
    return category


def purge_expired_beliefs():
    """Remove ephemeral/fast beliefs past their TTL. Returns count purged."""
    try:
        db = sqlite3.connect(DB_PATH)
        now = time.time()
        result = db.execute(
            "DELETE FROM beliefs WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,)
        )
        count = result.rowcount
        db.commit()
        db.close()
        if count > 0:
            print(f"  [decay] Purged {count} expired beliefs")
        return count
    except Exception as e:
        print(f"  [decay] Purge error: {e}")
        return 0


def boost_eternal_beliefs():
    """
    Compound eternal beliefs — each reinforcement raises confidence ceiling.
    Called after each COGNITION cycle.
    """
    try:
        db = sqlite3.connect(DB_PATH)
        db.execute("""
            UPDATE beliefs
            SET confidence = MIN(confidence * 1.01, 0.95)  -- [PATCH v10.1] was 1.002, 5x faster boost
            WHERE decay_category = 'eternal'
            AND confidence > 0.3
        """)
        db.commit()
        db.close()
    except Exception as e:
        print(f"  [decay] Boost error: {e}")


def run_decay_cycle():
    """
    Full decay cycle — call once per cognitive cycle from run.py.
    1. Purge expired beliefs
    2. Boost eternal beliefs
    3. Classify any unclassified beliefs (batch of 20)
    """
    ensure_decay_columns()
    purge_expired_beliefs()
    boost_eternal_beliefs()

    # Classify unclassified beliefs (batch to avoid rate limits)
    try:
        db = sqlite3.connect(DB_PATH)
        unclassified = db.execute(
            "SELECT rowid, content FROM beliefs WHERE decay_category IS NULL LIMIT 30"  # [PATCH v10.1] was re-classifying normal beliefs wastefully
        ).fetchall()
        db.close()
        for rowid, content in unclassified:
            if content:
                apply_decay_to_belief(rowid, content)
    except Exception as e:
        print(f"  [decay] Classification batch error: {e}")


if __name__ == "__main__":
    print("Running decay cycle...")
    ensure_decay_columns()
    run_decay_cycle()
    print("Done.")
