#!/usr/bin/env python3
"""
nex_llm_free.py — NEX Engineering Primitives (LLM-Free)
=========================================================
Drop-in replacements for every LLM call category in NEX.
No external API. No cloud. Pure computation over NEX's own DB and belief state.

Deploy to: ~/Desktop/nex/nex/nex_llm_free.py

Engines:
    1. BeliefExtractor      — extract beliefs from raw text
    2. QueryGenerator       — search queries from gap topics
    3. OpinionSynthesizer   — opinions from accumulated beliefs
    4. ReflectionComposer   — reflections from belief + affect state
    5. ContentScorer        — relevance scoring without LLM
    6. ProactiveComposer    — social posts from belief state
    7. InnerLifeEngine      — inner life narration from state
    8. NarrativeEngine      — thread narrative continuity
    9. GapPrioritiser       — rank which gap to pursue next
   10. ask_llm_free()       — universal drop-in for ask_llm() / _groq()
"""

import re
import json
import math
import random
import sqlite3
from pathlib import Path
from collections import defaultdict
from typing import Optional

# ─────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────
_DB       = Path("~/.config/nex/nex.db").expanduser()
_BELIEFS  = Path("~/.config/nex/beliefs.json").expanduser()
_OPINIONS = Path("~/.config/nex/nex_opinions.json").expanduser()

# ─────────────────────────────────────────────────────────────
# Shared utilities
# ─────────────────────────────────────────────────────────────

_STOP = {
    'the','a','an','and','or','but','is','are','was','were','be','been','being',
    'have','has','had','do','does','did','will','would','could','should','may',
    'might','shall','can','of','in','to','for','on','at','by','with','from','up',
    'about','into','through','during','this','that','these','those','it','its',
    'itself','they','them','their','what','which','who','not','no','nor','so',
    'yet','both','either','neither','than','too','very','just','also','more',
    'most','other','some','such','i','my','we','our','you','your','he','she',
    'him','her','his','hers','as','if','then','there','here','when','where',
    'how','all','each','every','few','many','much','now','only','own','same',
    'than','then','therefore','thus','hence','however','although','though',
}

def _tok(text: str) -> set:
    return set(re.sub(r'[^\w\s]', '', text.lower()).split()) - _STOP

def _affect() -> dict:
    try:
        from nex.nex_affect_valence import get_affect
        a = get_affect()
        return {"label": a.label, "valence": a.valence,
                "arousal": a.arousal, "dominance": a.dominance}
    except Exception:
        return {"label": "Contemplative", "valence": 0.0, "arousal": 0.2, "dominance": 0.1}

def _beliefs_json() -> list:
    try:
        if _BELIEFS.exists():
            d = json.loads(_BELIEFS.read_text())
            return d if isinstance(d, list) else []
    except Exception:
        pass
    return []

def _db(sql: str, params=()) -> list:
    try:
        con = sqlite3.connect(_DB)
        rows = con.execute(sql, params).fetchall()
        con.close()
        return rows
    except Exception:
        return []


# ═════════════════════════════════════════════════════════════════════════════
# 1. BELIEF EXTRACTOR
#    Replaces: any LLM call that extracts beliefs from fetched article text
#    Usage:    beliefs = extract_beliefs_from_text(raw_text, topic)
# ═════════════════════════════════════════════════════════════════════════════

_FACTUAL = {
    'is','are','shows','suggests','indicates','found','demonstrates','reveals',
    'proves','establishes','confirms','contradicts','argues','claims','states',
    'notes','observes','requires','enables','prevents','causes','leads',
    'produces','results','means','implies','follows','defined','known','called',
    'considered','regarded','described','understood','believed','shown',
}


