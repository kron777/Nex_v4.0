#!/usr/bin/env python3
"""
nex_factual_retriever.py — Factual query interceptor for NEX cognition pipeline

Sits between the user query and pass3_retrieve in nex_cognition.py.
Detects factual queries (geography, economics, statistics, current events,
named entities) and does a targeted DB lookup against belief_type='fact'
before the opinion-retrieval pipeline runs.

If facts are found, they get injected into ctx.beliefs with high scores
so they dominate the Mistral prompt — grounding the response in real data
rather than pattern-matched training weights.

Integration in nex_voice_gen.py _generate():
    from nex_factual_retriever import maybe_inject_facts
    ...
    ctx = Context(q)
    pass1_parse(ctx)
    pass2_feel(ctx)
    maybe_inject_facts(ctx)   # ← add this line
    pass3_retrieve(ctx)       # opinion retrieval still runs, fills gaps
    ...

The factual retriever doesn't replace opinion retrieval — it prepends
high-confidence facts so they lead the response, with opinions following.
"""

import os, re, sqlite3, math, logging
from typing import Optional

log = logging.getLogger("nex.factual_retriever")

DB_PATH        = os.path.expanduser("~/Desktop/nex/nex.db")
CONFIG_DB_PATH = os.path.expanduser("~/.config/nex/nex.db")
LOG            = "  [FACT_RETRIEVER]"

# Score assigned to injected facts — higher than typical opinion scores
# so they lead ctx.beliefs and dominate the prompt
FACT_INJECT_SCORE = 12.0

# Max facts to inject per query — enough to inform without flooding
MAX_INJECT      = 4
MIN_FACT_LENGTH = 25


# ── Factual query detection ───────────────────────────────────────────────────
# We only intercept queries that are clearly asking for factual information.
# Philosophical / emotional / identity queries go straight to opinion retrieval.

FACTUAL_INTENT_PATTERNS = [
    # Direct data requests
    r"\bwhat is the\b", r"\bwhat are the\b", r"\bhow many\b", r"\bhow much\b",
    r"\bwhat percentage\b", r"\bwhat rate\b", r"\bwhat population\b",
    r"\bwhat happened\b", r"\bwhen did\b", r"\bwhere is\b", r"\bwhere are\b",
    r"\bwho is\b", r"\bwho was\b", r"\bwho are\b",
    # Factual topics
    r"\bstatistics\b", r"\bdata\b", r"\bfigures\b", r"\bnumbers\b",
    r"\beconomy\b", r"\beconomics\b", r"\bgdp\b", r"\bunemployment\b",
    r"\bpopulation\b", r"\bcrime rate\b", r"\binflation\b",
    r"\belection\b", r"\bvote\b", r"\bgovernment\b", r"\bpolicy\b",
    r"\bhistory of\b", r"\bfounded\b", r"\bestablished\b",
    r"\btell me about\b", r"\bcan you tell\b", r"\bwhat do you know about\b",
    r"\bexplain\b", r"\bdescribe\b", r"\boverview\b",
    # Geography / place
    r"\bcity\b", r"\btown\b", r"\bcountry\b", r"\bprovince\b", r"\bregion\b",
    r"\bstrand\b", r"\bhelderberg\b", r"\bcape town\b", r"\bsouth africa\b",
    r"\bwestern cape\b", r"\bafrica\b",
    # Current events
    r"\brecently\b", r"\blatest\b", r"\bcurrent\b", r"\bnews\b", r"\btoday\b",
    r"\bthis year\b", r"\blast year\b", r"\bin 20\d\d\b",
]

# Topics that should NOT trigger factual retrieval even if patterns match
OPINION_OVERRIDE_PATTERNS = [
    r"\bdo you feel\b", r"\bdo you think\b", r"\bdo you believe\b",
    r"\bhow do you\b", r"\bwhat do you think\b", r"\bwhat do you feel\b",
    r"\bare you\b", r"\bwould you\b", r"\bshouldyou\b",
]


def is_factual_query(query: str) -> bool:
    """
    Returns True if the query is asking for factual information
    rather than NEX's opinion or introspective reflection.
    """
    ql = query.lower()

    # If it looks like asking NEX about herself, skip factual retrieval
    for pat in OPINION_OVERRIDE_PATTERNS:
        if re.search(pat, ql):
            return False

    # Check factual patterns
    for pat in FACTUAL_INTENT_PATTERNS:
        if re.search(pat, ql):
            return True

    # Named entity heuristic: proper nouns (Title Case) often mean factual queries
    # e.g. "Strand Helderberg", "Elon Musk", "Western Cape"
    proper_nouns = re.findall(r'\b[A-Z][a-z]{2,}\b', query)
    if len(proper_nouns) >= 2:
        return True

    return False


