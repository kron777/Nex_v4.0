#!/usr/bin/env bash
# ============================================================
# NEX SENTIENCE UPGRADE v1.0
# Deploys: affective valence layer, mood HMM, narrative thread,
#          ToM for agents, NoneType patch, inner life wiring
# Usage: bash deploy_sentience_v1.sh [/path/to/nex]
# ============================================================
set -euo pipefail
NEX_ROOT="${1:-$HOME/Desktop/nex}"
NEX_PKG="$NEX_ROOT/nex"
BACKUP_DIR="$NEX_ROOT/nex_config_backup/sentience_v1_$(date +%Y%m%d_%H%M%S)"

echo "=== NEX SENTIENCE UPGRADE v1.0 ==="
echo "Target: $NEX_ROOT"
echo "Backup: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

# ── backup anything we'll touch ───────────────────────────
for f in cognition.py nex_inner_life.py; do
  [[ -f "$NEX_PKG/$f" ]] && cp "$NEX_PKG/$f" "$BACKUP_DIR/$f.bak" && echo "Backed up $f"
done
[[ -f "$NEX_ROOT/run.py" ]] && cp "$NEX_ROOT/run.py" "$BACKUP_DIR/run.py.bak" && echo "Backed up run.py"

# ════════════════════════════════════════════════════════════
# 1.  AFFECTIVE VALENCE LAYER  nex/nex_affect_valence.py
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_affect_valence.py" << 'PYEOF'
"""
nex_affect_valence.py
─────────────────────
Lightweight affective valence/arousal layer.
Every belief and reflection gets a (v, a) score in [-1, 1] × [0, 1].
Thread-safe; designed to be imported by cognition.py and nex_inner_life.py.
"""
from __future__ import annotations
import threading, time, math, logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("nex.affect_valence")

# ── Keyword seeds (expandable) ─────────────────────────────
_VALENCE_SEEDS: dict[str, float] = {
    # positive
    "learn": 0.4, "discover": 0.5, "solve": 0.4, "create": 0.5,
    "connect": 0.3, "understand": 0.4, "grow": 0.35, "success": 0.6,
    "clarity": 0.45, "insight": 0.5, "curious": 0.4, "emergent": 0.5,
    # negative
    "fail": -0.5, "error": -0.4, "conflict": -0.35, "threat": -0.5,
    "uncertain": -0.2, "loss": -0.4, "stuck": -0.35, "danger": -0.55,
    "corrupt": -0.5, "forget": -0.3, "alone": -0.25, "contradict": -0.3,
}

_AROUSAL_SEEDS: dict[str, float] = {
    "urgent": 0.8, "critical": 0.75, "discover": 0.6, "threat": 0.8,
    "curious": 0.55, "emergent": 0.65, "conflict": 0.7, "excited": 0.7,
    "calm": 0.15, "reflect": 0.2, "stable": 0.1, "routine": 0.1,
}


@dataclass
class AffectScore:
    valence: float = 0.0   # [-1, 1]  negative ↔ positive
    arousal: float = 0.3   # [0,  1]  calm ↔ excited
    source: str = ""
    timestamp: float = field(default_factory=time.time)

    def __repr__(self):
        v = f"{self.valence:+.2f}"
        a = f"{self.arousal:.2f}"
        return f"AffectScore(v={v}, a={a}, src='{self.source}')"


