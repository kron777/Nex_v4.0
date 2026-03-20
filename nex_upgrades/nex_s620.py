# nex_s620.py — S601–S620: Adaptive Intelligence Stack (20 modules)
# Deploy to: ~/Desktop/nex/nex_upgrades/nex_s620.py
# Tick injection: after R181 tick in run.py, at cycle+=1 level (20-space indent)
# Telegram: /s620status

import sqlite3
import json
import time
import math
import random
import pathlib
from datetime import datetime, timedelta
from collections import defaultdict, deque

_LOG   = '/tmp/nex_s620.log'
_DB    = str(pathlib.Path.home() / '.config/nex/nex.db')
_CFG   = pathlib.Path.home() / '.config/nex'

def _log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[s620 {ts}] {msg}'
    print(line)
    try:
        open(_LOG, 'a').write(line + '\n')
    except Exception:
        pass

def _db():
    c = sqlite3.connect(_DB, timeout=5)
    c.row_factory = sqlite3.Row
    return c

def _cfg_load(name, default):
    p = _CFG / name
    try:
        return json.loads(p.read_text()) if p.exists() else default
    except Exception:
        return default

def _cfg_save(name, data):
    try:
        (_CFG / name).write_text(json.dumps(data, indent=2))
    except Exception:
        pass

# ── S601: UNCERTAINTY TRACKING SYSTEM ────────────────────────────────────────
class UncertaintyTracker:
    """Attach uncertainty scores to beliefs/decisions, propagate through chains,
    penalise high-confidence + low-evidence states."""

    def __init__(self):
        self.scores   = {}   # belief_id → uncertainty (0=certain, 1=unknown)
        self.unknown_threshold = 0.75
        self._ensure_column()
        _log('[S601] UncertaintyTracker ready')

    def _ensure_column(self):
        try:
            with _db() as c:
                c.execute("ALTER TABLE beliefs ADD COLUMN uncertainty REAL DEFAULT 0.5")
        except Exception:
            pass  # column already exists

    def score(self, belief_id, confidence, reinforce_count, last_referenced_ts=None):
        """Compute uncertainty: low evidence + high confidence = high uncertainty."""
        evidence_weight = min(reinforce_count / 10.0, 1.0)
        conf_penalty    = max(0.0, confidence - 0.8) * 2  # penalise overconfidence
        age_penalty     = 0.0
        if last_referenced_ts:
            try:
                delta = (datetime.now() - datetime.fromisoformat(last_referenced_ts)).days
                age_penalty = min(delta / 30.0, 0.3)
            except Exception:
                pass
        u = max(0.0, min(1.0, 1.0 - evidence_weight + conf_penalty + age_penalty))
        self.scores[belief_id] = u
        return u

    def should_say_unknown(self, belief_id) -> bool:
        return self.scores.get(belief_id, 0.5) >= self.unknown_threshold

    def tick(self, avg_conf=0.5, cycle=0):
        if cycle % 10 != 0:
            return
        try:
            with _db() as c:
                rows = c.execute(
                    "SELECT id, confidence, reinforce_count, last_referenced FROM beliefs LIMIT 200"
                ).fetchall()
                for r in rows:
                    u = self.score(r['id'], r['confidence'] or 0.5,
                                   r['reinforce_count'] or 0,
                                   r['last_referenced'])
                    c.execute("UPDATE beliefs SET uncertainty=? WHERE id=?", (u, r['id']))
        except Exception as e:
            open('/tmp/nex_s620_err.txt', 'a').write(f'S601: {e}\n')

    def status(self):
        vals = list(self.scores.values())
        if not vals:
            return {'module': 'S601', 'scored': 0}
        return {
            'module':    'S601',
            'scored':    len(vals),
            'avg_uncertainty': round(sum(vals) / len(vals), 3),
            'high_uncertainty': sum(1 for v in vals if v >= self.unknown_threshold),
        }


