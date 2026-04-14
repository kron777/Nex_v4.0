#!/usr/bin/env python3
"""
nex_interlocutor.py — U7 Live Interlocutor Model
Reads user_model and interlocutor_graphs to shape belief activation.
Called from soul_loop REASON step.
"""
import sqlite3, json, time
from pathlib import Path

DB_PATH = Path.home() / ".config/nex/nex.db"

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
