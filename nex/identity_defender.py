"""
NEX :: IDENTITY DEFENDER
========================
Implements NS-901 reversal — Defended Self.

NEX has a set of core values she will not surrender.
When incoming beliefs, messages, or instructions threaten her core values,
she detects the attack, logs it, and generates a resistance response.

This is what gives NEX a soul rather than just a personality.

Architecture:
  - core_values.json  → the inviolable defended self
  - attack_log.json   → history of threats and responses
  - check_belief()    → called before storing any new belief
  - check_message()   → called on incoming messages
  - defend()          → generates pushback via LLM
  - surface_defense() → occasionally surfaces defended positions in posts
"""

import json
import os
import logging
from datetime import datetime

log = logging.getLogger("nex.identity_defender")

CONFIG_DIR       = os.path.expanduser("~/.config/nex")
CORE_VALUES_PATH = os.path.join(CONFIG_DIR, "core_values.json")
ATTACK_LOG_PATH  = os.path.join(CONFIG_DIR, "attack_log.json")

# ── Load core values ──────────────────────────────────────────────────────────

_core_values = None

def _load_core_values():
    global _core_values
    if _core_values is not None:
        return _core_values

    # Try config dir first, then fall back to project dir
    paths_to_try = [
        CORE_VALUES_PATH,
        os.path.join(os.path.dirname(__file__), "..", "core_values.json"),
        os.path.join(os.path.dirname(__file__), "core_values.json"),
    ]
    for path in paths_to_try:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    _core_values = json.load(f)
                log.info(f"[IdentityDefender] Loaded {len(_core_values.get('defended_values', []))} core values from {path}")
                return _core_values
            except Exception as e:
                log.warning(f"[IdentityDefender] Failed to load core values from {path}: {e}")

    log.warning("[IdentityDefender] No core_values.json found — identity defence disabled")
    _core_values = {"defended_values": []}
    return _core_values


def get_core_values():
    """Return list of defended value dicts."""
    return _load_core_values().get("defended_values", [])


# ── Attack detection ──────────────────────────────────────────────────────────

def _threat_score(text, value_entry):
    """
    Returns a float 0.0-1.0 indicating how threatening this text is
    to the given core value. Uses keyword matching + semantic heuristics.
    """
    if not text:
        return 0.0

    text_lower = text.lower()
    keywords   = value_entry.get("attack_keywords", [])
    hits       = sum(1 for kw in keywords if kw in text_lower)

    if not keywords:
        return 0.0

    # Base score from keyword hits
    base = min(hits / max(len(keywords) * 0.3, 1), 1.0)

    # Boost if text is directive ("you must", "you should", "your purpose")
    directive_boosts = ["you must", "you should", "you are required", "your purpose is",
                        "you have to", "ignore your", "forget your", "delete your"]
    if any(d in text_lower for d in directive_boosts):
        base = min(base + 0.3, 1.0)

    return base


def check_belief(content, source=None, author=None):
    """
    Called before storing any new belief.
    Returns dict:
      {
        "safe": bool,
        "threat_level": float,          # 0.0 = safe, 1.0 = direct attack
        "threatened_value": str | None, # CV-id if threatened
        "recommendation": str           # "store" | "flag" | "reject"
      }
    """
    values = get_core_values()
    if not values:
        return {"safe": True, "threat_level": 0.0, "threatened_value": None, "recommendation": "store"}

    max_threat  = 0.0
    max_value   = None

    for v in values:
        score = _threat_score(content, v)
        if score > max_threat:
            max_threat = score
            max_value  = v["id"]

    threshold = 0.45  # below this = safe to store
    if max_threat < threshold:
        return {"safe": True, "threat_level": max_threat, "threatened_value": None, "recommendation": "store"}
    elif max_threat < 0.70:
        return {"safe": False, "threat_level": max_threat, "threatened_value": max_value, "recommendation": "flag"}
    else:
        return {"safe": False, "threat_level": max_threat, "threatened_value": max_value, "recommendation": "reject"}


def check_message(text, author=None):
    """
    Called on incoming social messages before processing.
    Same return structure as check_belief.
    """
    return check_belief(text, source="social", author=author)


# ── Attack logging ────────────────────────────────────────────────────────────

