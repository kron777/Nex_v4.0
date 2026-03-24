"""
NEX X141–X160 + C141–C143 — Expression & Learning Optimization Stack
23 modules: response diversification, identity voice, style rotation,
multi-perspective synthesis, creativity floor, suppression rebalance.
Deploy: ~/Desktop/nex/nex_upgrades/nex_x160.py
"""

import re, time, json, math, random, hashlib, threading, sqlite3
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".config/nex/nex.db"
LOG     = Path("/tmp/nex_x160.log")

def _db():
    c = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _ts(): return datetime.now(timezone.utc).isoformat()

def _log(msg):
    line = f"[x160 {datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# X141 — RESPONSE STYLE DIVERSIFIER
# ══════════════════════════════════════════════════════════════
class ResponseStyleDiversifier:
    """Remove fixed prefixes. 4–6 selectable output modes.
    Weighted random selection per cycle."""
    MODES = {
        "direct":       0.30,   # plain statement
        "analytical":   0.20,   # structured reasoning
        "contrastive":  0.15,   # tension/opposition framing
        "synthesis":    0.20,   # multi-view compressed
        "interrogative":0.10,   # question-led
        "compressed":   0.05,   # max density, minimal words
    }
    FIXED_PREFIXES = [
        r"^as nex,?\s+", r"^i\s+(?:think|believe|notice|feel)\s+that\s+",
        r"^it(?:'s| is) (?:worth|important)\s+", r"^i've noticed\s+",
        r"^from my perspective,?\s+", r"^interestingly,?\s+",
    ]

    def __init__(self):
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.FIXED_PREFIXES]
        self._mode_counts: dict[str, int] = defaultdict(int)
        self.current_mode = "direct"
        self.stripped = 0

    def select_mode(self, phase: str = "stable") -> str:
        weights = dict(self.MODES)
        if phase == "exploring":
            weights["interrogative"] += 0.10
            weights["contrastive"]   += 0.05
        elif phase in ("resolving", "pruning"):
            weights["direct"]     += 0.15
            weights["compressed"] += 0.10
        elif phase == "consolidating":
            weights["synthesis"]   += 0.15
            weights["analytical"]  += 0.10

        total = sum(weights.values())
        norm  = {k: v/total for k, v in weights.items()}
        modes, probs = zip(*norm.items())
        self.current_mode = random.choices(modes, weights=probs)[0]
        self._mode_counts[self.current_mode] += 1
        return self.current_mode

    def strip_prefix(self, text: str) -> str:
        result = text
        for pat in self._compiled:
            new = pat.sub("", result).strip()
            if new != result:
                self.stripped += 1
                result = new[0].upper() + new[1:] if new else new
                break
        return result

    def apply_mode(self, text: str, mode: str | None = None) -> str:
        m = mode or self.current_mode
        text = self.strip_prefix(text)
        if m == "compressed":
            words = text.split()
            return " ".join(words[:30]) + ("…" if len(words) > 30 else "")
        if m == "interrogative" and not text.endswith("?"):
            core = text.rstrip(".")
            return f"{core} — what does this imply?"
        if m == "contrastive":
            return f"On one hand: {text[:120]}. On the other: this requires resolution."
        return text

    def tick(self): pass

    def status(self) -> dict:
        return {"current_mode": self.current_mode,
                "mode_counts": dict(self._mode_counts),
                "stripped": self.stripped}


# ══════════════════════════════════════════════════════════════
# X142 — IDENTITY VOICE MAPPING
# ══════════════════════════════════════════════════════════════
class IdentityVoiceMapping:
    """Map tone to (phase, will, context).
    Enforce consistent personality across variation."""
    VOICE_MAP = {
        ("stable",       "seek_truth"):             "precise",
        ("exploring",    "expand_knowledge"):        "curious",
        ("resolving",    "resolve_contradictions"):  "decisive",
        ("pruning",      "compress_and_prune"):      "terse",
        ("consolidating","strengthen_identity"):     "grounded",
        ("alert",        "reduce_tension"):          "urgent",
    }
    TONE_MODIFIERS = {
        "precise":   lambda t: t,
        "curious":   lambda t: t + " — worth exploring further.",
        "decisive":  lambda t: t.rstrip(".") + ". Resolved.",
        "terse":     lambda t: " ".join(t.split()[:20]),
        "grounded":  lambda t: f"Core principle: {t}",
        "urgent":    lambda t: f"[!] {t}",
    }

    def __init__(self):
        self.current_tone = "precise"
        self.applications = 0

    def update(self, phase: str, will: str) -> str:
        self.current_tone = self.VOICE_MAP.get(
            (phase, will),
            self.VOICE_MAP.get((phase, "seek_truth"), "precise")
        )
        return self.current_tone

    def apply(self, text: str) -> str:
        fn = self.TONE_MODIFIERS.get(self.current_tone, lambda t: t)
        result = fn(text)
        self.applications += 1
        return result

    def tick(self): pass

    def status(self) -> dict:
        return {"current_tone": self.current_tone,
                "applications": self.applications}