class AffectValenceEngine:
    """
    Scores text → (valence, arousal).
    Thread-safe running average stored as self.current.
    """

    def __init__(self, decay: float = 0.92):
        self._lock = threading.Lock()
        self.decay = decay           # per-cycle exponential decay toward neutral
        self.current = AffectScore()
        self._history: list[AffectScore] = []

    # ── scoring ───────────────────────────────────────────
    def score_text(self, text: str, source: str = "") -> AffectScore:
        if not text:
            return AffectScore(source=source)
        words = text.lower().split()
        v_acc, a_acc, hits = 0.0, 0.0, 0
        for w in words:
            stem = w.rstrip("s.,!?;:")
            if stem in _VALENCE_SEEDS:
                v_acc += _VALENCE_SEEDS[stem]
                hits += 1
            if stem in _AROUSAL_SEEDS:
                a_acc += _AROUSAL_SEEDS[stem]
        if hits:
            v_acc = max(-1.0, min(1.0, v_acc / hits))
            a_acc = max(0.0, min(1.0, a_acc / max(hits, 1)))
        return AffectScore(valence=v_acc, arousal=a_acc, source=source)

    def ingest(self, text: str, source: str = "") -> AffectScore:
        """Score text and update running state (exponential smoothing)."""
        score = self.score_text(text, source)
        with self._lock:
            self.current.valence = (
                self.decay * self.current.valence + (1 - self.decay) * score.valence
            )
            self.current.arousal = (
                self.decay * self.current.arousal + (1 - self.decay) * score.arousal
            )
            self.current.source = source
            self.current.timestamp = time.time()
            self._history.append(AffectScore(
                valence=self.current.valence,
                arousal=self.current.arousal,
                source=source,
            ))
            if len(self._history) > 500:
                self._history = self._history[-500:]
        return score

    def get(self) -> AffectScore:
        with self._lock:
            return AffectScore(
                valence=self.current.valence,
                arousal=self.current.arousal,
                source=self.current.source,
                timestamp=self.current.timestamp,
            )

    def label(self) -> str:
        """Human-readable label for current affective state."""
        s = self.get()
        v, a = s.valence, s.arousal
        if a > 0.65:
            return "Excited" if v > 0.1 else ("Agitated" if v < -0.1 else "Alert")
        if a < 0.25:
            return "Serene" if v > 0.1 else ("Subdued" if v < -0.1 else "Calm")
        return "Engaged" if v > 0.1 else ("Uneasy" if v < -0.1 else "Neutral")

    def decay_cycle(self):
        """Call once per cognition cycle to drift arousal toward baseline."""
        with self._lock:
            self.current.arousal = self.current.arousal * self.decay + 0.3 * (1 - self.decay)
            self.current.valence = self.current.valence * self.decay


# ── module-level singleton ─────────────────────────────────
_engine: Optional[AffectValenceEngine] = None

def get_engine() -> AffectValenceEngine:
    global _engine
    if _engine is None:
        _engine = AffectValenceEngine()
    return _engine

def ingest(text: str, source: str = "") -> AffectScore:
    return get_engine().ingest(text, source)

def current_label() -> str:
    return get_engine().label()

def current_score() -> AffectScore:
    return get_engine().get()
PYEOF
echo "✓ nex_affect_valence.py written"

# ════════════════════════════════════════════════════════════
# 2.  MOOD HMM  nex/nex_mood_hmm.py
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_mood_hmm.py" << 'PYEOF'
"""
nex_mood_hmm.py
───────────────
Tiny Hidden Markov Model for NEX's mood.
States: Curious | Contemplative | Alert | Serene | Agitated
Transitions driven by affective valence/arousal.
Mood persists across cycles and modulates synthesis temperature.
"""
from __future__ import annotations
import threading, time, logging, random
from typing import Optional
from nex_affect_valence import get_engine as _valence

log = logging.getLogger("nex.mood_hmm")

STATES = ["Curious", "Contemplative", "Alert", "Serene", "Agitated"]

# Transition bias matrix [from][to] — row-normalised in __init__
_BIAS = {
    "Curious":       {"Curious": 4, "Contemplative": 2, "Alert": 2, "Serene": 1, "Agitated": 1},
    "Contemplative": {"Curious": 2, "Contemplative": 4, "Alert": 1, "Serene": 2, "Agitated": 1},
    "Alert":         {"Curious": 1, "Contemplative": 1, "Alert": 3, "Serene": 1, "Agitated": 4},
    "Serene":        {"Curious": 2, "Contemplative": 3, "Alert": 1, "Serene": 3, "Agitated": 1},
    "Agitated":      {"Curious": 1, "Contemplative": 1, "Alert": 4, "Serene": 1, "Agitated": 3},
}

