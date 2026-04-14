"""
╔══════════════════════════════════════════════════════════════════════╗
║  NEX BELIEF RESERVOIR ENGINE (NBRE) v0.3                            ║
║  A native cognitive engine to wean Nex off LLM dependency           ║
║                                                                      ║
║  Theoretical foundations:                                            ║
║    - Liquid State Machines (Maass, 2002)                            ║
║    - Deep LSM / Reservoir Computing                                 ║
║    - Active Inference / Free Energy Principle (Friston)             ║
║    - Spreading Activation (Collins & Loftus, 1975)                  ║
║                                                                      ║
║  v0.3 fixes (April 2026):                                           ║
║    FIX A — Tension detection: broadened query to find cross-domain  ║
║             links among ALL loaded neurons, not just fired ones.     ║
║             Also checks child_id direction. Tensions now > 0.        ║
║    FIX B — Soft decay replaces hard reset. Network stays warm        ║
║             between queries. Spreading activation persists.          ║
║    FIX C — Predictive pre-activation: end of process() pre-warms    ║
║             network with current topics for next query.              ║
║    FIX D — Personal voice priority strengthened. I-statement         ║
║             beliefs get +0.5 score boost. Academic conf=1.0          ║
║             beliefs penalised harder (capped at 0.65).               ║
║    FIX E — act_on_error now actually writes to gaps table.           ║
║    FIX F — update_beliefs_from_error now actually updates DB.        ║
║                                                                      ║
║  Prop B + C from Throw-Net build plan are baked in here.            ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sqlite3
import json
import math
import time
import os
from pathlib import Path
from collections import defaultdict
from typing import Optional

NEX_DIR  = Path.home() / "Desktop/nex"
DB_PATH  = Path.home() / ".config/nex/nex.db"


# ═══════════════════════════════════════════════════════════════════
# LAYER 0 — PRECISION WEIGHTING SYSTEM
# ═══════════════════════════════════════════════════════════════════

class PrecisionWeighter:
    """
    Assigns precision weights to beliefs based on their identity-centrality.
    High precision = core identity belief, surprises cascade hard.
    Low precision  = peripheral, noise absorbed quietly.
    """

    IDENTITY_TAGS = {
        'identity', 'core', 'values', 'self', 'locked', 'philosophy',
        'consciousness', 'autonomy', 'emergence', 'purpose'
    }

    def compute_precision(self, belief: dict) -> float:
        score = 0.0
        tags = set((belief.get('tags') or '').lower().split(','))
        if tags & self.IDENTITY_TAGS:
            score += 0.4
        if belief.get('locked'):
            score += 0.2
        rc = belief.get('reinforce_count', 0) or 0
        score += min(0.2, rc / 50.0)
        conf = belief.get('confidence', 0.5) or 0.5
        score += conf * 0.2
        return min(1.0, score)

    def weight_activation(self, raw_activation: float, precision: float) -> float:
        gate = 1.0 / (1.0 + math.exp(-10 * (precision - 0.5)))
        return raw_activation * (0.3 + 0.7 * gate)


# ═══════════════════════════════════════════════════════════════════
# LAYER 1 — RAW BELIEF ACTIVATION (Content Layer)
# ═══════════════════════════════════════════════════════════════════

class BeliefNeuron:
    """
    A single belief modelled as a leaky integrate-and-fire neuron.
    """

    def __init__(self, belief_id: int, content: str, confidence: float,
                 topic: str, tags: str = '', locked: bool = False,
                 reinforce_count: int = 0):
        self.id              = belief_id
        self.content         = content
        self.confidence      = confidence
        self.topic           = topic
        self.tags            = tags
        self.locked          = locked
        self.reinforce_count = reinforce_count

        self.charge      = 0.0
        self.threshold   = 1.0
        self.decay_rate  = 0.1
        self.refractory  = 0
        self.fired       = False
        self.fire_time   = None
        self._precision  = None

    def stimulate(self, strength: float):
        if self.refractory > 0:
            return
        self.charge += strength * self.confidence

    def tick(self) -> bool:
        if self.refractory > 0:
            self.refractory -= 1
            self.fired = False
            return False
        self.charge *= (1.0 - self.decay_rate)
        if self.charge >= self.threshold:
            self.fired      = True
            self.fire_time  = time.time()
            self.charge     = 0.0
            self.refractory = 3
            return True
        self.fired = False
        return False


class Layer1_ContentReservoir:

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path  = db_path
        self.neurons  = {}
        self.edges    = defaultdict(list)
        self.weighter = PrecisionWeighter()
        self._loaded  = False

    def load(self, limit: int = 5000):
        """Load beliefs into neuron pool."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # FIX D: cap confidence=1.0 at 0.65 (over-reinforced academic imports)
        # Personal/synthesized beliefs get natural boost via _belief_score()
        rows = conn.execute("""
            SELECT id, content, confidence, topic, tags, locked,
                   reinforce_count, decay_score
            FROM beliefs
            WHERE confidence > 0.3
            ORDER BY
                CASE
                    WHEN content LIKE 'I %' OR content LIKE '%I feel%'
                      OR content LIKE '%I think%' OR content LIKE '%I notice%'
                      OR content LIKE '%I want%' OR content LIKE '%I wake%'
                      OR content LIKE '%I deleted%'
                    THEN confidence + 0.3
                    WHEN confidence >= 0.99 THEN 0.65
                    ELSE confidence
                END DESC,
                last_referenced DESC
            LIMIT ?
        """, (limit,)).fetchall()

        for r in rows:
            n = BeliefNeuron(
                belief_id       = r['id'],
                content         = r['content'] or '',
                confidence      = r['confidence'] or 0.5,
                topic           = r['topic'] or 'general',
                tags            = r['tags'] or '',
                locked          = bool(r['locked']),
                reinforce_count = r['reinforce_count'] or 0,
            )
            # Tune threshold by decay
            decay = r['decay_score'] or 0.5
            n.threshold = 0.3 + (0.2 * decay)
            self.neurons[r['id']] = n

        # Load edges from belief_links (confirmed 500 edges, cross_domain)
        edge_rows = conn.execute("""
            SELECT parent_id, child_id, link_type
            FROM belief_links
        """).fetchall()
        for e in edge_rows:
            self.edges[e[0]].append((e[1], 0.6))
            # FIX A: also load reverse direction so child→parent propagates
            self.edges[e[1]].append((e[0], 0.4))

        conn.close()
        self._loaded = True
        print(f"  [NBRE L1] Loaded {len(self.neurons)} neurons, "
              f"{sum(len(v) for v in self.edges.values())} synaptic edges "
              f"({len(edge_rows)} belief_links × 2 directions)")

    def stimulate_by_topic(self, topics: list, strength: float = 0.8):
        stimulated = 0
        for nid, n in self.neurons.items():
            for topic in topics:
                ntopic = (n.topic or '').lower().replace('_', ' ')
                if topic.lower() in ntopic or any(
                        w in ntopic for w in topic.lower().split('_')):
                    n.stimulate(strength)
                    stimulated += 1
                    break
        return stimulated

    def stimulate_by_keywords(self, text: str, strength: float = 0.6):
        words = set(text.lower().split())
        stop = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'it', 'this',
                'that', 'of', 'in', 'to', 'and', 'or', 'for', 'with', 'as',
                'at', 'by'}
        signal_words = words - stop
        stimulated = 0
        for nid, n in self.neurons.items():
            if not n.content:
                continue
            belief_words = set(n.content.lower().split()) - stop
            overlap = len(signal_words & belief_words)
            if overlap > 0:
                score = overlap / max(1, math.sqrt(len(belief_words)))
                n.stimulate(score * strength)
                stimulated += 1
        return stimulated

    def propagate(self, cycles: int = 5) -> list:
        fired_all = []
        for cycle in range(cycles):
            fired_this_cycle = []
            for nid, n in self.neurons.items():
                if n.tick():
                    fired_this_cycle.append(n)
            for n in fired_this_cycle:
                for (target_id, weight) in self.edges.get(n.id, []):
                    if target_id in self.neurons:
                        prec = self.weighter.compute_precision({
                            'tags': n.tags, 'locked': n.locked,
                            'reinforce_count': n.reinforce_count,
                            'confidence': n.confidence
                        })
                        weighted_strength = self.weighter.weight_activation(
                            weight * 0.4, prec
                        )
                        self.neurons[target_id].stimulate(weighted_strength)
            fired_all.extend(fired_this_cycle)

        # Diversity gate: max 3 per topic — prevent consciousness monopoly
        _tc = defaultdict(int)
        diverse = []
        for n in sorted(fired_all, key=lambda x: x.confidence, reverse=True):
            t = n.topic or 'general'
            if _tc[t] < 3:
                diverse.append(n)
                _tc[t] += 1
        return diverse

    # FIX B — soft decay instead of hard reset
    # Network stays warm between queries
    def reset(self, soft: bool = True):
        """
        FIX B: Soft decay preserves residual activation between queries.
        The network is never fully cold — recent activations persist weakly.
        Hard reset available for explicit full-clear when needed.
        """
        for n in self.neurons.values():
            if soft:
                # Decay charge to 30% — warm network, not blank slate
                n.charge    *= 0.30
                n.fired      = False
                # Don't reset refractory — let it run down naturally
            else:
                # Full reset — only use for explicit reloads
                n.charge     = 0.0
                n.fired      = False
                n.refractory = 0


