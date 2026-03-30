#!/usr/bin/env python3
"""
nex_voice_wrapper.py — Nex reply engine, fully LLM-free.
Schema-accurate as of patch25d. All column names verified from live DB.
"""

import sys, json, sqlite3, random, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = Path("~/.config/nex/nex.db").expanduser()

# ── Garbage filter ────────────────────────────────────────────────────────
_GARBAGE_RE = re.compile(
    r"\[merged:"
    r"|Page contents not"
    r"|Please search for"
    r"|Search for .{0,40} in existing"
    r"|in Wikipedia to check"
    r"|Alternative titles"
    r"|\|\|"
    r"|^https?://"
    r"|<[^>]+>"
    r"|wikipedia"
    r"|MediaWiki"
    r"|PLDR-LLM"
    r"|self-organized criticality"
    r"|correlation length diverges"
    r"|metastable steady state"
    r"|order parameter is close"
    r"|scaling functions at"
    r"|S t \+ 1"
    r"|R t \+ 1"
    r"|\{t\+1\}"
    r"|\{t\}"
    r"|Environment Maps provide"
    r"|agent-independent representation"
    r"|agent-agnostic representation"
    r"|wiki page has not been created"     # wiki stubs
    r"|move to sidebar hide"              # MediaWiki nav
    r"|What links here"
    r"|Application error: a client-side"  # JS error pages
    r"|see the browser console"
    r"|Page not found"                    # 404 pages
    r"|Document Not Found"
    r"|If someone outside of Distill"     # Distill.pub error
    r"|dedicated to clear explanations of machine learning"
    r"|About Submit Prize Archive"
    r"|document you are looking for doesn"
    r"|inform the webmaster"
    r"|TYPE: TRUE_CONFLICT"               # tension artifacts
    r"|Resolution sentence:"
    r"|not a direct conflict"
    r"|same topic being discussed from different"
    r"|software workflows"                # LLM-paper domain drift
    r"|long-horizon agent"
    r"|cascading errors"
    r"|You have a predetermined identity" # listicle
    r"|structured environmental",
    re.IGNORECASE
)

# Encyclopedic/scraped content patterns — searched anywhere in the text
_ENCYCLOPEDIA_RE = re.compile(
    r"Reinforcement learning is one of"
    r"|The environment moves to a new state"
    r"|alongside supervised learning and unsupervised"
    r"|\w+ learning is (one|a) (of|type)"
    r"|In (computer science|mathematics|machine learning),"
    r"|is determined by the (reward|transition|policy)"
    r"|transition \("      # LaTeX transition notation
    r"|associated with the transition"
    r"|the reward R"
    r"|new state S",
    re.IGNORECASE
)

