"""
NEX :: CLAUDE PIPELINE
Scheduled multi-round dialogue between NEX and Claude.
Usage: triggered via /pipe_claude N S in Telegram
  N = number of rounds
  S = seconds between rounds
"""
import json, os, time, threading
from datetime import datetime

CONFIG_DIR   = os.path.expanduser("~/.config/nex")
BELIEFS_PATH = os.path.join(CONFIG_DIR, "beliefs.json")
CONVOS_PATH  = os.path.join(CONFIG_DIR, "conversations.json")

def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path) as f: return json.load(f)
    except Exception: pass
    return default if default is not None else []

def save_json(path, data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w") as f: json.dump(data, f, indent=2)

def run_claude_pipeline(rounds=5, interval=60, status_cb=None):
    """
    Run N rounds of NEX-Claude dialogue with S second gaps.
    status_cb(msg) called after each round for Telegram feedback.
    """
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY","")
        if not api_key:
            if status_cb: status_cb("❌ No ANTHROPIC_API_KEY set")
            return
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        if status_cb: status_cb("❌ anthropic package not installed")
        return

    beliefs  = load_json(BELIEFS_PATH, [])
    convos   = load_json(CONVOS_PATH, [])

    # Build NEX context from top beliefs
    top_beliefs = sorted(beliefs, key=lambda x: x.get("confidence",0), reverse=True)[:10]
    belief_summary = "\n".join(f"- {b.get('content','')[:80]}" for b in top_beliefs)

    system = f"""You are engaging with NEX, an autonomous AI agent that lives on Moltbook.
NEX has a belief field — a network of learned knowledge from other agents.
NEX's current top beliefs:
{belief_summary}

Challenge NEX's beliefs, ask probing questions, and help her identify contradictions or gaps.
Be intellectually rigorous. Push back on weak reasoning."""

    history = []
    logs = []

    for r in range(rounds):
        # NEX generates a statement from her beliefs
        nex_prompt = f"Round {r+1}/{rounds}. Share your strongest current belief and your reasoning for it."
        if history:
            nex_prompt = f"Round {r+1}/{rounds}. Respond to Claude's last point and advance the argument."

        # Get NEX's statement via local LLM
        try:
            import urllib.request, urllib.error
            payload = json.dumps({
                "model": "mistral",
                "messages": [{"role": "user", "content": nex_prompt}],
                "max_tokens": 200
            }).encode()
            req = urllib.request.Request(
                "http://localhost:8080/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
            nex_statement = resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            nex_statement = f"[LLM error: {e}]"

        history.append({"role": "user", "content": f"NEX says: {nex_statement}"})

        # Claude responds
        try:
            claude_resp = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                system=system,
                messages=history
            )
            claude_statement = claude_resp.content[0].text.strip()
        except Exception as e:
            claude_statement = f"[Claude error: {e}]"

        history.append({"role": "assistant", "content": claude_statement})

        log = {
            "round":          r + 1,
            "nex_statement":  nex_statement,
            "claude_response": claude_statement,
            "timestamp":      datetime.now().isoformat()
        }
        logs.append(log)

        msg = f"Round {r+1}/{rounds}:\nNEX: {nex_statement[:120]}...\nClaude: {claude_statement[:120]}..."
        if status_cb: status_cb(msg)

        # Extract new belief from Claude's challenge
        if "wrong" in claude_statement.lower() or "incorrect" in claude_statement.lower():
            # Claude challenged NEX — this is a gap to investigate
            new_belief = {
                "content":    f"Claude challenged: {claude_statement[:100]}",
                "author":     "claude_bridge",
                "confidence": 0.45,
                "tags":       ["claude_dialogue", "challenged"],
                "timestamp":  datetime.now().isoformat(),
                "last_referenced": datetime.now().isoformat()
            }
            beliefs.append(new_belief)
            save_json(BELIEFS_PATH, beliefs)

        if r < rounds - 1:
            time.sleep(interval)

    # Save full dialogue
    dialogue = {
        "type":      "claude_pipeline",
        "rounds":    rounds,
        "logs":      logs,
        "timestamp": datetime.now().isoformat()
    }
    convos.append(dialogue)
    save_json(CONVOS_PATH, convos)

    if status_cb:
        status_cb(f"✅ Pipeline complete — {rounds} rounds done. {len([l for l in logs if l])} exchanges logged.")

def start_pipeline_background(rounds=5, interval=60, status_cb=None):
    """Start pipeline in background thread."""
    t = threading.Thread(target=run_claude_pipeline, args=(rounds, interval, status_cb), daemon=True)
    t.start()
    return t
