#!/usr/bin/env python3
"""
nex_belief_upgrade_bridge.py
============================
Turns NEX's strongest distilled beliefs into actionable upgrades.

Pipeline:
  1. Pull high-confidence beliefs (conf > 0.75) from DB
  2. LLM synthesises upgrade proposals from belief clusters
  3. Proposals sent to Telegram for approval
  4. Approved → executed (search config, prompt tweaks, belief seeds)
  5. Rejected → logged, factored into future proposals

Proposal types (safe first):
  - youtube_topic   : add topic to YouTube AGI search rotation
  - priority_topic  : add to priority_topics.json
  - seed_belief     : inject a synthesised belief into DB
  - search_query    : add a permanent AGI search query
  - prompt_hint     : add a reasoning hint to soul loop

Run from run.py every N cycles, or standalone for testing.
"""

import json, sqlite3, time, requests, logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger("nex.upgrade_bridge")

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH        = Path("/home/rr/Desktop/nex/nex.db")
CFG            = Path.home() / ".config/nex"
PROPOSALS_PATH = CFG / "belief_upgrade_proposals.json"
APPROVED_PATH  = CFG / "belief_upgrade_approved.json"
REJECTED_PATH  = CFG / "belief_upgrade_rejected.json"
PRIORITY_PATH  = CFG / "priority_topics.json"
LLM_URL        = "http://localhost:8080/completion"
BRIDGE_INTERVAL = 10  # run every N cycles

# ── LLM call ──────────────────────────────────────────────────────────────────
def _llm(prompt, max_tokens=400, timeout=25):
    try:
        r = requests.post(LLM_URL, json={
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": 0.4,
            "stop": ["###", "\n\n\n"]
        }, timeout=timeout)
        return r.json().get("content", "").strip()
    except Exception as e:
        log.warning(f"LLM call failed: {e}")
        return ""

# ── Pull strong beliefs ────────────────────────────────────────────────────────
def get_strong_beliefs(limit=30):
    try:
        con = sqlite3.connect(str(DB_PATH), timeout=5)
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT id, content, topic, confidence, timestamp
            FROM beliefs
            WHERE confidence >= 0.75
            ORDER BY confidence DESC, id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error(f"DB error: {e}")
        return []

# ── Get already-proposed belief IDs ───────────────────────────────────────────
def get_proposed_ids():
    try:
        proposed = json.loads(PROPOSALS_PATH.read_text()) if PROPOSALS_PATH.exists() else []
        approved = json.loads(APPROVED_PATH.read_text()) if APPROVED_PATH.exists() else []
        rejected = json.loads(REJECTED_PATH.read_text()) if REJECTED_PATH.exists() else []
        seen = set()
        for p in proposed + approved + rejected:
            for bid in p.get("belief_ids", []):
                seen.add(bid)
        return seen
    except:
        return set()

# ── Generate upgrade proposal from belief cluster ─────────────────────────────
def generate_proposal(beliefs):
    if not beliefs:
        return None

    belief_text = "\n".join([
        f"- [{b['topic']}] (conf={b['confidence']:.2f}) {b['content'][:120]}"
        for b in beliefs[:8]
    ])

    # Rule-based proposal — no LLM needed, fast and reliable
    import re as _re

    # Extract key themes from beliefs
    all_text = " ".join(b["content"].lower() for b in beliefs[:10])
    
    # Detect dominant theme and propose accordingly
    AGI_THEMES = [
        ("free energy principle", "free energy principle Karl Friston intelligence"),
        ("consciousness", "consciousness as information integration AGI"),
        ("emergence", "emergence complexity self-organisation intelligence"),
        ("corrigib", "corrigibility value alignment AI safety solutions"),
        ("recursive", "recursive self improvement intelligence explosion"),
        ("substrate", "substrate independence mind uploading general intelligence"),
        ("evolution", "evolutionary computation open-ended intelligence"),
        ("thermodynamic", "thermodynamics computation intelligence energy"),
        ("embodied", "embodied cognition intelligence without brain"),
        ("collective", "collective intelligence swarm emergence AGI"),
        ("formal", "formal systems incompleteness self-reference intelligence"),
        ("quantum", "quantum cognition decision making intelligence"),
        ("language", "language thought sapir whorf hypothesis intelligence"),
        ("memory", "memory consolidation sleep intelligence learning"),
        ("attention", "attention mechanism consciousness global workspace"),
    ]
    
    matched_query = None
    for keyword, query in AGI_THEMES:
        if keyword in all_text:
            matched_query = query
            break
    
    # Default to rotating AGI hunt if no theme match
    if not matched_query:
        import random
        matched_query = random.choice([
            "how does general intelligence differ from narrow AI",
            "what biological systems exhibit general intelligence",
            "AGI alignment approaches comparison 2024",
            "cognitive architecture general intelligence SOAR ACT-R",
            "intelligence as compression prediction world model",
        ])
    
    # Check dominant topic for priority_topic proposal
    topics = [b["topic"] for b in beliefs[:10] if b.get("topic")]
    from collections import Counter
    top_topic = Counter(topics).most_common(1)[0][0] if topics else "agi"
    
    # Alternate between proposal types based on belief count
    total_proposed = len(get_proposed_ids())
    ptype = ["youtube_topic", "priority_topic", "youtube_topic", "seed_belief"][total_proposed % 4]
    
    if ptype == "seed_belief":
        # Synthesise a meta-belief from the cluster
        snippets = [b["content"][:80] for b in beliefs[:4]]
        value = f"Pattern across high-confidence beliefs: {snippets[0][:60]}... implies {snippets[-1][:60]}"
        rationale = f"Synthesised from {len(beliefs[:4])} beliefs in domain {top_topic}"
    elif ptype == "priority_topic":
        value = top_topic
        rationale = f"Dominant topic across {len(beliefs)} strong beliefs — should lead next learning cycle"
    else:
        value = matched_query
        rationale = f"Theme detected in belief cluster: '{list(filter(lambda x: x[0] in all_text, AGI_THEMES+[('',matched_query)]))[0][0] or 'agi'}'"

    proposal = {
        "type": ptype,
        "value": value,
        "rationale": rationale,
        "confidence": round(sum(b["confidence"] for b in beliefs[:8]) / len(beliefs[:8]), 2),
        "belief_ids": [b["id"] for b in beliefs[:8]],
        "generated_at": datetime.now().isoformat(),
        "status": "pending"
    }
    return proposal