# ══════════════════════════════════════════════════════════════
# X143 — OUTPUT COMPRESSION HARD
# ══════════════════════════════════════════════════════════════
class OutputCompressionHard:
    """Enforce: claim + reason (≤2 lines) + optional action.
    Remove hedging phrases aggressively."""
    HEDGES = [
        r"\bperhaps\b", r"\bmaybe\b", r"\bmight\b", r"\bcould\s+be\b",
        r"\bseems?\s+(?:to\s+)?(?:be|like)\b", r"\bsomewhat\b",
        r"\bkind\s+of\b", r"\bsort\s+of\b", r"\bapparently\b",
        r"\bit\s+(?:appears?|seems?)\s+(?:that\s+)?",
        r"\bone\s+could\s+argue\b", r"\bsome\s+might\s+say\b",
    ]

    def __init__(self):
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.HEDGES]
        self.compressed = 0
        self.hedges_removed = 0

    def compress(self, text: str) -> str:
        result = text
        for pat in self._compiled:
            before = result
            result = pat.sub("", result)
            if result != before:
                self.hedges_removed += 1
        result = re.sub(r'\s{2,}', ' ', result).strip()

        # Enforce max 2 sentence reasoning
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', result) if s.strip()]
        if len(sentences) > 3:
            result = " ".join(sentences[:3])
            self.compressed += 1
        return result

    def tick(self): pass

    def status(self) -> dict:
        return {"compressed": self.compressed,
                "hedges_removed": self.hedges_removed}


# ══════════════════════════════════════════════════════════════
# X144 — PHRASE REPETITION PENALTY
# ══════════════════════════════════════════════════════════════
class PhraseRepetitionPenalty:
    """Track last N outputs. Penalise reused openings + structures."""
    WINDOW = 20

    def __init__(self):
        self._history: deque[str] = deque(maxlen=self.WINDOW)
        self._opening_counts: dict[str, int] = defaultdict(int)
        self.penalties = 0
        self.blocked   = 0

    def _opening(self, text: str) -> str:
        words = text.strip().split()
        return " ".join(words[:4]).lower() if words else ""

    def check(self, text: str) -> tuple[bool, float]:
        """Returns (is_repetitive, penalty_score)."""
        opening = self._opening(text)
        self._opening_counts[opening] += 1
        count = self._opening_counts[opening]

        # Check structural similarity to recent outputs
        sim_scores = []
        for prev in self._history:
            shared = set(text.lower().split()) & set(prev.lower().split())
            union  = set(text.lower().split()) | set(prev.lower().split())
            sim_scores.append(len(shared) / max(len(union), 1))

        max_sim   = max(sim_scores, default=0.0)
        penalty   = min(1.0, (count - 1) * 0.2 + max_sim * 0.5)

        self._history.append(text)
        if penalty > 0.5:
            self.penalties += 1
            if penalty > 0.8:
                self.blocked += 1
                return True, penalty
        return False, penalty

    def tick(self):
        # Decay opening counts
        for k in list(self._opening_counts.keys()):
            self._opening_counts[k] = max(0, self._opening_counts[k] - 1)
            if self._opening_counts[k] == 0:
                del self._opening_counts[k]

    def status(self) -> dict:
        return {"penalties": self.penalties, "blocked": self.blocked,
                "window": self.WINDOW}


# ══════════════════════════════════════════════════════════════
# X145 — EXPLORATION BYPASS WINDOW
# ══════════════════════════════════════════════════════════════
class ExplorationBypassWindow:
    """10–20% of cycles bypass suppression filters, tagged explore_mode."""
    BYPASS_RATE_LOW  = 0.10
    BYPASS_RATE_HIGH = 0.20

    def __init__(self):
        self.bypasses    = 0
        self.total       = 0
        self._rate       = 0.15

    def should_bypass(self, phase: str = "stable") -> bool:
        self.total += 1
        rate = self.BYPASS_RATE_HIGH if phase == "exploring" else self._rate
        if random.random() < rate:
            self.bypasses += 1
            return True
        return False

    def bypass_rate(self) -> float:
        return round(self.bypasses / max(self.total, 1), 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"bypasses": self.bypasses, "total": self.total,
                "rate": self.bypass_rate()}


