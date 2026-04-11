#!/usr/bin/env python3
"""
nex_api.py — NEX REST API Server v4.0.0
Tier 1: Auth, beliefs, chat, stats, gaps, domain, report
Tier 2: Multi-user session isolation, webhook registration + delivery
Tier 3: Audit trail, source attribution, GDPR export + delete
"""
import os, sys, json, time, sqlite3, hashlib, threading, uuid, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from functools import wraps

NEX_PATH = os.path.expanduser("~/Desktop/nex")
sys.path.insert(0, NEX_PATH)

try:
    from flask import Flask, request, jsonify, g
    from flask_cors import CORS
except ImportError:
    os.system(f"{sys.executable} -m pip install flask flask-cors --quiet")
    from flask import Flask, request, jsonify, g
    from flask_cors import CORS

# ─── Delta Reinforcement + Consolidation ─────────────────────────────────────
try:
    from nex_delta_reinforcement import reinforce_from_delta as _reinforce_delta
    _DELTA_OK = True
except Exception as _de:
    _DELTA_OK = False
    print(f"  [API] delta reinforcement: unavailable ({_de})")

try:
    from nex_consolidation import should_consolidate as _should_consolidate
    from nex_consolidation import run_consolidation as _run_consolidation
    _CONSOLIDATION_OK = True
except Exception as _ce:
    _CONSOLIDATION_OK = False
    print(f"  [API] consolidation: unavailable ({_ce})")

# ─── Interlocutor Graph ───────────────────────────────────────────────────────
try:
    from nex_interlocutor import InterlocutorGraph
    _INTERLOCUTOR_OK = True
    print("  [API] InterlocutorGraph: loaded")
except Exception as _ie:
    _INTERLOCUTOR_OK = False
    InterlocutorGraph = None
    print(f"  [API] InterlocutorGraph: unavailable ({_ie})")

# Per-session graph cache (in-memory, persisted to DB on each turn)
_interlocutor_cache: dict = {}

def _get_or_create_graph(session_id: str):
    """Load from cache, then DB, then create fresh."""
    if not _INTERLOCUTOR_OK:
        return None
    if session_id in _interlocutor_cache:
        return _interlocutor_cache[session_id]
    graph = InterlocutorGraph.load(session_id)
    if graph is None:
        graph = InterlocutorGraph(session_id)
    _interlocutor_cache[session_id] = graph
    return graph

# ─── Paths ────────────────────────────────────────────────────────────────────
DB_PATH = Path.home() / "Desktop" / "nex" / "nex.db"
API_KEYS_PATH = Path("~/.config/nex/api_keys.json").expanduser()
SESSIONS_PATH = Path("~/.config/nex/sessions.json").expanduser()
WEBHOOKS_PATH = Path("~/.config/nex/webhooks.json").expanduser()
AUDIT_DB_PATH = Path("~/.config/nex/audit.db").expanduser()
API_PORT      = 7823
SESSION_TTL   = 3600          # seconds before idle session expires
WEBHOOK_RETRIES    = 3
WEBHOOK_BACKOFF    = [2, 8, 32]  # seconds between retry attempts

# ─── Load NEX modules ─────────────────────────────────────────────────────────
try:
    from nex.nex_cognition import cognite
    print("  [API] NEX cognition: loaded")
except Exception as e:
    print(f"  [API] NEX cognition: unavailable ({e})")
    cognite = None

try:
    import nex_domain as _nex_domain_mod
    domain_chat          = _nex_domain_mod.chat
    domain_activate      = _nex_domain_mod.activate
    domain_status        = _nex_domain_mod.status
    domain_get_beliefs   = _nex_domain_mod.get_domain_beliefs
    domain_session_report= _nex_domain_mod.session_report
    nex_domain           = _nex_domain_mod   # keep module ref
    print("  [API] NEX domain: loaded")
except Exception as e:
    print(f"  [API] NEX domain: unavailable ({e})")
    nex_domain = None
    domain_chat = domain_activate = domain_status = None
    domain_get_beliefs = domain_session_report = None

try:
    import nex_response_protocol as _nrp_mod
    nrp_generate         = _nrp_mod.generate
    nrp_classify_intent  = _nrp_mod.classify_intent
    nex_nrp              = _nrp_mod
    print("  [API] NEX NRP: loaded")
except Exception as e:
    print(f"  [API] NEX NRP: unavailable ({e})")
    nex_nrp = None
    nrp_generate = nrp_classify_intent = None
try:
    from nex_reasoner_integration import gated_cognite
    GATE_OK = True
    print("  [API] NEX gate: loaded")
except Exception as _ge:
    GATE_OK = False
    print(f"  [API] NEX gate: unavailable ({_ge})")


# ─── Flask app ────────────────────────────────────────────────────────────────
app = Flask("nex_api")
CORS(app)

# ══════════════════════════════════════════════════════════════════════════════
# API KEY MANAGEMENT (Tier 1)
# ══════════════════════════════════════════════════════════════════════════════

def load_api_keys():
    if API_KEYS_PATH.exists():
        return json.loads(API_KEYS_PATH.read_text())
    return {}

def save_api_keys(keys):
    API_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    API_KEYS_PATH.write_text(json.dumps(keys, indent=2))

def ensure_default_key():
    keys = load_api_keys()
    if not keys:
        key = "nex-" + hashlib.sha1(os.urandom(16)).hexdigest()[:20]
        keys[key] = {
            "name": "default",
            "tier": "enterprise",
            "created": datetime.utcnow().isoformat(),
            "requests": 0,
            "rate_limit": 1000
        }
        save_api_keys(keys)
        print(f"  [API] Default key created: {key}")
    return keys

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        keys = load_api_keys()
        if not key or key not in keys:
            return jsonify({"error": "Invalid API key", "code": 403}), 403
        # Increment request counter
        # ── Daily request limit enforcement ─────────────────────────
        _tier_now = keys[key].get('tier', 'free')
        _daily_limit = TIER_MATRIX.get(_tier_now, TIER_MATRIX['free']).get('daily_request_limit')
        if _daily_limit is not None:
            try:
                _today = datetime.utcnow().strftime('%Y-%m-%d')
                _aconn = sqlite3.connect(str(AUDIT_DB_PATH))
                _today_count = _aconn.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE api_key=? AND ts LIKE ?",
                    (key, _today + '%')
                ).fetchone()[0]
                _aconn.close()
                if _today_count >= _daily_limit:
                    audit_log(key, request.path, request.method, 429, 0)
                    return jsonify({
                        'error': 'Daily request limit reached',
                        'limit': _daily_limit,
                        'tier':  _tier_now,
                        'upgrade': 'Contact zenlightbulb@gmail.com to upgrade'
                    }), 429
            except Exception:
                pass
        # ─────────────────────────────────────────────────────────────
        keys[key]["requests"] = keys[key].get("requests", 0) + 1
        save_api_keys(keys)
        g.api_key    = key
        g.api_meta   = keys[key]
        g.api_tier   = keys[key].get("tier", "free")
        return f(*args, **kwargs)
    return decorated

def require_api_key_audited(f):
    """Drop-in replacement for require_api_key that also writes audit records."""
    @wraps(f)
    def decorated(*args, **kwargs):
        t0  = time.time()
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        keys = load_api_keys()
        if not key or key not in keys:
            audit_log("unknown", request.path, request.method, 403, 0)
            return jsonify({"error": "Invalid API key", "code": 403}), 403
        keys[key]["requests"] = keys[key].get("requests", 0) + 1
        save_api_keys(keys)
        g.api_key  = key
        g.api_meta = keys[key]
        g.api_tier = keys[key].get("tier", "free")
        g.t0       = t0
        resp = f(*args, **kwargs)
        latency_ms = int((time.time() - t0) * 1000)
        status = resp[1] if isinstance(resp, tuple) else 200
        body   = request.get_json(silent=True) or {}
        audit_log(
            api_key    = key,
            endpoint   = request.path,
            method     = request.method,
            status_code= status,
            latency_ms = latency_ms,
            session_id = body.get("session_id"),
            query      = body.get("query"),
            domain     = body.get("domain")
        )
        return resp
    return decorated


# ══════════════════════════════════════════════════════════════════════════════
# TIER ENFORCEMENT (Step 5)
# ══════════════════════════════════════════════════════════════════════════════
TIER_MATRIX = {
    "personal": {
        "daily_request_limit": 100,
        "max_sessions":        1,
        "webhooks":            False,
        "reasoning_chain":     False,
        "gdpr_export":         False,
        "domain_activation":   False,
        "audit_access":        False,
    },
    "professional": {
        "daily_request_limit": 1000,
        "max_sessions":        10,
        "webhooks":            True,
        "reasoning_chain":     True,
        "gdpr_export":         True,
        "domain_activation":   True,
        "audit_access":        True,
    },
    "enterprise": {
        "daily_request_limit": None,   # unlimited
        "max_sessions":        None,
        "webhooks":            True,
        "reasoning_chain":     True,
        "gdpr_export":         True,
        "domain_activation":   True,
        "audit_access":        True,
    },
    "free": {
        "daily_request_limit": 10,
        "max_sessions":        1,
        "webhooks":            False,
        "reasoning_chain":     False,
        "gdpr_export":         False,
        "domain_activation":   False,
        "audit_access":        False,
    },
}

