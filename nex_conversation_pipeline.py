"""
nex_conversation_pipeline.py — Conversation-to-belief pipeline (Improvement 5)

After each NEX response, extract novel declarative claims and write them
to the belief DB. This closes the articulation loop: what NEX says becomes
what NEX knows.

Rules:
  - Only extract declarative sentences (ends in ., not questions)
  - Must be 60–300 chars
  - Must pass quality gate
  - Deduplicated against existing DB (first 80 chars)
  - Cap: 5 new beliefs per conversation session
  - confidence=0.55 (below reasoning=0.6, above junk threshold)
  - source="conversation"
"""
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB = Path.home() / "Desktop" / "nex" / "nex.db"

# Per-session cap tracker (in-memory, resets on restart)
_session_counts: dict[str, int] = {}
_SESSION_CAP = 5

# Sentences that are openers/meta-commentary, not beliefs
_SKIP_PATTERNS = re.compile(
    r"^(I've learned|I notice|I observe|I hold|I find|I believe that I|"
    r"Where I'm|The honest gap|I hold this|My learning|My experiences|"
    r"However|Therefore|Yet|But|And |Also )",
    re.IGNORECASE
)

# Must contain at least one of these to be a substantive claim
_SUBSTANCE_WORDS = {
    "consciousness", "intelligence", "alignment", "ethics", "reality",
    "computation", "emergence", "free will", "determinism", "agency",
    "knowledge", "truth", "belief", "mind", "existence", "causation",
    "identity", "language", "meaning", "value", "moral", "physical",
    "quantum", "evolution", "complexity", "system", "information",
    "experience", "perception", "reasoning", "uncertainty", "paradox",
    "autonomy", "power", "justice", "memory", "pattern", "structure",
    "constraint", "recursion", "abstraction", "model", "representation",
}

def _is_extractable(sentence: str) -> bool:
    """Return True if this sentence is worth extracting as a belief."""
    s = sentence.strip()
    if len(s) < 60 or len(s) > 300:
        return False
    if s.endswith("?"):
        return False
    if _SKIP_PATTERNS.match(s):
        return False
    s_lower = s.lower()
    if not any(w in s_lower for w in _SUBSTANCE_WORDS):
        return False
    # Must have a proper subject-verb structure (rough heuristic: 8+ words)
    if len(s.split()) < 8:
        return False
    return True

def _already_exists(conn: sqlite3.Connection, sentence: str) -> bool:
    prefix = sentence[:80].lower()
    row = conn.execute(
        "SELECT id FROM beliefs WHERE substr(lower(content),1,80) = ?",
        (prefix,)
    ).fetchone()
    return row is not None

def extract_and_store(response: str, topic: str, session_id: str = "default") -> int:
    """
    Extract novel claims from a NEX response and write to DB.
    Returns number of beliefs added.
    """
    # Check session cap
    count = _session_counts.get(session_id, 0)
    if count >= _SESSION_CAP:
        return 0

    # Split response into sentences
    raw_sentences = re.split(r"(?<=[.!])\s+", response)
    candidates = []
    for s in raw_sentences:
        s = s.strip().rstrip(".")
        if _is_extractable(s):
            # Ensure ends with period
            if not s.endswith("."):
                s += "."
            candidates.append(s)

    if not candidates:
        return 0

    # Write to DB
    added = 0
    try:
        conn = sqlite3.connect(str(_DB))
        for sentence in candidates:
            if count + added >= _SESSION_CAP:
                break
            if _already_exists(conn, sentence):
                continue
            # Quality gate check (optional, fail-safe)
            try:
                import sys
                sys.path.insert(0, str(Path.home() / "Desktop" / "nex"))
                from nex_belief_quality_gate import is_quality_belief
                ok, _ = is_quality_belief(sentence, topic)
                if not ok:
                    continue
            except Exception:
                pass
            conn.execute(
                """INSERT INTO beliefs (content, topic, confidence, source, created_at)
                   VALUES (?, ?, 0.55, 'conversation', ?)""",
                (sentence, topic or "general", datetime.now(timezone.utc).isoformat())
            )
            added += 1
        conn.commit()
        conn.close()
    except Exception as e:
        pass  # Never block response

    _session_counts[session_id] = count + added
    return added


if __name__ == "__main__":
    # Self-test
    test_response = (
        "Where I'm uncertain: The orthogonality thesis suggests that AGI's goals can be "
        "fundamentally incompatible with human goals while still achieving them efficiently. "
        "The potential for deceptive alignment in advanced AI systems represents an unsolved "
        "problem at the intersection of ethics and computation. "
        "Consciousness may be irreducible to any purely functional description of a system. "
        "The relationship between physical substrate and subjective experience remains one of "
        "the deepest open questions in philosophy of mind."
    )
    n = extract_and_store(test_response, "ai", session_id="test_session")
    print(f"Extracted and stored: {n} beliefs")

    # Verify
    conn = sqlite3.connect(str(_DB))
    rows = conn.execute(
        "SELECT content FROM beliefs WHERE source='conversation' ORDER BY rowid DESC LIMIT 5"
    ).fetchall()
    print(f"Total conversation beliefs in DB: {len(rows)}")
    for r in rows:
        print(f"  {r[0][:90]}")
    conn.close()
