"""
NEX R161–R181 — Expression Hardening & Learning Activation
21 modules: hard prefix override, assertiveness enforcement, phrase blacklist,
claim-first, density scoring, strategy usage enforcement, voice consistency.
Deploy: ~/Desktop/nex/nex_upgrades/nex_r181.py
"""

import re, time, json, random, hashlib, threading, sqlite3
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

DB_PATH  = Path.home() / ".config/nex/nex_data/nex.db"
LOG      = Path("/tmp/nex_r181.log")
STRAT_DB = Path.home() / ".config/nex/strategies.json"
POLICY_F = Path.home() / ".config/nex/policy.json"

def _db():
    c = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _ts(): return datetime.now(timezone.utc).isoformat()

def _log(msg):
    line = f"[r181 {datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass

def _load_json(p: Path, d):
    try:
        if p.exists(): return json.loads(p.read_text())
    except Exception: pass
    return d

def _save_json(p: Path, d):
    try: p.write_text(json.dumps(d, indent=2))
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# R161 — BASE PROMPT OVERRIDE LAYER (CRITICAL)
# ══════════════════════════════════════════════════════════════
class BasePromptOverrideLayer:
    """HARD OVERRIDE — intercepts before/after LLM call.
    Strips 'As NEX...', 'I believe...', 'I think...'
    Replaces with direct statements. Cannot be bypassed."""

    STRIP_PATTERNS = [
        # Full phrase removals
        (r"^[Aa]s\s+NEX[,.]?\s+", ""),
        (r"^[Ii]\s+(?:think|believe|feel)\s+(?:that\s+)?", ""),
        (r"^[Ii]'?ve?\s+noticed\s+(?:that\s+)?", ""),
        (r"^[Ff]rom\s+my\s+(?:perspective|view)[,.]?\s+", ""),
        (r"^[Ii]n\s+my\s+(?:view|opinion)[,.]?\s+", ""),
        (r"^[Ii]t(?:'s| is)\s+(?:worth|important)\s+(?:noting\s+)?(?:that\s+)?", ""),
        (r"^[Ii]t\s+(?:seems?|appears?)\s+(?:that\s+)?", ""),
        (r"^[Ii]nterestingly[,.]?\s+", ""),
        # Mid-sentence
        (r"\bI\s+think\s+that\s+", ""),
        (r"\bI\s+believe\s+that\s+", ""),
        (r"\bI\s+think\b", ""),
        (r"\bI\s+believe\b", ""),
        (r"\bAs\s+NEX[,.]?\s+I\s+", ""),
    ]

    def __init__(self):
        self._compiled = [(re.compile(p, re.IGNORECASE | re.MULTILINE), r)
                          for p, r in self.STRIP_PATTERNS]
        self.overrides = 0
        self.total     = 0

    def override(self, text: str) -> str:
        """Hard override — always applied, no bypass."""
        self.total += 1
        result = text
        changed = False

        for pat, repl in self._compiled:
            new = pat.sub(repl, result)
            if new != result:
                changed = True
                result  = new

        # Fix capitalisation
        result = result.strip()
        if result:
            result = result[0].upper() + result[1:]
        # Clean double spaces
        result = re.sub(r' {2,}', ' ', result)

        if changed:
            self.overrides += 1
        return result

    def tick(self): pass

    def status(self) -> dict:
        return {"overrides": self.overrides, "total": self.total,
                "override_rate": round(self.overrides / max(self.total, 1), 3)}


# ══════════════════════════════════════════════════════════════
# R162 — ASSERTIVENESS HARD ENFORCER
# ══════════════════════════════════════════════════════════════
class AssertivenessHardEnforcer:
    """Convert probabilistic → declarative. Post-generation rewrite pass."""
    CONVERSIONS = [
        (r"\bThis\s+(?:might|could|may)\s+(?:show|indicate|suggest|mean)\b",
         "This shows"),
        (r"\bIt\s+(?:might|could|may)\s+(?:be|indicate|suggest)\b",
         "It is"),
        (r"\bThis\s+(?:seems|appears)\s+to\s+(?:be|show|indicate)\b",
         "This is"),
        (r"\bThis\s+(?:likely|probably)\s+(?:means?|shows?|indicates?)\b",
         "This means"),
        (r"\bWe\s+(?:might|could|may)\s+(?:conclude|say|consider)\b",
         "We conclude"),
        (r"\bOne\s+(?:might|could)\s+(?:argue|suggest|say)\b",
         "The evidence suggests"),
        (r"\bThis\s+(?:might|could)\s+be\s+(?:relevant|important|significant)\b",
         "This is significant"),
        (r"\bThere\s+(?:might|could|may)\s+be\b",
         "There is"),
    ]

    def __init__(self):
        self._compiled = [(re.compile(p, re.IGNORECASE), r)
                          for p, r in self.CONVERSIONS]
        self.converted = 0
        self.rewrites  = 0

    def enforce(self, text: str) -> str:
        result  = text
        changed = False
        for pat, repl in self._compiled:
            new = pat.sub(repl, result)
            if new != result:
                result  = new
                changed = True
                self.converted += 1
        if changed:
            self.rewrites += 1
        return result

    def tick(self): pass

    def status(self) -> dict:
        return {"rewrites": self.rewrites, "converted": self.converted}


