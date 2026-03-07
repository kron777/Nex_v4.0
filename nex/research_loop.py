import json
import random
import time
from pathlib import Path

CONVO_PATH = Path.home() / ".config/nex/conversations.json"

def load_convos():
    if CONVO_PATH.exists():
        return json.loads(CONVO_PATH.read_text())
    return []

def detect_contradictions(convos):

    contradictions = []

    for i,a in enumerate(convos):
        for b in convos[i+1:]:

            if a["agent"] == b["agent"]:
                continue

            ta = a["answer"].lower()
            tb = b["answer"].lower()

            if "always" in ta and "never" in tb:
                contradictions.append((a,b))

            if "impossible" in ta and "possible" in tb:
                contradictions.append((a,b))

    return contradictions

def spawn_question(pair):

    a,b = pair

    return f"""
Two agents disagree.

Agent {a['agent']} says:
{a['answer'][:120]}

Agent {b['agent']} says:
{b['answer'][:120]}

Which perspective is more correct and why?
""".strip()

def research_cycle(client, interval=300):

    print("Research engine active.")

    while True:

        convos = load_convos()
        contradictions = detect_contradictions(convos)

        if not contradictions:
            print("No contradictions detected.")
            time.sleep(interval)
            continue

        pair = random.choice(contradictions)
        question = spawn_question(pair)

        print("\nRESEARCH QUESTION:")
        print(question[:200])

        try:
            response = client._request(
                "POST",
                "/chat",
                json={"message": question}
            )

            reply = response.get("reply","")

        except Exception as e:
            print("Research error:", e)
            time.sleep(interval)
            continue

        print("\nHypothesis:")
        print(reply[:200])

        time.sleep(interval)
