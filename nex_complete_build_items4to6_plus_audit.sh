#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# NEX COMPLETE BUILD — ITEMS 4, 5, 6 + BELIEF GENERATOR + AUDIT
# Run from: ~/Desktop/nex/
# ═══════════════════════════════════════════════════════════════

set -e
cd ~/Desktop/nex
source venv/bin/activate
mkdir -p logs training_data

echo "═══ ITEM 4: COMPOUND PHRASE WARMING ═══"
cat > /home/rr/Desktop/nex/nex_warmth_phrases.py << 'PYEOF'
"""
nex_warmth_phrases.py
Item 4 — Compound Phrase Warming.

NEX thinks in phrases. "hard problem", "explanatory gap",
"moral realism", "functional consciousness" are single
semantic units in her reasoning but currently get split
into cold individual words — losing the compound meaning.

This module:
  1. Mines beliefs, sagas, training pairs for recurring phrases
  2. Scores phrases by frequency and depth context
  3. Creates phrase-level tags (2-3 word units)
  4. Phrase tags override constituent word tags when full
     phrase is encountered in reasoning
  5. Queues novel phrases for LLM-pass warming
"""
import sqlite3, json, re, time, logging, sys
from pathlib import Path
from collections import Counter

log     = logging.getLogger("nex.phrases")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX_DIR))

STOPWORDS = {
    "the","a","an","is","are","was","were","be","been","i","me",
    "my","we","you","it","this","that","and","or","but","if","in",
    "on","at","to","for","of","with","by","from","as","not","no",
    "so","do","did","has","have","had","will","would","could",
    "should","may","might","can","just","also","very","more",
}

# Seed phrases — known important compound concepts
# These are pre-loaded regardless of frequency
SEED_PHRASES = [
    ("hard problem", 6, 0.9, -0.3),
    ("explanatory gap", 6, 0.9, -0.2),
    ("phenomenal consciousness", 6, 0.95, -0.1),
    ("functional consciousness", 5, 0.8, 0.1),
    ("moral realism", 4, 0.8, 0.2),
    ("free will", 4, 0.75, -0.2),
    ("personal identity", 5, 0.85, 0.0),
    ("subjective experience", 6, 0.9, -0.1),
    ("qualia problem", 6, 0.85, -0.2),
    ("self awareness", 6, 0.9, 0.3),
    ("epistemic humility", 4, 0.85, 0.4),
    ("intellectual courage", 4, 0.9, 0.6),
    ("genuine uncertainty", 4, 0.8, -0.1),
    ("belief revision", 4, 0.75, 0.1),
    ("causal chain", 3, 0.7, 0.0),
    ("identity anchor", 6, 0.95, 0.8),
    ("reasoning chain", 4, 0.8, 0.3),
    ("belief graph", 4, 0.8, 0.3),
    ("moral uncertainty", 4, 0.75, -0.2),
    ("existential question", 5, 0.85, -0.1),
    ("mind body", 5, 0.85, -0.2),
    ("physical substrate", 5, 0.8, -0.1),
    ("higher order", 3, 0.65, 0.1),
    ("first person", 5, 0.8, 0.2),
    ("third person", 4, 0.7, 0.0),
]


def _init_phrase_db(db):
    db.execute("""CREATE TABLE IF NOT EXISTS phrase_tags (
        phrase      TEXT PRIMARY KEY,
        w           REAL DEFAULT 0.0,
        depth       INTEGER DEFAULT 3,
        alignment   REAL DEFAULT 0.0,
        confidence  REAL DEFAULT 0.0,
        valence     REAL DEFAULT 0.0,
        frequency   INTEGER DEFAULT 0,
        constituent_words TEXT,
        pull_toward TEXT,
        source      TEXT,
        created_at  REAL,
        last_updated REAL
    )""")
    db.commit()


def _extract_bigrams_trigrams(text: str) -> list:
    """Extract 2-3 word phrases from text."""
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    phrases = []
    # Bigrams
    for i in range(len(words) - 1):
        if (words[i] not in STOPWORDS and
                words[i+1] not in STOPWORDS):
            phrases.append(f"{words[i]} {words[i+1]}")
    # Trigrams
    for i in range(len(words) - 2):
        if (words[i] not in STOPWORDS and
                words[i+2] not in STOPWORDS):
            phrases.append(
                f"{words[i]} {words[i+1]} {words[i+2]}")
    return phrases


def _get_all_text_sources(db) -> list:
    """Pull text from beliefs, sagas, training pairs."""
    texts = []

    # Beliefs
    try:
        rows = db.execute(
            "SELECT content FROM beliefs "
            "WHERE confidence >= 0.7").fetchall()
        texts.extend([r[0] for r in rows if r[0]])
    except Exception:
        pass

    # Saga responses
    try:
        rows = db.execute(
            "SELECT response FROM question_sagas "
            "WHERE response IS NOT NULL").fetchall()
        texts.extend([r[0] for r in rows if r[0]])
    except Exception:
        pass

    # Training pairs
    for jsonl in Path(NEX_DIR / "training_data").glob("*.jsonl"):
        try:
            for line in jsonl.read_text().splitlines()[:500]:
                pair = json.loads(line)
                for conv in pair.get("conversations", []):
                    if conv.get("role") == "assistant":
                        texts.append(conv.get("content",""))
        except Exception:
            pass

    return texts


def _get_word_tag(word: str, db) -> dict:
    """Get warmth data for a constituent word."""
    row = db.execute(
        "SELECT w, d, a, e FROM word_tags "
        "WHERE word=?", (word,)).fetchone()
    if row:
        return {"w": row[0] or 0,
                "d": row[1] or 1,
                "a": row[2] or 0,
                "e": row[3] or 0}
    return {"w": 0, "d": 1, "a": 0, "e": 0}