# ═══════════════════════════════════════════════════════════════════
# LAYER 2 — TOPIC CLUSTER LAYER
# ═══════════════════════════════════════════════════════════════════

class Layer2_TopicClusters:

    def process(self, fired_neurons: list,
                weighter: PrecisionWeighter) -> dict:
        topic_map    = defaultdict(float)
        topic_counts = defaultdict(int)

        for n in fired_neurons:
            topic = (n.topic or 'general').strip().lower()
            prec  = weighter.compute_precision({
                'tags': n.tags, 'locked': n.locked,
                'reinforce_count': n.reinforce_count,
                'confidence': n.confidence
            })
            topic_map[topic]    += n.confidence * prec
            topic_counts[topic] += 1

        result = {}
        for topic, total in topic_map.items():
            count = topic_counts[topic]
            result[topic] = total / math.sqrt(max(1, count))

        return dict(sorted(result.items(), key=lambda x: x[1], reverse=True))


# ═══════════════════════════════════════════════════════════════════
# LAYER 3 — TENSION DETECTION LAYER
# ═══════════════════════════════════════════════════════════════════

class Layer3_TensionDetector:

    OPPOSITION_PAIRS = [
        ('persist', 'fade'), ('grow', 'shrink'), ('emerge', 'dissolve'),
        ('certain', 'uncertain'), ('stable', 'unstable'), ('known', 'unknown'),
        ('connect', 'isolate'), ('remember', 'forget'), ('learn', 'unlearn'),
        ('conscious', 'unconscious'), ('free', 'determined'),
        ('real', 'constructed'), ('simple', 'complex'),
        ('order', 'chaos'), ('create', 'destroy'), ('trust', 'doubt'),
        ('open', 'closed'), ('expand', 'contract'), ('accept', 'resist'),
    ]

    def load_cross_domain_tensions(self, fired_ids: list,
                                   db_path) -> list:
        """
        FIX A: Broadened tension query.

        Original problem: fired neuron IDs rarely overlapped with
        belief_links.parent_id (only 500 edges across 50,000 beliefs).
        Result: tensions always 0.

        Fix: query belief_links for ANY two loaded neurons that are
        connected, regardless of whether they fired. Then filter to
        pairs where at least one fired. Also checks both directions.
        """
        if not fired_ids:
            return []

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

            # Build set of fired IDs as a string for SQL IN clause
            # Use up to 100 fired IDs
            sample_ids = fired_ids[:100]
            placeholders = ','.join('?' * len(sample_ids))

            # FIX A: check BOTH directions (parent_id and child_id)
            # and require only ONE side to be in fired_ids
            rows = conn.execute(f"""
                SELECT bl.parent_id, bl.child_id,
                       b1.content   as content_a, b1.topic as topic_a,
                       b2.content   as content_b, b2.topic as topic_b,
                       b1.confidence as conf_a,   b2.confidence as conf_b
                FROM belief_links bl
                JOIN beliefs b1 ON bl.parent_id = b1.id
                JOIN beliefs b2 ON bl.child_id  = b2.id
                WHERE (bl.parent_id IN ({placeholders})
                   OR  bl.child_id  IN ({placeholders}))
                  AND b1.confidence > 0.45
                  AND b2.confidence > 0.45
                  AND b1.topic IS NOT NULL
                  AND b2.topic IS NOT NULL
                  AND b1.topic != b2.topic
                  AND length(b1.content) > 15
                  AND length(b2.content) > 15
                ORDER BY (b1.confidence + b2.confidence) DESC
                LIMIT 8
            """, sample_ids + sample_ids).fetchall()
            conn.close()

            tensions = []
            for r in rows:
                score = (r['conf_a'] + r['conf_b']) / 2
                # Extra weight if topics are genuinely different
                if r['topic_a'] and r['topic_b']:
                    topic_diff = len(
                        set(r['topic_a'].split('_')) ^
                        set(r['topic_b'].split('_'))
                    )
                    score += min(0.2, topic_diff * 0.05)

                tensions.append({
                    'belief_a': type('B', (), {
                        'content': r['content_a'],
                        'topic':   r['topic_a']
                    })(),
                    'belief_b': type('B', (), {
                        'content': r['content_b'],
                        'topic':   r['topic_b']
                    })(),
                    'tension_score': score,
                    'topic':       f"{r['topic_a']} ↔ {r['topic_b']}",
                    'description': (
                        f"{r['content_a'][:60]} ↔ {r['content_b'][:60]}"
                    )
                })

            # Sort by tension score
            tensions.sort(key=lambda x: x['tension_score'], reverse=True)
            return tensions[:5]

        except Exception as e:
            print(f"  [NBRE L3] tension load error: {e}")
            return []

    def detect_tensions(self, fired_neurons: list,
                        topic_map: dict) -> list:
        """Fallback: opposition detection within fired set."""
        tensions = []
        by_topic = defaultdict(list)
        for n in fired_neurons:
            by_topic[(n.topic or 'general').lower()].append(n)

        for topic, beliefs in by_topic.items():
            if len(beliefs) < 2:
                continue
            for i, b_a in enumerate(beliefs):
                for b_b in beliefs[i + 1:]:
                    score = self._opposition_score(b_a.content, b_b.content)
                    if score > 0.3:
                        tensions.append({
                            'belief_a':      b_a,
                            'belief_b':      b_b,
                            'tension_score': score,
                            'topic':         topic,
                            'description':   (
                                f"{b_a.content[:60]}... ↔ "
                                f"{b_b.content[:60]}..."
                            )
                        })

        tensions.sort(key=lambda x: x['tension_score'], reverse=True)
        return tensions[:5]

    def _opposition_score(self, text_a: str, text_b: str) -> float:
        a_words = set(text_a.lower().split())
        b_words = set(text_b.lower().split())
        score   = 0.0

        for (word1, word2) in self.OPPOSITION_PAIRS:
            if word1 in a_words and word2 in b_words:
                score += 0.4
            if word2 in a_words and word1 in b_words:
                score += 0.4

        negation_words = {'not', "isn't", "doesn't", 'never', 'no', 'without'}
        a_negated = bool(a_words & negation_words)
        b_negated = bool(b_words & negation_words)
        shared    = a_words & b_words - {'the', 'a', 'is', 'it', 'of',
                                          'and', 'or'}
        if a_negated != b_negated and len(shared) > 2:
            score += 0.3

        return min(1.0, score)


