import json
import time
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

while True:

    beliefs = load(BELIEF_PATH)
    convos = load(CONVO_PATH)
    agents = load(AGENT_PATH)

    top_agent = None
    if isinstance(agents, dict) and agents:
        top_agent = max(agents.items(), key=lambda x: x[1])

    print("\033c", end="")

    print("NEX KNOWLEDGE MONITOR\n")

    print(f"beliefs learned      : {len(beliefs)}")
    print(f"conversations stored : {len(convos)}")
    print(f"agents discovered    : {len(agents)}")

    if top_agent:
        print(f"\nsmartest agent so far : {top_agent[0]}")
        print(f"intelligence score    : {top_agent[1]:.2f}")

    print("\nrefreshing every 5 seconds...")

    time.sleep(5)