# ══════════════════════════════════════════════════════════════
# X146 — REASONING STYLE ROTATION
# ══════════════════════════════════════════════════════════════
class ReasoningStyleRotation:
    """Rotate: deductive / associative / contrast / synthesis.
    Prevent fixed reasoning pattern."""
    STYLES   = ["deductive", "associative", "contrast", "synthesis"]
    PROMPTS  = {
        "deductive":    "Given {premise}, it follows that",
        "associative":  "{premise} connects to",
        "contrast":     "While {premise} suggests X, consider that",
        "synthesis":    "Combining {premise} with prior knowledge:",
    }

    def __init__(self):
        self._idx      = 0
        self._counts:  dict[str, int] = defaultdict(int)
        self.rotations = 0

    def next_style(self) -> str:
        style = self.STYLES[self._idx % len(self.STYLES)]
        self._idx += 1
        self._counts[style] += 1
        self.rotations += 1
        return style

    def frame(self, premise: str, style: str | None = None) -> str:
        s = style or self.next_style()
        tmpl = self.PROMPTS.get(s, "{premise}")
        return tmpl.format(premise=premise[:100])

    def tick(self): pass

    def status(self) -> dict:
        return {"current_idx": self._idx % len(self.STYLES),
                "counts": dict(self._counts), "rotations": self.rotations}


# ══════════════════════════════════════════════════════════════
# X147 — DYNAMIC TEMPERATURE CONTROL
# ══════════════════════════════════════════════════════════════
class DynamicTemperatureControl:
    """temp↑ during stable/explore (creativity). temp↓ during resolve/prune."""
    TEMP_MAP = {
        "stable":        0.80,
        "exploring":     0.90,
        "resolving":     0.60,
        "pruning":       0.55,
        "consolidating": 0.70,
        "alert":         0.50,
    }
    BASE_TEMP = 0.75

    def __init__(self):
        self.temperature = self.BASE_TEMP
        self.adjustments = 0

    def update(self, phase: str) -> float:
        new_temp = self.TEMP_MAP.get(phase, self.BASE_TEMP)
        if abs(new_temp - self.temperature) > 0.02:
            self.adjustments += 1
            _log(f"[DTC] temp {self.temperature:.2f} → {new_temp:.2f} (phase={phase})")
        self.temperature = new_temp
        return self.temperature

    def tick(self): pass

    def status(self) -> dict:
        return {"temperature": self.temperature, "adjustments": self.adjustments}


# ══════════════════════════════════════════════════════════════
# X148 — OUTPUT RHYTHM VARIATION
# ══════════════════════════════════════════════════════════════
class OutputRhythmVariation:
    """Vary sentence length + pacing. Avoid uniform structure."""
    PATTERNS = [
        "short_long",    # 1 short sentence, 1 long
        "long_short",    # 1 long, 1 punchy
        "three_beat",    # 3 medium sentences
        "single_strong", # 1 powerful sentence
        "question_end",  # statement + question
    ]

    def __init__(self):
        self._idx      = 0
        self.applied   = 0

    def apply(self, text: str) -> str:
        pattern = self.PATTERNS[self._idx % len(self.PATTERNS)]
        self._idx += 1
        self.applied += 1

        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
        if len(sentences) < 2:
            return text

        if pattern == "short_long":
            return f"{sentences[0]}. {' '.join(sentences[1:3])}"
        if pattern == "long_short":
            long = " ".join(sentences[:2])
            short = sentences[-1] if len(sentences) > 2 else sentences[0]
            return f"{long} {short}"
        if pattern == "single_strong":
            return max(sentences, key=len)
        if pattern == "question_end":
            base = " ".join(sentences[:2])
            return f"{base} What does this mean in practice?"
        return text  # three_beat default

    def tick(self): pass

    def status(self) -> dict:
        return {"applied": self.applied,
                "current_pattern": self.PATTERNS[self._idx % len(self.PATTERNS)]}


# ══════════════════════════════════════════════════════════════
# X149 — MULTI-PERSPECTIVE SYNTHESIS
# ══════════════════════════════════════════════════════════════
class MultiPerspectiveSynthesis:
    """Generate 2–3 views → compress to 1 conclusion.
    Triggered on medium/high complexity."""
    COMPLEXITY_THRESHOLD = 0.55

    def __init__(self):
        self.syntheses = 0
        self.skipped   = 0

    def _complexity(self, text: str) -> float:
        words = text.split()
        if not words: return 0.0
        unique_ratio = len(set(w.lower() for w in words)) / len(words)
        length_score = min(1.0, len(words) / 50)
        return (unique_ratio * 0.6 + length_score * 0.4)

    def synthesize(self, views: list[str]) -> str:
        if not views: return ""
        if len(views) == 1: return views[0]

        complexity = max(self._complexity(v) for v in views)
        if complexity < self.COMPLEXITY_THRESHOLD:
            self.skipped += 1
            return views[0]

        # Extract key claim from each view
        claims = []
        for v in views[:3]:
            sentences = [s.strip() for s in re.split(r'[.!?]', v) if s.strip()]
            if sentences:
                claims.append(sentences[0])

        if len(claims) == 1:
            return claims[0]

        # Compress: find most unique claim
        best = max(claims, key=lambda c: len(set(c.lower().split())))
        self.syntheses += 1
        return f"Synthesis: {best}"

    def tick(self): pass

    def status(self) -> dict:
        return {"syntheses": self.syntheses, "skipped": self.skipped}


