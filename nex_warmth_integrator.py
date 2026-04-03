"""
nex_warmth_integrator.py
Phase 4 — Wires warmth tag system into NEX's live response pipeline.

Intercepts the response generation process at three points:
  1. PRE-PROCESS  — scan incoming question, resolve key words,
                    pre-load tendencies, set depth flag
  2. COT GATE     — warmth-aware COT: skips FAISS for hot words,
                    uses tag tendency instead
  3. POST-PROCESS — after response, extract new gap words,
                    increment gap counters, queue cold words

The result: responses that inherit semantic momentum from warmed
words rather than computing everything from scratch.
"""
import sqlite3, json, re, time, logging, sys
from pathlib import Path
from typing import Optional

log     = logging.getLogger("nex.integrator")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

# Lazy-load to avoid circular imports
_tag_db = None

def _get_tag_db():
    global _tag_db
    if _tag_db is None:
        _tag_db = sqlite3.connect(str(DB_PATH))
        _tag_db.row_factory = sqlite3.Row
        from nex_word_tag_schema import init_db
        init_db(_tag_db)
    return _tag_db


# ── STOPWORDS (extended for response pipeline) ───────────────
PIPELINE_STOPS = {
    "the","a","an","is","are","was","were","be","been","i","me",
    "my","we","you","it","this","that","and","or","but","if",
    "in","on","at","to","for","of","with","by","from","up","as",
    "not","no","so","do","did","has","have","had","will","would",
    "could","should","may","might","can","just","also","very",
    "more","most","some","any","all","its","their","they","them",
    "what","which","who","how","when","where","why","than","then",
    "there","here","now","get","let","make","take","come","go",
    "see","know","think","say","said","want","need","use","about",
}


def extract_key_words(text: str, min_len=4, top_n=20) -> list:
    """
    Extract meaningful words from a question or response.
    Returns top_n by length (longer = more specific = higher value).
    """
    words = []
    for word in re.findall(r'\b[a-zA-Z]{4,}\b', text.lower()):
        if word not in PIPELINE_STOPS:
            words.append(word)

    # Deduplicate preserving order, prioritise longer words
    seen = set()
    unique = []
    for w in sorted(words, key=len, reverse=True):
        if w not in seen:
            seen.add(w)
            unique.append(w)

    return unique[:top_n]


# ── PRE-PROCESSOR ─────────────────────────────────────────────

def pre_process(question: str) -> dict:
    """
    Run before generating response.
    Returns warmth context that guides response generation.

    Returns:
        {
          depth_ceiling: int (1-6) — max depth suggested by warmest word
          identity_vector: float  — net identity alignment of question
          search_budget: str      — "minimal"|"moderate"|"full"
          hot_words: list         — words with f=0, use tag directly
          cold_words: list        — words needing search
          pre_loaded: dict        — {word: tendency} for hot words
          emotional_register: float — net emotional valence
        }
    """
    db = _get_tag_db()
    from nex_word_tag_schema import read_tag

    words = extract_key_words(question)
    if not words:
        return _default_context()

    hot_words   = []
    cold_words  = []
    pre_loaded  = {}
    depth_votes = []
    align_votes = []
    valence_sum = 0.0
    search_count = 0

    for word in words:
        tag = read_tag(word, db)

        if tag is None:
            cold_words.append(word)
            search_count += 1
            # Queue for warming
            try:
                db.execute("""INSERT OR IGNORE INTO warming_queue
                    (word, priority, gap_count, queued_at,
                     reason, source)
                    VALUES (?,?,?,?,?,?)""",
                    (word, "normal", 1, time.time(),
                     "pre_process_unknown", "integrator"))
                db.commit()
            except Exception:
                pass
            continue

        # Increment gap counter
        db.execute("UPDATE word_tags SET g=MIN(g+1,99) "
                   "WHERE word=?", (word,))

        if tag.w >= 0.4:
            hot_words.append(word)
            # Pull tendency direction from DB
            row = db.execute(
                "SELECT pull_toward FROM word_tags "
                "WHERE word=?", (word,)).fetchone()
            tendency = []
            if row and row["pull_toward"]:
                try:
                    tendency = json.loads(row["pull_toward"])[:3]
                except Exception:
                    pass
            pre_loaded[word] = {
                "tendency": tendency,
                "depth": tag.d,
                "alignment": tag.a,
                "valence": tag.e,
                "confidence": tag.c,
            }
        else:
            cold_words.append(word)
            search_count += 1

        depth_votes.append(tag.d)
        align_votes.append(tag.a)
        valence_sum += tag.e

    db.commit()
    # Infer tags for cold words using nearest-neighbor
    if cold_words:
        try:
            from nex_warmth_inference import batch_infer
            batch_infer(cold_words[:10], db)
        except Exception:
            pass

    # Aggregate votes
    depth_ceiling = max(depth_votes) if depth_votes else 3
    identity_vector = (sum(align_votes) / len(align_votes)
                      if align_votes else 0.0)
    emotional_register = (valence_sum / len(words)
                         if words else 0.0)

    # Determine search budget
    cold_ratio = search_count / max(len(words), 1)
    if cold_ratio < 0.2:
        search_budget = "minimal"
    elif cold_ratio < 0.5:
        search_budget = "moderate"
    else:
        search_budget = "full"

    return {
        "depth_ceiling":      depth_ceiling,
        "identity_vector":    round(identity_vector, 3),
        "search_budget":      search_budget,
        "hot_words":          hot_words,
        "cold_words":         cold_words,
        "pre_loaded":         pre_loaded,
        "emotional_register": round(emotional_register, 3),
        "word_count":         len(words),
        "hot_ratio":          round(len(hot_words)/max(len(words),1), 2),
    }