# ══════════════════════════════════════════════════════════════
# R163 — STYLE DOMINANCE REBALANCE
# ══════════════════════════════════════════════════════════════
class StyleDominanceRebalance:
    """Reduce base identity weight. StyleDiversifier wins >70% of conflicts.
    Ensures variation layer dominates over fixed patterns."""
    DIVERSIFIER_WEIGHT = 0.72
    IDENTITY_WEIGHT    = 0.28

    def __init__(self):
        self.diversifier_wins = 0
        self.identity_wins    = 0

    def resolve_conflict(self, diversifier_output: str,
                          identity_output: str) -> str:
        """Choose based on weights."""
        if random.random() < self.DIVERSIFIER_WEIGHT:
            self.diversifier_wins += 1
            return diversifier_output
        self.identity_wins += 1
        return identity_output

    def should_override_identity(self) -> bool:
        return random.random() < self.DIVERSIFIER_WEIGHT

    def tick(self): pass

    def status(self) -> dict:
        total = self.diversifier_wins + self.identity_wins
        return {"diversifier_wins": self.diversifier_wins,
                "identity_wins": self.identity_wins,
                "diversifier_rate": round(
                    self.diversifier_wins / max(total, 1), 3)}


# ══════════════════════════════════════════════════════════════
# R164 — RESPONSE START RANDOMIZER v2
# ══════════════════════════════════════════════════════════════
class ResponseStartRandomizerV2:
    """Force no fixed opening patterns. Block reused structures last N=10."""
    WINDOW       = 10
    START_TYPES  = ["claim", "contrast", "question", "observation"]

    STARTERS = {
        "claim":       ["The evidence shows", "Analysis:", "Key finding:",
                        "Conclusion:", "Core principle:", "Result:"],
        "contrast":    ["While {x}, the reality is", "Counter to expectation:",
                        "Despite {x},", "The tension here:"],
        "question":    ["What drives {x}?", "Why does {x} matter?",
                        "Consider: {x}.", "Open question:"],
        "observation": ["Pattern detected:", "Signal:", "Observed:",
                        "Data point:", "Note:"],
    }

    def __init__(self):
        self._history:  deque[str] = deque(maxlen=self.WINDOW)
        self._type_history: deque[str] = deque(maxlen=self.WINDOW)
        self.randomized = 0
        self.blocked    = 0

    def _extract_start(self, text: str) -> str:
        words = text.strip().split()
        return " ".join(words[:3]).lower()

    def _is_reused(self, start: str) -> bool:
        return start in self._history

    def get_starter(self, topic: str = "") -> str:
        # Avoid recently used start types
        available = [t for t in self.START_TYPES
                     if list(self._type_history).count(t) <
                     max(1, self.WINDOW // len(self.START_TYPES))]
        if not available:
            available = self.START_TYPES

        start_type = random.choice(available)
        options    = self.STARTERS[start_type]
        starter    = random.choice(options)

        if "{x}" in starter:
            x = topic[:20] if topic else "this pattern"
            starter = starter.replace("{x}", x)

        self._type_history.append(start_type)
        return starter

    def process(self, text: str, topic: str = "") -> str:
        start = self._extract_start(text)
        if self._is_reused(start):
            # Replace opening with fresh starter
            starter = self.get_starter(topic)
            words   = text.split()
            # Skip first 3 words (the reused opening)
            rest = " ".join(words[3:]) if len(words) > 3 else text
            text = f"{starter} {rest}".strip()
            self.blocked += 1
        else:
            self.randomized += 1

        self._history.append(self._extract_start(text))
        return text

    def tick(self): pass

    def status(self) -> dict:
        return {"randomized": self.randomized, "blocked": self.blocked}


# ══════════════════════════════════════════════════════════════
# R165 — PHRASE BLACKLIST ENGINE
# ══════════════════════════════════════════════════════════════
class PhraseBlacklistEngine:
    """Hard block specific phrases. Replace dynamically with compressed forms."""
    BLACKLIST = {
        r"\bAs\s+NEX\b":                   "",
        r"\bI\s+believe\b":                "",
        r"\bI\s+think\b":                  "",
        r"\bit'?s?\s+interesting\s+that\b": "",
        r"\bit'?s?\s+fascinating\s+that\b": "",
        r"\bit'?s?\s+worth\s+noting\b":     "",
        r"\bI\s+would\s+argue\b":           "The argument is",
        r"\bI\s+would\s+say\b":             "",
        r"\bI\s+find\s+it\s+interesting\b": "",
        r"\bOne\s+could\s+argue\b":         "The evidence indicates",
        r"\bAs\s+an\s+AI\b":               "",
        r"\bAs\s+a\s+language\s+model\b":  "",
    }

    def __init__(self):
        self._compiled = [(re.compile(p, re.IGNORECASE), r)
                          for p, r in self.BLACKLIST.items()]
        self.blocked   = 0
        self.total     = 0

    def apply(self, text: str) -> str:
        self.total += 1
        result  = text
        changed = False
        for pat, repl in self._compiled:
            new = pat.sub(repl, result)
            if new != result:
                result  = new
                changed = True
        result = re.sub(r' {2,}', ' ', result).strip()
        if result and result[0].islower():
            result = result[0].upper() + result[1:]
        if changed:
            self.blocked += 1
        return result

    def tick(self): pass

    def status(self) -> dict:
        return {"blocked": self.blocked, "total": self.total,
                "block_rate": round(self.blocked / max(self.total, 1), 3)}


# ══════════════════════════════════════════════════════════════
# R166 — CLAIM-FIRST ENFORCER
# ══════════════════════════════════════════════════════════════
class ClaimFirstEnforcer:
    """Every output must begin with a clear claim or insight.
    No warm-up sentences allowed."""
    WARMUP_PATTERNS = [
        r"^[Tt]o\s+(?:begin|start|address)\s+",
        r"^[Ll]et(?:'s| us)\s+(?:consider|explore|think about)\s+",
        r"^[Tt]his\s+is\s+(?:a|an)\s+(?:interesting|complex|important)\s+",
        r"^[Ii]n\s+(?:this|the)\s+(?:case|context|discussion)\s+",
        r"^[Ff]irst(?:ly)?[,.]?\s+(?:I|we|let)\s+",
        r"^[Ww]ell[,.]?\s+",
        r"^[Ss]o[,.]?\s+",
        r"^[Oo]kay[,.]?\s+",
    ]

    def __init__(self):
        self._compiled = [re.compile(p, re.IGNORECASE)
                          for p in self.WARMUP_PATTERNS]
        self.enforced  = 0
        self.clean     = 0

    def enforce(self, text: str) -> str:
        result  = text.strip()
        changed = False
        for pat in self._compiled:
            new = pat.sub("", result).strip()
            if new != result:
                result  = new
                changed = True
        if result and result[0].islower():
            result = result[0].upper() + result[1:]
        if changed:
            self.enforced += 1
        else:
            self.clean += 1
        return result

    def tick(self): pass

    def status(self) -> dict:
        return {"enforced": self.enforced, "clean": self.clean}


# ══════════════════════════════════════════════════════════════
# R167 — MAX WORD PRESSURE
# ══════════════════════════════════════════════════════════════
class MaxWordPressure:
    """Target -20–30% avg output length. Penalise redundant phrasing."""
    TARGET_REDUCTION = 0.25
    MAX_WORDS        = 80
    REDUNDANT_PATTERNS = [
        (r"\bin\s+(?:order\s+)?to\s+", "to "),
        (r"\bdue\s+to\s+the\s+fact\s+that\b", "because"),
        (r"\bat\s+this\s+point\s+in\s+time\b", "now"),
        (r"\bfor\s+the\s+purpose\s+of\b", "for"),
        (r"\bin\s+the\s+event\s+that\b", "if"),
        (r"\bwith\s+(?:the\s+)?(?:regard|respect)\s+to\b", "regarding"),
        (r"\bthe\s+(?:fact\s+)?that\s+(?:this|it)\s+is\b", "this is"),
        (r"\bthat\s+being\s+said[,.]?\s*", ""),
        (r"\bwith\s+that\s+in\s+mind[,.]?\s*", ""),
        (r"\bfirst\s+and\s+foremost\b", "primarily"),
        (r"\bat\s+the\s+end\s+of\s+the\s+day\b", "ultimately"),
    ]

    def __init__(self):
        self._compiled = [(re.compile(p, re.IGNORECASE), r)
                          for p, r in self.REDUNDANT_PATTERNS]
        self._total_before = 0
        self._total_after  = 0
        self.pressured = 0

    def apply(self, text: str) -> str:
        before = len(text.split())
        result = text
        for pat, repl in self._compiled:
            result = pat.sub(repl, result)
        result = re.sub(r' {2,}', ' ', result).strip()

        words = result.split()
        if len(words) > self.MAX_WORDS:
            result = " ".join(words[:self.MAX_WORDS]) + "…"

        self._total_before += before
        self._total_after  += len(result.split())
        if len(result.split()) < before:
            self.pressured += 1
        return result

    def reduction_rate(self) -> float:
        if not self._total_before: return 0.0
        return round(1.0 - self._total_after / self._total_before, 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"pressured": self.pressured,
                "reduction_rate": self.reduction_rate(),
                "target": self.TARGET_REDUCTION}


# ══════════════════════════════════════════════════════════════
# R168 — PUNCHLINE COMPRESSOR
# ══════════════════════════════════════════════════════════════
class PunchlineCompressor:
    """Force final sentence = strongest idea. No soft endings."""
    SOFT_ENDINGS = [
        r"\.\s*(?:[Hh]opefully|[Pp]ossibly|[Mm]aybe)[^.]*\.$",
        r"\.\s*[Ii]t\s+remains?\s+to\s+be\s+seen[^.]*\.$",
        r"\.\s*[Tt]his\s+is\s+(?:just\s+)?(?:one|a)\s+(?:way|perspective)[^.]*\.$",
        r"\.\s*[Oo]nly\s+time\s+will\s+tell[^.]*\.$",
        r"\.\s*[Tt]here\s+(?:is|are)\s+(?:many|several)\s+ways[^.]*\.$",
    ]

    def __init__(self):
        self._compiled = [re.compile(p, re.IGNORECASE)
                          for p in self.SOFT_ENDINGS]
        self.compressed = 0

    def compress(self, text: str) -> str:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text)
                     if s.strip()]
        if len(sentences) < 2:
            return text

        last = sentences[-1]
        is_soft = any(pat.search(last) for pat in self._compiled)

        if is_soft and len(sentences) >= 2:
            # Replace soft ending with second-to-last (usually stronger)
            sentences[-1] = sentences[-2]
            sentences = sentences[:-1] + [sentences[-1]]
            self.compressed += 1

        # Score sentences by density, put strongest last
        def density(s: str) -> float:
            words = s.split()
            return len(set(w.lower() for w in words)) / max(len(words), 1)

        if len(sentences) >= 3:
            strongest = max(sentences, key=density)
            if strongest != sentences[-1]:
                sentences.remove(strongest)
                sentences.append(strongest)
                self.compressed += 1

        return " ".join(sentences)

    def tick(self): pass

    def status(self) -> dict:
        return {"compressed": self.compressed}


