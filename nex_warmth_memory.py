"""
nex_warmth_memory.py
Item 12 — Inter-Session Memory Warmth.

If a user returns to a topic from a previous conversation,
the words from that topic should arrive pre-warmed at
session level — not just persistent background level.

NEX remembers not just what was said but what conceptual
territory was warm. Returning conversations feel continuous.

How it works:
  1. At conversation end, session's top-boosted words
     are stored in a persistent memory layer (per user/topic)
  2. On new conversation start, check for topic overlap
     with stored sessions
  3. If overlap detected, pre-boost matching vocabulary
     into the new session before first response

Memory entries:
  user_id (or "default")
  topic_signature (top 5 most-active words, sorted)
  warm_words: {word: boost_value} for top 20 words
  timestamp
  access_count

Topic matching:
  New question → extract key words → check overlap with
  stored topic signatures → if >= 3 words match → pre-boost
"""
import sqlite3, json, re, time, logging, sys
from pathlib import Path
from collections import defaultdict

log     = logging.getLogger("nex.warmth_memory")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

TOPIC_OVERLAP_THRESHOLD = 3   # words that must match
MAX_STORED_SESSIONS     = 50  # per user
SESSION_TTL_DAYS        = 30  # discard after 30 days
PRE_BOOST_DISCOUNT      = 0.6 # pre-boosts are discounted


def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def _init_memory_db(db):
    """Create inter-session memory table."""
    db.execute("""CREATE TABLE IF NOT EXISTS
        session_warmth_memory (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         TEXT DEFAULT 'default',
        topic_signature TEXT NOT NULL,
        warm_words      TEXT NOT NULL,
        dominant_depth  INTEGER DEFAULT 3,
        dominant_valence REAL DEFAULT 0.0,
        exchange_count  INTEGER DEFAULT 0,
        created_at      REAL,
        accessed_at     REAL,
        access_count    INTEGER DEFAULT 0
    )""")
    db.commit()


def _extract_topic_signature(warm_words: dict,
                              n=5) -> str:
    """
    Build a topic signature from top warm words.
    Sorted alphabetically for consistent matching.
    """
    top = sorted(warm_words.items(),
                key=lambda x: x[1], reverse=True)[:n]
    return "|".join(sorted(w for w, _ in top))


def _extract_query_words(text: str) -> set:
    """Extract key words from query for topic matching."""
    STOPS = {
        "the","and","for","that","this","with","from","have",
        "been","will","would","could","should","just","also",
        "very","more","most","some","any","its","what","which",
        "who","how","when","where","why","than","then","like",
    }
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
    return {w for w in words if w not in STOPS}


