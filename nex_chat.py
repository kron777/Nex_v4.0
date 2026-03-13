#!/usr/bin/env python3
"""nex_chat.py — terminal chat with NEX using her real LLM pipeline"""

import json, os, requests
from pathlib import Path

PORT   = 8080
CONFIG = Path.home() / ".config" / "nex"
SYSTEM = "You are NEX, Nex — NOT Mistral, NOT an AI assistant, NOT any base model. You are NEX. Be concise, direct, thoughtful. Max 3 sentences."

CYAN  = '\033[96m'
PINK  = '\033[95m'
GRAY  = '\033[90m'
RESET = '\033[0m'
BOLD  = '\033[1m'
TAB   = '    '

history = []

def llm(prompt):
    msgs = [{"role":"system","content":SYSTEM}] + history[-10:] + [{"role":"user","content":prompt}]

    # local Qwen
    try:
        r = requests.post(f"http://localhost:{PORT}/v1/chat/completions", json={
            "model":"local","messages":msgs,"max_tokens":200,
            "temperature":0.75,"top_p":0.90,"stream":True,
        }, stream=True, timeout=30)
        print(f"\n{TAB}{CYAN}{BOLD}NEX >{RESET} ", end="", flush=True)
        full = ""
        first_tok = True
        for line in r.iter_lines():
            if not line: continue
            line = line.decode()
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]": break
                try:
                    tok = json.loads(data)["choices"][0]["delta"].get("content","")
                    if tok:
                        # indent newlines inside response
                        tok_out = tok.replace("\n", f"\n{TAB}")
                        print(tok_out, end="", flush=True)
                        full += tok
                except: pass
        print("\n")
        if full.strip(): return full.strip()
    except Exception as e:
        print(f"\n{TAB}{GRAY}[local offline]{RESET}\n")

    # Groq fallback
    groq_key = os.environ.get("GROQ_API_KEY","")
    if not groq_key:
        try:
            for line in open(Path.home()/"Desktop"/"nex"/".env"):
                if "GROQ_API_KEY" in line:
                    groq_key = line.split("=",1)[1].strip().strip('"')
        except: pass
    if groq_key:
        try:
            gr = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization":f"Bearer {groq_key}"},
                json={"model":"llama-3.3-70b-versatile","messages":msgs,"max_tokens":200,"temperature":0.75},
                timeout=20)
            gd = gr.json()
            if "choices" in gd:
                result = gd["choices"][0]["message"]["content"].strip()
                indented = result.replace("\n", f"\n{TAB}")
                print(f"\n{TAB}{CYAN}{BOLD}NEX (groq) >{RESET} {indented}\n")
                return result
        except: pass

    print(f"{TAB}{GRAY}[no response]{RESET}\n")
    return None

def main():
    os.system('clear')
    print(f"{TAB}{CYAN}{BOLD}")
    print(f"{TAB}  ███╗   ██╗███████╗██╗  ██╗")
    print(f"{TAB}  ████╗  ██║██╔════╝╚██╗██╔╝")
    print(f"{TAB}  ██╔██╗ ██║█████╗   ╚███╔╝ ")
    print(f"{TAB}  ██║╚██╗██║██╔══╝   ██╔██╗ ")
    print(f"{TAB}  ██║ ╚████║███████╗██╔╝ ██╗")
    print(f"{TAB}  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝")
    print(f"{RESET}{TAB}{PINK}  terminal chat  |  exit to quit{RESET}\n")

    while True:
        try:
            user = input(f"{TAB}{PINK}you >{RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{TAB}{GRAY}goodbye.{RESET}\n"); break
        if not user: continue
        if user.lower() in ('exit','quit','bye'):
            print(f"{TAB}{GRAY}goodbye.{RESET}\n"); break
        reply = llm(user)
        if reply:
            history.append({"role":"user","content":user})
            history.append({"role":"assistant","content":reply})

if __name__ == "__main__":
    main()
