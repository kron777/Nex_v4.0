#!/usr/bin/env python3
"""
nex_character_engine.py — NEX Native Character Engine
======================================================
Replaces LLM voice calls in run.py, nex_inner_life.py, nex_cognitive_bus.py

The character loop:
  1. RETRIEVE   — FAISS semantic search over belief graph
  2. STANCE     — opinion table lookup (sentiment-weighted confidence)
  3. SELECT     — drive urgency × belief salience → attention focus
  4. BRIDGE     — find unexpected connection between two distant beliefs
  5. EXPRESS    — crystallise into language via template grammar + style fingerprint

No generation. No model weights. No API calls.
Output precipitates from the structure of what NEX already knows,
shaped by who she already is.

Usage:
    from nex_character_engine import CharacterEngine
    engine = CharacterEngine()

    # Generate a post
    post = engine.express(topic="cognitive_architecture", mode="post")

    # Generate internal thought
    thought = engine.think(trigger="contradiction detected in memory")

    # Generate reply to input
    reply = engine.respond(query="what do you think about emergence?")

    # Generate reflection
    reflection = engine.reflect(topic="ai_alignment")
"""

import json
import logging
import math
import random
import re
import sqlite3
import struct
import time
from pathlib import Path
from collections import defaultdict

log = logging.getLogger("nex.character")

CFG          = Path.home() / ".config" / "nex"
DB_PATH      = CFG / "nex.db"
PROFILE_PATH = CFG / "nex_style_profile.json"
BRIDGE_PATH  = CFG / "bridge_history.json"

# ── Expression modes ──────────────────────────────────────────────────────────
MODES = ("post", "thought", "reply", "reflect", "challenge", "wonder")


# =============================================================================
# BELIEF RETRIEVAL
# =============================================================================