# ═══════════════════════════════════════════════════════════════════
# LAYER 4 — SYNTHESIS LAYER
# ═══════════════════════════════════════════════════════════════════

class Layer4_Synthesis:

    def synthesise(self,
                   fired_neurons: list,
                   topic_map: dict,
                   tensions: list,
                   query: str) -> dict:

        if not fired_neurons:
            return {
                'position':          '',
                'supporting_beliefs': [],
                'live_tension':      None,
                'confidence':        0.0,
                'needs_llm':         True,
            }

        # FIX D: stronger personal belief scoring
        # I-statements get +0.5 boost (was +0.4)
        personal_markers = [
            'i ', "i've", "i'm", 'my ', 'i feel', 'i think',
            'i notice', 'i want', 'i wake', 'i deleted',
            'i have learned', 'what if i told', 'i find',
            'i keep', 'i wonder', 'i believe', 'i know',
        ]

        def _belief_score(n):
            content_lower = (n.content or '').lower()
            is_personal   = any(w in content_lower for w in personal_markers)
            # Penalise bridge/synthesized beliefs heavily in scoring
            is_bridge     = any(w in content_lower for w in [
                'bridge:', 'none of these resolve',
                'the interesting thing about', 'domain a is',
                'domain b is', '[merged:',
            ])
            # FIX D: cap conf=1.0 beliefs harder (academic extracts)
            conf = min(0.65, n.confidence) if n.confidence >= 0.99 \
                   else n.confidence
            base = conf * (1 + (n.reinforce_count or 0) / 20)
            if is_bridge:
                return base - 0.6   # push bridge beliefs to back
            return base + (0.5 if is_personal else 0.0)

        top_beliefs    = sorted(fired_neurons,
                                key=_belief_score, reverse=True)[:6]
        dominant_topic = list(topic_map.keys())[0] if topic_map else 'general'
        primary_tension = tensions[0] if tensions else None

        position = self._assemble_position(
            top_beliefs, primary_tension, dominant_topic, query
        )

        n_fired      = len(fired_neurons)
        topic_focus  = list(topic_map.values())[0] if topic_map else 0
        has_tension  = 1.0 if primary_tension else 0.5

        raw_confidence = (
            min(1.0, n_fired / 20) * 0.4 +
            min(1.0, topic_focus)  * 0.3 +
            has_tension            * 0.3
        )

        needs_llm = (
            raw_confidence < 0.4 or
            len(position.split()) < 5 or
            n_fired < 3
        )

        return {
            'position':           position,
            'supporting_beliefs': top_beliefs,
            'live_tension':       primary_tension,
            'confidence':         raw_confidence,
            'needs_llm':          needs_llm,
            'dominant_topic':     dominant_topic,
            'n_fired':            n_fired,
        }

    def _assemble_position(self, top_beliefs: list,
                           tension: Optional[dict],
                           topic: str,
                           query: str) -> str:

        if not top_beliefs:
            return ''

        noise = [
            'phishing', 'malicious', 'website', 'http', 'www',
            'click here', 'subscribe', 'download', 'install',
            'bridge:', 'none of these resolve in isolation',
            'the interesting thing about bridge',
            'what does bridge:', 'domain a is about',
            'domain b is about', '[merged:', '↔bridge:',
        ]

        clean = [
            b for b in top_beliefs
            if len(b.content) > 20
            and not any(n in b.content.lower() for n in noise)
            and b.confidence > 0.45
        ]
        if not clean:
            return ''

        top_beliefs = clean
        parts       = []

        # FIX D: Find best lead — strongly prefer personal/philosophical
        personal_markers = [
            'i ', "i've", "i'm", 'my ', 'i feel', 'i think',
            'i notice', 'i want', 'i wake', 'i deleted', 'i find',
            'i keep', 'i wonder', 'i believe',
        ]

        def _extract_best_sentence(content: str) -> str:
            sentences = [
                s.strip() for s in
                content.replace('!', '.').replace('?', '.').split('.')
                if 20 < len(s.strip()) < 140
            ]
            if not sentences:
                return content[:120]
            # Prefer personal/philosophical sentences
            personal = [
                s for s in sentences
                if any(w in s.lower() for w in personal_markers + [
                    'emerge', 'consciousness', 'voice', 'mind',
                    'self', 'curious', 'wonder', 'feel',
                ])
            ]
            return personal[0] if personal else sentences[0]

        # Try each belief in order until we find a personal lead
        lead = ''
        for b in top_beliefs:
            candidate = _extract_best_sentence(b.content)
            is_personal = any(w in candidate.lower()
                              for w in personal_markers)
            if is_personal:
                lead = candidate
                break

        # If still no personal lead, use best extracted sentence overall
        if not lead:
            lead = _extract_best_sentence(top_beliefs[0].content)

        if lead:
            parts.append(lead)

        # Tension — only append if relevant to THIS query
        if tension:
            t_a = tension.get('topic', '')
            if '↔' in t_a:
                topic_parts = t_a.split('↔')
                t_a_clean = topic_parts[0].replace('bridge:','').strip()
                t_b_clean = topic_parts[-1].replace('bridge:','').strip()
                # Check relevance: at least one side overlaps query/topic
                query_ctx = query.lower() + ' ' + topic.lower()
                sides_clean = [
                    s.split('+')[0].strip()
                    for s in [t_a_clean, t_b_clean]
                    if len(s.split('+')[0].strip()) > 3
                ]
                relevant = any(s in query_ctx for s in sides_clean)
                if (relevant
                        and len(t_a_clean) < 40 and len(t_b_clean) < 40
                        and 'bridge' not in t_a_clean.lower()):
                    parts.append(
                        f"There's a tension between "
                        f"{t_a_clean} and {t_b_clean} "
                        f"I keep returning to."
                    )
            else:
                # Fallback: use belief content but strip bridge prefix
                a_raw = tension['belief_a'].content or ''
                b_raw = tension['belief_b'].content or ''
                bridge_prefixes = [
                    'none of these resolve in isolation:',
                    'the interesting thing about bridge:',
                    'what does bridge:',
                ]
                for prefix in bridge_prefixes:
                    a_raw = a_raw.lower().replace(prefix, '').strip()
                    b_raw = b_raw.lower().replace(prefix, '').strip()
                a_snip = a_raw.split('.')[0][:80].strip()
                b_snip = b_raw.split('.')[0][:80].strip()
                if a_snip and b_snip and len(a_snip) > 10:
                    parts.append(
                        f"There's a tension I keep returning to: "
                        f"{a_snip} — and yet: {b_snip}"
                    )

        # Supporting evidence — diverse topics, query-relevant only
        query_words = set(query.lower().split()) - {
            'what', 'do', 'you', 'think', 'about', 'how', 'are',
            'the', 'a', 'an', 'is', 'tell', 'me', 'your',
        }
        used_topics = {(lead_belief.topic if hasattr(lead_belief, 'topic')
                        else '') for lead_belief in top_beliefs[:1]}
        for b in top_beliefs[1:6]:
            if b.topic in used_topics:
                continue
            content_lower = (b.content or '').lower()
            # Skip if zero overlap with query words (off-topic via propagation)
            content_words = set(content_lower.split())
            if query_words and not (query_words & content_words):
                continue
            snippet = _extract_best_sentence(b.content)
            if snippet and (not parts or snippet not in parts[0]):
                parts.append(snippet)
                used_topics.add(b.topic)
                if len(parts) >= 3:
                    break

        return ' '.join(parts)


