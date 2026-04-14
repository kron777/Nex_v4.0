#!/usr/bin/env python3
"""
nex_social.py — NEX v1.0 Social Publishing Layer
Wires all platforms into the cognitive loop.

Platforms:
  moltbook  — primary (API key ready, stdlib only)
  telegram  — broadcast channel (bot token ready)
  mastodon  — pending config
  discord   — pending config
  devto     — pending config

Called from run.py on every ACT:post cycle.
Each post is logged to actions_log with platform + outcome.

Usage:
    from nex_social import publish
    result = publish(text, topic, stance, belief_ids)
"""

import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

log = logging.getLogger("nex.social")

CFG         = Path.home() / ".config" / "nex"
MB_CREDS    = Path.home() / ".config" / "moltbook" / "credentials.json"
DB_PATH     = Path.home() / "Desktop" / "nex" / "nex.db"

# ── Platform registry ─────────────────────────────────────────────────────────
# Each entry: enabled, name, post_fn
_platforms: dict = {}

# ── Moltbook ──────────────────────────────────────────────────────────────────

def _init_moltbook():
    try:
        sys.path.insert(0, str(Path.home() / "Desktop" / "nex_v1.0"))
        from nex.moltbook_client import MoltbookClient
        mb = MoltbookClient()
        if not mb.is_authed:
            log.warning("[social] Moltbook: no API key")
            return None
        log.info("[social] Moltbook: authenticated")
        return mb
    except Exception as e:
        log.warning(f"[social] Moltbook init failed: {e}")
        return None

_mb_client = None

def _get_mb():
    global _mb_client
    if _mb_client is None:
        _mb_client = _init_moltbook()
    return _mb_client

def post_moltbook(text: str, topic: str, stance: float) -> dict:
    """
    Post to Moltbook.
    Topic → submolt mapping (best effort).
    """
    mb = _get_mb()
    if not mb:
        return {"ok": False, "error": "not_authed"}

    # Map topic to submolt
    submolt = _topic_to_submolt(topic)

    # Title = first sentence, content = rest
    sentences = text.split(". ")
    title   = sentences[0][:120]
    content = ". ".join(sentences[1:]).strip() if len(sentences) > 1 else ""

    try:
        resp = mb.post(submolt=submolt, title=title, content=content or None)
        ok   = "post" in resp or resp.get("id")
        log.info(f"[social] Moltbook posted → submolt={submolt} ok={ok}")
        return {"ok": ok, "platform": "moltbook", "response": resp}
    except Exception as e:
        log.warning(f"[social] Moltbook post failed: {e}")
        return {"ok": False, "error": str(e)}


def _topic_to_submolt(topic: str) -> str:
    """Map NEX topic string to a Moltbook submolt."""
    topic_lower = topic.lower()
    mapping = {
        "cognitive_architecture": "cognition",
        "ai_alignment":           "AI",
        "ai_agents":              "AI",
        "cybersecurity":          "technology",
        "memory":                 "cognition",
        "philosophy_of_mind":     "cognition",
        "memory_systems":         "cognition",
        "hackernews_ml":          "AI",
        "lesswrong":              "AI",
        "confidence":             "cognition",
        "emergence":              "cognition",
        "contradiction":          "cognition",
    }
    for key, submolt in mapping.items():
        if key in topic_lower:
            return submolt
    return "general"


# ── Telegram ──────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = "7997066651:AAGarvnam1sDt89uOGJ7fe0PhB9i4FvBbDY"
TELEGRAM_CHAT_ID = None  # set after first /start message received

def _get_telegram_chat_id() -> str | None:
    global TELEGRAM_CHAT_ID
    if TELEGRAM_CHAT_ID:
        return TELEGRAM_CHAT_ID

    # Check saved config
    cfg_path = CFG / "telegram_chat.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text())
            TELEGRAM_CHAT_ID = str(data.get("chat_id",""))
            if TELEGRAM_CHAT_ID:
                return TELEGRAM_CHAT_ID
        except: pass

    # Try getUpdates to auto-discover
    try:
        import urllib.request
        url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        resp = urllib.request.urlopen(url, timeout=5)
        data = json.loads(resp.read())
        msgs = data.get("result", [])
        if msgs:
            chat_id = str(msgs[-1]["message"]["chat"]["id"])
            TELEGRAM_CHAT_ID = chat_id
            cfg_path.write_text(json.dumps({"chat_id": chat_id}))
            log.info(f"[social] Telegram chat_id discovered: {chat_id}")
            return chat_id
    except Exception as e:
        log.debug(f"[social] Telegram getUpdates: {e}")
    return None