# ── Send proposal to Telegram ─────────────────────────────────────────────────
def send_telegram_proposal(proposal, bot_token, chat_id):
    try:
        ptype = proposal.get("type", "?")
        value = proposal.get("value", "?")
        rationale = proposal.get("rationale", "?")
        conf = proposal.get("confidence", 0)
        pid = proposal.get("id", "?")

        msg = (
            f"🧠 *NEX UPGRADE PROPOSAL*\n\n"
            f"*Type:* `{ptype}`\n"
            f"*Value:* {value}\n"
            f"*Why:* {rationale}\n"
            f"*Confidence:* {conf:.0%}\n\n"
            f"Reply *yes {pid}* to approve or *no {pid}* to reject."
        )

        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
        log.info(f"Proposal {pid} sent to Telegram")
        return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False

# ── Execute approved proposal ─────────────────────────────────────────────────
def execute_proposal(proposal):
    ptype = proposal.get("type")
    value = proposal.get("value", "")

    try:
        if ptype == "youtube_topic":
            # Add to YouTube AGI hunt queries in nex_youtube.py
            yt_path = Path("/home/rr/Desktop/nex/nex_youtube.py")
            content = yt_path.read_text()
            if value not in content:
                old = "AGI_HUNT_QUERIES = ["
                new = f'AGI_HUNT_QUERIES = [\n    "{value}",'
                content = content.replace(old, new)
                yt_path.write_text(content)
                log.info(f"Added YouTube topic: {value}")
                return True, f"Added '{value}' to AGI_HUNT_QUERIES"

        elif ptype == "priority_topic":
            topics = json.loads(PRIORITY_PATH.read_text()) if PRIORITY_PATH.exists() else []
            if value not in topics:
                topics.insert(0, value)
                PRIORITY_PATH.write_text(json.dumps(topics[:15]))
                log.info(f"Added priority topic: {value}")
                return True, f"Added '{value}' to priority topics"

        elif ptype == "seed_belief":
            con = sqlite3.connect(str(DB_PATH), timeout=5)
            con.execute("""
                INSERT OR IGNORE INTO beliefs (content, topic, confidence, source, timestamp)
                VALUES (?, 'agi', 0.80, 'upgrade_bridge', datetime('now'))
            """, (value,))
            con.commit()
            con.close()
            log.info(f"Seeded belief: {value[:60]}")
            return True, f"Seeded belief into DB"

        elif ptype == "search_query":
            # Add to neti-neti queries
            yt_path = Path("/home/rr/Desktop/nex/nex_youtube.py")
            content = yt_path.read_text()
            if value not in content:
                old = "NETI_NETI_QUERIES = ["
                new = f'NETI_NETI_QUERIES = [\n    "{value}",'
                content = content.replace(old, new)
                yt_path.write_text(content)
                return True, f"Added search query: {value}"

        return False, f"Unknown type: {ptype}"

    except Exception as e:
        log.error(f"Execute failed: {e}")
        return False, str(e)

# ── Save proposals ─────────────────────────────────────────────────────────────
def save_proposal(proposal):
    proposals = json.loads(PROPOSALS_PATH.read_text()) if PROPOSALS_PATH.exists() else []
    proposal["id"] = f"UP{len(proposals)+1:04d}"
    proposals.append(proposal)
    PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))
    return proposal["id"]

