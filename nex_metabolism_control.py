#!/usr/bin/env python3
"""
nex_metabolism_control.py — NEX GPU Load Controller v2.1
Usage:
  python3 nex_metabolism_control.py --set -3   # hibernation
  python3 nex_metabolism_control.py --set 1    # eco
  python3 nex_metabolism_control.py --set 2    # balanced
  python3 nex_metabolism_control.py --status
"""

import json, sys, os, requests
from pathlib import Path

CONFIG_PATH  = Path("~/.config/nex/metabolism.json").expanduser()
SCHED_URL    = "http://localhost:7825"
ADMIN_SECRET = os.environ.get("NEX_ADMIN_SECRET", "nex-admin-2026")

PROFILES = {
    -3: {"name":"HIBERNATION","emoji":"💤","description":"Almost asleep. LLM suspended. Perfect for overnight.","gpu_target":"~5%","llm_suspended":True,"intervals":{"rss":240,"hn_reddit":480,"wikipedia":720,"arxiv":1440,"youtube":1440,"crawl4ai":1440},"llm_calls_per_min":0,"rest_between_cycles":600,"posts_per_absorb":0,"posting":False,"replying":False,"chatting":False,"saturation":{"enabled":False,"start_hour":3,"end_hour":4,"target_per_domain":50}},
    -2: {"name":"SLEEP","emoji":"🌙","description":"Very slow. Keeps beliefs warm. No posting.","gpu_target":"~10%","llm_suspended":False,"intervals":{"rss":120,"hn_reddit":240,"wikipedia":360,"arxiv":720,"youtube":1440,"crawl4ai":1440},"llm_calls_per_min":1,"rest_between_cycles":300,"posts_per_absorb":2,"posting":False,"replying":False,"chatting":False,"saturation":{"enabled":True,"start_hour":2,"end_hour":4,"target_per_domain":50}},
    -1: {"name":"IDLE","emoji":"😴","description":"Low activity. Replies only if directly mentioned.","gpu_target":"~15%","llm_suspended":False,"intervals":{"rss":60,"hn_reddit":120,"wikipedia":180,"arxiv":480,"youtube":1440,"crawl4ai":720},"llm_calls_per_min":1,"rest_between_cycles":180,"posts_per_absorb":3,"posting":False,"replying":True,"chatting":False,"saturation":{"enabled":True,"start_hour":2,"end_hour":5,"target_per_domain":75}},
    0:  {"name":"MINIMAL","emoji":"🔅","description":"Just responsive. Replies but no proactive posting.","gpu_target":"~20%","llm_suspended":False,"intervals":{"rss":45,"hn_reddit":90,"wikipedia":120,"arxiv":360,"youtube":720,"crawl4ai":480},"llm_calls_per_min":2,"rest_between_cycles":120,"posts_per_absorb":4,"posting":False,"replying":True,"chatting":True,"saturation":{"enabled":True,"start_hour":2,"end_hour":5,"target_per_domain":100}},
    1:  {"name":"ECO","emoji":"🌿","description":"Low GPU use. Slow absorb, long rests. Full function.","gpu_target":"~30%","llm_suspended":False,"intervals":{"rss":30,"hn_reddit":60,"wikipedia":120,"arxiv":480,"youtube":720,"crawl4ai":720},"llm_calls_per_min":2,"rest_between_cycles":120,"posts_per_absorb":4,"posting":True,"replying":True,"chatting":True,"saturation":{"enabled":True,"start_hour":3,"end_hour":5,"target_per_domain":100}},
    2:  {"name":"BALANCED","emoji":"⚖️","description":"Steady rhythm. Healthy learning without overloading GPU.","gpu_target":"~55%","llm_suspended":False,"intervals":{"rss":15,"hn_reddit":30,"wikipedia":60,"arxiv":240,"youtube":720,"crawl4ai":360},"llm_calls_per_min":5,"rest_between_cycles":60,"posts_per_absorb":8,"posting":True,"replying":True,"chatting":True,"saturation":{"enabled":True,"start_hour":2,"end_hour":6,"target_per_domain":200}},
    3:  {"name":"BEAST","emoji":"🔥","description":"Maximum learning speed. High GPU. Short bursts only.","gpu_target":"~85%","llm_suspended":False,"intervals":{"rss":8,"hn_reddit":15,"wikipedia":30,"arxiv":120,"youtube":180,"crawl4ai":240},"llm_calls_per_min":10,"rest_between_cycles":10,"posts_per_absorb":15,"posting":True,"replying":True,"chatting":True,"saturation":{"enabled":True,"start_hour":0,"end_hour":23,"target_per_domain":500}},
}

VALID = list(PROFILES.keys())
G="\033[92m"; Y="\033[93m"; R="\033[91m"; C="\033[96m"; B="\033[1m"; D="\033[2m"; X="\033[0m"

def banner():
    print(C+B+"""
╔══════════════════════════════════════════════╗
║      NEX METABOLISM CONTROL v2.1            ║
║    -3=Hibernate  0=Minimal  +3=Beast        ║
╚══════════════════════════════════════════════╝"""+X+"\n")

def load_current():
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text())
    except: pass
    return {"level": 2, "name": "BALANCED"}