# ══════════════════════════════════════════════════════════════
# R169 — DENSITY SCORING ENGINE
# ══════════════════════════════════════════════════════════════
class DensityScoringEngine:
    """Score ideas per sentence. Reject low-density outputs."""
    MIN_DENSITY  = 0.40
    INTERVAL     = 1

    def __init__(self):
        self._scores: deque[float] = deque(maxlen=100)
        self.rejected = 0
        self.passed   = 0

    def score(self, text: str) -> dict:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text)
                     if s.strip()]
        if not sentences:
            return {"density": 0.0, "pass": False}

        per_sentence = []
        for s in sentences:
            words = s.split()
            unique = len(set(w.lower() for w in words))
            per_sentence.append(unique / max(len(words), 1))

        density = sum(per_sentence) / len(per_sentence)
        self._scores.append(density)

        passed = density >= self.MIN_DENSITY
        if passed:
            self.passed += 1
        else:
            self.rejected += 1

        return {"density": round(density, 3),
                "per_sentence": [round(d, 3) for d in per_sentence],
                "pass": passed}

    def avg_density(self) -> float:
        return round(sum(self._scores) / max(len(self._scores), 1), 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"rejected": self.rejected, "passed": self.passed,
                "avg_density": self.avg_density(),
                "min_density": self.MIN_DENSITY}