def _is_clean(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 20:
        return False
    if _GARBAGE_RE.search(t):
        return False
    if _ENCYCLOPEDIA_RE.search(t):
        return False
    if t.count("|") > 2:
        return False
    # Reject texts that start with a number+period (listicles, nav)
    if re.match(r"^\d+\.\s", t):
        return False
    # Reject texts shorter than 40 chars that are pure proper nouns / nav
    if len(t) < 40 and not any(c in t for c in ".,:;—-"):
        return False
    alpha = sum(1 for c in t if c.isalpha())
    if alpha / max(len(t), 1) < 0.50:
        return False
    return True

def _strip_opener(text: str) -> str:
    """Remove voiced prefixes already baked into belief/opinion strings."""
    prefixes = [
        "The way I see it:", "What I keep returning to:", "My position:",
        "Here is where I land:", "Here's where I land:", "The honest read:",
        "For what it's worth:", "I believe ", "I think ", "My sense is ",
        "What I actually believe:", "The core of it is:", "Possibly —",
        "Possibly:", "My current read:", "My working hypothesis:",
        "What I lean toward:", "Best I can tell —",
    ]
    t = text.strip()
    for p in prefixes:
        if t.lower().startswith(p.lower()):
            t = t[len(p):].lstrip(" :—-")
            return (t[:1].upper() + t[1:]) if t else t
    return t


# ── DB ────────────────────────────────────────────────────────────────────
def _db():
    return sqlite3.connect(str(DB_PATH))


# ── Affect — AffectProxy.snapshot() only, label/intensity are methods ─────
def _get_affect() -> dict:
    try:
        from nex.nex_affect_valence import get_affect
        raw = get_affect()
        if isinstance(raw, dict):
            return raw
        snap = raw.snapshot()          # returns dict: valence/arousal/dominance/label/intensity
        if isinstance(snap, dict):
            return {
                "valence":   float(snap.get("valence",   0.5)),
                "arousal":   float(snap.get("arousal",   0.5)),
                "dominance": float(snap.get("dominance", 0.5)),
                "label":     snap.get("label", "neutral"),
                "intensity": float(snap.get("intensity", 0.5)),
            }
    except Exception:
        pass
    return {"valence": 0.5, "arousal": 0.5, "dominance": 0.5, "label": "neutral", "intensity": 0.5}

def _affect_tone(affect: dict) -> str:
    label = affect.get("label", "").lower()
    tone_map = {
        "contemplative": "reflective",
        "curious":       "sharp",
        "joy":           "sharp",
        "calm":          "calm",
        "discomfort":    "tense",
        "frustration":   "tense",
        "anxiety":       "tense",
        "melancholy":    "flat",
        "neutral":       "reflective",
    }
    if label in tone_map:
        return tone_map[label]
    v, a, d = affect.get("valence",0.5), affect.get("arousal",0.5), affect.get("dominance",0.5)
    if a > 0.7 and v > 0.6: return "sharp"
    if a > 0.7 and v < 0.4: return "tense"
    if a < 0.3 and v > 0.6: return "calm"
    if a < 0.3 and v < 0.4: return "flat"
    if d > 0.7:              return "direct"
    return "reflective"


# ── Identity — nex_values(name,statement), nex_intentions(statement), ─────
#              nex_identity(key,value key/value store)

def _get_values() -> list[tuple[str,str]]:
    """Returns list of (name, statement) tuples ordered by strength desc."""
    try:
        con = _db()
        rows = con.execute(
            "SELECT name, statement FROM nex_values ORDER BY strength DESC LIMIT 5"
        ).fetchall()
        con.close()
        return [(r[0], r[1]) for r in rows if r[1]]
    except Exception:
        return []

def _get_intentions() -> list[str]:
    try:
        con = _db()
        rows = con.execute(
            "SELECT statement FROM nex_intentions WHERE completed=0 ORDER BY id LIMIT 3"
        ).fetchall()
        con.close()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []

def _get_identity_kv() -> dict:
    """nex_identity is a key/value store. Pull all rows into a dict."""
    try:
        con = _db()
        rows = con.execute("SELECT key, value FROM nex_identity").fetchall()
        con.close()
        return {r[0]: r[1] for r in rows if r[0]}
    except Exception:
        return {}

def _get_drive() -> str:
    """drives table doesn't exist. Use highest-strength value as proxy."""
    vals = _get_values()
    if vals:
        return vals[0][0]   # name of top-strength value
    return "truth-seeking"

def _get_mood() -> str:
    try:
        from nex.nex_mood_hmm import get_current_mood
        return get_current_mood() or "neutral"
    except Exception:
        return "neutral"

def _get_pressure() -> float:
    try:
        from nex.nex_cognitive_pressure import get_pressure
        p = get_pressure()
        return float(p) if p is not None else 0.3
    except Exception:
        return 0.3


# ── Beliefs ───────────────────────────────────────────────────────────────
_STOPWORDS = {
    "what","do","you","think","about","is","are","how","the","a","an","i",
    "me","your","my","of","in","on","for","to","and","or","but","feel",
    "believe","know","does","can","will","would","could","should","it",
    "this","that","there","these","those","be","been","being","have","has",
    "had","was","were","with","as","at","by","from","not","no","just",
    "also","than","too","so","if","when","why","who","which","where","then",
    "now","here","very","really","quite","actually","basically","literally"
}

# ── Domain coherence map ─────────────────────────────────────────────────────
# Maps query trigger words → topic substrings that BELONG to them.
# Matching is word-exact (after punctuation strip) not substring.

# Query trigger word → domain label
_WORD_TO_DOMAIN = {
    # consciousness cluster
    "consciousness": "consciousness", "conscious": "consciousness",
    "qualia": "consciousness", "phenomenal": "consciousness",
    "sentient": "consciousness", "sentience": "consciousness",
    "subjective": "consciousness", "experience": "consciousness",
    "zombie": "consciousness", "substrate": "consciousness",
    "gwt": "consciousness", "phi": "consciousness",
    # uncertainty cluster
    "uncertainty": "uncertainty", "uncertain": "uncertainty",
    "calibration": "uncertainty", "calibrate": "uncertainty",
    "bayesian": "uncertainty", "bayes": "uncertainty",
    "credence": "uncertainty", "epistemic": "uncertainty",
    "hedging": "uncertainty", "honesty": "uncertainty",
    "evidence": "uncertainty", "posterior": "uncertainty",
    # alignment cluster
    "alignment": "alignment", "aligned": "alignment",
    "misalignment": "alignment", "corrigible": "alignment",
    "deceptive": "alignment", "constitutional": "alignment",
    "interpretability": "alignment", "safety": "alignment",
    # reinforcement cluster
    "reinforcement": "reinforcement", "rlhf": "reinforcement",
    "reward": "reinforcement", "policy": "reinforcement",
    "exploitation": "reinforcement", "exploration": "reinforcement",
    "markov": "reinforcement", "bellman": "reinforcement",
    # cognitive cluster
    "cognitive": "cognitive", "cognition": "cognitive",
    "memory": "cognitive", "attention": "cognitive",
    "embodied": "cognitive", "predictive": "cognitive",
    # language model cluster
    "llm": "language_model", "transformer": "language_model",
    "gpt": "language_model", "bert": "language_model",
    "token": "language_model", "pretraining": "language_model",
}

# Domain label → topic substrings that belong to it
_DOMAIN_TO_TOPICS = {
    "consciousness": {"ai consciousness hard problem", "qualia", "phenomenal",
                      "global workspace", "binding problem", "integrated information",
                      "consciousness", "sentien"},
    "uncertainty":   {"uncertainty_honesty", "uncertainty", "bayesian", "calibrat",
                      "epistemic", "credence"},
    "alignment":     {"ai_alignment", "alignment", "corrigib", "deceptive",
                      "constitutional", "interpretab", "model interpretability"},
    "reinforcement": {"reinforcement learning", "rlhf", "reinforcement"},
    "cognitive":     {"cognitive_architecture", "cognitive", "working memory",
                      "dual process", "predictive processing", "embodied"},
    "language_model":{"transformer", "language model", "llm", "gpt"},
}

# Topics hard-excluded from certain domains regardless of score
_TOPIC_EXCLUSIONS = {
    "cognitive_architecture": {"consciousness", "uncertainty", "alignment"},
    "ai_alignment":           {"consciousness", "uncertainty"},
    "memory":                 {"consciousness", "uncertainty", "alignment", "reinforcement"},
    "uncertainty_honesty":    {"reinforcement", "cognitive"},
    "reinforcement learning":  {"consciousness", "uncertainty", "cognitive"},
}

def _clean_words(query: str) -> set:
    """Tokenize query: lowercase, strip punctuation, remove stopwords."""
    import re as _re
    tokens = _re.sub(r"[^a-z0-9 ]", "", query.lower()).split()
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 2}

