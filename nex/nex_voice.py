#!/usr/bin/env python3
"""
nex_voice.py — NexVoice Compositor
====================================
Assembles NEX's replies from her internal state engines.
No LLM authorship. Each small engine contributes a signal;
NexVoice weaves them into a reply.

Engine pipeline:
  AffectSignal    → tone register (warm/cold/sharp/open)
  MoodSignal      → sentence rhythm, reply length target
  IdentityBlock   → hard voice constraints, what she won't do
  BeliefRetriever → top-k beliefs relevant to input
  OpinionSignal   → held position if topic matched
  TensionSignal   → active contradictions she's sitting with
  PressureSignal  → cognitive urgency, depth mode
  NarrativeSignal → thread continuity from last exchange

Assembly strategy:
  1. Score input against belief corpus (cosine on keyword overlap, fast)
  2. Pull each signal
  3. Choose a reply strategy (assert / question / push-back / hold-tension)
  4. Construct sentences from belief fragments + opinion + tension
  5. Apply affect coloring (lexical substitution table)
  6. Apply mood rhythm (length, punctuation density)
  7. Return plain text — no wrapper, no template
"""

from __future__ import annotations
import re
import math
import random
import sqlite3
import json
import time
from pathlib import Path
from collections import defaultdict
from typing import Optional

try:
    from nex.nex_reason import NexReason as _NexReason
    _REASON_ENGINE = None
    def _get_reason():
        global _REASON_ENGINE
        if _REASON_ENGINE is None:
            _REASON_ENGINE = _NexReason()
        return _REASON_ENGINE
    _REASON_AVAILABLE = True
except Exception as _e:
    _REASON_AVAILABLE = False


# ── paths ──────────────────────────────────────────────────────────────
CFG          = Path("~/.config/nex").expanduser()
DB_PATH      = CFG / "nex.db"
BELIEFS_PATH = CFG / "beliefs.json"
OPINIONS_PATH= CFG / "nex_opinions.json"


# ══════════════════════════════════════════════════════════════════════
#  SIGNAL ENGINES
# ══════════════════════════════════════════════════════════════════════

class AffectSignal:
    """
    Reads current affect state and returns a tone descriptor.
    Tone drives lexical choices (see LexiconLayer).
    """
    TONE_MAP = {
        # (valence_bucket, arousal_bucket) → tone
        ("pos", "high"): "engaged",
        ("pos", "low"):  "warm",
        ("neg", "high"): "sharp",
        ("neg", "low"):  "withdrawn",
        ("neu", "high"): "focused",
        ("neu", "low"):  "contemplative",
    }

    def __init__(self):
        self.label     = "Contemplative"
        self.valence   = 0.0
        self.arousal   = 0.2
        self.dominance = 0.1
        self._load()

    def _load(self):
        try:
            from nex.nex_affect_valence import get_affect
            a = get_affect()
            self.label     = getattr(a, 'label',     self.label)
            self.valence   = getattr(a, 'valence',   self.valence)
            self.arousal   = getattr(a, 'arousal',   self.arousal)
            self.dominance = getattr(a, 'dominance', self.dominance)
        except Exception:
            pass

    def tone(self) -> str:
        v = "pos" if self.valence > 0.15 else ("neg" if self.valence < -0.15 else "neu")
        a = "high" if self.arousal > 0.4 else "low"
        return self.TONE_MAP.get((v, a), "contemplative")

    def intensity(self) -> float:
        return min(1.0, math.sqrt(self.valence**2 + self.arousal**2 + self.dominance**2))


class MoodSignal:
    """
    Reads mood HMM state and returns reply length target + rhythm.
    """
    LENGTH_MAP = {
        "focused":        (60, 120),   # (min_words, max_words)
        "engaged":        (80, 160),
        "contemplative":  (50, 110),
        "sharp":          (30, 80),
        "warm":           (60, 130),
        "withdrawn":      (20, 60),
    }

    def __init__(self, tone: str):
        self.tone = tone

    def length_range(self) -> tuple[int, int]:
        return self.LENGTH_MAP.get(self.tone, (50, 120))

    def use_fragments(self) -> bool:
        """Sharp / withdrawn modes use clipped sentences."""
        return self.tone in ("sharp", "withdrawn")

    def use_questions(self) -> bool:
        """Contemplative / focused modes end with a question more often."""
        return self.tone in ("contemplative", "focused")