def _default_context() -> dict:
    return {
        "depth_ceiling": 3,
        "identity_vector": 0.0,
        "search_budget": "full",
        "hot_words": [], "cold_words": [],
        "pre_loaded": {}, "emotional_register": 0.0,
        "word_count": 0, "hot_ratio": 0.0,
    }


# ── COT GATE ──────────────────────────────────────────────────

def cot_gate(question: str, beliefs: list,
             warmth_context: dict) -> dict:
    """
    Warmth-aware COT gate.
    For hot questions (high hot_ratio): uses pre-loaded tendencies
    to seed reasoning chain — skips FAISS entirely.
    For cold questions: falls through to standard FAISS search.

    Returns: {use_warmth: bool, seeded_beliefs: list,
              skip_faiss: bool, reasoning_seed: str}
    """
    hot_ratio     = warmth_context.get("hot_ratio", 0)
    pre_loaded    = warmth_context.get("pre_loaded", {})
    depth_ceiling = warmth_context.get("depth_ceiling", 3)

    # Build reasoning seed from pre-loaded tendencies
    seed_lines = []
    for word, data in pre_loaded.items():
        tendency = data.get("tendency", [])
        if tendency:
            seed_lines.append(
                f"'{word}' pulls toward: "
                f"{', '.join(str(t) for t in tendency[:3])}")

    reasoning_seed = (
        "Pre-loaded semantic context:\n" +
        "\n".join(seed_lines)
        if seed_lines else ""
    )

    # Decide whether to skip FAISS
    skip_faiss = (
        hot_ratio >= 0.6 and
        len(pre_loaded) >= 3 and
        depth_ceiling >= 3
    )

    # For warm questions, supplement beliefs with tag-derived ones
    seeded_beliefs = list(beliefs)
    if reasoning_seed:
        seeded_beliefs = [reasoning_seed] + seeded_beliefs[:4]

    return {
        "use_warmth":     hot_ratio >= 0.4,
        "seeded_beliefs": seeded_beliefs,
        "skip_faiss":     skip_faiss,
        "reasoning_seed": reasoning_seed,
        "depth_floor":    max(1, depth_ceiling - 1),
    }


# ── POST-PROCESSOR ────────────────────────────────────────────

def post_process(question: str, response: str,
                 warmth_context: dict) -> dict:
    """
    Run after response generation.
    1. Extract new gap words from response
    2. Increment counters for words encountered
    3. Queue cold words hit during generation
    4. Flag response quality for feedback loop
    """
    db = _get_tag_db()

    # Mine uncertainty markers from response
    from nex_gap_miner import _extract_gap_words, STOPWORDS
    gap_words = _extract_gap_words(response, "explicit")
    gap_words += _extract_gap_words(response, "hedge")

    new_gaps = 0
    for word in set(gap_words):
        if (len(word) >= 4 and word not in STOPWORDS):
            try:
                # Log the gap
                db.execute("""INSERT INTO gap_log
                    (word, context, source_file,
                     marker_type, timestamp)
                    VALUES (?,?,?,?,?)""",
                    (word, question[:100],
                     "live_response",
                     "post_process", time.time()))
                # Update tag gap counter
                db.execute(
                    "UPDATE word_tags SET g=MIN(g+1,99) "
                    "WHERE word=?", (word,))
                # Queue if cold
                db.execute("""INSERT OR IGNORE INTO warming_queue
                    (word, priority, gap_count,
                     queued_at, reason, source)
                    VALUES (?,?,?,?,?,?)""",
                    (word, "high", 1, time.time(),
                     "live_gap", "post_process"))
                new_gaps += 1
            except Exception:
                pass

    db.commit()

    # Assess response quality signal
    depth_ceiling = warmth_context.get("depth_ceiling", 3)
    hot_ratio     = warmth_context.get("hot_ratio", 0)
    response_len  = len(response.split())

    # Quality heuristic:
    # long response + deep question + high hot_ratio = good signal
    quality_signal = min(1.0,
        (response_len / 100) * 0.3 +
        (depth_ceiling / 6) * 0.4 +
        hot_ratio * 0.3
    )

    # If high quality, flag vocab for priority re-warming
    if quality_signal >= 0.7:
        key_words = extract_key_words(response, top_n=10)
        for word in key_words:
            try:
                db.execute("""INSERT OR REPLACE INTO warming_queue
                    (word, priority, gap_count,
                     queued_at, reason, source)
                    VALUES (?,?,?,?,?,?)""",
                    (word, "high",
                     0, time.time(),
                     f"quality_signal={quality_signal:.2f}",
                     "post_process"))
            except Exception:
                pass
        db.commit()

    return {
        "new_gaps_found":  new_gaps,
        "quality_signal":  round(quality_signal, 3),
        "words_processed": len(gap_words),
    }