def save_config(level):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    p = PROFILES[level]
    suspended = p.get("llm_suspended", False)
    CONFIG_PATH.write_text(json.dumps({
        "level": level, "name": p["name"],
        "set_at": __import__("datetime").datetime.now().isoformat(),
        "set_via": "terminal",
        "intervals": p["intervals"],
        "llm_calls_per_min": p["llm_calls_per_min"],
        "llm_suspended": suspended,
        "posting": p.get("posting", True),
        "replying": p.get("replying", True),
        "chatting": p.get("chatting", True),
    }, indent=2))

def push_scheduler(level):
    p = PROFILES[level]
    try:
        r = requests.post(SCHED_URL+"/scheduler/config",
            json={"saturation": p["saturation"]},
            headers={"X-Admin-Secret": ADMIN_SECRET, "Content-Type": "application/json"},
            timeout=5)
        return (True, "Scheduler updated") if r.status_code==200 else (False, "Scheduler "+str(r.status_code))
    except Exception as e:
        return False, "Scheduler offline"

def fmt_intervals(level):
    lines = []
    for n, m in PROFILES[level]["intervals"].items():
        d = str(m//60)+"h" if m >= 60 else str(m)+"m"
        lines.append("  "+n.ljust(14)+" every "+d)
    return "\n".join(lines)

def llm_label(p):
    if p.get("llm_suspended"):
        return "SUSPENDED"
    return "max "+str(p["llm_calls_per_min"])+"/min"

def apply_metabolism(level):
    p = PROFILES[level]
    print("\n"+C+"Applying "+p["emoji"]+" "+B+p["name"]+X+C+" (Level "+str(level)+")..."+X+"\n")
    save_config(level)
    print("  "+G+"✅"+X+" Config saved")
    ok, msg = push_scheduler(level)
    print("  "+(G if ok else Y)+("✅" if ok else "⚠️ ")+X+" "+msg)
    print("  "+G+"✅"+X+" Source router applies next cycle (~60s)")
    print("\n"+G+B+p["emoji"]+" "+p["name"]+" set"+X)
    print("GPU: "+p["gpu_target"]+" | LLM: "+llm_label(p))
    print("Posting: "+("ON" if p.get("posting") else "OFF")+" | Replying: "+("ON" if p.get("replying") else "OFF"))
    print("\n"+B+"Intervals:"+X+"\n"+fmt_intervals(level)+"\n")

def show_status():
    current = load_current()
    level = current.get("level", 2)
    p = PROFILES[level]
    print("\n"+B+"Current:"+X+" "+p["emoji"]+" "+B+p["name"]+X+" (Level "+str(level)+")")
    print(D+p["description"]+X)
    print("GPU: "+p["gpu_target"]+" | LLM: "+llm_label(p))
    print("Posting: "+("🟢" if p.get("posting") else "🔴")+" | Replying: "+("🟢" if p.get("replying") else "🔴"))
    print("\n"+B+"Intervals:"+X+"\n"+fmt_intervals(level))
    try:
        r = requests.get(SCHED_URL+"/scheduler/status", timeout=3)
        b = r.json().get("total_beliefs","?") if r.status_code==200 else "?"
        print("\n"+G+"✅ Scheduler online"+X+" — "+str(b)+" beliefs")
    except: print("\n"+R+"❌ Scheduler offline"+X)
    try:
        r = requests.get("http://localhost:8080/health", timeout=3)
        print(G+"✅ LLM online"+X if r.status_code==200 else Y+"⚠️ LLM "+str(r.status_code)+X)
    except: print(R+"❌ LLM offline"+X)

def show_menu():
    current = load_current()
    cur = current.get("level", 2)
    print("Current: "+PROFILES[cur]["emoji"]+" "+B+PROFILES[cur]["name"]+X+" (Level "+str(cur)+")\n")
    for level in sorted(PROFILES.keys()):
        p = PROFILES[level]
        marker = G+"◀ ACTIVE"+X if level==cur else ""
        susp = " "+R+"[LLM OFF]"+X if p.get("llm_suspended") else ""
        print("  "+B+str(level).rjust(3)+X+") "+p["emoji"]+"  "+B+p["name"].ljust(14)+X+"  GPU:"+p["gpu_target"].ljust(8)+"  "+D+p["description"][:45]+X+susp+" "+marker)
    print("\n  "+B+"s"+X+") Status    "+B+"q"+X+") Quit\n")

def main():
    banner()
    args = sys.argv[1:]
    if "--status" in args:
        show_status(); return
    if "--set" in args:
        idx = args.index("--set")
        if idx+1 < len(args):
            try:
                level = int(args[idx+1])
                if level not in VALID:
                    print(R+"Invalid. Use -3 to 3."+X); sys.exit(1)
                apply_metabolism(level); return
            except ValueError:
                print(R+"Invalid. Use -3 to 3."+X); sys.exit(1)
    while True:
        show_menu()
        choice = input("Choose (-3/-2/-1/0/1/2/3/s/q): ").strip().lower()
        if choice == "q":
            print("Bye!"); break
        elif choice == "s":
            show_status(); print()
        elif choice in ("-3","-2","-1","0","1","2","3"):
            apply_metabolism(int(choice))
            input(D+"Press Enter to continue..."+X); print()
        else:
            print(Y+"Invalid. Use -3 to 3, s or q."+X+"\n")

if __name__ == "__main__":
    main()