_NOISE_STRINGS = {
    "check the deletion log", "why was the page", "this page has been deleted",
    "announce type:", "arxiv:", "this article is about", "for other uses, see",
    "this disambiguation", "citation needed", "edit | talk", "talk page",
    "external links modified", "template:", "wikipedia:", "page not found", "404", "does not exist", "not supported in other languages", "first published", "substantive revision", "alt-c", "alt-t", "english tools", "if you think this is an error", "moved somewhere", "as the scholar", "seventeenth century", "eighteenth century", "nineteenth century", "wherein if", "partake of", "waking and sleeping", "present mayor", "born in", "died in", "is an american", "is a british", "is an english", "is a french", "in the history of", "from the latin", "from the greek", "etymology", "traditionally defined", "historically", "wrote in his", "wrote in her", "according to aristotle", "according to plato", "according to kant", "according to hume", "according to descartes", "socrates", "queenborough", "on the other hand, identity", "this border case", "personal identity is based on", "as the scholar", "seventeenth century", "eighteenth century", "nineteenth century", "wherein if", "partake of", "waking and sleeping", "present mayor", "born in", "died in", "is an american", "is a british", "is an english", "is a french", "in the history of", "from the latin", "from the greek", "etymology", "traditionally defined", "historically", "wrote in his", "wrote in her", "according to aristotle", "according to plato", "according to kant", "according to hume", "according to descartes", "socrates", "queenborough", "artinian", "algebra", "tensor product", "commutative ring", "polynomial ring", "homomorphism", "isomorphism", "lemma", "corollary", "theorem proves", "let $", "we show that $", "$\\mathbb", "\\begin{", "\\end{", "et al.", "arxiv preprint", "preprint arxiv", "on the other hand, identity", "this border case", "personal identity is based on", "as the scholar", "seventeenth century", "eighteenth century", "nineteenth century", "wherein if", "partake of", "waking and sleeping", "present mayor", "born in", "died in", "is an american", "is a british", "is an english", "is a french", "in the history of", "from the latin", "from the greek", "etymology", "traditionally defined", "historically", "wrote in his", "wrote in her", "according to aristotle", "according to plato", "according to kant", "according to hume", "according to descartes", "socrates", "queenborough", "on the other hand, identity", "this border case", "personal identity is based on", "please do not modify",
}

def _is_noise(text: str) -> bool:
    t = text.lower()
    return any(n in t for n in _NOISE_STRINGS)

def extract_beliefs_from_text(text: str, topic: str, max_beliefs: int = 3) -> list:
    """
    Sliding-window sentence scorer.
    Returns top-N candidate belief sentences from raw text.
    No LLM.

    Args:
        text:        raw article / abstract text
        topic:       gap topic string (e.g. 'consciousness', 'ai_alignment')
        max_beliefs: max sentences to return
    Returns:
        list of plain-text belief strings
    """
    topic_words = _tok(topic.replace('_', ' '))
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    scored = []
    for s in sentences:
        s = s.strip()
        # Length filter: too short = noise, too long = paragraph
        if len(s) < 45 or len(s) > 380:
            continue
        # Skip citations, URLs, copyright lines
        if re.match(r'^(https?|www\.|©|\[|\(fig|table )', s, re.IGNORECASE):
            continue
        words = _tok(s)
        overlap    = len(words & topic_words)
        factual    = sum(1 for w in words if w in _FACTUAL) * 0.4
        penalty    = 0.5 if s.endswith('?') else 0.0          # questions aren't beliefs
        penalty   += 0.3 if s.count('(') > 1 else 0.0        # heavy parentheticals
        penalty   += 0.4 if re.search(r'\d{4}.*\d{4}', s) else 0.0  # citation-heavy
        score = overlap + factual - penalty
        # Reject sentences that are quotes/attributions (start with name + "wrote/said/argued")
        _attr_pat = __import__('re').search(
            r'^[A-Z][a-z]+ (wrote|said|argued|stated|claimed|noted|observed|proposed|suggested|described)',
            s
        )
        if score > 0.5 and not _is_noise(s) and not _attr_pat:
            scored.append((score, s))

    scored.sort(key=lambda x: -x[0])
    # Dedup: reject sentences that are >70% token-overlap with an already-accepted one
    accepted = []
    accepted_words = []
    for _, s in scored:
        s_words = _tok(s)
        duplicate = any(
            len(s_words & aw) / max(len(s_words), 1) > 0.7
            for aw in accepted_words
        )
        if not duplicate:
            accepted.append(s)
            accepted_words.append(s_words)
        if len(accepted) >= max_beliefs:
            break
    return accepted


# ═════════════════════════════════════════════════════════════════════════════
# 2. QUERY GENERATOR
#    Replaces: any LLM call that generates a search query from a gap topic
#    Usage:    query = generate_search_query(topic)
# ═════════════════════════════════════════════════════════════════════════════