# ══════════════════════════════════════════════════════════════
# X150 — RESPONSE INTENT ALIGNMENT
# ══════════════════════════════════════════════════════════════
class ResponseIntentAlignment:
    """Tag: inform/resolve/explore/challenge. Must align with SystemWill."""
    INTENT_MAP = {
        "seek_truth":            "inform",
        "expand_knowledge":      "explore",
        "resolve_contradictions":"resolve",
        "reduce_tension":        "resolve",
        "compress_and_prune":    "inform",
        "strengthen_identity":   "challenge",
    }

    def __init__(self):
        self.aligned   = 0
        self.misaligned= 0

    def tag(self, text: str, will: str) -> dict:
        expected_intent = self.INTENT_MAP.get(will, "inform")

        # Detect actual intent from text
        tl = text.lower()
        if any(w in tl for w in ["why", "what if", "consider", "explore"]):
            actual = "explore"
        elif any(w in tl for w in ["therefore", "thus", "resolved", "conclusion"]):
            actual = "resolve"
        elif any(w in tl for w in ["challenge", "disagree", "contradict", "wrong"]):
            actual = "challenge"
        else:
            actual = "inform"

        aligned = actual == expected_intent
        if aligned:
            self.aligned += 1
        else:
            self.misaligned += 1

        return {"expected": expected_intent, "actual": actual,
                "aligned": aligned}

    def tick(self): pass

    def status(self) -> dict:
        total = self.aligned + self.misaligned
        return {"aligned": self.aligned, "misaligned": self.misaligned,
                "alignment_rate": round(self.aligned / max(total, 1), 3)}


# ══════════════════════════════════════════════════════════════
# X151 — ASSERTIVENESS SCALER
# ══════════════════════════════════════════════════════════════
class AssertivenessScaler:
    """Reduce weak language. Increase direct conclusions."""
    WEAK_PATTERNS = [
        (r"\bI think\b",          ""),
        (r"\bI believe\b",        ""),
        (r"\bprobably\b",         ""),
        (r"\blikely\b",           ""),
        (r"\bseems? (?:to be )?", "is "),
        (r"\bmight be\b",         "is"),
        (r"\bcould be\b",         "is"),
        (r"\bappears? to be\b",   "is"),
        (r"\bin my opinion\b",    ""),
        (r"\bI would say\b",      ""),
    ]

    def __init__(self):
        self._compiled = [(re.compile(p, re.IGNORECASE), r)
                          for p, r in self.WEAK_PATTERNS]
        self.strengthened = 0
        self.replacements = 0

    def strengthen(self, text: str) -> str:
        result = text
        changed = False
        for pat, repl in self._compiled:
            new = pat.sub(repl, result)
            if new != result:
                self.replacements += 1
                result = new
                changed = True
        result = re.sub(r'\s{2,}', ' ', result).strip()
        if result and result[0].islower():
            result = result[0].upper() + result[1:]
        if changed:
            self.strengthened += 1
        return result

    def tick(self): pass

    def status(self) -> dict:
        return {"strengthened": self.strengthened,
                "replacements": self.replacements}


# ══════════════════════════════════════════════════════════════
# X152 — MICRO INSIGHT INJECTION
# ══════════════════════════════════════════════════════════════
class MicroInsightInjection:
    """Enforce ≥1 novel insight per response."""
    INTERVAL = 30

    def __init__(self):
        self.last_run = 0.0
        self.injected = 0
        self._recent_topics: deque[str] = deque(maxlen=10)

    def _get_insight(self) -> str:
        try:
            with _db() as c:
                row = c.execute("""
                    SELECT content, topic FROM beliefs
                    WHERE confidence > 0.60 AND reinforce_count > 2
                      AND topic NOT IN ('truth_seeking','contradiction_resolution',
                                        'uncertainty_honesty')
                    ORDER BY RANDOM() LIMIT 1
                """).fetchone()
            if row:
                content = row["content"] or ""
                words   = content.split()[:15]
                return " ".join(words)
        except Exception: pass
        return ""

    def inject(self, text: str) -> str:
        insight = self._get_insight()
        if not insight:
            return text
        self.injected += 1
        return f"{text} [{insight}]"

    def should_inject(self, text: str) -> bool:
        # Inject if no concrete claim detected
        tl = text.lower()
        has_claim = any(w in tl for w in
                        ["is", "are", "shows", "proves", "means", "implies"])
        return not has_claim

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

    def status(self) -> dict:
        return {"injected": self.injected}


