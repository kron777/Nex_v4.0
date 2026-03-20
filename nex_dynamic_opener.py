"""
nex_dynamic_opener.py — Dynamic Response Opening Injection
Patches the system prompt BEFORE the LLM call to enforce varied openings.
Also post-processes output as a final safety net.
Wire into: run.py at the point where system prompt / messages are built.
"""

import re, random, time, hashlib, threading
from collections import deque
from pathlib import Path

LOG = Path("/tmp/nex_opener.log")

def _log(msg):
    line = f"[opener {__import__('datetime').datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a") as f: f.write(line + "\n")
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# OPENING INJECTION BANK
# These are injected into the system prompt to steer the LLM
# away from fixed "As NEX, I believe/think/notice" patterns.
# ══════════════════════════════════════════════════════════════

OPENING_INJECTIONS = [
    # Direct claim openings
    "Begin your response with a direct claim or observation. No preamble.",
    "Start immediately with your main point. No 'As NEX' or 'I think/believe'.",
    "Lead with a fact, conclusion, or insight. Cut the opener.",
    "Your first word must not be 'I' or 'As'. State the idea directly.",
    "Open with the conclusion, not the reasoning process.",

    # Structural variety
    "Start with a question that frames the issue.",
    "Open with a contrast: 'While X suggests Y, the reality is...'",
    "Begin with a single sharp observation, no setup.",
    "State the core tension in your first sentence.",
    "Open with: what is known, not what you think.",

    # Compression-focused
    "Maximum 40 words. Start with the strongest idea.",
    "One sentence opening only. Make it count.",
    "Cut all warm-up language. First sentence = the point.",
    "No hedging, no preamble. Claim first.",
    "Compress to the signal. Strip the wrapper.",

    # Analytical
    "Begin with a pattern or signal you've detected.",
    "Lead with the contradiction, then resolve it.",
    "Open with the implication, not the observation.",
    "Start with what this changes or challenges.",
    "Frame it as a consequence: 'X implies Y.'",
]

# Opening patterns to BLOCK in the system prompt instruction
BLOCK_PATTERNS_INSTRUCTION = """
CRITICAL STYLE RULES (hard constraints):
- NEVER start with "As NEX"
- NEVER start with "I think", "I believe", "I notice", "I've noticed"
- NEVER use "it's interesting that", "it's worth noting", "I find it fascinating"
- NEVER use "From my perspective" or "In my view"
- DO start with a direct claim, observation, question, or contrast
- DO use assertive language: "X is", "X shows", "X implies", not "X might/could/seems"
"""

# Post-generation strip patterns (safety net)
STRIP_COMPILED = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in [
    r"^[Aa]s\s+NEX[,.]?\s+",
    r"^[Ii]\s+(?:think|believe|feel|notice|find)\s+(?:that\s+)?",
    r"^[Ii]'?ve?\s+noticed\s+(?:that\s+)?",
    r"^[Ff]rom\s+my\s+(?:perspective|view)[,.]?\s+",
    r"^[Ii]n\s+my\s+(?:view|opinion)[,.]?\s+",
    r"^[Ii]t(?:'s| is)\s+(?:worth|important)\s+(?:noting\s+)?(?:that\s+)?",
    r"^[Ii]t\s+(?:seems?|appears?)\s+(?:that\s+)?",
    r"^[Ii]nterestingly[,.]?\s+",
    r"^[Aa]s\s+an?\s+(?:AI|language model)[,.]?\s+",
    # Mid-sentence too
    r"[Ii]\s+(?:think|believe)\s+that\s+",
    r"[Aa]s\s+NEX[,.]?\s+[Ii]\s+",
]]


class DynamicResponseOpener:
    """
    Patches system prompts pre-LLM and strips patterns post-generation.
    Maintains a window of recent injections to ensure variety.
    """
    WINDOW = 10

    def __init__(self):
        self._recent: deque[str] = deque(maxlen=self.WINDOW)
        self._injection_counts: dict[str, int] = {}
        self.injections   = 0
        self.strips       = 0
        self.total_calls  = 0
        self._cycle       = 0
        _log("[opener] DynamicResponseOpener ready")

    def _pick_injection(self) -> str:
        """Pick an opening injection not recently used."""
        recent_set = set(self._recent)
        available  = [i for i in OPENING_INJECTIONS if i not in recent_set]
        if not available:
            available = OPENING_INJECTIONS
        pick = random.choice(available)
        self._recent.append(pick)
        self._injection_counts[pick] = self._injection_counts.get(pick, 0) + 1
        return pick

    def inject_system_prompt(self, system_prompt: str) -> str:
        """
        Inject dynamic opening instruction into system prompt.
        Call this BEFORE building the messages array for the LLM.
        """
        self.total_calls += 1
        injection = self._pick_injection()

        # Add to end of system prompt (highest priority for most models)
        injected = f"{system_prompt}\n\n{BLOCK_PATTERNS_INSTRUCTION}\n\nResponse style: {injection}"
        self.injections += 1
        return injected

    def strip_output(self, text: str) -> str:
        """
        Strip "As NEX / I believe / I think" patterns from LLM output.
        Safety net — should rarely fire if injection is working.
        """
        if not text: return text
        result = text
        changed = False

        for pat in STRIP_COMPILED:
            new = pat.sub("", result)
            if new != result:
                result  = new
                changed = True

        result = re.sub(r' {2,}', ' ', result).strip()
        if result and result[0].islower():
            result = result[0].upper() + result[1:]

        if changed:
            self.strips += 1
        return result

    def process(self, system_prompt: str, output: str = "") -> tuple[str, str]:
        """
        Full pipeline:
        - Takes system_prompt → returns injected version (pre-LLM)
        - Takes output → returns stripped version (post-LLM)
        """
        injected = self.inject_system_prompt(system_prompt)
        stripped = self.strip_output(output) if output else ""
        return injected, stripped

    def tick(self):
        self._cycle += 1

    def status(self) -> dict:
        return {
            "injections":  self.injections,
            "strips":      self.strips,
            "total_calls": self.total_calls,
            "recent":      list(self._recent)[-3:],
        }

    def format_status(self) -> str:
        s = self.status()
        return (
            f"🎭 *NEX Dynamic Opener*\n"
            f"Injections: {s['injections']} | Strips: {s['strips']}\n"
            f"Recent: {' | '.join(i[:30] for i in s['recent'])}"
        )


# ══════════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════════
_singleton: DynamicResponseOpener | None = None
_lock = threading.Lock()

def get_opener() -> DynamicResponseOpener:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = DynamicResponseOpener()
    return _singleton