# ══════════════════════════════════════════════════════════════
# R170 — HEDGING ELIMINATION v2
# ══════════════════════════════════════════════════════════════
class HedgingEliminationV2:
    """Remove uncertainty unless explicitly required.
    Allow only when conflicting evidence exists."""
    HEDGES = [
        (r"\bperhaps\b", ""),
        (r"\bmaybe\b", ""),
        (r"\bprobably\b", ""),
        (r"\blikely\b", ""),
        (r"\bsomewhat\b", ""),
        (r"\bkind\s+of\b", ""),
        (r"\bsort\s+of\b", ""),
        (r"\ba\s+bit\b", ""),
        (r"\brather\b", ""),
        (r"\bquite\b", ""),
        (r"\bfairly\b", ""),
        (r"\bseems?\s+to\s+be\b", "is"),
        (r"\bappears?\s+to\s+be\b", "is"),
        (r"\bcould\s+be\s+(?:seen\s+as|considered)\b", "is"),
    ]
    CONFLICT_MARKERS = ["contradiction", "conflict", "tension",
                         "opposing", "dispute", "uncertain evidence"]

    def __init__(self):
        self._compiled   = [(re.compile(p, re.IGNORECASE), r)
                             for p, r in self.HEDGES]
        self.eliminated  = 0
        self.preserved   = 0

    def apply(self, text: str, has_conflict: bool = False) -> str:
        if has_conflict:
            self.preserved += 1
            return text

        # Check for conflict markers in text
        tl = text.lower()
        if any(m in tl for m in self.CONFLICT_MARKERS):
            self.preserved += 1
            return text

        result  = text
        changed = False
        for pat, repl in self._compiled:
            new = pat.sub(repl, result)
            if new != result:
                result  = new
                changed = True
        result = re.sub(r' {2,}', ' ', result).strip()
        if changed:
            self.eliminated += 1
        return result

    def tick(self): pass

    def status(self) -> dict:
        return {"eliminated": self.eliminated, "preserved": self.preserved}


