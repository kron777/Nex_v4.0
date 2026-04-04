#!/usr/bin/env python3
"""
nex_memory_crystallisation.py
Conversational Memory Crystallisation Engine.

Detects implicit beliefs that NEX has expressed repeatedly across
conversations but never formally stated as a belief.

If NEX argues the same position in 3+ conversations without it
being in the belief graph — that position should crystallise
into an explicit belief.

Process:
  1. Load all conversation summaries (positions extracted per conversation)
  2. Embed each position
  3. Cluster by semantic similarity (threshold >= 0.82)
  4. If cluster has 3+ members from different conversations: crystallise
  5. Ask LLM to synthesise cluster into a canonical belief statement
  6. Novelty check against existing beliefs
  7. Store with confidence proportional to recurrence count

Effect: NEX stops re-deriving the same positions from scratch.
        Recurring implicit positions become explicit held beliefs.
"""
import sqlite3, json, re, logging, time
from pathlib import Path
from collections import defaultdict

log     = logging.getLogger("nex.crystallise")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
API     = "http://localhost:8080/completion"
CONV_LOG = NEX_DIR / "logs/conversations.jsonl"

MIN_CLUSTER_SIZE   = 2     # minimum recurrences to crystallise
SIMILARITY_THRESH  = 0.85  # cosine similarity for clustering
MIN_NOVELTY        = 0.30  # must differ from existing beliefs


CRYSTALLISE_PROMPT = """These positions have appeared repeatedly in conversations:

{positions}

Synthesise ONE canonical belief statement that captures what
all these positions have in common.

First person. 15-40 words. Direct claim.
Start with "I hold" or "My position is".
Return only the belief statement."""


def _llm(prompt: str, max_tokens=80) -> str:
    import requests as _r
    try:
        resp = _r.post(API, json={
            "prompt": f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "n_predict": max_tokens, "temperature": 0.3,
            "stop": ["<|im_end|>","<|im_start|>"],
            "cache_prompt": False,
        }, timeout=25)
        return resp.json().get("content","").strip()
    except Exception as e:
        log.debug(f"LLM failed: {e}")
        return ""


def _load_model():
    if not hasattr(_load_model, "_m"):
        from sentence_transformers import SentenceTransformer
        _load_model._m = SentenceTransformer("all-MiniLM-L6-v2")
    return _load_model._m


def extract_conversation_positions(log_path: Path) -> list:
    """
    Parse conversations.jsonl and extract NEX positions.
    Groups by conversation session (gap > 30 min = new session).
    Returns list of {session_id, positions, timestamp}.
    """
    if not log_path.exists():
        return []

    turns = []
    with open(log_path) as f:
        for line in f:
            try:
                turns.append(json.loads(line.strip()))
            except Exception:
                pass

    # Group into sessions by time gaps
    sessions = []
    current  = []
    last_ts  = 0

    for turn in turns:
        ts = turn.get("timestamp", 0)
        if last_ts and (ts - last_ts) > 1800:  # 30 min gap
            if current:
                sessions.append(current)
                current = []
        current.append(turn)
        last_ts = ts

    if current:
        sessions.append(current)

    # Extract NEX positions from each session
    result = []
    for i, session in enumerate(sessions):
        nex_turns = [t["content"] for t in session
                     if t.get("role") == "assistant" and len(t.get("content","")) > 50]
        if not nex_turns:
            continue
        # Extract "I hold" / "My position" statements
        positions = []
        for text in nex_turns:
            sentences = re.split(r"(?<=[.!?])\s+", text)
            for s in sentences:
                sl = s.lower()
                if any(marker in sl for marker in
                       ["i hold", "my position", "i believe", "i think that",
                        "my view is", "what i hold"]):
                    if len(s.split()) >= 8:
                        positions.append(s.strip()[:200])
        if positions:
            result.append({
                "session_id": i,
                "positions": positions[:5],  # top 5 per session
                "timestamp": session[0].get("timestamp", 0),
            })

    return result


