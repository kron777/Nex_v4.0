import os, sys

LOCK_FILE = "/tmp/nex_telegram.lock"

def _is_telegram_process(pid):
    try:
        cmd = open(f"/proc/{pid}/cmdline").read()
        return "nex_telegram" in cmd
    except:
        return False

def enforce_singleton():
    my_pid = os.getpid()
    if os.path.exists(LOCK_FILE):
        try:
            old_pid = int(open(LOCK_FILE).read().strip())
            if old_pid != my_pid:
                if _is_telegram_process(old_pid):
                    print(f"  [singleton] live Telegram already running (pid={old_pid}) — exiting")
                    sys.exit(0)
                else:
                    # Stale lock — delete it and continue
                    print(f"  [singleton] stale lock (pid={old_pid}) — clearing and continuing")
                    os.remove(LOCK_FILE)
        except Exception as e:
            print(f"  [singleton] lock error ({e}) — clearing")
            try:
                os.remove(LOCK_FILE)
            except:
                pass
    # Write our PID
    with open(LOCK_FILE, "w") as f:
        f.write(str(my_pid))
    print(f"  [singleton] lock acquired (pid={my_pid})")