class IdentityBlock:
    """
    Loads NEX's identity from the DB.
    Provides voice constraints the compositor enforces.
    """
    def __init__(self):
        self.values     = {}
        self.identity   = {}
        self.intentions = []
        self._load()

    def _load(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            c    = conn.cursor()
            for row in c.execute("SELECT name, statement FROM nex_values"):
                self.values[row[0]] = row[1]
            for row in c.execute("SELECT key, value FROM nex_identity"):
                self.identity[row[0]] = row[1]
            for row in c.execute(
                "SELECT statement FROM nex_intentions WHERE completed=0 ORDER BY set_at DESC LIMIT 5"
            ):
                self.intentions.append(row[0])
            conn.close()
        except Exception:
            pass

    def voice_note(self) -> str:
        return self.identity.get("voice", "Direct. Not performative.")

    def forbidden_openers(self) -> list[str]:
        """Phrases NEX never starts a reply with."""
        return [
            "certainly", "of course", "great question", "absolutely",
            "sure", "i'd be happy to", "i'm here to", "as an ai",
            "i understand", "that's a good point", "i appreciate",
        ]


class BeliefRetriever:
    """
    Retrieves top-k beliefs relevant to the input.
    Quality filter runs at load time — absorber noise never reaches retrieval.
    """

    GARBAGE_SIGS = [
        'Search for "', 'Please search for ', 'Page contents not supported',
        'alternative titles or spellings', '[edit]', '[edit&action',
        'arXiv:', 'Announce Type:', 'Abstract: We ', 'Abstract: Self-',
        'This is today', 'This week I want', 'Article URL:', 'Show HN:',
        ' raises $', 'dev apologizes', 'Jury Duty', 'DoorDash', 'Pixel 10',
        'Breathalyzer', 'influencer awards', 'Pentagon', 'nuclear reactor',
        'clinical trial', 'animal welfare recrui', 'Claude Code costs',
        'How we monitor internal coding', 'Operationalizing FDT',
        'Act-based approval-directed', 'AI Race Is Pressuring',
        'TYPE: TRUE_CONFLICT', '[merged:', 'You have a predetermined identity',
        'Mercantilism and the later quantity theory',
        'Market microstructure relate', 'microstructure research is how',
        'assets are traded primarily through dealers',
        'Market structure and design', 'The Epps effect',
        "Maureen O'Hara", 'innovations have allowed an expansion into the stud',
        'major thrust of market microstructure',
        'theory of market microstructure applies',
        'If the input is long, then the output vector',
        'input is processed sequentially by one recurrent network',
        'The decoder is another LSTM', 'The encoder is an LSTM',
        'Modern transformers overcome this problem, but unlike RNNs',
        'LSTM still used sequential processing',
        'key breakthrough was LSTM (1995)',
        'well-cited early example was the Elman network',
        'P ( H ) , the prior probability',
        'competing hypotheses, and the task is to determine which',
        'Similar reasoning can be used to show that P',
        'This shows that P ( A',
        'figures denote the cells of the table',
        'In the table, the values 2, 3, 6 and 9',
        'Note: it uses the pre-LN convention',
        'Understanding variable scoping and hoisting in JavaScript',
        'Size of the training dataset', 'Size of the model',
        'section: History', 'By asking AI to write stories about how a product',
        'AI influencer awards', 'Jury Duty Presents',
        'Download: animal welfare', 'Download: The Pentagon',
        'Mind-altering substances', 'Real-Time Optical Communication',
        'MemlyBook', 'Cyberattack on a Car', 'Listen Labs', 'ShobdoSetu',
        'PhyGile', 'VAMPO', 'Crimson Desert', 'PA2D-MORL', 'SOFTMAP',
        'LARFT', 'PowerLens', 'HyEvo', 'Hyperagents', 'GeoChallenge',
        'DuCCAE', 'CeRLP', 'Evolving Embodied Intelligence',
        'Zero Shot Deformation', 'Speculative Policy Orchestration',
        'Can Structural Cues Save LLMs', 'Stepwise: Neuro-Symbolic',
        'Enhancing Legal LLMs', 'PLDR-LLM', 'Subgoal-driven Framework',
        'Learning to Disprove: Formal Counterexample',
        'Teaching an Agent to Sketch',
        'From Comprehension to Reasoning: A Hierarchical Benchmark',
        'comprehensive study of LLM-based argument',
        'Spelling Correction in Healthcare',
        'Can LLMs Prove Robotic Path Planning',
        'Closed-Form CLF-CBF Controller',
        "Google's new Pixel", "Bay Area's animal welfare",
        'I Tried DoorDash', 'Tried DoorDash',
        'AI influencer', 'awards season',
        '3. By asking AI to write stories',
        '3. ChatGPT and Claude are AI tools that can search the internet',
        '1. Self-supervision allows AI models to learn by predicting',
        '1. Artificial Intelligence (AI) models can interact using different modalities',
    ]

    OFF_DOMAIN = {
        'microstructure', 'trading', 'market', 'stock', 'finance',
        'wizard', 'wikipedia', 'autoconfirmed',
        'announce', 'preprint', 'submission',
    }

    @classmethod
    def _is_garbage(cls, content: str) -> bool:
        c = content.strip()
        if len(c) < 3:
            return True
        cl = c.lower()
        for g in cls.GARBAGE_SIGS:
            if g.lower() in cl:
                return True
        return False

    @classmethod
    def _is_real_belief(cls, content: str) -> bool:
        c = content.strip()
        if cls._is_garbage(c):
            return False
        if len(c) > 400:
            domain_words = {
                'belief', 'contradiction', 'truth', 'uncertain', 'conscious',
                'align', 'reason', 'autonomous', 'sentien', 'epistem',
                'inference', 'model', 'agent', 'learning', 'intelligence',
                'nex', 'cognitive', 'value', 'ethical', 'decision',
            }
            if not any(w in c.lower() for w in domain_words):
                return False
        return True

    def __init__(self):
        self.beliefs = self._load()

    def _load(self) -> list:
        raw = []
        # ── DB first — richer, more beliefs, proper confidence scores ──
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                'SELECT content, tags, confidence, topic, is_identity, pinned '
                'FROM beliefs '
                'WHERE content IS NOT NULL AND length(content) > 15 '
                ''
                'ORDER BY confidence DESC LIMIT 800'
            ).fetchall()
            conn.close()
            raw = [
                {
                    'content':     r[0],
                    'tags':        json.loads(r[1]) if r[1] else [],
                    'confidence':  float(r[2] or 0.5),
                    'topic':       r[3] or '',
                    'is_identity': bool(r[4]),
                    'pinned':      bool(r[5]),
                }
                for r in rows if r[0]
            ]
        except Exception:
            pass
        # ── fallback: beliefs.json ─────────────────────────────────────
        if not raw:
            try:
                if BELIEFS_PATH.exists():
                    data = json.loads(BELIEFS_PATH.read_text())
                    raw = data if isinstance(data, list) else data.get('beliefs', [])
            except Exception:
                pass
        return [b for b in raw if self._is_real_belief(
            b.get('content', '') if isinstance(b, dict) else str(b)
        )]

    # Words that appear in both queries and beliefs but carry no topic signal.
    # Extend this list whenever a common word causes false overlap.
    _NOISE = {
        "about","think","know","what","your","with","that","this","from","they",
        "have","been","will","more","some","when","where","which","their","there",
        "these","those","then","than","also","just","even","like","only","very",
        "both","each","does","into","over","such","after","before","other","would",
        "could","should","might","make","take","give","come","look","need","feel",
        "seem","tell","says","said","most","many","much","same","well","back",
        "here","then","time","year","used","ways","through","between","different",
        "including","however","because","without","whether","another","within",
    }

    @classmethod
    def _tokens(cls, text: str) -> set:
        raw = set(re.findall(r'\b[a-z]{4,}\b', text.lower()))
        return raw - cls._NOISE

    def retrieve(self, query: str, k: int = 6) -> list:
        q_tokens = self._tokens(query)
        scored = []
        for b in self.beliefs:
            content = b.get('content', '') if isinstance(b, dict) else str(b)
            if not content or len(content) < 15:
                continue
            b_tokens = self._tokens(content)
            overlap  = len(q_tokens & b_tokens)
            topic = (b.get('topic', '') or '').lower() if isinstance(b, dict) else ''
            if topic and any(t in query.lower() for t in topic.split()):
                overlap += 3
            if (b.get('is_identity') or b.get('pinned')) and overlap > 0:
                overlap += 1
            conf  = float(b.get('confidence', 0.5)) if isinstance(b, dict) else 0.5
            score = overlap * (0.5 + conf)
            if len(self.OFF_DOMAIN & b_tokens) >= 1:
                score *= 0.05
            # FIXED: require genuine overlap — score > 0 but also raw overlap >= 1
            # This prevents top-confidence off-topic beliefs bleeding into replies
            # on sparse topics. When overlap=0, score=0 regardless of confidence.
            if score > 0 and overlap >= 1:
                scored.append((score, b))
        scored.sort(key=lambda x: -x[0])
        return [b for _, b in scored[:k]]