def store_session(session,
                  user_id: str = "default",
                  db=None) -> bool:
    """
    Store a completed session's warmth data for future recall.
    Called at conversation end.

    session: SessionWarmthLayer instance
    """
    close_db = False
    if db is None:
        db = _get_db()
        close_db = True

    _init_memory_db(db)

    # Only store sessions with meaningful activity
    if not session.boosts or len(session.boosts) < 3:
        if close_db:
            db.close()
        return False

    # Get top warm words
    top_words = dict(session.most_active(20))
    if not top_words:
        if close_db:
            db.close()
        return False

    topic_sig = _extract_topic_signature(top_words)

    # Get dominant depth and valence from DB
    dominant_depth   = 3
    dominant_valence = 0.0
    depths   = []
    valences = []
    nex_db = sqlite3.connect(str(DB_PATH))
    nex_db.row_factory = sqlite3.Row
    for word in list(top_words.keys())[:10]:
        row = nex_db.execute(
            "SELECT d, e FROM word_tags WHERE word=?",
            (word,)).fetchone()
        if row:
            if row["d"]: depths.append(row["d"])
            if row["e"]: valences.append(row["e"])
    nex_db.close()
    if depths:
        dominant_depth = int(sum(depths)/len(depths))
    if valences:
        dominant_valence = sum(valences)/len(valences)

    try:
        db.execute("""INSERT INTO session_warmth_memory
            (user_id, topic_signature, warm_words,
             dominant_depth, dominant_valence,
             exchange_count, created_at, accessed_at,
             access_count)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id,
             topic_sig,
             json.dumps(top_words),
             dominant_depth,
             round(dominant_valence, 3),
             session.exchange_count,
             time.time(),
             time.time(),
             0))
        db.commit()

        # Trim old sessions
        db.execute("""DELETE FROM session_warmth_memory
            WHERE user_id=?
            AND id NOT IN (
                SELECT id FROM session_warmth_memory
                WHERE user_id=?
                ORDER BY created_at DESC
                LIMIT ?)""",
            (user_id, user_id, MAX_STORED_SESSIONS))
        db.commit()

        log.info(f"Session stored: {topic_sig[:40]} "
                 f"({len(top_words)} words)")

        if close_db:
            db.close()
        return True

    except Exception as e:
        log.debug(f"Session store failed: {e}")
        if close_db:
            db.close()
        return False


def recall_session(question: str,
                   user_id: str = "default",
                   db=None) -> dict:
    """
    Check if a new question matches stored session topics.
    If match found, return pre-boost recommendations.

    Returns:
        {
          matched: bool,
          pre_boosts: {word: boost_value},
          topic_match: str,
          dominant_depth: int,
          tone_hint: str,
        }
    """
    close_db = False
    if db is None:
        db = _get_db()
        close_db = True

    _init_memory_db(db)

    query_words = _extract_query_words(question)
    if not query_words:
        if close_db:
            db.close()
        return {"matched": False}

    # Purge expired sessions
    cutoff = time.time() - (SESSION_TTL_DAYS * 86400)
    db.execute("""DELETE FROM session_warmth_memory
        WHERE created_at < ?""", (cutoff,))
    db.commit()

    # Get stored sessions for this user
    sessions = db.execute("""SELECT id, topic_signature,
        warm_words, dominant_depth, dominant_valence,
        access_count
        FROM session_warmth_memory
        WHERE user_id=?
        ORDER BY accessed_at DESC""",
        (user_id,)).fetchall()

    best_match    = None
    best_overlap  = 0

    for stored in sessions:
        sig_words = set(
            stored["topic_signature"].split("|"))
        overlap = len(query_words & sig_words)

        if overlap >= TOPIC_OVERLAP_THRESHOLD:
            if overlap > best_overlap:
                best_overlap  = overlap
                best_match    = stored

    if not best_match:
        if close_db:
            db.close()
        return {"matched": False}

    # Load warm words from match
    try:
        warm_words = json.loads(
            best_match["warm_words"])
    except Exception:
        if close_db:
            db.close()
        return {"matched": False}

    # Apply discount to pre-boosts
    # (inherited warmth is less certain than live warmth)
    pre_boosts = {
        word: round(boost * PRE_BOOST_DISCOUNT, 3)
        for word, boost in warm_words.items()
        if boost * PRE_BOOST_DISCOUNT >= 0.05
    }

    # Update access record
    db.execute("""UPDATE session_warmth_memory
        SET accessed_at=?, access_count=access_count+1
        WHERE id=?""",
        (time.time(), best_match["id"]))
    db.commit()

    dominant_depth = best_match["dominant_depth"] or 3
    depth_names = {
        1:"shallow", 2:"semi_mid", 3:"mid",
        4:"semi_deep", 5:"deep", 6:"soul"
    }

    tone_hints = {
        5: "You've explored this deep territory before.",
        6: "This touches questions you've sat with before.",
        4: "You have prior engagement with this territory.",
        3: "Some familiar ground here.",
    }
    tone_hint = tone_hints.get(
        dominant_depth,
        "Continuing from prior engagement.")

    result = {
        "matched":        True,
        "overlap":        best_overlap,
        "pre_boosts":     pre_boosts,
        "topic_match":    best_match["topic_signature"],
        "dominant_depth": dominant_depth,
        "depth_name":     depth_names.get(
            dominant_depth, "mid"),
        "tone_hint":      tone_hint,
        "prior_exchanges":best_match["access_count"],
    }

    log.info(f"Session recalled: "
             f"overlap={best_overlap} "
             f"depth={dominant_depth} "
             f"pre_boosts={len(pre_boosts)}")

    if close_db:
        db.close()

    return result


def apply_recall_to_session(session,
                             question: str,
                             user_id: str = "default"):
    """
    Check for stored session match and pre-boost
    the new session's vocabulary if found.

    Call at start of each new conversation.
    """
    result = recall_session(question, user_id)

    if not result.get("matched"):
        return result

    # Apply pre-boosts to session
    for word, boost in result["pre_boosts"].items():
        session.boosts[word] = max(
            session.boosts.get(word, 0), boost)
        session.encounter_counts[word] = 1

    log.info(f"Session pre-boosted: "
             f"{len(result['pre_boosts'])} words "
             f"from prior session")

    return result


def memory_report(user_id: str = "default") -> None:
    """Show stored session memory."""
    db = _get_db()
    _init_memory_db(db)

    total = db.execute("""SELECT COUNT(*) FROM
        session_warmth_memory
        WHERE user_id=?""", (user_id,)).fetchone()[0]

    print(f"\n  Session memory for '{user_id}':")
    print(f"  Stored sessions: {total}")

    recent = db.execute("""SELECT topic_signature,
        dominant_depth, exchange_count, access_count,
        created_at
        FROM session_warmth_memory
        WHERE user_id=?
        ORDER BY created_at DESC LIMIT 5""",
        (user_id,)).fetchall()

    depth_names = {
        1:"shallow",2:"semi_mid",3:"mid",
        4:"semi_deep",5:"deep",6:"soul"
    }

    for r in recent:
        ts = time.strftime(
            "%m/%d %H:%M",
            time.localtime(r["created_at"]))
        depth = depth_names.get(r["dominant_depth"],"?")
        print(f"  [{ts}] "
              f"depth={depth:9} "
              f"exchanges={r['exchange_count']} "
              f"recalled={r['access_count']}x "
              f"| {r['topic_signature'][:35]}")

    db.close()


if __name__ == "__main__":
    import argparse, sys
    sys.path.insert(0, str(NEX_DIR))
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--test-recall", type=str,
        help="Test recall for a question")
    args = parser.parse_args()

    if args.report:
        memory_report()
    elif args.test_recall:
        result = recall_session(args.test_recall)
        print(json.dumps(result, indent=2))
    else:
        memory_report()
        print("\nDemo: testing recall on consciousness question")
        result = recall_session(
            "What is the relationship between "
            "consciousness and identity?")
        if result.get("matched"):
            print(f"  Match found: {result['topic_match']}")
            print(f"  Pre-boosts : {len(result['pre_boosts'])}")
        else:
            print("  No match yet — "
                  "store some sessions first")