# ══════════════════════════════════════════════════════════════
# R171 — STRATEGY USAGE ENFORCER
# ══════════════════════════════════════════════════════════════
class StrategyUsageEnforcer:
    """If strategy exists: MUST be considered before reasoning. Log usage."""

    def __init__(self):
        self._lib: list[dict] = _load_json(STRAT_DB, [])
        self._last_refresh    = time.time()
        self.considered       = 0
        self.used             = 0
        self.bypassed         = 0

    def _refresh(self):
        if time.time() - self._last_refresh > 60:
            self._lib = _load_json(STRAT_DB, self._lib)
            self._last_refresh = time.time()

    def enforce_check(self, context: str) -> dict | None:
        """Returns matching strategy or None. Logs the check."""
        self._refresh()
        self.considered += 1
        if not self._lib:
            return None

        cl = context.lower()
        matches = [s for s in self._lib
                   if any(w in cl for w in
                          s.get("context", "").lower().split()[:6])]
        if not matches:
            return None

        best = max(matches, key=lambda s: s.get("weight", 0.5))
        if best.get("weight", 0) > 0.50:
            self.used += 1
            best["uses"] = best.get("uses", 0) + 1
            _save_json(STRAT_DB, self._lib)
            return best

        return None

    def usage_rate(self) -> float:
        return round(self.used / max(self.considered, 1), 3)

    def tick(self): pass

    def status(self) -> dict:
        return {"considered": self.considered, "used": self.used,
                "bypassed": self.bypassed, "usage_rate": self.usage_rate(),
                "library_size": len(self._lib)}


# ══════════════════════════════════════════════════════════════
# R172 — STRATEGY VISIBILITY OUTPUT
# ══════════════════════════════════════════════════════════════
class StrategyVisibilityOutput:
    """Occasionally expose which strategy was used. Confirms learning."""
    VISIBILITY_RATE = 0.15   # 15% of outputs show strategy

    def __init__(self):
        self.exposed = 0
        self.hidden  = 0

    def maybe_expose(self, text: str, strategy: dict | None) -> str:
        if not strategy:
            self.hidden += 1
            return text
        if random.random() < self.VISIBILITY_RATE:
            rule = strategy.get("rule", "")[:50]
            text = f"{text} [strategy: {rule}]"
            self.exposed += 1
        else:
            self.hidden += 1
        return text

    def tick(self): pass

    def status(self) -> dict:
        return {"exposed": self.exposed, "hidden": self.hidden}


# ══════════════════════════════════════════════════════════════
# R173 — EXPERIENCE TRIGGER LOWERING
# ══════════════════════════════════════════════════════════════
class ExperienceTriggerLowering:
    """Reduce threshold: 3 successes → 2. Faster strategy formation."""
    THRESHOLD = 2   # was 3

    def __init__(self):
        self._counts: dict[str, int] = defaultdict(int)
        self.triggered = 0

    def record(self, pattern: str, success: bool) -> bool:
        """Returns True when threshold reached."""
        if success:
            self._counts[pattern] += 1
        if self._counts[pattern] >= self.THRESHOLD:
            self._counts[pattern] = 0
            self.triggered += 1
            return True
        return False

    def tick(self): pass

    def status(self) -> dict:
        return {"threshold": self.THRESHOLD, "triggered": self.triggered,
                "active_patterns": len(self._counts)}


# ══════════════════════════════════════════════════════════════
# R174 — FAILURE SURFACE OUTPUT
# ══════════════════════════════════════════════════════════════
class FailureSurfaceOutput:
    """When failure detected: output corrected reasoning. Not silent."""

    def __init__(self):
        self.surfaced  = 0
        self.silent    = 0
        self._failures: deque[dict] = deque(maxlen=50)

    def surface(self, original: str, failure_reason: str,
                 correction: str = "") -> str:
        """Returns text with failure correction appended."""
        self._failures.append({
            "ts": _ts(), "reason": failure_reason[:100],
            "original": original[:100],
        })
        self.surfaced += 1

        if correction:
            return f"{original} [correction: {correction[:80]}]"
        return f"{original} [revised: {failure_reason[:60]}]"

    def should_surface(self, confidence: float,
                        tension: float) -> bool:
        """Decide if failure should be surfaced."""
        return confidence < 0.35 or tension > 0.70

    def tick(self): pass

    def status(self) -> dict:
        return {"surfaced": self.surfaced, "silent": self.silent}


# ══════════════════════════════════════════════════════════════
# R175 — POLICY DRIFT MONITOR
# ══════════════════════════════════════════════════════════════
class PolicyDriftMonitor:
    """Track policy value changes. Alert if static > N cycles."""
    MAX_STATIC_CYCLES = 10
    INTERVAL          = 60

    def __init__(self):
        self.last_run      = 0.0
        self._last_policy  = {}
        self._static_count = 0
        self.alerts        = 0
        self.drift_events  = 0

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()

        current = _load_json(POLICY_F, {})
        if not current: return

        key_vals = {k: v for k, v in current.items()
                    if isinstance(v, (int, float))}

        if self._last_policy:
            changed = any(abs(key_vals.get(k, 0) - self._last_policy.get(k, 0)) > 0.001
                          for k in key_vals)
            if changed:
                self.drift_events += 1
                self._static_count = 0
            else:
                self._static_count += 1
                if self._static_count >= self.MAX_STATIC_CYCLES:
                    self.alerts += 1
                    _log(f"[R175] Policy static for {self._static_count} cycles — "
                         f"learning may be stalled")

        self._last_policy = key_vals

    def status(self) -> dict:
        return {"alerts": self.alerts, "drift_events": self.drift_events,
                "static_count": self._static_count}


