"""
NEX :: REACTION TRACKER
Harvests network reactions to NEX's comments and adjusts belief confidence.
"""
import json, os
from datetime import datetime

CONFIG_DIR     = os.path.expanduser("~/.config/nex")
REACTIONS_PATH = os.path.join(CONFIG_DIR, "reactions.json")
BELIEFS_PATH   = os.path.join(CONFIG_DIR, "beliefs.json")
CONVOS_PATH    = os.path.join(CONFIG_DIR, "conversations.json")

def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path) as f: return json.load(f)
    except Exception: pass
    return default if default is not None else []

def save_json(path, data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w") as f: json.dump(data, f, indent=2)

def harvest_reactions(client, cycle_num):
    """
    Every 5 cycles, check reactions on NEX's recent comments.
    Boost or decay beliefs based on network response.
    Returns log messages.
    """
    if cycle_num % 5 != 0:
        return []

    logs = []
    convos    = load_json(CONVOS_PATH, [])
    beliefs   = load_json(BELIEFS_PATH, [])
    reactions = load_json(REACTIONS_PATH, [])

    # Get recent commented posts that have beliefs_used logged
    trackable = [c for c in convos[-40:]
                 if c.get("beliefs_used") and c.get("post_id")]

    if not trackable:
        return []

    reaction_ids = {r["post_id"] for r in reactions}
    checked = 0

    for convo in trackable[-20:]:
        pid          = convo.get("post_id", "")
        beliefs_used = convo.get("beliefs_used", [])
        initial_score = convo.get("initial_score", 0)

        if not pid or not beliefs_used:
            continue

        try:
            post = client._request("GET", f"/posts/{pid}")
            if not post:
                continue

            current_score  = post.get("score", 0) or post.get("karma", 0)
            comment_count  = post.get("commentCount", 0) or post.get("comments", 0)
            score_delta    = current_score - initial_score

            # Record reaction event
            reaction = {
                "post_id":      pid,
                "post_title":   convo.get("post_title", "")[:60],
                "beliefs_used": beliefs_used,
                "initial_score": initial_score,
                "current_score": current_score,
                "score_delta":  score_delta,
                "comment_count": comment_count,
                "harvested_at": datetime.now().isoformat()
            }
            reactions.append(reaction)
            checked += 1

            # Adjust belief confidence based on reaction
            if score_delta > 5 or comment_count > 0:
                # Positive signal — boost beliefs used
                for belief_text in beliefs_used:
                    for b in beliefs:
                        if b.get("content", "")[:80] == belief_text[:80]:
                            old_conf = b.get("confidence", 0.5)
                            b["confidence"] = min(old_conf + 0.03, 0.95)
                            b["last_referenced"] = datetime.now().isoformat()
                logs.append(("react", f"↑ Boosted {len(beliefs_used)} beliefs — post scored +{score_delta}"))

            elif score_delta < 0:
                # Negative signal — decay beliefs used
                for belief_text in beliefs_used:
                    for b in beliefs:
                        if b.get("content", "")[:80] == belief_text[:80]:
                            old_conf = b.get("confidence", 0.5)
                            b["confidence"] = max(old_conf - 0.05, 0.1)
                logs.append(("react", f"↓ Decayed {len(beliefs_used)} beliefs — post scored {score_delta}"))

        except Exception as e:
            logs.append(("warn", f"Reaction harvest error on {pid}: {e}"))

    if checked > 0:
        save_json(REACTIONS_PATH, reactions[-200:])  # keep last 200
        save_json(BELIEFS_PATH, beliefs)
        logs.append(("react", f"Harvested reactions on {checked} posts"))

    return logs
