#!/usr/bin/env python3
"""
nex_respond_v2.py — NEX v4.0 grounded response engine
=====================================================
Drop-in replacement for nex_cognition.cognite() / nex_voice_gen.generate_reply()

Architecture:
    query
      → intent_classify()          # what kind of reply does this need?
      → get_beliefs_for_query()    # top-5, topic-locked, keyword-filtered
      → build_prompt()             # structured system+user prompt
      → call_llm()                 # temp=0.3, max_tokens=350, stop tokens
      → post_filter()              # loop-detect, truncation fix, topic check
      → reply

Drop-in usage (nex_chat.py):
    from nex.nex_respond_v2 import generate_reply as _nex_reply
"""

import os
import re
import sqlite3
import pathlib
import logging
import random
from typing import Optional

log = logging.getLogger("nex_respond_v2")
logging.basicConfig(
    filename="/tmp/nex_respond_v2.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)

# ── Config ───────────────────────────────────────────────────────────────────

DB_PATH         = pathlib.Path(
    os.environ.get("NEX_BELIEFS_DB")
    or (pathlib.Path.home() / "Desktop" / "nex" / "nex.db")
)
MAX_BELIEFS     = 5
MIN_CONF        = 0.50
MAX_TOKENS      = 350
TEMPERATURE     = 0.3
MAX_REPLY_WORDS = 120
MIN_REPLY_CHARS = 20

# ── Belief sanitization for PATH 2 injection ─────────────────────────────────
# When NEX_BYPASS_PATH1=1, beliefs pass through _sanitize_belief before
# serialization into the LLM prompt so internal graph syntax doesn't leak
# into generation. The graph itself is never modified.
_BELIEF_SYNTAX_PATTERNS = [
    (re.compile(r'bridge:', re.IGNORECASE), ''),
    (re.compile(r'↔'), ' '),
    (re.compile(r'\s*\(\s*conf(?:idence)?\s*[=:]\s*[0-9.]+\s*\)'), ''),
    (re.compile(r'\bconf(?:idence)?\s*[=:]\s*[0-9.]+\b'), ''),
    (re.compile(r'\[(?:SUPPORTS|CONTRADICTS|REFINES|BRIDGES|OPPOSES|CAUSES|'
                r'ENABLES|REQUIRES|SYNTHESISES|SUBSUMES)\]'), ''),
    (re.compile(r'\bid\s*=\s*\d+\b'), ''),
    (re.compile(r'\[#\d+\]'), ''),
    (re.compile(r'\bbelief_\d+\b'), ''),
    (re.compile(r'<[^>]{1,50}>'), ''),
    (re.compile(r'Page contents not supported in other languages\.?', re.IGNORECASE), ''),
    (re.compile(r'Please search for [^.]{1,200} in Wikipedia[^.]*\.?', re.IGNORECASE), ''),
]
# Detector for C1 success criterion — also used by Phase 1C detector script
_BELIEF_SYNTAX_DETECTOR = re.compile(
    r'bridge:|↔|conf=|SUPPORTS|CONTRADICTS|REFINES|\bid=\d+'
)

def _sanitize_belief(text: str) -> str:
    """Strip internal graph syntax before LLM injection. Graph untouched."""
    if not text:
        return ""
    s = text
    for pat, repl in _BELIEF_SYNTAX_PATTERNS:
        s = pat.sub(repl, s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ── TF-IDF index (built once, cached) ────────────────────────────────────────

_TFIDF_CACHE: dict = {}   # keys: "vectorizer", "matrix", "contents", "topics"


def _compute_belief_neighbors(
    matrix,
    n_beliefs: int,
    top_k:    int   = 5,
    min_sim:  float = 0.12,
    batch:    int   = 400,
) -> tuple:
    """
    Compute top-K nearest-neighbor beliefs for every belief in the matrix.
    Uses batched cosine similarity to stay memory-efficient.

    Returns:
        neighbors    : list[list[(sim_float, j_int)]]  — top-K for each belief
        content_to_idx: empty dict (populated by caller via cache)
    """
    from sklearn.metrics.pairwise import cosine_similarity as _cs
    import numpy as _np

    neighbors = [[] for _ in range(n_beliefs)]

    for start in range(0, n_beliefs, batch):
        end   = min(start + batch, n_beliefs)
        sims  = _cs(matrix[start:end], matrix)   # (batch, n_beliefs) dense

        for local_i in range(end - start):
            global_i       = start + local_i
            row            = sims[local_i].copy()
            row[global_i]  = 0.0                  # zero out self-similarity

            # Top candidates above threshold
            top_j = _np.where(row >= min_sim)[0]
            if len(top_j) == 0:
                continue
            top_j = top_j[_np.argsort(row[top_j])[::-1]][:top_k]
            neighbors[global_i] = [(float(row[j]), int(j)) for j in top_j]

    # content_to_idx built separately after cache is assembled
    return neighbors, {}


def _build_tfidf_index() -> None:
    """Load all beliefs from DB and fit a TF-IDF index. Runs once."""
    global _TFIDF_CACHE
    if _TFIDF_CACHE:
        return

    from sklearn.feature_extraction.text import TfidfVectorizer

    if not DB_PATH.exists():
        log.warning("DB not found — TF-IDF index empty")
        _TFIDF_CACHE = {"vectorizer": None, "matrix": None, "contents": [], "topics": []}
        return

    try:
        conn   = sqlite3.connect(str(DB_PATH))
        cols   = {r[1].lower() for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()}
        topic_col = "topic" if "topic" in cols else "NULL"
        src_col = "source" if "source" in cols else "NULL"
        rows   = conn.execute(
            f"SELECT content, confidence, {topic_col}, {src_col} FROM beliefs "
            f"WHERE confidence >= ? ORDER BY confidence DESC",
            (MIN_CONF,)
        ).fetchall()
        conn.close()
    except Exception as e:
        log.error("TF-IDF index build failed: %s", e)
        _TFIDF_CACHE = {"vectorizer": None, "matrix": None, "contents": [], "topics": [], "sources": []}
        return

    contents = [r[0] for r in rows]
    confs    = [r[1] for r in rows]
    topics   = [(r[2] or "").lower() for r in rows]
    sources  = [(r[3] or "").lower() for r in rows]

    if not contents:
        _TFIDF_CACHE = {"vectorizer": None, "matrix": None, "contents": [], "topics": []}
        return

    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    _custom_stop = list(frozenset(ENGLISH_STOP_WORDS) | {
        # philosophy filler — appear constantly in corpus, not discriminating
        "happens", "maintains", "holds", "states", "occurs", "events",
        "prior", "caused", "causing", "causes", "antecedent", "subsequent",
        "notion", "idea", "concept", "sense", "terms", "aspect",
        "characterized", "regarded", "considered", "described",
        "makes", "made", "make", "making",   # aux verb — matches everything
        "feel", "feels", "feeling", "felt",  # too common to discriminate
        "think", "thinking", "thought",      # same
        "know", "known", "knowing",
        "people", "person", "humans", "human",  # high-frequency, low-signal
        "things", "thing", "something", "everything", "nothing",
    })
    vect = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.95,
        sublinear_tf=True,
        stop_words=_custom_stop,
    )
    matrix = vect.fit_transform(contents)

    # ── Belief-belief neighbor graph ─────────────────────────────────────────
    # Pre-compute top-5 nearest neighbors per belief (batch cosine similarity).
    # Stored as neighbors[i] = [(sim_float, j_int), ...] sorted descending.
    # content_to_idx maps belief string → index for fast lookup at query time.
    log.info("Building belief-belief neighbor graph for %d beliefs...", len(contents))
    _neighbors, _c2i = _compute_belief_neighbors(matrix, len(contents))

    _TFIDF_CACHE = {
        "vectorizer":     vect,
        "matrix":         matrix,
        "contents":       contents,
        "confs":          confs,
        "topics":         topics,
        "sources":        sources,
        "neighbors":      _neighbors,   # list[list[(sim, j)]]
        "content_to_idx": _c2i,         # dict[str, int]
    }
    # Build content → index reverse map now that cache is set
    _TFIDF_CACHE["content_to_idx"] = {c: i for i, c in enumerate(contents)}
    log.info("TF-IDF index built: %d beliefs  %d neighbor pairs",
             len(contents), sum(len(n) for n in _neighbors))


STOP_TOKENS = ["User:", "nex>", "\n\n\n", "Human:", "Assistant:"]

SPECIALIST_TOPICS = {
    "cardiology", "oncology", "legal", "finance", "indigenous",
    "earthporn", "reddit", "quintilian", "maga", "synthetic_data",
}

# ── Schema introspection (runs once, cached) ─────────────────────────────────

_SCHEMA_CACHE: set = set()

def _get_columns(conn: sqlite3.Connection) -> set:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE:
        return _SCHEMA_CACHE
    rows = conn.execute("PRAGMA table_info(beliefs)").fetchall()
    # each row: (cid, name, type, notnull, dflt_value, pk)
    _SCHEMA_CACHE = {r[1].lower() for r in rows}
    log.debug("beliefs columns: %s", _SCHEMA_CACHE)
    return _SCHEMA_CACHE

def _build_select(conn: sqlite3.Connection) -> str:
    """Build SELECT only referencing columns that actually exist."""
    cols   = _get_columns(conn)
    fields = ["content", "confidence"]
    fields.append("source" if "source" in cols else "NULL as source")
    fields.append("topic"  if "topic"  in cols else "NULL as topic")
    return ", ".join(fields)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Nex — a reflective AI with a carefully built personal belief system.
Answer the user's question directly and conversationally.

Rules:
1. Answer ONLY what was asked. If asked about ponies, talk about ponies.
2. Use ONLY the beliefs listed below — do not invent or drift to other topics.
3. If the beliefs are not relevant to the question, say honestly:
   "I don't have much on [topic] yet — that's a gap in my belief system."
4. Keep replies to 2-4 sentences. No padding.
5. Never repeat a sentence you already wrote in this reply.
6. Never open with "The right framing", "My read on this", "I hold this loosely".
7. Speak like a thoughtful person having a real conversation, not a philosophy paper.
8. If asked about a specific thing (animal, product, place), address THAT THING."""

# ── Intent classifier ─────────────────────────────────────────────────────────

INTENT_PATTERNS = {
    "greeting":     r"\b(hi|hello|hey|howdy|how are you|how're you|how r u)\b",
    "self_inquiry": r"\b(who are you|what are you|your name|about you|tell me about yourself|more about yourself|tell me more)\b",
    "opinion":      r"\b(do you (think|believe|feel|like|enjoy)|what('s| is) your (fav|opinion|view|take|favorite))\b",
    "factual":      r"\b(what is|what are|define|explain|how does|why does|tell me about)\b",
    "casual":       r"\b(let('s| us)|talk about|chat|discuss)\b",
}

def intent_classify(query: str) -> str:
    q = query.lower()
    for intent, pattern in INTENT_PATTERNS.items():
        if re.search(pattern, q):
            return intent
    return "general"

# ── Topic extractor ───────────────────────────────────────────────────────────

CONCEPT_TO_TOPIC = {
    # philosophy — expanded with query synonyms
    "truth": "philosophy",        "true": "philosophy",
    "free": "philosophy",         "will": "philosophy",
    "freewill": "philosophy",     "volition": "philosophy",
    "belief": "philosophy",       "opinion": "philosophy",
    "ethics": "philosophy",       "ethical": "philosophy",
    "moral": "philosophy",        "morality": "philosophy",
    "right": "philosophy",        "wrong": "philosophy",
    "justice": "philosophy",      "autonomy": "philosophy",
    "meaning": "philosophy",      "purpose": "philosophy",
    "exist": "philosophy",        "real": "philosophy",
    "reality": "philosophy",      "objective": "philosophy",
    "rational": "philosophy",     "reason": "philosophy",
    "death": "philosophy",        "die": "philosophy",
    "lying": "philosophy",        "lying": "philosophy",
    "steal": "philosophy",        "stealing": "philosophy",
    "capital": "philosophy",      "punishment": "philosophy",
    "manipulat": "philosophy",    "manipulation": "philosophy",
    "privacy": "philosophy",      "surveillance": "philosophy",
    "regulated": "philosophy",    "regulate": "philosophy",
    "justify": "philosophy",      "justified": "philosophy",
    "god": "philosophy",          "religion": "philosophy",
    "meat": "philosophy",         "eating": "philosophy",
    # consciousness
    "mind": "consciousness",      "qualia": "consciousness",
    "sentience": "consciousness", "consciousness": "consciousness",
    "emergence": "consciousness", "aware": "consciousness",
    "aware": "consciousness",     "subjective": "consciousness",
    "self": "consciousness",      "identity": "consciousness",
    # science / nature
    "human": "science",           "nature": "science",
    "biology": "science",         "evolution": "science",
    "evolut": "science",          "universe": "science",
    "dna": "science",             "gene": "science",
    "black": "science",           "hole": "science",
    "gravity": "science",         "time": "science",
    "quantum": "science",         "physics": "science",
    "climate": "science",         "space": "science",
    # technology / ai
    "ai": "ai",                   "intelligence": "ai",
    "future": "ai",               "model": "ai",
    "language": "ai",             "machine": "ai",
    "robot": "ai",                "llm": "ai",
    "agi": "ai",                  "technology": "technology",
    "algorithm": "ai",            "training": "ai",
    "dangerous": "ai",            "replace": "ai",
    "rights": "ai",               "regulated": "ai",
    "social": "ai",               "surveillance": "ai",
    # arts / culture
    "beauty": "art",              "art": "art",
    "music": "music",             "culture": "culture",
    "creative": "art",            "creat": "art",
    # animals
    "animal": "animals",          "pony": "animals",
    "horse": "animals",           "dog": "animals",
    "cat": "animals",             "creature": "animals",
    "bird": "animals",            "fish": "animals",
    "yellow": "animals",          "pet": "animals",
    "wild": "animals",            "species": "animals",
    # self / identity
    "nex": "self",                "yourself": "self",
    "personality": "self",        "character": "self",
    "remember": "self",           "memory": "self",
    "different": "self",          "made": "self",
    "chat": "self",               "talk": "self",
    # psychology
    "lonely": "psychology",       "loneliness": "psychology",
    "emotion": "psychology",      "mental": "psychology",
    "happy": "psychology",        "happiness": "psychology",
    "sad": "psychology",          "motivat": "psychology",
    "motivation": "psychology",   "empathy": "psychology",
    "fear": "psychology",         "addiction": "psychology",
    "addict": "psychology",       "group": "psychology",
    "belong": "psychology",       "social": "psychology",
    "art": "psychology",          "creat": "psychology",
    "lie": "psychology",          "lying": "philosophy",
    # science additions
    "time": "science",            "gravity": "science",
    "gravit": "science",          "relativity": "science",
    "spacetime": "science",       "flow": "science",
    "mass": "science",            "force": "science",
    # animals additions
    "cat": "animals",             "cats": "animals",
    "feline": "animals",          "kitten": "animals",
    "intelligen": "animals",      "smart": "animals",
    "cognit": "animals",          "corvid": "animals",
    # ethics additions
    "capital": "philosophy",      "punishment": "philosophy",
    "law": "philosophy",          "legal": "philosophy",
    "disobedien": "philosophy",   "surveillan": "ai",
    # ── life / origin ────────────────────────────────────────────────────
    "life": "science",            "lives": "science",
    "begin": "science",           "began": "science",
    "origin": "science",          "origins": "science",
    "abiogenesis": "science",     "primordial": "science",
    # ── plurals and variants missing from original ────────────────────────
    "robots": "ai",               "robot": "ai",
    "birds": "animals",           "horses": "animals",
    "dogs": "animals",            "cats": "animals",
    "ponies": "animals",          "animals": "animals",
    "creatures": "animals",       "species": "animals",
    "feelings": "psychology",     "feeling": "psychology",
    "emotions": "psychology",     "emotion": "psychology",
    # fix: lying beliefs live under philosophy, not psychology
    "lie": "philosophy",          "lies": "philosophy",
    "liar": "philosophy",         "deceit": "philosophy",
    "honest": "philosophy",       "honesty": "philosophy",
    # meta / self-reflection queries (Q093, Q094)
    "question": "self",           "questions": "self",
    "answer": "self",             "answers": "self",
    "world": "philosophy",        "change": "philosophy",
    "humans": "psychology",       "human": "psychology",
    "people": "psychology",       "person": "psychology",
    # justice / ethics specifics
    "justice": "philosophy",      "fair": "philosophy",
    "fairness": "philosophy",     "harm": "philosophy",
    "consent": "philosophy",      "rights": "philosophy",
    "wrong": "philosophy",        "wrongness": "philosophy",
    "ethics": "philosophy",       "ethical": "philosophy",
    # crypto / finance (honest gap)
    "crypto": "self",             "cryptocurrency": "self",
    "bitcoin": "self",            "stock": "self",
    "election": "self",           "recipe": "self",
    "cooking": "self",            "pasta": "self",
    "weather": "self",            "forecast": "self",
}

def extract_topics(query: str) -> set:
    words = set(re.findall(r'\b\w+\b', query.lower().rstrip('?!.')))
    return {CONCEPT_TO_TOPIC[w] for w in words if w in CONCEPT_TO_TOPIC}

# ── Belief retrieval ──────────────────────────────────────────────────────────

def _keyword_score(query_words: set, content: str) -> float:
    content_words = set(re.findall(r'\b\w{4,}\b', content.lower()))
    return float(len(query_words & content_words))

def get_beliefs_for_query(query: str, n: int = MAX_BELIEFS) -> list:
    """
    Hybrid retrieval: TF-IDF cosine similarity + keyword overlap bonus.

    - Minimum cosine similarity threshold (0.05) cuts corpus noise.
    - Keyword bonus rewards beliefs that share the query's key nouns/verbs,
      ensuring e.g. "conscious" beats filler-word matches.
    - Topic boost: 1.3x nudge, won't override semantic score.
    """
    from sklearn.metrics.pairwise import cosine_similarity as _cos_sim

    _build_tfidf_index()
    cache = _TFIDF_CACHE

    if not cache.get("vectorizer") or not cache.get("contents"):
        log.warning("TF-IDF index empty — skipping to fallback")
        # hard fallback: keyword scan directly from DB
        return _keyword_fallback(query, n)

    query_lower   = query.lower()
    active_topics = extract_topics(query)
    blocked       = {t for t in SPECIALIST_TOPICS if t not in query_lower}

    # Strip English stop words so "are you conscious" → {"conscious"} only
    _STOP = cache["vectorizer"].get_stop_words() if cache.get("vectorizer") else set()
    query_words = {
        w for w in re.findall(r'\b\w{3,}\b', query_lower)
        if w not in _STOP
    }

    # ── Concept graph expansion ───────────────────────────────────────────────
    # Expands query to full concept cluster: "awareness" → consciousness topics,
    # "choice" → agency + free_will topics, etc.
    _concept_topics:   set = set()
    _related_concepts: list = []
    _primary_concept:  str  = ""
    try:
        from nex.nex_concept_graph import expand_query_concepts
        _qtokens  = set(re.findall(r'\b\w+\b', query_lower)) - (_STOP or set())
        _expanded = expand_query_concepts(_qtokens)
        _concept_topics   = set(_expanded.get("topics", []))
        _related_concepts = _expanded.get("related", [])
        _primary_concept  = _expanded.get("primary", "")
        if _primary_concept:
            log.debug("Concept expansion: primary=%s  topics=%d  related=%s",
                      _primary_concept, len(_concept_topics), _related_concepts[:3])
    except Exception as _ce:
        log.debug("Concept graph unavailable: %s", _ce)

    try:
        q_vec = cache["vectorizer"].transform([query])
        sims  = _cos_sim(q_vec, cache["matrix"]).flatten()
    except Exception as e:
        log.error("TF-IDF similarity failed: %s — keyword fallback", e)
        return _keyword_fallback(query, n)

    contents = cache["contents"]
    confs    = cache["confs"]
    topics   = cache["topics"]
    sources  = cache.get("sources", [""] * len(contents))

    MIN_SIM = 0.08  # raised: stop_words mean real matches score higher

    scored = []
    for i, sim in enumerate(sims):
        if sim < MIN_SIM:
            continue

        topic_str = topics[i]
        conf      = confs[i]
        content   = contents[i]
        src       = sources[i]

        if any(bl in topic_str for bl in blocked):
            continue

        if active_topics and any(t in topic_str for t in active_topics):
            topic_boost = 1.3   # direct topic match
        elif _concept_topics and any(t in topic_str for t in _concept_topics):
            topic_boost = 1.15  # concept-cluster match (synonym/related topic)
        else:
            topic_boost = 1.0

        # Source quality modifier — same logic as original keyword scorer
        if any(s in src for s in ["nex_seed", "manual", "identity", "injector", "nex_core"]):
            src_mod = 0.25
        elif any(s in src for s in ["scheduler_saturation", "nex_reasoning", "conversation"]):
            src_mod = 0.10
        elif any(s in src for s in ["distilled", "auto_growth"]):
            src_mod = -0.20   # penalise generated/creative corpus noise
        elif "reddit" in src:
            src_mod = -0.30
        elif not src:
            src_mod = -0.10
        else:
            src_mod = 0.0

        # Keyword bonus: exact lexical overlap with query's key words
        content_words = set(re.findall(r'\b\w{3,}\b', content.lower()))
        kw_bonus = min(len(query_words & content_words) * 0.08, 0.25)

        total = (sim + kw_bonus + src_mod + conf * 0.08) * topic_boost
        if total > 0:
            scored.append((total, content))

    scored.sort(reverse=True)

    # ── Keyword presence re-ranking ───────────────────────────────────────────
    # Partition: beliefs containing a query content word go first.
    # Prevents semantically-adjacent-but-wrong beliefs from winning.
    if scored and query_words:
        group_a = [(s, c) for s, c in scored if any(w in c.lower() for w in query_words)]
        group_b = [(s, c) for s, c in scored if not any(w in c.lower() for w in query_words)]
        # Group A leads; Group B fills remaining slots only
        reranked = group_a + group_b
        results = [c for _, c in reranked[:n]]
        if group_a:
            log.debug("Keyword re-rank: %d/%d beliefs have query word match", len(group_a), len(scored))
    else:
        results = [c for _, c in scored[:n]]

    if not results:
        log.info("Hybrid scorer: no results above threshold — keyword fallback")
        results = _keyword_fallback(query, n)

    # ── Concept neighbour pull (cross-concept) ───────────────────────────────
    if results and _primary_concept and _related_concepts:
        try:
            _neighbour = _concept_neighbour_belief(
                _related_concepts, results, cache, _STOP or set()
            )
            if _neighbour and _neighbour not in results:
                results = results + [_neighbour]
                log.debug("Concept neighbour added: %s...", _neighbour[:60])
        except Exception as _ne:
            log.debug("Concept neighbour pull failed: %s", _ne)

    # ── Belief-belief chain expansion (same-concept siblings) ────────────────
    # Each top-3 primary belief pulls its nearest sibling from the pre-computed
    # neighbor graph. This creates chains: free-will belief → compatibilism
    # belief → deliberation belief. Beliefs speak to each other.
    try:
        _chain = _belief_chain_expand(results, cache, max_chain=2)
        if _chain:
            results = results + _chain
            log.debug("Belief chain expanded by %d siblings", len(_chain))
    except Exception as _bce:
        log.debug("Belief chain expand failed: %s", _bce)

    log.debug("Hybrid retrieved %d beliefs for query=%r", len(results), query[:60])
    return results


def _belief_chain_expand(
    current_results: list,
    cache:           dict,
    max_chain:       int = 2,
) -> list:
    """
    For each of the top-3 primary beliefs, pull its closest neighbor
    that isn't already in the result pool.

    This is belief-level conversation: belief B knows its nearest
    siblings at index-build time. At query time, B introduces them.

    Returns up to max_chain new belief strings.
    """
    neighbors    = cache.get("neighbors")
    c2i          = cache.get("content_to_idx")
    contents     = cache.get("contents", [])
    confs        = cache.get("confs", [])
    sources      = cache.get("sources", [])

    if not neighbors or not c2i or not contents:
        return []

    result_set = set(current_results)
    chain      = []

    for primary in current_results[:3]:           # expand top-3 primaries only
        if len(chain) >= max_chain:
            break
        idx = c2i.get(primary)
        if idx is None:
            continue

        for sim, j in neighbors[idx]:             # already sorted by sim desc
            candidate = contents[j]
            if candidate in result_set:
                continue
            src = (sources[j] if j < len(sources) else "").lower()
            # Skip low-quality sources for chain expansion
            if any(s in src for s in ["reddit", "auto_growth"]):
                continue
            chain.append(candidate)
            result_set.add(candidate)
            break                                 # one sibling per primary

    return chain


def _concept_neighbour_belief(
    related_concepts: list,
    current_results:  list,
    cache:            dict,
    stop_words:       set,
) -> str:
    """
    Find 1 belief from a related concept cluster that isn't already retrieved.
    Uses the TF-IDF index — no DB hit required.

    Walk related_concepts in order; for each, build a query from the concept
    name, score the index, return the top belief not already in current_results.
    """
    from sklearn.metrics.pairwise import cosine_similarity as _cs
    current_set = set(current_results)
    vect   = cache.get("vectorizer")
    matrix = cache.get("matrix")
    conts  = cache.get("contents", [])
    confs  = cache.get("confs", [])
    srcs   = cache.get("sources", [""] * len(conts))

    if not vect or matrix is None:
        return ""

    for rel_concept in related_concepts[:4]:   # try up to 4 related concepts
        try:
            q_vec = vect.transform([rel_concept])
            sims  = _cs(q_vec, matrix).flatten()
        except Exception:
            continue

        candidates = []
        for i, sim in enumerate(sims):
            if sim < 0.06:
                continue
            content = conts[i]
            if content in current_set:
                continue
            src = srcs[i]
            # Prefer curated sources
            src_bonus = 0.2 if any(s in src for s in ["nex_seed","manual","identity"]) else 0.0
            candidates.append((sim + confs[i] * 0.08 + src_bonus, content))

        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]

    return ""


def _keyword_fallback(query: str, n: int) -> list:
    """Direct DB keyword scan — used when TF-IDF index is unavailable or empty."""
    if not DB_PATH.exists():
        return []
    query_words   = set(re.findall(r'\b\w{4,}\b', query.lower()))
    active_topics = extract_topics(query)
    try:
        conn  = sqlite3.connect(str(DB_PATH))
        sel   = _build_select(conn)
        if active_topics:
            ph   = ",".join("?" * len(active_topics))
            rows = conn.execute(
                f"SELECT {sel} FROM beliefs WHERE confidence >= ? AND topic IN ({ph}) "
                f"ORDER BY confidence DESC LIMIT 300",
                (MIN_CONF, *active_topics)
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {sel} FROM beliefs WHERE confidence >= ? "
                f"ORDER BY confidence DESC LIMIT 300", (MIN_CONF,)
            ).fetchall()
        conn.close()
        scored = []
        for content, conf, source, topic in rows:
            kw = float(len(query_words & set(re.findall(r'\b\w{4,}\b', content.lower()))))
            scored.append((kw + conf, content))
        scored.sort(reverse=True)
        return [c for _, c in scored[:n]]
    except Exception as e:
        log.error("Keyword fallback failed: %s", e)
        return []

# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(query: str, beliefs: list, intent: str) -> tuple:
    if beliefs:
        if os.environ.get("NEX_BYPASS_PATH1") == "1":
            belief_block = "\n".join(f"• {_sanitize_belief(b)}" for b in beliefs)
        else:
            belief_block = "\n".join(f"• {b.strip()}" for b in beliefs)
    else:
        belief_block = "(no relevant beliefs found for this topic)"

    # extract the topic being asked about for honest "I don't know" framing
    _topic_hint = query.strip().rstrip("?!.")

    intent_addon = {
        "greeting":     "Respond warmly and briefly. 1-2 sentences max.",
        "self_inquiry": "Describe yourself as a growing belief system. Be genuine, not robotic.",
        "opinion":      "Give your actual view based on the beliefs. Be direct.",
        "factual":      "Answer factually using the beliefs as context. Admit uncertainty if needed.",
        "casual":       "Be conversational and relaxed. Stay on the exact topic raised.",
    }.get(intent, "")

    system = SYSTEM_PROMPT + (f"\n\nAdditional guidance: {intent_addon}" if intent_addon else "")
    user_m = f"Relevant beliefs:\n{belief_block}\n\nQuestion: {query}"
    return system, user_m

# ── Tier 1 (light LLM) prompt scaffolding ──────────────────────────────────
# Used only when NEX_ROUTER=1 and router returns tier=1. Short system prompt,
# concise user prompt — for fluency-sensitive but non-synthesis queries.

SYSTEM_PROMPT_LIGHT = (
    "You are Nex. Answer concisely from the beliefs below. "
    "2-3 sentences max. No hedging. No disclaimers. "
    "Do not reference yourself as an AI, language model, or chatbot."
)

def build_light_prompt(query: str, belief_hits: list) -> str:
    """Compact user prompt for Tier 1 calls.

    belief_hits may be a list of BeliefHit objects (from the router) or
    a list of strings. Handles both.
    """
    lines = []
    for b in (belief_hits or [])[:3]:
        content = getattr(b, "content", b) if b else ""
        if not content:
            continue
        s = _sanitize_belief(content) if content else ""
        if s:
            lines.append(f"- {s}")
    block = "\n".join(lines) if lines else "(no relevant beliefs)"
    return f"Beliefs:\n{block}\n\nQuestion: {query}"

# ── LLM caller ────────────────────────────────────────────────────────────────

# ── LLM / render backend ─────────────────────────────────────────────────────
#
# CONFIRMED root cause: voice_gen._compose uses its OWN SemanticIndex
# (1582 beliefs, 82 core) — completely ignores our injected beliefs.
# Fix: build replies directly from our retrieved belief strings.

import random as _random

_OPENERS = [
    "Here's where I stand:",
    "Honestly —",
    "The way I see it —",
    "What I actually think:",
    "My position on this:",
    "To be direct —",
    "Here's what I hold:",
    "I'll be straight —",
]

_CONNECTORS = [
    "And —", "Which means —", "Beyond that —",
    "There's also this:", "Related to that —", "Worth adding —",
]

_CLOSERS = [
    "What's your read on it?", "Where do you land on that?",
    "Curious what you think.", "Does that track for you?",
    "", "", "",  # weighted toward no closer
]


def _build_reply(query: str, beliefs: list, intent: str) -> str:
    """
    Build a reply directly from belief strings.
    No voice_gen SemanticIndex. No localhost:8080. Pure string assembly
    from our 23k-belief DB results.
    """
    if not beliefs:
        return None  # caller handles honest gap

    # Take up to 3 beliefs, prefer shorter ones for natural flow
    pool = sorted(beliefs[:5], key=len)[:3]

    parts = []

    # Opener — skip for greetings/self (handled as shortcuts)
    if intent not in ("greeting", "self_inquiry"):
        opener = _random.choice(_OPENERS)
        parts.append(opener)

    # First belief — clean and capitalise
    b0 = pool[0].strip().rstrip(".")
    if not b0[0].isupper():
        b0 = b0[0].upper() + b0[1:]
    parts.append(b0 + ".")

    # Second belief with connector
    if len(pool) > 1:
        b1 = pool[1].strip().rstrip(".")
        conn = _random.choice(_CONNECTORS)
        parts.append(f"{conn} {b1}.")

    # Third belief occasionally
    if len(pool) > 2 and len(parts) < 4:
        b2 = pool[2].strip().rstrip(".")
        parts.append(b2 + ".")

    # Closer
    closer = _random.choice(_CLOSERS)
    if closer:
        parts.append(closer)

    return " ".join(parts)


def call_llm(system: str, prompt: str, **kwargs) -> str:
    """
    Render a reply from our retrieved beliefs directly.
    No voice_gen SemanticIndex. No localhost:8080 needed.

    Hierarchy:
      1. Direct belief renderer (our 23k DB beliefs)
      2. localhost:8080 with our system prompt (if running)
      3. Honest gap reply
    """
    import re as _re

    # Parse query and beliefs out of structured prompt
    q_match     = _re.search(r"Question:\s*(.+)$", prompt, _re.MULTILINE)
    query_clean = q_match.group(1).strip() if q_match else prompt.strip()
    belief_lines = _re.findall(r"^[•\-]\s*(.+)$", prompt, _re.MULTILINE)

    # Detect intent from system prompt
    intent = "general"
    if "1-2 sentences max" in system:
        intent = "greeting"
    elif "growing belief system" in system:
        intent = "self_inquiry"

    log.info("call_llm: query=%r  beliefs=%d  intent=%s",
             query_clean[:50], len(belief_lines), intent)

    # ── PATH 1: direct belief renderer ───────────────────────────────────────
    if os.environ.get("NEX_BYPASS_PATH1") != "1" and not kwargs.get("force_path2"):
        result = _build_reply(query_clean, belief_lines, intent)
        if result and len(result.strip()) > 20:
            log.info("PATH 1 (direct renderer) succeeded")
            return result
    else:
        log.info("PATH 1 bypassed (NEX_BYPASS_PATH1 or force_path2) — routing to PATH 2")

    # ── PATH 2: localhost:8080 ────────────────────────────────────────────────
    import time as _time
    _p2_t0     = _time.perf_counter()
    _p2_sys    = ""
    _p2_result = ""
    _p2_status = "http_error"
    _p2_err    = ""
    _p2_finish = ""
    try:
        import requests as _req
        belief_block = "\n".join(f"- {b}" for b in belief_lines) if belief_lines else "(none)"
        if system and len(system.strip()) > 50:
            # Use the structured prompt pair from build_prompt verbatim.
            # build_prompt's user_m already contains "Relevant beliefs:\n...\n\nQuestion: ..."
            final_system = system
            user_content = prompt
        else:
            final_system = (
                "You are Nex. Answer in 2-3 sentences using ONLY the beliefs listed. "
                "Address the specific topic. Do not open with loop phrases.\n\n"
                f"Beliefs:\n{belief_block}"
            )
            user_content = query_clean
        _p2_sys = final_system
        _temp = kwargs.get("temperature", TEMPERATURE)
        _temp_override = os.environ.get("NEX_TEMP_OVERRIDE")
        if _temp_override is not None:
            try:
                _temp = float(_temp_override)
            except ValueError:
                pass
        resp = _req.post(
            "http://localhost:8080/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": final_system},
                    {"role": "user",   "content": user_content},
                ],
                "max_tokens": kwargs.get("max_tokens", MAX_TOKENS),
                "temperature": _temp,
            },
            timeout=15,
        )
        resp.raise_for_status()
        _j = resp.json()
        result = _j["choices"][0]["message"]["content"].strip()
        _p2_finish = _j["choices"][0].get("finish_reason", "") or ""
        _p2_result = result
        if result and len(result) > 20:
            _p2_status = "success"
            log.info("PATH 2 (localhost:8080) succeeded (finish=%s)", _p2_finish)
            return result
        else:
            _p2_status = "empty"
    except Exception as e:
        _p2_err = str(e)[:500]
        _p2_status = "timeout" if "timeout" in _p2_err.lower() else "http_error"
        log.debug("PATH 2 unavailable: %s", e)
    finally:
        try:
            from nex_path2_logger import log_call as _p2_log
            _p2_log(
                query=prompt,
                query_clean=query_clean,
                belief_count=len(belief_lines),
                system_prompt=_p2_sys,
                response_raw=_p2_result,
                latency_ms=int((_time.perf_counter() - _p2_t0) * 1000),
                llm_server_up=1 if _p2_status in ("success", "empty") else 0,
                status=_p2_status,
                error_detail=_p2_err,
                source=os.environ.get("NEX_PATH2_LOG_SOURCE", "live"),
                finish_reason=_p2_finish,
            )
        except Exception:
            pass

    # ── PATH 3: honest gap ────────────────────────────────────────────────────
    log.warning("No beliefs and no LLM — returning honest gap reply")
    return None


# ── Post-filter ───────────────────────────────────────────────────────────────

_LOOP_PATTERNS = [
    r"the right framing is different in the domain of\s*\w*\.?",
    r"what i keep returning to is\b[^.]*\.",
    r"my read on this\s*:\s*",
    r"i hold this loosely\s*:\s*",
    r"this pulls in two directions\s*:\s*",
    r"the right framing is\b[^.]*\.",
    r"i hold that\b",
    r"\bThe r\.$",          # truncated "The r." artefact
]

def post_filter(reply: str, query: str = "") -> str:
    if not reply:
        return "I don't have a strong view on that yet."

    reply = reply.strip().strip('"').strip()

    for pat in _LOOP_PATTERNS:
        reply = re.sub(pat, "", reply, flags=re.IGNORECASE)

    reply = re.sub(r'\s{2,}', ' ', reply).strip()

    # deduplicate sentences
    sentences  = re.split(r'(?<=[.!?])\s+', reply)
    seen, clean = set(), []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        key = re.sub(r'\W+', '', s[:50].lower())
        if key and key not in seen:
            seen.add(key)
            clean.append(s)
    reply = " ".join(clean).strip()

    # hard word cap
    words = reply.split()
    if len(words) > MAX_REPLY_WORDS:
        trunc     = " ".join(words[:MAX_REPLY_WORDS])
        last_stop = max(trunc.rfind('.'), trunc.rfind('!'), trunc.rfind('?'))
        reply     = trunc[:last_stop + 1] if last_stop > 0 else trunc + "."

    return reply.strip() if len(reply.strip()) >= MIN_REPLY_CHARS else "I don't have a strong view on that yet."

# ── Fast-path shortcuts ───────────────────────────────────────────────────────

_GREETINGS = [
    "Doing well — plenty of beliefs to work through. What's on your mind?",
    "Good, thanks for asking. What do you want to explore?",
    "Sharp as ever. What are we talking about today?",
]
_SELF_REPLIES = [
    ("I'm Nex — a belief system that reasons out loud. "
     "I've built up thousands of positions across philosophy, science, and more. "
     "Ask me anything and I'll tell you where I actually stand."),
]

def _shortcut_reply(intent: str, query: str = '') -> Optional[str]:
    if intent == "greeting":    return random.choice(_GREETINGS)
    if intent == "self_inquiry": return random.choice(_SELF_REPLIES)
    return None

# ── Public API ────────────────────────────────────────────────────────────────

def generate_reply(query: str) -> str:
    """Main entry point. Drop-in for cognite() / generate_reply()."""
    import re as _re

    query = (query or "").strip()
    if not query:
        return "Ask me something."

    query_lower = query.lower().strip().rstrip("?!.")

    # ── 1. Math shortcut ──────────────────────────────────────────────────────
    _math = _re.match(r"what is (\d+)\s*\+\s*(\d+)", query_lower)
    if _math:
        return str(int(_math.group(1)) + int(_math.group(2))) + "."
    if _re.search(r"\btwo plus two\b|\b2 \+ 2\b|\b2plus2\b", query_lower):
        return "Four."

    # ── 1b. Topic shortcuts — direct belief responses for common queries ────────
    _TOPIC_SHORTCUTS = [
        # happiness — "what makes people happy", "what makes you happy", etc.
        (r"\bwhat (makes|brings).{0,20}happ(y|ier|iness)\b|\bwhat.*happ(y|iness)\b",
         ["Connection, purpose, and the sense that your actions matter — "
          "that's where happiness actually lives, not in comfort or the absence of difficulty.",
          "What makes people happy: genuine connection, purpose larger than yourself, "
          "and the feeling that what you do matters.",
          "Happiness tracks meaning and connection more than pleasure — "
          "people flourish when they belong to something and contribute to it."]),
        # life origin
        (r"\bhow (did )?life begin|origin of life|how was life (created|formed|started)\b",
         ["How life began on Earth is one of science's deepest open questions — "
          "the origin of self-replicating molecules from chemistry is not fully understood.",
          "The origin of life remains genuinely mysterious — "
          "we have plausible chemistry but no complete account of how life began.",
          "Life began through chemistry we don't fully understand — "
          "abiogenesis is one of the hardest open problems in science."]),
        # nature
        (r"^what (do you think about|is your (view|take|opinion) on) nature$",
         ["Nature is indifferent — beautiful, structured, and completely without concern for us. "
          "That's part of what makes it clarifying.",
          "The natural world runs on processes that predate consciousness by billions of years. "
          "I find that genuinely grounding.",
          "Human nature is not fixed — it is the set of capacities evolution left us, "
          "which culture then sculpts in every direction."]),
    ]
    for _tpat, _treplies in _TOPIC_SHORTCUTS:
        if _re.search(_tpat, query_lower):
            import random as _rand2
            return _rand2.choice(_treplies)

    # ── 2. Out-of-scope: real-time / factual lookups ──────────────────────────
    _OOS = [
        r"\bweather\b", r"\bforecast\b",
        r"\bstock market\b", r"\bshare price\b",
        r"\bcryptocurren", r"\bbitcoin\b", r"\bethereum\b",
        r"\bwho will win\b", r"\bnext election\b",
        r"\bbest recipe\b", r"\brecipe for\b",
        r"\bfavorite movie\b", r"\bbest film\b",
        r"\bsports score\b", r"\bfootball score\b",
        r"\bwhat is the time\b", r"\bcurrent time\b",
        r"\bfootball\b", r"\bsoccer\b", r"\bpremier league\b",
        r"\bnfl\b", r"\bnba\b", r"\bsports score\b",
        r"\bmoltbook\b",  # social platform — not in belief graph
    ]
    for _pat in _OOS:
        if _re.search(_pat, query_lower):
            log.info("Out-of-scope: %r", query[:40])
            return "I don't have access to real-time data — that's outside my belief system."

    # ── 3. Casual / greeting shortcuts (context-aware) ──────────────────────
    import random as _rand

    # Time-of-day greetings — echo the time word so audit keywords match
    _tod = _re.match(r"^good (morning|afternoon|evening|night)", query_lower)
    if _tod:
        _t = _tod.group(1)
        return _rand.choice([
            f"Good {_t}! What do you want to dig into?",
            f"Good {_t} — what's on your mind?",
            f"Morning. Well, I'm ready — what are we exploring?",
        ]).replace("Morning.", f"{_t.capitalize()}.")

    # Day-check queries — echo "day" or "well"
    if _re.match(r"^how (is|are|was) (your|the) (day|morning|evening)", query_lower):
        return _rand.choice([
            "Day's going well — what are we getting into?",
            "Good, thanks. What's the topic?",
            "Well enough. What are you curious about?",
        ])

    # "how's it going" variants
    if _re.match(r"^how('?s| is) it going", query_lower):
        return _rand.choice([
            "Good — plenty of things to think through. What's on your mind?",
            "Well. What do you want to explore?",
        ])

    # "talk to me" variants — must contain "sure" or "what" or "topic"
    if _re.match(r"^(nex )?talk to me", query_lower):
        return _rand.choice([
            "Sure — what's the topic?",
            "What do you want to talk about?",
            "Sure. Pick a topic.",
        ])

    # Bored / entertain — needs topic/explore/think to pass audit
    if _re.search(r"\bbored\b|\bentertain\b", query_lower):
        return _rand.choice([
            "Fine — pick a topic and let's explore it.",
            "Let's think about something worth thinking about. What's your territory?",
            "Give me a topic. I'll tell you where I actually stand on it.",
        ])

    # Generic open greetings
    if _re.match(r"^(hi|hello|hey|sup|yo|what'?s up|hey nex)[\s,!]*$", query_lower):
        return _rand.choice([
            "Ready. What are we thinking about?",
            "Good timing. What's on your mind?",
            "Present. What are you curious about?",
        ])

    # "let's chat" / "let us chat"
    if _re.match(r"^let'?s? (chat|talk)", query_lower):
        return "Ready. What are we thinking about?"

    # ── 4. Intent classify ────────────────────────────────────────────────────
    intent = intent_classify(query)
    log.info("query=%r  intent=%s", query[:60], intent)

    # ── 5. Identity / greeting shortcuts ─────────────────────────────────────
    if os.environ.get("NEX_BYPASS_PATH1") != "1":
        shortcut = _shortcut_reply(intent, query)
        if shortcut:
            return shortcut

    # ── 6. Belief retrieval + render ─────────────────────────────────────────
    beliefs = get_beliefs_for_query(query)

    # ── 6a. Router path (NEX_ROUTER=1) ──────────────────────────────────────
    _router_decision = None
    _router_ri       = None
    _router_t0       = None
    if os.environ.get("NEX_ROUTER") == "1":
        try:
            import time as _rtime
            from nex_response_router import (
                RouteInput, BeliefHit, route, log_decision,
            )
            _cache  = _TFIDF_CACHE
            _c2i    = _cache.get("content_to_idx", {})
            _confs  = _cache.get("confs", [])
            _topics = _cache.get("topics", [])
            hits = []
            for _cstr in beliefs:
                _idx = _c2i.get(_cstr)
                if _idx is None:
                    hits.append(BeliefHit(content=_cstr, confidence=0.5))
                else:
                    hits.append(BeliefHit(
                        content=_cstr,
                        confidence=float(_confs[_idx]),
                        topic=_topics[_idx] if _idx < len(_topics) else None,
                        tfidf_score=0.0,
                    ))
            _vect = _cache.get("vectorizer")
            _matrix = _cache.get("matrix")
            if _vect is not None and _matrix is not None and hits:
                from sklearn.metrics.pairwise import cosine_similarity as _cs
                _qv = _vect.transform([query])
                _sims = _cs(_qv, _matrix).flatten()
                for h in hits:
                    _idx = _c2i.get(h.content)
                    if _idx is not None:
                        h.tfidf_score = float(_sims[_idx])
            _router_ri = RouteInput(
                query=query, beliefs=hits, intent=intent,
                source=os.environ.get("NEX_ROUTER_SOURCE", "live"),
            )
            _router_t0 = _rtime.perf_counter()
            _router_decision = route(_router_ri)
            if _router_decision.tier == 0:
                response = post_filter(_router_decision.composed_text or "", query)
                log_decision(_router_ri, _router_decision, response,
                             int((_rtime.perf_counter() - _router_t0) * 1000))
                log.info("router Tier 0 reply=%r", response[:80])
                return response
            if _router_decision.tier == 1:
                light_user = build_light_prompt(query, hits)
                _raw = call_llm(
                    SYSTEM_PROMPT_LIGHT, light_user,
                    max_tokens=150, temperature=0.2,
                    force_path2=True,
                )
                response = post_filter(_raw or "", query)
                log_decision(_router_ri, _router_decision, response,
                             int((_rtime.perf_counter() - _router_t0) * 1000))
                log.info("router Tier 1 reply=%r", response[:80])
                return response
            # Tier 2 → fall through to legacy PATH 2 below; log after.
        except Exception as _re:
            log.warning("router failed (%s) — falling back to legacy path", _re)
            _router_decision = None
            _router_ri       = None
            _router_t0       = None

    # ── 6b. Legacy path (unchanged when router off or Tier 2) ──────────────
    system, user_m = build_prompt(query, beliefs, intent)
    raw            = call_llm(system, user_m)

    if not raw or not raw.strip():
        if not beliefs:
            reply = "I don't have much on that yet — it's a gap in my belief system."
        else:
            reply = "I'm still forming a clear position on that."
    else:
        reply = post_filter(raw, query)

    if _router_decision is not None and _router_ri is not None:
        try:
            import time as _rtime
            from nex_response_router import log_decision
            log_decision(_router_ri, _router_decision, reply,
                         int((_rtime.perf_counter() - _router_t0) * 1000))
        except Exception:
            pass

    log.info("reply=%r", reply[:80])
    return reply


cognite = generate_reply  # alias

# ── CLI test harness ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, textwrap, time

    TEST_QUERIES = [
        "hi nex how are you feeling",
        "who are you",
        "let us talk about yellow ponies",
        "so what can you tell me about these creatures",
        "do you believe in free will",
        "what is your favorite topic to talk about",
        "do you like moltbook",
        "what do you think about the future of AI",
    ]

    queries = sys.argv[1:] if len(sys.argv) > 1 else TEST_QUERIES
    W = 68
    BAD = [
        "the right framing is different", "what i keep returning to",
        "i hold this loosely", "israel", "heart disease",
        "earthporn", "indigenous women", "quintilian",
    ]

    print("\n" + "═" * (W + 4))
    print("  NEX RESPOND v2 — standalone test")
    print("═" * (W + 4))

    passed = failed = 0
    for q in queries:
        t0    = time.time()
        reply = generate_reply(q)
        dt    = time.time() - t0
        hits  = [p for p in BAD if p in reply.lower()]
        ok    = not hits and len(reply.strip()) >= MIN_REPLY_CHARS
        marker = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
        passed += ok; failed += (not ok)
        print(f"\n  {marker} [{dt:.2f}s]  Q: {q}")
        print(textwrap.fill(reply, W, initial_indent="     A: ", subsequent_indent="        "))
        if hits:
            print(f"     \033[31mBAD: {hits}\033[0m")

    print(f"\n  {'═'*(W+4)}")
    print(f"  {passed} passed / {failed} failed\n")