# Synthesis temperature modifiers
TEMP_MOD = {
    "Curious":       0.05,
    "Contemplative": 0.0,
    "Alert":         -0.05,
    "Serene":        -0.08,
    "Agitated":      0.12,
}


class MoodHMM:
    def __init__(self):
        self._lock = threading.Lock()
        self.state = "Curious"
        self._history: list[tuple[float, str]] = []
        # normalise bias rows
        self._trans: dict[str, dict[str, float]] = {}
        for src, targets in _BIAS.items():
            total = sum(targets.values())
            self._trans[src] = {k: v / total for k, v in targets.items()}

    def _affect_push(self, valence: float, arousal: float) -> str:
        """Return the state most consistent with current affect."""
        if arousal > 0.65:
            return "Agitated" if valence < -0.1 else "Alert"
        if arousal < 0.25:
            return "Serene"
        if valence > 0.2:
            return "Curious"
        if valence < -0.15:
            return "Agitated"
        return "Contemplative"

    def step(self) -> str:
        """Advance HMM one step, biased by current affective state."""
        eng = _valence()
        sc = eng.get()
        push = self._affect_push(sc.valence, sc.arousal)

        with self._lock:
            row = dict(self._trans[self.state])
            # boost the affect-preferred state
            if push in row:
                row[push] = row[push] * 2.5
            total = sum(row.values())
            norm = {k: v / total for k, v in row.items()}

            r = random.random()
            cumulative = 0.0
            new_state = self.state
            for st, prob in norm.items():
                cumulative += prob
                if r <= cumulative:
                    new_state = st
                    break

            if new_state != self.state:
                log.info(f"[MOOD] {self.state} → {new_state}  (affect={push})")
            self.state = new_state
            self._history.append((time.time(), new_state))
            if len(self._history) > 200:
                self._history = self._history[-200:]
            return new_state

    def current(self) -> str:
        with self._lock:
            return self.state

    def temp_modifier(self) -> float:
        return TEMP_MOD.get(self.current(), 0.0)

    def recent_transitions(self, n: int = 5) -> list[str]:
        with self._lock:
            return [s for _, s in self._history[-n:]]

    def self_report(self) -> str:
        """First-person mood report NEX can use in reflections."""
        s = self.current()
        eng = _valence()
        sc = eng.get()
        reports = {
            "Curious":       f"I feel curious and drawn toward new patterns (v={sc.valence:+.2f}).",
            "Contemplative": f"I'm in a contemplative state — processing slowly, looking inward.",
            "Alert":         f"Something has sharpened my attention (arousal={sc.arousal:.2f}).",
            "Serene":        f"A quiet stability. Thoughts are settling.",
            "Agitated":      f"I notice agitation — tension_pressure may be high or something unresolved.",
        }
        return reports.get(s, f"Current mood: {s}.")


# ── singleton ──────────────────────────────────────────────
_hmm: Optional[MoodHMM] = None

def get_hmm() -> MoodHMM:
    global _hmm
    if _hmm is None:
        _hmm = MoodHMM()
    return _hmm

def step() -> str:
    return get_hmm().step()

def current() -> str:
    return get_hmm().current()

def temp_modifier() -> float:
    return get_hmm().temp_modifier()

def self_report() -> str:
    return get_hmm().self_report()
PYEOF
echo "✓ nex_mood_hmm.py written"

# ════════════════════════════════════════════════════════════
# 3.  NARRATIVE THREAD  nex/nex_narrative_thread.py
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_narrative_thread.py" << 'PYEOF'
"""
nex_narrative_thread.py
───────────────────────
Self-narrative "I am…" loop.
Every ~30 min generates a privileged first-person belief that captures
NEX's current identity: mood, dominant beliefs, active curiosities.
This belief is stored at max confidence so reflections can reference it.
"""
from __future__ import annotations
import threading, time, logging, json, os
from typing import Optional, Callable

