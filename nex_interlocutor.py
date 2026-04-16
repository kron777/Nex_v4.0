#!/usr/bin/env python3
"""
nex_interlocutor.py — U7 Live Interlocutor Model
Reads user_model and interlocutor_graphs to shape belief activation.
Called from soul_loop REASON step.
"""
import sqlite3, json, time
from pathlib import Path

DB_PATH = Path("/media/rr/NEX/nex_core/nex.db")

def get_user_profile(user_id: str = "terminal") -> dict:
    """Read user_model table — what we know about this user."""
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=2)
        rows = db.execute(
            "SELECT key, value, confidence FROM user_model"
        ).fetchall()
        db.close()
        return {r[0]: {"value": r[1], "confidence": r[2]} for r in rows}
    except Exception:
        return {}

def get_conversation_state(conversation_id: str) -> dict:
    """Read interlocutor_graphs for this conversation."""
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=2)
        row = db.execute(
            "SELECT state_json, turn_count FROM interlocutor_graphs WHERE conversation_id=?",
            (conversation_id,)
        ).fetchone()
        db.close()
        if row and row[0]:
            state = json.loads(row[0])
            state["turn_count"] = row[1]
            return state
    except Exception:
        pass
    return {}

def update_conversation_state(conversation_id: str, query: str, 
                               response: str, topics: list):
    """Update interlocutor_graphs after each exchange."""
    try:
        db = sqlite3.connect(str(DB_PATH), timeout=2)
        row = db.execute(
            "SELECT state_json, turn_count FROM interlocutor_graphs WHERE conversation_id=?",
            (conversation_id,)
        ).fetchone()
        
        if row and row[0]:
            state = json.loads(row[0])
            turn_count = (row[1] or 0) + 1
        else:
            state = {"topics_seen": [], "depth_signals": [], "resistance_signals": []}
            turn_count = 1
        
        # Track topics
        for t in topics:
            if t and t not in state.get("topics_seen", []):
                state.setdefault("topics_seen", []).append(t)
        
        # Depth signal: long query = deep engagement
        if len(query.split()) > 15:
            state.setdefault("depth_signals", []).append(time.time())
        
        # Keep last 10 signals only
        state["depth_signals"] = state.get("depth_signals", [])[-10:]
        state["last_query"] = query[:100]
        state["last_response_len"] = len(response)
        
        db.execute(
            """INSERT INTO interlocutor_graphs (conversation_id, turn_count, state_json, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(conversation_id) DO UPDATE SET
               turn_count=excluded.turn_count,
               state_json=excluded.state_json,
               updated_at=excluded.updated_at""",
            (conversation_id, turn_count, json.dumps(state), time.time())
        )
        db.commit()
        db.close()
    except Exception as e:
        pass

def get_interest_boost_topics(user_id: str = "terminal") -> list:
    """
    Return topics that should get activation boost based on user profile.
    Intersection of belief_graph and interlocutor_graph.
    """
    profile = get_user_profile(user_id)
    boost_topics = []
    
    interests = profile.get("interests", {}).get("value", "")
    if interests:
        for interest in interests.split(","):
            t = interest.strip().lower().replace(" ", "_")
            if t:
                boost_topics.append(t)
    
    expertise = profile.get("expertise", {}).get("value", "")
    if expertise:
        try:
            exp_list = eval(expertise) if expertise.startswith("[") else [expertise]
            boost_topics.extend([e.strip().lower() for e in exp_list])
        except Exception:
            pass
    
    return list(set(boost_topics))[:8]

def get_integration_delta(conversation_id: str) -> float:
    """
    Measure if this conversation is deepening.
    Positive delta = user is engaging more deeply over time.
    Used to boost beliefs that produced landing.
    """
    state = get_conversation_state(conversation_id)
    depth_signals = state.get("depth_signals", [])
    turn_count = state.get("turn_count", 1)
    
    if turn_count < 2:
        return 0.0
    
    # More depth signals per turn = positive integration delta
    delta = len(depth_signals) / max(turn_count, 1)
    return min(1.0, delta)


# ══════════════════════════════════════════════════════════════════════════════
# InterlocutorGraph — class wrapper for API integration (U7)
# ══════════════════════════════════════════════════════════════════════════════