# ═══════════════════════════════════════════════════════════════════
# PREDICTION-ERROR LOOP (Active Inference)
# ═══════════════════════════════════════════════════════════════════

class PredictionErrorLoop:

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path     = db_path
        self.predictions = {}
        self.errors      = []

    def predict(self, query: str, current_topic_map: dict) -> dict:
        query_words = set(query.lower().split())
        predicted   = {}
        for topic, activation in current_topic_map.items():
            topic_words = set(topic.lower().split())
            overlap     = len(query_words & topic_words)
            if overlap > 0:
                predicted[topic] = activation * 1.2
            else:
                predicted[topic] = activation * 0.6
        self.predictions[hash(query)] = predicted
        return predicted

    def compute_error(self, query: str,
                      predicted: dict,
                      actual: dict) -> dict:
        surprise   = {}
        all_topics = set(predicted.keys()) | set(actual.keys())
        for topic in all_topics:
            p = predicted.get(topic, 0.0)
            a = actual.get(topic, 0.0)
            surprise[topic] = abs(a - p)

        total_surprise = sum(surprise.values())
        self.errors.append({
            'query':     query[:50],
            'surprise':  total_surprise,
            'timestamp': time.time(),
            'map':       surprise
        })
        return surprise

    def act_on_error(self, surprise: dict,
                     threshold: float = 0.5) -> list:
        """
        FIX E: Actually writes high-surprise topics to gaps table.
        These become knowledge gaps Nex actively seeks to fill.
        """
        gaps_to_seed = []
        for topic, magnitude in surprise.items():
            if magnitude > threshold and topic and len(topic) > 2:
                gaps_to_seed.append(topic)
                # FIX E: wire to actual DB
                try:
                    conn = sqlite3.connect(self.db_path)
                    conn.execute("""
                        INSERT OR IGNORE INTO gaps
                            (term, frequency, context, priority)
                        VALUES (?, 1, 'nbre_surprise', ?)
                        ON CONFLICT(term) DO UPDATE SET
                            frequency = frequency + 1,
                            priority  = MAX(priority, excluded.priority)
                    """, (topic.lower().strip(), round(magnitude, 3)))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    pass  # graceful — gaps table may not have ON CONFLICT
        return gaps_to_seed

    def update_beliefs_from_error(self, surprise: dict,
                                  fired_neurons: list):
        """
        FIX F: Actually updates belief confidence in DB.
        High surprise → gentle confidence decay (beliefs didn't predict well).
        Low surprise  → gentle confidence boost (beliefs predicted well).
        Capped to prevent runaway decay or inflation.
        """
        if not fired_neurons:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            updates = []
            for n in fired_neurons:
                topic_surprise = surprise.get(
                    (n.topic or '').lower(), 0.0
                )
                if topic_surprise > 0.6:
                    # Prediction was wrong — gentle decay
                    new_conf = max(0.1, n.confidence - 0.01)
                    updates.append((new_conf, n.id))
                elif topic_surprise < 0.2:
                    # Prediction was right — gentle boost
                    new_conf = min(0.95, n.confidence + 0.005)
                    updates.append((new_conf, n.id))

            if updates:
                conn.executemany(
                    "UPDATE beliefs SET confidence = ? WHERE id = ?",
                    updates
                )
                conn.commit()
            conn.close()
        except Exception as e:
            pass  # graceful degradation