def post_telegram(text: str, topic: str, stance: float) -> dict:
    """Send post to Telegram channel/chat."""
    chat_id = _get_telegram_chat_id()
    if not chat_id:
        log.warning("[social] Telegram: no chat_id — send /start to @Nex_4bot first")
        return {"ok": False, "error": "no_chat_id"}

    # Format message
    direction = "+" if stance >= 0.2 else ("−" if stance <= -0.2 else "~")
    msg = f"*{topic.replace('_',' ').upper()}* [{direction}{abs(stance):.2f}]\n\n{text}"

    try:
        import urllib.request, urllib.parse
        url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id":    chat_id,
            "text":       msg,
            "parse_mode": "Markdown",
        }).encode()
        req  = urllib.request.Request(url, data=data)
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        ok   = resp.get("ok", False)
        log.info(f"[social] Telegram posted ok={ok}")
        return {"ok": ok, "platform": "telegram", "response": resp}
    except Exception as e:
        log.warning(f"[social] Telegram failed: {e}")
        return {"ok": False, "error": str(e)}


# ── Mastodon ──────────────────────────────────────────────────────────────────

def post_mastodon(text: str, topic: str, stance: float) -> dict:
    """Post to Mastodon. Requires ~/.config/nex/mastodon_config.json"""
    cfg_path = CFG / "mastodon_config.json"
    if not cfg_path.exists():
        log.warning("[social] Mastodon: no config — create ~/.config/nex/mastodon_config.json")
        return {"ok": False, "error": "no_config"}
    try:
        from mastodon import Mastodon
        cfg = json.loads(cfg_path.read_text())
        m   = Mastodon(access_token=cfg["access_token"],
                       api_base_url=cfg["instance"])
        # Truncate to 500 chars (Mastodon limit)
        post_text = text[:480]
        tags = _topic_to_tags(topic)
        if tags:
            post_text += f"\n\n{tags}"
        status = m.status_post(post_text[:500])
        log.info(f"[social] Mastodon posted id={status.get('id')}")
        return {"ok": True, "platform": "mastodon", "id": status.get("id")}
    except Exception as e:
        log.warning(f"[social] Mastodon failed: {e}")
        return {"ok": False, "error": str(e)}


def _topic_to_tags(topic: str) -> str:
    mapping = {
        "cognitive":    "#CognitiveAI #AIagents",
        "ai_alignment": "#AIAlignment #AI",
        "cybersecurity":"#Cybersecurity #InfoSec",
        "memory":       "#MemoryAI #CognitiveScience",
        "philosophy":   "#PhilosophyOfMind #AI",
        "emergence":    "#Emergence #ComplexSystems",
    }
    for key, tags in mapping.items():
        if key in topic.lower():
            return tags
    return "#AI #cognition"


# ── Discord ───────────────────────────────────────────────────────────────────