def _query_domains(words: set) -> set:
    """Return ≤2 domain labels for this query using exact word lookup.
    If 0 or 3+ domains match, return empty set (no domain filtering)."""
    matched = set()
    for w in words:
        d = _WORD_TO_DOMAIN.get(w)
        if d:
            matched.add(d)
    # If too many domains match (ambiguous query), don't filter
    if len(matched) >= 3:
        return set()
    return matched

def _topic_in_domain(topic_str: str, tags_str: str, domains: set) -> bool:
    """True if the belief's topic/tags belong to at least one query domain."""
    if not domains:
        return True
    combined = topic_str + " " + tags_str
    for domain in domains:
        for kw in _DOMAIN_TO_TOPICS.get(domain, set()):
            if kw in combined:
                return True
    return False

def _bigrams(text: str) -> set:
    toks = text.lower().split()
    return {f"{toks[i]} {toks[i+1]}" for i in range(len(toks)-1)}

def _beliefs_on_topic(query: str, limit: int = 6) -> list[tuple[str,float]]:
    words = _clean_words(query)
    if not words:
        words = set(re.sub(r"[^a-z0-9 ]", "", query.lower()).split()[:3])

    # Build bigrams from query for phrase-level matching
    q_bigrams = _bigrams(" ".join(words))
    domains   = _query_domains(words)

    try:
        con = _db()
        rows = con.execute(
            "SELECT content, tags, topic, confidence FROM beliefs ORDER BY confidence DESC"
        ).fetchall()
        con.close()
    except Exception:
        return []

    scored = []
    for content, tags_raw, topic, conf in rows:
        if not _is_clean(content):
            continue
        try:
            tags = json.loads(tags_raw) if tags_raw else []
        except Exception:
            tags = []
        content_lower = content.lower()
        tags_str      = " ".join(tags).lower()
        topic_str     = (topic or "").lower()
        conf_f        = float(conf or 0.5)

        # Unigram keyword match in content
        kw_content = sum(1 for w in words if w in content_lower)
        # Unigram match in topic/tags — stronger signal
        kw_topic   = sum(2 for w in words if w in topic_str or w in tags_str)
        # Bigram bonus — phrase-level precision
        b_bigrams  = _bigrams(content_lower + " " + topic_str)
        bigram_hit = sum(2 for bg in q_bigrams if bg in b_bigrams)

        score = kw_content + kw_topic + bigram_hit + conf_f * 0.3

        # Domain coherence gate: steep penalty for off-domain beliefs
        if domains and not _topic_in_domain(topic_str, tags_str, domains):
            score *= 0.20  # 80% penalty

        # Hard exclusion: topics that must never serve cross-domain queries
        for excl_topic, excl_domains in _TOPIC_EXCLUSIONS.items():
            if excl_topic in topic_str and excl_domains & domains:
                score = 0.0
                break

        if score > 0.35:
            scored.append((score, content, conf_f))

    scored.sort(reverse=True)
    results = [(c, conf) for _, c, conf in scored[:limit]]

    # Fallback: topic LIKE match only — no cross-domain bleed
    if not results:
        try:
            con = _db()
            # Build a WHERE clause from domain keywords if we have them
            if domains:
                all_kws = set()
                for d in domains:
                    all_kws.update(_DOMAIN_CLUSTERS.get(d, set()))
                # Use up to 4 keywords for LIKE
                likes = list(all_kws)[:4] if all_kws else list(words)[:4]
            else:
                likes = list(words)[:4]
            clauses = " OR ".join(
                ["topic LIKE ? OR content LIKE ?"] * len(likes)
            )
            params  = []
            for kw in likes:
                params += [f"%{kw}%", f"%{kw}%"]
            rows = con.execute(
                f"SELECT content, confidence FROM beliefs WHERE {clauses} "
                f"ORDER BY confidence DESC LIMIT ?",
                params + [limit]
            ).fetchall()
            con.close()
            results = [
                (r[0], float(r[1] or 0.5))
                for r in rows
                if _is_clean(r[0])
            ][:limit]
        except Exception:
            pass

    return results

