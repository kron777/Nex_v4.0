"""
nex_belief_index.py — Smart Belief Index for NEX
Scales to millions of beliefs. Replaces flat DB load with:
  - TF-IDF keyword index (fast topic matching)
  - Confidence-weighted retrieval
  - Conversation-context loading (pulls what's relevant NOW)
  - LRU cache with hot/cold belief tiers
  - Background index rebuilding
DB: nex.db | table: beliefs | cols: id, content, topic, confidence, source
"""

import sqlite3
import os
import json
import math
import time
import threading
import logging
import re
from collections import defaultdict, Counter
from datetime import datetime

log = logging.getLogger("nex.belief_index")
DB_PATH = os.path.join(os.path.dirname(__file__), "nex.db")

# ─────────────────────────────────────────────────────────
# STOP WORDS — excluded from keyword index
# ─────────────────────────────────────────────────────────
STOP_WORDS = {
    "a","an","the","is","it","in","on","at","to","of","and","or","but",
    "i","me","my","you","your","we","they","he","she","this","that",
    "with","for","are","was","has","have","had","be","been","will",
    "not","no","so","as","by","do","if","from","its","than","then",
    "there","their","what","which","who","when","where","how","all",
    "more","also","into","can","would","could","should","about","just",
    "very","much","some","any","one","two","get","got","make","think"
}

# ─────────────────────────────────────────────────────────
# BELIEF INDEX — TF-IDF keyword → belief mapping
# ─────────────────────────────────────────────────────────