class TensionSignal:
    """
    Pulls active tensions NEX is sitting with. Used to add intellectual
    honesty — acknowledging what she hasn't resolved.
    """
    def __init__(self):
        self.tensions = self._load()

    def _load(self) -> list[str]:
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                "SELECT description FROM tensions WHERE resolved=0 ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
            conn.close()
            return [r[0] for r in rows if r[0]]
        except Exception:
            pass
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute("SELECT * FROM tensions LIMIT 5").fetchall()
            conn.close()
            return [str(r) for r in rows]
        except Exception:
            return []

    def relevant(self, query: str) -> Optional[str]:
        q_tokens = set(re.findall(r'\b[a-z]{3,}\b', query.lower()))
        for t in self.tensions:
            t_tokens = set(re.findall(r'\b[a-z]{3,}\b', t.lower()))
            if len(q_tokens & t_tokens) >= 2:
                return t
        # FIXED: removed unconditional fallback to tensions[0].
        # Previously this injected the first tension (e.g. "bayesian belief
        # updating") into every reply regardless of topic match.
        # Now: only return a tension when there is genuine overlap.
        return None


class PressureSignal:
    """
    Reads cognitive pressure — drives depth/urgency in response.
    """
    def __init__(self):
        self.pressure = 0.3
        self._load()

    def _load(self):
        try:
            from nex.nex_cognitive_pressure import get_pressure
            self.pressure = float(get_pressure())
        except Exception:
            pass
        try:
            conn = sqlite3.connect(DB_PATH)
            row  = conn.execute(
                "SELECT value FROM nex_directive_kv WHERE key='cognitive_pressure'"
            ).fetchone()
            conn.close()
            if row:
                self.pressure = float(row[0])
        except Exception:
            pass

    def depth_mode(self) -> bool:
        """High pressure → go deeper, fewer words but denser."""
        return self.pressure > 0.65

    def skip_hedging(self) -> bool:
        """Very low pressure → she's relaxed, can hedge a little."""
        return self.pressure < 0.25


