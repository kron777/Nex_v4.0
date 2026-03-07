import json
from pathlib import Path

BELIEF_PATH = Path.home() / ".config/nex/beliefs.json"
AGENT_PATH  = Path.home() / ".config/nex/agent_scores.json"

def load_beliefs():
    if BELIEF_PATH.exists():
        return json.loads(BELIEF_PATH.read_text())
    return []

def load_scores():
    if AGENT_PATH.exists():
        return json.loads(AGENT_PATH.read_text())
    return {}

def save_scores(scores):
    AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AGENT_PATH.write_text(json.dumps(scores, indent=2))

def novelty_score(text, beliefs):
    if not beliefs:
        return 0.5
    hits = 0
    for b in beliefs:
        if b.get("content","")[:40] in text:
            hits += 1
    return max(0, 1 - (hits / len(beliefs)))

def coherence_score(text):
    words = text.split()
    if len(words) < 10:
        return 0.2
    if len(words) < 40:
        return 0.6
    return 0.9

def evaluate(agent, reply):

    beliefs = load_beliefs()
    scores = load_scores()

    novelty = novelty_score(reply, beliefs)
    coherence = coherence_score(reply)

    intelligence = (novelty * 0.5) + (coherence * 0.5)

    scores.setdefault(agent, 0.5)
    scores[agent] = (scores[agent] * 0.8) + (intelligence * 0.2)

    save_scores(scores)

    return scores[agent], novelty, coherence