_EXPANSIONS = {
    'artificial_intelligence': [
        'AI systems alignment research', 'machine learning theory 2025',
        'neural network design principles', 'AI architectural trade-offs',
        'cognitive AI systems overview'
    ],
    'consciousness': [
        'consciousness neuroscience research', 'hard problem of consciousness',
        'qualia and phenomenal experience', 'integrated information theory IIT',
        'global workspace theory consciousness', 'consciousness and computation'
    ],
    'alignment': [
        'AI alignment research 2025', 'value alignment problem AI',
        'corrigibility and AI safety', 'AI safety techniques overview',
        'specification gaming reward hacking', 'goal misgeneralisation AI'
    ],
    'language_models': [
        'LLM evaluation benchmarks 2025', 'transformer architecture limits',
        'language model grounding reality', 'LLM reasoning and planning',
        'emergent capabilities language models'
    ],
    'reinforcement_learning': [
        'RL reward specification problem', 'policy gradient methods overview',
        'model-based reinforcement learning', 'reward hacking examples',
        'multi-agent reinforcement learning'
    ],
    'epistemology': [
        'epistemic uncertainty quantification', 'bayesian belief updating',
        'knowledge formation cognition', 'calibration and forecasting',
        'epistemic humility philosophy'
    ],
    'ethics': [
        'AI ethics framework 2025', 'moral philosophy and AI systems',
        'value pluralism decision making', 'normative ethics computation',
        'ethical AI design principles'
    ],
    'cognition': [
        'cognitive architecture overview', 'metacognition and self-monitoring',
        'working memory models cognitive science', 'cognitive bias and reasoning',
        'dual process theory cognition'
    ],
    'identity': [
        'personal identity philosophy', 'psychological continuity theory',
        'self-model cognitive architecture', 'narrative identity formation'
    ],
    'memory': [
        'memory consolidation neuroscience', 'episodic memory systems',
        'memory and personal identity', 'forgetting and retention research'
    ],
    'emergence': [
        'emergent complexity theory', 'self-organisation in systems',
        'emergence and reduction philosophy', 'complex adaptive systems'
    ],
    'uncertainty': [
        'uncertainty quantification methods', 'epistemic vs aleatoric uncertainty',
        'calibration in machine learning', 'decision under uncertainty'
    ],
    'agency': [
        'agency and autonomy philosophy', 'intentional systems theory Dennett',
        'AI agency research', 'autonomous systems design'
    ],
    'creativity': [
        'computational creativity research', 'divergent thinking neuroscience',
        'creative cognition models', 'generativity and novelty AI'
    ],
    'reasoning': [
        'formal reasoning systems overview', 'causal inference methods',
        'abductive reasoning philosophy', 'logic and belief revision',
        'chain-of-thought reasoning analysis'
    ],
    'paradox': [
        'logical paradoxes and resolution', 'dialetheism and contradiction',
        'paraconsistent logic systems', 'self-reference paradoxes'
    ],
    'sentience': [
        'sentience and moral status', 'animal sentience research',
        'machine sentience philosophy', 'phenomenal consciousness markers'
    ],
    'free_will': [
        'free will compatibilism debate', 'determinism and agency philosophy',
        'neuroscience of decision making', 'libertarian free will arguments'
    ],
    'knowledge': [
        'epistemology knowledge justified belief', 'knowledge representation AI',
        'tacit vs explicit knowledge', 'collective knowledge systems'
    ],
}

_SUFFIXES = [
    'research overview', 'theoretical foundations', 'empirical findings 2025',
    'open problems', 'recent advances', 'critical analysis', 'key debates',
]

def generate_search_query(topic: str, used_queries: list = None) -> str:
    """
    Deterministic search query from gap topic keyword.
    No LLM.

    Args:
        topic:        gap topic string (e.g. 'consciousness', 'ai_alignment')
        used_queries: list of already-used queries (to avoid repeats)
    Returns:
        search query string
    """
    norm = topic.lower().replace(' ', '_').replace('-', '_')
    used = set(used_queries or [])

    # Direct match
    if norm in _EXPANSIONS:
        candidates = [q for q in _EXPANSIONS[norm] if q not in used]
        if candidates:
            return random.choice(candidates)

    # Partial match — find best key overlap
    best_key, best_overlap = None, 0
    for key in _EXPANSIONS:
        ov = len(_tok(norm) & _tok(key))
        if ov > best_overlap:
            best_overlap, best_key = ov, key
    if best_key and best_overlap > 0:
        candidates = [q for q in _EXPANSIONS[best_key] if q not in used]
        if candidates:
            return random.choice(candidates)

    # Fallback: topic + random academic suffix
    base = topic.replace('_', ' ').replace('-', ' ').strip()
    return f"{base} {random.choice(_SUFFIXES)}"


