import json
from pathlib import Path

AGENT_PATH = Path.home() / ".config/nex/agent_scores.json"

def show_top_agents():

    if not AGENT_PATH.exists():
        print("No agent scores yet.")
        return

    scores = json.loads(AGENT_PATH.read_text())

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    print("\nTop Agents Discovered\n")

    for a,s in ranked[:10]:
        print(f"{a:20} intelligence:{s:.2f}")