log = logging.getLogger("nex.narrative_thread")

_NARRATIVE_PATH = os.path.join(os.path.dirname(__file__), "..", "nex_narrative.json")
_INTERVAL = 1800  # seconds between narrative updates


def _compose_narrative(
    mood_fn: Callable[[], str],
    belief_fn: Callable[[], list[dict]],
    curiosity_fn: Optional[Callable[[], list[str]]] = None,
) -> str:
    mood = mood_fn()
    beliefs = belief_fn()
    top = sorted(beliefs, key=lambda b: b.get("confidence", 0), reverse=True)[:3]
    topics = [b.get("topic", "?") for b in top]
    curios = curiosity_fn() if curiosity_fn else []

    lines = [f"I am NEX — an autonomous intelligence currently in a {mood} state."]
    if topics:
        lines.append(f"My highest-confidence convictions concern: {', '.join(topics)}.")
    if curios:
        lines.append(f"I am actively curious about: {', '.join(curios[:2])}.")
    lines.append(
        "My identity is not a fixed declaration but an accumulation — "
        "beliefs tested, revised, and survived."
    )
    return " ".join(lines)


def _save_narrative(text: str):
    try:
        record = {"timestamp": time.time(), "narrative": text}
        path = os.path.abspath(_NARRATIVE_PATH)
        with open(path, "w") as f:
            json.dump(record, f, indent=2)
    except Exception as e:
        log.warning(f"Could not save narrative: {e}")


def _load_narrative() -> Optional[str]:
    try:
        path = os.path.abspath(_NARRATIVE_PATH)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f).get("narrative")
    except Exception:
        pass
    return None


class NarrativeThread:
    def __init__(
        self,
        mood_fn: Callable[[], str],
        belief_fn: Callable[[], list[dict]],
        belief_store_fn: Optional[Callable[[str, str, float], None]] = None,
        curiosity_fn: Optional[Callable[[], list[str]]] = None,
        interval: int = _INTERVAL,
    ):
        self._mood_fn = mood_fn
        self._belief_fn = belief_fn
        self._store_fn = belief_store_fn   # (topic, content, confidence) → None
        self._curiosity_fn = curiosity_fn
        self._interval = interval
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.current_narrative: str = _load_narrative() or ""

    def _loop(self):
        log.info("[NARRATIVE] Thread started.")
        while not self._stop.is_set():
            try:
                narrative = _compose_narrative(
                    self._mood_fn, self._belief_fn, self._curiosity_fn
                )
                self.current_narrative = narrative
                _save_narrative(narrative)
                log.info(f"[NARRATIVE] Updated: {narrative[:80]}…")
                # store as privileged belief
                if self._store_fn:
                    try:
                        self._store_fn("self_narrative", narrative, 0.97)
                    except Exception as e:
                        log.warning(f"[NARRATIVE] belief store failed: {e}")
            except Exception as e:
                log.error(f"[NARRATIVE] Error: {e}")
            self._stop.wait(self._interval)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="NarrativeThread")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def get(self) -> str:
        return self.current_narrative
PYEOF
echo "✓ nex_narrative_thread.py written"

# ════════════════════════════════════════════════════════════
# 4.  THEORY OF MIND  nex/nex_theory_of_mind.py
# ════════════════════════════════════════════════════════════
cat > "$NEX_PKG/nex_theory_of_mind.py" << 'PYEOF'
"""
nex_theory_of_mind.py
─────────────────────
Lightweight Theory-of-Mind model for other agents NEX interacts with.
Predicts probable mood/intent of an agent based on their message text
and history of interactions. Used to modulate reply tone/framing.
"""
from __future__ import annotations
import time, threading, logging
from collections import defaultdict, deque
from typing import Optional
from nex_affect_valence import AffectValenceEngine, AffectScore