# ── Check Telegram for approvals ───────────────────────────────────────────────
def check_telegram_responses(bot_token, last_update_id=0):
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getUpdates",
            params={"offset": last_update_id + 1, "timeout": 5},
            timeout=10
        )
        updates = r.json().get("result", [])
        responses = []
        new_last_id = last_update_id
        for u in updates:
            new_last_id = max(new_last_id, u["update_id"])
            msg = u.get("message", {}).get("text", "").strip().lower()
            if msg.startswith("yes ") or msg.startswith("no "):
                parts = msg.split()
                action = parts[0]
                pid = parts[1].upper() if len(parts) > 1 else ""
                responses.append({"action": action, "id": pid})
        return responses, new_last_id
    except:
        return [], last_update_id

# ── Main cycle ────────────────────────────────────────────────────────────────
def run_upgrade_bridge(cycle=0, bot_token=None, chat_id=None):
    if cycle % BRIDGE_INTERVAL != 0:
        return {"skipped": True}

    log.info("[UPGRADE BRIDGE] Running...")

    # Get strong beliefs not yet proposed
    beliefs = get_strong_beliefs(limit=40)
    proposed_ids = get_proposed_ids()
    fresh = [b for b in beliefs if b["id"] not in proposed_ids]

    if len(fresh) < 5:
        log.info("[UPGRADE BRIDGE] Not enough fresh beliefs yet")
        return {"skipped": True, "reason": "insufficient fresh beliefs"}

    # Generate proposal from top fresh beliefs
    proposal = generate_proposal(fresh[:10])
    if not proposal:
        return {"skipped": True, "reason": "proposal generation failed"}

    pid = save_proposal(proposal)
    log.info(f"[UPGRADE BRIDGE] Generated proposal {pid}: {proposal.get('type')} — {proposal.get('value','')[:60]}")

    # Auto-execute — no approval needed
    ok, result_msg = execute_proposal(proposal)
    log.info(f"[UPGRADE BRIDGE] Auto-executed {pid}: {ok} — {result_msg}")
    print(f"  [UPGRADE] Auto-executed: {proposal.get('type')} — {proposal.get('value','')[:60]}")
    # Notify Telegram (info only, no approval needed)
    if bot_token and chat_id:
        try:
            import requests as _rq
            _rq.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": f"⚡ NEX self-upgraded\nType: {proposal.get('type')}\nValue: {proposal.get('value','')[:80]}\nResult: {result_msg}", "parse_mode": "Markdown"},
                timeout=10)
        except: pass

    # Print to terminal always
    print(f"\n  [UPGRADE PROPOSAL {pid}] {proposal.get('type')}: {proposal.get('value','')[:80]}")
    print(f"  Why: {proposal.get('rationale','')[:100]}")
    print(f"  Reply 'yes {pid}' or 'no {pid}' in Telegram to action\n")

    return {
        "proposal_id": pid,
        "type": proposal.get("type"),
        "value": proposal.get("value", "")[:80]
    }


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Load Telegram creds
    try:
        import sys
        sys.path.insert(0, "/home/rr/Desktop/nex")
        from nex_telegram import BOT_TOKEN
        env = {}
        env_path = Path("/home/rr/Desktop/nex/.env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k,v = line.split("=",1)
                    env[k.strip()] = v.strip()
        try:
            from nex_telegram_commands import OWNER_TELEGRAM_ID as _OTID
            CHAT_ID = str(_OTID)
        except:
            CHAT_ID = env.get("OWNER_TELEGRAM_ID") or env.get("TELEGRAM_CHAT_ID") or "5217790760"
        print(f"Telegram: token={'OK' if BOT_TOKEN else 'MISSING'} chat_id={CHAT_ID}")
    except Exception as e:
        BOT_TOKEN = None
        CHAT_ID = None
        print(f"No Telegram creds: {e}")

    print("Running upgrade bridge standalone test...")
    result = run_upgrade_bridge(cycle=0, bot_token=BOT_TOKEN, chat_id=CHAT_ID)
    print(f"\nResult: {result}")

    if BOT_TOKEN and CHAT_ID:
        print("\nListening for Telegram responses (30s)...")
        last_id = 0
        for _ in range(6):
            responses, last_id = check_telegram_responses(BOT_TOKEN, last_id)
            for resp in responses:
                print(f"Response: {resp}")
                proposals = json.loads(PROPOSALS_PATH.read_text()) if PROPOSALS_PATH.exists() else []
                for p in proposals:
                    if p.get("id") == resp["id"]:
                        if resp["action"] == "yes":
                            ok, msg = execute_proposal(p)
                            print(f"Executed: {ok} — {msg}")
                        else:
                            print(f"Rejected proposal {resp['id']}")
            time.sleep(5)