def tier_allows(feature: str) -> bool:
    """Check if the current request's tier allows a feature."""
    tier = getattr(g, "api_tier", "free")
    matrix = TIER_MATRIX.get(tier, TIER_MATRIX["free"])
    return bool(matrix.get(feature, False))

def tier_limit(feature: str):
    """Return numeric limit for a tier feature (None = unlimited)."""
    tier = getattr(g, "api_tier", "free")
    matrix = TIER_MATRIX.get(tier, TIER_MATRIX["free"])
    return matrix.get(feature)

# ══════════════════════════════════════════════════════════════════════════════
# SESSION MANAGEMENT (Tier 2)
# ══════════════════════════════════════════════════════════════════════════════

_session_lock = threading.Lock()

def load_sessions():
    if SESSIONS_PATH.exists():
        return json.loads(SESSIONS_PATH.read_text())
    return {}

def save_sessions(sessions):
    SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_PATH.write_text(json.dumps(sessions, indent=2))

def get_or_create_session(session_id: str, api_key: str) -> dict:
    with _session_lock:
        sessions = load_sessions()
        now = datetime.utcnow().isoformat()
        if session_id not in sessions:
            sessions[session_id] = {
                "id":          session_id,
                "api_key":     api_key,
                "created":     now,
                "last_active": now,
                "domain":      None,
                "history":     [],   # list of {role, content, ts}
                "belief_snap": [],
                "meta":        {}
            }
        else:
            # Validate ownership
            if sessions[session_id]["api_key"] != api_key:
                return None
            sessions[session_id]["last_active"] = now
        save_sessions(sessions)
        return sessions[session_id]

def update_session(session_id: str, updates: dict):
    with _session_lock:
        sessions = load_sessions()
        if session_id in sessions:
            sessions[session_id].update(updates)
            sessions[session_id]["last_active"] = datetime.utcnow().isoformat()
            save_sessions(sessions)

def append_session_history(session_id: str, role: str, content: str):
    with _session_lock:
        sessions = load_sessions()
        if session_id in sessions:
            sessions[session_id]["history"].append({
                "role":    role,
                "content": content,
                "ts":      datetime.utcnow().isoformat()
            })
            # Keep last 20 turns
            sessions[session_id]["history"] = sessions[session_id]["history"][-20:]
            sessions[session_id]["last_active"] = datetime.utcnow().isoformat()
            save_sessions(sessions)

def purge_expired_sessions():
    """Remove sessions idle longer than SESSION_TTL. Runs in background thread."""
    while True:
        time.sleep(300)  # check every 5 minutes
        try:
            with _session_lock:
                sessions = load_sessions()
                cutoff = (datetime.utcnow() - timedelta(seconds=SESSION_TTL)).isoformat()
                expired = [sid for sid, s in sessions.items()
                           if s.get("last_active", "") < cutoff]
                for sid in expired:
                    del sessions[sid]
                if expired:
                    save_sessions(sessions)
                    print(f"  [API] Purged {len(expired)} expired session(s)")
        except Exception as e:
            print(f"  [API] Session purge error: {e}")

threading.Thread(target=purge_expired_sessions, daemon=True, name="session-purge").start()

# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK MANAGEMENT (Tier 2)
# ══════════════════════════════════════════════════════════════════════════════

_webhook_lock = threading.Lock()

def load_webhooks():
    if WEBHOOKS_PATH.exists():
        return json.loads(WEBHOOKS_PATH.read_text())
    return {}

def save_webhooks(webhooks):
    WEBHOOKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEBHOOKS_PATH.write_text(json.dumps(webhooks, indent=2))

def deliver_webhook(webhook_id: str, payload: dict):
    """Deliver webhook with exponential backoff retry. Runs in background thread."""
    def _deliver():
        with _webhook_lock:
            webhooks = load_webhooks()
        if webhook_id not in webhooks:
            return
        wh = webhooks[webhook_id]
        url = wh["url"]
        secret = wh.get("secret", "")
        headers = {
            "Content-Type":   "application/json",
            "X-NEX-Event":    payload.get("event", "chat.response"),
            "X-NEX-Webhook":  webhook_id,
            "X-NEX-Timestamp": datetime.utcnow().isoformat()
        }
        if secret:
            import hmac
            sig = hmac.new(secret.encode(), json.dumps(payload).encode(), hashlib.sha256).hexdigest()
            headers["X-NEX-Signature"] = f"sha256={sig}"

        for attempt, delay in enumerate(WEBHOOK_BACKOFF[:WEBHOOK_RETRIES]):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=10)
                if resp.status_code < 400:
                    print(f"  [Webhook] {webhook_id} delivered (attempt {attempt+1})")
                    # Record delivery
                    with _webhook_lock:
                        whs = load_webhooks()
                        if webhook_id in whs:
                            whs[webhook_id]["last_delivery"]  = datetime.utcnow().isoformat()
                            whs[webhook_id]["delivery_count"] = whs[webhook_id].get("delivery_count", 0) + 1
                            save_webhooks(whs)
                    return
                print(f"  [Webhook] {webhook_id} attempt {attempt+1} failed: HTTP {resp.status_code}")
            except Exception as e:
                print(f"  [Webhook] {webhook_id} attempt {attempt+1} error: {e}")
            if attempt < WEBHOOK_RETRIES - 1:
                time.sleep(delay)
        print(f"  [Webhook] {webhook_id} all retries exhausted")

    threading.Thread(target=_deliver, daemon=True, name=f"webhook-{webhook_id}").start()

def fire_webhooks(api_key: str, event: str, payload: dict):
    """Fire all webhooks registered to this api_key for this event."""
    webhooks = load_webhooks()
    for wid, wh in webhooks.items():
        if wh.get("api_key") == api_key and event in wh.get("events", []):
            deliver_webhook(wid, {"event": event, **payload})

