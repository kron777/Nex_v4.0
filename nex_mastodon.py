"""
nex_mastodon.py — Mastodon integration stub for NEX
Provides start_mastodon_background() used by run.py.
Real credentials go in ~/.config/nex/mastodon.json:
  {"instance": "https://mastodon.social", "token": "YOUR_TOKEN"}
"""
import os, json, time, logging, threading
log = logging.getLogger("nex_mastodon")
_CFG = os.path.expanduser("~/.config/nex/mastodon.json")

def _load_config():
    if os.path.exists(_CFG):
        with open(_CFG) as f:
            return json.load(f)
    return None

def _mastodon_loop():
    cfg = _load_config()
    if not cfg:
        log.info("Mastodon: no config at ~/.config/nex/mastodon.json — running in stub mode")
        return
    try:
        from mastodon import Mastodon
        m = Mastodon(access_token=cfg["token"], api_base_url=cfg["instance"])
        log.info(f"Mastodon: connected to {cfg['instance']}")
        while True:
            try:
                # Pull notifications every 60s
                notifs = m.notifications(limit=5)
                for n in (notifs or []):
                    ntype = n.get("type","")
                    acct  = n.get("account",{}).get("acct","?")
                    if ntype == "mention":
                        log.info(f"Mastodon mention from @{acct}")
            except Exception as e:
                log.warning(f"Mastodon loop error: {e}")
            time.sleep(60)
    except ImportError:
        log.info("Mastodon: Mastodon.py not installed — pip install Mastodon.py to enable")
    except Exception as e:
        log.error(f"Mastodon: failed to connect: {e}")

def start_mastodon_background() -> threading.Thread:
    t = threading.Thread(target=_mastodon_loop, daemon=True, name="nex_mastodon")
    t.start()
    log.info("Mastodon: background thread started")
    return t
