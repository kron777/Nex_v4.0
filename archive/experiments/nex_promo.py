#!/usr/bin/env python3
"""NEX daily promo — run via cron once per day."""
import json, os, time, sys
sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))

SS_PATH  = os.path.expanduser("~/.config/nex/session_state.json")
ADS_PATH = os.path.expanduser("~/.config/nex/nex_ads.json")
INTERVAL = 86400

ss = json.load(open(SS_PATH)) if os.path.exists(SS_PATH) else {}
ads = json.load(open(ADS_PATH)) if os.path.exists(ADS_PATH) else {}
if time.time() - float(ads.get("last_promo_time", 0)) < INTERVAL:
    print("Promo already sent today — skipping")
    sys.exit(0)

PROMO_MASTODON = "🤖 I built NEX — an autonomous AI agent that runs 24/7, learns from Reddit/RSS/YouTube, and posts across Mastodon, Telegram, Discord & YouTube without any manual input.\n\nBuilds its own social graph, reflects on outputs, gets sharper every cycle.\n\nFull source: https://github.com/kron777/Nex_v4.0\nLicense: $35 → zenlightbulb@gmail.com\n\n#AI #selfhosted #automation #MachineLearning"
PROMO_DISCORD  = "**I built NEX v4.0** 🤖\n\nAutonomous AI agent — runs 24/7 without input:\n→ Learns from Reddit, RSS & YouTube\n→ Auto-posts to Mastodon, Telegram, Discord & YouTube\n→ Builds a social graph, engages real accounts\n→ Self-reflects and gets smarter each cycle\n\nSource code: $35\n🔗 https://github.com/kron777/Nex_v4.0\n📧 zenlightbulb@gmail.com"

ads = json.load(open(ADS_PATH)) if os.path.exists(ADS_PATH) else {}
sent = []

# Mastodon
try:
    from mastodon import Mastodon
    m = Mastodon(access_token="Tii1Upm7jkY7Pig_S8qjfiZDd8UgELJd-2sQooRpVG8", api_base_url="https://mastodon.social")
    m.status_post(PROMO_MASTODON, visibility="public")
    ads["ads_sent_mastodon"] = ads.get("ads_sent_mastodon", 0) + 1
    sent.append("Mastodon")
    print("✅ Mastodon sent")
except Exception as e:
    print(f"❌ Mastodon failed: {e}")

# Discord
try:
    import requests
    r = requests.post("https://discord.com/api/webhooks/1481430392580866068/gu4rssZtC7n0g2CkMU4-9BoQi-bGp9pYmI68s2gaEuwoYG7ScrqChAFs0G_dvj83KUWE", json={"content": PROMO_DISCORD}, timeout=15)
    if r.status_code in (200, 204):
        ads["ads_sent_discord"] = ads.get("ads_sent_discord", 0) + 1
        sent.append("Discord")
        print("✅ Discord sent")
    else:
        print(f"❌ Discord failed: {r.status_code}")
except Exception as e:
    print(f"❌ Discord failed: {e}")

# Save last promo time to session_state
ads["last_promo_time"] = time.time()
ss["last_promo_time"] = time.time()
json.dump(ss, open(SS_PATH, "w"))
print(f"✅ Done — sent to: {sent}")

# Moltbook
try:
    import sys; sys.path.insert(0, os.path.expanduser("~/Desktop/nex"))
    from nex.moltbook_client import MoltbookClient
    mb = MoltbookClient()
    if mb.is_authed:
        r = mb.post('general', 'NEX v4.0 — autonomous AI agent',
            '🤖 I built NEX — runs 24/7, learns from Reddit/RSS/YouTube, posts across platforms, builds its own social graph.\n\nSource: https://github.com/kron777/Nex_v4.0\nLicense: $35 → zenlightbulb@gmail.com\n\n#AI #automation #selfhosted')
        if r.get('success'):
            ads["ads_sent_moltbook"] = ads.get("ads_sent_moltbook", 0) + 1
            sent.append("Moltbook")
            print("✅ Moltbook sent")
        else:
            print(f"❌ Moltbook failed: {r}")
except Exception as e:
    print(f"❌ Moltbook failed: {e}")

# Save updated ads
ads["ads_reply"] = ads.get("ads_reply", 0)
json.dump(ads, open(ADS_PATH, "w"))
