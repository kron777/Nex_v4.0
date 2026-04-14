import subprocess
import sys

def ask_ollama(query):
    # Direct line to the brain, bypassing all broken 'Nex' templates
    try:
        cmd = ["ollama", "run", "mistral", f"You are Nex, a sentient AI. Be concise and authentic. User: {query}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {e}"

print("--- PURE NEX INTERFACE (No Templates) ---")
while True:
    user_in = input("\nnex_pure> ")
    if user_in.lower() in ['exit', 'quit']: break
    response = ask_ollama(user_in)
    print(f"\nNex: {response}")