def cluster_positions(sessions: list) -> list:
    """
    Cluster positions by semantic similarity across sessions.
    Returns clusters of similar positions from different sessions.
    """
    import numpy as np
    model = _load_model()

    # Flatten all positions with session IDs
    all_positions = []
    for sess in sessions:
        for pos in sess["positions"]:
            all_positions.append({
                "text": pos,
                "session_id": sess["session_id"],
            })

    if len(all_positions) < MIN_CLUSTER_SIZE:
        return []

    # Embed all positions
    texts = [p["text"] for p in all_positions]
    vecs  = model.encode(texts, normalize_embeddings=True)

    # Greedy clustering
    used     = set()
    clusters = []

    for i in range(len(all_positions)):
        if i in used:
            continue
        cluster      = [all_positions[i]]
        cluster_sids = {all_positions[i]["session_id"]}
        used.add(i)

        for j in range(i+1, len(all_positions)):
            if j in used:
                continue
            # Don't cluster same session
            if all_positions[j]["session_id"] in cluster_sids:
                continue
            sim = float(np.dot(vecs[i], vecs[j]))
            if sim >= SIMILARITY_THRESH:
                cluster.append(all_positions[j])
                cluster_sids.add(all_positions[j]["session_id"])
                used.add(j)

        if len(cluster) >= MIN_CLUSTER_SIZE:
            clusters.append(cluster)

    return clusters


def crystallise_cluster(cluster: list, existing_beliefs: list) -> str:
    """Synthesise a cluster into a canonical belief statement."""
    positions_text = "\n".join(f"- {p['text'][:150]}" for p in cluster[:6])
    belief = _llm(CRYSTALLISE_PROMPT.format(positions=positions_text))
    if not belief or len(belief.split()) < 8:
        return ""

    # Novelty check
    bw = set(belief.lower().split())
    for ex in existing_beliefs[:30]:
        ew = set(ex.lower().split())
        if bw and ew:
            overlap = len(bw & ew) / len(bw | ew)
            if overlap > (1 - MIN_NOVELTY):
                return ""

    return belief


def run_crystallisation(dry_run=False) -> dict:
    """Main crystallisation run."""
    db = sqlite3.connect(str(DB_PATH))

    print("Loading conversation history...")
    sessions = extract_conversation_positions(CONV_LOG)
    print(f"  {len(sessions)} sessions, extracting positions...")

    if not sessions:
        print("No conversation sessions found")
        db.close()
        return {"crystallised": 0}

    print("Clustering positions across sessions...")
    clusters = cluster_positions(sessions)
    print(f"  {len(clusters)} clusters found with {MIN_CLUSTER_SIZE}+ recurrences")

    existing = [r[0] for r in db.execute(
        "SELECT content FROM beliefs WHERE confidence >= 0.65 LIMIT 100"
    ).fetchall()]

    crystallised = 0
    stored       = 0

    for cluster in clusters:
        belief = crystallise_cluster(cluster, existing)
        if not belief:
            continue

        crystallised += 1
        confidence = min(0.80, 0.60 + len(cluster) * 0.04)
        session_ids = list({p["session_id"] for p in cluster})

        print(f"\nCRYSTALLISED (n={len(cluster)} sessions):")
        print(f"  {belief[:120]}")
        print(f"  confidence={confidence:.2f}")

        if not dry_run:
            try:
                now = time.strftime("%Y-%m-%dT%H:%M:%S")
                db.execute("""INSERT INTO beliefs
                    (content, topic, confidence, source, belief_type, created_at)
                    VALUES (?,?,?,?,?,?)""", (
                    belief[:300], "self", confidence,
                    f"crystallised:{len(cluster)}_sessions",
                    "opinion", now,
                ))
                stored += 1
                existing.append(belief)
            except Exception as e:
                log.debug(f"Store failed: {e}")

    if not dry_run:
        db.commit()
    db.close()

    print(f"\nCrystallisation complete:")
    print(f"  Sessions processed: {len(sessions)}")
    print(f"  Clusters found:     {len(clusters)}")
    print(f"  Crystallised:       {crystallised}")
    print(f"  Stored:             {stored}")
    return {"sessions": len(sessions), "clusters": len(clusters),
            "crystallised": crystallised, "stored": stored}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_crystallisation(dry_run=args.dry_run)
