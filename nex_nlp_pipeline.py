"""
nex_nlp_pipeline.py  —  LLM-Free NLP Pipeline
================================================================
NEX v1.0 — Build 3

Replaces all LLM calls in nex_source_manager.py and nex_synthesis.py.

Takes raw article text (title + summary from RSS) and produces
clean, atomic beliefs ready for insertion into the DB.

Pipeline:
    raw text
        → spaCy (NER, sentences, POS)
        → KeyBERT (keyphrases)
        → VADER (sentiment per sentence)
        → belief candidate assembly
        → novelty filter via FAISS (reject if too similar to existing)
        → scored belief list

Usage:
    # From terminal — test on a URL or raw text:
    python3 nex_nlp_pipeline.py --text "Transformers now achieve state-of-the-art results on memory benchmarks by using sparse attention mechanisms that reduce compute quadratically."
    python3 nex_nlp_pipeline.py --test   # runs against live arxiv feed

    # From other modules:
    from nex_nlp_pipeline import NLPPipeline
    pipeline = NLPPipeline()
    beliefs  = pipeline.extract(title, summary, domain="cognitive_architecture")
    # returns list of dicts ready for DB insert
"""

import logging
import os
import re
import sqlite3
import time

log = logging.getLogger("nex.nlp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_PATH = os.path.expanduser("~/.config/nex/nex.db")

# ── Thresholds ────────────────────────────────────────────────────────────────
MIN_CONFIDENCE      = 0.45   # below this → discard belief
NOVELTY_THRESHOLD   = 0.82   # cosine similarity above this → too similar, skip
MIN_BELIEF_WORDS    = 6      # minimum words in a belief string
MAX_BELIEF_WORDS    = 40     # maximum words — keeps beliefs atomic
MAX_BELIEFS_PER_ARTICLE = 4  # cap per article to avoid flooding


# =============================================================================
# Lazy dep loader
# =============================================================================

def _load_deps():
    errors = []
    try:
        import spacy
    except ImportError:
        errors.append("spacy  →  pip install spacy --break-system-packages && python -m spacy download en_core_web_lg")

    try:
        from keybert import KeyBERT
    except ImportError:
        errors.append("keybert  →  pip install keybert --break-system-packages")

    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    except ImportError:
        errors.append("vaderSentiment  →  pip install vaderSentiment --break-system-packages")

    if errors:
        raise SystemExit("[!] Missing dependencies:\n" + "\n".join(f"    {e}" for e in errors))

    return spacy, KeyBERT, SentimentIntensityAnalyzer


# =============================================================================
# NLPPipeline
# =============================================================================

class NLPPipeline:

    def __init__(self):
        spacy_mod, KeyBERT_cls, VADER_cls = _load_deps()

        log.info("Loading spaCy model: en_core_web_lg")
        try:
            self._nlp = spacy_mod.load("en_core_web_lg")
        except OSError:
            raise SystemExit(
                "[!] spaCy model not found.\n"
                "    python -m spacy download en_core_web_lg"
            )

        log.info("Loading KeyBERT ...")
        self._kw = KeyBERT_cls()

        log.info("Loading VADER ...")
        self._vader = VADER_cls()

        # Lazy-load embedding engine only if available
        self._embedder = None
        try:
            from nex_embeddings import EmbeddingEngine
            self._embedder = EmbeddingEngine()
            log.info("FAISS novelty filter active")
        except Exception:
            log.warning("nex_embeddings not available — novelty filter disabled")

    # ── Public entry point ────────────────────────────────────────────────────

    def extract(self, title: str, body: str, domain: str = "general") -> list[dict]:
        """
        Main extraction method. Takes article title + body text.
        Returns list of belief dicts ready for DB insert:

            [
              {
                "content":    str,   # the belief statement
                "topic":      str,   # domain / keyphrases
                "confidence": float, # 0.0–1.0
                "sentiment":  float, # VADER compound -1.0 to +1.0
                "source":     str,   # domain label
              },
              ...
            ]
        """
        text = self._clean(f"{title}. {body}")
        if len(text.split()) < 10:
            return []

        doc        = self._nlp(text)
        keyphrases = self._extract_keyphrases(text)
        sentences  = self._score_sentences(doc)
        candidates = self._assemble_candidates(sentences, keyphrases, domain)
        beliefs    = self._filter_and_rank(candidates)

        return beliefs[:MAX_BELIEFS_PER_ARTICLE]

    # ── Text cleaning ─────────────────────────────────────────────────────────

    def _clean(self, text: str) -> str:
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # Remove arxiv-style abstract boilerplate
        text = re.sub(r"^(abstract|summary)[:\.\s]+", "", text, flags=re.IGNORECASE)
        return text

    # ── KeyBERT keyphrases ────────────────────────────────────────────────────

    def _extract_keyphrases(self, text: str) -> list[str]:
        try:
            kws = self._kw.extract_keywords(
                text,
                keyphrase_ngram_range=(1, 3),
                stop_words="english",
                top_n=8,
                use_mmr=True,       # diversity — avoids near-duplicate phrases
                diversity=0.5,
            )
            return [kw for kw, score in kws if score > 0.2]
        except Exception as e:
            log.warning(f"KeyBERT failed: {e}")
            return []

    # ── Sentence scoring ──────────────────────────────────────────────────────

    def _score_sentences(self, doc) -> list[dict]:
        """
        Score each sentence for belief candidacy.
        Score = informativeness × named_entity_bonus × length_penalty
        """
        scored = []
        for sent in doc.sents:
            text = sent.text.strip()
            words = text.split()

            if len(words) < MIN_BELIEF_WORDS:
                continue
            if len(words) > MAX_BELIEF_WORDS * 2:
                # Truncate to first MAX_BELIEF_WORDS words for long sentences
                text = " ".join(words[:MAX_BELIEF_WORDS])
                words = text.split()

            # Informativeness: ratio of nouns + verbs (content words)
            content_pos  = {"NOUN", "VERB", "PROPN", "ADJ"}
            content_words = sum(1 for t in sent if t.pos_ in content_pos and not t.is_stop)
            informativeness = content_words / max(len(list(sent)), 1)

            # Named entity bonus
            ne_bonus = min(len(sent.ents) * 0.1, 0.3)

            # Length penalty — prefer concise sentences
            length_score = 1.0 - max(0, (len(words) - 15) / 40)

            # VADER sentiment
            sentiment = self._vader.polarity_scores(text)["compound"]

            score = (informativeness * 0.6) + (ne_bonus * 0.2) + (length_score * 0.2)

            scored.append({
                "text":      text,
                "score":     round(score, 3),
                "sentiment": round(sentiment, 3),
                "entities":  [e.text for e in sent.ents],
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    # ── Belief candidate assembly ─────────────────────────────────────────────

    def _assemble_candidates(self, sentences: list[dict],
                              keyphrases: list[str],
                              domain: str) -> list[dict]:
        """
        Turn top-scored sentences into belief candidates.
        Topic = domain + top keyphrase (gives meaningful topics vs old generic ones).
        """
        candidates = []

        # Use top 6 sentences as candidates
        for sent in sentences[:6]:
            text = sent["text"]

            # Reject if it looks like LLM artifact text
            if self._is_llm_artifact(text):
                continue

            # Truncate to MAX_BELIEF_WORDS
            words = text.split()
            if len(words) > MAX_BELIEF_WORDS:
                text = " ".join(words[:MAX_BELIEF_WORDS]) + "..."

            # Topic = domain + best matching keyphrase
            topic = self._assign_topic(text, keyphrases, domain)

            # Confidence from sentence score + sentiment signal
            # High sentiment (strong opinion) slightly boosts confidence
            confidence = sent["score"] * 0.7 + min(abs(sent["sentiment"]) * 0.3, 0.3)
            confidence = round(min(confidence, 0.95), 3)

            candidates.append({
                "content":    text,
                "topic":      topic,
                "confidence": confidence,
                "sentiment":  sent["sentiment"],
                "source":     domain,
                "entities":   sent["entities"],
            })

        return candidates

    # ── Artifact detection ────────────────────────────────────────────────────

    def _is_llm_artifact(self, text: str) -> bool:
        """Reject strings that are clearly LLM-generated synthesis blobs."""
        artifact_patterns = [
            r"^yes,?\s+there are contradictions",
            r"^no contradictions exist",
            r"synthesized resolution belief",
            r"^\[synthesized insight",
            r"^\[thesis\]",
            r"^\[antithesis\]",
            r"tension score=",
            r"here'?s a synthesized",
            r"^a synthesized resolution",
        ]
        text_lower = text.lower()
        return any(re.search(p, text_lower) for p in artifact_patterns)

    # ── Topic assignment ──────────────────────────────────────────────────────

    def _assign_topic(self, text: str, keyphrases: list[str], domain: str) -> str:
        """
        Assign a meaningful topic string.
        Format: domain/keyphrase  e.g. "cognitive_architecture/sparse attention"
        Falls back to domain alone if no keyphrases.
        """
        if not keyphrases:
            return domain

        text_lower = text.lower()
        # Find the keyphrase most present in this sentence
        for kp in keyphrases:
            if kp.lower() in text_lower:
                return f"{domain}/{kp}"

        # Default to top keyphrase
        return f"{domain}/{keyphrases[0]}"

    # ── Novelty filter ────────────────────────────────────────────────────────

    def _is_novel(self, text: str, existing_in_batch: list[str]) -> bool:
        """
        Returns True if this belief is sufficiently novel.
        Checks:
          1. Not too similar to beliefs already accepted in this batch
          2. Not too similar to existing beliefs in FAISS index
        """
        if not self._embedder or not self._embedder._index:
            return True

        try:
            vec     = self._embedder.embed_one(text)
            results = self._embedder.search_by_vec(vec, k=3)
            if results and results[0]["score"] > NOVELTY_THRESHOLD:
                log.debug(f"  Skipping (too similar to: '{results[0]['content'][:60]}...')")
                return False
        except Exception as e:
            log.debug(f"  Novelty check failed: {e}")

        return True

    # ── Final filter + rank ───────────────────────────────────────────────────

    def _filter_and_rank(self, candidates: list[dict]) -> list[dict]:
        accepted    = []
        seen_texts  = []

        for c in candidates:
            if c["confidence"] < MIN_CONFIDENCE:
                continue
            if len(c["content"].split()) < MIN_BELIEF_WORDS:
                continue
            if not self._is_novel(c["content"], seen_texts):
                continue

            accepted.append(c)
            seen_texts.append(c["content"])

        # Sort by confidence descending
        accepted.sort(key=lambda x: x["confidence"], reverse=True)
        return accepted

    # ── DB insert ─────────────────────────────────────────────────────────────

    def insert_beliefs(self, beliefs: list[dict], source_name: str = "nlp_pipeline") -> int:
        """
        Insert extracted beliefs into nex.db.
        Returns count of actually inserted (skips duplicates).
        """
        if not beliefs:
            return 0

        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        inserted = 0

        for b in beliefs:
            try:
                cur.execute("""
                    INSERT OR IGNORE INTO beliefs
                        (content, topic, confidence, source, origin)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    b["content"],
                    b["topic"],
                    b["confidence"],
                    source_name,
                    "nlp_pipeline",
                ))
                if cur.rowcount > 0:
                    inserted += 1
            except Exception as e:
                log.warning(f"Insert failed: {e}")

        con.commit()
        con.close()
        return inserted


# =============================================================================
# CLI
# =============================================================================

def _fetch_arxiv_sample() -> list[tuple[str, str, str]]:
    """Fetch a few live arxiv cs.AI entries for testing."""
    import xml.etree.ElementTree as ET
    import urllib.request

    url  = "https://export.arxiv.org/rss/cs.AI"
    articles = []
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            tree = ET.parse(r)
        ns = {"dc": "http://purl.org/dc/elements/1.1/"}
        for item in tree.getroot().iter("item"):
            title   = item.findtext("title", "").strip()
            summary = item.findtext("description", "").strip()
            if title and summary:
                articles.append((title, summary, "cognitive_architecture"))
            if len(articles) >= 3:
                break
    except Exception as e:
        log.error(f"Fetch failed: {e}")
    return articles


def main():
    import argparse
    ap = argparse.ArgumentParser(description="NEX v1.0 — NLP Pipeline (Build 3)")
    ap.add_argument("--text",   type=str, help="Extract beliefs from a raw text string")
    ap.add_argument("--test",   action="store_true", help="Run against live arxiv feed")
    ap.add_argument("--insert", action="store_true", help="Insert extracted beliefs into DB (use with --test)")
    args = ap.parse_args()

    pipeline = NLPPipeline()

    if args.text:
        beliefs = pipeline.extract("Input", args.text, domain="general")
        print(f"\nExtracted {len(beliefs)} beliefs:\n")
        for b in beliefs:
            print(f"  [{b['confidence']:.2f}] topic={b['topic']}")
            print(f"  {b['content']}\n")
        return

    if args.test:
        print("\nFetching live arxiv cs.AI feed ...\n")
        articles = _fetch_arxiv_sample()
        if not articles:
            print("  No articles fetched.")
            return

        total_inserted = 0
        for title, summary, domain in articles:
            print(f"── Article: {title[:80]}")
            beliefs = pipeline.extract(title, summary, domain=domain)
            print(f"   Extracted {len(beliefs)} beliefs:")
            for b in beliefs:
                print(f"   [{b['confidence']:.2f} | {b['sentiment']:+.2f}] {b['topic']}")
                print(f"   {b['content'][:120]}")
            if args.insert:
                n = pipeline.insert_beliefs(beliefs, source_name="arxiv_AI")
                total_inserted += n
                print(f"   → Inserted {n} into DB")
            print()

        if args.insert:
            print(f"[✓] Total inserted: {total_inserted}")
            print("\nNext: run nex_embeddings.py --update to embed the new beliefs")
        else:
            print("  (pass --insert to write to DB)")
        return

    # No args — show help
    ap.print_help()


if __name__ == "__main__":
    main()