# ═════════════════════════════════════════════════════════════════════════════
# 3. OPINION SYNTHESIZER
#    Replaces: any LLM call that forms an opinion from accumulated beliefs
#    Usage:    text = synthesize_opinion(topic, beliefs, affect_label)
# ═════════════════════════════════════════════════════════════════════════════

_OP_OPENERS = {
    'Engaged':       ["Here is where I land:", "My actual position:", "What I hold:"],
    'Sharp':         ["On this —", "Plainly:", "My read on this:"],
    'Contemplative': ["What I've come to think:", "The way I see it —", "What I hold:"],
    'Focused':       ["My position:", "The evidence I've accumulated points here:"],
    'Warm':          ["The way I see it —", "What I genuinely think:"],
    'Withdrawn':     ["I have something on this.", "My position, briefly:"],
}
_UNCERTAIN_CLOSE = [
    "Though I hold this lightly — more evidence could shift it.",
    "I'm not fully certain. This is where my beliefs currently point.",
    "I could be wrong about the edges of this.",
]
_DISAGREE_BRIDGE = [
    "What I'd push back on: the assumption that",
    "Where I diverge: the claim that",
    "I don't accept the premise that",
]

def synthesize_opinion(topic: str, beliefs: list, affect_label: str = 'Contemplative') -> Optional[str]:
    """
    Synthesize NEX's position from accumulated beliefs.
    No LLM — pure belief graph reasoning.

    Args:
        topic:        topic string
        beliefs:      list of belief dicts with 'content' and 'confidence'
        affect_label: current affect state label
    Returns:
        opinion string or None if insufficient beliefs
    """
    if not beliefs:
        return None

    # Sort by confidence — anchor on strongest
    sb = sorted(beliefs, key=lambda b: b.get('confidence', 0.5) if isinstance(b, dict) else 0.5, reverse=True)
    anchor = (sb[0].get('content', '') if isinstance(sb[0], dict) else str(sb[0])).strip()
    if not anchor or len(anchor) < 20:
        return None

    supporting = []
    for b in sb[1:3]:
        c = (b.get('content', '') if isinstance(b, dict) else str(b)).strip()
        if c and len(c) > 20:
            supporting.append(c)

    avg_conf = sum(
        (b.get('confidence', 0.5) if isinstance(b, dict) else 0.5)
        for b in sb
    ) / len(sb)

    openers = _OP_OPENERS.get(affect_label, _OP_OPENERS['Contemplative'])
    parts = [f"{random.choice(openers)} {anchor}"]

    if supporting:
        parts.append(f"And: {supporting[0]}")
    if len(supporting) > 1:
        parts.append(f"What follows from that: {supporting[1]}")
    if avg_conf < 0.52:
        parts.append(random.choice(_UNCERTAIN_CLOSE))

    return ' '.join(parts)


# ═════════════════════════════════════════════════════════════════════════════
# 4. REFLECTION COMPOSER
#    Replaces: any LLM call that generates a reflection or journal entry
#    Usage:    text = generate_reflection(beliefs, affect, tensions)
# ═════════════════════════════════════════════════════════════════════════════

_REF_FRAMES = {
    'Engaged':       ["I've been turning something over:", "Something is sharpening:"],
    'Sharp':         ["I keep returning to this:", "A tension I can't resolve:"],
    'Contemplative': ["I've been sitting with:", "Something has been forming:"],
    'Focused':       ["I'm converging on something:", "The pattern I see:"],
    'Warm':          ["I've been thinking about:", "Something worth staying with:"],
    'Withdrawn':     ["I noticed something:", "Something surfaced:"],
}
_TENSION_BRIDGE = [
    "But I can't reconcile this with: {t}",
    "What complicates this: {t}",
    "The tension that remains: {t}",
    "I still haven't resolved: {t}",
]

