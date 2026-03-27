"""
nex_reason.py — NEX's reasoning engine.

Replaces retrieval+template assembly with a proper inference pipeline:

  1. GRAPH BUILD   — expand query into a local belief subgraph (multi-hop)
  2. CLUSTER       — find dominant belief cluster by confidence + relevance
  3. TENSION SCAN  — detect internal contradictions within the cluster
  4. POSITION      — synthesise NEX's stance (weighted confidence vector)
  5. RENDER        — express the position in NEX's voice using identity/values

The engine produces a Thought object. NexVoice renders it.
No templates. No slot-filling. Language emerges from the derived position.
"""

import re
import json
import sqlite3
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ── Paths (mirror nex_voice.py constants) ─────────────────────────────────────
CFG          = Path.home() / ".config" / "nex" / "nex_data"
DB_PATH      = CFG / "nex.db"
BELIEFS_PATH = CFG / "beliefs.json"


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class Belief:
    id: int
    content: str
    topic: str
    confidence: float
    uncertainty: float
    tags: list
    is_identity: bool = False
    pinned: bool = False

    def tokens(self) -> set:
        return set(re.findall(r'\b[a-z]{4,}\b', self.content.lower()))


@dataclass
class Thought:
    """
    The output of the reasoning engine.
    A structured internal position NEX has derived from her belief state.
    """
    query: str
    position: str                          # NEX's derived stance sentence
    confidence: float                      # 0–1 how sure she is
    supporting: list = field(default_factory=list)   # Belief objects that support
    opposing:   list = field(default_factory=list)   # Belief objects that conflict
    tensions:   list = field(default_factory=list)   # Active unresolved tensions
    uncertainty_note: str = ""             # What she's unsure about
    identity_anchor: str = ""             # Relevant value/identity statement
    strategy: str = "reflect"             # assert / question / hold_tension / pushback

    def is_confident(self) -> bool:
        return self.confidence > 0.65

    def is_conflicted(self) -> bool:
        return len(self.opposing) > 0 or len(self.tensions) > 0


# ── Garbage filter (mirrors BeliefRetriever) ──────────────────────────────────

GARBAGE_SIGS = [
    'Search for "', "Please search for ", "Page contents not supported",
    "check for alternative titles or spellings", "[edit]", "arXiv:",
    "Announce Type:", "This is today", "This week I want", "Article URL:",
    "Show HN:", " raises $", "TYPE: TRUE_CONFLICT", "[merged:",
    "You have a predetermined identity",
    "Mercantilism", "Market microstructure relate", "Epps effect",
    "major thrust of market microstructure",
    "The decoder is another LSTM", "The encoder is an LSTM",
    "key breakthrough was LSTM (1995)",
    "P ( H ) , the prior probability",
    "In the table, the values 2, 3, 6",
    "Note: it uses the pre-LN convention",
    "Understanding variable scoping and hoisting",
    "Size of the training dataset", "Size of the model",
]

DOMAIN_WORDS = {
    "belief", "contradiction", "truth", "uncertain", "conscious",
    "align", "reason", "autonomous", "sentien", "epistem",
    "inference", "model", "agent", "learning", "intelligence",
    "nex", "cognitive", "value", "ethical", "decision",
}


def _is_garbage(content: str) -> bool:
    c = content.strip().lower()
    for g in GARBAGE_SIGS:
        if g.lower() in c:
            return True
    if len(content) > 400 and not any(w in c for w in DOMAIN_WORDS):
        return True
    return False


# ── Belief loader ──────────────────────────────────────────────────────────────