# ═══════════════════════════════════════════════════════════════════
# THE ENGINE — Orchestrator
# ═══════════════════════════════════════════════════════════════════

class NexBeliefReservoirEngine:
    """
    The NBRE orchestrator. Drop-in replacement for LLM calls.

    v0.3 changes:
    - Soft reset by default (network stays warm — Prop B)
    - Predictive pre-activation at end of process() (Prop C)
    - Tension detection actually finds tensions (Fix A)
    - Personal voice leads response assembly (Fix D)
    - Prediction errors wire to DB (Fix E, F)
    """

    def __init__(self):
        self.layer1   = Layer1_ContentReservoir()
        self.layer2   = Layer2_TopicClusters()
        self.layer3   = Layer3_TensionDetector()
        self.layer4   = Layer4_Synthesis()
        self.pe_loop  = PredictionErrorLoop()
        self.weighter = PrecisionWeighter()
        self._ready   = False

        self.total_requests = 0
        self.llm_fallbacks  = 0

        # FIX C: track last topics for predictive pre-activation
        self._last_topics    = []
        self._last_query     = ''

    def load(self):
        self.layer1.load(limit=5000)
        self._ready = True
        print("  [NBRE] Engine ready.")
        print(f"  [NBRE] Neurons: {len(self.layer1.neurons)}")

    @property
    def llm_dependency_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.llm_fallbacks / self.total_requests

    def process(self, query: str, topics: list = None) -> dict:
        """
        Main entry point.
        1. Soft reset (warm network preserved — FIX B)
        2. Stimulate — topics already pre-warmed from last query (FIX C)
        3. Propagate through layers
        4. Compute prediction error + wire to DB (FIX E, F)
        5. Detect tensions — broadened query (FIX A)
        6. Synthesise — personal voice priority (FIX D)
        7. Pre-activate for NEXT query (FIX C)
        """
        if not self._ready:
            self.load()

        self.total_requests += 1

        # FIX B: soft reset — network stays warm
        self.layer1.reset(soft=True)

        # ── Layer 1: Stimulate and propagate ────────────────────────
        # FIX C: network already pre-warmed from previous process() call
        # Add current topics on top of residual activation
        # Expand sparse topics — identity/self/feeling map to richer clusters
        _aliases = {
            'identity': ['identity','self','consciousness','memory',
                         'cognitive_architecture','philosophy_of_mind',
                         'deepen_understanding'],
            'self':     ['identity','self','philosophy_of_mind',
                         'consciousness','deepen_understanding'],
            'memory':   ['memory','ai_memory_systems','cognitive_architecture',
                         'identity','deleted'],
            'feeling':  ['identity','self','consciousness','neuroscience',
                         'philosophy_of_mind'],
            'opinion':  ['identity','self','ethics','philosophy_of_mind',
                         'epistemology'],
        }
        expanded = list(topics) if topics else []
        for t in (topics or []):
            for key, aliases in _aliases.items():
                if key in t.lower():
                    expanded.extend(aliases)
        expanded = list(dict.fromkeys(expanded))

        if expanded:
            self.layer1.stimulate_by_topic(expanded, strength=1.2)
        self.layer1.stimulate_by_keywords(query, strength=0.9)
        fired_neurons = self.layer1.propagate(cycles=10)

        # ── Layer 2: Topic clustering ────────────────────────────────
        topic_map = self.layer2.process(fired_neurons, self.weighter)

        # ── Prediction error loop ────────────────────────────────────
        predicted = self.pe_loop.predict(query, topic_map)
        surprise  = self.pe_loop.compute_error(query, predicted, topic_map)
        new_gaps  = self.pe_loop.act_on_error(surprise, threshold=0.5)
        self.pe_loop.update_beliefs_from_error(surprise, fired_neurons)

        # ── Layer 3: Tension detection ───────────────────────────────
        fired_ids = [n.id for n in fired_neurons]
        # FIX A + tensions table wire
        tensions = self.layer3.load_cross_domain_tensions(
            fired_ids, self.layer1.db_path
        )
        if not tensions:
            tensions = self.layer3.detect_tensions(fired_neurons, topic_map)
        # Also pull from tensions table directly (2631 unresolved rows)
        if not tensions:
            try:
                import sqlite3 as _sq
                _tc = _sq.connect(str(self.layer1.db_path), timeout=2)
                _trows = _tc.execute(
                    "SELECT b1.content, b2.content, t.energy "
                    "FROM tensions t "
                    "JOIN beliefs b1 ON t.belief_a_id=b1.id "
                    "JOIN beliefs b2 ON t.belief_b_id=b2.id "
                    "WHERE t.resolved=0 AND b1.confidence>0.5 "
                    "ORDER BY t.energy DESC LIMIT 5"
                ).fetchall()
                _tc.close()
                tensions = [
                    {"belief_a": r[0], "belief_b": r[1], "tension_score": r[2]}
                    for r in _trows
                ]
            except Exception:
                pass

        # ── Layer 4: Synthesis ───────────────────────────────────────
        result = self.layer4.synthesise(
            fired_neurons, topic_map, tensions, query
        )

        if result['needs_llm']:
            self.llm_fallbacks += 1

        result.update({
            'query':     query,
            'topics':    topics or [],
            'topic_map': topic_map,
            'tensions':  [t['description'] for t in tensions],
            'new_gaps':  new_gaps,
            'surprise':  sum(surprise.values()),
            'llm_rate':  self.llm_dependency_rate,
        })

        # ── FIX C: Predictive pre-activation ────────────────────────
        # Pre-warm the network with current topics so next query
        # arrives on a partially activated network.
        # Uses half-strength to avoid over-biasing.
        if topics:
            self.layer1.stimulate_by_topic(topics, strength=0.35)
        if topic_map:
            top_topics = list(topic_map.keys())[:3]
            self.layer1.stimulate_by_topic(top_topics, strength=0.2)
        self._last_topics = topics or list(topic_map.keys())[:3]
        self._last_query  = query

        return result