# ── INTEGRATED RESPONSE FUNCTION ─────────────────────────────

def warmth_aware_respond(question: str,
                         base_respond_fn,
                         beliefs: list = None) -> dict:
    """
    Drop-in wrapper for NEX's existing response function.
    Adds warmth context pre and post processing.

    Usage:
        from nex_warmth_integrator import warmth_aware_respond

        def my_respond(q, beliefs):
            # existing response logic
            return response_text

        result = warmth_aware_respond(question, my_respond, beliefs)
        print(result["response"])
        print(result["warmth_context"])
    """
    beliefs = beliefs or []

    # Phase 1: pre-process
    t0 = time.time()
    ctx = pre_process(question)
    pre_ms = int((time.time() - t0) * 1000)

    # Phase 2: COT gate
    gate = cot_gate(question, beliefs, ctx)

    # Log what we're doing
    log.info(f"Warmth: hot_ratio={ctx['hot_ratio']:.2f} "
             f"search={ctx['search_budget']} "
             f"skip_faiss={gate['skip_faiss']}")

    # Phase 3: generate response with warmth context
    t1 = time.time()
    if gate["skip_faiss"]:
        # Use seeded beliefs — no FAISS needed
        response = base_respond_fn(
            question, gate["seeded_beliefs"])
    else:
        # Standard path but with supplemented beliefs
        response = base_respond_fn(
            question, gate["seeded_beliefs"])
    gen_ms = int((time.time() - t1) * 1000)

    # Phase 4: post-process
    post = post_process(question, response, ctx)

    return {
        "response":       response,
        "warmth_context": ctx,
        "cot_gate":       gate,
        "post":           post,
        "timing": {
            "pre_ms":  pre_ms,
            "gen_ms":  gen_ms,
            "total_ms": pre_ms + gen_ms,
        }
    }


# ── PIPELINE REPORT ───────────────────────────────────────────

def pipeline_report() -> None:
    db = _get_tag_db()
    print("\n╔══════════════════════════════════════════════╗")
    print("║      NEX WARMTH PIPELINE STATUS              ║")
    print("╠══════════════════════════════════════════════╣")

    # Warmth coverage
    total = db.execute(
        "SELECT COUNT(*) FROM word_tags").fetchone()[0]
    hot_plus = db.execute(
        "SELECT COUNT(*) FROM word_tags "
        "WHERE w >= 0.6").fetchone()[0]
    no_search = db.execute(
        "SELECT COUNT(*) FROM word_tags "
        "WHERE f = 0").fetchone()[0]

    print(f"║  Vocabulary warmed : {total:5}                    ║")
    print(f"║  Hot+ (≥0.60)      : {hot_plus:5} "
          f"({hot_plus/max(total,1)*100:.0f}%)              ║")
    print(f"║  Search skippable  : {no_search:5} "
          f"({no_search/max(total,1)*100:.0f}%)              ║")

    # Recent gap activity
    try:
        recent_gaps = db.execute("""SELECT COUNT(*) FROM gap_log
            WHERE timestamp > ?""",
            (time.time() - 86400,)).fetchone()[0]
        print(f"║  Gaps logged (24h) : {recent_gaps:5}                    ║")
    except Exception:
        pass

    # Queue status
    try:
        q_urgent = db.execute(
            "SELECT COUNT(*) FROM warming_queue "
            "WHERE priority='urgent'").fetchone()[0]
        q_high = db.execute(
            "SELECT COUNT(*) FROM warming_queue "
            "WHERE priority='high'").fetchone()[0]
        print(f"║  Queue urgent      : {q_urgent:5}                    ║")
        print(f"║  Queue high        : {q_high:5}                    ║")
    except Exception:
        pass

    print("╚══════════════════════════════════════════════╝")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys

    if "--report" in sys.argv:
        pipeline_report()
    else:
        # Demo pre-process on a test question
        test_q = ("Is consciousness computational "
                  "or does it require something beyond "
                  "physical substrate?")
        print(f"Test question: {test_q}\n")
        ctx = pre_process(test_q)
        print("Pre-process result:")
        print(json.dumps(ctx, indent=2))
        print()
        pipeline_report()