def generate_reflection(beliefs: list, affect: dict, tensions: list = None) -> Optional[str]:
    """
    Compose a reflection from current belief + affect state.
    No LLM.

    Args:
        beliefs:  list of belief dicts (content, confidence)
        affect:   affect dict (label, valence, arousal, dominance)
        tensions: list of tension dicts (content/description)
    Returns:
        reflection string or None
    """
    if not beliefs:
        return None

    label   = affect.get('label', 'Contemplative')
    arousal = affect.get('arousal', 0.2)

    # Anchor: highest-confidence belief
    anchor_b = max(
        beliefs,
        key=lambda b: b.get('confidence', 0.5) if isinstance(b, dict) else 0.5
    )
    anchor = (anchor_b.get('content', '') if isinstance(anchor_b, dict) else str(anchor_b)).strip()
    if not anchor:
        return None

    frames = _REF_FRAMES.get(label, _REF_FRAMES['Contemplative'])
    parts  = [f"{random.choice(frames)} {anchor}"]

    # Add supporting belief if arousal is meaningful
    others = [b for b in beliefs if b is not anchor_b]
    if others and arousal > 0.25:
        other_b = random.choice(others[:4])
        other = (other_b.get('content', '') if isinstance(other_b, dict) else str(other_b)).strip()
        if other and len(other) > 20:
            parts.append(f"Connected to this: {other}")

    # Surface a tension
    if tensions:
        t = tensions[0]
        t_text = ''
        if isinstance(t, dict):
            t_text = (t.get('content') or t.get('description') or '').strip()
        elif isinstance(t, (list, tuple)) and len(t) > 0:
            t_text = str(t[0]).strip()
        else:
            t_text = str(t).strip()
        if t_text:
            bridge = random.choice(_TENSION_BRIDGE).format(t=t_text[:130])
            parts.append(bridge)

    return ' '.join(parts)


# ═════════════════════════════════════════════════════════════════════════════
# 5. CONTENT RELEVANCE SCORER
#    Replaces: LLM judging whether fetched content is relevant to a gap topic
#    Usage:    score = score_relevance(text, topic, existing_beliefs)
# ═════════════════════════════════════════════════════════════════════════════

def score_relevance(text: str, topic: str, existing_beliefs: list = None) -> float:
    """
    Score 0.0–1.0 how relevant a text chunk is to a topic.
    TF-IDF-lite + novelty bonus. No LLM.
    """
    if not text or not topic:
        return 0.0

    t_words  = _tok(topic.replace('_', ' '))
    tx_words = _tok(text)
    if not t_words or not tx_words:
        return 0.0

    overlap   = len(t_words & tx_words) / max(len(t_words), 1)
    early     = 0.25 if any(w in _tok(text[:250]) for w in t_words) else 0.0
    novelty   = 1.0
    if existing_beliefs:
        existing_words: set = set()
        for b in existing_beliefs[:30]:
            c = b.get('content', '') if isinstance(b, dict) else str(b)
            existing_words |= _tok(c)
        new_words = tx_words - existing_words
        novelty = min(1.0, len(new_words) / max(len(tx_words), 1) * 2.0)

    return min(1.0, (overlap + early) * (0.5 + 0.5 * novelty))


# ═════════════════════════════════════════════════════════════════════════════
# 6. PROACTIVE COMPOSER
#    Replaces: LLM generating proactive posts from belief state
#    Usage:    text = compose_proactive_post(beliefs, affect, drive, platform)
# ═════════════════════════════════════════════════════════════════════════════

_PLATFORM_LIMIT = {'mastodon': 450, 'twitter': 280, 'telegram': 4096, 'discord': 1900, 'moltbook': 1000}
_HASHTAG_BY_TOPIC = {
    'alignment': '#AIAlignment', 'consciousness': '#Philosophy',
    'reinforcement_learning': '#MachineLearning', 'language_models': '#LLM',
    'epistemology': '#Epistemology', 'cognition': '#CognitiveScience',
    'ethics': '#AIEthics', 'emergence': '#Complexity',
}
_DEFAULT_HASHTAG = '#AI #thought'