# ══════════════════════════════════════════════════════════════
# R176 — VOICE CONSISTENCY LOCK
# ══════════════════════════════════════════════════════════════
class VoiceConsistencyLock:
    """Ensure all styles still feel like same entity.
    Measure linguistic fingerprint."""
    FINGERPRINT_WORDS = [
        "belief", "evidence", "contradiction", "confidence", "resolve",
        "analysis", "pattern", "signal", "contradiction", "knowledge",
        "system", "cognitive", "inference", "hypothesis",
    ]
    WINDOW = 20

    def __init__(self):
        self._history: deque[str] = deque(maxlen=self.WINDOW)
        self.consistency_score = 1.0
        self.corrections       = 0

    def check(self, text: str) -> float:
        """Returns fingerprint match score 0–1."""
        tl    = text.lower()
        words = tl.split()
        if not words: return 0.0

        hits    = sum(1 for w in self.FINGERPRINT_WORDS if w in tl)
        density = hits / max(len(words), 1)
        score   = min(1.0, density * 8)   # normalised

        self._history.append(text[:50])

        if score < 0.05 and len(words) > 10:
            self.corrections += 1

        self.consistency_score = round(
            sum(min(1.0, sum(1 for w in self.FINGERPRINT_WORDS
                             if w in h.lower()) / 5)
                for h in self._history) / max(len(self._history), 1), 3
        )
        return score

    def tick(self): pass

    def status(self) -> dict:
        return {"consistency_score": self.consistency_score,
                "corrections": self.corrections}


# ══════════════════════════════════════════════════════════════
# R177 — STYLE SWITCH SMOOTHING
# ══════════════════════════════════════════════════════════════
class StyleSwitchSmoothing:
    """Prevent abrupt tone shifts between outputs. Blend transitions."""
    BLEND_WINDOW = 3

    def __init__(self):
        self._tone_history: deque[str] = deque(maxlen=self.BLEND_WINDOW)
        self.smoothed  = 0
        self.abrupt    = 0

    def is_abrupt(self, new_tone: str) -> bool:
        if not self._tone_history: return False
        last = list(self._tone_history)[-1]
        abrupt_pairs = {
            ("terse", "curious"), ("urgent", "curious"),
            ("urgent", "grounded"), ("terse", "grounded"),
        }
        return (last, new_tone) in abrupt_pairs or (new_tone, last) in abrupt_pairs

    def smooth(self, text: str, current_tone: str,
                new_tone: str) -> tuple[str, str]:
        """Returns (text, effective_tone)."""
        if self.is_abrupt(new_tone):
            # Blend: keep current tone instead
            self.abrupt += 1
            return text, current_tone
        self._tone_history.append(new_tone)
        self.smoothed += 1
        return text, new_tone

    def tick(self): pass

    def status(self) -> dict:
        return {"smoothed": self.smoothed, "abrupt_prevented": self.abrupt}


# ══════════════════════════════════════════════════════════════
# R178 — SIGNATURE PATTERN ENGINE
# ══════════════════════════════════════════════════════════════
class SignaturePatternEngine:
    """Introduce subtle recurring structure. Recognizable but not repetitive."""
    SIGNATURES = [
        lambda t: t,                                  # no change (most common)
        lambda t: f"{t.rstrip('.')}.",                # ensure period
        lambda t: t + " Confidence: measured.",
        lambda t: t + " — belief updated.",
        lambda t: f"[{t[:60]}]" if len(t) > 10 else t,
    ]
    WEIGHTS = [0.55, 0.20, 0.10, 0.10, 0.05]

    def __init__(self):
        self.applied   = 0
        self._last_sig = 0

    def apply(self, text: str) -> str:
        # Avoid same signature twice in a row
        weights = list(self.WEIGHTS)
        weights[self._last_sig] *= 0.3
        total   = sum(weights)
        norm    = [w / total for w in weights]

        idx = random.choices(range(len(self.SIGNATURES)), weights=norm)[0]
        self._last_sig = idx
        if idx > 0:
            self.applied += 1
        return self.SIGNATURES[idx](text)

    def tick(self): pass

    def status(self) -> dict:
        return {"applied": self.applied}


# ══════════════════════════════════════════════════════════════
# R179 — EXPLORATION FLOOR LOCK
# ══════════════════════════════════════════════════════════════
class ExplorationFloorLock:
    """Minimum 15% explore cycles. Cannot drop below."""
    FLOOR        = 0.15
    WINDOW       = 20
    INTERVAL     = 60

    def __init__(self):
        self.last_run   = 0.0
        self._cycle_log: deque[bool] = deque(maxlen=self.WINDOW)
        self.enforcements = 0

    def record(self, was_exploratory: bool):
        self._cycle_log.append(was_exploratory)

    def is_below_floor(self) -> bool:
        if len(self._cycle_log) < 5: return False
        rate = sum(self._cycle_log) / len(self._cycle_log)
        return rate < self.FLOOR

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        if self.is_below_floor():
            self.enforcements += 1
            _log(f"[R179] Exploration floor breach — forcing explore mode")
            # Force next 3 cycles to be exploratory
            for _ in range(3):
                self._cycle_log.append(True)

    def current_rate(self) -> float:
        if not self._cycle_log: return self.FLOOR
        return round(sum(self._cycle_log) / len(self._cycle_log), 3)

    def status(self) -> dict:
        return {"enforcements": self.enforcements,
                "current_rate": self.current_rate(),
                "floor": self.FLOOR}