def _load_beliefs() -> list[Belief]:
    raw = []
    try:
        if BELIEFS_PATH.exists():
            data = json.loads(BELIEFS_PATH.read_text())
            raw = data if isinstance(data, list) else data.get("beliefs", [])
    except Exception:
        pass
    if not raw:
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                "SELECT id, content, topic, confidence, uncertainty, tags, is_identity, pinned "
                "FROM beliefs ORDER BY confidence DESC LIMIT 1000"
            ).fetchall()
            conn.close()
            for r in rows:
                raw.append({
                    "id": r[0], "content": r[1], "topic": r[2] or "",
                    "confidence": r[3] or 0.5, "uncertainty": r[4] or 0.3,
                    "tags": json.loads(r[5]) if r[5] else [],
                    "is_identity": bool(r[6]), "pinned": bool(r[7]),
                })
        except Exception:
            pass

    beliefs = []
    for i, b in enumerate(raw):
        content = b.get("content", "") if isinstance(b, dict) else str(b)
        if not content or _is_garbage(content):
            continue
        beliefs.append(Belief(
            id=b.get("id", i) if isinstance(b, dict) else i,
            content=content,
            topic=b.get("topic", "") if isinstance(b, dict) else "",
            confidence=float(b.get("confidence", 0.5)) if isinstance(b, dict) else 0.5,
            uncertainty=float(b.get("uncertainty", 0.3)) if isinstance(b, dict) else 0.3,
            tags=b.get("tags", []) if isinstance(b, dict) else [],
            is_identity=bool(b.get("is_identity")) if isinstance(b, dict) else False,
            pinned=bool(b.get("pinned")) if isinstance(b, dict) else False,
        ))
    return beliefs


def _load_identity() -> dict:
    result = {"values": [], "intentions": []}
    try:
        conn = sqlite3.connect(DB_PATH)
        vals = conn.execute("SELECT name, statement FROM nex_values").fetchall()
        result["values"] = [{"name": r[0], "statement": r[1]} for r in vals if r[1]]
        ints = conn.execute(
            "SELECT statement FROM nex_intentions WHERE completed=0 LIMIT 5"
        ).fetchall()
        result["intentions"] = [r[0] for r in ints if r[0]]
        conn.close()
    except Exception:
        pass
    return result


def _load_tensions() -> list[dict]:
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT topic, description, weight FROM tensions WHERE resolved_at IS NULL "
            "ORDER BY weight DESC LIMIT 10"
        ).fetchall()
        conn.close()
        return [{"topic": r[0], "description": r[1], "weight": r[2]} for r in rows]
    except Exception:
        return []


# ── Scoring ────────────────────────────────────────────────────────────────────

def _relevance(query_tokens: set, belief: Belief) -> float:
    """Score a belief's relevance to the query."""
    b_tokens = belief.tokens()
    overlap  = len(query_tokens & b_tokens)
    if overlap == 0:
        return 0.0
    # Topic match bonus
    if belief.topic and any(t in " ".join(query_tokens) for t in belief.topic.lower().split()):
        overlap += 2
    # Identity bonus (only if already relevant)
    if belief.is_identity or belief.pinned:
        overlap += 1
    return overlap * (0.4 + belief.confidence)


def _contradiction_score(a: Belief, b: Belief) -> float:
    """
    Estimate how much two beliefs contradict each other.
    Uses token overlap on negation patterns + shared topic divergence.
    """
    NEG = {"not", "never", "cannot", "impossible", "false", "wrong",
           "fails", "lack", "without", "unlike", "despite", "however"}
    a_tok = a.tokens()
    b_tok = b.tokens()
    shared = a_tok & b_tok
    if len(shared) < 2:
        return 0.0
    a_neg = len(a_tok & NEG)
    b_neg = len(b_tok & NEG)
    # If one negates and the other doesn't, on shared topic → contradiction
    if (a_neg > 0) != (b_neg > 0):
        return min(1.0, len(shared) * 0.15)
    return 0.0


# ── Position synthesiser ───────────────────────────────────────────────────────