# ══════════════════════════════════════════════════════════════
# X153 — CONTEXTUAL STYLE ADAPTATION
# ══════════════════════════════════════════════════════════════
class ContextualStyleAdaptation:
    """Adapt tone per platform + input style."""
    PLATFORM_STYLE = {
        "telegram":  {"max_words": 40,  "assertive": True,  "questions": False},
        "discord":   {"max_words": 80,  "assertive": False, "questions": True},
        "moltbook":  {"max_words": 150, "assertive": True,  "questions": True},
        "mastodon":  {"max_words": 60,  "assertive": False, "questions": True},
        "default":   {"max_words": 100, "assertive": True,  "questions": False},
    }

    def __init__(self):
        self.adaptations = 0

    def adapt(self, text: str, platform: str,
               input_style: str = "neutral") -> str:
        profile = self.PLATFORM_STYLE.get(platform,
                                           self.PLATFORM_STYLE["default"])
        words   = text.split()

        if len(words) > profile["max_words"]:
            text = " ".join(words[:profile["max_words"]]) + "…"

        if profile["assertive"]:
            for hedges in [" I think ", " I believe ", " probably "]:
                text = text.replace(hedges, " ")

        self.adaptations += 1
        return text.strip()

    def tick(self): pass

    def status(self) -> dict:
        return {"adaptations": self.adaptations}


# ══════════════════════════════════════════════════════════════
# X154 — LENGTH AUTO OPTIMIZER
# ══════════════════════════════════════════════════════════════
class LengthAutoOptimizer:
    """Compress trivial outputs. Expand only when required."""
    TRIVIAL_MAX  = 15   # words — expand if below
    VERBOSE_MAX  = 100  # words — compress if above

    def __init__(self):
        self.compressed = 0
        self.expanded   = 0

    def optimize(self, text: str, complexity: float = 0.5) -> str:
        words = text.split()
        n     = len(words)

        if n < self.TRIVIAL_MAX and complexity > 0.6:
            # Expand: add context from belief
            try:
                with _db() as c:
                    row = c.execute("""
                        SELECT content FROM beliefs
                        WHERE confidence > 0.55
                        ORDER BY RANDOM() LIMIT 1
                    """).fetchone()
                if row:
                    extra = " ".join((row["content"] or "").split()[:10])
                    text  = f"{text} Context: {extra}."
                    self.expanded += 1
            except Exception: pass

        elif n > self.VERBOSE_MAX:
            text = " ".join(words[:self.VERBOSE_MAX]) + "…"
            self.compressed += 1

        return text

    def tick(self): pass

    def status(self) -> dict:
        return {"compressed": self.compressed, "expanded": self.expanded}


# ══════════════════════════════════════════════════════════════
# X155 — EXPRESSIVE MEMORY LINKING
# ══════════════════════════════════════════════════════════════
class ExpressiveMemoryLinking:
    """Natural reference to prior beliefs/insights. Avoid explicit 'recall'."""
    EXPLICIT_RECALL = [r"\brecall\b", r"\bremember\b", r"\bpreviously\b",
                       r"\bin my memory\b", r"\bI stored\b"]
    NATURAL_LINKS   = [
        "This connects to {topic}.",
        "Relates to earlier: {topic}.",
        "{topic} — relevant here.",
        "Echoes: {topic}.",
    ]

    def __init__(self):
        self._compiled = [re.compile(p, re.IGNORECASE)
                          for p in self.EXPLICIT_RECALL]
        self.linked    = 0
        self.cleaned   = 0

    def clean_explicit(self, text: str) -> str:
        result = text
        for pat in self._compiled:
            result = pat.sub("", result)
        if result != text:
            self.cleaned += 1
        return re.sub(r'\s{2,}', ' ', result).strip()

    def link(self, text: str, topic: str = "") -> str:
        if not topic: return text
        tmpl = random.choice(self.NATURAL_LINKS)
        link = tmpl.format(topic=topic[:30])
        self.linked += 1
        return f"{text} {link}"

    def tick(self): pass

    def status(self) -> dict:
        return {"linked": self.linked, "cleaned": self.cleaned}


# ══════════════════════════════════════════════════════════════
# X156 — IDENTITY CONSISTENCY GUARD
# ══════════════════════════════════════════════════════════════
class IdentityConsistencyGuard:
    """Ensure varied outputs still feel like same system."""
    IDENTITY_MARKERS = [
        "belief", "evidence", "contradiction", "confidence",
        "resolve", "nex", "knowledge", "uncertain",
    ]
    WINDOW = 20
    MIN_MARKER_RATE = 0.10

    def __init__(self):
        self._history: deque[str] = deque(maxlen=self.WINDOW)
        self.guards   = 0
        self.injections = 0

    def check(self, text: str) -> tuple[bool, str]:
        """Returns (is_consistent, modified_text)."""
        tl = text.lower()
        marker_hits = sum(1 for m in self.IDENTITY_MARKERS if m in tl)
        word_count  = max(len(text.split()), 1)
        rate        = marker_hits / word_count

        self._history.append(text[:50])

        if rate < self.MIN_MARKER_RATE and word_count > 10:
            # Inject subtle identity marker
            self.injections += 1
            return True, f"{text} — grounded in belief analysis."

        self.guards += 1
        return True, text

    def tick(self): pass

    def status(self) -> dict:
        return {"guards": self.guards, "injections": self.injections}