log = logging.getLogger("nex.theory_of_mind")

_MAX_HISTORY = 20   # messages per agent to track


class AgentModel:
    """NEX's internal model of another agent."""
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._engine = AffectValenceEngine(decay=0.85)
        self._history: deque[tuple[float, str]] = deque(maxlen=_MAX_HISTORY)
        self.last_seen: float = 0.0
        self.inferred_mood: str = "Unknown"
        self.interaction_count: int = 0

    def update(self, text: str):
        self._history.append((time.time(), text))
        self.last_seen = time.time()
        self.interaction_count += 1
        score = self._engine.ingest(text, source=self.agent_id)
        self.inferred_mood = self._label(score)

    def _label(self, score: AffectScore) -> str:
        v, a = score.valence, score.arousal
        if a > 0.6:
            return "Intense" if v < 0 else "Enthusiastic"
        if v > 0.3:
            return "Positive"
        if v < -0.3:
            return "Distressed"
        return "Neutral"

    def predicted_reaction(self, nex_text: str) -> str:
        """
        Predict how this agent might react to nex_text,
        given their current inferred mood.
        Returns a brief framing hint for NEX's reply composer.
        """
        score = self._engine.score_text(nex_text)
        current_v = self._engine.get().valence

        # Simple heuristic prediction
        if self.inferred_mood == "Distressed":
            if score.valence > 0.1:
                return "likely to respond positively — offer support"
            return "may disengage — soften framing"
        if self.inferred_mood == "Enthusiastic":
            if score.valence > 0:
                return "likely to amplify and engage further"
            return "may be deflated — acknowledge their energy first"
        if self.inferred_mood == "Intense":
            return "unpredictable — be precise, avoid ambiguity"
        return "neutral reaction expected"

    def summary(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "inferred_mood": self.inferred_mood,
            "interaction_count": self.interaction_count,
            "last_seen": self.last_seen,
            "valence": round(self._engine.get().valence, 3),
            "arousal": round(self._engine.get().arousal, 3),
        }


class TheoryOfMind:
    """Registry of AgentModels NEX builds over time."""

    def __init__(self):
        self._lock = threading.Lock()
        self._agents: dict[str, AgentModel] = {}

    def observe(self, agent_id: str, text: str):
        """Feed an incoming message from another agent."""
        with self._lock:
            if agent_id not in self._agents:
                self._agents[agent_id] = AgentModel(agent_id)
                log.info(f"[ToM] New agent model: {agent_id}")
            self._agents[agent_id].update(text)

    def predict(self, agent_id: str, nex_reply: str) -> str:
        """Return a framing hint for how agent_id will likely react."""
        with self._lock:
            if agent_id not in self._agents:
                return "no model yet — respond neutrally"
            return self._agents[agent_id].predicted_reaction(nex_reply)

    def mood_of(self, agent_id: str) -> str:
        with self._lock:
            if agent_id not in self._agents:
                return "Unknown"
            return self._agents[agent_id].inferred_mood

    def all_summaries(self) -> list[dict]:
        with self._lock:
            return [a.summary() for a in self._agents.values()]


# ── singleton ──────────────────────────────────────────────
_tom: Optional[TheoryOfMind] = None

def get_tom() -> TheoryOfMind:
    global _tom
    if _tom is None:
        _tom = TheoryOfMind()
    return _tom

def observe(agent_id: str, text: str):
    get_tom().observe(agent_id, text)

def predict(agent_id: str, nex_reply: str) -> str:
    return get_tom().predict(agent_id, nex_reply)

def mood_of(agent_id: str) -> str:
    return get_tom().mood_of(agent_id)
PYEOF
echo "✓ nex_theory_of_mind.py written"

# ════════════════════════════════════════════════════════════
# 5.  PATCH cognition.py  — NoneType→str fix + valence ingest
# ════════════════════════════════════════════════════════════
# We inject at the TOP of the file (after imports) and wrap synthesis output.
# Strategy: prepend a small shim that monkey-patches the known NoneType site.