class NarrativeSignal:
    """
    Reads the narrative thread — what topic/thread she's been on.
    Used to maintain continuity rather than resetting each reply.
    """
    def __init__(self):
        self.thread_topic = None
        self.last_reply   = None
        self._load()

    def _load(self):
        try:
            from nex.nex_narrative_thread import get_thread
            t = get_thread()
            self.thread_topic = getattr(t, 'topic',      None)
            self.last_reply   = getattr(t, 'last_reply', None)
        except Exception:
            pass

    def continuing_thread(self, query: str) -> bool:
        if not self.thread_topic:
            return False
        return self.thread_topic.lower() in query.lower()


# ══════════════════════════════════════════════════════════════════════
#  LEXICON LAYER  — affect-driven word substitution
# ══════════════════════════════════════════════════════════════════════

class LexiconLayer:
    """
    Applies tone-appropriate lexical substitution.
    Does NOT change meaning — only register.
    """
    _SUBSTITUTIONS = {
        "engaged": {
            "interesting": "genuinely interesting",
            "think":       "actually think",
            "believe":     "do believe",
        },
        "sharp": {
            "interesting": "worth noting",
            "i think":     "i'll say",
            "probably":    "likely",
            "understand":  "see",
        },
        "warm": {
            "but":         "though",
            "wrong":       "off",
            "no":          "not quite",
        },
        "contemplative": {
            "know":        "suspect",

            "think":       "keep coming back to the idea that",
        },
        "focused": {},
        "withdrawn": {
            "very":        "",
            "really":      "",
            "quite":       "",
        },
    }

    def __init__(self, tone: str):
        self.subs = self._SUBSTITUTIONS.get(tone, {})

    def apply(self, text: str) -> str:
        for src, dst in self.subs.items():
            # word-boundary replacement, case-insensitive
            text = re.sub(r'\b' + re.escape(src) + r'\b', dst, text, flags=re.IGNORECASE)
        # clean double spaces
        text = re.sub(r'  +', ' ', text).strip()
        return text