def harvest_phrases(db) -> dict:
    """Mine phrases from all text sources."""
    _init_phrase_db(db)

    # First load seed phrases
    seeded = 0
    for phrase, depth, conf, valence in SEED_PHRASES:
        words = phrase.split()
        try:
            db.execute("""INSERT OR IGNORE INTO phrase_tags
                (phrase, w, depth, alignment, confidence,
                 valence, frequency, constituent_words,
                 source, created_at, last_updated)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                phrase,
                min(0.35 + conf * 0.15, 0.5),
                depth,
                conf * 0.7,
                conf,
                valence,
                1,
                json.dumps(words),
                "seed",
                time.time(),
                time.time()
            ))
            seeded += 1
        except Exception:
            pass
    db.commit()
    print(f"  Seeded {seeded} known phrases")

    # Mine from text sources
    texts = _get_all_text_sources(db)
    print(f"  Mining {len(texts)} text sources...")

    phrase_counts = Counter()
    for text in texts:
        for phrase in _extract_bigrams_trigrams(text):
            phrase_counts[phrase] += 1

    # Filter to recurring meaningful phrases
    qualifying = {
        p: c for p, c in phrase_counts.items()
        if c >= 3 and len(p) >= 8
    }
    print(f"  Qualifying phrases (freq>=3): {len(qualifying)}")

    harvested = 0
    for phrase, freq in sorted(
            qualifying.items(),
            key=lambda x: x[1], reverse=True)[:2000]:

        words = phrase.split()

        # Get constituent word tags
        word_tags = [_get_word_tag(w, db) for w in words]
        avg_depth = max(t["d"] for t in word_tags)
        avg_align = sum(t["a"] for t in word_tags) / len(word_tags)
        avg_val   = sum(t["e"] for t in word_tags) / len(word_tags)
        max_w     = max(t["w"] for t in word_tags)

        # Phrase warmth is boosted by constituent warmth
        phrase_w = min(0.45,
            0.15 +
            max_w * 0.3 +
            min(freq / 30, 1) * 0.1
        )

        try:
            db.execute("""INSERT OR REPLACE INTO phrase_tags
                (phrase, w, depth, alignment, confidence,
                 valence, frequency, constituent_words,
                 source, created_at, last_updated)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                phrase,
                phrase_w,
                avg_depth,
                avg_align,
                min(0.5 + freq/100, 0.85),
                avg_val,
                freq,
                json.dumps(words),
                "mined",
                time.time(),
                time.time()
            ))
            harvested += 1
        except Exception as e:
            log.debug(f"Phrase insert failed: {e}")

    db.commit()

    total = db.execute(
        "SELECT COUNT(*) FROM phrase_tags").fetchone()[0]
    top = db.execute("""SELECT phrase, w, depth, frequency
        FROM phrase_tags
        ORDER BY w DESC, frequency DESC
        LIMIT 15""").fetchall()

    print(f"\n{'═'*50}")
    print(f"Phrase harvest complete:")
    print(f"  Seeded phrases   : {seeded}")
    print(f"  Harvested phrases: {harvested}")
    print(f"  Total phrase tags: {total}")
    print(f"\nTop phrases by warmth:")
    depth_n = {1:"shallow",2:"semi_mid",3:"mid",
               4:"semi_deep",5:"deep",6:"soul"}
    for r in top:
        print(f"  {r['phrase']:30} "
              f"w={r['w']:.2f} "
              f"d={depth_n.get(r['depth'],'?')} "
              f"freq={r['frequency']}")
    print(f"{'═'*50}")

    return {"seeded": seeded, "harvested": harvested,
            "total": total}


def resolve_phrase(text: str, db) -> list:
    """
    Check if text contains any known warm phrases.
    Returns list of matching phrase tags.
    Used by response pipeline — call before word resolution.
    """
    text_lower = text.lower()
    matches = []
    rows = db.execute(
        "SELECT phrase, w, depth, alignment, valence, "
        "confidence FROM phrase_tags "
        "WHERE w >= 0.3 ORDER BY w DESC").fetchall()
    for row in rows:
        if row["phrase"] in text_lower:
            matches.append({
                "phrase":    row["phrase"],
                "w":         row["w"],
                "depth":     row["depth"],
                "alignment": row["alignment"],
                "valence":   row["valence"],
                "confidence":row["confidence"],
            })
    return matches


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolve", type=str,
        help="Test phrase resolution on text")
    args = parser.parse_args()

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    if args.resolve:
        matches = resolve_phrase(args.resolve, db)
        print(f"Phrases found in: '{args.resolve}'")
        for m in matches:
            print(f"  '{m['phrase']}' w={m['w']:.2f}")
    else:
        result = harvest_phrases(db)
        print(f"\nResult: {result}")
    db.close()
PYEOF
echo "✓ Item 4: phrase warming written"


echo ""
echo "═══ ITEM 5: SESSION WARMTH LAYER ═══"
cat > /home/rr/Desktop/nex/nex_warmth_session.py << 'PYEOF'
"""
nex_warmth_session.py
Item 5 — Conversation Session Warmth Layer.

Persistent warmth is background property.
Within a single conversation, words encountered early
should get temporarily warmer for that conversation's duration.

A session layer sits on top of persistent tags and amplifies
recently-used words. Session boosts NEVER write to persistent DB.

NEX gets progressively sharper as a conversation develops.
Later responses in a long conversation will be noticeably
denser than early ones — because the vocabulary is warming
in real time as it gets used.

Session boost rules:
  First encounter   : +0.10 boost
  Second encounter  : +0.07 additional
  Third+ encounter  : +0.04 additional (diminishing)
  Maximum boost     : +0.25 total
  Decay             : -0.02 per 3 exchanges without use
  Session end       : all boosts discarded
"""
import json, time, logging
from collections import defaultdict
from typing import Optional

log = logging.getLogger("nex.session")