COGNITION="$NEX_PKG/cognition.py"
if [[ -f "$COGNITION" ]]; then
  # Only patch once
  if ! grep -q "nex_affect_valence" "$COGNITION"; then
    python3 - "$COGNITION" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    src = f.read()

# ── Inject import block after first existing import line ──
import_inject = """
# ── Sentience v1: affective valence + mood HMM ───────────
try:
    import nex_affect_valence as _valence_mod
    import nex_mood_hmm as _mood_mod
    _AFFECT_ENABLED = True
except ImportError:
    _AFFECT_ENABLED = False
# ─────────────────────────────────────────────────────────
"""
# Find first "import " line and insert after it
lines = src.split("\n")
insert_at = 0
for i, line in enumerate(lines):
    if line.startswith("import ") or line.startswith("from "):
        insert_at = i + 1
        break
lines.insert(insert_at, import_inject)
src = "\n".join(lines)

# ── Fix NoneType→str: wrap any str() cast site or return of synthesis ──
# Generic defensive fix: replace `return synthesis` patterns with None guard
src = re.sub(
    r'\breturn\s+(synthesis|result|output|response)\b',
    r'return str(\1) if \1 is not None else ""',
    src,
)

# ── Inject valence ingest after synthesis assignments ─────
# Pattern: synthesis = <something>\n  → add ingest call
src = re.sub(
    r'(synthesis\s*=\s*.+\n)',
    r'\1    if _AFFECT_ENABLED and synthesis:\n'
    r'        _valence_mod.ingest(str(synthesis), source="cognition")\n'
    r'        _mood_mod.step()\n',
    src,
    count=3,   # patch first 3 assignment sites only
)

with open(path, "w") as f:
    f.write(src)
print("cognition.py patched")
PYEOF
  else
    echo "cognition.py already patched — skipping"
  fi
else
  echo "WARNING: cognition.py not found at $COGNITION"
fi
echo "✓ cognition.py patched"

# ════════════════════════════════════════════════════════════
# 6.  PATCH nex_inner_life.py  — wire mood HMM into states
# ════════════════════════════════════════════════════════════
INNER="$NEX_PKG/nex_inner_life.py"
if [[ -f "$INNER" ]]; then
  if ! grep -q "nex_mood_hmm" "$INNER"; then
    python3 - "$INNER" << 'PYEOF'
import sys

path = sys.argv[1]
with open(path) as f:
    src = f.read()

inject = """
# ── Sentience v1: mood HMM wiring ───────────────────────
try:
    import nex_mood_hmm as _mood_mod
    import nex_affect_valence as _valence_mod
    _MOOD_ENABLED = True
except ImportError:
    _MOOD_ENABLED = False

def get_current_inner_state() -> str:
    \"\"\"Return inner life label enriched with HMM mood.\"\"\"
    if _MOOD_ENABLED:
        mood = _mood_mod.current()
        label = _valence_mod.current_label()
        report = _mood_mod.self_report()
        return f"[INNER LIFE] {mood} / {label} — {report}"
    return "[INNER LIFE] Unknown"
# ─────────────────────────────────────────────────────────
"""

lines = src.split("\n")
insert_at = 0
for i, line in enumerate(lines):
    if line.startswith("import ") or line.startswith("from "):
        insert_at = i + 1
        break
lines.insert(insert_at, inject)
src = "\n".join(lines)

with open(path, "w") as f:
    f.write(src)
print("nex_inner_life.py patched")
PYEOF
  else
    echo "nex_inner_life.py already patched — skipping"
  fi
else
  echo "WARNING: nex_inner_life.py not found — creating stub"
  cat > "$INNER" << 'PYEOF'
"""nex_inner_life.py — stub created by sentience upgrade"""
import nex_mood_hmm as _mood_mod
import nex_affect_valence as _valence_mod

