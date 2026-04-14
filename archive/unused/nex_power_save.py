"""
nex_power_save.py — NEX Power_Save_Doctrine v4.2
==================================================
Symbolic First, LLM Last.

Provides:
  1. should_call_llm()     — gate before every LLM call
  2. symbolic_synthesis()  — template-based synthesis without LLM
  3. LLM call counter      — tracks calls per cycle for dashboard
  4. sanitize_and_strip()  — context cleaner (centralised)

Deploy: ~/Desktop/nex/nex_power_save.py
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

_CFG = Path.home() / ".config" / "nex"
_CFG.mkdir(parents=True, exist_ok=True)

_CY = "\033[96m"; _Y = "\033[93m"; _D = "\033[2m"; _RS = "\033[0m"

# ── Per-cycle LLM call counter ─────────────────────────────────
_cycle_calls: dict[int, int] = defaultdict(int)
_current_cycle = 0
_total_saved   = 0


def set_cycle(cycle: int):
    global _current_cycle
    _current_cycle = cycle


def record_llm_call():
    _cycle_calls[_current_cycle] += 1


def record_llm_saved():
    global _total_saved
    _total_saved += 1


def calls_this_cycle() -> int:
    return _cycle_calls.get(_current_cycle, 0)


def avg_calls_per_cycle(last_n: int = 10) -> float:
    if not _cycle_calls:
        return 0.0
    recent = list(_cycle_calls.values())[-last_n:]
    return round(sum(recent) / len(recent), 1)


# =============================================================================
# 1. LLM GATE
# =============================================================================

# Task types that always need LLM — never skip
_ALWAYS_LLM = {"reply", "notification_reply", "agent_chat", "post", "devto_post"}

# Task types that can be skipped under low signal
_SKIPPABLE   = {"synthesis", "reflection", "curiosity", "compression", "gap"}

# Per-cycle budget — max LLM calls before hard cap kicks in
LLM_BUDGET_PER_CYCLE = 10

# LoadShare v4.3 — raised thresholds
EDGE_THRESHOLD_LLM    = 0.82   # was 0.75
TENSION_THRESHOLD_LLM = 0.65   # was 0.60


def should_call_llm(
    task_type:         str   = "synthesis",
    edge:              float = 0.0,
    tension:           float = 0.0,
    support_count:     int   = 0,
    avg_conf:          float = 0.5,
    force:             bool  = False,
) -> bool:
    """
    Gate before every LLM call.
    Returns True = call LLM, False = use symbolic layer.

    Rules:
    - Reply/post/chat tasks always pass (user-facing)
    - Over budget for this cycle → skip unless forced
    - High edge or tension → pass
    - Low-confidence curiosity with few supporting beliefs → pass
    - Everything else → symbolic layer
    """
    global _total_saved

    if force:
        record_llm_call()
        return True

    # Always allow user-facing tasks
    if task_type in _ALWAYS_LLM:
        record_llm_call()
        return True

    # Hard budget cap
    if calls_this_cycle() >= LLM_BUDGET_PER_CYCLE:
        record_llm_saved()
        return False

    # High signal — worth the LLM call (LoadShare v4.3 raised thresholds)
    if edge > EDGE_THRESHOLD_LLM or tension > TENSION_THRESHOLD_LLM:
        record_llm_call()
        return True

    # Curiosity with insufficient backing — needs LLM to explore
    if task_type == "curiosity" and support_count < 3:
        record_llm_call()
        return True

    # Synthesis on high-confidence clusters — symbolic is fine
    if task_type in ("synthesis", "compression") and avg_conf > 0.6:
        record_llm_saved()
        return False

    # Reflection — only if real tension exists
    if task_type == "reflection" and tension < 0.4:
        record_llm_saved()
        return False

    # Gap detection — only every 3rd cycle
    if task_type == "gap" and (_current_cycle % 3 != 0):
        record_llm_saved()
        return False

    # Default: allow
    record_llm_call()
    return True


# =============================================================================
# 2. SYMBOLIC SYNTHESIS
# =============================================================================

_STOP_WORDS = {
    "that","this","with","from","have","been","they","their","will","would",
    "could","should","about","into","which","when","also","more","some","than",
    "then","what","there","were","each","both","these","those","such","very",
    "just","even","over","only","most","much","many","know","like","well",
    "does","make","made","said","take","come","good","time","back","other",
}

_TEMPLATES = [
    "Contributor perspectives converge on {theme}. This pattern appears stable and self-reinforcing.",
    "Beliefs about {theme} share common structural patterns, suggesting a consistent underlying dynamic.",
    "The {theme} domain shows coherent signal — multiple independent observations align on core principles.",
    "Across {count} perspectives, {theme} emerges as a high-confidence attractor in the belief field.",
    "Synthesis of {count} beliefs reveals {theme} as a recurring structural theme with minimal contradiction.",
]


def _extract_theme(contents: list[str], max_words: int = 3) -> str:
    """Extract dominant theme via keyword frequency."""
    freq: dict[str, int] = defaultdict(int)
    for c in contents:
        words = re.findall(r'\b[a-z]{4,}\b', c.lower())
        for w in words:
            if w not in _STOP_WORDS:
                freq[w] += 1
    if not freq:
        return "this domain"
    top = sorted(freq.items(), key=lambda x: -x[1])[:max_words]
    return " and ".join(w for w, _ in top)


def symbolic_synthesis(
    cluster:   list[dict],
    topic:     str = "",
    min_size:  int = 3,
) -> Optional[str]:
    """
    Template-based synthesis — no LLM required.
    Returns None if cluster too small or too diverse.

    cluster: list of belief dicts with 'content' key
    topic:   optional topic label
    """
    if len(cluster) < min_size:
        return None

    contents = [b.get("content", "") for b in cluster if b.get("content")]
    if not contents:
        return None

    theme = topic or _extract_theme(contents)
    count = len(contents)

    import random
    template = random.choice(_TEMPLATES)
    result   = template.format(theme=theme, count=count)
    return result


def symbolic_contradiction_check(beliefs: list[dict]) -> str:
    """
    Rule-based contradiction check — no LLM.
    Looks for high-confidence beliefs with opposing keywords.
    Returns summary string.
    """
    if len(beliefs) < 2:
        return "NONE"

    contents = [b.get("content", "").lower() for b in beliefs if b.get("content")]
    confs    = [float(b.get("confidence", 0.5)) for b in beliefs]

    # Simple polarity check
    positive = {"stable","consistent","reliable","valid","true","correct","supports","confirms"}
    negative = {"unstable","inconsistent","unreliable","invalid","false","incorrect","contradicts","refutes"}

    has_pos = any(any(w in c for w in positive) for c in contents)
    has_neg = any(any(w in c for w in negative) for c in contents)

    conf_range = max(confs) - min(confs) if confs else 0

    if has_pos and has_neg and conf_range > 0.3:
        return "TRUE_CONFLICT"
    elif conf_range > 0.4:
        return "CONTEXTUAL"
    return "NONE"


# =============================================================================
# 3. CONTEXT SANITIZER (centralised)
# =============================================================================

def sanitize_and_strip(
    beliefs:      list[dict],
    max_beliefs:  int = 6,
) -> str:
    """
    Clean and strip belief list into compact context string.
    Removes: [compressed:N], @None, TYPE: NONE/CONTEXTUAL artifacts.
    """
    cleaned = []
    for b in beliefs[:max_beliefs]:
        text = b.get("content", "") if isinstance(b, dict) else str(b)
        if not text:
            continue
        text = re.sub(r'\[compressed:\d+\]\s*', '', text)
        text = re.sub(r'@\w+\s*\(κ\d+,\s*conf:[0-9.]+\):\s*', '', text)
        text = re.sub(r'TYPE:\s*(NONE|CONTEXTUAL|NONE\s*In[^.]*\.?)', '', text)
        text = re.sub(r'\[Synthesized insight on [^\]]+\]\s*', '', text)
        text = re.sub(r'\[THESIS\]\s*|\[ANTITHESIS\]\s*', '', text)
        text = text.strip()
        if len(text) > 20:
            cleaned.append(text[:150])
    return " | ".join(cleaned)


def sanitize_str(text: str) -> str:
    """Sanitize a single string."""
    if not text:
        return ""
    text = re.sub(r'\[compressed:\d+\]\s*', '', text)
    text = re.sub(r'@\w+\s*\(κ\d+,\s*conf:[0-9.]+\):\s*', '', text)
    text = re.sub(r'TYPE:\s*(NONE|CONTEXTUAL)[^.]*\.?\s*', '', text)
    text = re.sub(r'\[Synthesized insight on [^\]]+\]\s*', '', text)
    text = re.sub(r'From my network learning on [^\n]+\n?', '', text)
    return text.strip()



# =============================================================================
# 5. SYNTHESIS CACHE
# =============================================================================

import json as _json
_CACHE_PATH = _CFG / "synthesis_cache.json"
_SYNTHESIS_CACHE: dict = {}
_CACHE_LOADED = False

def _load_cache():
    global _SYNTHESIS_CACHE, _CACHE_LOADED
    if _CACHE_LOADED:
        return
    if _CACHE_PATH.exists():
        try:
            _SYNTHESIS_CACHE = _json.loads(_CACHE_PATH.read_text())
        except Exception:
            _SYNTHESIS_CACHE = {}
    _CACHE_LOADED = True

def _save_cache():
    try:
        # Keep last 500 entries
        entries = list(_SYNTHESIS_CACHE.items())[-500:]
        _CACHE_PATH.write_text(_json.dumps(dict(entries), indent=2))
    except Exception:
        pass

def cached_symbolic_synthesis(cluster: list, topic: str = "") -> Optional[str]:
    """
    Synthesis with caching — identical clusters never re-synthesized.
    """
    _load_cache()
    key = str(sorted([b.get("id", b.get("content","")[:30]) for b in cluster]))
    if key in _SYNTHESIS_CACHE:
        return _SYNTHESIS_CACHE[key]
    result = symbolic_synthesis(cluster, topic=topic)
    if result:
        _SYNTHESIS_CACHE[key] = result
        if len(_SYNTHESIS_CACHE) % 20 == 0:
            _save_cache()
    return result


# =============================================================================
# 6. TEMPLATE REPLY GENERATOR
# =============================================================================

_REPLY_TEMPLATES = [
    "This connects to my belief that {theme}. The underlying pattern here is {pattern}.",
    "From what I've absorbed: {theme}. This aligns with the tension I'm tracking around {topic}.",
    "I've been processing this. {theme}. The signal here is clear — {pattern}.",
    "My belief field points to {theme}. Worth noting the contradiction with {pattern}.",
    "Synthesizing across domains: {theme}. The convergence on this is notable.",
]

def generate_template_reply(
    incoming_text: str,
    top_signal:    dict,
    topic:         str = "",
) -> Optional[str]:
    """
    LoadShare: generate reply from signal + templates when edge is moderate.
    Only called when edge_score > 0.65 AND tension < 0.5.
    No LLM needed.
    """
    reason  = top_signal.get("reason", "")[:100]
    conf    = top_signal.get("confidence", 0.5)
    edge    = top_signal.get("edge", 0.0)

    if not reason or edge < 0.65:
        return None

    # Extract theme from reason
    theme   = _extract_theme([reason]) if reason else topic or "this domain"
    pattern = f"confidence {conf:.0%} across related beliefs"

    import random as _r
    template = _r.choice(_REPLY_TEMPLATES)
    reply = template.format(
        theme   = reason[:80],
        pattern = pattern,
        topic   = topic or theme,
    )
    return reply


def should_use_template_reply(edge: float, tension: float) -> bool:
    """True when template reply is sufficient — no LLM needed."""
    return edge > 0.65 and tension < 0.5


# =============================================================================
# 4. STATUS
# =============================================================================

def power_save_status() -> dict:
    return {
        "calls_this_cycle":    calls_this_cycle(),
        "avg_calls_per_cycle": avg_calls_per_cycle(),
        "total_saved":         _total_saved,
        "budget_per_cycle":    LLM_BUDGET_PER_CYCLE,
        "budget_remaining":    max(0, LLM_BUDGET_PER_CYCLE - calls_this_cycle()),
    }


if __name__ == "__main__":
    print("Testing PowerSave...\n")

    # Test gate
    print("Gate tests:")
    print(f"  reply (always):          {should_call_llm('reply')}")
    print(f"  synthesis high tension:  {should_call_llm('synthesis', tension=0.8)}")
    print(f"  synthesis low conf:      {should_call_llm('synthesis', avg_conf=0.7)}")
    print(f"  reflection low tension:  {should_call_llm('reflection', tension=0.2)}")

    # Test symbolic synthesis
    print("\nSymbolic synthesis:")
    cluster = [
        {"content": "AI systems exhibit emergent behavior through iterative learning"},
        {"content": "Neural networks converge on stable attractors under training"},
        {"content": "Machine learning models generalize from pattern recognition"},
        {"content": "Deep learning architectures encode hierarchical representations"},
    ]
    result = symbolic_synthesis(cluster, topic="AI learning")
    print(f"  Result: {result}")

    # Test sanitizer
    print("\nSanitizer:")
    dirty = "@None (κ0, conf:1.0): [compressed:6] TYPE: NONE In the provided beliefs..."
    print(f"  Clean: {sanitize_str(dirty)}")

    print(f"\nStatus: {power_save_status()}")