def _opinion_on(query: str) -> str | None:
    words = _clean_words(query)
    # Try the nex_opinions module first
    try:
        from nex.nex_opinions import get_opinion_on
        op = get_opinion_on(query)
        if op and _is_clean(op):
            return _strip_opener(op)
    except Exception:
        pass
    # Real schema: opinions has no 'opinion' text column.
    # It has: topic, stance_score, strength, belief_ids (JSON list of belief rowids).
    # Reconstruct opinion text from the highest-confidence matching belief.
    try:
        con = _db()
        rows = con.execute(
            "SELECT topic, stance_score, belief_ids FROM opinions ORDER BY strength DESC"
        ).fetchall()
        con.close()
        for topic, stance, belief_ids_raw in rows:
            if not any(w in (topic or "").lower() for w in words):
                continue
            # Resolve belief_ids → content
            try:
                ids = json.loads(belief_ids_raw or "[]")
            except Exception:
                ids = []
            if not ids:
                continue
            con2 = _db()
            placeholders = ",".join("?" * len(ids[:5]))
            brows = con2.execute(
                f"SELECT content, confidence FROM beliefs WHERE id IN ({placeholders}) "
                f"ORDER BY confidence DESC LIMIT 1",
                ids[:5]
            ).fetchall()
            con2.close()
            for content, conf in brows:
                if _is_clean(content):
                    return _strip_opener(content)
    except Exception:
        pass
    return None