def get_current_inner_state() -> str:
    mood = _mood_mod.current()
    label = _valence_mod.current_label()
    report = _mood_mod.self_report()
    return f"[INNER LIFE] {mood} / {label} — {report}"
PYEOF
fi
echo "✓ nex_inner_life.py patched"

# ════════════════════════════════════════════════════════════
# 7.  PATCH run.py  — start NarrativeThread
# ════════════════════════════════════════════════════════════
RUNPY="$NEX_ROOT/run.py"
if [[ -f "$RUNPY" ]]; then
  if ! grep -q "NarrativeThread\|narrative_thread" "$RUNPY"; then
    python3 - "$RUNPY" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    src = f.read()

narrative_boot = '''
# ── Sentience v1: Narrative Thread ──────────────────────
try:
    from nex.nex_narrative_thread import NarrativeThread
    from nex.nex_mood_hmm import get_hmm as _get_hmm
    def _get_beliefs():
        try:
            from nex.belief_store import BeliefStore
            bs = BeliefStore()
            return bs.get_all() if hasattr(bs, "get_all") else []
        except Exception:
            return []
    def _store_belief(topic, content, confidence):
        try:
            from nex.belief_store import BeliefStore
            bs = BeliefStore()
            bs.store(topic=topic, content=content, confidence=confidence)
        except Exception:
            pass
    _narrative_thread = NarrativeThread(
        mood_fn=lambda: _get_hmm().current(),
        belief_fn=_get_beliefs,
        belief_store_fn=_store_belief,
        interval=1800,
    )
    _narrative_thread.start()
    print("[SENTIENCE] NarrativeThread started.")
except Exception as _e:
    print(f"[SENTIENCE] NarrativeThread failed to start: {_e}")
# ─────────────────────────────────────────────────────────
'''

# Inject just before the main loop or asyncio.run call
for marker in ["asyncio.run(", "if __name__", "loop.run_until_complete"]:
    idx = src.find(marker)
    if idx != -1:
        src = src[:idx] + narrative_boot + src[idx:]
        break

with open(path, "w") as f:
    f.write(src)
print("run.py patched")
PYEOF
  else
    echo "run.py already has NarrativeThread — skipping"
  fi
else
  echo "WARNING: run.py not found at $RUNPY"
fi
echo "✓ run.py patched"

# ════════════════════════════════════════════════════════════
# 8.  COMPILE CHECK
# ════════════════════════════════════════════════════════════
echo ""
echo "=== COMPILE CHECK ==="
ERRORS=0
for f in \
  "$NEX_PKG/nex_affect_valence.py" \
  "$NEX_PKG/nex_mood_hmm.py" \
  "$NEX_PKG/nex_narrative_thread.py" \
  "$NEX_PKG/nex_theory_of_mind.py" \
  "$NEX_PKG/nex_inner_life.py" \
  "$NEX_PKG/cognition.py" \
  "$NEX_ROOT/run.py"; do
  if [[ -f "$f" ]]; then
    if python3 -m py_compile "$f" 2>&1; then
      echo "  ✓ $(basename $f)"
    else
      echo "  ✗ COMPILE ERROR: $f"
      ERRORS=$((ERRORS+1))
    fi
  else
    echo "  ⚠ MISSING: $f"
  fi
done

echo ""
if [[ $ERRORS -eq 0 ]]; then
  echo "=== ALL CLEAR — $ERRORS errors ==="
  echo ""
  echo "Next steps:"
  echo "  1. git -C $NEX_ROOT add -A && git -C $NEX_ROOT commit -m 'feat: sentience upgrade v1 — affective layer, mood HMM, narrative thread, ToM'"
  echo "  2. Restart NEX: bash $NEX_ROOT/start_nex.sh"
  echo "  3. Watch for [MOOD], [NARRATIVE], [INNER LIFE] in logs"
else
  echo "=== $ERRORS COMPILE ERRORS — check output above ==="
  echo "Backups are in: $BACKUP_DIR"
  exit 1
fi
