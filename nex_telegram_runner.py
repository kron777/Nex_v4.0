#!/usr/bin/env python3
"""
nex_telegram_runner.py — Clean standalone Telegram bridge for NEX
Replaces the broken nex_telegram.py launch chain.
Run via: python3 nex_telegram_runner.py
"""
import sys, os, time, asyncio, signal, requests, logging
sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))

logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# ── Load token ────────────────────────────────────────────────────────────────
try:
    from nex_telegram import BOT_TOKEN
except Exception:
    import re
    src = open(os.path.expanduser("~/Desktop/nex/nex_telegram.py")).read()
    m = re.search(r'[0-9]{8,10}:[A-Za-z0-9_-]{35}', src)
    BOT_TOKEN = m.group(0) if m else None

if not BOT_TOKEN:
    print("[runner] ERROR: Could not find BOT_TOKEN")
    sys.exit(1)

print(f"[runner] Token loaded: {BOT_TOKEN[:10]}...")

# ── Step 1: Delete any webhook ────────────────────────────────────────────────
def clear_webhook():
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
            "?drop_pending_updates=true",
            timeout=10
        )
        print(f"[runner] Webhook cleared: {r.json().get('description','ok')}")
    except Exception as e:
        print(f"[runner] Webhook clear failed: {e}")

# ── Step 2: Kill any other bot instances ──────────────────────────────────────
def kill_other_instances():
    import subprocess
    mypid = os.getpid()
    result = subprocess.run(
        ["pgrep", "-f", "nex_telegram"],
        capture_output=True, text=True
    )
    for pid_str in result.stdout.strip().split("\n"):
        try:
            pid = int(pid_str.strip())
            if pid != mypid:
                # Verify it's actually a telegram process
                with open(f"/proc/{pid}/cmdline") as f:
                    cmd = f.read()
                if "telegram" in cmd.lower():
                    os.kill(pid, signal.SIGKILL)
                    print(f"[runner] Killed old instance PID {pid}")
        except Exception:
            pass

# ── Step 3: Wait for Telegram servers to drop old session ────────────────────
def wait_for_clear(seconds=5):
    print(f"[runner] Waiting {seconds}s for old sessions to expire...")
    time.sleep(seconds)

# ── Step 4: Import and run the actual bot ────────────────────────────────────
def run_bot():
    print("[runner] Importing nex_telegram bot...")
    import nex_telegram
    # Run the main bot function directly
    nex_telegram.main()

# ── Main loop with restart on crash ──────────────────────────────────────────
def main():
    print("[runner] NEX Telegram Runner starting...")
    clear_webhook()
    kill_other_instances()
    wait_for_clear(5)

    attempt = 0
    while True:
        attempt += 1
        try:
            print(f"[runner] Starting bot (attempt {attempt})...")
            run_bot()
            print("[runner] Bot exited cleanly")
        except Exception as e:
            err = str(e)
            if "Conflict" in err:
                print(f"[runner] Conflict detected — clearing webhook and waiting 20s...")
                clear_webhook()
                time.sleep(20)
            else:
                print(f"[runner] Error: {e}")
                backoff = min(5 * attempt, 60)
                print(f"[runner] Retrying in {backoff}s...")
                time.sleep(backoff)

if __name__ == "__main__":
    main()