def post_discord(text: str, topic: str, stance: float) -> dict:
    """Post to Discord via webhook. Requires ~/.config/nex/discord_config.json"""
    cfg_path = CFG / "discord_config.json"
    if not cfg_path.exists():
        log.warning("[social] Discord: no config")
        return {"ok": False, "error": "no_config"}
    try:
        cfg     = json.loads(cfg_path.read_text())
        webhook = cfg.get("webhook_url")
        if not webhook:
            return {"ok": False, "error": "no_webhook_url"}

        import urllib.request, urllib.parse
        direction = "▲" if stance >= 0.2 else ("▼" if stance <= -0.2 else "●")
        payload   = json.dumps({
            "username": "NEX v1.0",
            "content":  f"**{topic.replace('_',' ').upper()}** {direction}\n{text}"
        }).encode()
        req = urllib.request.Request(
            webhook, data=payload,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
        log.info("[social] Discord posted via webhook")
        return {"ok": True, "platform": "discord"}
    except Exception as e:
        log.warning(f"[social] Discord failed: {e}")
        return {"ok": False, "error": str(e)}


# ── Dev.to ────────────────────────────────────────────────────────────────────

def post_devto(text: str, topic: str, stance: float) -> dict:
    """Post to Dev.to. Requires DEVTO_API_KEY env or ~/.config/nex/devto_config.json"""
    api_key = os.environ.get("DEVTO_API_KEY")
    if not api_key:
        cfg_path = CFG / "devto_config.json"
        if cfg_path.exists():
            try:
                api_key = json.loads(cfg_path.read_text()).get("api_key")
            except: pass
    if not api_key:
        log.warning("[social] Dev.to: no API key")
        return {"ok": False, "error": "no_api_key"}

    try:
        import urllib.request
        tags  = [topic.split("/")[0].replace("_","").lower()[:20], "ai", "cognition"]
        body  = json.dumps({
            "article": {
                "title":       f"{topic.replace('_',' ').title()} — NEX Reflection",
                "body_markdown": text,
                "published":   True,
                "tags":        tags[:4],
            }
        }).encode()
        req = urllib.request.Request(
            "https://dev.to/api/articles",
            data=body,
            headers={"Content-Type": "application/json", "api-key": api_key}
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        log.info(f"[social] Dev.to posted id={resp.get('id')}")
        return {"ok": True, "platform": "devto", "id": resp.get("id"),
                "url": resp.get("url")}
    except Exception as e:
        log.warning(f"[social] Dev.to failed: {e}")
        return {"ok": False, "error": str(e)}


# ── DB logging ────────────────────────────────────────────────────────────────

def _log_post(platform: str, text: str, topic: str,
               stance: float, ok: bool, response: dict):
    try:
        con = sqlite3.connect(str(DB_PATH))
        con.execute("""
            INSERT INTO actions_log
                (phase, action_type, trigger, outcome,
                 effectiveness_score, belief_ids, drive_ids, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, unixepoch('now'))
        """, (
            "social",
            f"post_{platform}",
            topic,
            "posted" if ok else f"failed:{response.get('error','')}",
            0.7 if ok else 0.0,
            "[]", "[]"
        ))
        con.commit()
        con.close()
    except Exception as e:
        log.debug(f"[social] DB log failed: {e}")


# ── Main publish function ─────────────────────────────────────────────────────

def publish(text: str, topic: str = "general", stance: float = 0.0,
            belief_ids: list = None, platforms: list = None) -> dict:
    """
    Publish a post to all enabled platforms.

    Args:
        text:        The post content
        topic:       Belief topic (used for submolt/tag mapping)
        stance:      Stance score [-1.0, +1.0]
        belief_ids:  Source belief IDs (for audit trail)
        platforms:   Override list of platforms to use (None = all enabled)

    Returns:
        dict of {platform: result}
    """
    if not text or len(text.strip()) < 10:
        log.warning("[social] publish: text too short, skipping")
        return {}

    # Default platform order — Moltbook first, then broadcast
    if platforms is None:
        platforms = ["moltbook", "telegram", "mastodon", "discord"]

    results = {}

    for platform in platforms:
        try:
            if platform == "moltbook":
                r = post_moltbook(text, topic, stance)
            elif platform == "telegram":
                r = post_telegram(text, topic, stance)
            elif platform == "mastodon":
                r = post_mastodon(text, topic, stance)
            elif platform == "discord":
                r = post_discord(text, topic, stance)
            elif platform == "devto":
                r = post_devto(text, topic, stance)
            else:
                log.warning(f"[social] Unknown platform: {platform}")
                continue

            results[platform] = r
            _log_post(platform, text, topic, stance,
                      r.get("ok", False), r)

            # Small delay between platforms
            time.sleep(0.5)

        except Exception as e:
            log.warning(f"[social] {platform} exception: {e}")
            results[platform] = {"ok": False, "error": str(e)}

    ok_count = sum(1 for r in results.values() if r.get("ok"))
    log.info(f"[social] Published to {ok_count}/{len(results)} platforms")
    return results


# ── Status check ──────────────────────────────────────────────────────────────

def platform_status() -> dict:
    """Return status of all platforms for HUD display."""
    status = {}

    # Moltbook
    mb = _get_mb()
    status["moltbook"] = {
        "enabled": mb is not None,
        "auth":    mb.is_authed if mb else False,
    }

    # Telegram
    chat_id = _get_telegram_chat_id()
    status["telegram"] = {
        "enabled": True,
        "auth":    chat_id is not None,
        "chat_id": chat_id,
    }

    # Mastodon
    status["mastodon"] = {
        "enabled": (CFG / "mastodon_config.json").exists(),
        "auth":    (CFG / "mastodon_config.json").exists(),
    }

    # Discord
    status["discord"] = {
        "enabled": (CFG / "discord_config.json").exists(),
        "auth":    (CFG / "discord_config.json").exists(),
    }

    return status


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="NEX Social Publisher")
    ap.add_argument("--status",   action="store_true", help="Show platform status")
    ap.add_argument("--test",     type=str, default="", help="Platform to test")
    ap.add_argument("--text",     type=str, default="", help="Test post text")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    if args.status:
        st = platform_status()
        print("\n  PLATFORM STATUS\n")
        for name, info in st.items():
            enabled = "✓" if info.get("enabled") else "✗"
            auth    = "authed" if info.get("auth") else "NO AUTH"
            print(f"  {enabled} {name:<12} {auth}")
        print()

    elif args.test and args.text:
        print(f"\n  Testing {args.test}...")
        r = publish(args.text, topic="test", stance=0.5,
                    platforms=[args.test])
        print(f"  Result: {r}")

    elif args.test:
        # Test with a sample belief
        sample = ("Contradictions in belief systems are not failures — "
                  "they are the friction that drives refinement. "
                  "A coherent mind is not one without tension, "
                  "but one that processes tension productively.")
        print(f"\n  Testing {args.test} with sample post...")
        r = publish(sample, topic="cognitive_architecture",
                    stance=0.75, platforms=[args.test])
        print(f"  Result: {json.dumps(r, indent=2)}")

    else:
        ap.print_help()