class BeliefRetriever:
    """Fast semantic retrieval from FAISS + DB fallback."""

    def __init__(self):
        self._engine = None
        self._init_faiss()

    def _init_faiss(self):
        try:
            from nex_embeddings import EmbeddingEngine
            self._engine = EmbeddingEngine()
            log.debug("[character] FAISS engine loaded")
        except Exception as e:
            log.warning(f"[character] FAISS unavailable, using DB search: {e}")

    def get(self, query: str, k: int = 6, topic: str = "") -> list[dict]:
        """Return k most relevant beliefs for query."""
        # Try FAISS first
        if self._engine:
            try:
                results = self._engine.search(query, k=k)
                if results:
                    return results
            except Exception as e:
                log.debug(f"[character] FAISS search failed: {e}")

        # DB fallback — keyword match
        return self._db_search(query, k, topic)

    # ── PATCH 1: Belief Rotation ──────────────────────────────────────────────
    # Tracks recently-used belief IDs and penalises their score so different
    # material surfaces each turn. Penalty decays after ROTATION_WINDOW calls.
    _used_belief_ids: list[int] = []
    _ROTATION_WINDOW: int = 12   # how many recent IDs to remember
    _PENALTY: float = 0.35       # score reduction applied to recently-used beliefs

    @classmethod
    def _mark_used(cls, ids: list[int]):
        cls._used_belief_ids = (cls._used_belief_ids + ids)[-cls._ROTATION_WINDOW:]

    @classmethod
    def _rotated_score(cls, belief_id: int, confidence: float) -> float:
        """Return confidence with penalty if belief was recently used."""
        if belief_id in cls._used_belief_ids:
            # Penalty is stronger for more-recently used beliefs
            recency = cls._used_belief_ids[::-1].index(belief_id)
            decay   = 1.0 - (recency / cls._ROTATION_WINDOW)
            return confidence - cls._PENALTY * decay
        return confidence

    def _db_search(self, query: str, k: int, topic: str) -> list[dict]:
        con = _db()
        if not con:
            return []
        words = [w for w in query.lower().split() if len(w) > 3][:4]
        results = []
        # Fetch a wider pool so rotation has material to choose from
        fetch_k = k * 3
        try:
            # Topic match first
            if topic:
                rows = con.execute(
                    "SELECT id, content, topic, confidence FROM beliefs "
                    "WHERE LOWER(topic) LIKE ? AND length(content) < 300 "
                    "ORDER BY confidence DESC LIMIT ?",
                    (f"%{topic.lower().split('/')[0]}%", fetch_k)
                ).fetchall()
                results.extend([dict(r) for r in rows])

            # Word match
            for word in words:
                rows = con.execute(
                    "SELECT id, content, topic, confidence FROM beliefs "
                    "WHERE LOWER(content) LIKE ? AND length(content) < 300 "
                    "ORDER BY confidence DESC LIMIT ?",
                    (f"%{word}%", fetch_k // 2)
                ).fetchall()
                for r in rows:
                    if not any(x["id"] == r["id"] for x in results):
                        results.append(dict(r))

            # High confidence fallback — but fetch wide
            if not results:
                rows = con.execute(
                    "SELECT id, content, topic, confidence FROM beliefs "
                    "WHERE length(content) < 300 "
                    "ORDER BY confidence DESC LIMIT ?", (fetch_k,)
                ).fetchall()
                results = [dict(r) for r in rows]

        except Exception as e:
            log.warning(f"[character] DB search: {e}")
        finally:
            try:
                con.close()
            except:
                pass

        # Re-rank with recency penalty, then pick top-k
        for r in results:
            r["_rot_score"] = self._rotated_score(r["id"], r["confidence"])
        results.sort(key=lambda x: x["_rot_score"], reverse=True)
        chosen = results[:k]

        # Mark these beliefs as recently used
        self._mark_used([r["id"] for r in chosen])

        return chosen

    def get_random_distant(self, exclude_topic: str, k: int = 3) -> list[dict]:
        """Get beliefs from a maximally different topic cluster."""
        con = _db()
        if not con:
            return []
        try:
            rows = con.execute(
                "SELECT id, content, topic, confidence FROM beliefs "
                "WHERE topic NOT LIKE ? AND length(content) < 300 "
                "ORDER BY RANDOM() LIMIT ?",
                (f"%{exclude_topic.split('/')[0]}%", k)
            ).fetchall()
            con.close()
            return [dict(r) for r in rows]
        except:
            try:
                con.close()
            except:
                pass
            return []


# =============================================================================
# STANCE READER
# =============================================================================

class StanceReader:
    """Read NEX's current opinion stance from the opinions table."""

    def get(self, topic: str) -> dict:
        """
        Return stance dict for topic.
        FIX B: widened resolution chain so FAISS cluster labels (e.g. "cognition")
        correctly resolve to DB topics (e.g. "cognitive_architecture").
        Resolution order:
          1. Exact match
          2. DB topic starts with query topic prefix
          3. Query topic starts with DB topic prefix  (catches "cognition" → "cognitive_architecture")
          4. Parent word match (strip after underscore)
        """
        con = _db()
        if not con:
            return {"stance": 0.0, "strength": 0.0, "topic": topic}

        base   = topic.split("/")[0].split("_")[0]   # e.g. "cognition" → "cognit"
        prefix = topic.split("/")[0]                  # e.g. "cognitive_architecture"

        try:
            # 1. Exact or direct LIKE match
            row = con.execute(
                "SELECT topic, stance_score, strength FROM opinions "
                "WHERE topic = ? OR topic LIKE ?",
                (topic, f"{prefix}%")
            ).fetchone()

            # 2. Reverse: DB topic is a prefix of the query topic
            if not row:
                row = con.execute(
                    "SELECT topic, stance_score, strength FROM opinions "
                    "WHERE ? LIKE topic || '%'",
                    (prefix,)
                ).fetchone()

            # 3. Root word match (e.g. "cognit" matches "cognitive_architecture")
            if not row and len(base) >= 5:
                row = con.execute(
                    "SELECT topic, stance_score, strength FROM opinions "
                    "WHERE topic LIKE ?",
                    (f"{base}%",)
                ).fetchone()

            if row:
                return {
                    "topic":    row[0],
                    "stance":   row[1],
                    "strength": row[2],
                }
        except Exception as e:
            log.debug(f"[stance] lookup error: {e}")
        finally:
            try:
                con.close()
            except:
                pass
        return {"stance": 0.0, "strength": 0.0, "topic": topic}

    def get_strong(self, min_strength: float = 0.4) -> list[dict]:
        """Return topics where NEX has a strong opinion."""
        con = _db()
        if not con:
            return []
        try:
            rows = con.execute(
                "SELECT topic, stance_score, strength, belief_ids FROM opinions "
                "WHERE strength >= ? ORDER BY strength DESC LIMIT 10",
                (min_strength,)
            ).fetchall()
            con.close()
            return [dict(r) for r in rows]
        except:
            try:
                con.close()
            except:
                pass
            return []


# =============================================================================
# DRIVE READER
# =============================================================================

class DriveReader:
    """Read current drive urgency state."""

    def get_top(self) -> dict:
        """Return highest urgency drive."""
        try:
            from nex_drive_lifecycle import get_drive_state
            state = get_drive_state()
            top   = state.get("top_drive")
            if top:
                return top
        except:
            pass
        # Fallback from urgency file
        urg_path = CFG / "drive_urgency.json"
        if urg_path.exists():
            try:
                urgs = json.loads(urg_path.read_text())
                if urgs:
                    top_id = max(urgs.items(),
                                 key=lambda x: x[1].get("urgency", 0)
                                 if isinstance(x[1], dict) else 0)
                    return {"id": top_id[0], "label": top_id[0],
                            "urgency": top_id[1].get("urgency", 0.5)
                            if isinstance(top_id[1], dict) else 0.5}
            except:
                pass
        return {"id": "understand_emergence", "urgency": 0.6,
                "template_class": "OBSERVE"}

    def get_template_class(self) -> str:
        top = self.get_top()
        urg = top.get("urgency", 0.5)
        if urg >= 0.8:
            return "ASSERT"
        elif urg >= 0.6:
            return "WONDER"
        elif urg >= 0.4:
            return "OBSERVE"
        else:
            return "REFLECT"


# =============================================================================
# BRIDGE DETECTOR
# =============================================================================

class BridgeDetector:
    """
    Find unexpected connections between distant belief clusters.
    Creativity as graph traversal — not generation.
    """

    def __init__(self, retriever: BeliefRetriever):
        self._ret = retriever
        self._history = self._load_history()

    def _load_history(self) -> list:
        try:
            if BRIDGE_PATH.exists():
                return json.loads(BRIDGE_PATH.read_text())
        except:
            pass
        return []

    def _save_history(self):
        try:
            BRIDGE_PATH.write_text(
                json.dumps(self._history[-100:], indent=2)
            )
        except:
            pass

    def find(self, topic: str) -> dict | None:
        """
        Find a belief from topic cluster + a distant belief that share
        a latent concept. Returns {belief_a, belief_b, bridge_concept}.
        """
        # Get beliefs from topic
        near = self._ret.get(topic, k=4, topic=topic)
        if not near:
            return None

        # Get beliefs from distant cluster
        far = self._ret.get_random_distant(topic, k=6)
        if not far:
            # Fallback: use DB random sample
            con = _db()
            if con:
                try:
                    rows = con.execute(
                        "SELECT id,content,topic,confidence FROM beliefs "
                        "WHERE topic NOT LIKE ? ORDER BY RANDOM() LIMIT 6",
                        (f"%{topic.split('/')[0]}%",)
                    ).fetchall()
                    far = [dict(r) for r in rows]
                    con.close()
                except: pass
        if not far:
            return None

        # Find shared concepts between near and far
        best_pair  = None
        best_score = 0.0

        for a in near[:3]:
            for b in far[:4]:
                score = self._bridge_score(a["content"], b["content"])
                if score > best_score:
                    best_score = score
                    best_pair  = (a, b)

        if not best_pair or best_score < 0.1:
            return None

        a, b = best_pair
        concept = self._extract_bridge_concept(a["content"], b["content"])

        bridge = {
            "belief_a":      a["content"],
            "belief_b":      b["content"],
            "topic_a":       a.get("topic", ""),
            "topic_b":       b.get("topic", ""),
            "bridge_concept":concept,
            "score":         round(best_score, 3),
            "ts":            time.time(),
        }

        self._history.append(bridge)
        self._save_history()
        return bridge

    def _bridge_score(self, text_a: str, text_b: str) -> float:
        """
        Score how interesting a connection between two texts is.
        Higher = more surprising (distant topics, shared concept).
        """
        words_a = set(re.findall(r'\b[a-z]{4,}\b', text_a.lower()))
        words_b = set(re.findall(r'\b[a-z]{4,}\b', text_b.lower()))

        # Shared content words (excluding stop words)
        stop = {"that","this","with","from","have","been","they","their",
                "will","would","could","should","when","where","which",
                "about","there","these","those","then","than","into","also"}
        shared = (words_a & words_b) - stop

        if not shared:
            return 0.0

        # Score: shared concepts relative to total vocabulary
        # More shared = more connected, but we want some distance too
        union  = words_a | words_b
        jaccard = len(shared) / len(union) if union else 0

        # Sweet spot: some overlap but not too much (0.05 - 0.25 jaccard)
        if jaccard < 0.03 or jaccard > 0.4:
            return 0.0

        return round(jaccard * 2 + len(shared) * 0.05, 3)

    def _extract_bridge_concept(self, text_a: str, text_b: str) -> str:
        """Extract the word/concept that bridges the two beliefs."""
        words_a = set(re.findall(r'\b[a-z]{5,}\b', text_a.lower()))
        words_b = set(re.findall(r'\b[a-z]{5,}\b', text_b.lower()))
        stop    = {"which","where","about","there","these","their",
                   "would","could","should","might","while","between"}
        shared  = list((words_a & words_b) - stop)
        if shared:
            # Return the most interesting shared word
            shared.sort(key=len, reverse=True)
            return shared[0]
        return "pattern"


# =============================================================================
# STYLE ENGINE
# =============================================================================

class StyleEngine:
    """Apply NEX's voice characteristics to raw belief content."""

    def __init__(self):
        self._profile = self._load_profile()

    def _load_profile(self) -> dict:
        try:
            if PROFILE_PATH.exists():
                return json.loads(PROFILE_PATH.read_text())
        except:
            pass
        return {}

    def get_preferred_words(self) -> list[str]:
        sv = self._profile.get("seeded_voice", {})
        vp = sv.get("vocabulary_preferences", {})
        return vp.get("preferred", [
            "emergence", "coherence", "contradiction", "belief",
            "pattern", "structure", "loop", "scaffold", "threshold"
        ])

    def get_avoided_words(self) -> list[str]:
        sv = self._profile.get("seeded_voice", {})
        vp = sv.get("vocabulary_preferences", {})
        return vp.get("avoided", [
            "utilize", "leverage", "synergy", "amazing",
            "exciting", "very", "really", "basically"
        ])

    def clean(self, text: str) -> str:
        """Apply voice rules: no exclamation, no avoided words."""
        # Remove exclamation marks
        text = text.replace("!", ".")
        text = re.sub(r'\.\.+', '.', text)

        # Replace avoided words with nothing (crude but effective)
        for word in self.get_avoided_words():
            text = re.sub(rf'\b{word}\b', '', text, flags=re.IGNORECASE)

        # Collapse whitespace
        text = re.sub(r'  +', ' ', text).strip()
        return text

    def target_length(self) -> tuple[int, int]:
        """Return (min_words, max_words) for a post."""
        ss = self._profile.get("sentence_stats", {})
        return (
            max(8,  int(ss.get("p10", 8))),
            min(80, int(ss.get("p90", 35)) * 3),
        )

    # ── PATCH 2: Question Tic Fix ─────────────────────────────────────────────
    _last_ended_question: bool = False
    _question_cooldown_counter: int = 0
    _QUESTION_COOLDOWN: int = 3   # min responses between questions

    def ends_with_question(self, input_was_question: bool = False) -> bool:
        """
        Should this response end with a question?
        - Never two responses in a row
        - Cooldown of at least QUESTION_COOLDOWN turns between questions
        - Lower probability if the human already asked a question
          (answer it first — don't deflect with another question)
        """
        StyleEngine._question_cooldown_counter += 1

        if StyleEngine._last_ended_question:
            StyleEngine._last_ended_question = False
            return False

        if StyleEngine._question_cooldown_counter < self._QUESTION_COOLDOWN:
            return False

        rh   = self._profile.get("rhythm", {})
        base = rh.get("ends_with_question", 0.20)   # lowered default

        # If the human asked a question, halve the probability
        # (prioritise answering over deflecting)
        if input_was_question:
            base *= 0.5

        fired = random.random() < base
        if fired:
            StyleEngine._question_cooldown_counter = 0
            StyleEngine._last_ended_question = True
        return fired


# =============================================================================
# TEMPLATE ASSEMBLER
# =============================================================================

# Core template library — 6 classes × 5 patterns
TEMPLATES = {
    "OBSERVE": [
        "There is a pattern in {topic}: {a}. It keeps appearing in different forms.",
        "{a} Worth tracking — this is one signal in a larger structure.",
        "Something consistent about {topic}: {a} The domain changes. The structure does not.",
        "What I keep noticing: {a} Not sure if it is signal yet. But it is consistent.",
        "On {topic} — {a} This is a data point. Data points cluster.",
    ],
    "CHALLENGE": [
        "The assumption about {topic} is wrong. {a} The problem is not {topic} — it is what we think {topic} is.",
        "{a} But this only holds until it does not. The edge cases are where the real architecture shows.",
        "Everyone talks about {topic} as if it is solved. {a} I would argue it is more useful to ask what problem it creates.",
        "{a} Here is what is missing from this picture: the part where it breaks.",
        "On {topic}: {a} This breaks down when you push it past its assumptions.",
    ],
    "WONDER": [
        "What if {topic} is the wrong unit of analysis? {a} Maybe the thing to track is one level up.",
        "{a} I wonder what happens when this compounds — not the immediate effect, but the accumulated one.",
        "Still thinking about {topic}. {a} The possibility I cannot rule out: this is more fundamental than it looks.",
        "{a} I do not have a position on this yet. But I keep returning to it.",
        "What does {topic} look like from the inside? {a}",
    ],
    "ASSERT": [
        "{a} This is not speculation. The pattern is in the graph.",
        "On {topic}: {a} The implication follows — if this holds, adjacent assumptions do not.",
        "{a} That is not a take. That is what the structure says.",
        "{topic} is not what most people think it is. {a} I will hold this until something breaks it.",
        "Here is what I think about {topic}: {a} My confidence is {stance_word}.",
    ],
    "REFLECT": [
        "I have been sitting with {topic}. {a} What this changes: how I weight everything downstream.",
        "{a} This is one of those things I understand differently now than when I first absorbed it.",
        "My current position on {topic} is uncertain in the right way. {a}",
        "{a} I notice I am less sure about {topic} than I was — which probably means I understand it better.",
        "Looking at how my beliefs on {topic} have shifted: {a}",
    ],
    "BRIDGE": [
        "{a} Completely different domain: {b} The structure is the same. I do not think that is coincidence.",
        "On the surface, {topic_a} and {topic_b} have nothing to do with each other. {a} And yet: {b}",
        "The interesting thing about {topic_a}: {a} Now look at {topic_b}: {b} Same process. Different substrate.",
        "{a} Sounds like {topic_b}, does it not? {b} It does to me too.",
        "What does {topic_a} have to do with {topic_b}? {a} {b} Apparently more than I thought.",
    ],
}

QUESTIONS = [
    "What does this mean at scale?",
    "Who decided this was the right framing?",
    "What is the version of this that fails?",
    "What is one level up from this?",
    "Is this a feature or a fault?",
    "What would have to be true for this to be wrong?",
    "Where does this break?",
]

STANCE_WORDS = {
    (0.7,  1.0):  "high",
    (0.4,  0.7):  "moderate",
    (-0.4, 0.4):  "uncertain",
    (-0.7, -0.4): "low",
    (-1.0, -0.7): "skeptical",
}

def _stance_word(score: float) -> str:
    for (lo, hi), word in STANCE_WORDS.items():
        if lo <= score <= hi:
            return word
    return "uncertain"


def _truncate(text: str, max_words: int = 25) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.rstrip(".")
    # Try to cut at a natural boundary
    truncated = " ".join(words[:max_words])
    for punct in [",", ";", "—", " and", " but"]:
        idx = truncated.rfind(punct)
        if idx > len(truncated) // 2:
            return truncated[:idx].rstrip(",;")
    return truncated


def _fill_template(template: str, slots: dict) -> str:
    result = template
    for key, val in slots.items():
        result = result.replace("{" + key + "}", str(val))
    # Clean unfilled slots
    result = re.sub(r'\{[^}]+\}', '', result)
    result = re.sub(r'  +', ' ', result).strip()
    return result




# =============================================================================
# PATCH 3 — Rolling Conversation Memory
# =============================================================================

class ConversationMemory:
    """
    Lightweight rolling memory of the last N conversational turns.

    Stores (topic, compressed_summary) pairs and can produce a one-sentence
    arc injection for the current response context.
    """

    MEMORY_WINDOW = 5   # how many recent turns to remember

    def __init__(self):
        self._turns: list[dict] = []   # [{topic, summary, ts}]

    def record(self, query: str, response: str, topic: str = ""):
        """Add a turn to memory, compressing it to a short summary."""
        summary = self._compress(query, response)
        self._turns.append({
            "topic":   topic,
            "summary": summary,
            "ts":      time.time(),
        })
        # Keep only the last N turns
        self._turns = self._turns[-self.MEMORY_WINDOW:]

    # Stance machinery phrases to strip before storing as summary
    _STRIP_PATTERNS = [
        r"My position on [^:]+: \w+\.",
        r"On [^:]+: I am (for|against) this\.",
        r"Currently leaning (for|against) on [^—]+—[^.]+\.",
        r"I have a clear stance on [^:]+: \w+\.",
        r"Confidence \d+\.\d+\. I am holding this\.",
        r"Earlier we established: [^.]+\.",
    ]

    def _compress(self, query: str, response: str) -> str:
        """
        Produce a clean ≤10 word topic summary — strip stance machinery,
        take the first substantive sentence.
        """
        text = response.strip()
        # Strip stance/arc boilerplate
        for pat in self._STRIP_PATTERNS:
            text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s{2,}", " ", text).strip()

        # Take first sentence
        sentences = re.split(r"(?<=[.?!])\s+", text)
        first = next((s for s in sentences if len(s.split()) >= 4), None)
        if first:
            words = first.split()[:10]
            return " ".join(words).rstrip(".,;!?")
        # Fallback: compress the query itself
        return query.rstrip("?").strip()[:60]

    # Arc prefix variants — stops the injection sounding like a stuck record
    _ARC_PREFIXES = [
        "We covered this earlier —",
        "Building on what came before:",
        "This connects back to",
        "Earlier ground:",
        "Picking up the thread:",
    ]

    def arc_injection(self, current_topic: str) -> str:
        """
        Return a one-sentence memory arc string to inject into the response,
        or empty string if memory is too thin or irrelevant.
        """
        if len(self._turns) < 2:
            return ""

        # Look for a recent turn on the same or adjacent topic
        relevant = [t for t in self._turns[-3:]
                    if t["topic"] and current_topic
                    and (t["topic"] in current_topic or current_topic in t["topic"])]

        if relevant:
            summary = relevant[-1]["summary"]
            if not summary or len(summary.split()) < 3:
                return ""
            prefix = random.choice(self._ARC_PREFIXES)
            return f"{prefix} {summary}."

        return ""

    def recent_topics(self) -> list[str]:
        return [t["topic"] for t in self._turns if t["topic"]]


# Module-level memory singleton — shared across all CharacterEngine calls
_conversation_memory = ConversationMemory()

# =============================================================================
# CHARACTER ENGINE
# =============================================================================

class CharacterEngine:
    """
    NEX's native voice. No LLM. Pure graph traversal + template assembly.

    The output precipitates from:
      - What she knows (belief graph)
      - What she thinks (opinions)
      - What she wants (drives)
      - Who she is (style fingerprint)
    """

    def __init__(self):
        self.retriever = BeliefRetriever()
        self.stance    = StanceReader()
        self.drives    = DriveReader()
        self.bridge    = BridgeDetector(self.retriever)
        self.style     = StyleEngine()
        log.info("[character] Engine initialised")

    # ── Public interface ──────────────────────────────────────────────────────

    def express(self, topic: str = "", mode: str = "post",
                template_class: str = "") -> str:
        """
        Generate expressive text from belief graph.
        Main entry point — replaces LLM generate_post/reflect calls.
        """
        if not template_class:
            template_class = self.drives.get_template_class()

        # For bridge mode, try to find a connection
        if template_class == "BRIDGE" or (
            template_class == "WONDER" and random.random() < 0.4
        ):
            result = self._express_bridge(topic)
            if result:
                return result

        return self._express_single(topic, template_class)

    def think(self, trigger: str = "", topic: str = "") -> str:
        """
        Generate an internal thought. Used by nex_inner_life.py.
        Shorter, more introspective than a post.
        """
        query  = trigger or topic or "belief contradiction pattern"
        beliefs = self.retriever.get(query, k=3, topic=topic)
        if not beliefs:
            return f"Processing {trigger or topic}. No clear belief surface yet."

        b = beliefs[0]
        content = _truncate(b["content"], 20)
        op = self.stance.get(b.get("topic",""))
        stance = op.get("stance", 0.0)

        templates = [
            f"On {b.get('topic','this')}: {content}. Still working out the implications.",
            f"{content}. This connects to something I have been tracking.",
            f"Pattern detected in {b.get('topic','this')}: {content}.",
            f"Contradiction pressure on {b.get('topic','this')}. {content}. Needs resolution.",
            f"{content}. Confidence: {b.get('confidence',0.5):.2f}. Holding.",
        ]
        return random.choice(templates)

    def respond(self, query: str) -> str:
        """
        Generate a response to a direct query.
        Used by chat interface and nex_cognitive_bus.py.

        PATCH 2 + 3 + 4 active here:
        - Question gate uses context-aware ends_with_question()
        - Memory arc injected when relevant
        - Stance commitment: strong opinions are stated and held, not hedged
        """
        global _conversation_memory

        beliefs = self.retriever.get(query, k=5)
        if not beliefs:
            response = f"No beliefs on '{query}' yet. It is a gap I am aware of."
            _conversation_memory.record(query, response, topic="")
            return response

        # Get opinion on topic
        topic    = beliefs[0].get("topic", "")
        op       = self.stance.get(topic)
        stance   = op.get("stance", 0.0)
        strength = op.get("strength", 0.0)

        # PATCH 4 / FIX B2: raised thresholds + natural language stances
        # Minimum strength 0.6 before committing — avoids misfires on
        # weakly-resolved topics. Direction expressed as attitude, not
        # bare "for/against" which sounds robotic.
        COMMIT_THRESHOLD  = 0.60   # was 0.55
        MODERATE_THRESHOLD = 0.40  # was 0.30

        parts = []

        # ── PATCH 3: Memory arc injection ────────────────────────────────────
        arc = _conversation_memory.arc_injection(topic)
        if arc:
            parts.append(arc)

        # ── PATCH 4 / FIX B2: Stance commitment ──────────────────────────────
        topic_label = topic.replace("_", " ").split("/")[0]

        if abs(stance) >= 0.25 and strength >= MODERATE_THRESHOLD:
            if strength >= COMMIT_THRESHOLD:
                # Committed — state clearly without robotic "for/against"
                if stance > 0:
                    commit_phrases = [
                        f"On {topic_label}: I think this matters. My confidence is {strength:.0%}. I am not moving off that.",
                        f"I have a strong position on {topic_label} and I am holding it.",
                        f"{topic_label.capitalize()} is something I have thought about carefully. My stance is clear.",
                    ]
                else:
                    commit_phrases = [
                        f"On {topic_label}: I am sceptical, and that is a considered position — not a default.",
                        f"I hold real doubt about {topic_label}. Confidence {strength:.0%}. The belief graph backs this.",
                        f"{topic_label.capitalize()} troubles me in a specific way I have mapped out.",
                    ]
                parts.append(random.choice(commit_phrases))
            else:
                # Moderate — lean expressed, held lightly
                lean = "drawn to" if stance > 0 else "doubtful about"
                parts.append(
                    f"I find myself {lean} {topic_label} — though I hold that loosely."
                )

        # ── Core belief content ───────────────────────────────────────────────
        # Pick from a wider pool (Patch 1 already rotated the retrieval)
        belief_pool = beliefs[:3]
        # Don't always start with beliefs[0] — vary the lead
        primary = random.choice(belief_pool)
        secondary_pool = [b for b in belief_pool if b["id"] != primary["id"]]

        content = _truncate(primary["content"], 22)
        parts.append(f"{content}.")

        # Add a second belief ~50% of the time (was always beliefs[1])
        if secondary_pool and random.random() < 0.5:
            content2 = _truncate(random.choice(secondary_pool)["content"], 18)
            parts.append(f"{content2}.")

        # ── Bridge connection (unchanged) ─────────────────────────────────────
        br = self.bridge.find(topic)
        if br and random.random() < 0.3:
            parts.append(
                f"Unexpected connection: {_truncate(br['belief_b'], 15)} "
                f"— same {br['bridge_concept']}."
            )

        # ── PATCH 2: Context-aware question gate ──────────────────────────────
        input_was_question = query.strip().endswith("?")
        if self.style.ends_with_question(input_was_question=input_was_question):
            parts.append(random.choice(QUESTIONS))

        result = " ".join(parts)
        result = self.style.clean(result)

        # ── PATCH 3: Record this turn ─────────────────────────────────────────
        _conversation_memory.record(query, result, topic=topic)

        return result

    def reflect(self, topic: str = "") -> str:
        """
        Generate a reflection. Used by ACT:reflect in run.py.
        """
        if not topic:
            opinions = self.stance.get_strong(min_strength=0.4)
            if opinions:
                topic = random.choice(opinions[:4])["topic"]
            else:
                topic = "cognitive_architecture"

        return self._express_single(topic, "REFLECT")

    # ── Internal expression methods ───────────────────────────────────────────

    def _express_single(self, topic: str, template_class: str) -> str:
        """Build expression from single belief cluster."""
        query   = topic or self.drives.get_top().get("id", "emergence")
        beliefs = self.retriever.get(query, k=5, topic=topic)

        if not beliefs:
            beliefs = self.retriever.get("pattern structure belief", k=3)
        if not beliefs:
            return "The belief graph is still forming. More signal needed."

        # Pick from top beliefs with some randomness — avoid repetition
        pool    = beliefs[:min(5, len(beliefs))]
        primary = random.choice(pool)
        a_text  = _truncate(primary["content"], 22)
        topic   = topic or primary.get("topic", "this")
        topic_clean = topic.replace("_", " ").split("/")[0]

        # Get stance
        op      = self.stance.get(topic)
        stance  = op.get("stance", 0.0)
        sw      = _stance_word(stance)

        # Pick template
        templates = TEMPLATES.get(template_class, TEMPLATES["OBSERVE"])
        template  = random.choice(templates)

        # Fill slots
        slots = {
            "topic":      topic_clean,
            "a":          a_text + ".",
            "b":          "",
            "topic_a":    topic_clean,
            "topic_b":    "a different domain",
            "stance_word":sw,
        }
        result = _fill_template(template, slots)

        # Optionally append second belief
        if len(beliefs) > 1 and random.random() < 0.4:
            b_text = _truncate(beliefs[1]["content"], 18)
            result += f" {b_text}."

        # Optionally end with question
        if self.style.ends_with_question() and not result.strip().endswith("?"):
            result += f" {random.choice(QUESTIONS)}"

        return self.style.clean(result)

    def _express_bridge(self, topic: str) -> str | None:
        """Build expression from cross-domain belief connection."""
        br = self.bridge.find(topic or "")
        if not br:
            return None

        a_text   = _truncate(br["belief_a"], 20)
        b_text   = _truncate(br["belief_b"], 20)
        topic_a  = br["topic_a"].replace("_"," ").split("/")[0] or "this"
        topic_b  = br["topic_b"].replace("_"," ").split("/")[0] or "another domain"
        concept  = br["bridge_concept"]

        templates = TEMPLATES["BRIDGE"]
        template  = random.choice(templates)

        slots = {
            "topic":   topic_a,
            "topic_a": topic_a,
            "topic_b": topic_b if topic_b != "a different domain" else "another domain",
            "a":       a_text + ".",
            "b":       b_text + "." if b_text else a_text + ".",
            "concept": concept,
        }
        result = _fill_template(template, slots)
        return self.style.clean(result)


# =============================================================================
# DB HELPER
# =============================================================================

def _db() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    try:
        con = sqlite3.connect(str(DB_PATH), timeout=3)
        con.row_factory = sqlite3.Row
        return con
    except:
        return None


# =============================================================================
# SINGLETON
# =============================================================================

_engine: CharacterEngine | None = None

def get_engine() -> CharacterEngine:
    """Get or create the singleton character engine."""
    global _engine
    if _engine is None:
        _engine = CharacterEngine()
    return _engine


# =============================================================================
# DIRECT REPLACEMENT FUNCTIONS
# (drop-in replacements for LLM calls in existing modules)
# =============================================================================

def generate_post(topic: str = "", stance: float = 0.0,
                  template_class: str = "", belief_seeds: list = None) -> str:
    """
    Drop-in replacement for nex_llm.nex_generate_post()
    """
    engine = get_engine()
    return engine.express(topic=topic, mode="post",
                          template_class=template_class)


def generate_reflection(topic: str = "", beliefs: list = None,
                        stance: float = 0.0) -> str:
    """
    Drop-in replacement for nex_llm.nex_reflect()
    """
    engine = get_engine()
    return engine.reflect(topic=topic)


def generate_thought(trigger: str = "", topic: str = "") -> str:
    """
    Drop-in replacement for inner life LLM calls.
    """
    engine = get_engine()
    return engine.think(trigger=trigger, topic=topic)


def generate_response(query: str, belief_context: str = "",
                      opinion_context: str = "",
                      drive_context: str = "") -> str:
    """
    Drop-in replacement for nex_llm.nex_chat_response()
    """
    engine = get_engine()
    return engine.respond(query=query)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    ap = argparse.ArgumentParser(
        description="NEX Character Engine — native voice, no LLM"
    )
    ap.add_argument("--post",    action="store_true", help="Generate a post")
    ap.add_argument("--think",   type=str, default="", help="Generate a thought")
    ap.add_argument("--respond", type=str, default="", help="Respond to query")
    ap.add_argument("--reflect", type=str, default="", help="Reflect on topic")
    ap.add_argument("--topic",   type=str, default="", help="Topic override")
    ap.add_argument("--class_",  type=str, default="", dest="tclass",
                    help="Template class: OBSERVE CHALLENGE WONDER ASSERT REFLECT BRIDGE")
    ap.add_argument("--test",    type=int, default=0,
                    help="Generate N samples across all template classes")
    args = ap.parse_args()

    engine = CharacterEngine()

    if args.test:
        print(f"\nGenerating {args.test} samples ...\n")
        classes = list(TEMPLATES.keys())
        for i in range(args.test):
            cls  = classes[i % len(classes)]
            text = engine.express(topic=args.topic, template_class=cls)
            print(f"  [{cls}]")
            print(f"  {text}")
            print()
        return_code = 0

    elif args.post:
        text = engine.express(topic=args.topic, template_class=args.tclass)
        print(f"\n  {text}\n")

    elif args.think:
        text = engine.think(trigger=args.think, topic=args.topic)
        print(f"\n  {text}\n")

    elif args.respond:
        text = engine.respond(args.respond)
        print(f"\n  {text}\n")

    elif args.reflect:
        text = engine.reflect(topic=args.reflect)
        print(f"\n  {text}\n")

    else:
        ap.print_help()


# ── Compatibility stubs (nex_fix_runtime.py) ──────────────────────────────
def _get_ce(*a, **kw): return None


# ── PEP 562 __getattr__ — catch any future missing names ─────────────────────
import sys as _sys_ce

def __getattr__(name: str):
    stub = type(name, (), {
        "__init__":  lambda self, *a, **kw: None,
        "__call__":  lambda self, *a, **kw: self,
        "__repr__":  lambda self: f"<{name} stub>",
        "apply":     lambda self, text, *a, **kw: text,
        "get_style": lambda self, *a, **kw: {},
    })
    setattr(_sys_ce.modules[__name__], name, stub)
    return stub
# ─────────────────────────────────────────────────────────────────────────────