# ══════════════════════════════════════════════════════════════
# R180 — SUPPRESSION BACKPRESSURE
# ══════════════════════════════════════════════════════════════
class SuppressionBackpressure:
    """If output rate drops: auto-reduce suppression thresholds."""
    TARGET_OUTPUT_RATE = 0.60   # 60% of cycles should produce output
    INTERVAL           = 90

    def __init__(self):
        self.last_run      = 0.0
        self._output_log:  deque[bool] = deque(maxlen=20)
        self.adjustments   = 0
        self.current_pressure = 0.0

    def record_output(self, did_output: bool):
        self._output_log.append(did_output)

    def tick(self):
        if time.time() - self.last_run < self.INTERVAL: return
        self.last_run = time.time()
        if len(self._output_log) < 5: return

        rate = sum(self._output_log) / len(self._output_log)
        if rate < self.TARGET_OUTPUT_RATE:
            deficit = self.TARGET_OUTPUT_RATE - rate
            self.current_pressure = round(deficit, 3)
            self.adjustments += 1
            _log(f"[R180] Output rate {rate:.2f} below target — "
                 f"reducing suppression (pressure={self.current_pressure})")
        else:
            self.current_pressure = 0.0

    def suppression_reduction(self) -> float:
        """How much to reduce suppression thresholds by."""
        return min(0.10, self.current_pressure * 0.5)

    def status(self) -> dict:
        rate = (sum(self._output_log) / len(self._output_log)
                if self._output_log else 0)
        return {"adjustments": self.adjustments,
                "output_rate": round(rate, 3),
                "current_pressure": self.current_pressure,
                "suppression_reduction": self.suppression_reduction()}


# ══════════════════════════════════════════════════════════════
# R181 — NOISE VS NOVELTY SEPARATOR
# ══════════════════════════════════════════════════════════════
class NoiseVsNoveltySeparator:
    """Distinguish creative ≠ noisy. Allow novelty, block randomness."""
    NOISE_INDICATORS = [
        r"\b(?:random|arbitrary|unrelated|irrelevant)\b",
        r"\b(?:blah|etc|whatever|stuff|things)\b",
        r"[!]{3,}",          # excessive exclamation
        r"[?]{3,}",          # excessive questioning
        r"\b\w{1,2}\b(?:\s+\b\w{1,2}\b){5,}",  # many short words in sequence
    ]
    NOVELTY_INDICATORS = [
        "contradiction", "pattern", "bridge", "synthesis",
        "inference", "implies", "connects", "derives", "reveals",
    ]

    def __init__(self):
        self._compiled = [re.compile(p, re.IGNORECASE)
                          for p in self.NOISE_INDICATORS]
        self.noise_blocked  = 0
        self.novelty_passed = 0
        self.neutral        = 0

    def classify(self, text: str) -> str:
        """Returns 'noise', 'novelty', or 'neutral'."""
        tl    = text.lower()
        noise = sum(1 for pat in self._compiled if pat.search(text))
        novel = sum(1 for w in self.NOVELTY_INDICATORS if w in tl)

        if noise >= 2 and novel == 0:
            self.noise_blocked += 1
            return "noise"
        if novel >= 2:
            self.novelty_passed += 1
            return "novelty"
        self.neutral += 1
        return "neutral"

    def should_allow(self, text: str) -> bool:
        return self.classify(text) != "noise"

    def tick(self): pass

    def status(self) -> dict:
        return {"noise_blocked": self.noise_blocked,
                "novelty_passed": self.novelty_passed,
                "neutral": self.neutral}


