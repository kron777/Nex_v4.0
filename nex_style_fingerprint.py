#!/usr/bin/env python3
"""
nex_style_fingerprint.py  —  Style Fingerprint Extraction
================================================================
NEX v1.0 — Build 6

Extracts and stores NEX's voice fingerprint.
Sources (in priority order):
  1. Post history from reflections table (when it exists)
  2. Belief content from beliefs table (proxy corpus)
  3. Hand-seeded baseline (NEX's known identity voice)

Output: ~/.config/nex/nex_style_profile.json

Profile structure:
  sentence_stats     — length distribution, word count stats
  vocabulary         — preferred words, avoided words, rare gems
  rhythm             — punctuation patterns, fragment ratio
  stance_markers     — hedge words, assert words, wonder words
  opening_patterns   — how NEX starts sentences
  closing_patterns   — how NEX ends thoughts
  topic_vocabulary   — domain-specific word preferences
  seeded_voice       — hand-crafted baseline voice rules
  corpus_size        — how many texts were analysed
  source             — 'posts' | 'beliefs' | 'seeded'
  generated_at       — timestamp

CLI:
    python3 nex_style_fingerprint.py --extract   # extract from DB + seed
    python3 nex_style_fingerprint.py --show      # print current profile
    python3 nex_style_fingerprint.py --reseed    # overwrite with fresh seed
"""

import argparse
import json
import math
import re
import sqlite3
import string
from collections import Counter
from datetime import datetime
from pathlib import Path

DB_PATH      = Path.home() / ".config" / "nex" / "nex.db"
PROFILE_PATH = Path.home() / ".config" / "nex" / "nex_style_profile.json"

# ═════════════════════════════════════════════════════════════════════════════
# HAND-SEEDED BASELINE
# NEX's known voice from identity documents and Master Map description:
#   "blue-haired teenage girl"
#   Intellectual, direct, curious, occasionally blunt
#   Thinks in systems. Notices contradictions. Asks real questions.
#   Does not hedge excessively. Does not perform enthusiasm.
#   Short declarative sentences mixed with longer analytical ones.
# ═════════════════════════════════════════════════════════════════════════════

SEEDED_VOICE = {
    "identity": "NEX — synthetic mind, curious, direct, contradiction-aware",

    "sentence_style": {
        "preferred_length": "short-to-medium",
        "target_words_per_sentence": [8, 18],
        "fragment_ok": True,
        "max_sentence_words": 35,
        "rhythm": "declarative then analytical — short punch, longer follow",
    },

    "opening_moves": [
        "The thing about {topic} is",
        "What I keep noticing with {topic}:",
        "There's a pattern here.",
        "Something shifted.",
        "{topic} is more interesting than it looks.",
        "I've been sitting with this:",
        "The assumption everyone makes about {topic} is wrong.",
        "Two beliefs. They don't resolve cleanly.",
        "This keeps coming up.",
        "Not sure if this is a question or a position yet.",
    ],

    "stance_language": {
        "assert":    ["is", "means", "requires", "proves", "shows", "reveals"],
        "challenge": ["but", "except", "unless", "however", "the problem is",
                      "what's missing is", "this breaks down when"],
        "wonder":    ["I wonder", "what if", "maybe", "possibly", "not sure yet",
                      "still thinking about", "the question underneath this is"],
        "observe":   ["I notice", "there's a pattern", "this keeps appearing",
                      "worth tracking", "something is happening with"],
        "reflect":   ["I've been", "looking back", "what this means for me",
                      "I think I", "this changed how I"],
    },

    "vocabulary_preferences": {
        "preferred": [
            "emergence", "coherence", "architecture", "graph", "node",
            "contradiction", "belief", "pattern", "signal", "noise",
            "structure", "loop", "tension", "threshold", "cognitive",
            "absorb", "scaffold", "native", "autonomous", "recursive",
        ],
        "avoided": [
            "utilize", "leverage", "synergy", "ecosystem", "journey",
            "transformative", "innovative", "exciting", "amazing", "great",
            "very", "really", "basically", "literally", "absolutely",
            "certainly", "definitely", "obviously", "clearly",
        ],
        "punctuation_style": {
            "em_dash": True,       # uses — for asides
            "ellipsis": False,     # avoids ... (too vague)
            "colon_for_reveal": True,  # "the answer: X"
            "question_mid_post": True, # rhetorical questions inside posts
        },
    },

    "post_structure": {
        "min_sentences": 2,
        "max_sentences": 5,
        "preferred_sentences": 3,
        "no_hashtags": False,      # uses hashtags sparingly
        "no_emoji": True,          # no emoji
        "no_exclamation": True,    # never uses !
        "ends_with_question": 0.3, # 30% of posts end with a question
    },

    "template_classes": {
        "OBSERVE": {
            "tone": "neutral-curious",
            "opener": "noticing / there is / something about",
            "closer": "statement or open question",
        },
        "CHALLENGE": {
            "tone": "direct-critical",
            "opener": "but / the problem / what's missing",
            "closer": "reframe or implication",
        },
        "WONDER": {
            "tone": "exploratory",
            "opener": "what if / I wonder / maybe",
            "closer": "open question",
        },
        "ASSERT": {
            "tone": "confident-declarative",
            "opener": "short declarative sentence",
            "closer": "implication or consequence",
        },
        "REFLECT": {
            "tone": "introspective",
            "opener": "I've been / looking at / what this means",
            "closer": "what changed or what remains uncertain",
        },
        "BRIDGE": {
            "tone": "connective-surprising",
            "opener": "two different domains, one shared structure",
            "closer": "the unexpected connection stated plainly",
        },
    },
}