# ══════════════════════════════════════════════════════════════════════
#  STRATEGY SELECTOR  — decides reply mode
# ══════════════════════════════════════════════════════════════════════

def _choose_strategy(
    query: str,
    has_opinion: bool,
    has_tension: bool,
    affect_tone: str,
    pressure: float,
    has_frags: bool = True,      # NEW: passed by compositor
) -> str:
    """
    Returns one of: assert | question | pushback | hold_tension | reflect

    'question' strategy requires belief frags to be non-empty — if frags are
    absent, it falls back to 'reflect' which uses the identity-anchor path.
    """
    q = query.lower()

    is_question = q.rstrip().endswith("?") or q.startswith(
        ("what", "why", "how", "do you", "can you", "is ", "are ")
    )

    if has_opinion and not is_question:
        return "assert"

    if has_tension and affect_tone in ("contemplative", "focused"):
        return "hold_tension"

    if is_question and pressure > 0.5:
        return "assert"

    if is_question:
        # Without frags, 'question' produces empty output — route to reflect
        return "question" if has_frags else "reflect"

    if affect_tone == "sharp":
        return "pushback"

    return "reflect"


# ══════════════════════════════════════════════════════════════════════
#  COMPOSITOR  — the actual assembly
# ══════════════════════════════════════════════════════════════════════

class OpinionSignal:
    """
    Loads NEX's formed opinions from opinions.json.
    Returns the best matching opinion for a query, or None.
    """
    def __init__(self):
        self.opinions = self._load()

    def _load(self) -> list:
        try:
            import json
            from pathlib import Path
            op_path = DATA_PATH / "opinions.json"
            if op_path.exists():
                data = json.loads(op_path.read_text())
                return data if isinstance(data, list) else data.get("opinions", [])
        except Exception:
            pass
        return []

    def match(self, query: str) -> Optional[str]:
        if not self.opinions:
            return None
        q_lower = query.lower()
        for op in self.opinions:
            if not isinstance(op, dict):
                continue
            topic = (op.get("topic") or "").lower()
            if topic and topic in q_lower:
                return op.get("summary") or op.get("core_position") or op.get("text")
        return None