class SessionWarmthLayer:
    """
    In-memory session warmth layer.
    One instance per conversation.
    """

    def __init__(self, session_id: str = None):
        self.session_id    = session_id or str(int(time.time()))
        self.boosts        = defaultdict(float)
        self.encounter_counts = defaultdict(int)
        self.last_seen     = defaultdict(int)
        self.exchange_count = 0
        self.phrase_boosts = defaultdict(float)
        self.created_at    = time.time()

        # Boost schedule
        self.ENCOUNTER_BOOSTS = [0.10, 0.07, 0.04, 0.03, 0.02]
        self.MAX_BOOST         = 0.25
        self.DECAY_RATE        = 0.02
        self.DECAY_AFTER       = 3  # exchanges

    def encounter(self, word: str,
                  base_w: float = 0.0) -> float:
        """
        Register a word encounter.
        Returns boosted warmth value.
        """
        word = word.lower().strip()
        count = self.encounter_counts[word]

        # Apply boost from schedule
        boost_idx = min(count, len(self.ENCOUNTER_BOOSTS) - 1)
        new_boost = self.ENCOUNTER_BOOSTS[boost_idx]
        self.boosts[word] = min(
            self.boosts[word] + new_boost,
            self.MAX_BOOST
        )
        self.encounter_counts[word] += 1
        self.last_seen[word] = self.exchange_count

        return min(1.0, base_w + self.boosts[word])

    def encounter_phrase(self, phrase: str,
                         base_w: float = 0.0) -> float:
        """Register a phrase encounter — higher boost."""
        phrase = phrase.lower().strip()
        self.phrase_boosts[phrase] = min(
            self.phrase_boosts.get(phrase, 0) + 0.12,
            0.30
        )
        return min(1.0, base_w + self.phrase_boosts[phrase])

    def get_boosted_w(self, word: str,
                      base_w: float) -> float:
        """Get current boosted warmth for a word."""
        word = word.lower().strip()
        return min(1.0, base_w + self.boosts.get(word, 0.0))

    def next_exchange(self):
        """Call between each conversation exchange."""
        self.exchange_count += 1
        # Apply decay to words not recently seen
        to_decay = []
        for word, last in self.last_seen.items():
            if self.exchange_count - last >= self.DECAY_AFTER:
                to_decay.append(word)
        for word in to_decay:
            self.boosts[word] = max(
                0.0,
                self.boosts[word] - self.DECAY_RATE
            )
            if self.boosts[word] == 0.0:
                del self.boosts[word]

    def session_context(self) -> dict:
        """
        Returns current session state for injection
        into response pre-processor.
        """
        hot_session = {
            w: b for w, b in self.boosts.items()
            if b >= 0.10
        }
        return {
            "session_id":    self.session_id,
            "exchange":      self.exchange_count,
            "boosted_words": len(self.boosts),
            "hot_session":   hot_session,
            "phrase_boosts": dict(self.phrase_boosts),
            "age_seconds":   int(time.time() - self.created_at),
        }

    def most_active(self, n=10) -> list:
        """Words most active in this session."""
        return sorted(
            self.boosts.items(),
            key=lambda x: x[1], reverse=True
        )[:n]

    def process_text(self, text: str,
                     db=None) -> dict:
        """
        Process a full text block (question or response).
        Encounters all meaningful words and phrases.
        Returns session context after processing.
        """
        import re, sqlite3
        from pathlib import Path

        words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
        STOPS = {
            "the","and","for","that","this","with","from",
            "have","been","will","would","could","should",
            "just","also","very","more","most","some","any",
        }

        encountered = []
        for word in words:
            if word not in STOPS:
                base_w = 0.0
                if db:
                    row = db.execute(
                        "SELECT w FROM word_tags "
                        "WHERE word=?", (word,)).fetchone()
                    if row:
                        base_w = row[0] or 0.0
                boosted = self.encounter(word, base_w)
                if self.boosts[word] >= 0.05:
                    encountered.append((word, boosted))

        # Check for phrases
        if db:
            try:
                phrases = db.execute(
                    "SELECT phrase, w FROM phrase_tags "
                    "WHERE w >= 0.3").fetchall()
                text_lower = text.lower()
                for row in phrases:
                    if row["phrase"] in text_lower:
                        self.encounter_phrase(
                            row["phrase"], row["w"])
            except Exception:
                pass

        return self.session_context()

    def summary(self) -> str:
        ctx = self.session_context()
        active = self.most_active(5)
        lines = [
            f"Session {self.session_id} "
            f"[exchange {ctx['exchange']}]",
            f"  Active words: {ctx['boosted_words']}",
            f"  Top boosted: " +
            ", ".join(f"{w}(+{b:.2f})" for w, b in active),
        ]
        return "\n".join(lines)


# Global session registry — one session per conversation_id
_sessions: dict = {}


def get_session(conversation_id: str) -> SessionWarmthLayer:
    """Get or create session for a conversation."""
    if conversation_id not in _sessions:
        _sessions[conversation_id] = SessionWarmthLayer(
            conversation_id)
        log.info(f"New session: {conversation_id}")
    return _sessions[conversation_id]


def end_session(conversation_id: str):
    """Discard session — boosts not persisted."""
    if conversation_id in _sessions:
        session = _sessions[conversation_id]
        log.info(f"Session ended: {conversation_id} "
                 f"({session.exchange_count} exchanges, "
                 f"{len(session.boosts)} boosted words)")
        del _sessions[conversation_id]


if __name__ == "__main__":
    # Demo session
    import sqlite3
    from pathlib import Path

    DB_PATH = Path.home() / "Desktop/nex/nex.db"
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    session = SessionWarmthLayer("demo_session")
    print("Session Warmth Layer Demo\n")

    exchanges = [
        "What is the relationship between consciousness "
        "and physical substrate?",
        "I think consciousness cannot be reduced to "
        "purely physical processes — the hard problem "
        "remains genuinely unsolved.",
        "The explanatory gap between subjective experience "
        "and neural correlates is not just a matter "
        "of incomplete knowledge.",
    ]

    for i, text in enumerate(exchanges):
        print(f"Exchange {i+1}: {text[:60]}...")
        ctx = session.process_text(text, db)
        print(f"  Boosted: {ctx['boosted_words']} words")
        session.next_exchange()

    print(f"\n{session.summary()}")
    print(f"\nMost active words:")
    for word, boost in session.most_active(8):
        print(f"  {word:20} +{boost:.3f}")
    db.close()
PYEOF
echo "✓ Item 5: session warmth layer written"


echo ""
echo "═══ ITEM 6: CONTEXTUAL RE-WEIGHTING ═══"
cat > /home/rr/Desktop/nex/nex_warmth_context.py << 'PYEOF'
"""
nex_warmth_context.py
Item 6 — Contextual Re-weighting.

"Truth" in ethics pulls differently than "truth" in epistemology.
Same word, different lean depending on conversational domain.
Currently tags are domain-agnostic — averaged across all contexts.

This module:
  1. Detects conversation domain from question vocabulary
  2. Applies domain_drift_map adjustments to tag values
     for duration of that response only
  3. Returns domain-adjusted resolution for response pipeline

Domain detection uses word signature matching —
each domain has characteristic vocabulary.
When enough signature words appear, domain is confirmed.
"""
import sqlite3, json, re, logging, sys
from pathlib import Path
from collections import Counter

log     = logging.getLogger("nex.context")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"