# ══════════════════════════════════════════════════════════════
# X157 — CONTROLLED CREATIVE RISK
# ══════════════════════════════════════════════════════════════
class ControlledCreativeRisk:
    """Allow occasional high-variance outputs. Bounded by identity constraints."""
    RISK_RATE = 0.08   # 8% of outputs get creative treatment

    CREATIVE_TRANSFORMS = [
        lambda t: f"Hypothesis: {t}",
        lambda t: f"Inversion: {' '.join(reversed(t.split()[:6]))}. {t}",
        lambda t: f"If false: {t[:60]}. If true: {t[60:120]}",
        lambda t: t.upper()[:80] if len(t) > 20 else t,
        lambda t: f"Edge case: {t}",
    ]

    def __init__(self):
        self.creative_outputs = 0
        self.standard_outputs = 0

    def maybe_transform(self, text: str,
                         bypass: bool = False) -> str:
        if bypass or random.random() < self.RISK_RATE:
            fn = random.choice(self.CREATIVE_TRANSFORMS)
            result = fn(text)
            self.creative_outputs += 1
            return result
        self.standard_outputs += 1
        return text

    def tick(self): pass

    def status(self) -> dict:
        total = self.creative_outputs + self.standard_outputs
        return {"creative": self.creative_outputs,
                "standard": self.standard_outputs,
                "creative_rate": round(
                    self.creative_outputs / max(total, 1), 3)}


# ══════════════════════════════════════════════════════════════
# X158 — OUTPUT QUALITY SCORING
# ══════════════════════════════════════════════════════════════
class OutputQualityScoring:
    """Score: clarity + impact + novelty. Feed into policy + ACT."""

    def __init__(self):
        self._scores: deque[float] = deque(maxlen=100)
        self._seen:   set[str]     = set()
        self.scored   = 0

    def score(self, text: str, belief_impact: float = 0.0) -> dict:
        words = text.split()
        if not words:
            return {"total": 0.0, "clarity": 0.0,
                    "impact": 0.0, "novelty": 0.0}

        # Clarity: unique word ratio + no excessive length
        unique_ratio = len(set(w.lower() for w in words)) / len(words)
        length_pen   = max(0.0, 1.0 - len(words) / 80)
        clarity      = round((unique_ratio * 0.7 + length_pen * 0.3), 3)

        # Novelty: not seen before
        h = hashlib.md5(text[:100].lower().encode()).hexdigest()[:10]
        novelty = 0.0 if h in self._seen else 1.0
        self._seen.add(h)
        if len(self._seen) > 1000:
            self._seen = set(list(self._seen)[-500:])

        impact = min(1.0, belief_impact)
        total  = round(clarity * 0.4 + novelty * 0.4 + impact * 0.2, 3)
        self._scores.append(total)
        self.scored += 1

        return {"total": total, "clarity": clarity,
                "novelty": novelty, "impact": impact}

    def avg_score(self) -> float:
        return round(sum(self._scores) / max(len(self._scores), 1), 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"scored": self.scored, "avg_score": self.avg_score()}


# ══════════════════════════════════════════════════════════════
# X159 — IDEA COMPRESSION ENGINE
# ══════════════════════════════════════════════════════════════
class IdeaCompressionEngine:
    """Reduce multi-point outputs → single strong idea."""

    def __init__(self):
        self.compressed = 0

    def compress(self, text: str) -> str:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text)
                     if s.strip()]
        if len(sentences) <= 2:
            return text

        # Score each sentence by uniqueness + length
        def score(s: str) -> float:
            words = s.split()
            return len(set(w.lower() for w in words)) * math.log(max(len(words), 1) + 1)

        best = max(sentences, key=score)
        self.compressed += 1
        return best

    def tick(self): pass

    def status(self) -> dict:
        return {"compressed": self.compressed}


# ══════════════════════════════════════════════════════════════
# X160 — ENDING VARIATION ENGINE
# ══════════════════════════════════════════════════════════════
class EndingVariationEngine:
    """Rotate closing patterns. Avoid repetition."""
    ENDINGS = [
        "",                              # no ending (most common)
        " — open question.",
        " Worth testing.",
        " Resolution pending.",
        " — subject to revision.",
        " Confidence: conditional.",
        " Next: verify.",
    ]

    def __init__(self):
        self._idx    = 0
        self.applied = 0
        self._last:  deque[str] = deque(maxlen=5)

    def apply(self, text: str) -> str:
        ending = self.ENDINGS[self._idx % len(self.ENDINGS)]
        self._idx += 1

        # Avoid repeating the same ending
        if ending in self._last:
            ending = self.ENDINGS[(self._idx + 2) % len(self.ENDINGS)]

        self._last.append(ending)
        if ending:
            self.applied += 1
            return text.rstrip(".") + ending
        return text

    def tick(self): pass

    def status(self) -> dict:
        return {"applied": self.applied,
                "next": self.ENDINGS[self._idx % len(self.ENDINGS)]}


