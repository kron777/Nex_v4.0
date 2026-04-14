#!/usr/bin/env python3
"""
nex_telegram_clean.py — NEX Telegram bridge (raw HTTP polling, no PTB conflicts)
"""
import os, sys, time, re, logging, requests, json, threading
sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))
logging.basicConfig(level=logging.ERROR)

# Token
_src = open(os.path.expanduser("~/Desktop/nex/nex_telegram.py")).read()
_m = re.search(r'[0-9]{8,10}:[A-Za-z0-9_-]{35}', _src)
BOT_TOKEN = "7997066651:AAFM3a3IujcnwzGQk1lpMJj1JctH2d0JBGw"
assert BOT_TOKEN, "No token found"
try:
    from nex_telegram_commands import OWNER_TELEGRAM_ID
except Exception:
    OWNER_TELEGRAM_ID = 5217790760
BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
NEX_API_KEY = "nex-72ea474306ea0d1dfbefeda3"
print(f"[NEX-TG] Token: {BOT_TOKEN[:12]}...")

def api(method, **kwargs):
    try:
        r = requests.post(f"{BASE}/{method}", json=kwargs, timeout=35)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send(chat_id, text):
    api("sendMessage", chat_id=chat_id, text=str(text)[:4096])
    # ── Log full reply for HUD ───────────────────────────────────────
    try:
        import json as _json, time as _time
        _log = "/tmp/nex_replies.jsonl"
        with open(_log, "a") as _f:
            _f.write(_json.dumps({
                "ts":   __import__('datetime').datetime.now().strftime("%H:%M:%S"),
                "type": "REPLIED",
                "text": str(text)
            }) + "\n")
        # Keep last 50 lines only
        with open(_log) as _f: _lines = _f.readlines()
        if len(_lines) > 50:
            with open(_log, "w") as _f: _f.writelines(_lines[-50:])
    except: pass
    # ─────────────────────────────────────────────────────────────────

def handle(text, chat_id, user_id):
    cmd = text.split()[0].split("@")[0] if text.startswith("/") else None
    if cmd == "/start":
        send(chat_id, "NEX v1.2 online.\n/status /beliefs /help")
    elif cmd == "/help":
        send(chat_id, "/status\n/beliefs\n/mood")
    elif cmd == "/status":
        try:
            d = requests.get("http://localhost:7823/api/version", timeout=3).json()
            send(chat_id, f"Beliefs: {d.get('beliefs','?')}  Status: {d.get('status','?')}")
        except Exception:
            send(chat_id, "API unreachable")
    elif cmd == "/beliefs":
        try:
            import sqlite3
            con = sqlite3.connect(os.path.expanduser("~/.config/nex/nex.db"), timeout=3)
            n = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
            con.close()
            send(chat_id, f"Active beliefs: {n:,}")
        except Exception as e:
            send(chat_id, f"DB error: {e}")
    elif cmd == "/restart" and user_id == OWNER_TELEGRAM_ID:
        send(chat_id, "Restarting...")
        threading.Thread(target=lambda: os.system("nex &"), daemon=True).start()
    elif cmd == "/thrownet" and user_id == OWNER_TELEGRAM_ID:
        args = text[len("/thrownet"):].strip()
        if not args:
            send(chat_id, "Usage: /thrownet <constraint description>")
        else:
            send(chat_id, f"🧠 Throw-Net running...")
            try:
                import sys; sys.path.insert(0, '/home/rr/Desktop/nex/nex')
                from nex_throw_net import handle_thrownet_command
                send(chat_id, handle_thrownet_command(args)[:4000])
            except Exception as e:
                send(chat_id, f"Throw-Net error: {e}")
    elif cmd == "/tn_sessions" and user_id == OWNER_TELEGRAM_ID:
        try:
            import sys; sys.path.insert(0, '/home/rr/Desktop/nex/nex')
            from nex_throw_net import handle_sessions_command
            send(chat_id, handle_sessions_command(limit=5)[:4000])
        except Exception as e:
            send(chat_id, f"Sessions error: {e}")
    elif cmd == "/approve_tn" and user_id == OWNER_TELEGRAM_ID:
        args = text[len("/approve_tn"):].strip()
        if not args:
            send(chat_id, "Usage: /approve_tn <session_id>")
        else:
            try:
                import sys; sys.path.insert(0, '/home/rr/Desktop/nex/nex')
                from nex_throw_net import handle_approve_command
                send(chat_id, handle_approve_command(int(args))[:2000])
            except Exception as e:
                send(chat_id, f"Approve error: {e}")
    elif cmd == "/refine_tn" and user_id == OWNER_TELEGRAM_ID:
        args = text[len("/refine_tn"):].strip()
        if not args:
            send(chat_id, "Usage: /refine_tn <session_id>")
        else:
            send(chat_id, "🔬 Refining...")
            try:
                import sys; sys.path.insert(0, '/home/rr/Desktop/nex/nex')
                from nex_refinement_engine import handle_refine_command
                send(chat_id, handle_refine_command(args)[:4000])
            except Exception as e:
                send(chat_id, f"Refine error: {e}")
    elif cmd == "/auto_refine" and user_id == OWNER_TELEGRAM_ID:
        try:
            import sys; sys.path.insert(0, '/home/rr/Desktop/nex/nex')
            from nex_refinement_engine import handle_auto_refine_command
            send(chat_id, handle_auto_refine_command()[:2000])
        except Exception as e:
            send(chat_id, f"Auto-refine error: {e}")
    else:
        try:
            r = requests.post("http://localhost:7823/api/chat",
                json={"query": text, "user": str(chat_id)},
                headers={"X-API-Key": NEX_API_KEY}, timeout=30)
            reply = r.json().get("reply") or r.json().get("response", "")
            if reply:
                send(chat_id, reply)
        except Exception:
            try:
                from nex.nex_soul_loop import SoulLoop
                send(chat_id, SoulLoop().respond(text))
            except Exception:
                pass

def main():
    print("[NEX-TG] Starting raw HTTP polling...")
    # Close any existing server session
    try:
        requests.post(f"{BASE}/getUpdates", json={"timeout": 0, "offset": -1}, timeout=5)
    except Exception:
        pass
    requests.get(f"{BASE}/deleteWebhook?drop_pending_updates=true", timeout=10)
    time.sleep(3)
    print("[NEX-TG] ONLINE")
    offset = 0
    while True:
        try:
            r = requests.post(f"{BASE}/getUpdates",
                json={"timeout": 10, "offset": offset, "allowed_updates": ["message"]},
                timeout=20)
            data = r.json()
            if not data.get("ok"):
                err = data.get("description", "")
                if "Conflict" in err:
                    print(f"[NEX-TG] Conflict — waiting 15s then forcing clear...")
                    time.sleep(15)
                    requests.post(f"{BASE}/getUpdates", json={"timeout": 0, "offset": -1}, timeout=5)
                    time.sleep(3)
                else:
                    print(f"[NEX-TG] Error: {err}")
                    time.sleep(2)
                continue
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "")
                chat_id = msg.get("chat", {}).get("id")
                user_id = msg.get("from", {}).get("id")
                if text and chat_id:
                    threading.Thread(target=handle, args=(text, chat_id, user_id), daemon=True).start()
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            print(f"[NEX-TG] Poll error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