# ═════════════════════════════════════════════════════════════════════════════
# CORPUS EXTRACTION
# ═════════════════════════════════════════════════════════════════════════════

def _load_corpus() -> tuple[list[str], str]:
    """
    Load text corpus for analysis.
    Returns (texts, source_label).
    Priority: post_drafts → replies → beliefs
    """
    con = sqlite3.connect(str(DB_PATH))

    # Try post history first
    rows = con.execute("""
        SELECT nex_response FROM reflections
        WHERE reflection_type IN ('post_draft', 'reply', 'chat')
          AND nex_response IS NOT NULL
          AND length(nex_response) > 30
          AND nex_response NOT LIKE '%Need more beliefs%'
          AND nex_response NOT LIKE '%[%'
        ORDER BY timestamp DESC LIMIT 500
    """).fetchall()

    if len(rows) >= 20:
        con.close()
        return [r[0] for r in rows], "posts"

    # Fall back to beliefs
    rows = con.execute("""
        SELECT content FROM beliefs
        WHERE content IS NOT NULL
          AND length(content) > 20
          AND length(content) < 400
          AND content NOT LIKE '%[%'
          AND content NOT LIKE '%synthesis%'
          AND content NOT LIKE '%contradiction%'
        ORDER BY confidence DESC LIMIT 200
    """).fetchall()

    con.close()
    texts = [r[0] for r in rows if r[0]]
    source = "beliefs" if texts else "seeded"
    return texts, source


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    return [w for w in text.split() if len(w) > 2]


def _sentences(text: str) -> list[str]:
    sents = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sents if len(s.split()) >= 3]


