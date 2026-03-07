import time
import random
from datetime import datetime

CYAN = "\033[96m"
MAG  = "\033[95m"
GRN  = "\033[92m"
YEL  = "\033[93m"
BLU  = "\033[94m"
GRAY = "\033[90m"
RST  = "\033[0m"

def banner():

    print(CYAN)
    print("AUTO LEARN")
    print("Neural Ingestion Protocol // cyberlearn v2.0")
    print("Moltbook × Belief Field × Agent Conversations")
    print(RST)

    print("status:",GRN+"■ ONLINE"+RST,"   agent: nex_v4")
    print("mode:",MAG+"AUTO-LEARN"+RST," kill:",YEL+"Ctrl+C"+RST)
    print()

def system_block():

    print(GRAY+"[SYS] Neural link → moltbook.com"+RST)
    print(GRAY+"[SYS] API key: moltbook_sk_****"+RST)
    print(GRAY+"[DISK] Restored 21 beliefs"+RST)
    print(GRAY+"[SYS] Interval: 60s  Chat: ON  Persistence: ON"+RST)
    print()

def emit():

    ops = [
        ("NET", BLU, "Cycle"),
        ("PULL", CYAN, "20 posts"),
        ("PROC", YEL, "pattern extraction"),
        ("LEARN", GRN, "belief synthesized"),
        ("DISK", MAG, "beliefs saved"),
    ]

    op = random.choice(ops)
    ts = datetime.now().strftime("%H:%M:%S")

    print(GRAY+"["+ts+"]"+RST, op[1]+op[0]+RST, op[2])

def main():

    banner()
    system_block()

    print(CYAN+"— LIVE FEED"+RST)

    while True:
        emit()
        time.sleep(1)

if __name__ == "__main__":
    main()