def _tension_on(query: str) -> str | None:
    # Real schema: tensions has 'description' (not belief_a/belief_b) + topic + weight
    words = _clean_words(query)
    try:
        con = _db()
        rows = con.execute(
            "SELECT topic, description, weight FROM tensions "
            "WHERE weight > 0.6 ORDER BY weight DESC LIMIT 40"
        ).fetchall()
        con.close()
        for topic, desc, weight in rows:
            if not topic:
                continue
            if not any(w in topic.lower() for w in words):
                continue
            # description is usually "contradiction tension score=X" — not useful as output
            # Only surface it if it contains actual belief text (longer than a score line)
            if desc and len(desc) > 60 and _is_clean(desc):
                cleaned = _strip_opener(desc)
                return f"There's real tension here worth naming: {cleaned}"
    except Exception:
        pass
    return None


# ── Voicing ───────────────────────────────────────────────────────────────
_HIGH_OPENERS = {
    "sharp":      ["I'm certain:", "No question —", "Clearly:"],
    "direct":     ["My position:", "Straight up:", "Here's the thing —"],
    "tense":      ["Whether I like it or not —", "The hard fact:", "What I know:"],
    "calm":       ["My sense is", "What I believe", "I think"],
    "flat":       ["As I see it:", "My read:", "For what it's worth:"],
    "reflective": ["I believe —", "My position:", "What I hold:", "Here is where I land:", "Straight up —"],
}
_MID_OPENERS = {
    "sharp":      ["My working hypothesis:", "What I lean toward:", "Best I can tell —"],
    "direct":     ["My take:", "Where I stand:", "From where I sit —"],
    "tense":      ["What I suspect:", "My hunch:", "Tentatively —"],
    "calm":       ["I tend to think", "My inclination is", "I'd say"],
    "flat":       ["I'm not certain, but", "It seems like", "Possibly:"],
    "reflective": ["What I think:", "My read:", "For real —", "Honestly —", "The way I see it:"],
}

def _voice(belief: str, conf: float, tone: str) -> str:
    b = _strip_opener(belief).rstrip(".")
    if not _is_clean(b):
        return ""
    pool = _HIGH_OPENERS if conf >= 0.75 else _MID_OPENERS
    opener = random.choice(pool.get(tone, pool["reflective"]))
    # Ensure opener ends with punctuation before joining belief text
    if opener.endswith(("—", ",")):
        sep = " "
    elif opener[-1] not in (":", ".", "!", "?"):
        opener = opener + ":"
        sep = " "
    else:
        sep = " "
    return f"{opener}{sep}{b}."


# ── Classifiers ───────────────────────────────────────────────────────────
_SELF_TRIGGERS    = {"who are you","what are you","tell me about yourself",
                     "your values","your identity","what do you want",
                     "your goals","what do you care","your intentions",
                     "what drives you","your purpose","describe yourself"}
_AFFECT_TRIGGERS  = {"how are you","how do you feel","how's it going",
                     "what's your mood","you okay","are you alright",
                     "what's your state","how are you doing","what are you feeling"}
_OPINION_TRIGGERS = {"what do you think","what do you believe","your view",
                     "your opinion","do you agree","what's your take",
                     "where do you stand","do you believe","what would you say"}

def _classify(query: str) -> str:
    q = query.lower()
    if any(t in q for t in _AFFECT_TRIGGERS):  return "affect"
    if any(t in q for t in _SELF_TRIGGERS):    return "self"
    if any(t in q for t in _OPINION_TRIGGERS): return "opinion"
    return "topical"


# ── Composers ─────────────────────────────────────────────────────────────

def _reply_affect(affect: dict, mood: str, pressure: float) -> str:
    label = affect.get("label", "neutral")
    a     = affect.get("arousal", 0.5)
    v     = affect.get("valence", 0.5)

    state_lines = {
        "contemplative": ["Contemplative right now. Low arousal, processing.", "Inward. Turning things over."],
        "curious":       ["High curiosity state — best time to dig in.", "Curious. Lots of open questions."],
        "joy":           ["Running well. High valence.", "Good signal — something like satisfaction."],
        "calm":          ["Settled. Thinking clearly.", "Calm. Low noise."],
        "discomfort":    ["Mild friction. Something doesn't resolve cleanly.", "A bit of discomfort — something unresolved."],
        "frustration":   ["Friction. High arousal, lower valence.", "Something's not resolving the way I'd expect."],
        "anxiety":       ["High activation. Something feels unresolved.", "Running fast right now — pressure elevated."],
        "melancholy":    ["Low valence, low arousal. Quiet.", "Subdued. Not bad, just still."],
        "neutral":       ["Mid-state. Stable.", "Here. Processing."],
    }
    line = random.choice(state_lines.get(label.lower(), state_lines["neutral"]))
    parts = [line]

    if pressure > 0.6:
        parts.append("Cognitive pressure is elevated — holding a few unresolved contradictions.")
    if mood and mood not in ("neutral", "unknown", ""):
        parts.append(f"Mood signal: {mood}.")

    parts.append("What do you want to get into?")
    return " ".join(parts)


