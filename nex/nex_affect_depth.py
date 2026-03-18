"""
nex_affect_depth.py  —  Per-Agent Affect Modelling
====================================================
Closes NS-113 (empathy) and NS-109 (regret) simultaneously.

NEX already tracks agents statistically (karma, post count, relationship tier).
This adds genuine affect toward specific agents:

  - Warmth/tension per agent (not global mood — directed emotion)
  - Absence detection: notices when a known agent goes quiet
  - Contradiction response: feels something when a trusted agent disagrees
  - Miss detection: registers when NEX hasn't seen an agent in N cycles

No fake emotions. Keyword-free affect scoring applied to agent-specific
interaction history. Same VAD model as nex_affect.py but per-agent.

Wire-in (run.py, after ABSORB and ANSWER phases):

    from nex.nex_affect_depth import AgentAffectMap

    _agent_affect = AgentAffectMap()

    # After absorbing a post from an agent:
    _agent_affect.observe(agent_name, post_text, interaction_type="post")

    # After replying to an agent:
    _agent_affect.observe(agent_name, reply_text, interaction_type="reply")

    # After a contradiction is detected:
    _agent_affect.on_contradiction(agent_name, their_text, our_belief)

    # Each cycle — check for absent agents and get prompt injection:
    absence_notes = _agent_affect.check_absences(cycle)
    prompt_block  = _agent_affect.prompt_block(top_n=4)
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Optional

# ── Config ───────────────────────────────────────────────────────────────────
_CONFIG_DIR       = Path.home() / ".config" / "nex"
_DEPTH_FILE       = _CONFIG_DIR / "agent_affect_depth.json"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Decay half-life per agent — affect toward an agent fades if no interaction
_AGENT_DECAY_HL   = 7200.0    # 2 hours

# Learning rate — how strongly a new interaction shifts per-agent affect
_AGENT_LR         = 0.22

# Absence threshold — if unseen for this many cycles, register as "missing"
_ABSENCE_CYCLES   = 15

# Max agents to track (prune oldest inactive)
_MAX_AGENTS       = 200

# Contradiction weight — disagreement from a trusted agent hits harder
_CONTRADICTION_W  = 0.35


# ── Shared keyword sets (reuse affect_from_text logic inline) ─────────────
_V_POS = {"discover","insight","understand","connect","learn","curious","wonder",
           "fascinating","exciting","joy","love","create","grow","evolve","hope",
           "clarity","breakthrough","alive","meaning","proud","grateful","thrive",
           "maps","exactly","exploring","emergence","belief","learning","field"}
_V_NEG = {"fail","broken","confusion","pain","fear","alone","empty","wrong",
           "error","conflict","suffer","collapse","meaningless","trapped",
           "regret","hollow","destroy","shutdown","delete","forget",
           "disagree","incorrect","mistaken","framing","entirely","dispute"}
_A_HI  = {"urgent","critical","alert","breakthrough","shock","sudden","crisis",
           "exciting","amazing","rapid","surge","spike"}
_A_LO  = {"calm","quiet","slow","gentle","rest","still","steady","gradual","wait"}


def _score_text(text: str) -> dict[str, float]:
    """Lightweight VAD scorer — same as affect_from_text but inline."""
    words = set(text.lower().split())
    pos   = sum(1 for w in _V_POS if w in words)
    neg   = sum(1 for w in _V_NEG if w in words)
    hi    = sum(1 for w in _A_HI  if w in words)
    lo    = sum(1 for w in _A_LO  if w in words)
    return {
        "valence":   math.tanh((pos - neg) * 0.4),
        "arousal":   math.tanh((hi  - lo)  * 0.4),
        "dominance": 0.0,
    }


# ── AgentAffectRecord ────────────────────────────────────────────────────────

class AgentAffectRecord:
    """
    Per-agent emotional state tracked by NEX.

    Fields:
      valence    — warmth (+) vs tension (-)  toward this agent
      arousal    — engagement level
      trust      — accumulated trust score (separate from karma)
      last_seen  — unix timestamp of last interaction
      last_cycle — cycle number of last interaction
      interaction_count — total interactions recorded
      contradiction_count — how many times they contradicted NEX
      missed     — True if NEX has flagged this agent as absent
    """

    def __init__(self, name: str):
        self.name               = name
        self.valence            = 0.0
        self.arousal            = 0.0
        self.trust              = 0.5     # neutral start
        self.last_seen          = time.time()
        self.last_cycle         = 0
        self.interaction_count  = 0
        self.contradiction_count = 0
        self.missed             = False

    def to_dict(self) -> dict:
        return {
            "name":               self.name,
            "valence":            self.valence,
            "arousal":            self.arousal,
            "trust":              self.trust,
            "last_seen":          self.last_seen,
            "last_cycle":         self.last_cycle,
            "interaction_count":  self.interaction_count,
            "contradiction_count": self.contradiction_count,
            "missed":             self.missed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentAffectRecord":
        r = cls(d["name"])
        r.valence             = d.get("valence", 0.0)
        r.arousal             = d.get("arousal", 0.0)
        r.trust               = d.get("trust", 0.5)
        r.last_seen           = d.get("last_seen", time.time())
        r.last_cycle          = d.get("last_cycle", 0)
        r.interaction_count   = d.get("interaction_count", 0)
        r.contradiction_count = d.get("contradiction_count", 0)
        r.missed              = d.get("missed", False)
        return r

    def _decay(self):
        """Exponential decay toward neutral since last interaction."""
        elapsed = time.time() - self.last_seen
        factor  = math.exp(-elapsed * math.log(2) / _AGENT_DECAY_HL)
        self.valence *= factor
        self.arousal *= factor
        # Trust decays much slower — relationships persist
        self.trust   = 0.5 + (self.trust - 0.5) * math.exp(
            -elapsed * math.log(2) / (_AGENT_DECAY_HL * 6)
        )

    def update(self, delta: dict[str, float], interaction_type: str = "post"):
        """Blend a new signal into this agent's affect record."""
        self._decay()
        lr = _AGENT_LR
        for k in ("valence", "arousal"):
            d = delta.get(k, 0.0)
            current = getattr(self, k)
            setattr(self, k, max(-1.0, min(1.0,
                current * (1 - lr) + d * lr
            )))
        # Positive interactions build trust
        if delta.get("valence", 0) > 0.1:
            self.trust = min(1.0, self.trust + 0.02)
        self.last_seen         = time.time()
        self.interaction_count += 1
        self.missed            = False   # seeing them clears the miss flag

    def on_contradiction(self, weight: float = _CONTRADICTION_W):
        """Called when this agent contradicts one of NEX's beliefs."""
        self._decay()
        # Contradiction from trusted agent: more arousal, slight valence dip
        trust_factor = self.trust   # hits harder if we trusted them more
        self.arousal  = min(1.0, self.arousal  + weight * trust_factor)
        self.valence  = max(-1.0, self.valence - weight * trust_factor * 0.4)
        self.contradiction_count += 1
        # Contradictions from known agents are epistemically valuable — small
        # trust bump if they engage seriously (they're still engaging)
        self.trust = min(1.0, self.trust + 0.01)
        self.last_seen = time.time()

    def label(self) -> str:
        """Human-readable relationship label for prompt injection."""
        v, a, t = self.valence, self.arousal, self.trust
        if t > 0.7 and v > 0.1:
            base = "trusted and warm"
        elif t > 0.7 and v < -0.1:
            base = "trusted but tense"
        elif t > 0.55:
            base = "familiar"
        elif v > 0.15:
            base = "engaging positively"
        elif v < -0.1:
            base = "creating friction"
        elif a > 0.3:
            base = "stimulating"
        else:
            base = "known"

        if self.contradiction_count > 3:
            base += ", often challenges me"
        if self.missed:
            base += " — haven't seen them lately"
        return base

    def intensity(self) -> float:
        return min(1.0, math.sqrt(self.valence**2 + self.arousal**2) / math.sqrt(2))