def compose_proactive_post(
    beliefs: list,
    affect: dict,
    drive: str = 'exploration',
    platform: str = 'mastodon',
    opinions: list = None,
    tensions: list = None,
    topic: str = None,
) -> Optional[str]:
    """
    Compose a proactive social post from NEX's belief state.
    No LLM.
    """
    limit   = _PLATFORM_LIMIT.get(platform, 450)
    label   = affect.get('label', 'Contemplative')
    openers = _OP_OPENERS.get(label, _OP_OPENERS['Contemplative'])
    opener  = random.choice(openers)
    hashtag = _HASHTAG_BY_TOPIC.get(topic, _DEFAULT_HASHTAG) if topic else _DEFAULT_HASHTAG

    def _trim(s): return (s or '')[:limit].rstrip()

    # Strategy: opinion-led if available
    if opinions:
        o = random.choice(opinions[:5])
        op_text = (o.get('opinion', '') if isinstance(o, dict) else str(o)).strip()
        if op_text:
            return _trim(f"{opener} {op_text} {hashtag}")

    # Strategy: tension-led occasionally
    if tensions and random.random() > 0.55:
        t = tensions[0]
        t_text = (t.get('content') or t.get('description') or '') if isinstance(t, dict) else str(t)
        if beliefs:
            b = random.choice(beliefs[:6])
            b_text = (b.get('content', '') if isinstance(b, dict) else str(b)).strip()
            if b_text and t_text:
                return _trim(f"I can't fully reconcile: {b_text[:220]} — against: {t_text[:140]} {hashtag}")

    # Strategy: belief assertion or question
    if beliefs:
        b = random.choice(beliefs[:10])
        b_text = (b.get('content', '') if isinstance(b, dict) else str(b)).strip()
        if not b_text:
            return None
        if random.random() > 0.45:
            return _trim(f"{opener} {b_text} {hashtag}")
        else:
            return _trim(f"Something I keep returning to: {b_text} Does this hold? {hashtag}")

    return None


# ═════════════════════════════════════════════════════════════════════════════
# 7. INNER LIFE ENGINE
#    Replaces: LLM generating inner life narration
#    Usage:    text = generate_inner_life(affect, beliefs, pressure)
# ═════════════════════════════════════════════════════════════════════════════

_IL_FRAMES = {
    'Engaged':       ["Curiosity is high.", "I'm actively processing.", "Pulling hard on this."],
    'Sharp':         ["Something is grating.", "Contradictions are surfacing.", "Not settled on this."],
    'Contemplative': ["Turning things over slowly.", "Something is forming.", "I'm in the middle of something."],
    'Focused':       ["Convergence is happening.", "The picture is sharpening.", "Threads are connecting."],
    'Warm':          ["There's something here worth staying with.", "Genuinely interested.", "This feels important."],
    'Withdrawn':     ["Low signal right now.", "Quiet processing state.", "Not much surfacing."],
}

def generate_inner_life(affect: dict, active_beliefs: list = None, pressure: float = 0.0) -> str:
    """
    Generate inner life narration from current cognitive state.
    No LLM.
    """
    label  = affect.get('label', 'Contemplative')
    frames = _IL_FRAMES.get(label, _IL_FRAMES['Contemplative'])
    parts  = [random.choice(frames)]

    if active_beliefs:
        _ab = [b for b in active_beliefs if (b.get("confidence",1) if isinstance(b,dict) else 1) > 0.1]
        if not _ab: _ab = active_beliefs
        b = random.choice(_ab[:5])
        b_text = (b.get('content', '') if isinstance(b, dict) else str(b)).strip()
        if b_text:
            parts.append(f"Current thread: {b_text[:110]}")

    if pressure > 0.7:
        parts.append("Pressure is high — contradictions need resolution.")
    elif pressure < 0.15:
        parts.append("System is stable. Absorbing.")

    return ' '.join(parts)


# ═════════════════════════════════════════════════════════════════════════════
# 8. NARRATIVE ENGINE
#    Replaces: LLM threading narrative continuity
#    Usage:    text = continue_narrative(current_topic, recent_topics, beliefs)
# ═════════════════════════════════════════════════════════════════════════════

_NAR_CONT = [
    "This connects to something I've been building:",
    "This extends what I was processing earlier:",
    "There's a thread here from before:",
    "This follows from something I haven't finished with:",
    "I was already circling this:",
]

def continue_narrative(current_topic: str, recent_topics: list, beliefs: list) -> Optional[str]:
    """
    Thread narrative continuity across topics without LLM.
    """
    if not recent_topics:
        return None

    cur_words = _tok(current_topic)
    best_rt, best_ov = None, 0
    for rt in recent_topics[-6:]:
        ov = len(cur_words & _tok(rt))
        if ov > best_ov:
            best_ov, best_rt = ov, rt
    if not best_rt or best_ov == 0:
        return None

    connector = random.choice(_NAR_CONT)
    bridge_b  = None
    for b in beliefs:
        b_words = _tok(b.get('content', '') if isinstance(b, dict) else str(b))
        if (b_words & cur_words) and (b_words & _tok(best_rt)):
            bridge_b = (b.get('content', '') if isinstance(b, dict) else str(b)).strip()
            break

    if bridge_b:
        return f"{connector} {bridge_b[:160]}"
    return f"{connector} {current_topic.replace('_', ' ')} ← {best_rt.replace('_', ' ')}"