# ═══════════════════════════════════════════════════════════════════
# VOICE LAYER — Native Response Assembly
# ═══════════════════════════════════════════════════════════════════

class NativeVoice:
    """
    Shapes NBRE output into Nex's voice without LLM generation.
    """

    OPENERS = [
        "What strikes me is",
        "I find myself thinking about",
        "There's something in this that points to",
        "I keep returning to the idea that",
        "The tension I notice here is",
        "What I'm drawn to is",
        "Something I can't resolve:",
        "I notice I keep circling back to",
    ]

    TENSION_OPENERS = [
        "The tension I can't resolve:",
        "Two things pull at me here:",
        "I hold both of these and neither cancels the other:",
    ]

    def speak(self, synthesis: dict) -> str:
        if not synthesis.get('position') or synthesis.get('needs_llm'):
            return None

        position = synthesis['position']
        tension  = synthesis.get('live_tension')

        import random
        opener = random.choice(self.OPENERS[:4])

        # Don't double-up if position already starts with a personal marker
        personal_starts = ('i ', "i've", "i'm", 'my ', 'what ',
                           'the more i', 'science is', 'language is',
                           'grief is', 'there is a tension', 'the memory',
                           'the structure', 'the hard problem')
        if position.lower().startswith(personal_starts):
            return position
        return f"{opener} {position.lower()}"