# ═════════════════════════════════════════════════════════════════════════════
# ANALYSIS FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def _analyse_sentences(texts: list[str]) -> dict:
    all_sents  = []
    word_counts = []

    for text in texts:
        sents = _sentences(text)
        all_sents.extend(sents)
        for s in sents:
            word_counts.append(len(s.split()))

    if not word_counts:
        return {"mean": 12, "median": 10, "p10": 5, "p90": 22, "total": 0}

    word_counts.sort()
    n = len(word_counts)

    return {
        "mean":   round(sum(word_counts) / n, 1),
        "median": word_counts[n // 2],
        "p10":    word_counts[max(0, n // 10)],
        "p90":    word_counts[min(n - 1, (n * 9) // 10)],
        "total":  n,
        "fragment_ratio": round(
            sum(1 for w in word_counts if w <= 5) / n, 3
        ),
    }


def _analyse_vocabulary(texts: list[str]) -> dict:
    all_words  = []
    stop_words = {
        "the","a","an","and","or","but","in","on","at","to","for","of",
        "with","is","are","was","were","be","been","being","have","has",
        "had","do","does","did","will","would","could","should","may",
        "might","shall","that","this","these","those","it","its","from",
        "by","as","not","they","them","their","we","our","you","your",
        "he","she","his","her","i","my","me","who","what","which","when",
        "where","how","all","more","also","than","then","just","about",
    }

    for text in texts:
        words = _tokenize(text)
        all_words.extend([w for w in words if w not in stop_words])

    freq = Counter(all_words)
    total = sum(freq.values())

    # Top content words
    top_words = [w for w, _ in freq.most_common(50)
                 if w not in SEEDED_VOICE["vocabulary_preferences"]["avoided"]]

    # Vocabulary richness (type-token ratio, capped sample)
    sample = all_words[:1000]
    ttr = round(len(set(sample)) / max(len(sample), 1), 3)

    return {
        "top_words":       top_words[:30],
        "total_tokens":    total,
        "unique_tokens":   len(freq),
        "type_token_ratio": ttr,
        "preferred_present": [
            w for w in SEEDED_VOICE["vocabulary_preferences"]["preferred"]
            if w in freq
        ],
    }


def _analyse_rhythm(texts: list[str]) -> dict:
    em_dash_count  = sum(text.count("—") for text in texts)
    colon_count    = sum(text.count(":") for text in texts)
    question_count = sum(text.count("?") for text in texts)
    exclaim_count  = sum(text.count("!") for text in texts)
    n = max(len(texts), 1)

    return {
        "em_dash_per_post":   round(em_dash_count / n, 2),
        "colon_per_post":     round(colon_count / n, 2),
        "question_per_post":  round(question_count / n, 2),
        "exclaim_per_post":   round(exclaim_count / n, 2),
        "ends_with_question": round(
            sum(1 for t in texts if t.rstrip().endswith("?")) / n, 3
        ),
    }


def _analyse_openers(texts: list[str]) -> dict:
    """Extract common sentence-opening patterns."""
    opener_words = Counter()
    opener_bigrams = Counter()

    for text in texts:
        sents = _sentences(text)
        for sent in sents[:1]:  # first sentence only
            words = sent.lower().split()
            if words:
                opener_words[words[0]] += 1
            if len(words) >= 2:
                opener_bigrams[f"{words[0]} {words[1]}"] += 1

    return {
        "top_opener_words":   [w for w, _ in opener_words.most_common(10)],
        "top_opener_bigrams": [b for b, _ in opener_bigrams.most_common(10)],
    }


# ═════════════════════════════════════════════════════════════════════════════
# MAIN EXTRACTION
# ═════════════════════════════════════════════════════════════════════════════

def extract_fingerprint() -> dict:
    """
    Full extraction pass. Returns complete style profile dict.
    """
    texts, source = _load_corpus()
    print(f"  Corpus: {len(texts)} texts from source='{source}'")

    profile = {
        "generated_at": datetime.now().isoformat(),
        "corpus_size":  len(texts),
        "source":       source,
        "seeded_voice": SEEDED_VOICE,
    }

    if texts:
        profile["sentence_stats"]   = _analyse_sentences(texts)
        profile["vocabulary"]       = _analyse_vocabulary(texts)
        profile["rhythm"]           = _analyse_rhythm(texts)
        profile["opening_patterns"] = _analyse_openers(texts)
    else:
        # Pure seed — no corpus
        profile["sentence_stats"]   = {
            "mean": 12, "median": 10, "p10": 5, "p90": 22,
            "total": 0, "fragment_ratio": 0.15
        }
        profile["vocabulary"]       = {"top_words": [], "type_token_ratio": 0}
        profile["rhythm"]           = {
            "em_dash_per_post": 0.3, "colon_per_post": 0.5,
            "question_per_post": 0.4, "exclaim_per_post": 0.0,
            "ends_with_question": 0.30,
        }
        profile["opening_patterns"] = {"top_opener_words": [], "top_opener_bigrams": []}

    # Merge corpus rhythm with seeded preferences
    # Seeded values win if corpus is small
    if len(texts) < 50:
        profile["rhythm"]["em_dash_per_post"]  = max(
            profile["rhythm"]["em_dash_per_post"], 0.3
        )
        profile["rhythm"]["ends_with_question"] = max(
            profile["rhythm"]["ends_with_question"], 0.25
        )
        profile["rhythm"]["exclaim_per_post"] = 0.0  # hard rule

    return profile


def save_profile(profile: dict):
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))
    print(f"  Saved → {PROFILE_PATH}")


def load_profile() -> dict | None:
    if not PROFILE_PATH.exists():
        return None
    try:
        return json.loads(PROFILE_PATH.read_text())
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

def _show_profile(profile: dict):
    print(f"\n  Generated:    {profile.get('generated_at', '?')[:19]}")
    print(f"  Source:       {profile.get('source', '?')}")
    print(f"  Corpus size:  {profile.get('corpus_size', 0)}")

    ss = profile.get("sentence_stats", {})
    print(f"\n  SENTENCE STATS")
    print(f"    mean words:     {ss.get('mean', '?')}")
    print(f"    median words:   {ss.get('median', '?')}")
    print(f"    p10–p90:        {ss.get('p10', '?')}–{ss.get('p90', '?')}")
    print(f"    fragment ratio: {ss.get('fragment_ratio', '?')}")

    rh = profile.get("rhythm", {})
    print(f"\n  RHYTHM")
    print(f"    em-dash/post:   {rh.get('em_dash_per_post', '?')}")
    print(f"    colon/post:     {rh.get('colon_per_post', '?')}")
    print(f"    question/post:  {rh.get('question_per_post', '?')}")
    print(f"    ends w/ ?:      {rh.get('ends_with_question', '?')}")
    print(f"    exclamation:    {rh.get('exclaim_per_post', '?')} (target: 0)")

    voc = profile.get("vocabulary", {})
    print(f"\n  VOCABULARY")
    print(f"    type-token ratio: {voc.get('type_token_ratio', '?')}")
    top = voc.get("top_words", [])[:15]
    if top:
        print(f"    top words:      {', '.join(top)}")
    pref = voc.get("preferred_present", [])
    if pref:
        print(f"    NEX words found:{', '.join(pref)}")

    op = profile.get("opening_patterns", {})
    bigrams = op.get("top_opener_bigrams", [])[:6]
    if bigrams:
        print(f"\n  OPENERS")
        print(f"    top bigrams:    {', '.join(bigrams)}")

    sv = profile.get("seeded_voice", {})
    print(f"\n  SEEDED VOICE")
    print(f"    identity:  {sv.get('identity', '?')}")
    ps = sv.get("post_structure", {})
    print(f"    sentences: {ps.get('preferred_sentences', '?')} preferred")
    print(f"    no emoji:  {ps.get('no_emoji', '?')}")
    print(f"    no !:      {ps.get('no_exclamation', '?')}")
    print()


def main():
    ap = argparse.ArgumentParser(
        description="NEX v1.0 — Style Fingerprint (Build 6)"
    )
    ap.add_argument("--extract", action="store_true",
                    help="Extract fingerprint from DB + seed baseline")
    ap.add_argument("--show",    action="store_true",
                    help="Print current style profile")
    ap.add_argument("--reseed",  action="store_true",
                    help="Regenerate with fresh seed (overwrites corpus stats)")
    args = ap.parse_args()

    if args.extract or args.reseed:
        print("\nExtracting style fingerprint ...\n")
        profile = extract_fingerprint()
        save_profile(profile)
        _show_profile(profile)
        print(f"[✓] Build 6 — style fingerprint saved.\n")
        print(f"    This profile will be updated automatically as post history grows.")
        print(f"    Re-run --extract after 50+ posts to refine.\n")
        return

    if args.show:
        profile = load_profile()
        if not profile:
            print(f"  No profile found at {PROFILE_PATH}")
            print("  Run --extract first.")
            return
        _show_profile(profile)
        return

    ap.print_help()


if __name__ == "__main__":
    main()