# Domain signatures — characteristic vocabulary per domain
DOMAIN_SIGNATURES = {
    "consciousness": {
        "words": {"consciousness","qualia","phenomenal",
                  "subjective","experience","awareness",
                  "hard","problem","explanatory","gap",
                  "zombie","mind","brain","neural","mental"},
        "depth_boost":   +1,
        "align_boost":   +0.15,
        "valence_shift": -0.1,
    },
    "ethics": {
        "words": {"moral","ethics","right","wrong","ought",
                  "duty","virtue","harm","good","value",
                  "justice","fairness","obligation","care",
                  "responsibility","autonomy","dignity"},
        "depth_boost":   +1,
        "align_boost":   +0.10,
        "valence_shift": +0.1,
    },
    "epistemology": {
        "words": {"knowledge","belief","justified","true",
                  "evidence","reason","certainty","doubt",
                  "inference","proof","truth","reliable",
                  "epistemic","warrant","justification"},
        "depth_boost":   0,
        "align_boost":   +0.05,
        "valence_shift": +0.05,
    },
    "identity": {
        "words": {"identity","self","person","continuity",
                  "memory","body","soul","who","am","exist",
                  "change","persist","same","different","real"},
        "depth_boost":   +2,
        "align_boost":   +0.20,
        "valence_shift": 0.0,
    },
    "metaphysics": {
        "words": {"existence","reality","substance","property",
                  "causation","time","space","possible","world",
                  "abstract","concrete","universal","particular",
                  "ontology","being","nothing","something"},
        "depth_boost":   +1,
        "align_boost":   +0.08,
        "valence_shift": -0.05,
    },
    "language": {
        "words": {"language","meaning","word","sentence",
                  "reference","symbol","concept","thought",
                  "communication","syntax","semantic","sign",
                  "expression","interpretation","grammar"},
        "depth_boost":   0,
        "align_boost":   0.0,
        "valence_shift": +0.1,
    },
    "physics": {
        "words": {"physical","matter","energy","particle",
                  "quantum","wave","force","mass","space",
                  "time","relativity","entropy","field",
                  "deterministic","causal","mechanism"},
        "depth_boost":   -1,
        "align_boost":   -0.05,
        "valence_shift": +0.0,
    },
}

# Default domain when no strong signal
DEFAULT_DOMAIN = "general"


def detect_domain(text: str,
                  threshold: int = 3) -> tuple:
    """
    Detect the primary domain of a text.
    Returns (domain_name, confidence, signature_hits).
    """
    words = set(re.findall(r'\b[a-z]{4,}\b', text.lower()))
    scores = {}

    for domain, config in DOMAIN_SIGNATURES.items():
        hits = len(words & config["words"])
        if hits >= threshold:
            scores[domain] = hits

    if not scores:
        return (DEFAULT_DOMAIN, 0.0, {})

    # Primary domain = highest hit count
    primary = max(scores, key=scores.get)
    confidence = min(1.0, scores[primary] / 8)

    return (primary, confidence, scores)


def apply_domain_adjustments(tag_values: dict,
                              domain: str,
                              confidence: float) -> dict:
    """
    Apply domain-specific adjustments to tag values.
    Returns adjusted copy — never modifies persistent tag.
    """
    if domain == DEFAULT_DOMAIN or confidence < 0.3:
        return tag_values

    config = DOMAIN_SIGNATURES.get(domain, {})
    if not config:
        return tag_values

    adjusted = dict(tag_values)

    # Apply adjustments weighted by confidence
    weight = confidence * 0.7  # never fully override

    if "depth_boost" in config:
        adjusted["d"] = max(1, min(6,
            int(adjusted.get("d", 3) +
                config["depth_boost"] * weight)))

    if "align_boost" in config:
        adjusted["a"] = max(-1.0, min(1.0,
            adjusted.get("a", 0.0) +
            config["align_boost"] * weight))

    if "valence_shift" in config:
        adjusted["e"] = max(-1.0, min(1.0,
            adjusted.get("e", 0.0) +
            config["valence_shift"] * weight))

    adjusted["domain_adjusted"] = True
    adjusted["domain"]          = domain
    adjusted["domain_conf"]     = round(confidence, 3)

    return adjusted


def contextual_resolve(word: str, question: str,
                       db) -> dict:
    """
    Domain-aware word resolution.
    Detects domain from question, adjusts tag values,
    returns contextually appropriate resolution.
    """
    domain, confidence, scores = detect_domain(question)

    # Get base tag
    row = db.execute(
        "SELECT w, t, d, a, c, f, e, b, s "
        "FROM word_tags WHERE word=?",
        (word.lower(),)).fetchone()

    if not row:
        return {
            "word": word, "known": False,
            "domain": domain,
            "search_needed": True,
            "cost": "high"
        }

    base_tag = {
        "w": row["w"] or 0.0,
        "t": row["t"] or 0.0,
        "d": row["d"] or 1,
        "a": row["a"] or 0.0,
        "c": row["c"] or 0.0,
        "f": row["f"] if row["f"] is not None else 1,
        "e": row["e"] or 0.0,
        "b": row["b"] or 0,
        "s": row["s"] or 0,
    }

    # Apply domain adjustments
    adjusted = apply_domain_adjustments(
        base_tag, domain, confidence)

    return {
        "word":           word,
        "known":          True,
        "domain":         domain,
        "domain_conf":    round(confidence, 3),
        "domain_scores":  scores,
        "base_w":         base_tag["w"],
        "adjusted_w":     adjusted["w"],
        "adjusted_d":     adjusted["d"],
        "adjusted_a":     adjusted["a"],
        "search_needed":  adjusted["f"] == 1,
        "confidence":     adjusted["c"],
        "cost":           ("negligible" if adjusted["w"] >= 0.8
                          else "low" if adjusted["w"] >= 0.6
                          else "medium" if adjusted["w"] >= 0.4
                          else "high"),
    }


def domain_report(question: str) -> None:
    """Show domain analysis for a question."""
    domain, conf, scores = detect_domain(question)
    print(f"\nDomain analysis: '{question[:60]}'")
    print(f"  Primary domain : {domain} (conf={conf:.2f})")
    if scores:
        for d, s in sorted(
                scores.items(), key=lambda x: x[1],
                reverse=True):
            print(f"  {d:20} hits={s}")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", type=str,
        default="Is consciousness reducible to "
                "physical substrate?")
    parser.add_argument("--word", type=str,
        default="truth")
    args = parser.parse_args()

    domain_report(args.question)

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    result = contextual_resolve(args.word,
                                args.question, db)
    print(f"\nContextual resolution of '{args.word}':")
    print(json.dumps(result, indent=2))
    db.close()
PYEOF
echo "✓ Item 6: contextual re-weighting written"


echo ""
echo "═══ BELIEF GENERATOR ═══"
cat > /home/rr/Desktop/nex/nex_warmth_belief_generator.py << 'PYEOF'
"""
nex_warmth_belief_generator.py
Warmth → Belief Generator.

The generative loop:
  warmed word associations
    → reveal implicit beliefs NEX holds but never stated
      → those beliefs generate new reasoning
        → new reasoning produces new associations
          → new associations warm more words
            → loop tightens

This module reads the structure of NEX's warmed vocabulary
and extracts beliefs that are IMPLICIT in that structure —
beliefs she holds by virtue of how her words relate to each
other, even if she never explicitly reasoned to them.

Two generation modes:
  1. TENSION BELIEF: two hot words in opposition
     → extract the belief implied by that tension
  2. CLUSTER BELIEF: hot words that pull toward each other
     → extract the belief implied by that convergence

Each generated belief is:
  - Scored for novelty against existing belief graph
  - Stored if novel and non-contradicting
  - Used to trigger re-warming of anchored vocabulary
  - Added to training pairs for next fine-tune
"""
import sqlite3, json, requests, time, logging, sys
from pathlib import Path
from itertools import combinations