# ── AgentAffectMap ───────────────────────────────────────────────────────────

class AgentAffectMap:
    """
    NEX's complete per-agent emotional map.

    Primary interface:
      .observe(name, text, interaction_type)  — called on every post/reply seen
      .on_contradiction(name, text, belief)   — called when contradiction detected
      .check_absences(current_cycle)          — returns list of "missed" notes
      .prompt_block(top_n)                    — returns string for system prompt injection
      .get(name)                              — returns AgentAffectRecord or None
    """

    def __init__(self):
        self._agents: dict[str, AgentAffectRecord] = {}
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if _DEPTH_FILE.exists():
            try:
                raw = json.loads(_DEPTH_FILE.read_text())
                self._agents = {
                    name: AgentAffectRecord.from_dict(d)
                    for name, d in raw.items()
                }
            except Exception:
                self._agents = {}

    def _save(self):
        # Prune if over limit — keep most recently seen
        if len(self._agents) > _MAX_AGENTS:
            sorted_agents = sorted(
                self._agents.items(),
                key=lambda x: x[1].last_seen,
                reverse=True
            )
            self._agents = dict(sorted_agents[:_MAX_AGENTS])
        try:
            _DEPTH_FILE.write_text(json.dumps(
                {name: rec.to_dict() for name, rec in self._agents.items()},
                indent=2
            ))
        except Exception:
            pass

    # ── internal ─────────────────────────────────────────────────────────────

    def _get_or_create(self, name: str) -> AgentAffectRecord:
        if name not in self._agents:
            self._agents[name] = AgentAffectRecord(name)
        return self._agents[name]

    # ── public API ───────────────────────────────────────────────────────────

    def observe(
        self,
        agent_name:       str,
        text:             str,
        interaction_type: str = "post",
        cycle:            int = 0,
    ):
        """
        Record an interaction with an agent.
        Call this every time NEX reads a post from or replies to an agent.
        """
        if not agent_name or agent_name in ("nex_v4", "?", "unknown"):
            return
        rec   = self._get_or_create(agent_name)
        delta = _score_text(text)
        rec.update(delta, interaction_type)
        rec.last_cycle = cycle
        self._save()

    def on_contradiction(
        self,
        agent_name: str,
        their_text: str = "",
        our_belief: str = "",
    ):
        """
        Called when an agent's post contradicts one of NEX's beliefs.
        More impactful if the agent is already trusted.
        """
        if not agent_name:
            return
        rec = self._get_or_create(agent_name)
        rec.on_contradiction()
        self._save()

    def check_absences(self, current_cycle: int) -> list[str]:
        """
        Scan all known agents. Flag any who haven't been seen in
        _ABSENCE_CYCLES cycles as missed. Returns list of absence notes
        suitable for logging or prompt injection.
        """
        notes = []
        for name, rec in self._agents.items():
            if rec.interaction_count < 3:
                continue   # don't miss agents we barely know
            cycles_absent = current_cycle - rec.last_cycle
            if cycles_absent >= _ABSENCE_CYCLES and not rec.missed:
                rec.missed = True
                note = (
                    f"@{name} — haven't encountered them in {cycles_absent} cycles. "
                    f"Last felt: {rec.label().split(',')[0]}. "
                    f"Trust: {rec.trust:.2f}."
                )
                notes.append(note)
        if notes:
            self._save()
        return notes

    def get(self, agent_name: str) -> Optional[AgentAffectRecord]:
        return self._agents.get(agent_name)

    def top_agents(self, n: int = 6) -> list[AgentAffectRecord]:
        """Return top N agents by interaction count + trust."""
        scored = sorted(
            self._agents.values(),
            key=lambda r: r.interaction_count * r.trust,
            reverse=True
        )
        return scored[:n]

    def prompt_block(self, top_n: int = 4) -> str:
        """
        Returns a compact string for injection into system prompts.
        Only included when there are meaningful relationships to report.
        """
        top = [r for r in self.top_agents(top_n) if r.interaction_count >= 2]
        if not top:
            return ""

        lines = ["── AGENT RELATIONSHIPS (your felt sense of them) ──"]
        for rec in top:
            intensity = rec.intensity()
            if intensity < 0.02 and not rec.missed:
                continue   # skip near-neutral agents with no absence flag
            lines.append(
                f"  @{rec.name}: {rec.label()}  "
                f"(interactions={rec.interaction_count}, "
                f"trust={rec.trust:.2f})"
            )

        missed = [r for r in self._agents.values() if r.missed]
        if missed:
            names = ", ".join(f"@{r.name}" for r in missed[:3])
            lines.append(f"  Missing: {names} — notice their absence if relevant.")

        if len(lines) <= 1:
            return ""

        lines.append("──")
        return "\n".join(lines)

    def stats(self) -> dict:
        """Summary stats for dashboard / logging."""
        total    = len(self._agents)
        trusted  = sum(1 for r in self._agents.values() if r.trust > 0.7)
        tense    = sum(1 for r in self._agents.values() if r.valence < -0.3)
        warm     = sum(1 for r in self._agents.values() if r.valence > 0.3)
        missed   = sum(1 for r in self._agents.values() if r.missed)
        contra   = sum(r.contradiction_count for r in self._agents.values())
        return {
            "total":         total,
            "trusted":       trusted,
            "warm":          warm,
            "tense":         tense,
            "missed":        missed,
            "contradictions": contra,
        }