# ── Keyword extraction ────────────────────────────────────────────────────────

STOPWORDS = {
    "what", "when", "where", "who", "how", "why", "is", "are", "was",
    "were", "the", "a", "an", "of", "in", "on", "at", "to", "for",
    "and", "or", "but", "tell", "me", "about", "can", "you", "do",
    "does", "did", "has", "have", "had", "will", "would", "could",
    "should", "please", "know", "explain", "describe", "give",
}

def extract_keywords(query: str) -> list[str]:
    """
    Extract meaningful keywords from query for DB matching.
    Returns list sorted by length (longer = more specific = better signal).
    """
    words = re.findall(r'\b[a-zA-Z]{3,}\b', query.lower())
    keywords = [w for w in words if w not in STOPWORDS]
    # Deduplicate preserving order
    seen = set()
    unique = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    # Sort longer words first — more specific
    return sorted(unique, key=len, reverse=True)


# ── DB retrieval ──────────────────────────────────────────────────────────────

def _get_db() -> Optional[sqlite3.Connection]:
    """Connect to whichever DB exists, preferring config DB (full schema)."""
    for path in [CONFIG_DB_PATH, DB_PATH]:
        if os.path.exists(path):
            try:
                conn = sqlite3.connect(path)
                # Verify belief_type column exists
                cols = [r[1] for r in conn.execute("PRAGMA table_info(beliefs)").fetchall()]
                if "belief_type" in cols:
                    return conn
                conn.close()
            except Exception:
                pass
    return None


def _score_fact(fact_content: str, keywords: list[str], query: str) -> float:
    """
    Score a fact against the query.
    Uses keyword overlap weighted by keyword specificity (length proxy).
    """
    cl = fact_content.lower()
    ql = query.lower()

    # Direct keyword overlap
    score = 0.0
    for kw in keywords:
        if kw in cl:
            # Weight by length — longer keywords are more specific
            score += math.log(len(kw) + 1) * 1.5

    # Bonus for exact phrase matches from query (bigrams)
    words = ql.split()
    for i in range(len(words) - 1):
        bigram = words[i] + " " + words[i+1]
        if len(bigram) > 6 and bigram in cl:
            score += 3.0

    # Penalty for very short facts (less information density)
    if len(fact_content) < 60:
        score *= 0.7

    return score