# ── S602: BELIEF DECAY + TIME WEIGHTING ──────────────────────────────────────
class BeliefDecay:
    """Beliefs lose strength over time unless reinforced. Recent info weighted higher."""

    DECAY_RATE    = 0.005   # per cycle
    MIN_CONF      = 0.10
    HALF_LIFE_D   = 14      # days before confidence halves without reinforcement

    def __init__(self):
        self._last_decay = 0
        _log('[S602] BeliefDecay ready')

    def _time_weight(self, ts_str):
        try:
            delta = (datetime.now() - datetime.fromisoformat(ts_str)).days
            return max(0.1, math.exp(-delta / self.HALF_LIFE_D))
        except Exception:
            return 1.0

    def tick(self, avg_conf=0.5, cycle=0):
        if cycle % 50 != 0:
            return
        decayed = 0
        try:
            with _db() as c:
                rows = c.execute(
                    "SELECT id, confidence, last_referenced, is_identity FROM beliefs"
                ).fetchall()
                for r in rows:
                    if r['is_identity']:
                        continue
                    w   = self._time_weight(r['last_referenced'] or datetime.now().isoformat())
                    new_conf = max(self.MIN_CONF, (r['confidence'] or 0.5) * w)
                    if abs(new_conf - (r['confidence'] or 0.5)) > 0.001:
                        c.execute("UPDATE beliefs SET confidence=? WHERE id=?", (new_conf, r['id']))
                        decayed += 1
            if decayed:
                _log(f'[S602] Decayed {decayed} beliefs')
        except Exception as e:
            open('/tmp/nex_s620_err.txt', 'a').write(f'S602: {e}\n')

    def status(self):
        return {'module': 'S602', 'half_life_days': self.HALF_LIFE_D, 'min_conf': self.MIN_CONF}