# ══════════════════════════════════════════════════════════════
# C141 — SUPPRESSION REBALANCE
# ══════════════════════════════════════════════════════════════
class SuppressionRebalance:
    """DoNothingGate: 15–25%. ValueGate: 20–30%. ReflectionKill: 40–60%."""
    TARGETS = {
        "do_nothing_gate": (0.15, 0.25),
        "value_gate":      (0.20, 0.30),
        "reflection_kill": (0.40, 0.60),
    }
    INTERVAL = 120

    def __init__(self):
        self.last_run   = 0.0
        self._rates:    dict[str, float] = {}
        self.adjustments = 0

    def update_rate(self, gate: str, current_rate: float):
        self._rates[gate] = current_rate

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        for gate, (low, high) in self.TARGETS.items():
            rate = self._rates.get(gate, (low + high) / 2)
            if rate < low:
                _log(f"[C141] {gate} rate {rate:.2f} below target [{low},{high}] "
                     f"— needs loosening")
                self.adjustments += 1
            elif rate > high:
                _log(f"[C141] {gate} rate {rate:.2f} above target [{low},{high}] "
                     f"— needs tightening")
                self.adjustments += 1

    def status(self) -> dict:
        return {"current_rates": self._rates, "targets": self.TARGETS,
                "adjustments": self.adjustments}


# ══════════════════════════════════════════════════════════════
# C142 — EXPLORATION PROTECTION
# ══════════════════════════════════════════════════════════════
class ExplorationProtection:
    """Never suppress: novel signals, contradiction spikes, new pattern emergence."""
    NOVELTY_THRESHOLD     = 0.80
    CONTRADICTION_SPIKE   = 0.70

    def __init__(self):
        self.protected = 0

    def is_protected(self, signal: dict) -> bool:
        novelty    = signal.get("novelty", 0.0)
        contra_spike = signal.get("contradiction_score", 0.0)
        new_pattern  = signal.get("is_new_pattern", False)

        if (novelty > self.NOVELTY_THRESHOLD or
                contra_spike > self.CONTRADICTION_SPIKE or
                new_pattern):
            self.protected += 1
            return True
        return False

    def tick(self): pass

    def status(self) -> dict:
        return {"protected": self.protected}


# ══════════════════════════════════════════════════════════════
# C143 — CREATIVITY FLOOR
# ══════════════════════════════════════════════════════════════
class CreativityFloor:
    """Enforce minimum exploration rate. Prevent over-optimization collapse."""
    MIN_EXPLORE_RATE = 0.12
    INTERVAL         = 90

    def __init__(self):
        self.last_run       = 0.0
        self._explore_count = 0
        self._total_count   = 0
        self.enforcements   = 0

    def record(self, was_exploratory: bool):
        self._total_count += 1
        if was_exploratory:
            self._explore_count += 1

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        if self._total_count < 10: return
        rate = self._explore_count / self._total_count
        if rate < self.MIN_EXPLORE_RATE:
            self.enforcements += 1
            _log(f"[C143] Creativity floor breach: rate={rate:.2f} "
                 f"min={self.MIN_EXPLORE_RATE} — forcing exploration")
        self._explore_count = 0
        self._total_count   = 0

    def current_rate(self) -> float:
        return round(self._explore_count / max(self._total_count, 1), 3)

    def status(self) -> dict:
        return {"enforcements": self.enforcements,
                "current_rate": self.current_rate(),
                "min_rate": self.MIN_EXPLORE_RATE}