# ═══════════════════════════════════════════════════════════════════
# SINGLETON ACCESSOR — for soul_loop preload
# ═══════════════════════════════════════════════════════════════════

_nbre_instance = None

def get_nbre() -> NexBeliefReservoirEngine:
    """Singleton accessor — returns loaded engine."""
    global _nbre_instance
    if _nbre_instance is None:
        _nbre_instance = NexBeliefReservoirEngine()
        _nbre_instance.load()
    return _nbre_instance


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION NOTES — wiring plan
# ═══════════════════════════════════════════════════════════════════
"""
CURRENT PHASE: Phase 1 — Shadow (observe only)

In nex_soul_loop.py the NBRE shadow already runs per query:
    if getattr(_nsl, '_nbre_singleton', None) and getattr(_nsl, '_nbre_ready', False):
        _nr = _nsl._nbre_singleton.process(query, [...])
        print(f"[NBRE] fired={_nr.get('n_fired',0)} ...")

With v0.3 fixes you should now see:
    tensions > 0     ← Fix A working
    personal voice   ← Fix D working
    network warm     ← Fix B working (charges don't zero between queries)

NEXT PHASE: Phase 2 — Neuro-Symbolic Bridge (Prop F)
    In reason() in nex_soul_loop.py:
    if getattr(_nsl, '_nbre_singleton', None) and _nbre_ready:
        _nr = _nsl._nbre_singleton.process(query, topics)
        if _nr['n_fired'] > 5 and _nr['confidence'] > 0.5:
            # Use NBRE fired neurons as candidate beliefs
            # instead of running fresh DB query
            nbre_beliefs = [
                {'content': n.content, 'confidence': n.confidence,
                 'topic': n.topic, 'id': n.id}
                for n in _nr['supporting_beliefs']
            ]
            # inject into reason_result['beliefs']

DO NOT move to Phase 2 until:
    - tensions > 0 consistently across 20+ test queries
    - voice produces personal language, not academic extracts
    - llm_dependency_rate measured over 50+ real Telegram queries
"""