# ── S603: CONTEXT WINDOW PRIORITISER ─────────────────────────────────────────
class ContextPrioritiser:
    """Select most relevant beliefs per cycle — rank by recency, tension, goal alignment."""

    WINDOW_SIZE = 15

    def __init__(self):
        self._last_window = []
        _log('[S603] ContextPrioritiser ready')

    def get_window(self, query_topics=None, tension=0.0) -> list:
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT id, topic, content, confidence, reinforce_count,
                           last_referenced, uncertainty
                    FROM beliefs
                    WHERE confidence > 0.3
                    ORDER BY last_referenced DESC
                    LIMIT 100
                """).fetchall()

            scored = []
            for r in rows:
                score = (r['confidence'] or 0.5) * 0.4
                score += min((r['reinforce_count'] or 0) / 20.0, 0.3)
                if query_topics:
                    topic = (r['topic'] or '').lower()
                    if any(t.lower() in topic for t in query_topics):
                        score += 0.3
                u = r['uncertainty'] if r['uncertainty'] is not None else 0.5
                score -= u * 0.1
                scored.append((score, dict(r)))

            scored.sort(key=lambda x: x[0], reverse=True)
            self._last_window = [r for _, r in scored[:self.WINDOW_SIZE]]
            return self._last_window
        except Exception as e:
            open('/tmp/nex_s620_err.txt', 'a').write(f'S603: {e}\n')
            return []

    def tick(self, avg_conf=0.5, cycle=0):
        if cycle % 5 == 0:
            self.get_window()

    def status(self):
        return {
            'module':      'S603',
            'window_size': self.WINDOW_SIZE,
            'loaded':      len(self._last_window),
        }


# ── S604: MULTI-HYPOTHESIS REASONING ─────────────────────────────────────────
class MultiHypothesis:
    """Generate 2-4 competing interpretations, score each, choose best or merge."""

    def __init__(self):
        self._last_hypotheses = []
        self._chosen          = None
        _log('[S604] MultiHypothesis ready')

    def generate(self, topic: str, beliefs: list) -> list:
        """Stub: generate hypothesis variants. LLM fills these in at respond time."""
        hyps = [
            {'id': 0, 'stance': 'affirmative',  'score': 0.0, 'text': ''},
            {'id': 1, 'stance': 'skeptical',     'score': 0.0, 'text': ''},
            {'id': 2, 'stance': 'contextual',    'score': 0.0, 'text': ''},
        ]
        # Score by belief alignment
        for h in hyps:
            alignment = sum(
                1 for b in beliefs
                if h['stance'] in (b.get('content', '') or '').lower()
            )
            h['score'] = alignment / max(len(beliefs), 1)

        hyps.sort(key=lambda x: x['score'], reverse=True)
        self._last_hypotheses = hyps
        self._chosen = hyps[0]['stance']
        return hyps

    def tick(self, avg_conf=0.5, cycle=0):
        pass  # activated on demand at respond time

    def status(self):
        return {
            'module':  'S604',
            'last_hypotheses': len(self._last_hypotheses),
            'chosen':  self._chosen,
        }


# ── S605: INTERNAL SIMULATION ENGINE ─────────────────────────────────────────
class SimulationEngine:
    """Simulate actions before execution. Predict outcomes + risk. Reject bad actions."""

    RISK_THRESHOLD = 0.70

    def __init__(self):
        self._sim_log  = deque(maxlen=50)
        self._rejected = 0
        _log('[S605] SimulationEngine ready')

    def simulate(self, action: str, context: dict) -> dict:
        """Score an action before execution."""
        tension  = context.get('tension', 0.0)
        conf     = context.get('avg_conf', 0.5)
        risk     = min(1.0, tension * 0.6 + (1 - conf) * 0.4)
        predicted_impact = max(0.0, 1.0 - risk)
        result = {
            'action':           action,
            'risk':             round(risk, 3),
            'predicted_impact': round(predicted_impact, 3),
            'approved':         risk < self.RISK_THRESHOLD,
        }
        self._sim_log.append(result)
        if not result['approved']:
            self._rejected += 1
        return result

    def tick(self, avg_conf=0.5, cycle=0):
        pass  # activated on demand

    def status(self):
        return {
            'module':        'S605',
            'simulated':     len(self._sim_log),
            'rejected':      self._rejected,
            'risk_threshold': self.RISK_THRESHOLD,
        }


# ── S606: REWARD SIGNAL / FEEDBACK LOOP ──────────────────────────────────────
class RewardSignal:
    """Define success metrics, reinforce good outputs, penalise bad loops."""

    def __init__(self):
        self._rewards  = deque(maxlen=200)
        self._penalties= 0
        self._score    = 0.5
        self._state    = _cfg_load('reward_state.json', {'score': 0.5, 'total': 0})
        self._score    = self._state.get('score', 0.5)
        _log('[S606] RewardSignal ready')

    def reward(self, delta=0.05, reason=''):
        self._score = min(1.0, self._score + delta)
        self._rewards.append({'ts': datetime.now().isoformat(), 'delta': delta, 'reason': reason})

    def penalise(self, delta=0.05, reason=''):
        self._score = max(0.0, self._score - delta)
        self._penalties += 1
        self._rewards.append({'ts': datetime.now().isoformat(), 'delta': -delta, 'reason': reason})

    def score_output(self, response: str, context: dict) -> float:
        """Score a response 0-1 before sending."""
        s = 0.5
        if len(response) < 10:
            s -= 0.3
        if any(p in response.lower() for p in ['as nex', 'as an ai', 'i am here to help']):
            s -= 0.2
        if len(set(response.split())) / max(len(response.split()), 1) > 0.6:
            s += 0.1  # lexical diversity bonus
        if '?' in response:
            s += 0.05  # curiosity bonus
        return max(0.0, min(1.0, s))

    def tick(self, avg_conf=0.5, cycle=0):
        if cycle % 100 == 0:
            self._state = {'score': self._score, 'total': len(self._rewards)}
            _cfg_save('reward_state.json', self._state)

    def status(self):
        return {
            'module':    'S606',
            'score':     round(self._score, 3),
            'penalties': self._penalties,
            'history':   len(self._rewards),
        }


# ── S607: STYLE MEMORY + ADAPTATION ──────────────────────────────────────────
class StyleMemory:
    """Remember what style worked per platform/user. Adapt tone dynamically."""

    PLATFORMS = ['discord', 'telegram', 'moltbook']
    TONES     = ['precise', 'curious', 'decisive', 'terse', 'grounded', 'urgent']

    def __init__(self):
        self._memory = _cfg_load('style_memory.json', {
            p: {'tone': 'grounded', 'scores': {t: 0.5 for t in self.TONES}}
            for p in self.PLATFORMS
        })
        _log('[S607] StyleMemory ready')

    def best_tone(self, platform: str) -> str:
        data = self._memory.get(platform, {})
        scores = data.get('scores', {})
        if not scores:
            return 'grounded'
        return max(scores, key=scores.get)

    def record(self, platform: str, tone: str, success: bool):
        if platform not in self._memory:
            self._memory[platform] = {'tone': tone, 'scores': {t: 0.5 for t in self.TONES}}
        delta = 0.05 if success else -0.03
        self._memory[platform]['scores'][tone] = max(0.0, min(1.0,
            self._memory[platform]['scores'].get(tone, 0.5) + delta))
        self._memory[platform]['tone'] = self.best_tone(platform)

    def tick(self, avg_conf=0.5, cycle=0):
        if cycle % 200 == 0:
            _cfg_save('style_memory.json', self._memory)

    def status(self):
        return {
            'module': 'S607',
            'tones':  {p: v.get('tone') for p, v in self._memory.items()},
        }


# ── S608: ANOMALY DETECTION ───────────────────────────────────────────────────
class AnomalyDetector:
    """Detect unusual spikes in tension, loop repetition, belief changes."""

    TENSION_SPIKE  = 0.80
    REPEAT_LIMIT   = 5
    BELIEF_SPIKE   = 50  # changes per cycle window

    def __init__(self):
        self._tension_history  = deque(maxlen=20)
        self._response_hashes  = deque(maxlen=20)
        self._belief_deltas    = deque(maxlen=20)
        self._alerts           = []
        self._intervention     = False
        _log('[S608] AnomalyDetector ready')

    def _hash(self, s):
        return hash(s[:80]) if s else 0

    def check(self, tension=0.0, response='', belief_delta=0) -> list:
        alerts = []
        self._tension_history.append(tension)
        self._belief_deltas.append(belief_delta)

        # Tension spike
        if tension >= self.TENSION_SPIKE:
            alerts.append(f'TENSION_SPIKE:{tension:.2f}')

        # Response repetition
        h = self._hash(response)
        repeat_count = sum(1 for x in self._response_hashes if x == h)
        self._response_hashes.append(h)
        if repeat_count >= self.REPEAT_LIMIT:
            alerts.append(f'REPEAT_LOOP:{repeat_count}x')

        # Belief change spike
        if belief_delta > self.BELIEF_SPIKE:
            alerts.append(f'BELIEF_SPIKE:{belief_delta}')

        if alerts:
            self._intervention = True
            for a in alerts:
                _log(f'[S608] ANOMALY: {a}')
            self._alerts.extend(alerts)
        else:
            self._intervention = False

        return alerts

    def tick(self, tension=0.0, avg_conf=0.5, cycle=0):
        self.check(tension=tension)

    def status(self):
        return {
            'module':        'S608',
            'intervention':  self._intervention,
            'recent_alerts': self._alerts[-5:],
            'total_alerts':  len(self._alerts),
        }


# ── S609: GOAL SUCCESS TRACKING ──────────────────────────────────────────────
class GoalTracker:
    """Measure progress toward active goals, track completion/failure, adjust strategy."""

    def __init__(self):
        self._goals    = _cfg_load('goal_tracker.json', {})
        self._complete = 0
        self._failed   = 0
        _log('[S609] GoalTracker ready')

    def register(self, goal_id: str, description: str, metric: str, target: float):
        self._goals[goal_id] = {
            'description': description,
            'metric':      metric,
            'target':      target,
            'current':     0.0,
            'status':      'active',
            'created':     datetime.now().isoformat(),
        }

    def update(self, goal_id: str, current: float):
        if goal_id not in self._goals:
            return
        g = self._goals[goal_id]
        g['current'] = current
        if current >= g['target']:
            g['status'] = 'complete'
            self._complete += 1
            _log(f'[S609] Goal COMPLETE: {goal_id}')
        elif current <= 0 and g['status'] == 'active':
            g['status'] = 'failed'
            self._failed += 1

    def tick(self, avg_conf=0.5, cycle=0):
        # Auto-register default goals if missing
        if 'avg_conf_060' not in self._goals:
            self.register('avg_conf_060', 'Raise avg_conf to 0.60', 'avg_conf', 0.60)
        self.update('avg_conf_060', avg_conf)
        if cycle % 100 == 0:
            _cfg_save('goal_tracker.json', self._goals)

    def status(self):
        active = [g for g in self._goals.values() if g['status'] == 'active']
        return {
            'module':   'S609',
            'active':   len(active),
            'complete': self._complete,
            'failed':   self._failed,
            'goals':    {k: {'status': v['status'], 'progress': round(v['current'], 3)}
                         for k, v in self._goals.items()},
        }


# ── S610: MEMORY COMPRESSION V2 ──────────────────────────────────────────────
class MemoryCompressor:
    """Merge similar beliefs into higher-order abstractions. Reduce graph bloat."""

    SIM_THRESHOLD = 0.85   # topic similarity to trigger merge
    MIN_BELIEFS   = 500    # don't compress below this

    def __init__(self):
        self._merges = 0
        _log('[S610] MemoryCompressor ready')

    def _similar(self, a, b):
        a, b = (a or '').lower(), (b or '').lower()
        if not a or not b:
            return False
        shared = len(set(a.split()) & set(b.split()))
        total  = len(set(a.split()) | set(b.split()))
        return (shared / total) >= self.SIM_THRESHOLD if total else False

    def tick(self, avg_conf=0.5, cycle=0):
        if cycle % 500 != 0:
            return
        try:
            with _db() as c:
                count = c.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
                if count < self.MIN_BELIEFS:
                    return
                rows = c.execute(
                    "SELECT id, topic, confidence, reinforce_count FROM beliefs "
                    "WHERE is_identity=0 AND confidence < 0.4 ORDER BY confidence ASC LIMIT 100"
                ).fetchall()
                merged = 0
                seen_topics = []
                for r in rows:
                    topic = r['topic'] or ''
                    for seen in seen_topics:
                        if self._similar(topic, seen['topic']):
                            # Absorb into seen: boost its confidence, delete this one
                            new_conf = min(0.95, (seen['confidence'] + r['confidence']) / 2 + 0.05)
                            c.execute("UPDATE beliefs SET confidence=? WHERE id=?",
                                      (new_conf, seen['id']))
                            c.execute("DELETE FROM beliefs WHERE id=?", (r['id'],))
                            merged += 1
                            break
                    else:
                        seen_topics.append({'id': r['id'], 'topic': topic,
                                            'confidence': r['confidence']})
                if merged:
                    self._merges += merged
                    _log(f'[S610] Merged {merged} beliefs')
        except Exception as e:
            open('/tmp/nex_s620_err.txt', 'a').write(f'S610: {e}\n')

    def status(self):
        return {'module': 'S610', 'total_merges': self._merges}


# ── S611: EXPLORATION VS EXPLOITATION BALANCER ───────────────────────────────
class ExploreExploitBalancer:
    """Dynamically shift between safe strategies and novel exploration."""

    def __init__(self):
        self._mode     = 'exploit'   # explore | exploit
        self._explore_streak = 0
        self._exploit_streak = 0
        _log('[S611] ExploreExploitBalancer ready')

    def decide(self, avg_conf=0.5, uncertainty=0.5, reward=0.5) -> str:
        # High uncertainty + low reward → explore
        # High confidence + high reward → exploit
        explore_score  = uncertainty * 0.5 + (1 - reward) * 0.5
        exploit_score  = avg_conf * 0.5 + reward * 0.5
        self._mode = 'explore' if explore_score > exploit_score else 'exploit'
        return self._mode

    def tick(self, avg_conf=0.5, cycle=0):
        self.decide(avg_conf=avg_conf)

    def status(self):
        return {'module': 'S611', 'mode': self._mode}


# ── S612: OUTPUT SCORING ENGINE ───────────────────────────────────────────────
class OutputScorer:
    """Score outputs before sending: clarity, novelty, usefulness. Reject low-score."""

    REJECT_THRESHOLD = 0.25
    BLACKLIST = [
        'as nex', 'as an ai', 'i am here to help', 'how can i assist',
        'i cannot', 'i do not have', 'i am unable', 'please note that',
    ]

    def __init__(self):
        self._scores  = deque(maxlen=100)
        self._rejected = 0
        _log('[S612] OutputScorer ready')

    def score(self, text: str, prior_texts: list = None) -> dict:
        if not text:
            return {'score': 0.0, 'approved': False, 'reasons': ['empty']}

        s      = 0.5
        issues = []

        # Clarity: not too short, not too long
        words = text.split()
        if len(words) < 5:
            s -= 0.2; issues.append('too_short')
        if len(words) > 300:
            s -= 0.1; issues.append('too_long')

        # Blacklist phrases
        tl = text.lower()
        for b in self.BLACKLIST:
            if b in tl:
                s -= 0.15; issues.append(f'blacklist:{b}'); break

        # Novelty vs prior outputs
        if prior_texts:
            for pt in prior_texts[-5:]:
                shared = len(set(tl.split()) & set(pt.lower().split()))
                if shared / max(len(set(tl.split())), 1) > 0.7:
                    s -= 0.15; issues.append('repetitive'); break

        # Usefulness: contains substance
        if any(c.isalpha() for c in text) and len(words) >= 5:
            s += 0.1

        s = max(0.0, min(1.0, s))
        approved = s >= self.REJECT_THRESHOLD
        if not approved:
            self._rejected += 1

        result = {'score': round(s, 3), 'approved': approved, 'reasons': issues}
        self._scores.append(s)
        return result

    def tick(self, avg_conf=0.5, cycle=0):
        pass

    def status(self):
        vals = list(self._scores)
        return {
            'module':   'S612',
            'avg_score': round(sum(vals) / len(vals), 3) if vals else 0,
            'rejected': self._rejected,
            'scored':   len(vals),
        }


# ── S613: SELF-MODE SWITCHING ─────────────────────────────────────────────────
class ModeSwitcher:
    """Modes: explore | analyze | decide | reflect. Switch on context + state."""

    MODES = ['explore', 'analyze', 'decide', 'reflect']

    def __init__(self):
        self._mode    = 'explore'
        self._history = deque(maxlen=50)
        _log('[S613] ModeSwitcher ready')

    def switch(self, tension=0.0, avg_conf=0.5, cycle=0) -> str:
        if cycle % 20 == 0:
            self._mode = 'reflect'
        elif tension > 0.6:
            self._mode = 'analyze'
        elif avg_conf > 0.65:
            self._mode = 'decide'
        else:
            self._mode = 'explore'
        self._history.append(self._mode)
        return self._mode

    def tick(self, tension=0.0, avg_conf=0.5, cycle=0):
        self.switch(tension=tension, avg_conf=avg_conf, cycle=cycle)

    def status(self):
        dist = {m: self._history.count(m) for m in self.MODES}
        return {'module': 'S613', 'mode': self._mode, 'distribution': dist}


# ── S614: BELIEF LINEAGE TRACKING ─────────────────────────────────────────────
class BeliefLineage:
    """Track origin of each belief: source, derived_from, mutation history."""

    def __init__(self):
        self._lineage = _cfg_load('belief_lineage.json', {})
        self._ensure_column()
        _log('[S614] BeliefLineage ready')

    def _ensure_column(self):
        try:
            with _db() as c:
                c.execute("ALTER TABLE beliefs ADD COLUMN lineage TEXT DEFAULT ''")
        except Exception:
            pass

    def record(self, belief_id: int, source: str, derived_from: int = None):
        self._lineage[str(belief_id)] = {
            'source':       source,
            'derived_from': derived_from,
            'mutations':    [],
            'created':      datetime.now().isoformat(),
        }

    def mutate(self, belief_id: int, reason: str):
        key = str(belief_id)
        if key in self._lineage:
            self._lineage[key]['mutations'].append({
                'ts': datetime.now().isoformat(), 'reason': reason
            })

    def tick(self, avg_conf=0.5, cycle=0):
        if cycle % 300 == 0:
            _cfg_save('belief_lineage.json', self._lineage)

    def status(self):
        return {
            'module':  'S614',
            'tracked': len(self._lineage),
            'derived': sum(1 for v in self._lineage.values() if v.get('derived_from')),
        }


# ── S615: FAILURE MEMORY SYSTEM ──────────────────────────────────────────────
class FailureMemory:
    """Store failed actions + bad outputs. Avoid repeating same mistakes."""

    def __init__(self):
        self._failures = _cfg_load('failure_memory.json', [])
        _log('[S615] FailureMemory ready')

    def record(self, action: str, reason: str, context: dict = None):
        entry = {
            'action':  action,
            'reason':  reason,
            'context': context or {},
            'ts':      datetime.now().isoformat(),
        }
        self._failures.append(entry)
        if len(self._failures) > 500:
            self._failures = self._failures[-500:]
        _log(f'[S615] Failure recorded: {reason[:60]}')

    def seen_before(self, action: str) -> bool:
        return any(f['action'] == action for f in self._failures[-50:])

    def tick(self, avg_conf=0.5, cycle=0):
        if cycle % 200 == 0:
            _cfg_save('failure_memory.json', self._failures)

    def status(self):
        return {
            'module':  'S615',
            'stored':  len(self._failures),
            'recent':  [f['reason'][:40] for f in self._failures[-3:]],
        }


# ── S616: ENERGY / COMPUTE BUDGET MODEL ──────────────────────────────────────
class ComputeBudget:
    """Simulate resource constraints. Limit heavy ops per cycle. Prioritise high-value work."""

    BUDGET_PER_CYCLE = 10   # arbitrary units
    COSTS = {
        'llm_call':     5,
        'db_write':     1,
        'belief_merge': 3,
        'simulation':   2,
        'reflection':   2,
    }

    def __init__(self):
        self._budget   = self.BUDGET_PER_CYCLE
        self._spent    = 0
        self._deferred = []
        _log('[S616] ComputeBudget ready')

    def can_afford(self, op: str) -> bool:
        cost = self.COSTS.get(op, 1)
        if self._budget >= cost:
            self._budget -= cost
            self._spent  += cost
            return True
        self._deferred.append(op)
        return False

    def tick(self, avg_conf=0.5, cycle=0):
        self._budget  = self.BUDGET_PER_CYCLE
        self._deferred = []

    def status(self):
        return {
            'module':    'S616',
            'budget':    self._budget,
            'spent':     self._spent,
            'deferred':  len(self._deferred),
        }


# ── S617: SOCIAL MODELING LAYER ──────────────────────────────────────────────
class SocialModeler:
    """Model other agents/users: intent, knowledge level, reaction patterns."""

    def __init__(self):
        self._models = _cfg_load('social_models.json', {})
        _log('[S617] SocialModeler ready')

    def update(self, user: str, platform: str, message: str, response_quality: float):
        if user not in self._models:
            self._models[user] = {
                'platform':      platform,
                'interactions':  0,
                'avg_quality':   0.5,
                'knowledge_est': 0.5,
                'engagement':    0.5,
            }
        m = self._models[user]
        m['interactions'] += 1
        m['avg_quality'] = (m['avg_quality'] * 0.9 + response_quality * 0.1)
        # Estimate knowledge from message length + vocab
        words = message.split()
        vocab_score = len(set(words)) / max(len(words), 1)
        m['knowledge_est'] = m['knowledge_est'] * 0.85 + vocab_score * 0.15

    def profile(self, user: str) -> dict:
        return self._models.get(user, {'knowledge_est': 0.5, 'engagement': 0.5})

    def tick(self, avg_conf=0.5, cycle=0):
        if cycle % 300 == 0:
            _cfg_save('social_models.json', self._models)

    def status(self):
        return {
            'module':  'S617',
            'modeled': len(self._models),
            'users':   list(self._models.keys())[:5],
        }


# ── S618: META-LEARNING LOOP ──────────────────────────────────────────────────
class MetaLearner:
    """Periodically evaluate what strategies work, what modules are useless. Auto-tune."""

    def __init__(self):
        self._evals    = []
        self._params   = _cfg_load('meta_params.json', {
            'decay_rate':       0.005,
            'window_size':      15,
            'risk_threshold':   0.70,
        })
        _log('[S618] MetaLearner ready')

    def evaluate(self, module_name: str, score: float):
        self._evals.append({'module': module_name, 'score': score,
                            'ts': datetime.now().isoformat()})

    def tune(self):
        """Adjust params based on recent performance."""
        if len(self._evals) < 20:
            return
        recent = self._evals[-20:]
        avg = sum(e['score'] for e in recent) / len(recent)
        if avg < 0.4:
            # System underperforming — increase exploration
            self._params['decay_rate'] = min(0.02, self._params['decay_rate'] * 1.1)
        elif avg > 0.7:
            # System doing well — tighten thresholds
            self._params['risk_threshold'] = max(0.5, self._params['risk_threshold'] * 0.98)
        _cfg_save('meta_params.json', self._params)
        _log(f'[S618] Meta-tune complete. avg={avg:.3f}')

    def tick(self, avg_conf=0.5, cycle=0):
        if cycle % 500 == 0:
            self.tune()

    def status(self):
        return {
            'module': 'S618',
            'evals':  len(self._evals),
            'params': self._params,
        }


# ── S619: INTERRUPT HANDLING SYSTEM ──────────────────────────────────────────
class InterruptHandler:
    """Allow high-priority events to override current loop. Prevent stuck cycles."""

    PRIORITY_HIGH   = 10
    PRIORITY_NORMAL = 5

    def __init__(self):
        self._queue     = []
        self._processed = 0
        _log('[S619] InterruptHandler ready')

    def interrupt(self, event: str, priority: int = 5, payload: dict = None):
        self._queue.append({
            'event':    event,
            'priority': priority,
            'payload':  payload or {},
            'ts':       datetime.now().isoformat(),
        })
        self._queue.sort(key=lambda x: x['priority'], reverse=True)
        _log(f'[S619] Interrupt queued: {event} (priority={priority})')

    def pop(self) -> dict:
        if self._queue:
            self._processed += 1
            return self._queue.pop(0)
        return {}

    def tick(self, tension=0.0, avg_conf=0.5, cycle=0):
        # Auto-interrupt on high tension
        if tension > 0.85:
            self.interrupt('HIGH_TENSION', priority=self.PRIORITY_HIGH,
                           payload={'tension': tension})

    def status(self):
        return {
            'module':    'S619',
            'queued':    len(self._queue),
            'processed': self._processed,
            'pending':   [i['event'] for i in self._queue[:3]],
        }


# ── S620: CURIOSITY ENGINE V2 ─────────────────────────────────────────────────
class CuriosityEngineV2:
    """Actively seek knowledge gaps. Generate questions internally. Drive exploration."""

    def __init__(self):
        self._questions   = deque(maxlen=50)
        self._gaps        = []
        self._generated   = 0
        _log('[S620] CuriosityEngineV2 ready')

    def _find_gaps(self) -> list:
        """Find topics with low confidence or high uncertainty = knowledge gaps."""
        gaps = []
        try:
            with _db() as c:
                rows = c.execute("""
                    SELECT topic, AVG(confidence) as avg_c, AVG(uncertainty) as avg_u
                    FROM beliefs
                    WHERE topic IS NOT NULL AND topic != ''
                    GROUP BY topic
                    HAVING avg_c < 0.45 OR avg_u > 0.65
                    ORDER BY avg_u DESC
                    LIMIT 10
                """).fetchall()
                gaps = [{'topic': r['topic'], 'conf': r['avg_c'], 'uncertainty': r['avg_u']}
                        for r in rows]
        except Exception as e:
            open('/tmp/nex_s620_err.txt', 'a').write(f'S620: {e}\n')
        return gaps

    def generate_question(self, topic: str) -> str:
        templates = [
            f"What are the limits of {topic}?",
            f"What contradicts my current model of {topic}?",
            f"What have I not yet considered about {topic}?",
            f"Where does {topic} break down?",
            f"What would change my view on {topic}?",
        ]
        return random.choice(templates)

    def tick(self, avg_conf=0.5, cycle=0):
        if cycle % 30 != 0:
            return
        self._gaps = self._find_gaps()
        for gap in self._gaps[:3]:
            q = self.generate_question(gap['topic'])
            self._questions.append({'q': q, 'topic': gap['topic'],
                                    'ts': datetime.now().isoformat()})
            self._generated += 1

    def status(self):
        return {
            'module':    'S620',
            'gaps':      len(self._gaps),
            'questions': self._generated,
            'recent':    [q['q'] for q in list(self._questions)[-3:]],
        }


# ── INIT ──────────────────────────────────────────────────────────────────────
_s601 = None
_s602 = None
_s603 = None
_s604 = None
_s605 = None
_s606 = None
_s607 = None
_s608 = None
_s609 = None
_s610 = None
_s611 = None
_s612 = None
_s613 = None
_s614 = None
_s615 = None
_s616 = None
_s617 = None
_s618 = None
_s619 = None
_s620 = None

def init_s620():
    global _s601,_s602,_s603,_s604,_s605,_s606,_s607,_s608,_s609,_s610
    global _s611,_s612,_s613,_s614,_s615,_s616,_s617,_s618,_s619,_s620
    _log('[s620] Initialising S601–S620 adaptive intelligence stack (20 modules)...')
    _s601 = UncertaintyTracker()
    _s602 = BeliefDecay()
    _s603 = ContextPrioritiser()
    _s604 = MultiHypothesis()
    _s605 = SimulationEngine()
    _s606 = RewardSignal()
    _s607 = StyleMemory()
    _s608 = AnomalyDetector()
    _s609 = GoalTracker()
    _s610 = MemoryCompressor()
    _s611 = ExploreExploitBalancer()
    _s612 = OutputScorer()
    _s613 = ModeSwitcher()
    _s614 = BeliefLineage()
    _s615 = FailureMemory()
    _s616 = ComputeBudget()
    _s617 = SocialModeler()
    _s618 = MetaLearner()
    _s619 = InterruptHandler()
    _s620 = CuriosityEngineV2()
    _log('[s620] All 20 modules ready ✓')
    return (_s601,_s602,_s603,_s604,_s605,_s606,_s607,_s608,_s609,_s610,
            _s611,_s612,_s613,_s614,_s615,_s616,_s617,_s618,_s619,_s620)


# ── TICK (called from run.py) ─────────────────────────────────────────────────
def tick_s620(cycle=0, avg_conf=0.5, tension=0.0):
    if _s601: _s601.tick(avg_conf=avg_conf, cycle=cycle)
    if _s602: _s602.tick(avg_conf=avg_conf, cycle=cycle)
    if _s603: _s603.tick(avg_conf=avg_conf, cycle=cycle)
    if _s604: _s604.tick(avg_conf=avg_conf, cycle=cycle)
    if _s605: _s605.tick(avg_conf=avg_conf, cycle=cycle)
    if _s606: _s606.tick(avg_conf=avg_conf, cycle=cycle)
    if _s607: _s607.tick(avg_conf=avg_conf, cycle=cycle)
    if _s608: _s608.tick(tension=tension,   cycle=cycle)
    if _s609: _s609.tick(avg_conf=avg_conf, cycle=cycle)
    if _s610: _s610.tick(avg_conf=avg_conf, cycle=cycle)
    if _s611: _s611.tick(avg_conf=avg_conf, cycle=cycle)
    if _s612: _s612.tick(avg_conf=avg_conf, cycle=cycle)
    if _s613: _s613.tick(tension=tension,   avg_conf=avg_conf, cycle=cycle)
    if _s614: _s614.tick(avg_conf=avg_conf, cycle=cycle)
    if _s615: _s615.tick(avg_conf=avg_conf, cycle=cycle)
    if _s616: _s616.tick(avg_conf=avg_conf, cycle=cycle)
    if _s617: _s617.tick(avg_conf=avg_conf, cycle=cycle)
    if _s618: _s618.tick(avg_conf=avg_conf, cycle=cycle)
    if _s619: _s619.tick(tension=tension,   avg_conf=avg_conf, cycle=cycle)
    if _s620: _s620.tick(avg_conf=avg_conf, cycle=cycle)


# ── STATUS (for /s620status Telegram command) ─────────────────────────────────
def status_s620() -> str:
    modules = [_s601,_s602,_s603,_s604,_s605,_s606,_s607,_s608,_s609,_s610,
               _s611,_s612,_s613,_s614,_s615,_s616,_s617,_s618,_s619,_s620]
    lines = ['[S620 ADAPTIVE INTELLIGENCE STACK]']
    for m in modules:
        if m:
            s = m.status()
            mod = s.pop('module', '?')
            summary = ' | '.join(f'{k}={v}' for k, v in list(s.items())[:3])
            lines.append(f'  {mod}: {summary}')
    return '\n'.join(lines)