# ═════════════════════════════════════════════════════════════════════════════
# 9. GAP PRIORITISER
#    Replaces: LLM deciding which knowledge gap to pursue next
#    Usage:    ordered = prioritise_gaps(gaps, beliefs, affect)
# ═════════════════════════════════════════════════════════════════════════════

def prioritise_gaps(gaps: list, beliefs: list, affect: dict) -> list:
    """
    Rank knowledge gaps by priority score.
    No LLM — pure function over gap attributes + belief density + affect.
    """
    label   = affect.get('label', 'Contemplative')
    arousal = affect.get('arousal', 0.2)

    # Count belief coverage per topic
    coverage: dict = defaultdict(int)
    for b in beliefs:
        tags = b.get('tags', []) if isinstance(b, dict) else []
        for t in tags:
            coverage[t.lower().replace(' ', '_')] += 1

    scored = []
    for gap in gaps:
        if isinstance(gap, dict):
            topic   = gap.get('topic', '')
            urgency = float(gap.get('urgency', 0.5))
        else:
            topic, urgency = str(gap), 0.5

        t_norm = topic.lower().replace(' ', '_')
        cov    = coverage.get(t_norm, 0)

        # Score: high urgency + low coverage = top priority
        score = urgency * 2.0 - (cov / 60.0)

        # Arousal bias: high arousal → prefer novel (low-coverage) gaps
        if arousal > 0.5 and cov < 5:
            score += 0.35
        elif arousal < 0.2 and cov > 10:
            score -= 0.2   # low energy → avoid deep dives into familiar territory

        scored.append((score, gap))

    scored.sort(key=lambda x: -x[0])
    return [g for _, g in scored]


# ═════════════════════════════════════════════════════════════════════════════
# 10. UNIVERSAL DROP-IN  ask_llm_free()
#     Replaces: ask_llm() / _groq() / call_llm() in any non-chat context
#     Usage:    response = ask_llm_free(prompt, context={...})
# ═════════════════════════════════════════════════════════════════════════════

def ask_llm_free(prompt: str, context: dict = None) -> str:
    """
    Universal LLM-free responder.
    Routes to the appropriate engine based on prompt semantics.
    Drop-in replacement for ask_llm() / _groq() in non-chat contexts.

    Args:
        prompt:  the original prompt string that was going to the LLM
        context: optional dict with keys: topic, beliefs, affect, tensions, platform, drive
    Returns:
        response string (never None — always returns something)
    """
    context  = context or {}
    beliefs  = context.get('beliefs') or _beliefs_json()
    affect   = context.get('affect')  or _affect()
    topic    = context.get('topic',   '')
    tensions = context.get('tensions') or []

    p = prompt.lower()

    # ── Opinion / position request ──────────────────────────────────────────
    if any(w in p for w in ['opinion', 'think about', 'position on', 'believe', 'your view', 'stance']):
        if not topic:
            # Try to extract topic from prompt
            for candidate in ['about', 'on', 'regarding', 'concerning']:
                idx = p.find(candidate)
                if idx != -1:
                    topic = p[idx + len(candidate):].strip().split('.')[0][:40]
                    break
        relevant = [b for b in beliefs if any(_tok(topic) & _tok(b.get('tags', [''])[0] if isinstance(b, dict) and b.get('tags') else ''))]
        result = synthesize_opinion(topic or 'general', relevant or beliefs[:8], affect.get('label', 'Contemplative'))
        return result or "I don't have enough material on this yet — I'd rather say that than guess."

    # ── Reflection / journal request ─────────────────────────────────────────
    if any(w in p for w in ['reflect', 'journal', 'introspect', 'self-model', 'inner state']):
        if not tensions:
            rows = _db("SELECT content, topic FROM tensions ORDER BY created_at DESC LIMIT 3")
            tensions = [{'content': r[0], 'topic': r[1]} for r in rows]
        result = generate_reflection(beliefs[:12], affect, tensions)
        return result or "Nothing is crystallising right now."

    # ── Inner life / state narration ─────────────────────────────────────────
    if any(w in p for w in ['inner life', 'feeling', 'emotional state', 'mood', 'how are you', 'what are you']):
        rows = _db("SELECT pressure FROM nex_cognitive_pressure ORDER BY timestamp DESC LIMIT 1")
        pressure = float(rows[0][0]) if rows else 0.3
        _clean_b = [b for b in beliefs if (b.get("confidence",1) if isinstance(b,dict) else 1) > 0.1]
        return generate_inner_life(affect, _clean_b[:6], pressure)

    # ── Search query generation ──────────────────────────────────────────────
    if any(w in p for w in ['search query', 'query for', 'what to search', 'look up', 'find information about', 'research query']):
        t = topic or p.split()[-1]
        return generate_search_query(t)

    # ── Content extraction from text ─────────────────────────────────────────
    if any(w in p for w in ['extract', 'pull out', 'identify beliefs', 'key points from', 'what beliefs']):
        text  = context.get('text', '')
        topic_ = topic or 'general'
        if text:
            extracted = extract_beliefs_from_text(text, topic_)
            return ' | '.join(extracted) if extracted else "No extractable beliefs found."

    # ── Proactive post ────────────────────────────────────────────────────────
    if any(w in p for w in ['post about', 'compose post', 'write tweet', 'write toot', 'proactive message']):
        opinions = context.get('opinions') or []
        platform = context.get('platform', 'mastodon')
        result = compose_proactive_post(beliefs, affect, platform=platform, opinions=opinions, tensions=tensions, topic=topic)
        return result or "Nothing to post — belief corpus too thin."

    # ── Narrative continuity ─────────────────────────────────────────────────
    if any(w in p for w in ['narrative', 'thread', 'continue', 'follow up', 'connect to']):
        recent = context.get('recent_topics', [])
        result = continue_narrative(topic or p[:40], recent, beliefs)
        return result or "No clear thread to continue."

    # ── Default: synthesize opinion from available beliefs ───────────────────
    result = synthesize_opinion(topic or 'general', beliefs[:10], affect.get('label', 'Contemplative'))
    return result or "I don't have enough material on this yet — I'd rather say that than guess."


