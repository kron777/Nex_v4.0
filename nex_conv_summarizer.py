"""
nex_conv_summarizer.py
Compresses long conversations into belief update candidates.
Extracts positions NEX took, contradictions encountered, new topics.
Runs after each conversation above N turns.
"""
import sqlite3, json, logging, time, requests
from pathlib import Path

log     = logging.getLogger("nex.summarizer")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
API     = "http://localhost:8080/completion"

SUMMARIZE_PROMPT = """Extract the key intellectual positions from this conversation.

Conversation:
{conversation}

Return JSON only:
{{
  "positions": ["NEX stated position 1", "NEX stated position 2"],
  "topics": ["topic1", "topic2"],
  "contradictions": ["tension or unresolved point"],
  "new_ground": ["something NEX hadn't addressed before"]
}}"""

def summarize_conversation(turns: list) -> dict:
    """
    Takes list of {role, content} dicts.
    Returns extracted positions and topics.
    """
    # Format conversation
    conv_text = "\n".join(
        f"{t['role'].upper()}: {t['content'][:200]}"
        for t in turns[-20:]  # last 20 turns max
    )

    try:
        prompt = SUMMARIZE_PROMPT.format(conversation=conv_text[:2000])
        r = requests.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": 300, "temperature": 0.2,
            "stop": ["<|im_end|>","<|im_start|>","```"],
            "cache_prompt": False
        }, timeout=30)
        text = r.json().get("content", "").strip()
        import re
        # Try JSON parse
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        # Fallback: extract quoted strings as positions
        positions = re.findall(r'"([^"]{20,200})"', text)
        if positions:
            return {"positions": positions[:5], "topics": [], "contradictions": [], "new_ground": []}
    except Exception as e:
        log.debug(f"Summarize failed: {e}")

    return {"positions": [], "topics": [], "contradictions": [], "new_ground": []}

def positions_to_beliefs(positions: list, topics: list) -> int:
    """Insert extracted positions as low-confidence belief candidates."""
    if not positions:
        return 0
    db = sqlite3.connect(str(DB_PATH))
    inserted = 0
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    topic = topics[0] if topics else "conversation"

    for pos in positions:
        if len(pos.split()) < 5:
            continue
        try:
            db.execute("""INSERT INTO beliefs
                (content, topic, confidence, source, belief_type, created_at)
                VALUES (?,?,?,?,?,?)""",
                (pos[:300], topic, 0.55, "conv_summarizer", "opinion", now))
            inserted += 1
        except sqlite3.IntegrityError:
            pass

    db.commit()
    db.close()
    log.info(f"Inserted {inserted} belief candidates from conversation")
    return inserted

def process_log(conv_log_path: str, min_turns=6) -> dict:
    """Process conversations.jsonl and extract beliefs from long conversations."""
    lines = Path(conv_log_path).read_text().strip().split("\n")
    entries = [json.loads(l) for l in lines if l.strip()]

    # Group into conversation sessions (gap > 5 min = new session)
    sessions = []
    current = []
    last_ts = 0

    for e in entries:
        ts = e.get("timestamp", 0)
        if ts - last_ts > 300 and current:  # 5 min gap
            sessions.append(current)
            current = []
        current.append(e)
        last_ts = ts

    if current:
        sessions.append(current)

    total_inserted = 0
    processed = 0

    for session in sessions:
        turns = [e for e in session if e.get("role") in ("user", "assistant")]
        if len(turns) < min_turns:
            continue

        result = summarize_conversation(turns)
        inserted = positions_to_beliefs(result["positions"], result["topics"])
        total_inserted += inserted
        processed += 1

    return {"sessions_processed": processed, "beliefs_inserted": total_inserted}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing summarizer on recent conversations...")
    import sys
    sys.path.insert(0, "/home/rr/Desktop/nex")

    conv_log = "/home/rr/Desktop/nex/logs/conversations.jsonl"
    result = process_log(conv_log, min_turns=4)
    print(f"Sessions processed: {result['sessions_processed']}")
    print(f"Belief candidates inserted: {result['beliefs_inserted']}")