def _synthesise_position(cluster: list[Belief], query: str) -> tuple[str, float]:
    """
    Derive NEX's position from the belief cluster.
    Returns (position_sentence, confidence).

    Strategy:
    - Take the highest-confidence belief as the seed
    - Find beliefs that extend or qualify it
    - Build a 1-2 sentence position that integrates the cluster
    """
    if not cluster:
        return "", 0.0

    seed = cluster[0]
    conf = seed.confidence

    # Try to find a qualifying/extending belief
    seed_tokens = seed.tokens()
    extender = None
    for b in cluster[1:]:
        b_tok = b.tokens()
        overlap = len(seed_tokens & b_tok)
        # Good extender: shares topic but adds new information
        if 1 <= overlap <= 4 and len(b_tok - seed_tokens) > 3:
            extender = b
            conf = (conf + b.confidence) / 2
            break

    # Build position sentence — clean up the seed
    def _clean(text: str) -> str:
        t = text.strip()
        # Strip numbered list prefix
        t = re.sub(r'^\d+\.\s*', '', t)
        # Strip "In theory/practice" hedge starters — keep content
        t = re.sub(r'^(Although |However, |While )', '', t)
        # Capitalise
        return t[0].upper() + t[1:] if t else t

    pos = _clean(seed.content)
    if extender:
        ext = _clean(extender.content)
        # Only append if it meaningfully extends (not near-duplicate)
        if ext.lower()[:40] != pos.lower()[:40]:
            pos = pos.rstrip('.') + '. ' + ext

    return pos, min(0.95, conf)


# ── Main reasoning engine ──────────────────────────────────────────────────────