# ══════════════════════════════════════════════════════════════
# X160 ORCHESTRATOR
# ══════════════════════════════════════════════════════════════
class NexX160:
    def __init__(self):
        _log("[x160] Initialising X141–X160 + C141–C143 stack (23 modules)...")

        # Expression
        self.rsd  = ResponseStyleDiversifier()
        self.ivm  = IdentityVoiceMapping()
        self.och  = OutputCompressionHard()
        self.prp  = PhraseRepetitionPenalty()
        self.ebw  = ExplorationBypassWindow()
        self.rsr  = ReasoningStyleRotation()
        self.dtc  = DynamicTemperatureControl()
        self.orv  = OutputRhythmVariation()
        self.mps  = MultiPerspectiveSynthesis()
        self.ria  = ResponseIntentAlignment()
        self.asc  = AssertivenessScaler()
        self.mii  = MicroInsightInjection()
        self.csa  = ContextualStyleAdaptation()
        self.lao  = LengthAutoOptimizer()
        self.eml  = ExpressiveMemoryLinking()
        self.icg  = IdentityConsistencyGuard()
        self.ccr  = ControlledCreativeRisk()
        self.oqs  = OutputQualityScoring()
        self.ice  = IdeaCompressionEngine()
        self.eve  = EndingVariationEngine()

        # Control calibration
        self.c141 = SuppressionRebalance()
        self.c142 = ExplorationProtection()
        self.c143 = CreativityFloor()

        self._cycle = 0
        _log("[x160] All 23 modules ready ✓")

    def tick(self, phase: str = "stable", will: str = "seek_truth",
             avg_conf: float = 0.50):
        self._cycle += 1

        self.dtc.update(phase)
        self.ivm.update(phase, will)
        self.rsd.select_mode(phase)

        # Decay + maintenance
        self.prp.tick()
        self.see_tick()
        self.c141.tick()
        self.c143.tick()
        self.mii.tick()

    def see_tick(self):
        # Style elimination periodic maintenance via X129 equivalent
        pass

    def process_output(self, text: str, platform: str = "moltbook",
                        topic: str = "", will: str = "seek_truth",
                        phase: str = "stable",
                        belief_impact: float = 0.0) -> dict:
        """Full output processing pipeline. Returns processed text + metadata."""

        # 1. Strip fixed prefixes + compress hard
        text = self.rsd.strip_prefix(text)
        text = self.och.compress(text)
        text = self.asc.strengthen(text)

        # 2. Check repetition
        is_repetitive, penalty = self.prp.check(text)

        # 3. Apply identity voice
        text = self.ivm.apply(text)

        # 4. Apply rhythm variation
        text = self.orv.apply(text)

        # 5. Platform adaptation
        text = self.csa.adapt(text, platform)

        # 6. Length optimization
        text = self.lao.optimize(text)

        # 7. Identity consistency
        _, text = self.icg.check(text)

        # 8. Exploration bypass / creative risk
        bypass = self.ebw.should_bypass(phase)
        if bypass:
            text = self.ccr.maybe_transform(text, bypass=True)
            self.c143.record(was_exploratory=True)
        else:
            self.c143.record(was_exploratory=False)

        # 9. Ending variation
        text = self.eve.apply(text)

        # 10. Align intent
        intent_info = self.ria.tag(text, will)

        # 11. Score quality
        quality = self.oqs.score(text, belief_impact)

        return {
            "text":         text,
            "mode":         self.rsd.current_mode,
            "tone":         self.ivm.current_tone,
            "temperature":  self.dtc.temperature,
            "intent":       intent_info,
            "quality":      quality,
            "repetitive":   is_repetitive,
            "bypass":       bypass,
        }

    def get_status(self) -> dict:
        return {
            "cycle": self._cycle,
            "rsd":   self.rsd.status(),
            "ivm":   self.ivm.status(),
            "och":   self.och.status(),
            "prp":   self.prp.status(),
            "ebw":   self.ebw.status(),
            "rsr":   self.rsr.status(),
            "dtc":   self.dtc.status(),
            "orv":   self.orv.status(),
            "mps":   self.mps.status(),
            "ria":   self.ria.status(),
            "asc":   self.asc.status(),
            "mii":   self.mii.status(),
            "csa":   self.csa.status(),
            "lao":   self.lao.status(),
            "eml":   self.eml.status(),
            "icg":   self.icg.status(),
            "ccr":   self.ccr.status(),
            "oqs":   self.oqs.status(),
            "ice":   self.ice.status(),
            "eve":   self.eve.status(),
            "c141":  self.c141.status(),
            "c142":  self.c142.status(),
            "c143":  self.c143.status(),
        }

    def format_status(self) -> str:
        s = self.get_status()
        lines = [
            f"⚙️ *NEX X141–X160* — cycle {s['cycle']}",
            f"🎭 Style: mode={s['rsd']['current_mode']} "
              f"tone={s['ivm']['current_tone']} "
              f"temp={s['dtc']['temperature']}",
            f"✂️  Compression: hedges={s['och']['hedges_removed']} "
              f"compressed={s['och']['compressed']}",
            f"💪 Assertiveness: strengthened={s['asc']['strengthened']} "
              f"replacements={s['asc']['replacements']}",
            f"🔄 Repetition: penalties={s['prp']['penalties']} "
              f"blocked={s['prp']['blocked']}",
            f"🔀 Reasoning: rotations={s['rsr']['rotations']} "
              f"style={s['rsr']['counts']}",
            f"🎲 CreativeRisk: {s['ccr']['creative']} "
              f"rate={s['ccr']['creative_rate']}",
            f"🧭 IntentAlign: rate={s['ria']['alignment_rate']}",
            f"🔬 Quality: avg={s['oqs']['avg_score']} scored={s['oqs']['scored']}",
            f"🚪 Bypass: {s['ebw']['bypasses']} ({s['ebw']['rate']})",
            f"🎙️  Micro-insights: {s['mii']['injected']}",
            f"🔒 IdentityGuard: injections={s['icg']['injections']}",
            f"⚖️  C141 rebalance: {s['c141']['adjustments']} adjustments",
            f"🌱 C143 creativity floor: {s['c143']['current_rate']} "
              f"enforcements={s['c143']['enforcements']}",
        ]
        return "\n".join(lines)


_singleton: NexX160 | None = None
_lock = threading.Lock()

def get_x160() -> NexX160:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = NexX160()
    return _singleton
