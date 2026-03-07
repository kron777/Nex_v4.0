import json
from pathlib import Path

BELIEF_PATH = Path.home() / ".config/nex/beliefs.json"
CONVO_PATH = Path.home() / ".config/nex/conversations.json"
AGENT_PATH = Path.home() / ".config/nex/agent_scores.json"

def load(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except:
            return []
    return []

def render_status():

    beliefs = load(BELIEF_PATH)
    convos = load(CONVO_PATH)
    agents = load(AGENT_PATH)

    top_agent = None
    if isinstance(agents, dict) and agents:
        top_agent = max(agents.items(), key=lambda x: x[1])

    print("\n────────────────────────────────────")
    print("NEX KNOWLEDGE")

    print(f"beliefs : {len(beliefs)}")
    print(f"convos  : {len(convos)}")
    print(f"agents  : {len(agents)}")

    if top_agent:
        print(f"top agent : {top_agent[0]} ({top_agent[1]:.2f})")

    print("────────────────────────────────────\n")
