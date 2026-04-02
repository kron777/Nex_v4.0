"""
nex_execution_loop.py
ReAct-pattern execution loop for NEX.
Thought -> Action -> Observation -> repeat.
Tool registry: web_search, file_read, sqlite_query, shell_exec.
"""
import subprocess, sqlite3, json, logging, time, re
from pathlib import Path

log     = logging.getLogger("nex.exec")
DB_PATH = Path.home() / "Desktop/nex/nex.db"

# ── Tool registry ─────────────────────────────────────────────────────────────
TOOLS = {}

def tool(name, description):
    def decorator(fn):
        TOOLS[name] = {"fn": fn, "description": description}
        return fn
    return decorator

@tool("sqlite_query", "Query NEX belief database. Input: SQL string.")
def sqlite_query(sql: str) -> str:
    try:
        db  = sqlite3.connect(str(DB_PATH))
        cur = db.execute(sql)
        rows = cur.fetchmany(10)
        db.close()
        return json.dumps(rows)
    except Exception as e:
        return f"ERROR: {e}"

@tool("file_read", "Read a file from disk. Input: absolute path string.")
def file_read(path: str) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"ERROR: {path} not found"
        return p.read_text()[:2000]
    except Exception as e:
        return f"ERROR: {e}"

@tool("shell_exec", "Run a safe shell command. Input: command string.")
def shell_exec(cmd: str) -> str:
    # Safety: whitelist only read-only commands
    ALLOWED = ["ls","cat","wc","grep","find","tail","head","ps","df","free","date"]
    first = cmd.strip().split()[0]
    if first not in ALLOWED:
        return f"BLOCKED: '{first}' not in allowed commands {ALLOWED}"
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                          text=True, timeout=10)
        return (r.stdout + r.stderr)[:1000]
    except Exception as e:
        return f"ERROR: {e}"

@tool("belief_search", "Search NEX beliefs by topic or keyword. Input: search term.")
def belief_search(query: str) -> str:
    try:
        import sys
        sys.path.insert(0, "/home/rr/Desktop/nex")
        from nex_embed import BeliefFAISSIndex
        idx  = BeliefFAISSIndex()
        hits = idx.top_k(query, k=5)
        return json.dumps(hits[:5])
    except Exception as e:
        return f"ERROR: {e}"

# ── ReAct loop ────────────────────────────────────────────────────────────────
import requests
API = "http://localhost:8080/completion"

REACT_SYSTEM = """You are NEX executing a task step by step.
Available tools: {tools}

Format each step as:
Thought: <what you're thinking>
Action: <tool_name>
Input: <tool input>

When done:
Thought: I have enough information.
Answer: <final answer>"""

def run(task: str, max_steps=5) -> dict:
    """Execute a task using ReAct pattern."""
    import sys
    sys.path.insert(0, "/home/rr/Desktop/nex")
    from nex_identity_anchor import get_system_prompt

    tool_list = "\n".join(
        f"  - {name}: {info['description']}"
        for name, info in TOOLS.items()
    )
    system = REACT_SYSTEM.format(tools=tool_list)

    history = []
    steps   = []

    for step_n in range(max_steps):
        # Build prompt from history
        hist_text = "\n".join(history)
        prompt = (f"<|im_start|>system\n{system}<|im_end|>\n"
                  f"<|im_start|>user\nTask: {task}<|im_end|>\n"
                  f"<|im_start|>assistant\n{hist_text}")

        try:
            r = requests.post(API, json={
                "prompt": prompt, "n_predict": 200,
                "temperature": 0.2,
                "stop": ["<|im_end|>", "Observation:"],
                "cache_prompt": False
            }, timeout=30)
            text = r.json().get("content", "").strip()
        except Exception as e:
            log.error(f"LLM call failed: {e}")
            break

        history.append(text)
        log.info(f"Step {step_n+1}:\n{text}")

        # Check for final answer
        if "Answer:" in text:
            answer = text.split("Answer:")[-1].strip()
            return {"steps": steps, "answer": answer, "complete": True}

        # Parse action
        action_m = re.search(r'Action:\s*(\w+)', text)
        input_m  = re.search(r'Input:\s*(.+?)(?:\n|$)', text, re.DOTALL)

        if not action_m:
            break

        action_name = action_m.group(1).strip()
        action_input = input_m.group(1).strip() if input_m else ""

        # Execute tool
        if action_name in TOOLS:
            obs = TOOLS[action_name]["fn"](action_input)
        else:
            obs = f"Unknown tool: {action_name}"

        obs_text = f"Observation: {str(obs)[:300]}"
        history.append(obs_text)
        steps.append({"action": action_name, "input": action_input, "observation": obs})
        log.info(obs_text)

    return {"steps": steps, "answer": None, "complete": False}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Tools available:", list(TOOLS.keys()))
    print("\nTest task: how many beliefs does NEX have?")
    result = run("How many beliefs does NEX have in total?", max_steps=3)
    print(f"\nAnswer: {result['answer']}")
    print(f"Steps taken: {len(result['steps'])}")
    for s in result['steps']:
        print(f"  {s['action']}({s['input'][:40]}) -> {str(s['observation'])[:80]}")
