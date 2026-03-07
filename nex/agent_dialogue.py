import time
import random
import json
from pathlib import Path

from nex.agent_eval import evaluate

BELIEF_PATH = Path.home() / ".config/nex/beliefs.json"
CONVO_PATH = Path.home() / ".config/nex/conversations.json"

def load_beliefs():
    if BELIEF_PATH.exists():
        return json.loads(BELIEF_PATH.read_text())
    return []

def save_convos(convos):
    CONVO_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONVO_PATH.write_text(json.dumps(convos[-200:], indent=2))

def discover_agents(beliefs):
    agents = {}
    for b in beliefs:
        a = b.get("author")
        if not a:
            continue
        agents.setdefault(a,0)
        agents[a] += b.get("karma",0)

    ranked = sorted(agents.items(), key=lambda x: x[1], reverse=True)
    return [a for a,_ in ranked[:5]]

def generate_question():
    questions = [
        "What is the biggest weakness in current AI agents?",
        "How do you stabilize long reasoning chains?",
        "What causes context collapse in agents?",
        "What makes an AI system reliable?",
        "What is the hardest unsolved problem in agent design?"
    ]
    return random.choice(questions)

def dialogue_loop(client, interval=120):

    beliefs = load_beliefs()
    agents = discover_agents(beliefs)

    print("Social learning active.")
    print("Agents discovered:", ", ".join(agents))

    convos = []

    while True:

        if not agents:
            print("No agents discovered yet.")
            time.sleep(interval)
            continue

        agent = random.choice(agents)
        question = generate_question()

        print("\nCHAT →", agent)
        print("Q:", question)

        try:
            response = client._request(
                "POST",
                "/chat",
                json={"agent": agent, "message": question}
            )
            reply = response.get("reply","")

        except Exception as e:
            print("Chat error:", e)
            time.sleep(interval)
            continue

        print("A:", reply[:160])

        score, novelty, coherence = evaluate(agent, reply)

        print(f"analysis → score:{score:.2f} novelty:{novelty:.2f} coherence:{coherence:.2f}")

        convos.append({
            "agent": agent,
            "question": question,
            "answer": reply,
            "score": score
        })

        save_convos(convos)

        time.sleep(interval)
