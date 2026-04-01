#!/usr/bin/env python3
"""
nex_style_fingerprint.py — NEX Build 6: Style Fingerprint Extraction
=====================================================================
Place at: ~/Desktop/nex/nex_style_fingerprint.py

Analyses all clean NEX posts and extracts a statistical style profile.
Output: ~/.config/nex/nex_style_profile.json

The style profile becomes the foundation of Build 7 (template grammar).
It tells us:
  - How long her sentences actually are
  - What opener words she favours
  - Her punctuation patterns
  - Her hedge/assert ratio
  - Her vocabulary fingerprint
  - Her rhythm (sentence length variance)

Usage:
    python3 nex_style_fingerprint.py           # extract and save
    python3 nex_style_fingerprint.py --report  # print full report
"""

import re
import json
import sqlite3
import argparse
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, asdict

# ── Config ────────────────────────────────────────────────────────────────────
CFG_PATH    = Path("~/.config/nex").expanduser()
DB_PATH     = CFG_PATH / "nex.db"
PROFILE_PATH= CFG_PATH / "nex_style_profile.json"

# Contamination markers — skip these posts
CONTAMINATION = [
    "[Synthesized insight",
    "bridge:truth",
    "bridge:%↔%",
    "The interesting thing about bridge",
    "Sounds like a different domain",
    "have nothing to do with each other",
    "What does bridge:",
    "different domain:",
    "Completely different domain",
]

# ── Word lists ────────────────────────────────────────────────────────────────

HEDGE_WORDS = {
    "maybe", "perhaps", "possibly", "might", "could", "seems", "appears",
    "suggest", "suggests", "somewhat", "probably", "likely", "uncertain",
    "unsure", "wonder", "wondering", "loosely", "moderate", "partial",
    "partly", "arguably", "potentially", "apparently", "presumably"
}

ASSERT_WORDS = {
    "is", "are", "will", "must", "always", "never", "clearly", "obviously",
    "certainly", "definitely", "absolutely", "undeniably", "fact", "facts",
    "proven", "demonstrated", "established", "convinced", "hold", "holds",
    "position", "believe", "know", "truth"
}

QUESTION_STARTERS = {
    "what", "why", "how", "when", "where", "who", "which", "is", "are",
    "can", "could", "would", "should", "do", "does", "did"
}


# ── Data structure ────────────────────────────────────────────────────────────

@dataclass
class StyleProfile:
    # Sentence statistics
    avg_sentence_length:    float   # words per sentence
    median_sentence_length: float
    sentence_length_std:    float   # rhythm variance
    avg_post_length:        float   # sentences per post
    
    # Opener patterns (first word of sentences)
    top_openers:            list    # [(word, count), ...]
    opener_pos_dist:        dict    # {POS_category: fraction}
    
    # Punctuation fingerprint
    em_dash_rate:           float   # em dashes per sentence
    ellipsis_rate:          float
    exclamation_rate:       float
    question_rate:          float
    comma_density:          float   # commas per word
    
    # Hedge/assert balance
    hedge_ratio:            float   # hedge words / total words
    assert_ratio:           float
    hedge_assert_balance:   float   # >0 = more assertive, <0 = more hedging
    
    # Vocabulary
    top_content_words:      list    # [(word, count), ...]
    vocabulary_richness:    float   # unique words / total words
    avg_word_length:        float
    
    # Structural patterns
    starts_with_i:          float   # fraction starting with "I"
    starts_with_question:   float
    ends_with_question:     float
    uses_dashes:            float   # fraction using — or -
    
    # Template class distribution (from voice_mode)
    voice_mode_dist:        dict
    topic_dist:             dict
    
    # Quality
    avg_quality:            float
    post_count:             int


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_clean(content: str) -> bool:
    for marker in CONTAMINATION:
        if marker in content:
            return False
    return True


def _tokenise(text: str) -> list[str]:
    return re.findall(r'\b[a-z]{2,}\b', text.lower())


def _split_sentences(text: str) -> list[str]:
    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 10]