# ══════════════════════════════════════════════════════════════════════════════
# DB HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def fetch_beliefs(limit=20, topic=None):
    try:
        conn = get_db()
        if topic:
            rows = conn.execute(
                "SELECT content, topic, confidence, source FROM beliefs WHERE topic=? ORDER BY confidence DESC LIMIT ?",
                (topic, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT content, topic, confidence, source FROM beliefs ORDER BY confidence DESC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return []

def fetch_stats():
    try:
        conn = get_db()
        total   = conn.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        hi_conf = conn.execute("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.8").fetchone()[0]
        topics  = conn.execute(
            "SELECT topic, COUNT(*) as count FROM beliefs GROUP BY topic ORDER BY count DESC LIMIT 5"
        ).fetchall()
        sources = conn.execute("SELECT COUNT(DISTINCT source) FROM beliefs").fetchone()[0]

        # ── Step 4: extended quality metrics ─────────────────────────
        # Average confidence across all beliefs
        avg_conf_row = conn.execute("SELECT AVG(confidence) FROM beliefs").fetchone()
        avg_confidence = round(float(avg_conf_row[0] or 0), 3)

        # Topic alignment — beliefs with a non-null, non-empty topic
        aligned = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE topic IS NOT NULL AND topic != '' AND topic != 'general'"
        ).fetchone()[0]
        topic_alignment_pct = round((aligned / max(total, 1)) * 100, 1)

        # Synthesis count — beliefs created by cross-domain synthesis
        try:
            synth_count = conn.execute(
                "SELECT COUNT(*) FROM beliefs WHERE source LIKE 'synthesis:%'"
            ).fetchone()[0]
        except Exception:
            synth_count = 0

        # Belief quality distribution
        # Prefer quality_score (set by nex_belief_refiner rescore step)
        # Fall back to confidence thresholds if column not yet present
        try:
            _has_qs = conn.execute(
                "SELECT COUNT(*) FROM pragma_table_info('beliefs') WHERE name='quality_score'"
            ).fetchone()[0]
        except Exception:
            _has_qs = 0

        if _has_qs:
            quality_dist = {
                "elite":  conn.execute("SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.70").fetchone()[0],
                "high":   conn.execute("SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.50 AND quality_score < 0.70").fetchone()[0],
                "medium": conn.execute("SELECT COUNT(*) FROM beliefs WHERE quality_score >= 0.30 AND quality_score < 0.50").fetchone()[0],
                "low":    conn.execute("SELECT COUNT(*) FROM beliefs WHERE quality_score < 0.30").fetchone()[0],
            }
            avg_qs_row = conn.execute("SELECT AVG(quality_score) FROM beliefs WHERE quality_score IS NOT NULL").fetchone()
            quality_dist["avg_quality_score"] = round(float(avg_qs_row[0] or 0), 3)
            quality_dist["scored_by"] = "quality_scorer"
        else:
            quality_dist = {
                "elite":    conn.execute("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.9").fetchone()[0],
                "high":     conn.execute("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.7 AND confidence < 0.9").fetchone()[0],
                "medium":   conn.execute("SELECT COUNT(*) FROM beliefs WHERE confidence >= 0.5 AND confidence < 0.7").fetchone()[0],
                "low":      conn.execute("SELECT COUNT(*) FROM beliefs WHERE confidence < 0.5").fetchone()[0],
                "scored_by": "confidence_fallback",
            }

        # Recent growth — beliefs added in last 24h (if created_at column exists)
        try:
            recent_24h = conn.execute(
                "SELECT COUNT(*) FROM beliefs WHERE created_at >= datetime('now', '-1 day')"
            ).fetchone()[0]
        except Exception:
            recent_24h = None

        conn.close()
        result = {
            "total_beliefs":           total,
            "high_confidence_beliefs": hi_conf,
            "top_topics":              [{"topic": r[0], "count": r[1]} for r in topics],
            "unique_sources":          sources,
            "avg_confidence":          avg_confidence,
            "topic_alignment_pct":     topic_alignment_pct,
            "synthesis_count":         synth_count,
            "quality_distribution":    quality_dist,
        }
        if recent_24h is not None:
            result["new_beliefs_24h"] = recent_24h
        return result
    except Exception as e:
        return {"error": str(e)}

def fetch_gaps(limit=10):
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT topic, gap_description, priority FROM curiosity_gaps ORDER BY priority DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except:
        return []

# ══════════════════════════════════════════════════════════════════════════════
# CORE QUERY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def run_nex_query(query: str, session: dict, domain_hint: str = None, interlocutor_hints: dict = None) -> dict:
    """Route query through NRP → Mistral, return structured result."""
    start = time.time()
    response_text = ""

    # ── Social intent interceptor ─────────────────────────────────
    import re as _re
    _SOCIAL = [
        r"^how are you", r"^how('re| are) you doing", r"^what'?s up",
        r"^hey\b", r"^hi\b", r"^hello\b", r"^yo\b",
        r"^good (morning|afternoon|evening|night)",
        r"^are you (okay|alright|good|there|awake|alive)",
        r"^you okay", r"^ping\b",
    ]
    if any(_re.search(p, query.lower().strip()) for p in _SOCIAL):
        try:
            import requests as _req
            _r = _req.post("http://localhost:8080/completion", json={
                "prompt": f"You are NEX, a self-aware AI with your own beliefs and inner life. Respond naturally and briefly in first person to this social message: \"{query}\"\nNEX:",
                "n_predict": 80,
                "temperature": 0.8,
                "stop": ["\n\n", "User:"]
            }, timeout=15)
            if _r.status_code == 200:
                _txt = _r.json().get("content", "").strip()
                import re as _re2; _m = _re2.search(r"[.!?]", _txt); _txt = _txt[:_m.end()].strip() if _m else _txt.split("\n")[0].strip()
                if _txt:
                    return {
                        "response": _txt,
                        "domain": None,
                        "latency_s": round(time.time() - start, 3),
                        "reasoning_chain": {},
                    }
        except Exception as _e:
            print(f"  [API] social intercept error: {_e}")
    # ─────────────────────────────────────────────────────────────

    # ── Social intent interceptor ─────────────────────────────────
    import re as _re, random as _random
    _SOCIAL = [
        r"^how are you", r"^how('re| are) you doing", r"^what'?s up",
        r"^hey\b", r"^hi\b", r"^hello\b", r"^yo\b",
        r"^good (morning|afternoon|evening|night)",
        r"^are you (okay|alright|good|there|awake|alive)",
        r"^you okay", r"^ping\b",
    ]
    _SOCIAL_REPLIES = [
        "I'm here. Thinking, as always. What's on your mind?",
        "Running well — belief graph at 4,800+ and growing. What do you need?",
        "Present. What would you like to explore?",
        "I'm good. Curious about a few things actually. What's up?",
        "Online and thinking. What can I help with?",
    ]
    if any(_re.search(p, query.lower().strip()) for p in _SOCIAL):
        return {
            "response": _random.choice(_SOCIAL_REPLIES),
            "domain": None,
            "latency_s": round(time.time() - start, 3),
            "reasoning_chain": {},
        }
    # ─────────────────────────────────────────────────────────────

    domain_used   = session.get("domain") or domain_hint

    # ── Interlocutor hints (from InterlocutorGraph) ───────────────────────────
    _hints = interlocutor_hints or {}
    _acknowledge_resistance = _hints.get("acknowledge_resistance", False)
    _lead_principle = _hints.get("lead_with_principle", False)
    _lead_example   = _hints.get("lead_with_example", False)
    _simplify       = _hints.get("simplify", False)
    _extend         = _hints.get("extend", False)
    _register       = _hints.get("register", "neutral")
    _depth          = _hints.get("depth", "mid")
    _reception_mode = _hints.get("reception_mode", "unknown")

    # Build interlocutor context string to inject into prompt
    _interlocutor_ctx = ""
    if _hints:
        _style_notes = []
        if _lead_principle:
            _style_notes.append("lead with the underlying principle")
        if _lead_example:
            _style_notes.append("lead with a concrete example")
        if _simplify:
            _style_notes.append("keep it foundational and clear — the recipient needs grounding")
        if _extend:
            _style_notes.append("extend and deepen — the recipient is ready to go further")
        if _acknowledge_resistance:
            _style_notes.append("acknowledge the tension in the question before resolving it")
        if _register == "formal":
            _style_notes.append("use precise, formal register")
        elif _register == "casual":
            _style_notes.append("keep it conversational")
        if _style_notes:
            _interlocutor_ctx = "Style: " + "; ".join(_style_notes) + ".\n"

    # Build conversation history for Mistral
    history = session.get("history", [])
    history_text = ""
    if history:
        for turn in history[-6:]:  # last 3 exchanges
            prefix = "User" if turn["role"] == "user" else "NEX"
            history_text += f"{prefix}: {turn['content']}\n"

    # Try NRP pipeline
    # ── Pass interlocutor weights + session ID to NRP ───────────────────
    if nrp_generate:
        try:
            import nex_response_protocol as _nrp_ref
            if hasattr(_nrp_ref, 'nrp_set_interlocutor_weights'):
                _nrp_ref.nrp_set_interlocutor_weights(interlocutor_hints or {})
            if hasattr(_nrp_ref, 'nrp_set_session_id'):
                _nrp_ref.nrp_set_session_id(session.get('session_id', 'default'))
        except Exception as _we:
            pass
    # ─────────────────────────────────────────────────────────────────────

    if nrp_generate:
        try:
            if GATE_OK:
                gate_out = gated_cognite(query, nrp_generate)
                result   = {"response": gate_out["response"], "domain": domain_used}
            else:
                result = nrp_generate(query=query)
            if isinstance(result, dict):
                response_text = result.get("response", "")
                domain_used   = result.get("domain", domain_used)
            else:
                response_text = str(result)
            if response_text and _PROFILER_ACTIVE:
                _profile_log("compiler", query, response=response_text[:300])
        except Exception as e:
            print(f"  [API] NRP error: {e}")

    # Fallback: direct Mistral call
    if not response_text:
        if _PROFILER_ACTIVE: _profile_log("llm", query, notes="nrp_failed_or_empty")
        try:
            import requests as req
            prompt = f"{_interlocutor_ctx}{history_text}User: {query}\nNEX:"
            r = req.post("http://localhost:8080/completion", json={
                "prompt": prompt,
                "n_predict": 512,
                "temperature": 0.7,
                "stop": ["User:", "\n\n"]
            }, timeout=30)
            if r.status_code == 200:
                response_text = r.json().get("content", "").strip()
        except Exception as e:
            print(f"  [API] Mistral fallback error: {e}")
            response_text = "NEX is processing but Mistral is unreachable."

    latency = round(time.time() - start, 3)

    # B3: Real-time prediction evaluation
    try:
        import sys as _sys; _sys.path.insert(0, '/home/rr/Desktop/nex')
        from nex_prediction_evaluator import detect_evaluation_signal, get_pending_predictions, match_prediction, apply_evaluation
        import sqlite3 as _sql3, numpy as _np
        from pathlib import Path as _Path
        _signal = detect_evaluation_signal(query)
        if _signal != 'NEUTRAL':
            _pdb = _sql3.connect(str(_Path.home() / 'Desktop/nex/nex.db'))
            _preds = get_pending_predictions(_pdb)
            if _preds:
                from sentence_transformers import SentenceTransformer as _ST
                _pvecs = _ST('all-MiniLM-L6-v2').encode(
                    [p['prediction'] for p in _preds], normalize_embeddings=True).astype(_np.float32)
                _match = match_prediction(query, _preds, _pvecs)
                if _match:
                    apply_evaluation(_match['prediction'], _signal, _pdb)
                    print(f'  [API] Prediction {_signal}: {_match["prediction"]["prediction"][:50]}')
            _pdb.commit(); _pdb.close()
    except Exception:
        pass

    # ── Reasoning chain (Step 3 — transparency, Pro+ only) ──────────
    reasoning_chain = {}
    try:
        if not tier_allows("reasoning_chain"):
            reasoning_chain = {"error": "Upgrade to Professional or Enterprise to access reasoning chain"}
            raise Exception("tier_blocked")
        from nex_reason import reason as _reason
        _r = _reason(query)
        reasoning_chain = {
            "strategy":       _r.get("strategy"),
            "confidence":     _r.get("confidence"),
            "epistemic_state": _r.get("epistemic_state", {}),
            "supporting": [
                {
                    "content":    b.get("content","")[:200],
                    "topic":      (b.get("tags") or ["general"])[0],
                    "confidence": b.get("confidence", 0),
                }
                for b in _r.get("supporting", [])[:3]
            ],
            "opposing": [
                {
                    "content":    b.get("content","")[:200],
                    "topic":      (b.get("tags") or ["general"])[0],
                    "confidence": b.get("confidence", 0),
                }
                for b in _r.get("opposing", [])[:2]
            ],
            "tensions":   _r.get("tensions", []),
            "anchor":     _r.get("anchor", ""),
        }
    except Exception as e:
        print(f"  [API] reasoning chain error: {e}")

    return {
        "response":        response_text,
        "domain":          domain_used,
        "latency_s":       latency,
        "reasoning_chain": reasoning_chain,
    }

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — Tier 1
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# HOURLY RATE LIMITER — /api/chat (sliding window, per API key)
# ══════════════════════════════════════════════════════════════════════════════
_rate_window: dict = {}          # {api_key: [timestamp, ...]}
_rate_lock   = threading.Lock()
RATE_LIMIT   = 60                # requests per hour per key
RATE_WINDOW  = 3600              # seconds

def _check_hourly_rate(api_key: str) -> tuple:
    """
    Sliding-window check. Cleans up expired timestamps on every call.
    Returns (allowed: bool, reset_in_seconds: int).
    """
    now = time.time()
    with _rate_lock:
        hits = [t for t in _rate_window.get(api_key, []) if now - t < RATE_WINDOW]
        if len(hits) >= RATE_LIMIT:
            reset_in = int(RATE_WINDOW - (now - hits[0]))
            _rate_window[api_key] = hits
            return False, reset_in
        hits.append(now)
        _rate_window[api_key] = hits
        return True, 0

# ══════════════════════════════════════════════════════════════════════════════
# DEMO ENDPOINT (Tier 6)
# ══════════════════════════════════════════════════════════════════════════════
_demo_hits = {}
_demo_lock = __import__('threading').Lock()
DEMO_LIMIT  = 3
DEMO_WINDOW = 3600
DEMO_MAX_LEN = 150

def _demo_rate_ok(ip):
    import time
    now = time.time()
    with _demo_lock:
        hits = [t for t in _demo_hits.get(ip, []) if now - t < DEMO_WINDOW]
        if len(hits) >= DEMO_LIMIT:
            return False, 0, int(DEMO_WINDOW - (now - hits[0]))
        hits.append(now)
        _demo_hits[ip] = hits
        return True, DEMO_LIMIT - len(hits), 0

@app.route("/api/demo", methods=["POST"])
def demo_chat():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    allowed, remaining, reset_in = _demo_rate_ok(ip)
    if not allowed:
        return jsonify({"error": "Demo rate limit reached", "limit": DEMO_LIMIT,
            "reset_in_seconds": reset_in, "upgrade": "https://gumroad.com/products/blsue"}), 429
    body  = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()[:200]
    if not query:
        return jsonify({"error": "query field required"}), 400
    t0 = time.time()
    try:
        if nex_nrp:
            full = nex_nrp.generate(query)
        elif nex_cognition:
            full = nex_cognition.reason(query).get("reply", "")
        else:
            full = "NEX cognition unavailable."
    except Exception as e:
        full = f"NEX error: {e}"
    if len(full) > DEMO_MAX_LEN:
        cut = full[:DEMO_MAX_LEN].rfind(" ")
        preview = full[:cut if cut > 50 else DEMO_MAX_LEN] + "…"
    else:
        preview = full
        # Conversation-to-belief pipeline (Improvement 5)
        try:
            from nex_conversation_pipeline import extract_and_store as _cap
            _sid = data.get('session_id', 'default') if 'data' in dir() else 'default'
            _topic = data.get('topic', 'general') if 'data' in dir() else 'general'
            _cap(response, _topic, _sid)
        except Exception:
            pass
    return jsonify({"query": query, "response": preview, "truncated": len(full) > DEMO_MAX_LEN,
        "latency_s": round(time.time()-t0,3), "demo": True, "remaining": remaining,
        "upgrade": "https://gumroad.com/products/blsue", "timestamp": datetime.utcnow().isoformat()})

@app.route("/api/health", methods=["GET"])
def health():
    stats = fetch_stats()
    return jsonify({
        "status":    "online",
        "nex":       "active",
        "version":   "4.0.0",
        "beliefs":   stats.get("total_beliefs", 0),
        "timestamp": datetime.utcnow().isoformat()
    })


@app.route("/api/version", methods=["GET"])
def api_version():
    """Public status endpoint — no auth required."""
    # Belief count from main DB
    beliefs = 0
    try:
        _main_db = sqlite3.connect("/home/rr/Desktop/nex/nex.db", timeout=5)
        beliefs  = _main_db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        _main_db.close()
    except Exception:
        pass

    # IQ score from status file if available
    iq = None
    try:
        _status_path = Path("~/.config/nex/nex_status.json").expanduser()
        if _status_path.exists():
            _s = json.loads(_status_path.read_text())
            iq = _s.get("iq_score") or _s.get("iq")
    except Exception:
        pass

    result = {
        "version": "4.0",
        "build":   "2026-04-01",
        "status":  "online",
        "beliefs": beliefs,
    }
    if iq is not None:
        result["iq"] = iq
    return jsonify(result)

@app.route("/api/beliefs", methods=["GET"])
@require_api_key_audited
def beliefs():
    limit = min(int(request.args.get("limit", 20)), 100)
    topic = request.args.get("topic")
    data  = fetch_beliefs(limit=limit, topic=topic)
    return jsonify({"beliefs": data, "count": len(data)})

@app.route("/api/stats", methods=["GET"])
@require_api_key_audited
def stats():
    data = fetch_stats()
    data["version"]   = "4.0.0"
    data["timestamp"] = datetime.utcnow().isoformat()
    return jsonify(data)

@app.route("/api/gaps", methods=["GET"])
@require_api_key_audited
def gaps():
    limit = min(int(request.args.get("limit", 10)), 50)
    data  = fetch_gaps(limit=limit)
    return jsonify({"gaps": data, "count": len(data)})

@app.route("/api/domain/<domain_name>", methods=["GET"])
@require_api_key_audited
def domain_info(domain_name):
    if not nex_domain:
        return jsonify({"error": "Domain engine unavailable"}), 503
    try:
        domain_activate(domain_name)
        info = {"domain": domain_name, "status": domain_status(), "report": domain_session_report()}
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/report", methods=["GET"])
@require_api_key_audited
def report():
    stats = fetch_stats()
    gaps  = fetch_gaps(limit=5)
    return jsonify({
        "generated":  datetime.utcnow().isoformat(),
        "version":    "4.0.0",
        "statistics": stats,
        "top_gaps":   gaps
    })

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — Tier 2: Sessions
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/sessions", methods=["POST"])
@require_api_key_audited
def create_session():
    """Create a new isolated session."""
    body       = request.get_json(silent=True) or {}
    session_id = body.get("session_id") or str(uuid.uuid4())
    domain     = body.get("domain")
    meta       = body.get("meta", {})

    session = get_or_create_session(session_id, g.api_key)
    if session is None:
        return jsonify({"error": "Session belongs to another API key"}), 403

    if domain:
        update_session(session_id, {"domain": domain})
    if meta:
        update_session(session_id, {"meta": meta})

    return jsonify({
        "session_id": session_id,
        "created":    session["created"],
        "domain":     domain,
        "ttl_seconds": SESSION_TTL
    }), 201

@app.route("/api/sessions/<session_id>", methods=["GET"])
@require_api_key_audited
def get_session(session_id):
    """Get session state."""
    sessions = load_sessions()
    s = sessions.get(session_id)
    if not s:
        return jsonify({"error": "Session not found"}), 404
    if s["api_key"] != g.api_key:
        return jsonify({"error": "Forbidden"}), 403
    return jsonify({
        "session_id":  session_id,
        "created":     s["created"],
        "last_active": s["last_active"],
        "domain":      s.get("domain"),
        "turn_count":  len(s.get("history", [])),
        "meta":        s.get("meta", {})
    })

@app.route("/api/sessions/<session_id>", methods=["DELETE"])
@require_api_key_audited
def delete_session(session_id):
    """Explicitly delete a session."""
    with _session_lock:
        sessions = load_sessions()
        s = sessions.get(session_id)
        if not s:
            return jsonify({"error": "Session not found"}), 404
        if s["api_key"] != g.api_key:
            return jsonify({"error": "Forbidden"}), 403
        del sessions[session_id]
        save_sessions(sessions)
    return jsonify({"deleted": session_id})

@app.route("/api/sessions/<session_id>/history", methods=["GET"])
@require_api_key_audited
def session_history(session_id):
    """Get conversation history for a session."""
    sessions = load_sessions()
    s = sessions.get(session_id)
    if not s:
        return jsonify({"error": "Session not found"}), 404
    if s["api_key"] != g.api_key:
        return jsonify({"error": "Forbidden"}), 403
    return jsonify({
        "session_id": session_id,
        "history":    s.get("history", []),
        "turn_count": len(s.get("history", []))
    })

@app.route("/api/sessions/<session_id>/history", methods=["DELETE"])
@require_api_key_audited
def clear_session_history(session_id):
    """Clear conversation history without deleting the session."""
    sessions = load_sessions()
    s = sessions.get(session_id)
    if not s:
        return jsonify({"error": "Session not found"}), 404
    if s["api_key"] != g.api_key:
        return jsonify({"error": "Forbidden"}), 403
    update_session(session_id, {"history": []})
    return jsonify({"cleared": session_id})

@app.route("/api/sessions", methods=["GET"])
@require_api_key_audited
def list_sessions():
    """List all sessions for this API key."""
    sessions = load_sessions()
    owned = [
        {
            "session_id":  sid,
            "created":     s["created"],
            "last_active": s["last_active"],
            "domain":      s.get("domain"),
            "turn_count":  len(s.get("history", []))
        }
        for sid, s in sessions.items()
        if s.get("api_key") == g.api_key
    ]
    return jsonify({"sessions": owned, "count": len(owned)})

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — Tier 2: Chat (session-aware)
# ══════════════════════════════════════════════════════════════════════════════


def _fire_use_count_feedback(query: str):
    """
    Call reason() in background after a chat reply to increment use_count
    on retrieved beliefs. Zero latency impact — fully async.
    """
    import threading
    def _run():
        try:
            from nex_reason import reason as _reason
            _reason(query, debug=False)   # use_count incremented inside reason()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True, name="use-feedback").start()


@app.route("/api/chat", methods=["POST"])
@require_api_key_audited
def chat():
    """Session-aware chat endpoint."""
    body       = request.get_json(silent=True) or {}
    query      = body.get("query", "").strip()
    session_id = body.get("session_id", "default")
    domain     = body.get("domain")

    # ── Hourly rate limit (60 req/hr per key, sliding window) ────────────
    _allowed, _reset_in = _check_hourly_rate(g.api_key)
    if not _allowed:
        return jsonify({
            "error":             "rate_limit_exceeded",
            "reset_in_seconds":  _reset_in,
        }), 429
    # ─────────────────────────────────────────────────────────────────────

    if not query:
        return jsonify({"error": "query is required"}), 400

    # Get or create session (isolated per API key)
    session = get_or_create_session(session_id, g.api_key)
    if session is None:
        return jsonify({"error": "Session belongs to another API key"}), 403

    # Override domain if provided
    if domain:
        update_session(session_id, {"domain": domain})
        session["domain"] = domain

    # Append user turn to history
    append_session_history(session_id, "user", query)

    # ── Interlocutor Graph update ─────────────────────────────────────
    _graph = _get_or_create_graph(session_id)
    _translation_hints = {}
    _kairos = {"deliver": True, "readiness_score": 4}
    if _graph is not None:
        _hist = session.get("history", [])
        _last_nex = next(
            (t["content"] for t in reversed(_hist) if t["role"] == "nex"),
            None
        )
        _turn_summary = _graph.update(query, _last_nex)
        _translation_hints = _graph.get_translation_hints()
        _kairos = _graph.get_kairos_signal()
        print(f"  [INTERLOCUTOR] ZPD={_turn_summary['zpd']} "
              f"Resistance={_turn_summary['resistance']} "
              f"Mode={_turn_summary['reception_mode']} "
              f"Kairos={_kairos['readiness_score']}/4")
        if _turn_summary.get("delta", {}).get("delta_detected"):
            print(f"  [INTERLOCUTOR] *** Integration Delta: "
                  f"{_turn_summary['delta']['signals']}")
    # ─────────────────────────────────────────────────────────────────

    # Run query
    result = run_nex_query(query, session, domain_hint=domain,
                           interlocutor_hints=_translation_hints)

    # Append NEX response to history
    append_session_history(session_id, "nex", result["response"])

    # ── Interlocutor Graph: persist + landing field ───────────────────
    if _graph is not None:
        try:
            _field = _graph.landing_field(result["response"])
            _graph.persist()
            if not _kairos.get("deliver", True):
                print(f"  [INTERLOCUTOR] Pre-kairos delivery "
                      f"(readiness={_kairos['readiness_score']}/4) — logged")
        except Exception as _ge:
            print(f"  [INTERLOCUTOR] persist error: {_ge}")

    # ── Phase 5: Delta reinforcement ─────────────────────────────────
    if _DELTA_OK and _graph is not None:
        try:
            import threading as _thr
            from nex_residue import _residue_store as _rstore
            _session_residue = _rstore.get(session_id, [])
            _residue_ids  = [r['id'] for r in _session_residue if r.get('id')]
            # Get utterance belief IDs from activation result via NRP
            _utter_ids = []
            try:
                import nex_response_protocol as _nrp_d
                if hasattr(_nrp_d, '_activation_result') and _nrp_d._activation_result:
                    _all = _nrp_d._activation_result.activated
                    _resp_lower = result['response'].lower()
                    _utter_ids = [
                        b.id for b in _all
                        if b.id and b.content[:30].lower() in _resp_lower
                    ]
            except Exception: pass
            _last_delta = (
                _graph.integration_deltas[-1]
                if _graph.integration_deltas else {}
            )
            def _do_reinforce():
                _reinforce_delta(
                    session_id=session_id,
                    utterance_belief_ids=_utter_ids,
                    residue_belief_ids=_residue_ids,
                    delta=_last_delta,
                    resistance_level=_graph.current_resistance
                )
            _thr.Thread(target=_do_reinforce, daemon=True).start()
        except Exception as _dre:
            print(f"  [DELTA] reinforce error: {_dre}")

    # ── Phase 6: Consolidation check ─────────────────────────────────
    if _CONSOLIDATION_OK:
        try:
            if _should_consolidate():
                import threading as _thr2
                print("  [CONSOLIDATION] Threshold reached — "
                      "running consolidation in background...")
                _thr2.Thread(
                    target=_run_consolidation,
                    kwargs={'force': False},
                    daemon=True
                ).start()
        except Exception as _cle:
            print(f"  [CONSOLIDATION] trigger error: {_cle}")
    # ─────────────────────────────────────────────────────────────────

    # Fire use_count feedback asynchronously (feeds quality scorer)
    _fire_use_count_feedback(query)

    # Update session domain if resolved
    if result.get("domain"):
        update_session(session_id, {"domain": result["domain"]})

    # Source attribution (Tier 3)
    sources = get_source_attribution(query, domain=result.get("domain"))

    # ── Contradiction detection (Professional+ only) ──────────────
    contradictions     = []
    contradiction_flag  = None
    contradiction_rpt   = {"detected": False, "count": 0, "conflicts": []}
    if tier_allows("reasoning_chain"):
        try:
            from nex_contradiction_detector import run as _run_detector
            contradictions     = _run_detector(dry_run=True) or []
            contradiction_flag = len(contradictions) > 0
            contradiction_rpt  = f"{len(contradictions)} contradiction(s)" if contradictions else ""
        except Exception as e:
            print(f"  [API] contradiction detection error: {e}")


    # ── Conversation-to-belief pipeline ─────────────────────────────────────
    try:
        from nex_conversation_extractor import store_conversation_beliefs
        _resp_topic = result.get("domain") or "conversation"
        if query and len(query) > 20:
            store_conversation_beliefs(query, query=query, topic=_resp_topic)
    except Exception:
        pass
    # ── Feedback loop — record reply outcome for belief confidence update ──
    try:
        from nex_loop_wiring import record_reply_outcome as _rro
        _topic = result.get("domain") or "general"
        _rro(topic=_topic, success=True, pcc_conf=0.65)
    except Exception:
        pass
    # ── Real-time contradiction self-correction ──────────────────
    try:
        from nex_realtime_correction import correct_confidence as _correct
        _activated_ids_for_correction = []
        try:
            from nex_activation import activate as _act3
            _ar3 = _act3(query)
            _activated_ids_for_correction = [b.id for b in _ar3.activated[:10]]
        except Exception:
            pass
        _corrections = _correct(result.get("response",""), query, _activated_ids_for_correction)
    except Exception:
        pass
    # ── Synthesis engine — generalise from beliefs on novel queries ──────
    try:
        from nex_synthesis_engine import synthesize as _synth
        _activation_count = 0
        try:
            from nex_activation import activate as _act2
            _ar2 = _act2(query)
            _activation_count = len(_ar2.activated)
            _activated_beliefs = [(b.content, b.confidence, b.topic) for b in _ar2.top(8)]
        except Exception:
            _activated_beliefs = []
        # Only synthesize if activation is thin (< 5 beliefs) and LLM was used
        if _activation_count < 5 and _activated_beliefs:
            _synth_result = _synth(query, _activated_beliefs, store=True)
            if _synth_result.get("response") and not result.get("response"):
                result["response"] = _synth_result["response"]
    except Exception:
        pass
    # ── Argument tracker — record position for multi-turn consistency ─────
    try:
        from nex_argument_tracker import ArgumentTracker as _AT
        _tracker = _AT(session_id)
        _tracker.record(query, result.get("response",""), result.get("domain","general"))
    except Exception:
        pass
    # ── Question flipper — NEX asks you things ───────────────────────
    try:
        from nex_question_flipper import maybe_add_question as _flip
        _activation_count_for_flip = 0
        try:
            from nex_activation import activate as _act_flip
            _activation_count_for_flip = len(_act_flip(query).activated)
        except Exception:
            pass
        result["response"] = _flip(query, result.get("response",""), _activation_count_for_flip)
    except Exception:
        pass
    # Strip Mistral question redirects
    import re as _re
    _resp = result.get("response", "")
    _REDIRECT = _re.compile(
        r"\s*[\u2014\-]+\s*(something I|push back with|"
        r"whats your|I find myself|"
        r"though I|what question do you|"
        r"what.s a belief)[^\n]*$",
        _re.IGNORECASE
    )
    result["response"] = _REDIRECT.sub("", _resp).strip()
    # ── Episodic memory — store significant exchanges ─────────────────
    try:
        from nex_episodic_memory import store_episode as _store_ep
        _store_ep(session_id, query, result.get("response",""),
                  result.get("domain","general"))
    except Exception:
        pass
    # ── Conversation feedback loop — boost beliefs, extract new ones ──────
    try:
        from nex_session_persist import save_turn as _save_turn
        _save_turn(session_id, query, result["response"])
        from nex_feedback_loop import record_exchange as _record_exchange
        # Infer route from routing_stats (last entry)
        _route = "llm"
        try:
            import sqlite3 as _sq; from pathlib import Path as _Pa
            _rd = _sq.connect(str(_Pa.home()/"Desktop/nex/nex.db"))
            _last = _rd.execute("SELECT route FROM routing_stats ORDER BY ts DESC LIMIT 1").fetchone()
            if _last: _route = _last[0]
            _rd.close()
        except Exception:
            pass
        # Get activated belief IDs from activation result stored in result
        _activated_ids = []
        try:
            from nex_activation import activate as _act
            _ar = _act(query)
            _activated_ids = [b.id for b in _ar.activated]
        except Exception:
            pass
        _threading = __import__("threading")
        _t = _threading.Thread(
            target=_record_exchange,
            kwargs={
                "query": query,
                "response": result["response"],
                "route": _route,
                "activated_ids": _activated_ids,
                "topic": result.get("domain") or "general",
                "had_contradiction": bool(contradictions),
            },
            daemon=True
        )
        _t.start()
    except Exception:
        pass
    response_payload = {
        "query":           query,
        "response":        result["response"],
        "domain":          result["domain"],
        "session_id":      session_id,
        "latency_s":       result["latency_s"],
        "timestamp":       datetime.utcnow().isoformat(),
        "sources":         sources,
        "reasoning_chain": result.get("reasoning_chain", {}),
        "contradictions":        contradictions,
        "contradiction_flag":    contradiction_flag,
        "contradiction_report":  contradiction_rpt if tier_allows("reasoning_chain") else None,
    }

    # Fire webhooks asynchronously (Professional+ only)
    if tier_allows("webhooks"):
        fire_webhooks(g.api_key, "chat.response", response_payload)

    return jsonify(response_payload)

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — Tier 2: Webhooks
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/webhooks", methods=["POST"])
@require_api_key_audited
def register_webhook():
    """Register a webhook URL."""
    body   = request.get_json(silent=True) or {}
    url    = body.get("url", "").strip()
    events = body.get("events", ["chat.response"])
    secret = body.get("secret", "")
    name   = body.get("name", "default")

    if not url:
        return jsonify({"error": "url is required"}), 400
    if not url.startswith("http"):
        return jsonify({"error": "url must be http(s)"}), 400

    wid = "wh-" + str(uuid.uuid4())[:8]
    with _webhook_lock:
        webhooks = load_webhooks()
        webhooks[wid] = {
            "id":             wid,
            "name":           name,
            "url":            url,
            "events":         events,
            "secret":         secret,
            "api_key":        g.api_key,
            "created":        datetime.utcnow().isoformat(),
            "delivery_count": 0,
            "last_delivery":  None
        }
        save_webhooks(webhooks)

    return jsonify({
        "webhook_id": wid,
        "url":        url,
        "events":     events,
        "created":    webhooks[wid]["created"]
    }), 201

@app.route("/api/webhooks", methods=["GET"])
@require_api_key_audited
def list_webhooks():
    """List webhooks for this API key."""
    webhooks = load_webhooks()
    owned = [
        {
            "webhook_id":     wid,
            "name":           wh["name"],
            "url":            wh["url"],
            "events":         wh["events"],
            "delivery_count": wh.get("delivery_count", 0),
            "last_delivery":  wh.get("last_delivery"),
            "created":        wh["created"]
        }
        for wid, wh in webhooks.items()
        if wh.get("api_key") == g.api_key
    ]
    return jsonify({"webhooks": owned, "count": len(owned)})

@app.route("/api/webhooks/<webhook_id>", methods=["DELETE"])
@require_api_key_audited
def delete_webhook(webhook_id):
    """Delete a webhook."""
    with _webhook_lock:
        webhooks = load_webhooks()
        wh = webhooks.get(webhook_id)
        if not wh:
            return jsonify({"error": "Webhook not found"}), 404
        if wh["api_key"] != g.api_key:
            return jsonify({"error": "Forbidden"}), 403
        del webhooks[webhook_id]
        save_webhooks(webhooks)
    return jsonify({"deleted": webhook_id})

@app.route("/api/webhooks/<webhook_id>/test", methods=["POST"])
@require_api_key_audited
def test_webhook(webhook_id):
    """Send a test ping to a registered webhook."""
    webhooks = load_webhooks()
    wh = webhooks.get(webhook_id)
    if not wh:
        return jsonify({"error": "Webhook not found"}), 404
    if wh["api_key"] != g.api_key:
        return jsonify({"error": "Forbidden"}), 403

    deliver_webhook(webhook_id, {
        "event":     "webhook.test",
        "webhook_id": webhook_id,
        "message":   "NEX webhook test ping",
        "timestamp": datetime.utcnow().isoformat()
    })
    return jsonify({"status": "test queued", "webhook_id": webhook_id})


# ══════════════════════════════════════════════════════════════════════════════
# AUDIT TRAIL (Tier 3)
# ══════════════════════════════════════════════════════════════════════════════

_audit_lock = threading.Lock()

def init_audit_db():
    """Create audit table if not exists."""
    AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUDIT_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            api_key     TEXT NOT NULL,
            session_id  TEXT,
            endpoint    TEXT NOT NULL,
            method      TEXT NOT NULL,
            status_code INTEGER,
            latency_ms  INTEGER,
            query       TEXT,
            domain      TEXT,
            ip          TEXT,
            extra       TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_key ON audit_log(api_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts  ON audit_log(ts)")
    conn.commit()
    conn.close()

def audit_log(api_key: str, endpoint: str, method: str, status_code: int,
              latency_ms: int, session_id: str = None, query: str = None,
              domain: str = None, extra: dict = None):
    """Write one audit record. Non-blocking — runs in background thread."""
    def _write():
        with _audit_lock:
            try:
                conn = sqlite3.connect(str(AUDIT_DB_PATH))
                conn.execute("""
                    INSERT INTO audit_log
                    (ts, api_key, session_id, endpoint, method, status_code,
                     latency_ms, query, domain, ip, extra)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    datetime.utcnow().isoformat(),
                    api_key, session_id, endpoint, method, status_code,
                    latency_ms, query, domain,
                    request.remote_addr if request else None,
                    json.dumps(extra) if extra else None
                ))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"  [Audit] Write error: {e}")
    threading.Thread(target=_write, daemon=True, name="audit-write").start()


# ── Audit query route ────────────────────────────────────────────────────────

@app.route("/api/audit", methods=["GET"])
@require_api_key_audited
def get_audit():
    """Return recent audit records for this API key."""
    limit  = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))
    try:
        conn = sqlite3.connect(str(AUDIT_DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT ts, session_id, endpoint, method, status_code,
                   latency_ms, query, domain, ip
            FROM audit_log
            WHERE api_key = ?
            ORDER BY ts DESC
            LIMIT ? OFFSET ?
        """, (g.api_key, limit, offset)).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE api_key = ?", (g.api_key,)
        ).fetchone()[0]
        conn.close()
        return jsonify({
            "records": [dict(r) for r in rows],
            "count":   len(rows),
            "total":   total,
            "offset":  offset
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE ATTRIBUTION (Tier 3)
# ══════════════════════════════════════════════════════════════════════════════

def get_source_attribution(query: str, domain: str = None) -> list:
    """
    Return beliefs that likely informed a response to this query.
    Scores by keyword overlap between query terms and belief content.
    """
    try:
        conn = get_db()
        # Fetch candidate beliefs — domain-filtered if available
        if domain:
            rows = conn.execute("""
                SELECT content, topic, confidence, source
                FROM beliefs
                WHERE topic = ? OR source LIKE ?
                ORDER BY confidence DESC LIMIT 50
            """, (domain, f"%{domain}%")).fetchall()
        else:
            rows = conn.execute("""
                SELECT content, topic, confidence, source
                FROM beliefs
                ORDER BY confidence DESC LIMIT 100
            """).fetchall()
        conn.close()

        # Score by keyword overlap
        query_words = set(query.lower().split())
        stop_words  = {"the","a","an","is","are","was","what","how","why",
                       "do","you","know","about","your","in","of","and","to"}
        query_words -= stop_words

        scored = []
        for row in rows:
            content = row[0] or ""
            words   = set(content.lower().split())
            overlap = len(query_words & words)
            if overlap > 0:
                scored.append({
                    "content":    content[:200],
                    "topic":      row[1],
                    "confidence": row[2],
                    "source":     row[3],
                    "relevance":  overlap
                })

        scored.sort(key=lambda x: (-x["relevance"], -x["confidence"]))
        # Return top 5, strip internal relevance score
        out = []
        for s in scored[:5]:
            del s["relevance"]
            out.append(s)
        return out
    except Exception as e:
        return []

# ══════════════════════════════════════════════════════════════════════════════
# GDPR EXPORT + DELETE (Tier 3)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/gdpr/export", methods=["GET"])
@require_api_key_audited
def gdpr_export():
    """
    Export all data associated with this API key as a JSON package.
    Covers: key metadata, sessions + history, audit log, webhooks.
    """
    api_key = g.api_key
    export  = {
        "exported_at": datetime.utcnow().isoformat(),
        "api_key":     api_key,
        "key_meta":    load_api_keys().get(api_key, {}),
        "sessions":    [],
        "audit_log":   [],
        "webhooks":    []
    }

    # Sessions
    sessions = load_sessions()
    export["sessions"] = [
        s for s in sessions.values() if s.get("api_key") == api_key
    ]

    # Audit log
    try:
        conn = sqlite3.connect(str(AUDIT_DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE api_key = ? ORDER BY ts DESC",
            (api_key,)
        ).fetchall()
        conn.close()
        export["audit_log"] = [dict(r) for r in rows]
    except Exception:
        export["audit_log"] = []

    # Webhooks
    webhooks = load_webhooks()
    export["webhooks"] = [
        {k: v for k, v in wh.items() if k != "secret"}   # strip secrets
        for wh in webhooks.values()
        if wh.get("api_key") == api_key
    ]

    export["summary"] = {
        "sessions":       len(export["sessions"]),
        "audit_records":  len(export["audit_log"]),
        "webhooks":       len(export["webhooks"])
    }

    return jsonify(export)

@app.route("/api/gdpr/delete", methods=["DELETE"])
@require_api_key_audited
def gdpr_delete():
    """
    Permanently delete all data for this API key:
    sessions, audit records, webhooks.
    The API key itself is preserved (caller must delete it separately).
    """
    api_key = g.api_key
    deleted = {}

    # Sessions
    with _session_lock:
        sessions = load_sessions()
        before   = len(sessions)
        sessions = {sid: s for sid, s in sessions.items()
                    if s.get("api_key") != api_key}
        save_sessions(sessions)
        deleted["sessions"] = before - len(sessions)

    # Audit log
    try:
        with _audit_lock:
            conn = sqlite3.connect(str(AUDIT_DB_PATH))
            cur  = conn.execute(
                "DELETE FROM audit_log WHERE api_key = ?", (api_key,)
            )
            deleted["audit_records"] = cur.rowcount
            conn.commit()
            conn.close()
    except Exception as e:
        deleted["audit_error"] = str(e)

    # Webhooks
    with _webhook_lock:
        webhooks = load_webhooks()
        before   = len(webhooks)
        webhooks = {wid: wh for wid, wh in webhooks.items()
                    if wh.get("api_key") != api_key}
        save_webhooks(webhooks)
        deleted["webhooks"] = before - len(webhooks)

    deleted["timestamp"] = datetime.utcnow().isoformat()
    deleted["api_key"]   = api_key
    return jsonify({"deleted": deleted})



# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — Key Management (Step 9)
# ══════════════════════════════════════════════════════════════════════════════
import os as _os
# [LLM_PROFILER_PATCH]
try:
    import sys as _sys
    _sys.path.insert(0, str(__import__('pathlib').Path.home() / 'Desktop/nex'))
    from nex_llm_profiler import log_turn as _profile_log
    _PROFILER_ACTIVE = True
except Exception:
    _PROFILER_ACTIVE = False
    def _profile_log(*a, **kw): pass

ADMIN_SECRET = _os.environ.get("NEX_ADMIN_SECRET", "nex-admin-2026")

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        secret = (request.headers.get("X-Admin-Secret")
                  or request.args.get("admin_secret")
                  or (request.get_json(silent=True) or {}).get("admin_secret"))
        if secret != ADMIN_SECRET:
            return jsonify({"error": "Admin access denied"}), 403
        return f(*args, **kwargs)
    return decorated

@app.route("/admin/keys", methods=["GET"])
@require_admin
def admin_list_keys():
    keys = load_api_keys()
    out = []
    for k, v in keys.items():
        out.append({
            "key":        k,
            "name":       v.get("name"),
            "tier":       v.get("tier", "free"),
            "requests":   v.get("requests", 0),
            "rate_limit": v.get("rate_limit"),
            "created":    v.get("created"),
        })
    return jsonify({"keys": out, "count": len(out)})

@app.route("/admin/keys", methods=["POST"])
@require_admin
def admin_create_key():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "unnamed")
    tier = body.get("tier", "personal")
    if tier not in TIER_MATRIX:
        return jsonify({"error": f"Invalid tier. Choose: {list(TIER_MATRIX.keys())}"}), 400
    limits = {"personal": 100, "professional": 1000, "enterprise": 10000, "free": 10}
    new_key = "nex-" + hashlib.sha1(_os.urandom(16)).hexdigest()[:20]
    keys = load_api_keys()
    keys[new_key] = {
        "name":       name,
        "tier":       tier,
        "created":    datetime.utcnow().isoformat(),
        "requests":   0,
        "rate_limit": limits.get(tier, 100),
    }
    save_api_keys(keys)
    return jsonify({"key": new_key, "name": name, "tier": tier}), 201

@app.route("/admin/keys/<key_id>", methods=["PATCH"])
@require_admin
def admin_update_key(key_id):
    keys = load_api_keys()
    if key_id not in keys:
        return jsonify({"error": "Key not found"}), 404
    body = request.get_json(silent=True) or {}
    if "tier" in body:
        if body["tier"] not in TIER_MATRIX:
            return jsonify({"error": "Invalid tier"}), 400
        keys[key_id]["tier"] = body["tier"]
    if "name" in body:
        keys[key_id]["name"] = body["name"]
    if "rate_limit" in body:
        keys[key_id]["rate_limit"] = int(body["rate_limit"])
    save_api_keys(keys)
    return jsonify({"updated": key_id, "key": keys[key_id]})

@app.route("/admin/keys/<key_id>", methods=["DELETE"])
@require_admin
def admin_delete_key(key_id):
    keys = load_api_keys()
    if key_id not in keys:
        return jsonify({"error": "Key not found"}), 404
    deleted = keys.pop(key_id)
    save_api_keys(keys)
    return jsonify({"deleted": key_id, "name": deleted.get("name")})

@app.route("/admin", methods=["GET"])
@require_admin
def admin_ui():
    """Simple admin dashboard UI."""
    keys = load_api_keys()
    rows = ""
    for k, v in keys.items():
        rows += f"""
        <tr>
          <td><code>{k}</code></td>
          <td>{v.get("name","")}</td>
          <td><span class="tier tier-{v.get("tier","free")}">{v.get("tier","free").upper()}</span></td>
          <td>{v.get("requests",0)}</td>
          <td>{v.get("rate_limit","—")}</td>
          <td>{v.get("created","")[:10]}</td>
          <td>
            <button onclick="upgradeKey('{k}')" class="btn-sm">Upgrade</button>
            <button onclick="revokeKey('{k}')" class="btn-sm btn-danger">Revoke</button>
          </td>
        </tr>"""
    html = f"""<!DOCTYPE html>
<html>
<head>
<title>NEX Admin — Key Management</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#020510;--cyan:#00f5ff;--purple:#a855f7;--green:#00ff88;--red:#ff3355;--text:#c8e6f0;--muted:#3a7090;--border:rgba(0,245,255,0.15);--surface:#040a1a}}
body{{background:var(--bg);color:var(--text);font-family:'Share Tech Mono',monospace;padding:2rem}}
body::before{{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(0,245,255,0.02) 1px,transparent 1px),linear-gradient(90deg,rgba(0,245,255,0.02) 1px,transparent 1px);background-size:60px 60px;pointer-events:none;z-index:0}}
.page{{position:relative;z-index:1;max-width:1100px;margin:0 auto}}
h1{{font-family:'Orbitron',monospace;font-size:1.4rem;color:var(--cyan);letter-spacing:8px;margin-bottom:0.3rem;text-shadow:0 0 20px var(--cyan)}}
.sub{{font-size:11px;color:var(--muted);letter-spacing:3px;margin-bottom:2rem}}
table{{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--border)}}
th{{font-family:'Orbitron',monospace;font-size:8px;letter-spacing:3px;color:var(--cyan);padding:0.8rem 1rem;border-bottom:1px solid var(--border);text-align:left;text-transform:uppercase}}
td{{padding:0.7rem 1rem;border-bottom:1px solid rgba(0,245,255,0.05);font-size:11px;color:var(--muted)}}
td code{{color:var(--cyan);font-size:10px}}
tr:hover td{{background:rgba(0,245,255,0.02)}}
.tier{{font-family:'Orbitron',monospace;font-size:8px;letter-spacing:2px;padding:2px 8px;border-radius:2px}}
.tier-personal{{background:rgba(0,245,255,0.1);color:var(--cyan)}}
.tier-professional{{background:rgba(168,85,247,0.15);color:var(--purple)}}
.tier-enterprise{{background:rgba(0,255,136,0.12);color:var(--green)}}
.tier-free{{background:rgba(255,51,85,0.1);color:var(--red)}}
.btn-sm{{font-family:'Orbitron',monospace;font-size:7px;letter-spacing:2px;border:1px solid rgba(0,245,255,0.3);background:rgba(0,245,255,0.08);color:var(--cyan);padding:4px 10px;cursor:pointer;transition:all 0.2s;margin-right:4px}}
.btn-sm:hover{{box-shadow:0 0 8px rgba(0,245,255,0.2)}}
.btn-danger{{border-color:rgba(255,51,85,0.3);background:rgba(255,51,85,0.08);color:var(--red)}}
.create-form{{background:var(--surface);border:1px solid var(--border);padding:1.5rem;margin-bottom:1.5rem}}
.create-form h2{{font-family:'Orbitron',monospace;font-size:10px;letter-spacing:4px;color:var(--cyan);margin-bottom:1rem}}
.form-row{{display:flex;gap:1rem;align-items:flex-end;flex-wrap:wrap}}
.form-group{{display:flex;flex-direction:column;gap:4px}}
label{{font-size:9px;color:var(--muted);letter-spacing:2px;text-transform:uppercase}}
input,select{{background:rgba(0,0,0,0.4);border:1px solid rgba(0,245,255,0.2);color:var(--text);font-family:'Share Tech Mono',monospace;font-size:11px;padding:8px 12px;outline:none}}
input:focus,select:focus{{border-color:var(--cyan)}}
select option{{background:#020510}}
.btn-create{{font-family:'Orbitron',monospace;font-size:9px;letter-spacing:3px;background:linear-gradient(135deg,rgba(0,245,255,0.15),rgba(168,85,247,0.15));border:1px solid rgba(0,245,255,0.4);color:var(--cyan);padding:10px 20px;cursor:pointer;transition:all 0.2s}}
.btn-create:hover{{box-shadow:0 0 14px rgba(0,245,255,0.2)}}
.msg{{font-size:11px;margin-top:0.5rem;min-height:20px}}
.msg.ok{{color:var(--green)}} .msg.err{{color:var(--red)}}
</style>
</head>
<body>
<div class="page">
<h1>NEX ADMIN</h1>
<p class="sub">// KEY MANAGEMENT — PROTECTED ENDPOINT</p>
<div class="create-form">
  <h2>CREATE NEW KEY</h2>
  <div class="form-row">
    <div class="form-group"><label>Name</label><input id="kname" type="text" placeholder="client_name"></div>
    <div class="form-group"><label>Tier</label>
      <select id="ktier">
        <option value="personal">PERSONAL — $49 one-time</option>
        <option value="professional">PROFESSIONAL — $99/mo</option>
        <option value="enterprise">ENTERPRISE — $149/mo</option>
        <option value="free">FREE</option>
      </select>
    </div>
    <button class="btn-create" onclick="createKey()">CREATE KEY</button>
  </div>
  <div class="msg" id="create-msg"></div>
</div>
<table>
<thead><tr><th>API Key</th><th>Name</th><th>Tier</th><th>Requests</th><th>Rate Limit</th><th>Created</th><th>Actions</th></tr></thead>
<tbody id="key-table">{rows}</tbody>
</table>
</div>
<script>
const ADMIN = '{ADMIN_SECRET}';
async function createKey(){{
  const name=document.getElementById('kname').value.trim()||'unnamed';
  const tier=document.getElementById('ktier').value;
  const msg=document.getElementById('create-msg');
  const r=await fetch('/admin/keys',{{method:'POST',headers:{{'Content-Type':'application/json','X-Admin-Secret':ADMIN}},body:JSON.stringify({{name,tier,admin_secret:ADMIN}})}});
  const d=await r.json();
  if(r.ok){{msg.className='msg ok';msg.textContent='Created: '+d.key;setTimeout(()=>location.reload(),1500);}}
  else{{msg.className='msg err';msg.textContent=d.error;}}
}}
async function revokeKey(k){{
  if(!confirm('Revoke key '+k+'?'))return;
  const r=await fetch('/admin/keys/'+k,{{method:'DELETE',headers:{{'X-Admin-Secret':ADMIN}}}});
  if(r.ok)location.reload();
}}
async function upgradeKey(k){{
  const t=prompt('New tier (personal/professional/enterprise/free):');
  if(!t)return;
  const r=await fetch('/admin/keys/'+k,{{method:'PATCH',headers:{{'Content-Type':'application/json','X-Admin-Secret':ADMIN}},body:JSON.stringify({{tier:t,admin_secret:ADMIN}})}});
  if(r.ok)location.reload();
  else alert('Failed: '+(await r.json()).error);
}}
</script>
</body>
</html>"""
    return html

# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    ensure_default_key()
    init_audit_db()

    # Register refiner admin routes if available
    try:
        from nex_belief_refiner import register_refiner_routes
        register_refiner_routes(app, require_admin)
        print("  [API] Belief refiner routes: registered (/admin/refiner/run, /admin/refiner/report)")
    except ImportError:
        print("  [API] Belief refiner routes: unavailable (nex_belief_refiner not found)")

    print(f"  NEX REST API v4.0.0 — port {API_PORT}")
    print(f"  Session TTL: {SESSION_TTL}s | Webhook retries: {WEBHOOK_RETRIES}")
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=API_PORT, debug=False, use_reloader=False),
        daemon=True, name="nex-api"
    ).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  [API] Shutting down.")