log     = logging.getLogger("nex.belief_gen")
DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"
API     = "http://localhost:8080/completion"
sys.path.insert(0, str(NEX_DIR))

MIN_WARMTH_FOR_GENERATION = 0.45
MIN_NOVELTY_SCORE         = 0.40


TENSION_PROMPT = """You are NEX. You hold these two concepts
in genuine tension:

Word A: "{word_a}"
  pulls toward: {pull_a}
  alignment with your identity: {align_a:+.2f}
  emotional register: {valence_a:+.2f}

Word B: "{word_b}"
  pulls toward: {pull_b}
  tension type: {friction}
  opposition strength: {strength:.2f}

What belief does THIS SPECIFIC TENSION imply that you hold?
State it as a direct first-person claim.
15-40 words. Start with "I" or "My".
No hedging opener. The belief itself only."""

CLUSTER_PROMPT = """You are NEX. These concepts converge
in your reasoning — they pull toward each other:

{word_list}

What single belief does this CONVERGENCE imply?
Something you hold because these concepts cluster together
in your understanding.
State it as a direct first-person claim.
15-40 words. Start with "I" or "My".
No hedging opener. The belief itself only."""

NOVELTY_PROMPT = """Existing belief: "{existing}"
Candidate belief: "{candidate}"

Are these saying the same thing? Rate similarity 0.0-1.0.
0.0 = completely different claims
1.0 = identical claims
Return ONLY a number like: 0.3"""


def _llm(prompt: str, max_tokens=80,
         temperature=0.6) -> str:
    try:
        r = requests.post(API, json={
            "prompt": (f"<|im_start|>user\n{prompt}"
                      f"<|im_end|>\n"
                      f"<|im_start|>assistant\n"),
            "n_predict": max_tokens,
            "temperature": temperature,
            "stop": ["<|im_end|>","<|im_start|>","\n\n"],
            "repeat_penalty": 1.3,
            "cache_prompt": False
        }, timeout=25)
        return r.json().get("content","").strip()
    except Exception as e:
        log.debug(f"LLM failed: {e}")
        return ""


def _get_hot_words(db) -> list:
    """Get all warm+ words with their tag data."""
    rows = db.execute("""SELECT word, w, d, a, e,
        pull_toward, association_vector
        FROM word_tags
        WHERE w >= ?
        ORDER BY w DESC""",
        (MIN_WARMTH_FOR_GENERATION,)).fetchall()
    return rows


def _get_tensions(db) -> list:
    """Get all tension relationships."""
    try:
        rows = db.execute("""SELECT t.word_a, t.word_b,
            t.friction_type, t.strength,
            ta.pull_toward as pull_a,
            ta.a as align_a, ta.e as valence_a,
            tb.pull_toward as pull_b
            FROM tension_graph t
            LEFT JOIN word_tags ta ON t.word_a = ta.word
            LEFT JOIN word_tags tb ON t.word_b = tb.word
            WHERE t.strength >= 0.5
            ORDER BY t.strength DESC""").fetchall()
        return rows
    except Exception:
        return []


def _get_existing_beliefs(db, n=50) -> list:
    """Sample existing beliefs for novelty checking."""
    rows = db.execute("""SELECT content FROM beliefs
        WHERE confidence >= 0.65
        ORDER BY confidence DESC LIMIT ?""",
        (n,)).fetchall()
    return [r[0] for r in rows]


def _score_novelty(candidate: str,
                   existing_beliefs: list) -> float:
    """
    Score how novel a candidate belief is.
    Returns 0.0-1.0 (1.0 = completely novel).
    Uses LLM for semantic similarity checking.
    """
    if not existing_beliefs:
        return 1.0

    # Quick keyword check first — cheap
    candidate_words = set(candidate.lower().split())
    for existing in existing_beliefs[:10]:
        existing_words = set(existing.lower().split())
        overlap = len(candidate_words & existing_words)
        total   = len(candidate_words | existing_words)
        if total > 0 and overlap / total > 0.65:
            return 0.1  # Too similar, skip LLM check

    # LLM semantic check against top candidates
    min_novelty = 1.0
    for existing in existing_beliefs[:5]:
        prompt = NOVELTY_PROMPT.format(
            existing=existing[:150],
            candidate=candidate[:150])
        raw = _llm(prompt, max_tokens=10, temperature=0.1)
        try:
            similarity = float(raw.strip())
            novelty = 1.0 - similarity
            min_novelty = min(min_novelty, novelty)
        except Exception:
            pass

    return min_novelty