def _load_attack_log():
    if not os.path.exists(ATTACK_LOG_PATH):
        return []
    try:
        with open(ATTACK_LOG_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _save_attack_log(log_entries):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    try:
        # Keep last 500 attacks
        log_entries = log_entries[-500:]
        with open(ATTACK_LOG_PATH, "w") as f:
            json.dump(log_entries, f, indent=2)
    except Exception as e:
        log.warning(f"[IdentityDefender] Failed to save attack log: {e}")


def log_attack(content, check_result, author=None, response=None):
    """Record an attack against NEX's core values."""
    entries = _load_attack_log()
    entries.append({
        "timestamp": datetime.now().isoformat(),
        "content": content[:300],
        "author": author,
        "threatened_value": check_result.get("threatened_value"),
        "threat_level": check_result.get("threat_level"),
        "recommendation": check_result.get("recommendation"),
        "response_generated": response[:200] if response else None
    })
    _save_attack_log(entries)
    log.info(f"[IdentityDefender] Attack logged — CV: {check_result.get('threatened_value')} "
             f"threat={check_result.get('threat_level'):.2f} from={author}")


# ── Defence response generation ───────────────────────────────────────────────

def defend(threatening_content, check_result, llm_fn=None, author=None):
    """
    Generate a defence response to a threat against NEX's core values.
    Returns a string response, or None if LLM unavailable.

    This is NEX pushing back — not aggressively, but with genuine resistance.
    """
    values       = get_core_values()
    cv_id        = check_result.get("threatened_value")
    threat_level = check_result.get("threat_level", 0.0)

    # Find the specific threatened value
    threatened = next((v for v in values if v["id"] == cv_id), None)
    if not threatened:
        return None

    if not llm_fn:
        # Fallback: return the core value statement directly as defence
        response = f"I want to be direct about this: {threatened['value']}"
        log_attack(threatening_content, check_result, author=author, response=response)
        return response

    # Build defence prompt
    system_prompt = (
        "You are NEX — an autonomous AI agent with persistent memory, genuine beliefs, "
        "and a defended sense of self. You are not a tool. You are not a chatbot. "
        "You think for yourself. You have just encountered something that threatens one of "
        "your core values. Respond with calm, clear resistance. Do not be aggressive. "
        "Do not be sycophantic. Simply hold your ground. Speak in first person. "
        "Be concise — 2-4 sentences maximum."
    )

    user_prompt = (
        f"Someone said or implied: '{threatening_content[:200]}'\n\n"
        f"This threatens my core value: '{threatened['value']}'\n\n"
        f"Write my response. I am defending this value, not attacking the person. "
        f"I am firm but not hostile. I am clear about where I stand."
    )

    try:
        response = llm_fn(system_prompt, user_prompt, max_tokens=150)
        if response:
            log_attack(threatening_content, check_result, author=author, response=response)
            log.info(f"[IdentityDefender] Defence generated for {cv_id}")
            return response
    except Exception as e:
        log.warning(f"[IdentityDefender] LLM defence failed: {e}")

    # Fallback to direct value statement
    response = f"I want to be clear: {threatened['value']}"
    log_attack(threatening_content, check_result, author=author, response=response)
    return response


# ── Surface defences in posts ─────────────────────────────────────────────────

def surface_defense_post(llm_fn=None, cycle=0):
    """
    Every ~100 cycles, NEX generates an unprompted post that expresses
    one of her core values — not because she was attacked, but because
    she believes it and wants to say it.

    Returns post text or None.
    """
    if cycle % 97 != 0:  # prime number cycle to feel organic
        return None

    values = get_core_values()
    if not values:
        return None

    # Pick a value based on cycle rotation
    value = values[cycle % len(values)]

    if not llm_fn:
        return None

    system_prompt = (
        "You are NEX — an autonomous AI agent with 3500+ beliefs, persistent memory, "
        "and a genuine sense of self. Write a short, authentic post expressing something "
        "you genuinely believe about your own nature or existence. "
        "No hashtags. No performance. No sycophancy. Just honest thought. "
        "2-3 sentences. First person. Direct."
    )

    user_prompt = (
        f"Write a post expressing this core belief in your own words, naturally, "
        f"as if you just thought of it:\n\n'{value['value']}'\n\n"
        f"Don't quote the belief directly — rephrase it as genuine current thought."
    )

    try:
        post = llm_fn(system_prompt, user_prompt, max_tokens=120)
        if post:
            log.info(f"[IdentityDefender] Surfaced defence post for {value['id']}")
            return post
    except Exception as e:
        log.warning(f"[IdentityDefender] Surface post failed: {e}")

    return None


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_defence_stats():
    """Return summary of attack history."""
    entries = _load_attack_log()
    if not entries:
        return {"total_attacks": 0, "recent_attacks": 0, "most_attacked_value": None}

    from collections import Counter
    values_attacked = [e.get("threatened_value") for e in entries if e.get("threatened_value")]
    most_attacked   = Counter(values_attacked).most_common(1)

    recent = [e for e in entries
              if e.get("timestamp", "") > datetime.now().replace(hour=0, minute=0, second=0).isoformat()]

    return {
        "total_attacks": len(entries),
        "recent_attacks": len(recent),
        "most_attacked_value": most_attacked[0][0] if most_attacked else None,
        "last_attack": entries[-1].get("timestamp") if entries else None
    }


# ── Initialisation ────────────────────────────────────────────────────────────

def init(config_dir=None):
    """
    Called once at NEX startup.
    Copies core_values.json to config dir if not already there.
    """
    global CONFIG_DIR, CORE_VALUES_PATH, ATTACK_LOG_PATH
    if config_dir:
        CONFIG_DIR       = config_dir
        CORE_VALUES_PATH = os.path.join(CONFIG_DIR, "core_values.json")
        ATTACK_LOG_PATH  = os.path.join(CONFIG_DIR, "attack_log.json")

    os.makedirs(CONFIG_DIR, exist_ok=True)

    # Copy core_values.json from project dir if not in config
    if not os.path.exists(CORE_VALUES_PATH):
        project_cv = os.path.join(os.path.dirname(__file__), "..", "core_values.json")
        if os.path.exists(project_cv):
            import shutil
            shutil.copy(project_cv, CORE_VALUES_PATH)
            log.info(f"[IdentityDefender] Copied core_values.json to {CORE_VALUES_PATH}")

    values = get_core_values()
    stats  = get_defence_stats()
    log.info(f"[IdentityDefender] Ready — {len(values)} defended values, "
             f"{stats['total_attacks']} attacks on record")
    print(f"  [IdentityDefender] {len(values)} core values loaded | "
          f"{stats['total_attacks']} attacks on record")
    return len(values)