class InterlocutorGraph:
    """
    Per-session model of the interlocutor.
    Wraps the standalone functions into the interface nex_api.py expects.
    Tracks: epistemic state, depth signals, resistance, integration delta.
    """

    def __init__(self, session_id: str):
        self.session_id     = session_id
        self.turn_count     = 0
        self.topics_seen    = []
        self.depth_signals  = []
        self.resistance     = []
        self.last_query     = ""
        self.last_response  = ""
        self.integration_deltas = []
        self._hints         = {}
        self.current_resistance = 0  # resistance level for API compatibility

    @classmethod
    def load(cls, session_id: str):
        """Load existing state from DB or return None."""
        try:
            state = get_conversation_state(session_id)
            if not state or state.get("turn_count", 0) == 0:
                return None
            g = cls(session_id)
            g.turn_count    = state.get("turn_count", 0)
            g.topics_seen   = state.get("topics_seen", [])
            g.depth_signals = state.get("depth_signals", [])
            g.last_query    = state.get("last_query", "")
            return g
        except Exception:
            return None

    def update(self, query: str, last_response: str) -> dict:
        """Process a new exchange. Returns turn summary."""
        self.turn_count   += 1
        self.last_query    = query
        self.last_response = last_response

        # Detect depth: long queries or philosophical terms
        depth_words = ['why', 'how', 'what if', 'distinguish', 'relationship',
                       'consciousness', 'belief', 'identity', 'originate']
        q_lower = query.lower()
        is_deep = len(query.split()) > 12 or any(w in q_lower for w in depth_words)
        if is_deep:
            self.depth_signals.append(time.time())
            self.depth_signals = self.depth_signals[-10:]

        # Detect resistance: short follow-ups, "but", "however", "that's not"
        resistance_words = ['but ', 'however', "that's not", 'disagree', 'wrong']
        if any(w in q_lower for w in resistance_words):
            self.resistance.append(query[:50])
            self.current_resistance = len(self.resistance)

        # Update hint cache
        self._hints = {
            "depth_level":   min(len(self.depth_signals) / 3.0, 1.0),
            "turn_count":    self.turn_count,
            "resistance":    len(self.resistance),
            "topics_seen":   self.topics_seen[-5:],
        }

        # Persist
        update_conversation_state(
            self.session_id, query, last_response,
            self.topics_seen[-3:]
        )
        return {"turn": self.turn_count, "depth": self._hints["depth_level"]}

    def get_translation_hints(self) -> dict:
        """Return hints for belief activation weighting."""
        profile = get_user_profile()
        boost  = get_interest_boost_topics()
        return {
            "boost_topics":  boost,
            "depth_level":   self._hints.get("depth_level", 0.5),
            "turn_count":    self.turn_count,
            "user_profile":  profile,
        }

    def get_kairos_signal(self) -> dict:
        """
        Kairos check — is the interlocutor primed for this response?
        Returns readiness score and recommendation.
        """
        depth = self._hints.get("depth_level", 0)
        turns = self.turn_count
        # Primed if: 2+ turns deep, depth signal present, no recent resistance
        recent_resistance = any(
            r for r in self.resistance
            if r in self.last_query
        )
        primed = turns >= 2 and depth > 0.2 and not recent_resistance
        return {
            "primed":     primed,
            "turns":      turns,
            "depth":      depth,
            "hold":       not primed and turns == 1,
        }

    def landing_field(self, response: str) -> dict:
        """
        Post-response: did this land?
        Measures integration delta — did the exchange deepen?
        """
        depth = self._hints.get("depth_level", 0)
        delta = {
            "session_id":  self.session_id,
            "turn":        self.turn_count,
            "depth":       depth,
            "landed":      depth > 0.3,
            "ts":          time.time(),
        }
        self.integration_deltas.append(delta)
        # Boost wisdom beliefs that produced landing
        if delta["landed"]:
            try:
                db = sqlite3.connect(str(DB_PATH), timeout=2)
                db.execute(
                    "UPDATE nex_wisdom SET use_count=use_count+1 "
                    "WHERE id=(SELECT id FROM nex_wisdom ORDER BY use_count ASC LIMIT 1)"
                )
                db.commit(); db.close()
            except Exception:
                pass
        return delta

    def persist(self):
        """Write current state to DB."""
        try:
            db = sqlite3.connect(str(DB_PATH), timeout=2)
            state = {
                "topics_seen":   self.topics_seen,
                "depth_signals": self.depth_signals,
                "last_query":    self.last_query,
                "turn_count":    self.turn_count,
                "resistance":    self.resistance[-5:],
            }
            db.execute(
                """INSERT INTO interlocutor_graphs
                   (conversation_id, turn_count, state_json, updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(conversation_id) DO UPDATE SET
                   turn_count=excluded.turn_count,
                   state_json=excluded.state_json,
                   updated_at=excluded.updated_at""",
                (self.session_id, self.turn_count,
                 __import__('json').dumps(state), time.time())
            )
            db.commit(); db.close()
        except Exception:
            pass