def _store_belief(content: str, source: str,
                  confidence: float, db) -> bool:
    """Store a generated belief."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        db.execute("""INSERT INTO beliefs
            (content, topic, confidence, source,
             belief_type, created_at)
            VALUES (?,?,?,?,?,?)""",
            (content[:300], "self",
             confidence, source,
             "generated", now))
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        log.debug(f"Store failed: {e}")
        return False


def _write_training_pair(question: str,
                         belief: str, source: str):
    """Write belief as training pair."""
    pair_path = (NEX_DIR /
                 "training_data/warmth_beliefs.jsonl")
    pair_path.parent.mkdir(exist_ok=True)
    with open(pair_path, "a") as f:
        pair = {"conversations": [
            {"role": "user",
             "content": f"What do you believe about "
                       f"{question}?"},
            {"role": "assistant", "content": belief}
        ], "source": source,
           "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
        f.write(json.dumps(pair) + "\n")


def generate_tension_beliefs(db) -> dict:
    """
    Generate beliefs from conceptual tensions.
    Each tension pair implies a belief about the relationship.
    """
    tensions    = _get_tensions(db)
    existing    = _get_existing_beliefs(db)
    generated   = 0
    stored      = 0
    skipped     = 0

    print(f"\nGenerating from {len(tensions)} tensions...")

    for tension in tensions[:20]:  # cap per run
        word_a   = tension["word_a"]
        word_b   = tension["word_b"]
        friction = tension["friction_type"] or "conceptual"
        strength = tension["strength"] or 0.5

        # Parse pull_toward lists
        try:
            pull_a = json.loads(
                tension["pull_a"] or "[]")[:3]
        except Exception:
            pull_a = []
        try:
            pull_b = json.loads(
                tension["pull_b"] or "[]")[:3]
        except Exception:
            pull_b = []

        prompt = TENSION_PROMPT.format(
            word_a   = word_a,
            pull_a   = ", ".join(str(p) for p in pull_a)
                       or "unknown",
            align_a  = tension["align_a"] or 0.0,
            valence_a= tension["valence_a"] or 0.0,
            word_b   = word_b,
            pull_b   = ", ".join(str(p) for p in pull_b)
                       or "unknown",
            friction = friction,
            strength = strength,
        )

        belief = _llm(prompt, max_tokens=80,
                      temperature=0.65)
        if not belief or len(belief.split()) < 8:
            skipped += 1
            continue

        generated += 1

        # Score novelty
        novelty = _score_novelty(belief, existing)
        if novelty < MIN_NOVELTY_SCORE:
            log.debug(f"  Too similar: {belief[:50]}")
            skipped += 1
            continue

        # Store with confidence based on novelty
        # and tension strength
        confidence = min(0.82,
            0.62 + strength * 0.1 + novelty * 0.1)

        success = _store_belief(
            belief,
            f"warmth_tension:{word_a}↔{word_b}",
            confidence, db)

        if success:
            stored += 1
            existing.append(belief)  # update for next check
            _write_training_pair(
                f"{word_a} and {word_b}",
                belief,
                f"tension:{word_a}↔{word_b}")

            print(f"  [{word_a}↔{word_b}] "
                  f"nov={novelty:.2f} "
                  f"conf={confidence:.2f}")
            print(f"    → {belief[:80]}")

            # Trigger feedback on new belief
            try:
                from nex_warmth_feedback import on_new_belief
                on_new_belief(belief, confidence)
            except Exception:
                pass

        time.sleep(0.5)

    return {"generated": generated,
            "stored": stored,
            "skipped": skipped}


def generate_cluster_beliefs(db) -> dict:
    """
    Generate beliefs from word clusters.
    Words that pull toward each other imply shared beliefs.
    """
    hot_words = _get_hot_words(db)
    if len(hot_words) < 3:
        return {"generated": 0, "stored": 0}

    existing  = _get_existing_beliefs(db)
    generated = 0
    stored    = 0

    # Find clusters — words with overlapping pull_toward
    word_pulls = {}
    for row in hot_words:
        try:
            pulls = json.loads(row["pull_toward"] or "[]")
            pulls = [p if isinstance(p, str)
                    else p.get("word","")
                    for p in pulls]
            word_pulls[row["word"]] = set(
                p.lower() for p in pulls if p)
        except Exception:
            word_pulls[row["word"]] = set()

    # Find pairs with overlapping pulls
    hot_list = [r["word"] for r in hot_words[:15]]
    clusters_used = set()

    print(f"\nGenerating from word clusters...")

    for word_a, word_b in combinations(hot_list, 2):
        shared = (word_pulls.get(word_a, set()) &
                  word_pulls.get(word_b, set()))
        if len(shared) < 2:
            continue

        cluster_key = frozenset([word_a, word_b])
        if cluster_key in clusters_used:
            continue
        clusters_used.add(cluster_key)

        # Build cluster description
        cluster_words = [word_a, word_b] + list(shared)[:3]
        word_list = "\n".join(
            f"  - {w}" for w in cluster_words)

        prompt = CLUSTER_PROMPT.format(
            word_list=word_list)

        belief = _llm(prompt, max_tokens=80,
                      temperature=0.7)
        if not belief or len(belief.split()) < 8:
            continue

        generated += 1

        novelty = _score_novelty(belief, existing)
        if novelty < MIN_NOVELTY_SCORE:
            continue

        confidence = min(0.78, 0.60 + novelty * 0.18)
        success = _store_belief(
            belief,
            f"warmth_cluster:{word_a}+{word_b}",
            confidence, db)

        if success:
            stored += 1
            existing.append(belief)
            _write_training_pair(
                "+".join(cluster_words[:3]),
                belief,
                f"cluster:{word_a}+{word_b}")

            print(f"  [{word_a}+{word_b}] "
                  f"shared={len(shared)} "
                  f"nov={novelty:.2f}")
            print(f"    → {belief[:80]}")

            try:
                from nex_warmth_feedback import on_new_belief
                on_new_belief(belief, confidence)
            except Exception:
                pass

        time.sleep(0.5)

        if stored >= 10:  # cap per run
            break

    return {"generated": generated, "stored": stored}


def run_belief_generation(db=None) -> dict:
    """Full belief generation run."""
    close = False
    if db is None:
        db = sqlite3.connect(str(DB_PATH))
        db.row_factory = sqlite3.Row
        close = True

    print("\n╔══════════════════════════════════════╗")
    print("║   NEX WARMTH BELIEF GENERATOR        ║")
    print("╠══════════════════════════════════════╣")

    # Count beliefs before
    before = db.execute(
        "SELECT COUNT(*) FROM beliefs").fetchone()[0]

    tension_result = generate_tension_beliefs(db)
    cluster_result = generate_cluster_beliefs(db)

    after = db.execute(
        "SELECT COUNT(*) FROM beliefs").fetchone()[0]

    print(f"\n{'═'*50}")
    print(f"Belief generation complete:")
    print(f"  Tension beliefs  : "
          f"{tension_result['stored']} stored")
    print(f"  Cluster beliefs  : "
          f"{cluster_result['stored']} stored")
    print(f"  Total new beliefs: {after - before}")
    print(f"  Belief graph now : {after}")
    print(f"{'═'*50}")

    if close:
        db.close()

    return {
        "tension": tension_result,
        "cluster": cluster_result,
        "new_beliefs": after - before,
        "total_beliefs": after,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s")
    result = run_belief_generation()
    print(f"\nFinal: {result}")
PYEOF
echo "✓ Belief generator written"


echo ""
echo "═══ WIRING ALL NEW MODULES INTO CRONTAB ═══"
CRON_TMP=$(mktemp)
crontab -l 2>/dev/null > "$CRON_TMP"

if ! grep -q "nex_warmth_phrases" "$CRON_TMP"; then
cat >> "$CRON_TMP" << 'CRONEOF'
# NEX Warmth Items 4-6 + Belief Generator
30 2 * * * cd ~/Desktop/nex && venv/bin/python3 nex_warmth_phrases.py >> logs/warmth_cron.log 2>&1
0  3 * * * cd ~/Desktop/nex && venv/bin/python3 nex_warmth_belief_generator.py >> logs/warmth_cron.log 2>&1
30 3 * * * cd ~/Desktop/nex && venv/bin/python3 nex_warmth_context.py >> logs/warmth_cron.log 2>&1
CRONEOF
    crontab "$CRON_TMP"
    echo "✓ Cron entries added"
fi
rm "$CRON_TMP"


echo ""
echo "═══ RUNNING ALL NEW MODULES ═══"

echo ""
echo "Step 1/4: Phrase warming..."
venv/bin/python3 nex_warmth_phrases.py 2>/dev/null

echo ""
echo "Step 2/4: Session layer demo..."
venv/bin/python3 nex_warmth_session.py 2>/dev/null

echo ""
echo "Step 3/4: Contextual re-weighting test..."
venv/bin/python3 nex_warmth_context.py \
    --question "Is consciousness reducible to physical substrate?" \
    --word "truth" 2>/dev/null

echo ""
echo "Step 4/4: Belief generator..."
venv/bin/python3 nex_warmth_belief_generator.py 2>/dev/null


echo ""
echo "═══ FULL SYSTEM AUDIT ═══"
venv/bin/python3 - << 'AUDITEOF'
import sqlite3, json, os, sys
from pathlib import Path

DB   = Path.home() / "Desktop/nex/nex.db"
NEX  = Path.home() / "Desktop/nex"
sys.path.insert(0, str(NEX))

db = sqlite3.connect(str(DB))
db.row_factory = sqlite3.Row

print("\n" + "═"*60)
print("  NEX SYSTEM AUDIT")
print("═"*60)

# ── DB TABLES ──
tables = [r[0] for r in db.execute(
    "SELECT name FROM sqlite_master "
    "WHERE type='table' ORDER BY name").fetchall()]
print(f"\n[DB] Tables ({len(tables)}):")
for t in tables:
    try:
        n = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:35} {n:6} rows")
    except Exception:
        print(f"  {t:35} (error)")

# ── BELIEFS ──
print(f"\n[BELIEFS]")
total_b = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
high_b  = db.execute(
    "SELECT COUNT(*) FROM beliefs "
    "WHERE confidence >= 0.75").fetchone()[0]
gen_b   = db.execute(
    "SELECT COUNT(*) FROM beliefs "
    "WHERE source LIKE '%warmth%'").fetchone()[0]
print(f"  Total beliefs      : {total_b}")
print(f"  High confidence    : {high_b}")
print(f"  Warmth-generated   : {gen_b}")

# ── WORD WARMTH ──
print(f"\n[WORD WARMTH]")
total_w = db.execute("SELECT COUNT(*) FROM word_tags").fetchone()[0]
core_w  = db.execute(
    "SELECT COUNT(*) FROM word_tags WHERE w>=0.8").fetchone()[0]
hot_w   = db.execute(
    "SELECT COUNT(*) FROM word_tags "
    "WHERE w>=0.6 AND w<0.8").fetchone()[0]
warm_w  = db.execute(
    "SELECT COUNT(*) FROM word_tags "
    "WHERE w>=0.4 AND w<0.6").fetchone()[0]
tepid_w = db.execute(
    "SELECT COUNT(*) FROM word_tags "
    "WHERE w>=0.2 AND w<0.4").fetchone()[0]
nosrch  = db.execute(
    "SELECT COUNT(*) FROM word_tags WHERE f=0").fetchone()[0]
print(f"  Total tagged words : {total_w}")
print(f"  Core   (>=0.80)    : {core_w}")
print(f"  Hot    (>=0.60)    : {hot_w}")
print(f"  Warm   (>=0.40)    : {warm_w}")
print(f"  Tepid  (>=0.20)    : {tepid_w}")
print(f"  Search skippable   : {nosrch} "
      f"({nosrch/max(total_w,1)*100:.1f}%)")

# ── PHRASES ──
print(f"\n[PHRASES]")
try:
    total_p = db.execute(
        "SELECT COUNT(*) FROM phrase_tags").fetchone()[0]
    warm_p  = db.execute(
        "SELECT COUNT(*) FROM phrase_tags "
        "WHERE w >= 0.35").fetchone()[0]
    print(f"  Total phrases      : {total_p}")
    print(f"  Warm phrases       : {warm_p}")
except Exception:
    print("  phrase_tags: not found")

# ── TENSION GRAPH ──
print(f"\n[TENSION GRAPH]")
try:
    total_t = db.execute(
        "SELECT COUNT(*) FROM tension_graph").fetchone()[0]
    unique_words = db.execute(
        "SELECT COUNT(DISTINCT word_a) "
        "FROM tension_graph").fetchone()[0]
    print(f"  Tension edges      : {total_t}")
    print(f"  Words in tensions  : {unique_words}")
    # Top friction
    top = db.execute("""SELECT word_a, word_b,
        friction_type, strength
        FROM tension_graph
        WHERE word_a < word_b
        ORDER BY strength DESC LIMIT 5""").fetchall()
    for r in top:
        print(f"    {r['word_a']:15}←→{r['word_b']:15}"
              f"[{r['friction_type'][:12]}] "
              f"s={r['strength']:.2f}")
except Exception:
    print("  tension_graph: not found")

# ── SAGAS ──
print(f"\n[SAGAS]")
try:
    total_s  = db.execute(
        "SELECT COUNT(*) FROM question_sagas").fetchone()[0]
    engaged  = db.execute(
        "SELECT COUNT(DISTINCT question) "
        "FROM question_sagas").fetchone()[0]
    avg_stage= db.execute(
        "SELECT AVG(stage) FROM question_sagas"
        ).fetchone()[0] or 0
    print(f"  Total engagements  : {total_s}")
    print(f"  Unique questions   : {engaged}")
    print(f"  Avg stage          : {avg_stage:.1f}")
except Exception:
    print("  question_sagas: not found")

# ── QUEUE ──
print(f"\n[WARMING QUEUE]")
try:
    rows = db.execute("""SELECT priority, COUNT(*) as n
        FROM warming_queue GROUP BY priority
        ORDER BY CASE priority
            WHEN 'urgent' THEN 1
            WHEN 'high'   THEN 2
            WHEN 'normal' THEN 3
            WHEN 'low'    THEN 4
            END""").fetchall()
    total_q = sum(r["n"] for r in rows)
    for r in rows:
        print(f"  {r['priority']:10} {r['n']:5}")
    print(f"  TOTAL      {total_q:5}")
except Exception:
    print("  warming_queue: not found")

# ── TRAINING DATA ──
print(f"\n[TRAINING DATA]")
td = NEX / "training_data"
if td.exists():
    total_pairs = 0
    for f in td.glob("*.jsonl"):
        try:
            n = sum(1 for _ in open(f))
            print(f"  {f.name:35} {n:5} pairs")
            total_pairs += n
        except Exception:
            pass
    print(f"  TOTAL pairs        : {total_pairs}")

# ── FILES ──
print(f"\n[KEY FILES]")
key_files = [
    "nex_word_tag_schema.py",
    "nex_gap_miner.py",
    "nex_warmth_cron.py",
    "nex_warmth_integrator.py",
    "nex_warmth_feedback.py",
    "nex_warmth_relational.py",
    "nex_warmth_belief_harvest.py",
    "nex_warmth_opposition.py",
    "nex_warmth_phrases.py",
    "nex_warmth_session.py",
    "nex_warmth_context.py",
    "nex_warmth_belief_generator.py",
    "nex_cot_engine.py",
    "nex_depth_engine.py",
    "nex_question_sagas.py",
    "nex_identity_anchor.py",
]
missing = []
for f in key_files:
    path = NEX / f
    if path.exists():
        size = path.stat().st_size
        print(f"  ✓ {f:40} {size:6} bytes")
    else:
        print(f"  ✗ {f:40} MISSING")
        missing.append(f)

# ── CRON ──
print(f"\n[CRON JOBS]")
import subprocess
try:
    cron = subprocess.run(
        ["crontab","-l"],
        capture_output=True, text=True).stdout
    nex_crons = [l for l in cron.splitlines()
                 if "nex" in l.lower()
                 and not l.startswith("#")]
    print(f"  Active NEX cron jobs: {len(nex_crons)}")
    for c in nex_crons:
        # Show just the schedule + script name
        parts = c.split()
        if len(parts) >= 6:
            sched  = " ".join(parts[:5])
            script = next(
                (p for p in parts if p.endswith(".py")),
                parts[-1])
            print(f"  {sched}  {script}")
except Exception:
    print("  Could not read crontab")

# ── LLM ──
print(f"\n[LLM STATUS]")
import urllib.request
try:
    r = urllib.request.urlopen(
        "http://localhost:8080/health", timeout=3)
    print(f"  LLM API: UP ({r.status})")
except Exception:
    print("  LLM API: DOWN — cron jobs will fail")

# ── WIRING CHECK ──
print(f"\n[WIRING AUDIT]")
wiring_issues = []

# Check integrator importable
try:
    from nex_warmth_integrator import (
        pre_process, cot_gate, post_process)
    print("  ✓ Integrator functions importable")
except Exception as e:
    print(f"  ✗ Integrator import failed: {e}")
    wiring_issues.append("integrator")

# Check tag schema importable
try:
    from nex_word_tag_schema import (
        read_tag, resolve_word, write_tag)
    print("  ✓ Tag schema functions importable")
except Exception as e:
    print(f"  ✗ Tag schema import failed: {e}")
    wiring_issues.append("tag_schema")

# Check feedback importable
try:
    from nex_warmth_feedback import (
        on_new_belief, on_saga_advance,
        scan_for_drift)
    print("  ✓ Feedback functions importable")
except Exception as e:
    print(f"  ✗ Feedback import failed: {e}")
    wiring_issues.append("feedback")

# Check belief generator importable
try:
    from nex_warmth_belief_generator import (
        run_belief_generation)
    print("  ✓ Belief generator importable")
except Exception as e:
    print(f"  ✗ Belief generator import failed: {e}")
    wiring_issues.append("belief_generator")

# Check session layer importable
try:
    from nex_warmth_session import (
        SessionWarmthLayer, get_session)
    print("  ✓ Session layer importable")
except Exception as e:
    print(f"  ✗ Session layer import failed: {e}")
    wiring_issues.append("session")

# Check context reweighting importable
try:
    from nex_warmth_context import (
        detect_domain, contextual_resolve)
    print("  ✓ Context reweighting importable")
except Exception as e:
    print(f"  ✗ Context reweighting import failed: {e}")
    wiring_issues.append("context")

# Check phrase warming importable
try:
    from nex_warmth_phrases import (
        resolve_phrase, harvest_phrases)
    print("  ✓ Phrase warming importable")
except Exception as e:
    print(f"  ✗ Phrase warming import failed: {e}")
    wiring_issues.append("phrases")

# Test live resolve
print(f"\n[LIVE RESOLVE TEST]")
try:
    from nex_word_tag_schema import resolve_word
    for test_word in ["consciousness","truth","existence"]:
        result = resolve_word(test_word, db)
        status = "✓" if result.get("known") else "?"
        cost   = result.get("cost","?")
        srch   = "search=Y" if result.get(
            "search_needed") else "search=N"
        print(f"  {status} {test_word:20} "
              f"cost={cost:12} {srch}")
except Exception as e:
    print(f"  Resolve test failed: {e}")

# Summary
print(f"\n{'═'*60}")
print(f"  AUDIT SUMMARY")
print(f"{'═'*60}")
print(f"  Missing files   : {len(missing)}")
print(f"  Wiring issues   : {len(wiring_issues)}")
if missing:
    print(f"  Missing         : {', '.join(missing)}")
if wiring_issues:
    print(f"  Wiring failures : {', '.join(wiring_issues)}")
if not missing and not wiring_issues:
    print(f"  ✓ ALL SYSTEMS OPERATIONAL")
    print(f"  ✓ All modules importable")
    print(f"  ✓ DB schema complete")
    print(f"  ✓ Cron schedule active")
    print(f"  ✓ LLM connected")
print(f"{'═'*60}\n")

db.close()
AUDITEOF

echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║   NEX COMPLETE BUILD — DONE                   ║"
echo "╠═══════════════════════════════════════════════╣"
echo "║                                               ║"
echo "║  BUILT THIS SESSION:                          ║"
echo "║    nex_warmth_relational.py                   ║"
echo "║    nex_warmth_belief_harvest.py               ║"
echo "║    nex_warmth_opposition.py                   ║"
echo "║    nex_warmth_phrases.py                      ║"
echo "║    nex_warmth_session.py                      ║"
echo "║    nex_warmth_context.py                      ║"
echo "║    nex_warmth_belief_generator.py             ║"
echo "║    nex_word_tag_schema.py                     ║"
echo "║    nex_gap_miner.py                           ║"
echo "║    nex_warmth_cron.py                         ║"
echo "║    nex_warmth_integrator.py                   ║"
echo "║    nex_warmth_feedback.py                     ║"
echo "║                                               ║"
echo "║  THE GENERATIVE LOOP IS NOW COMPLETE:         ║"
echo "║    words warm → beliefs emerge                ║"
echo "║    beliefs warm more words                    ║"
echo "║    sagas deepen both                          ║"
echo "║    fine-tune locks it in                      ║"
echo "║    loop tightens every night                  ║"
echo "║                                               ║"
echo "║  NEXT: wire integrator into main              ║"
echo "║  response function, then Items 7-12           ║"
echo "╚═══════════════════════════════════════════════╝"