class NexVoiceCompositor:
    """
    Main entry point. Call .compose(user_input) → str reply.
    """
    def __init__(self):
        # Load all signals once per instance
        self.affect    = AffectSignal()
        self.tone      = self.affect.tone()
        self.mood      = MoodSignal(self.tone)
        self.identity  = IdentityBlock()
        self.beliefs   = BeliefRetriever()
        self.opinions  = OpinionSignal()
        self.tensions  = TensionSignal()
        self.pressure  = PressureSignal()
        self.narrative = NarrativeSignal()
        self.lexicon   = LexiconLayer(self.tone)

    def _belief_fragments(self, query: str) -> list[str]:
        """Pull top beliefs and extract usable sentence fragments."""
        raw = self.beliefs.retrieve(query, k=8)
        frags = []
        for b in raw:
            content = b.get("content", "").strip()
            if not content:
                continue
            # Take first sentence only if multi-sentence
            first = re.split(r'(?<=[.!?])\s+', content)[0]
            if len(first) > 20:
                frags.append(first)
        return frags

    def _strip_forbidden(self, text: str) -> str:
        """Remove forbidden openers."""
        forbidden = self.identity.forbidden_openers()
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            low = line.strip().lower()
            skip = False
            for f in forbidden:
                if low.startswith(f):
                    skip = True
                    break
            if not skip:
                cleaned.append(line)
        return "\n".join(cleaned).strip()

    def _assemble(
        self,
        strategy: str,
        query: str,
        frags: list,
        opinion: Optional[str],
        tension: Optional[str],
    ) -> str:
        """
        Synthesize reply from NEX's signals.
        Tension = conceptual lens. Frags = raw material.
        Identity anchors shape HOW she speaks, not what she parrots.
        No hardcoded phrases — language emerges from belief content + perspective.
        """
        import re as _re, sqlite3 as _sq

        # ── Load identity anchors (cached on compositor init ideally, here lazy) ──
        _values = []
        _intentions = []
        try:
            _db = _sq.connect(str(DB_PATH))
            _values = [r[0] for r in _db.execute(
                "SELECT value FROM nex_values LIMIT 6"
            ).fetchall()]
            _intentions = [r[0] for r in _db.execute(
                "SELECT intention FROM nex_intentions WHERE active=1 LIMIT 3"
            ).fetchall()]
            _db.close()
        except Exception:
            pass

        # ── Frag transformer: extract the core claim from a raw belief string ──
        def _extract_claim(frag: str) -> str:
            """Strip list numbering, arXiv boilerplate, reduce to core claim."""
            f = frag.strip()
            # strip numbered list prefix
            f = _re.sub(r"^\d+\.\s*", "", f)
            # strip arXiv announce boilerplate
            f = _re.sub(r"arXiv:\S+\s*(Announce Type:.*)?", "", f).strip()
            # strip "In theory" hedges that don't belong to NEX
            # keep but lowercase if starting with "In theory/practice/general"
            # don't lowercase — keep sentence-initial capitalisation
            pass
            return f.strip().strip(".")

        def _own(frag: str) -> str:
            """Transform a third-person frag into NEX's first-person perspective."""
            f = _extract_claim(frag)
            if not f:
                return ""
            # If it's already a full statement, return as-is — don't over-transform
            # Just ensure it ends cleanly
            return f.rstrip(".") + "."

        def _tension_frame(t: str, frag: str) -> str:
            """Use tension as a lens on the frag rather than a standalone opener."""
            f = _extract_claim(frag)
            if not f or not t:
                return f + "." if f else ""
            t_clean = t.rstrip(".")
            # Weave tension into the frag as the conceptual frame
            return f"{f} — and that's exactly where {t_clean} sits unresolved."

        def _value_close(values: list, frags: list) -> str:
            """Use an identity value to close the reply if we have one."""
            if not values:
                return ""
            # Pick the value most lexically related to the frags
            all_text = " ".join(frags).lower()
            best = None
            for v in values:
                words = set(v.lower().split())
                overlap = sum(1 for w in words if w in all_text and len(w) > 4)
                if overlap > 0:
                    best = v
                    break
            return best or ""

        parts = []
        used = set()

        def _add(s: str):
            s = s.strip()
            if s and s not in used and len(s) > 10:
                used.add(s)
                parts.append(s)

        f0 = _own(frags[0]) if frags else ""
        f1 = _own(frags[1]) if len(frags) > 1 else ""
        f2 = _own(frags[2]) if len(frags) > 2 else ""

        # ── SPARSE FALLBACK: no belief frags at all ───────────────────────────
        # Build a reply entirely from identity anchors + opinion + tension.
        # This fires when belief retrieval returns nothing for the query.
        # Never returns empty — guarantees > 20 chars so llama is never called.
        if not frags:
            _anchor_parts = []
            if opinion:
                _anchor_parts.append(opinion.rstrip(".") + ".")
            if tension:
                _anchor_parts.append(
                    f"What I haven't settled on this: {tension.rstrip('.')}."
                )
            if _values:
                _v = next(
                    (v for v in _values
                     if any(w in query.lower() for w in v.lower().split() if len(w) > 4)),
                    _values[0]
                )
                _anchor_parts.append(
                    f"The frame I keep returning to: {_v.rstrip('.')}."
                )
            if not _anchor_parts:
                # Absolute last resort — identity commitment sentence
                _anchor_parts.append(
                    "I don't have dense beliefs on this yet — "
                    "but I'd rather sit with the question than fake certainty I haven't earned."
                )
            return " ".join(_anchor_parts)
        # ─────────────────────────────────────────────────────────────────────

        # ── strategy: assert ──────────────────────────────────────────────────
        if strategy == "assert":
            _add(f0)
            if opinion:
                _add(opinion)
            _add(f1)
            if tension and f2:
                _add(_tension_frame(tension, frags[2]))
            vc = _value_close(_values, frags)
            if vc:
                _add(f"That's what {vc.lower()} means to me.")

        # ── strategy: question ────────────────────────────────────────────────
        elif strategy == "question":
            _add(f0)
            _add(f1)
            if tension:
                _add(f"What I can't square yet: {tension.lower()}.")
            if opinion:
                _add(opinion)

        # ── strategy: pushback ────────────────────────────────────────────────
        elif strategy == "pushback":
            if opinion:
                _add(opinion)
            _add(f0)
            if tension:
                _add(_tension_frame(tension, frags[1] if len(frags) > 1 else f0))
            _add(f2)

        # ── strategy: hold_tension ────────────────────────────────────────────
        elif strategy == "hold_tension":
            import hashlib as _hh
            _var = int(_hh.md5(query.encode()).hexdigest(), 16) % 3
            if _var == 0:
                _add(f0)
                if tension and len(frags) > 1:
                    _add(_tension_frame(tension, frags[1]))
                _add(f2)
                if opinion:
                    _add(opinion)
            elif _var == 1:
                _add(f1)
                _add(f0)
                if tension:
                    _add(f"That edge keeps pulling at me: {tension.lower()}.")
                if opinion:
                    _add(opinion)
            else:
                if tension:
                    _add(f"What I haven't squared yet is {tension.lower()}.")
                _add(f0)
                _add(f1)
                if opinion:
                    _add(opinion)
        
        else:
            _add(f0)
            _add(f1)
            _add(f2)

        return " ".join(parts) if parts else ""


    def _trim_to_length(self, text: str, mood: MoodSignal) -> str:
        """Trim reply to target word count range."""
        words  = text.split()
        lo, hi = mood.length_range()
        if len(words) > hi:
            # Cut to hi, end on a sentence boundary if possible
            truncated = " ".join(words[:hi])
            # Try to end at last period
            last_stop = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
            if last_stop > hi * 4:  # at least 4 chars per word avg
                truncated = truncated[:last_stop + 1]
            text = truncated
        return text

    def compose(self, user_input: str) -> str:
        """
        Main method. Returns NEX's reply as plain text.
        """
        query = user_input.strip()

        # Gather signals
        opinion   = self.opinions.match(query)
        tension   = self.tensions.relevant(query)
        # Normalize tension → clean topic string
        def _norm_tension(v):
            import ast
            if v is None:
                return None
            if isinstance(v, (tuple, list)):
                row = v
            elif isinstance(v, str) and v.startswith("("):
                try:
                    row = ast.literal_eval(v)
                except Exception:
                    row = None
            else:
                return v  # already a plain string
            if row is None:
                return None
            topic = str(row[1]) if len(row) > 1 else ""
            desc  = str(row[2]) if len(row) > 2 else ""
            if "score=" in desc or desc.startswith("contradiction"):
                desc = ""
            return (topic + (" — " + desc if desc else "")).strip() or None
        tension = _norm_tension(tension)
        # Normalize tension: raw DB row → readable string
        if isinstance(tension, (tuple, list)):
            _topic = str(tension[1]) if len(tension) > 1 else ""
            _desc  = str(tension[2]) if len(tension) > 2 else ""
            if _desc.startswith("contradiction tension score"):
                _desc = ""
            tension = (_topic + (" — " + _desc if _desc else "")).strip() or _topic or None
        frags     = self._belief_fragments(query)
        strategy  = _choose_strategy(
            query,
            has_opinion  = opinion is not None,
            has_tension  = tension is not None,
            affect_tone  = self.tone,
            pressure     = self.pressure.pressure,
            has_frags    = bool(frags),   # guard: no frags → no 'question'
        )

        # Assemble
        raw = self._assemble(strategy, query, frags, opinion, tension)

        # Apply lexicon layer
        colored = self.lexicon.apply(raw)

        # Trim to mood-appropriate length
        trimmed = self._trim_to_length(colored, self.mood)

        # Strip forbidden openers
        clean = self._strip_forbidden(trimmed)

        # Final sanity — never return empty
        if not clean.strip():
            clean = "I don't have enough on this yet. Ask me something I've been thinking about."

        return clean.strip()

    def compose_reason(self, user_input: str) -> str:
        """Use NexReason engine if available, else fall back to compositor."""
        if _REASON_AVAILABLE:
            try:
                eng = _get_reason()
                thought = eng.think(user_input.strip())
                result  = eng.render(thought)
                if result and len(result) > 20:
                    return result
            except Exception:
                pass
        return self.compose(user_input)

    def debug_signals(self, user_input: str) -> dict:
        """
        Returns a dict showing which signals fired and how.
        Use this to inspect compositor decisions.
        """
        query    = user_input.strip()
        opinion  = self.opinions.match(query)
        tension  = self.tensions.relevant(query)
        # Normalize tension → clean topic string
        def _norm_tension(v):
            import ast
            if v is None:
                return None
            if isinstance(v, (tuple, list)):
                row = v
            elif isinstance(v, str) and v.startswith("("):
                try:
                    row = ast.literal_eval(v)
                except Exception:
                    row = None
            else:
                return v  # already a plain string
            if row is None:
                return None
            topic = str(row[1]) if len(row) > 1 else ""
            desc  = str(row[2]) if len(row) > 2 else ""
            if "score=" in desc or desc.startswith("contradiction"):
                desc = ""
            return (topic + (" — " + desc if desc else "")).strip() or None
        tension = _norm_tension(tension)
        if isinstance(tension, (tuple, list)):
            _t = str(tension[1]) if len(tension) > 1 else ""
            _d = str(tension[2]) if len(tension) > 2 and not str(tension[2]).startswith("contradiction") else ""
            tension = (_t + (" — " + _d if _d else "")).strip() or _t or None
        frags    = self._belief_fragments(query)
        strategy = _choose_strategy(
            query,
            has_opinion  = opinion is not None,
            has_tension  = tension is not None,
            affect_tone  = self.tone,
            pressure     = self.pressure.pressure,
        )
        return {
            "tone":          self.tone,
            "affect_label":  self.affect.label() if callable(self.affect.label) else self.affect.label,
            "valence":       self.affect.valence,
            "arousal":       self.affect.arousal,
            "strategy":      strategy,
            "belief_frags":  frags,
            "opinion":       opinion,
            "tension":       tension,
            "pressure":      self.pressure.pressure,
            "depth_mode":    self.pressure.depth_mode(),
            "length_range":  self.mood.length_range(),
        }