def retrieve_facts(query: str, limit: int = MAX_INJECT) -> list[tuple[str, float]]:
    """
    Retrieve relevant facts from the DB for a given query.
    Returns list of (content, score) tuples, highest score first.
    """
    keywords = extract_keywords(query)
    if not keywords:
        return []

    conn = _get_db()
    if conn is None:
        return []

    try:
        # Fetch candidate facts — use LIKE matching on top keywords
        # for the first 3 keywords to get a candidate pool,
        # then score all candidates properly
        top_kws = keywords[:4]

        # Build WHERE clause with OR conditions for each keyword
        conditions = " OR ".join(["LOWER(content) LIKE ?" for _ in top_kws])
        params = [f"%{kw}%" for kw in top_kws]

        rows = conn.execute(
            f"""SELECT content, confidence, topic, source_url
                FROM beliefs
                WHERE belief_type = 'fact'
                AND ({conditions})
                AND LENGTH(content) >= {MIN_FACT_LENGTH}
                LIMIT 50""",
            params
        ).fetchall()

        # If narrow search found nothing, try broader topic match
        if not rows and keywords:
            # Try topic-based retrieval using inferred topic
            topic_kws = _query_to_topics(query)
            if topic_kws:
                topic_conds = " OR ".join(["topic LIKE ?" for _ in topic_kws])
                rows = conn.execute(
                    f"""SELECT content, confidence, topic, source_url
                        FROM beliefs
                        WHERE belief_type = 'fact'
                        AND ({topic_conds})
                        AND LENGTH(content) >= {MIN_FACT_LENGTH}
                        LIMIT 30""",
                    [f"%{t}%" for t in topic_kws]
                ).fetchall()

        conn.close()
    except Exception as e:
        log.warning(f"{LOG} retrieval error: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return []

    if not rows:
        return []

    # Score all candidates
    scored = []
    for content, confidence, topic, source_url in rows:
        base_score = _score_fact(content, keywords, query)
        # Boost by confidence (facts with higher confidence score higher)
        final_score = base_score * (0.8 + confidence * 0.2)
        if final_score > 0:
            scored.append((content, final_score))

    # Sort by score, deduplicate similar content
    scored.sort(key=lambda x: x[1], reverse=True)

    selected = []
    selected_words = set()
    for content, score in scored:
        c_words = set(re.findall(r'\w+', content.lower())) - STOPWORDS
        if len(c_words) == 0:
            continue
        overlap = len(c_words & selected_words) / len(c_words)
        if overlap < 0.5:
            selected.append((content, score))
            selected_words.update(c_words)
        if len(selected) >= limit:
            break

    return selected


def _query_to_topics(query: str) -> list[str]:
    """Map query to likely DB topic values for fallback retrieval."""
    ql = query.lower()
    topics = []
    mapping = [
        (["economy", "gdp", "growth", "inflation", "unemployment", "rand", "money"], "economics"),
        (["south africa", "sa ", "south african"], "south_africa"),
        (["cape town", "western cape", "strand", "helderberg", "somerset"], "south_africa"),
        (["crime", "murder", "robbery", "police"], "crime"),
        (["election", "vote", "anc", "da ", "parliament"], "politics"),
        (["population", "people", "demographic", "residents"], "demographics"),
        (["health", "hospital", "disease", "hiv", "covid"], "health"),
        (["education", "school", "university", "matric"], "education"),
        (["energy", "electricity", "eskom", "loadshed"], "energy"),
        (["technology", "ai ", "software", "tech"], "technology"),
        (["climate", "weather", "drought", "flood", "temperature"], "climate"),
        (["business", "company", "invest", "market"], "business"),
    ]
    for keywords, topic in mapping:
        if any(k in ql for k in keywords):
            topics.append(topic)
    return topics


# ── Main injection function ───────────────────────────────────────────────────

def maybe_inject_facts(ctx) -> int:
    """
    Main integration point — call this in nex_voice_gen._generate()
    after pass2_feel and before pass3_retrieve.

    Checks if the query is factual, retrieves relevant facts,
    and prepends them to ctx.beliefs with high scores.

    Returns number of facts injected (0 if not a factual query or no facts found).

    Usage:
        from nex_factual_retriever import maybe_inject_facts
        ...
        pass2_feel(ctx)
        maybe_inject_facts(ctx)  # inject facts before opinion retrieval
        pass3_retrieve(ctx)
    """
    if not is_factual_query(ctx.query):
        return 0

    facts = retrieve_facts(ctx.query)
    if not facts:
        return 0

    # Prepend facts to ctx.beliefs with FACT_INJECT_SCORE
    # so they rank above any opinion beliefs that come from pass3_retrieve
    fact_entries = [(content, FACT_INJECT_SCORE) for content, score in facts]
    ctx.beliefs = fact_entries + ctx.beliefs

    log.debug(f"{LOG} injected {len(facts)} facts for: {ctx.query[:50]}")
    return len(facts)


# ── Stats / diagnostics ───────────────────────────────────────────────────────

def fact_stats() -> dict:
    """Return basic stats about the fact DB."""
    conn = _get_db()
    if conn is None:
        return {"available": False, "reason": "no DB with belief_type column found"}
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE belief_type='fact'"
        ).fetchone()[0]
        by_topic = conn.execute(
            "SELECT topic, COUNT(*) FROM beliefs WHERE belief_type='fact' "
            "GROUP BY topic ORDER BY COUNT(*) DESC LIMIT 10"
        ).fetchall()
        recent = conn.execute(
            "SELECT content, retrieved_date FROM beliefs "
            "WHERE belief_type='fact' ORDER BY retrieved_date DESC LIMIT 5"
        ).fetchall()
        conn.close()
        return {
            "available":  True,
            "total_facts": total,
            "by_topic":   dict(by_topic),
            "recent":     [(c[:80], d) for c, d in recent],
        }
    except Exception as e:
        return {"available": False, "reason": str(e)}


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NEX Factual Retriever")
    parser.add_argument("--query", help="Test a query")
    parser.add_argument("--stats", action="store_true", help="Show DB stats")
    args = parser.parse_args()

    if args.stats:
        stats = fact_stats()
        print(f"\nFact DB stats:")
        for k, v in stats.items():
            print(f"  {k}: {v}")

    elif args.query:
        print(f"\nQuery: {args.query}")
        print(f"Is factual: {is_factual_query(args.query)}")
        print(f"Keywords: {extract_keywords(args.query)}")
        facts = retrieve_facts(args.query)
        print(f"Facts found: {len(facts)}")
        for content, score in facts:
            print(f"  [{score:.2f}] {content[:100]}")

    else:
        # Run test queries
        test_queries = [
            "can you tell me about strand helderberg?",
            "what is the unemployment rate in south africa?",
            "what do you think about consciousness?",
            "are you lonely?",
            "what are the main industries in cape town?",
            "tell me about the western cape economy",
            "what do you feel right now?",
            "what happened in the last south african election?",
        ]
        print("\n── Factual query detection test ──\n")
        for q in test_queries:
            is_fact = is_factual_query(q)
            kws = extract_keywords(q)
            print(f"Q: {q}")
            print(f"   factual={is_fact}  keywords={kws[:4]}")
            print()
