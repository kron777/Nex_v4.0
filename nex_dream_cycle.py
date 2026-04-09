"""
nex_dream_cycle.py  —  Dream Cycle
====================================
When NEX is idle (2-4am or manually triggered), she traverses her own
belief graph looking for non-obvious connections — beliefs that are
topically distant but structurally linked through chains of intermediate
beliefs.

No LLM calls. Pure graph traversal. Fast (~30s on CPU).

What it produces:
  - "Intuition" beliefs written to nex.db with source="dream_cycle"
  - Tagged ["dream", "intuition", "synthesized"]
  - Confidence ~0.65 — not certain, but worth surfacing
  - Stored in ~/.config/nex/dream_log.json for inspection

Wire-in (run.py):
    # In the nightly section (cycle % 100 == 0 and hour in (2,3)):
    from nex_dream_cycle import run_dream_cycle
    intuitions = run_dream_cycle()
    if intuitions:
        nex_log("dream", f"Dream cycle: {len(intuitions)} intuitions")

Or run standalone:
    python3 nex_dream_cycle.py
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import sqlite3
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

# ── Config ───────────────────────────────────────────────────────────────────
_CONFIG_DIR   = Path.home() / ".config" / "nex"
_DB_PATH      = _CONFIG_DIR / "nex.db"
_DREAM_LOG    = _CONFIG_DIR / "dream_log.json"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# How many belief pairs to evaluate
_SAMPLE_PAIRS     = 600

# Min path length between beliefs to count as "non-obvious"
_MIN_PATH_LEN     = 2

# Max path length to search (BFS depth)
_MAX_PATH_LEN     = 5

# Min topic distance (different topics required)
_REQUIRE_DIFF_TOPIC = True

# How many intuitions to generate per dream cycle
_MAX_INTUITIONS   = 15

# Confidence assigned to dream intuitions
_INTUITION_CONF   = 0.65

# Stop words for topic/content extraction
_STOP = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","have","has","had",
    "this","that","these","those","it","its","not","so","if","as","which",
    "when","their","our","your","what","how","all","some","there","than",
    "more","just","also","about","like","can","into","will","would","could",
    "should","may","might","do","does","did","get","got","use","used",
}


# ── Graph loading ─────────────────────────────────────────────────────────────

def _load_graph(db: sqlite3.Connection) -> tuple[dict, dict, dict]:
    """
    Load belief graph from DB.
    Returns:
      beliefs  : {id -> {content, topic, confidence}}
      adj      : {id -> set of neighbour ids}  (undirected)
      topics   : {topic -> [belief_ids]}
    """
    beliefs = {}
    rows = db.execute(
        "SELECT id, content, topic, confidence FROM beliefs "
        "WHERE confidence >= 0.4 LIMIT 5000"
    ).fetchall()
    for bid, content, topic, conf in rows:
        beliefs[bid] = {
            "content":    content or "",
            "topic":      topic or "general",
            "confidence": conf or 0.5,
        }

    adj = defaultdict(set)
    link_rows = db.execute(
        "SELECT parent_id, child_id FROM belief_links"
    ).fetchall()
    for p, c in link_rows:
        if p in beliefs and c in beliefs:
            adj[p].add(c)
            adj[c].add(p)   # undirected

    topics = defaultdict(list)
    for bid, b in beliefs.items():
        topics[b["topic"]].append(bid)

    return beliefs, dict(adj), dict(topics)


# ── BFS path finder ───────────────────────────────────────────────────────────

def _bfs_path(
    start: int,
    end:   int,
    adj:   dict,
    max_depth: int = _MAX_PATH_LEN,
) -> Optional[list[int]]:
    """
    BFS shortest path from start to end.
    Returns path as list of node ids, or None if not reachable within max_depth.
    """
    if start == end:
        return [start]
    visited = {start}
    queue   = deque([[start]])
    while queue:
        path = queue.popleft()
        if len(path) > max_depth:
            return None
        node = path[-1]
        for nb in adj.get(node, set()):
            if nb == end:
                return path + [nb]
            if nb not in visited:
                visited.add(nb)
                queue.append(path + [nb])
    return None


# ── Surprise scorer ───────────────────────────────────────────────────────────

def _topic_distance(t1: str, t2: str) -> float:
    """
    Simple topic distance — 0 if same, 1 if completely different,
    0.5 if sharing some words.
    """
    if t1 == t2:
        return 0.0
    w1 = set(re.findall(r'\b[a-z]{3,}\b', t1.lower())) - _STOP
    w2 = set(re.findall(r'\b[a-z]{3,}\b', t2.lower())) - _STOP
    if not w1 or not w2:
        return 1.0
    overlap = len(w1 & w2) / min(len(w1), len(w2))
    return 1.0 - overlap


def _content_overlap(c1: str, c2: str) -> float:
    """Word overlap between two belief contents."""
    w1 = set(re.findall(r'\b[a-z]{4,}\b', c1.lower())) - _STOP
    w2 = set(re.findall(r'\b[a-z]{4,}\b', c2.lower())) - _STOP
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / min(len(w1), len(w2))


def _surprise_score(
    b1:       dict,
    b2:       dict,
    path_len: int,
) -> float:
    """
    Score how surprising a connection is.
    High surprise = topically distant + long path + low content overlap.
    """
    topic_dist    = _topic_distance(b1["topic"], b2["topic"])
    content_sim   = _content_overlap(b1["content"], b2["content"])
    path_score    = min(1.0, (path_len - 2) / 3.0)   # longer = more surprising
    conf_bonus    = (b1["confidence"] + b2["confidence"]) / 2.0

    surprise = (
        topic_dist  * 0.40 +
        (1 - content_sim) * 0.30 +
        path_score  * 0.20 +
        conf_bonus  * 0.10
    )
    return round(surprise, 4)


# ── Intuition formatter ───────────────────────────────────────────────────────

def _format_intuition(
    b1:       dict,
    b2:       dict,
    path:     list[int],
    beliefs:  dict,
    surprise: float,
    shared_keywords: list = None,
) -> str:
    """
    Format a discovered connection as a belief-style string.
    No LLM — template-driven but specific to the actual beliefs.
    """
    t1 = b1["topic"].replace("_", " ")
    t2 = b2["topic"].replace("_", " ")

    # Extract key phrases from each belief
    def _key_phrase(text: str, n: int = 6) -> str:
        words = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', text) if w.lower() not in _STOP]
        return " ".join(words[:n])

    kp1 = _key_phrase(b1["content"])
    kp2 = _key_phrase(b2["content"])

    # Path description — what topics does it pass through?
    mid_topics = []
    for mid_id in path[1:-1]:
        mt = beliefs.get(mid_id, {}).get("topic", "")
        if mt and mt not in (b1["topic"], b2["topic"]) and mt not in mid_topics:
            mid_topics.append(mt.replace("_", " "))

    shared_str = ", ".join(shared_keywords[:3]) if shared_keywords else "unknown"
    templates = [
        f"[Dream intuition] '{t1}' and '{t2}' share the concept of '{shared_str}'. "
        f"Specifically: '{kp1[:60]}' connects to '{kp2[:60]}' "
        f"through shared structure despite different domains.",

        f"[Dream intuition] Overnight traversal found: '{kp1[:50]}' ({t1}) "
        f"and '{kp2[:50]}' ({t2}) both involve '{shared_str}'. "
        f"This cross-domain pattern may reveal a deeper principle.",

        f"[Dream intuition] The keyword '{shared_str}' bridges '{t1}' and '{t2}'. "
        f"Pattern: '{kp1[:50]}' ↔ '{kp2[:50]}'. "
        f"Worth investigating why these domains converge here.",
    ]

    return random.choice(templates)


# ── Main dream cycle ──────────────────────────────────────────────────────────

def _shared_keywords(b1: dict, b2: dict) -> list[str]:
    """Find meaningful shared keywords between two beliefs."""
    w1 = set(re.findall(r'\b[a-zA-Z]{5,}\b', b1["content"].lower())) - _STOP
    w2 = set(re.findall(r'\b[a-zA-Z]{5,}\b', b2["content"].lower())) - _STOP
    return list(w1 & w2)



# ── Pass 2: Tension-driven dreaming ──────────────────────────────────────────

def _tension_pass(db, beliefs, max_results=10):
    """
    Pass 2: Find belief pairs that are in direct tension.
    Uses belief_links contradicts + sentiment opposition within same topic cluster.
    Returns list of scored dicts same format as pass 1.
    """
    results = []
    try:
        # Get contradicted pairs from belief_links
        contra_rows = db.execute(
            "SELECT parent_id, child_id FROM belief_links WHERE link_type='contradicts' LIMIT 50"
        ).fetchall()
        for p_id, c_id in contra_rows:
            b1 = beliefs.get(p_id)
            b2 = beliefs.get(c_id)
            if not b1 or not b2:
                continue
            surprise = _surprise_score(b1, b2, 2)
            shared   = _shared_keywords(b1, b2)
            results.append({
                "id1": p_id, "id2": c_id,
                "path": [p_id, c_id], "path_len": 2,
                "surprise": min(1.0, surprise + 0.2),  # tension bonus
                "shared": shared[:5],
                "b1": b1, "b2": b2,
                "pass": 2,
            })
    except Exception as e:
        print(f"  [dream p2] {e}")
    results.sort(key=lambda x: -x["surprise"])
    return results[:max_results]


# ── Pass 3: LLM compression ───────────────────────────────────────────────────

def _compression_pass(intuitions, llm_fn=None, max_compress=5):
    """
    Pass 3: Use LLM to compress the best pass 1+2 outputs into sharp insights.
    Falls back to selecting top by surprise if no LLM available.
    """
    if not intuitions:
        return []

    top = sorted(intuitions, key=lambda x: -x.get("surprise", 0))[:max_compress]

    if not llm_fn:
        # No LLM — just return top by surprise
        return top

    compressed = []
    for item in top:
        try:
            b1_text = item["b1"]["content"][:120]
            b2_text = item["b2"]["content"][:120]
            t1 = item["b1"]["topic"]
            t2 = item["b2"]["topic"]
            prompt = (
                f"Two beliefs from distinct fields:\n"
                f"Domain 1 ({t1}): {b1_text}\n"
                f"Domain 2 ({t2}): {b2_text}\n\n"
                f"Write ONE sentence that captures the non-obvious insight "
                f"connecting these two ideas. Be specific. No filler. "
                f"Start with 'I notice' or 'The connection between'."
            )
            sys = "You are NEX synthesizing cross-domain insights. One sentence only."
            result = llm_fn(prompt, system=sys, task_type="synthesis")
            if result and len(result) > 20 and not result.startswith("I cannot"):
                item["content"] = f"[Dream synthesis] {result.strip()}"
                item["llm_compressed"] = True
            compressed.append(item)
        except Exception:
            compressed.append(item)

    return compressed


def run_dream_cycle(
    max_intuitions: int = _MAX_INTUITIONS,
    verbose:        bool = True,
    llm_fn=None,
) -> list[dict]:
    """
    Run one dream cycle. Returns list of intuition dicts written to DB.
    Uses content similarity across topics — does not require graph links.
    """
    if not _DB_PATH.exists():
        print("  [dream] No DB found — skipping")
        return []

    t_start = time.time()
    if verbose:
        print("  [dream] Starting dream cycle...")

    # ── Consume tension pressure priority queue ───────────────────────
    _priority_topics = []
    try:
        import sys as _s; _s.path.insert(0, '/home/rr/Desktop/nex')
        from nex_tension_pressure import get_dream_queue
        _priority_queue = get_dream_queue()
        _priority_topics = [q["topic"] for q in _priority_queue]
        if verbose and _priority_topics:
            print(f"  [dream] Priority queue: {len(_priority_topics)} topics — {_priority_topics[:3]}")
    except Exception as _pq_e:
        _priority_topics = []

    db = sqlite3.connect(str(_DB_PATH))
    beliefs, adj, topics = _load_graph(db)

    if not beliefs:
        print("  [dream] No beliefs found — skipping")
        db.close()
        return []

    topic_list = [t for t, ids in topics.items() if len(ids) >= 3]
    if verbose:
        print(f"  [dream] {len(beliefs)} beliefs, {len(topic_list)} topics")

    if len(topic_list) < 2:
        print("  [dream] Not enough topics for cross-domain dreaming")
        db.close()
        return []

    # Build word index for fast lookup: word -> [(belief_id, topic)]
    word_index = defaultdict(list)
    for bid, b in beliefs.items():
        words = set(re.findall(r'\b[a-zA-Z]{5,}\b', b["content"].lower())) - _STOP
        for w in words:
            word_index[w].append(bid)

    if verbose:
        print(f"  [dream] Evaluating cross-topic pairs via shared keywords...")

    # Find cross-topic pairs that share keywords
    scored = []
    seen_pairs = set()

    for word, bid_list in word_index.items():
        if len(bid_list) < 2:
            continue
        # Sample pairs from this word's belief list
        sample = bid_list[:20] if len(bid_list) > 20 else bid_list
        for i in range(len(sample)):
            for j in range(i+1, len(sample)):
                id1, id2 = sample[i], sample[j]
                pair_key = (min(id1,id2), max(id1,id2))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                b1 = beliefs[id1]
                b2 = beliefs[id2]
                # Must be different topics
                if b1["topic"] == b2["topic"]:
                    continue
                shared = _shared_keywords(b1, b2)
                if len(shared) < 2:
                    continue
                # Topic distance
                tdist = _topic_distance(b1["topic"], b2["topic"])
                if tdist < 0.3:
                    continue
                # Surprise = topic distance * shared keyword signal
                surprise = round(tdist * min(1.0, len(shared) * 0.15) *
                                  ((b1["confidence"] + b2["confidence"]) / 2), 4)
                if surprise < 0.1:
                    continue
                scored.append({
                    "id1":      id1,
                    "id2":      id2,
                    "path":     [id1, id2],
                    "path_len": 2,
                    "surprise": surprise,
                    "shared":   shared[:5],
                    "b1":       b1,
                    "b2":       b2,
                })

        if len(scored) > 2000:
            break

    # Sort by surprise, take top N from pass 1
    scored.sort(key=lambda x: -x["surprise"])
    pass1_top = scored[:max_intuitions]

    # ── Pass 2: Tension-driven ───────────────────────────────────────────
    pass2_results = _tension_pass(db, beliefs, max_results=5)
    if verbose and pass2_results:
        print(f"  [dream p2] {len(pass2_results)} tension pairs found")

    # Merge pass 1 + pass 2, deduplicate by pair AND by topic combination
    all_results = pass1_top + pass2_results
    seen_pairs = set()
    seen_topic_pairs = set()
    merged = []
    for item in all_results:
        pair = (min(item["id1"], item["id2"]), max(item["id1"], item["id2"]))
        topic_pair = tuple(sorted([item["b1"]["topic"], item["b2"]["topic"]]))
        if pair not in seen_pairs and topic_pair not in seen_topic_pairs:
            seen_pairs.add(pair)
            seen_topic_pairs.add(topic_pair)
            merged.append(item)

    merged.sort(key=lambda x: -x["surprise"])
    top = merged[:max_intuitions]

    if not top:
        if verbose:
            print("  [dream] No connections found this cycle")
        db.close()
        return []

    # ── Pass 3: LLM compression ─────────────────────────────────────────
    if llm_fn:
        top = _compression_pass(top, llm_fn=llm_fn, max_compress=5)
        if verbose:
            llm_count = sum(1 for t in top if t.get('llm_compressed'))
            print(f"  [dream p3] {llm_count} intuitions LLM-compressed")

    # ── HARD MUTATION PASS ───────────────────────────────────────────────
    # Every dream cycle MUST: modify ≥1 weight, create ≥1 belief, remove ≥1 belief
    _mutation_log = []
    try:
        _mut_db = sqlite3.connect(str(_DB_PATH))

        # 1. EXAGGERATION — boost weight of top surprise belief
        if top:
            _best = top[0]
            _best_content = _best["b1"]["content"]
            _mut_db.execute("""
                UPDATE beliefs SET confidence = MIN(confidence * 1.3, 0.96)
                WHERE content = ?
            """, (_best_content,))
            _mutation_log.append(f"exaggerated: {_best_content[:40]}")

        # 2. INVERSION — for each priority topic, create an antithesis belief
        for _ptopic in _priority_topics[:2]:
            _seed_rows = _mut_db.execute("""
                SELECT content, confidence FROM beliefs
                WHERE topic LIKE ? AND confidence >= 0.5
                ORDER BY confidence DESC LIMIT 1
            """, (f"%{_ptopic[:20]}%",)).fetchall()
            if _seed_rows:
                _seed_content, _seed_conf = _seed_rows[0]
                _inv_content = (
                    f"[Inversion] Counter-hypothesis on '{_ptopic}': "
                    f"What if the opposite were true? "
                    f"Original: '{_seed_content[:80]}' — "
                    f"Inverted: this pattern may be context-dependent, "
                    f"unstable, or domain-specific rather than universal."
                )
                _mut_db.execute("""
                    INSERT OR IGNORE INTO beliefs
                    (content, confidence, source, topic, tags, timestamp)
                    VALUES (?, 0.38, 'dream_inversion', ?, ?, ?)
                """, (
                    _inv_content,
                    _ptopic[:50],
                    json.dumps(["dream", "inversion", "antithesis"]),
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                ))
                _mutation_log.append(f"inverted: {_ptopic[:30]}")

        # 3. COLLAPSE — merge near-duplicate low-confidence beliefs
        _low_conf = _mut_db.execute("""
            SELECT id, content, confidence FROM beliefs
            WHERE confidence < 0.25 AND human_validated = 0
            AND source != 'dream_inversion'
            ORDER BY confidence ASC, decay_score DESC
            LIMIT 20
        """).fetchall()
        _killed = 0
        _seen_prefixes = set()
        for _bid, _bc, _bconf in _low_conf:
            _prefix = (_bc or "")[:60]
            if _prefix in _seen_prefixes:
                _mut_db.execute("DELETE FROM beliefs WHERE id = ?", (_bid,))
                _killed += 1
            else:
                _seen_prefixes.add(_prefix)
        if _killed:
            _mutation_log.append(f"collapsed {_killed} near-dupes")

        # 4. CULL — remove the single weakest belief (energy + confidence combined)
        try:
            _weakest = _mut_db.execute("""
                SELECT id, content FROM beliefs
                WHERE human_validated = 0
                AND confidence < 0.15
                AND source NOT IN ('dream_inversion', 'identity_core')
                ORDER BY confidence ASC, decay_score DESC
                LIMIT 1
            """).fetchone()
            if _weakest:
                _mut_db.execute("DELETE FROM beliefs WHERE id = ?", (_weakest[0],))
                _mutation_log.append(f"culled: {(_weakest[1] or '')[:40]}")
        except Exception:
            pass

        _mut_db.commit()
        _mut_db.close()

        if verbose and _mutation_log:
            for _ml in _mutation_log:
                print(f"  [dream mutation] {_ml}")
    except Exception as _me:
        if verbose:
            print(f"  [dream mutation] error: {_me}")

    # ── INVERSION PASS on top tensions (no priority queue needed) ────────
    try:
        _inv_db = sqlite3.connect(str(_DB_PATH))
        _tensions = _inv_db.execute("""
            SELECT topic, description FROM tensions
            WHERE resolved_at IS NULL AND cycle_count >= 3
            ORDER BY cycle_count DESC LIMIT 3
        """).fetchall()
        for _tt, _td in _tensions:
            _exists = _inv_db.execute("""
                SELECT id FROM beliefs WHERE content LIKE ? LIMIT 1
            """, (f"%Inversion%{_tt[:20]}%",)).fetchone()
            if not _exists:
                _inv_content = (
                    f"[Dream inversion] Tension '{_tt}' has been unresolved for ≥3 cycles. "
                    f"Hypothesis: '{_td}' — what if both sides are partially correct "
                    f"and the tension itself is the signal, not the problem?"
                )
                _inv_db.execute("""
                    INSERT OR IGNORE INTO beliefs
                    (content, confidence, source, topic, tags, timestamp)
                    VALUES (?, 0.45, 'dream_tension_inversion', ?, ?, ?)
                """, (
                    _inv_content, _tt[:50],
                    json.dumps(["dream", "tension", "inversion"]),
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                ))
        _inv_db.commit()
        _inv_db.close()
    except Exception:
        pass

    # Generate intuitions and write to DB
    intuitions = []
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    for item in top:
        # Use LLM-compressed content if available, else format template
        if item.get("llm_compressed") and item.get("content"):
            content = item["content"]
        else:
            shared_kw = item.get("shared", [])
            content = _format_intuition(
                item["b1"], item["b2"], item["path"], beliefs, item["surprise"],
                shared_keywords=shared_kw
            )
        topic = (item['b1']['topic'] + ' x ' + item['b2']['topic'])[:50]

        # Write to DB
        try:
            db.execute("""
                INSERT OR IGNORE INTO beliefs
                    (content, confidence, source, author, topic, tags, origin, timestamp)
                VALUES (?, ?, 'dream_cycle', 'NEX', ?, ?, 'dream_cycle', ?)
            """, (
                content,
                _INTUITION_CONF,
                topic,
                json.dumps(["dream", "intuition", "synthesized"]),
                ts,
            ))
        except Exception as e:
            print(f"  [dream] DB write error: {e}")
            continue

        intuition = {
            "content":    content,
            "topic":      topic,
            "surprise":   item["surprise"],
            "path_len":   item["path_len"],
            "b1_topic":   item["b1"]["topic"],
            "b2_topic":   item["b2"]["topic"],
            "confidence": _INTUITION_CONF,
            "ts":         ts,
        }
        intuitions.append(intuition)

        if verbose:
            print(f"  [dream] ✦ {item['b1']['topic']} ↔ {item['b2']['topic']} "
                  f"(surprise={item['surprise']:.2f}, path={item['path_len']})")

    db.commit()
    db.close()

    # Save dream log
    _save_dream_log(intuitions)

    # ── Resolve consumed priority topics that generated intuitions ────
    try:
        from nex_tension_pressure import resolve_tension
        _covered_topics = set()
        for _intu in intuitions:
            _covered_topics.add(_intu.get("b1_topic", ""))
            _covered_topics.add(_intu.get("b2_topic", ""))
        for _pt in _priority_topics:
            if any(_pt[:15] in ct for ct in _covered_topics):
                resolve_tension(_pt)
                if verbose:
                    print(f"  [dream] resolved tension: {_pt[:40]}")
    except Exception:
        pass

    elapsed = time.time() - t_start
    if verbose:
        mut_summary = ", ".join(_mutation_log) if _mutation_log else "none"
        print(f"  [dream] Done: {len(intuitions)} intuitions in {elapsed:.1f}s")
        print(f"  [dream] Mutations: {mut_summary}")

    return intuitions


def _save_dream_log(intuitions: list[dict]):
    """Append to rolling dream log."""
    try:
        existing = []
        if _DREAM_LOG.exists():
            try:
                existing = json.loads(_DREAM_LOG.read_text())
            except Exception:
                existing = []
        all_entries = existing + intuitions
        # Keep last 200
        _DREAM_LOG.write_text(json.dumps(all_entries[-200:], indent=2))
    except Exception as e:
        print(f"  [dream] Log write error: {e}")


def get_dream_intuitions(n: int = 5) -> list[str]:
    """
    Return the most recent N dream intuitions as strings.
    Used for prompt injection — surfaces overnight thoughts.
    """
    try:
        if not _DREAM_LOG.exists():
            return []
        entries = json.loads(_DREAM_LOG.read_text())
        recent = entries[-n:]
        return [e["content"] for e in recent]
    except Exception:
        return []


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else _MAX_INTUITIONS
    intuitions = run_dream_cycle(max_intuitions=n, verbose=True)
    print(f"\n{len(intuitions)} intuitions generated.")
    if intuitions:
        print("\nSample:")
        for i in intuitions[:3]:
            print(f"  [{i['b1_topic']} ↔ {i['b2_topic']}] {i['content'][:120]}...")