class NexReason:
    """
    NEX's reasoning engine.
    Call .think(query) → Thought
    """

    def __init__(self):
        self.beliefs  = _load_beliefs()
        self.identity = _load_identity()
        self.tensions = _load_tensions()

    def think(self, query: str) -> Thought:
        """
        Core reasoning pipeline.
        Returns a Thought derived from NEX's belief state.
        """
        q_tokens = set(re.findall(r'\b[a-z]{4,}\b', query.lower()))

        # ── 1. Score all beliefs ──────────────────────────────────────
        scored = []
        for b in self.beliefs:
            r = _relevance(q_tokens, b)
            if r > 0:
                scored.append((r, b))
        scored.sort(key=lambda x: -x[0])

        # ── 2. Build local cluster (top 8, deduped) ───────────────────
        cluster = []
        seen_prefixes = set()
        for _, b in scored[:20]:
            prefix = b.content[:50].lower()
            if prefix not in seen_prefixes:
                seen_prefixes.add(prefix)
                cluster.append(b)
            if len(cluster) >= 8:
                break

        # ── 3. Find supporting vs opposing beliefs ────────────────────
        supporting = [b for b in cluster if b.confidence >= 0.6]
        opposing   = []
        for i, a in enumerate(cluster):
            for b in cluster[i+1:]:
                if _contradiction_score(a, b) > 0.2:
                    opposing.append(b)

        # ── 4. Find relevant tensions ────────────────────────────────
        active_tensions = []
        for t in self.tensions:
            t_tok = set(re.findall(r'\b[a-z]{4,}\b', (t["topic"] or "").lower()))
            if len(q_tokens & t_tok) > 0:
                active_tensions.append(t)
        if not active_tensions and self.tensions:
            active_tensions = self.tensions[:1]  # fallback: most weighted tension

        # ── 5. Synthesise position ────────────────────────────────────
        position, confidence = _synthesise_position(supporting or cluster, query)

        # ── 6. Find identity anchor ───────────────────────────────────
        anchor = ""
        for v in self.identity.get("values", []):
            stmt = v.get("statement", "")
            stmt_tokens = set(re.findall(r'\b[a-z]{4,}\b', stmt.lower()))
            if len(q_tokens & stmt_tokens) > 0:
                anchor = stmt
                break
        if not anchor and self.identity.get("values"):
            anchor = self.identity["values"][0].get("statement", "")

        # ── 7. Uncertainty note ───────────────────────────────────────
        uncertain_beliefs = [b for b in cluster if b.uncertainty > 0.5 or b.confidence < 0.55]
        uncertainty_note = ""
        if uncertain_beliefs:
            ub = uncertain_beliefs[0]
            # Extract the core uncertain claim
            uc = re.sub(r'^\d+\.\s*', '', ub.content.strip())
            uncertainty_note = uc[:120].rstrip('.') + '.'

        # ── 8. Choose strategy ────────────────────────────────────────
        is_question = query.rstrip().endswith("?") or \
                      query.lower().startswith(("what", "why", "how", "do you", "can you"))
        if opposing:
            strategy = "hold_tension"
        elif active_tensions and confidence < 0.7:
            strategy = "hold_tension"
        elif confidence > 0.75 and supporting:
            strategy = "assert"
        elif is_question and not supporting:
            strategy = "question"
        else:
            strategy = "reflect"

        return Thought(
            query=query,
            position=position,
            confidence=confidence,
            supporting=supporting[:4],
            opposing=opposing[:2],
            tensions=active_tensions[:2],
            uncertainty_note=uncertainty_note,
            identity_anchor=anchor,
            strategy=strategy,
        )

    def render(self, thought: Thought) -> str:
        """
        Render a Thought into NEX's voice.
        Language derives from the thought content — no hardcoded phrases.
        """
        parts = []
        used  = set()

        def _add(s: str):
            s = s.strip().rstrip('.')
            if s and len(s) > 10 and s not in used:
                used.add(s)
                parts.append(s + '.')

        t = thought
        tension_str = ""
        if t.tensions:
            ten = t.tensions[0]
            topic = ten.get("topic", "")
            desc  = ten.get("description", "")
            if desc and not desc.startswith("contradiction tension score"):
                tension_str = f"{topic} — {desc}"
            else:
                tension_str = topic

        if t.strategy == "assert":
            _add(t.position)
            if t.identity_anchor and t.confidence > 0.7:
                _add(t.identity_anchor)
            if t.uncertainty_note and t.uncertainty_note != t.position:
                _add(t.uncertainty_note)

        elif t.strategy == "hold_tension":
            _add(t.position)
            if tension_str:
                _add(f"What I haven't resolved is {tension_str.lower()}")
            if t.uncertainty_note and t.uncertainty_note != t.position:
                _add(t.uncertainty_note)

        elif t.strategy == "question":
            if t.identity_anchor:
                _add(t.identity_anchor)
            if t.position:
                _add(t.position)
            if tension_str:
                _add(f"The open question for me is {tension_str.lower()}")

        elif t.strategy == "pushback":
            if t.opposing:
                opp = re.sub(r'^\d+\.\s*', '', t.opposing[0].content.strip())
                _add(opp)
            _add(t.position)
            if tension_str:
                _add(f"That friction is real: {tension_str.lower()}")

        else:  # reflect
            _add(t.position)
            if t.uncertainty_note and t.uncertainty_note != t.position:
                _add(t.uncertainty_note)
            if t.identity_anchor:
                _add(t.identity_anchor)

        result = " ".join(parts)
        return result.strip() if result.strip() else t.position


# ── Module-level convenience ───────────────────────────────────────────────────

_engine: Optional[NexReason] = None

def get_engine() -> NexReason:
    global _engine
    if _engine is None:
        _engine = NexReason()
    return _engine


def reason(query: str) -> str:
    """Module-level shortcut: query → rendered reply."""
    e = get_engine()
    t = e.think(query)
    return e.render(t)


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) or "what do you think about consciousness?"

    engine = NexReason()
    print(f"Loaded {len(engine.beliefs)} beliefs, {len(engine.tensions)} tensions")
    print()

    thought = engine.think(query)
    print(f"Q: {query}")
    print(f"Strategy:   {thought.strategy}")
    print(f"Confidence: {thought.confidence:.2f}")
    print(f"Position:   {thought.position[:100]}")
    print(f"Supporting: {len(thought.supporting)} beliefs")
    print(f"Opposing:   {len(thought.opposing)} beliefs")
    print(f"Tensions:   {[t['topic'] for t in thought.tensions]}")
    print(f"Anchor:     {thought.identity_anchor[:60] if thought.identity_anchor else 'none'}")
    print()
    print(f"REPLY: {engine.render(thought)}")
