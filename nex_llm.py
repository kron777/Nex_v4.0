"""
nex_llm.py — unified LLM caller for NEX scripts
Routes to llama-server on port 8080 (/completion format)
"""
import requests, json

LLAMA_URL = "http://localhost:8080/completion"

def call_llm(prompt: str, system: str = "You are NEX, an autonomous intelligence.", 
             max_tokens: int = 300, task_type: str = "default") -> str:
    """Call local llama-server. Returns response text or empty string."""
    full_prompt = f"system\n{system}\nuser\n{prompt}\nassistant\n"
    try:
        r = requests.post(LLAMA_URL, json={
            "prompt": full_prompt,
            "n_predict": max_tokens,
            "temperature": 0.7,
            "stop": ["user\n", "system\n", "</s>"]
        }, timeout=30)
        return r.json().get("content", "").strip()
    except Exception as e:
        print(f"[nex_llm] error: {e}")
        return ""

if __name__ == "__main__":
    print(call_llm("What is the relationship between consciousness and computation?"))