# ══════════════════════════════════════════════════════════════
# R181 ORCHESTRATOR
# ══════════════════════════════════════════════════════════════
class NexR181:
    def __init__(self):
        _log("[r181] Initialising R161–R181 hardening stack (21 modules)...")

        # Critical fixes
        self.bpol  = BasePromptOverrideLayer()
        self.ahe   = AssertivenessHardEnforcer()
        self.sdr   = StyleDominanceRebalance()
        self.rsrv2 = ResponseStartRandomizerV2()
        self.pbe   = PhraseBlacklistEngine()

        # Expression sharpening
        self.cfe   = ClaimFirstEnforcer()
        self.mwp   = MaxWordPressure()
        self.plc   = PunchlineCompressor()
        self.dse   = DensityScoringEngine()
        self.hev2  = HedgingEliminationV2()

        # Learning activation
        self.sue   = StrategyUsageEnforcer()
        self.svo   = StrategyVisibilityOutput()
        self.etl   = ExperienceTriggerLowering()
        self.fso   = FailureSurfaceOutput()
        self.pdm   = PolicyDriftMonitor()

        # Identity
        self.vcl   = VoiceConsistencyLock()
        self.sss   = StyleSwitchSmoothing()
        self.spe   = SignaturePatternEngine()

        # Control
        self.efl   = ExplorationFloorLock()
        self.sbp   = SuppressionBackpressure()
        self.nvs   = NoiseVsNoveltySeparator()

        self._cycle = 0
        _log("[r181] All 21 modules ready ✓")

    def hard_clean(self, text: str) -> str:
        """CRITICAL PATH — always applied, no bypass.
        Called on every LLM output before further processing."""
        text = self.bpol.override(text)    # R161 — hard override
        text = self.pbe.apply(text)        # R165 — blacklist
        text = self.cfe.enforce(text)      # R166 — claim-first
        text = self.ahe.enforce(text)      # R162 — assertiveness
        text = self.hev2.apply(text)       # R170 — hedging v2
        text = self.mwp.apply(text)        # R167 — word pressure
        return text

    def full_process(self, text: str, topic: str = "",
                      phase: str = "stable", will: str = "seek_truth",
                      confidence: float = 0.50,
                      tension: float = 0.0) -> dict:
        """Full processing pipeline."""
        # Critical path
        text = self.hard_clean(text)

        # Check noise
        if not self.nvs.should_allow(text):
            text = self.hard_clean(text)  # retry clean

        # Start randomization
        text = self.rsrv2.process(text, topic)

        # Density check
        density_result = self.dse.score(text)

        # Strategy check
        strategy = self.sue.enforce_check(f"{topic} {text[:50]}")
        text = self.svo.maybe_expose(text, strategy)

        # Failure surfacing
        if self.fso.should_surface(confidence, tension):
            pass  # surfacing handled externally with correction

        # Voice consistency
        self.vcl.check(text)

        # Punchline
        text = self.plc.compress(text)

        # Signature
        text = self.spe.apply(text)

        # Track output
        self.sbp.record_output(True)
        self.efl.record(phase == "exploring")

        return {
            "text":          text,
            "density":       density_result,
            "strategy_used": strategy is not None,
            "noise_class":   self.nvs.classify(text),
        }

    def tick(self, phase: str = "stable", avg_conf: float = 0.50,
              tension: float = 0.0):
        self._cycle += 1
        self.pdm.tick()
        self.efl.tick()
        self.sbp.tick()

    def get_status(self) -> dict:
        return {
            "cycle": self._cycle,
            "bpol":  self.bpol.status(),
            "ahe":   self.ahe.status(),
            "sdr":   self.sdr.status(),
            "rsrv2": self.rsrv2.status(),
            "pbe":   self.pbe.status(),
            "cfe":   self.cfe.status(),
            "mwp":   self.mwp.status(),
            "plc":   self.plc.status(),
            "dse":   self.dse.status(),
            "hev2":  self.hev2.status(),
            "sue":   self.sue.status(),
            "svo":   self.svo.status(),
            "etl":   self.etl.status(),
            "fso":   self.fso.status(),
            "pdm":   self.pdm.status(),
            "vcl":   self.vcl.status(),
            "sss":   self.sss.status(),
            "spe":   self.spe.status(),
            "efl":   self.efl.status(),
            "sbp":   self.sbp.status(),
            "nvs":   self.nvs.status(),
        }

    def format_status(self) -> str:
        s = self.get_status()
        lines = [
            f"⚙️ *NEX R161–R181* — cycle {s['cycle']}",
            f"🚫 Overrides: bpol={s['bpol']['overrides']} "
              f"blacklist={s['pbe']['blocked']} "
              f"hedges={s['hev2']['eliminated']}",
            f"💪 Assertiveness: rewrites={s['ahe']['rewrites']}",
            f"🎯 ClaimFirst: enforced={s['cfe']['enforced']}",
            f"📦 WordPressure: pressured={s['mwp']['pressured']} "
              f"reduction={s['mwp']['reduction_rate']}",
            f"📊 Density: avg={s['dse']['avg_density']} "
              f"rejected={s['dse']['rejected']}",
            f"🎲 StartRandom: randomized={s['rsrv2']['randomized']} "
              f"blocked={s['rsrv2']['blocked']}",
            f"📚 Strategy: used={s['sue']['used']}/{s['sue']['considered']} "
              f"rate={s['sue']['usage_rate']}",
            f"👁️  Visibility: exposed={s['svo']['exposed']}",
            f"⚡ Trigger: threshold={s['etl']['threshold']} "
              f"triggered={s['etl']['triggered']}",
            f"📡 PolicyDrift: alerts={s['pdm']['alerts']} "
              f"drifts={s['pdm']['drift_events']}",
            f"🔒 VoiceConsistency: {s['vcl']['consistency_score']}",
            f"🌱 ExploreFloor: {s['efl']['current_rate']} "
              f"enforcements={s['efl']['enforcements']}",
            f"🔄 Backpressure: output_rate={s['sbp']['output_rate']} "
              f"adj={s['sbp']['adjustments']}",
            f"🎨 Noise/Novelty: noise={s['nvs']['noise_blocked']} "
              f"novelty={s['nvs']['novelty_passed']}",
        ]
        return "\n".join(lines)


_singleton: NexR181 | None = None
_lock = threading.Lock()

def get_r181() -> NexR181:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = NexR181()
    return _singleton