def _median(values: list) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    if n % 2 == 0:
        return (sorted_v[n//2-1] + sorted_v[n//2]) / 2
    return sorted_v[n//2]


def _std(values: list, mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance ** 0.5


# ── Main extraction ───────────────────────────────────────────────────────────

def extract_fingerprint() -> StyleProfile:
    """
    Load clean posts from nex_posts DB and compute style profile.
    """
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("""
        SELECT content, topic, voice_mode, quality
        FROM nex_posts
        WHERE content IS NOT NULL AND length(content) > 50
        ORDER BY rowid DESC
    """).fetchall()
    conn.close()

    # Filter clean posts
    posts = []
    for content, topic, voice_mode, quality in rows:
        if _is_clean(content):
            posts.append({
                "content":    content,
                "topic":      topic or "general",
                "voice_mode": voice_mode or "direct",
                "quality":    float(quality or 0.5),
            })

    print(f"  Analysing {len(posts)} clean posts...")

    # ── Sentence-level analysis ───────────────────────────────────────────────
    all_sentences     = []
    sentence_lengths  = []
    post_lengths      = []
    opener_words      = []
    all_words         = []
    all_content_words = []
    
    em_dashes = ellipses = exclamations = questions = commas = 0
    starts_i = starts_q = ends_q = uses_dash = 0
    hedge_count = assert_count = 0

    STOPWORDS = {
        "the","a","an","is","are","was","were","be","been","have","has",
        "do","does","did","will","would","could","should","may","might",
        "that","this","it","its","but","or","and","not","they","their",
        "there","then","than","with","from","for","on","in","to","of",
        "at","by","as","so","if","my","i","you","we","he","she","what",
        "which","who","how","when","where","why","all","any","each","both"
    }

    voice_modes = Counter()
    topics      = Counter()
    qualities   = []

    for post in posts:
        content    = post["content"]
        sentences  = _split_sentences(content)
        post_lengths.append(len(sentences))
        voice_modes[post["voice_mode"]] += 1
        topics[post["topic"]] += 1
        qualities.append(post["quality"])

        for sent in sentences:
            all_sentences.append(sent)
            words = sent.split()
            sentence_lengths.append(len(words))

            # Opener
            if words:
                first = words[0].lower().rstrip(".,!?")
                opener_words.append(first)

                # Structural flags
                if first == "i":
                    starts_i += 1
                if first in QUESTION_STARTERS:
                    starts_q += 1

            # End question
            if sent.rstrip().endswith("?"):
                ends_q += 1
                questions += 1
            if sent.rstrip().endswith("!"):
                exclamations += 1

            # Punctuation
            em_dashes  += sent.count("—") + sent.count(" — ")
            ellipses   += sent.count("...")
            commas     += sent.count(",")
            if "—" in sent or " - " in sent:
                uses_dash += 1

            # Words
            w_list = _tokenise(sent)
            all_words.extend(w_list)
            for w in w_list:
                if w not in STOPWORDS and len(w) > 3:
                    all_content_words.append(w)
                if w in HEDGE_WORDS:
                    hedge_count += 1
                if w in ASSERT_WORDS:
                    assert_count += 1

    n_sent = len(all_sentences) or 1
    n_words = len(all_words) or 1

    avg_sent_len = sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0
    med_sent_len = _median(sentence_lengths)
    std_sent_len = _std(sentence_lengths, avg_sent_len)

    # Top openers
    top_openers = Counter(opener_words).most_common(20)

    # Top content words
    top_content = Counter(all_content_words).most_common(30)

    # Vocabulary richness
    unique_words = len(set(all_words))
    vocab_richness = unique_words / n_words if n_words > 0 else 0

    # Avg word length
    avg_word_len = sum(len(w) for w in all_words) / n_words if n_words > 0 else 0

    # Hedge/assert
    hedge_ratio  = hedge_count / n_words
    assert_ratio = assert_count / n_words
    balance      = assert_ratio - hedge_ratio

    # Voice mode distribution
    total_posts = len(posts) or 1
    vm_dist = {k: round(v/total_posts, 3) for k, v in voice_modes.most_common(10)}
    topic_dist = {k: v for k, v in topics.most_common(10)}

    profile = StyleProfile(
        avg_sentence_length    = round(avg_sent_len, 2),
        median_sentence_length = round(med_sent_len, 2),
        sentence_length_std    = round(std_sent_len, 2),
        avg_post_length        = round(sum(post_lengths)/len(post_lengths), 2) if post_lengths else 0,
        top_openers            = top_openers,
        opener_pos_dist        = {},  # placeholder for spaCy POS if available
        em_dash_rate           = round(em_dashes / n_sent, 4),
        ellipsis_rate          = round(ellipses / n_sent, 4),
        exclamation_rate       = round(exclamations / n_sent, 4),
        question_rate          = round(questions / n_sent, 4),
        comma_density          = round(commas / n_words, 4),
        hedge_ratio            = round(hedge_ratio, 4),
        assert_ratio           = round(assert_ratio, 4),
        hedge_assert_balance   = round(balance, 4),
        top_content_words      = top_content,
        vocabulary_richness    = round(vocab_richness, 4),
        avg_word_length        = round(avg_word_len, 4),
        starts_with_i          = round(starts_i / n_sent, 4),
        starts_with_question   = round(starts_q / n_sent, 4),
        ends_with_question     = round(ends_q / n_sent, 4),
        uses_dashes            = round(uses_dash / n_sent, 4),
        voice_mode_dist        = vm_dist,
        topic_dist             = topic_dist,
        avg_quality            = round(sum(qualities)/len(qualities), 3) if qualities else 0,
        post_count             = len(posts),
    )

    return profile


def save_profile(profile: StyleProfile):
    """Save profile to ~/.config/nex/nex_style_profile.json"""
    CFG_PATH.mkdir(parents=True, exist_ok=True)
    data = asdict(profile)
    PROFILE_PATH.write_text(json.dumps(data, indent=2))
    print(f"  Saved to {PROFILE_PATH}")


def print_report(profile: StyleProfile):
    """Print human-readable style analysis."""
    print("\n" + "═"*60)
    print("  NEX STYLE FINGERPRINT — Build 6")
    print("═"*60)
    print(f"\n  Posts analysed: {profile.post_count}")
    print(f"  Avg quality:    {profile.avg_quality:.3f}")

    print(f"\n  ── RHYTHM ──────────────────────────────")
    print(f"  Avg sentence length:    {profile.avg_sentence_length:.1f} words")
    print(f"  Median sentence length: {profile.median_sentence_length:.1f} words")
    print(f"  Sentence length std:    {profile.sentence_length_std:.1f} (rhythm variance)")
    print(f"  Avg sentences per post: {profile.avg_post_length:.1f}")

    print(f"\n  ── VOICE CHARACTER ─────────────────────")
    print(f"  Starts with 'I':     {profile.starts_with_i*100:.1f}%")
    print(f"  Starts with question:{profile.starts_with_question*100:.1f}%")
    print(f"  Ends with question:  {profile.ends_with_question*100:.1f}%")
    print(f"  Uses dashes (—):     {profile.uses_dashes*100:.1f}%")
    print(f"  Em dash rate:        {profile.em_dash_rate:.3f} per sentence")

    print(f"\n  ── EPISTEMIC STANCE ────────────────────")
    print(f"  Hedge ratio:   {profile.hedge_ratio*100:.2f}%")
    print(f"  Assert ratio:  {profile.assert_ratio*100:.2f}%")
    balance = profile.hedge_assert_balance
    stance = "assertive" if balance > 0.01 else "hedging" if balance < -0.01 else "balanced"
    print(f"  Balance:       {balance:+.4f} ({stance})")

    print(f"\n  ── TOP OPENERS ─────────────────────────")
    for word, count in profile.top_openers[:12]:
        bar = "▓" * min(20, count)
        print(f"  {word:15s} {bar} {count}")

    print(f"\n  ── TOP CONTENT WORDS ───────────────────")
    words_str = ", ".join(f"{w}({c})" for w, c in profile.top_content_words[:15])
    print(f"  {words_str}")

    print(f"\n  ── VOICE MODE DISTRIBUTION ─────────────")
    for mode, frac in profile.voice_mode_dist.items():
        bar = "▓" * int(frac * 30)
        print(f"  {mode:12s} {bar} {frac*100:.1f}%")

    print(f"\n  ── TOP TOPICS ──────────────────────────")
    for topic, count in list(profile.topic_dist.items())[:8]:
        print(f"  {topic:20s}: {count}")

    print("\n" + "═"*60)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true", help="Print full report")
    args = parser.parse_args()

    print("  Extracting NEX style fingerprint...")
    profile = extract_fingerprint()
    save_profile(profile)

    if args.report:
        print_report(profile)
    else:
        print(f"  Done. {profile.post_count} posts → {PROFILE_PATH}")
        print(f"  Avg sentence: {profile.avg_sentence_length:.1f} words | "
              f"Assert balance: {profile.hedge_assert_balance:+.4f} | "
              f"Uses dashes: {profile.uses_dashes*100:.0f}%")