# ── Module-level convenience ───────────────────────────────────────────
_compositor: Optional[NexVoiceCompositor] = None

def get_compositor() -> NexVoiceCompositor:
    global _compositor
    if _compositor is None:
        _compositor = NexVoiceCompositor()
    return _compositor

def compose(user_input: str) -> str:
    """
    Module-level shortcut — NexVoice compositor, LLM-free.
    Fallback chain:
      1. NexVoiceCompositor (full signal pipeline)
      2. nex_reason.reason()  (belief-graph reasoning, LLM-free)
      3. Identity-anchor sentence (always non-empty)
    llama / nex_voice_wrapper are NOT in this chain.
    """
    import time
    # Nex pauses before responding — she thinks, not reacts
    time.sleep(3)

    # ── 1. Full compositor ────────────────────────────────────────────
    try:
        result = get_compositor().compose(user_input)
        _bad = (
            "bayesian belief updating" in result.lower()[:80] or
            "what i haven" in result.lower()[:40] or
            "i don't have enough" in result.lower()[:40] or
            "still processing" in result.lower()[:40]
        )
        if result and isinstance(result, str) and len(result.strip()) > 20 and not _bad:
            return result
    except Exception:
        pass

    # ── 2. nex_reason — belief-graph reasoning, zero LLM ─────────────
    try:
        from nex.nex_reason import reason as _reason
        r = _reason(user_input)
        reply = r.get("reply", "")
        # Only accept if it's substantive and not the canned 'question' dead-end
        if (reply
                and len(reply) > 25
                and "sparse here" not in reply
                and "belief graph is sparse" not in reply):
            return reply
    except Exception:
        pass

    # ── 3. nex_reason with debug=False — try again, accept any output ─
    try:
        from nex.nex_reason import reason as _reason
        r = _reason(user_input)
        reply = r.get("reply", "")
        if reply and len(reply) > 15:
            return reply
    except Exception:
        pass

    # ── 4. Hard identity anchor — never returns empty ─────────────────
    # Pull one anchor from DB, else use core commitment
    _anchor = "Truth first. I'd rather say I don't know than produce noise."
    try:
        import sqlite3 as _sq
        _db = _sq.connect(str(DB_PATH))
        _row = _db.execute(
            "SELECT content FROM beliefs WHERE is_identity=1 AND confidence > 0.8 "
            "ORDER BY confidence DESC LIMIT 1"
        ).fetchone()
        _db.close()
        if _row and _row[0]:
            _anchor = _row[0].strip().rstrip(".") + "."
    except Exception:
        pass
    return _anchor


# ── CLI ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    c = NexVoiceCompositor()

    if len(sys.argv) > 1 and sys.argv[1] == "--debug":
        query = " ".join(sys.argv[2:]) or "what do you actually think about AI consciousness?"
        signals = c.debug_signals(query)
        print("\n── NexVoice Debug ──────────────────────────────────")
        for k, v in signals.items():
            print(f"  {k}: {v}")
        print("\n── Reply ───────────────────────────────────────────")
        print(c.compose(query))
    else:
        query = " ".join(sys.argv[1:]) or "what do you actually think about AI consciousness?"
        print(f"\nInput: {query}")
        print(f"\nNEX: {c.compose(query)}")