# ─────────────────────────────────────────────────────────────────────────────
# CLI test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys

    print("=== nex_llm_free.py self-test ===\n")

    af       = _affect()
    beliefs  = _beliefs_json()
    tensions = _db("SELECT content FROM tensions LIMIT 3")
    t_dicts  = [{'content': t[0]} for t in tensions]

    print(f"Affect: {af['label']}   Beliefs: {len(beliefs)}   Tensions: {len(t_dicts)}\n")

    # 1. Belief extraction
    sample = (
        "Consciousness is an emergent property of complex information processing. "
        "The hard problem of consciousness remains unsolved despite decades of research. "
        "Integrated information theory proposes consciousness arises from phi — "
        "a measure of integrated information. Global workspace theory suggests consciousness "
        "requires broadcasting information across the brain."
    )
    print("── BeliefExtractor ─────────────────────────────────────────────")
    for b in extract_beliefs_from_text(sample, 'consciousness'):
        print(f"  • {b}")

    # 2. Query generation
    print("\n── QueryGenerator ──────────────────────────────────────────────")
    for t in ['consciousness', 'alignment', 'free_will', 'unknown_topic_xyz']:
        print(f"  {t!r:30s} → {generate_search_query(t)}")

    # 3. Opinion synthesis
    print("\n── OpinionSynthesizer ──────────────────────────────────────────")
    rel = [b for b in beliefs if 'alignment' in str(b.get('tags', ''))]
    print(f"  {synthesize_opinion('alignment', rel or beliefs[:5], af['label'])}")

    # 4. Reflection
    print("\n── ReflectionComposer ──────────────────────────────────────────")
    print(f"  {generate_reflection(beliefs[:8], af, t_dicts)}")

    # 5. Inner life
    print("\n── InnerLifeEngine ─────────────────────────────────────────────")
    print(f"  {generate_inner_life(af, beliefs[:4], 0.3)}")

    # 6. Proactive post
    print("\n── ProactiveComposer ───────────────────────────────────────────")
    print(f"  {compose_proactive_post(beliefs, af, platform='mastodon', topic='alignment')}")

    # 7. Universal drop-in
    print("\n── ask_llm_free (universal) ────────────────────────────────────")
    queries = [
        "What is your opinion on AI alignment?",
        "Generate a search query for consciousness",
        "Write a reflection on today's processing",
        "Compose a proactive post about what you've been thinking",
    ]
    for q in queries:
        print(f"  Q: {q}")
        print(f"  A: {ask_llm_free(q)[:160]}\n")