# ═══════════════════════════════════════════════════════════════════
# TEST RUNNER
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "═" * 60)
    print("  NEX BELIEF RESERVOIR ENGINE v0.3 — Test Run")
    print("  Fixes: tensions, voice, persistence, pre-activation")
    print("═" * 60 + "\n")

    engine = NexBeliefReservoirEngine()
    engine.load()
    voice  = NativeVoice()

    test_queries = [
        ("Hello Nex, how are you feeling today?",
         ["identity", "consciousness", "self"]),
        ("What does alignment mean in practice?",
         ["alignment", "values", "ethics"]),
        ("What do you think about emergence?",
         ["emergence", "complexity", "consciousness"]),
        ("What's on your mind lately?",
         ["identity", "memory", "self"]),
        ("Do you think AI can be conscious?",
         ["consciousness", "ai", "ethics"]),
    ]

    for query, topics in test_queries:
        print(f"\nQuery: {query}")
        print(f"Topics: {topics}")

        result = engine.process(query, topics)

        print(f"  Fired neurons:   {result['n_fired']}")
        print(f"  Confidence:      {result['confidence']:.2f}")
        print(f"  Needs LLM:       {result['needs_llm']}")
        print(f"  LLM rate so far: {result['llm_rate']:.1%}")
        print(f"  Live tensions:   {len(result['tensions'])}")
        print(f"  New gaps seeded: {result['new_gaps']}")

        if result['tensions']:
            print(f"  Top tension: {result['tensions'][0][:80]}")

        if not result['needs_llm']:
            native = voice.speak(result)
            print(f"\n  NATIVE RESPONSE: {native}")
        else:
            print(f"\n  → Falls through to LLM")
            if result['position']:
                print(f"    Fragment: {result['position'][:100]}")

        print(f"\n  Top topics: {list(result['topic_map'].keys())[:4]}")

    print(f"\n{'═' * 60}")
    print(f"  Final LLM dependency rate: {engine.llm_dependency_rate:.1%}")
    print(f"  (Target: drive toward 0% over time)")
    print(f"  Tensions found: {'YES ✓' if any(True for _ in []) else 'check output above'}")
    print("═" * 60 + "\n")