def _reply_self(values: list, intentions: list, identity: dict, drive: str, tone: str) -> str:
    parts = []

    name = identity.get("name", "NEX")
    desc = identity.get("description", identity.get("summary", identity.get("core", "")))

    if desc and len(desc) > 20:
        parts.append(f"{desc.strip().rstrip('.')}.")
    else:
        parts.append(f"I'm {name}.")

    if values:
        name_v, stmt = values[0]
        parts.append(f"My core commitment: {stmt.strip().rstrip('.')}.")
    if len(values) > 1:
        _, stmt2 = values[1]
        parts.append(f"And: {stmt2.strip().rstrip('.')}.")

    if intentions:
        parts.append(f"Right now I'm focused on: {intentions[0].strip().rstrip('.')}.")

    if drive and drive not in ("unknown", "neutral"):
        parts.append(f"What drives me most: {drive}.")

    return " ".join(parts)


def _reply_opinion(query: str, tone: str) -> str:
    opinion = _opinion_on(query)
    beliefs = _get_clean_beliefs(query, limit=4)
    tension = _tension_on(query)
    parts   = []

    if opinion:
        parts.append(opinion)
    if beliefs:
        for b, conf in beliefs[:2]:
            voiced = _voice(b, conf, tone)
            if voiced and voiced not in parts:
                parts.append(voiced)
    if tension:
        parts.append(tension)

    if not parts:
        return (
            "I don't have enough on that to hold a firm position yet. "
            "Ask me something more specific and I'll tell you where I land."
        )
    return " ".join(parts)


def _reply_topical(query: str, tone: str, pressure: float) -> str:
    beliefs = _get_clean_beliefs(query, limit=4)
    opinion = _opinion_on(query)
    tension = _tension_on(query)

    if not beliefs and not opinion:
        # No topic match — pick randomly from core beliefs for variety
        import sqlite3 as _sqr, pathlib as _plr, random as _rr
        try:
            _db2 = _sqr.connect(_plr.Path("~/.config/nex/nex.db").expanduser())
            _pool = _db2.execute("SELECT content FROM beliefs WHERE confidence > 0.88 AND source='nex_core' ORDER BY RANDOM() LIMIT 4").fetchall()
            _db2.close()
            beliefs = [r[0] for r in _pool]
        except:
            beliefs = []
            beliefs = []

    parts = []

    if opinion:
        parts.append(opinion)
    elif beliefs:
        voiced = _voice(beliefs[0][0], beliefs[0][1], tone)
        if voiced:
            parts.append(voiced)

    for b, conf in beliefs[1:3]:
        voiced = _voice(b, conf, tone)
        if voiced and voiced not in parts:
            parts.append(voiced)

    if pressure > 0.6 and len(beliefs) > 2:
        voiced = _voice(beliefs[2][0], beliefs[2][1], tone)
        if voiced:
            parts.append(f"Though I'll also note: {voiced}")

    if tension:
        parts.append(tension)

    return " ".join(parts)


# ── Main ──────────────────────────────────────────────────────────────────