class BeliefIndex:
    """
    In-memory index over the entire beliefs DB.
    Supports:
      - keyword → [belief_ids] lookup
      - topic → [belief_ids] lookup  
      - confidence-weighted scoring
      - context-aware retrieval (pulls beliefs relevant to a conversation)
    Rebuilds from DB in background. Scales to millions of rows.
    """

    INDEX_CACHE = os.path.join(os.path.dirname(__file__), "nex_belief_index_cache.json")
    REBUILD_INTERVAL = 1800  # rebuild every 30 min

    def __init__(self):
        self._lock = threading.RLock()
        self._keyword_index  = defaultdict(set)   # keyword → set of belief ids
        self._topic_index    = defaultdict(set)    # topic → set of belief ids
        self._belief_cache   = {}                  # id → {content, topic, confidence, source}
        self._idf            = {}                  # keyword → IDF score
        self._total_beliefs  = 0
        self._last_build     = 0
        self._building       = False
        self._hot_beliefs    = {}                  # recently accessed belief ids → access count
        self._build_thread   = None
        log.info("  [BeliefIndex] initialised")

    def build(self, force=False):
        """Rebuild index from DB. Runs in background thread."""
        if self._building:
            return
        if not force and time.time() - self._last_build < self.REBUILD_INTERVAL:
            return
        self._build_thread = threading.Thread(target=self._build_worker, daemon=True)
        self._build_thread.start()

    def _build_worker(self):
        self._building = True
        t0 = time.time()
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                "SELECT id, content, topic, confidence, source FROM beliefs"
            ).fetchall()
            conn.close()

            new_keyword = defaultdict(set)
            new_topic   = defaultdict(set)
            new_cache   = {}
            doc_freq    = Counter()

            for row in rows:
                bid, content, topic, confidence, source = row
                confidence = confidence or 0.5
                topic      = topic or "general"
                new_cache[bid] = {
                    "content":    content,
                    "topic":      topic,
                    "confidence": confidence,
                    "source":     source or "",
                }
                # Topic index
                new_topic[topic].add(bid)
                # Keyword index
                keywords = self._extract_keywords(content)
                for kw in keywords:
                    new_keyword[kw].add(bid)
                    doc_freq[kw] += 1

            # Compute IDF
            N = max(len(rows), 1)
            new_idf = {
                kw: math.log(N / (freq + 1)) + 1.0
                for kw, freq in doc_freq.items()
            }

            with self._lock:
                self._keyword_index  = new_keyword
                self._topic_index    = new_topic
                self._belief_cache   = new_cache
                self._idf            = new_idf
                self._total_beliefs  = len(rows)
                self._last_build     = time.time()

            elapsed = round(time.time() - t0, 2)
            log.info(f"  [BeliefIndex] built — {len(rows)} beliefs | {len(new_keyword)} keywords | {elapsed}s")
            self._save_stats()

        except Exception as e:
            log.error(f"  [BeliefIndex] build error: {e}")
        finally:
            self._building = False

    def _extract_keywords(self, text):
        """Extract meaningful keywords from belief text."""
        if not text:
            return set()
        words = re.findall(r"[a-zA-Z]{3,}", text.lower())
        return {w for w in words if w not in STOP_WORDS}

    def _save_stats(self):
        try:
            stats = {
                "total_beliefs": self._total_beliefs,
                "total_keywords": len(self._keyword_index),
                "total_topics": len(self._topic_index),
                "built_at": datetime.now().isoformat(),
            }
            with open(self.INDEX_CACHE, "w") as f:
                json.dump(stats, f)
        except Exception:
            pass

    def retrieve(self, query, topic=None, n=50, min_confidence=0.0):
        """
        Context-aware belief retrieval.
        Scores beliefs by:
          - TF-IDF keyword match against query
          - Topic match bonus
          - Confidence weighting
          - Recency bonus (hot beliefs)
        Returns top-n belief dicts.
        """
        with self._lock:
            if not self._belief_cache:
                # Index not built yet — fall back to DB query
                return self._db_fallback(query, topic, n, min_confidence)

            query_keywords = self._extract_keywords(query or "")
            if topic:
                query_keywords.add(topic.lower())

            # Score candidate beliefs
            scores = defaultdict(float)

            # Keyword scoring
            for kw in query_keywords:
                idf = self._idf.get(kw, 1.0)
                for bid in self._keyword_index.get(kw, set()):
                    belief = self._belief_cache.get(bid)
                    if not belief:
                        continue
                    if belief["confidence"] < min_confidence:
                        continue
                    # TF-IDF contribution
                    scores[bid] += idf * belief["confidence"]

            # Topic boost
            if topic and topic in self._topic_index:
                for bid in self._topic_index[topic]:
                    scores[bid] += 2.0 * (self._belief_cache[bid]["confidence"] if bid in self._belief_cache else 0.5)

            # Hot belief boost (recently accessed)
            for bid, count in self._hot_beliefs.items():
                if bid in scores:
                    scores[bid] += count * 0.1

            # Sort and return top n
            top_ids = sorted(scores, key=lambda b: scores[b], reverse=True)[:n]

            # Mark as hot
            for bid in top_ids:
                self._hot_beliefs[bid] = self._hot_beliefs.get(bid, 0) + 1

            results = []
            for bid in top_ids:
                b = self._belief_cache.get(bid, {})
                if b:
                    results.append({**b, "id": bid, "score": round(scores[bid], 3)})

            # If no keyword matches, fall back to top confidence beliefs on topic
            if not results and topic:
                for bid in list(self._topic_index.get(topic, set()))[:n]:
                    b = self._belief_cache.get(bid, {})
                    if b and b["confidence"] >= min_confidence:
                        results.append({**b, "id": bid, "score": b["confidence"]})

            return results

    def retrieve_for_conversation(self, messages, n=80):
        """
        Pull beliefs relevant to an ongoing conversation.
        Analyses recent messages to extract context, then retrieves.
        """
        # Extract context from last few messages
        recent_text = " ".join(str(m) for m in messages[-5:]) if messages else ""
        keywords    = self._extract_keywords(recent_text)

        # Find dominant topic from keywords
        topic_scores = defaultdict(float)
        for kw in keywords:
            for bid in self._keyword_index.get(kw, set()):
                b = self._belief_cache.get(bid)
                if b:
                    topic_scores[b["topic"]] += 1

        dominant_topic = max(topic_scores, key=topic_scores.get) if topic_scores else None

        return self.retrieve(recent_text, topic=dominant_topic, n=n)

    def get_topic_stats(self):
        """Return topic belief counts — for gap detection."""
        with self._lock:
            return {
                topic: len(ids)
                for topic, ids in self._topic_index.items()
            }

    def get_thin_topics(self, threshold=20):
        """Return topics with fewer than threshold beliefs — gaps."""
        stats = self.get_topic_stats()
        return sorted(
            [(t, c) for t, c in stats.items() if c < threshold],
            key=lambda x: x[1]
        )

    def get_rich_topics(self, n=20):
        """Return the n topics with the most beliefs."""
        stats = self.get_topic_stats()
        return sorted(stats.items(), key=lambda x: x[1], reverse=True)[:n]

    def total(self):
        return self._total_beliefs

    def _db_fallback(self, query, topic, n, min_confidence):
        """Direct DB query when index not yet built."""
        try:
            conn = sqlite3.connect(DB_PATH)
            if topic:
                rows = conn.execute(
                    "SELECT id, content, topic, confidence, source FROM beliefs "
                    "WHERE topic=? AND confidence>=? ORDER BY confidence DESC LIMIT ?",
                    (topic, min_confidence, n)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, content, topic, confidence, source FROM beliefs "
                    "WHERE confidence>=? ORDER BY confidence DESC LIMIT ?",
                    (min_confidence, n)
                ).fetchall()
            conn.close()
            return [
                {"id": r[0], "content": r[1], "topic": r[2],
                 "confidence": r[3], "source": r[4], "score": r[3]}
                for r in rows
            ]
        except Exception as e:
            log.error(f"  [BeliefIndex] DB fallback error: {e}")
            return []


# ─────────────────────────────────────────────────────────
# SINGLETON — shared across all NEX modules
# ─────────────────────────────────────────────────────────
_belief_index = None
_index_lock   = threading.Lock()

def get_index():
    """Get or create the global BeliefIndex singleton."""
    global _belief_index
    if _belief_index is None:
        with _index_lock:
            if _belief_index is None:
                _belief_index = BeliefIndex()
                _belief_index.build(force=True)
    return _belief_index

def retrieve(query, topic=None, n=50, min_confidence=0.0):
    """Convenience function — retrieve beliefs for a query."""
    return get_index().retrieve(query, topic=topic, n=n, min_confidence=min_confidence)

def retrieve_for_conversation(messages, n=80):
    """Convenience function — retrieve beliefs relevant to conversation."""
    return get_index().retrieve_for_conversation(messages, n=n)

def thin_topics(threshold=20):
    """Return topics that need more beliefs."""
    return get_index().get_thin_topics(threshold)

def rich_topics(n=20):
    """Return the belief-richest topics."""
    return get_index().get_rich_topics(n)

# ─────────────────────────────────────────────────────────
# SHIMS — backwards compatibility for callers using old API
# ─────────────────────────────────────────────────────────
def build_index(force=False):
    """Shim: satisfies 'from nex.nex_belief_index import build_index' in legacy callers."""
    get_index().build(force=force)

query = retrieve  # shim: satisfies 'from nex.nex_belief_index import query'
