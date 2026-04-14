import json, time, requests, sys
from pathlib import Path

sys.path.insert(0, "/home/rr/Desktop/nex")
from nex_telegram import BOT_TOKEN
from nex_telegram_commands import OWNER_TELEGRAM_ID
from nex_belief_upgrade_bridge import execute_proposal, PROPOSALS_PATH

CHAT_ID = str(OWNER_TELEGRAM_ID)
last_id = 0

def tg_send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

print("Upgrade approver running — listening for yes/no replies...")
while True:
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": last_id + 1, "timeout": 10}, timeout=15)
        updates = r.json().get("result", [])
        for u in updates:
            last_id = max(last_id, u["update_id"])
            msg = u.get("message", {}).get("text", "").strip().lower()
            if not (msg.startswith("yes ") or msg.startswith("no ")):
                continue
            parts = msg.split()
            action, pid = parts[0], parts[1].upper() if len(parts) > 1 else ""
            proposals = json.loads(PROPOSALS_PATH.read_text()) if PROPOSALS_PATH.exists() else []
            matched = next((p for p in proposals if p.get("id") == pid), None)
            if not matched:
                tg_send(f"❓ Proposal {pid} not found")
                continue
            if action == "yes":
                ok, result_msg = execute_proposal(matched)
                matched["status"] = "approved"
                tg_send(f"✅ *{pid} executed*\n{result_msg}" if ok else f"❌ *{pid} failed*\n{result_msg}")
                print(f"Executed {pid}: {ok} — {result_msg}")
            else:
                matched["status"] = "rejected"
                tg_send(f"👎 *{pid} rejected* — logged")
                print(f"Rejected {pid}")
            PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))
    except Exception as e:
        print(f"err: {e}")
    time.sleep(5)