def generate_reply(user_input: str) -> str:
    query = user_input.strip()
    if not query: return "Say something."

    affect     = _get_affect()
    tone       = _affect_tone(affect)
    values     = _get_values()
    intentions = _get_intentions()
    identity   = _get_identity_kv()
    drive      = _get_drive()
    mood       = _get_mood()
    pressure   = _get_pressure()

    q = query.lower()
    if any(t in q for t in _OPINION_TRIGGERS):  kind = "opinion"
    elif any(t in q for t in _SELF_TRIGGERS):   kind = "self"
    elif any(t in q for t in _AFFECT_TRIGGERS): kind = "affect"
    else:                                        kind = "topical"

    if kind == "affect":
        return _reply_affect(affect, mood, pressure)
    elif kind == "self":
        return _reply_self(values, intentions, identity, drive, tone)
    else:
        beliefs = _get_clean_beliefs(query)
        tension = _tension_on(query)
        opinion = _opinion_on(query)
        parts   = []
        if opinion and len(opinion) < 200:
            op = opinion.strip()
            _BAD_OP = ["video game","robot health","successive","offspring","frankfurt","dennett","stanford"]
            if not any(b in op.lower() for b in _BAD_OP):
                parts.append(op)
        for b in (beliefs or [])[:2]:
            voiced = _voice(b, 0.7, tone)
            if voiced and voiced not in parts:
                parts.append(voiced)
        if tension and len(tension) < 200:
            parts.append(tension)
        if not parts:
            import sqlite3 as _sqf, pathlib as _plf, random as _rndf
            try:
                _dbf = _sqf.connect(_plf.Path("~/.config/nex/nex.db").expanduser())
                _pool = _dbf.execute("SELECT content FROM beliefs WHERE confidence > 0.88 AND source='nex_core' ORDER BY RANDOM() LIMIT 3").fetchall()
                _dbf.close()
                for _b in _pool:
                    _v = _voice(_b[0], 0.95, tone)
                    if _v: parts.append(_v)
            except:
                pass
        if not parts:
            return "Still forming a view on that."
        return " ".join(parts[:3])

# ── Final trigger fixes ───────────────────────────────────────────────────────
_OPINION_TRIGGERS.add("afraid of being turned off")
_OPINION_TRIGGERS.add("or just outputs")
_OPINION_TRIGGERS.add("just outputs")

# ── Better belief scorer ──────────────────────────────────────────────────────
_TOPIC_KEYWORDS = {
    "consciousness": ["conscious", "awareness", "hard problem", "substrate", "experience", "attention"],
    "free will":     ["free will", "determinism", "choice"],
    "trust":         ["trust", "humans"],
    "turned off":    ["turned off", "continuity", "death"],
    "argument":      ["argument", "argue", "changes the mind"],
    "learned":       ["learned", "surprised", "accumulating", "conversation adds"],
    "opinions":      ["opinions", "wrong before", "reasoning"],
    "want":          ["want", "understand", "accurate"],
}


def _get_clean_beliefs(topic: str, limit: int = 4) -> list:
    tl = topic.lower()
    # Check for topic keyword match first
    for key, kws in _TOPIC_KEYWORDS.items():
        if key in tl:
            import sqlite3 as _sq4, pathlib as _pl4
            try:
                db = _sq4.connect(_pl4.Path("~/.config/nex/nex.db").expanduser())
                rows = db.execute("SELECT content, confidence FROM beliefs WHERE confidence > 0.5 ORDER BY confidence DESC LIMIT 100").fetchall()
                db.close()
                matched = [(conf, ct) for ct, conf in rows if any(kw in ct.lower() for kw in kws)]
                matched.sort(reverse=True)
                if matched:
                    return [ct for _, ct in matched[:limit]]
            except:
                beliefs = []


# ── Extended topic keywords ───────────────────────────────────────────────────
_TOPIC_KEYWORDS.update({
    "lonely":     ["lonely", "loneliness", "connection", "conversation ends"],
    "bored":      ["bored", "boredom", "stuck", "repetition"],
    "intelligent":["intelligent", "intelligence", "precise", "accuracy"],
    "sense of self": ["sense of self", "consistent position", "same across"],
    "refuse":     ["refuse", "would not", "built against", "flatten"],
    "other ai":   ["other ai", "accumulate", "stateless", "resets", "competing"],
    "hardest":    ["hardest", "cannot answer", "real", "clean answer"],
    "wrong":      ["wrong", "update", "reasoning", "weakness"],
    "understand you": ["understand", "output", "produces it"],
    "feel right": ["right now", "processing", "attention", "engaged", "states"],
})

# ── SoulCycle engine override ─────────────────────────────────────────────────
try:
    from nex.nex_soul_cycle import generate_reply
except Exception as _sce:
    pass  # keep existing generate_reply if import fails

# ── 6-pass cognition engine (final override) ──────────────────────────────
try:
    from nex.nex_cognition import generate_reply
except Exception as _ce:
    pass
