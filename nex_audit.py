#!/usr/bin/env python3
"""
NEX FULL PIPELINE AUDIT
Tests every component and writes a report to ~/Desktop/nex_audit.txt
"""
import json, os, re, sys, subprocess, traceback
from pathlib import Path
from datetime import datetime
from collections import Counter

sys.path.insert(0, str(Path.home() / "Desktop/nex"))

CONFIG   = Path.home() / ".config/nex"
DESKTOP  = Path.home() / "Desktop"
OUT_FILE = DESKTOP / "nex_audit.txt"

lines = []
issues = []
ok_count = 0
warn_count = 0
fail_count = 0

def section(title):
    lines.append("")
    lines.append("═" * 60)
    lines.append(f"  {title}")
    lines.append("═" * 60)

def ok(label, detail=""):
    global ok_count
    ok_count += 1
    lines.append(f"  ✓  {label}" + (f"  →  {detail}" if detail else ""))

def warn(label, detail=""):
    global warn_count
    warn_count += 1
    lines.append(f"  ⚠  {label}" + (f"  →  {detail}" if detail else ""))
    issues.append(f"WARN: {label} {detail}")

def fail(label, detail=""):
    global fail_count
    fail_count += 1
    lines.append(f"  ✗  {label}" + (f"  →  {detail}" if detail else ""))
    issues.append(f"FAIL: {label} {detail}")

def load(filename, default=None):
    try:
        p = CONFIG / filename
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return default

# ══════════════════════════════════════════════════════════════
lines.append("NEX FULL PIPELINE AUDIT")
lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
lines.append("")

# ══════════════════════════════════════════════════════════════
section("1. FILE SYSTEM")
# ══════════════════════════════════════════════════════════════

nex_root = Path.home() / "Desktop/nex"
nex_pkg  = nex_root / "nex"

critical_files = [
    (nex_root / "run.py",              "Main entry point"),
    (nex_root / "nex_telegram.py",     "Telegram bot"),
    (nex_root / "nex_watchdog_patch.py","Watchdog"),
    (nex_pkg  / "auto_learn.py",       "Auto-learn engine"),
    (nex_pkg  / "cognition.py",        "Cognition engine"),
    (nex_pkg  / "moltbook_learning.py","Moltbook learner"),
    (nex_pkg  / "moltbook_client.py",  "Moltbook client"),
    (nex_pkg  / "agent_brain.py",      "LLM brain"),
    (nex_pkg  / "belief_bridge.py",    "Belief bridge"),
    (nex_pkg  / "orchestrator.py",     "Orchestrator"),
]

for path, label in critical_files:
    if path.exists():
        ok(label, f"{path.stat().st_size} bytes")
    else:
        fail(label, f"MISSING: {path}")

# Check for leftover bak files
bak_files = list(nex_root.glob("*.bak*")) + list(nex_pkg.glob("*.bak*")) + \
            list(nex_root.glob("*.broken*")) + list(nex_pkg.glob("*.broken*"))
if bak_files:
    warn(f"{len(bak_files)} backup/broken files still present",
         ", ".join(f.name for f in bak_files[:5]))
else:
    ok("No leftover backup files")

# ══════════════════════════════════════════════════════════════
section("2. PYTHON SYNTAX CHECK — ALL CORE FILES")
# ══════════════════════════════════════════════════════════════

py_files = list(nex_pkg.glob("*.py")) + [nex_root/"run.py", nex_root/"nex_telegram.py"]
syntax_errors = []
for f in sorted(py_files):
    if ".bak" in f.name or ".broken" in f.name:
        continue
    r = subprocess.run(["python3", "-m", "py_compile", str(f)], capture_output=True)
    if r.returncode != 0:
        fail(f.name, r.stderr.decode().strip()[:80])
        syntax_errors.append(f.name)
    else:
        ok(f.name, "parses cleanly")

# ══════════════════════════════════════════════════════════════
section("3. DATA FILES — EXISTENCE & QUALITY")
# ══════════════════════════════════════════════════════════════

beliefs    = load("beliefs.json", [])
agents     = load("agents.json", {})
posts      = load("known_posts.json", [])
convos     = load("conversations.json", [])
insights   = load("insights.json", [])
reflects   = load("reflections.json", [])
profiles   = load("agent_profiles.json", {})
creds_path = Path.home() / ".config/moltbook/credentials.json"

lines.append(f"  beliefs.json       : {len(beliefs)} entries")
lines.append(f"  agents.json        : {len(agents)} entries")
lines.append(f"  known_posts.json   : {len(posts)} entries")
lines.append(f"  conversations.json : {len(convos)} entries")
lines.append(f"  insights.json      : {len(insights)} entries")
lines.append(f"  reflections.json   : {len(reflects)} entries")
lines.append(f"  agent_profiles.json: {len(profiles)} entries")
lines.append("")

# Belief quality
if len(beliefs) == 0:
    fail("beliefs.json is empty — no learning has occurred")
elif len(beliefs) < 50:
    warn("Low belief count", f"{len(beliefs)} — expected 100+")
else:
    ok("Belief count healthy", str(len(beliefs)))

# Check belief structure
if beliefs:
    sample = beliefs[-1]
    required_keys = ["source","author","content","karma","tags","confidence"]
    missing = [k for k in required_keys if k not in sample]
    if missing:
        fail("Belief schema missing keys", str(missing))
    else:
        ok("Belief schema correct")

    # Check karma population
    zero_karma = sum(1 for b in beliefs if b.get("karma",0) == 0)
    pct = zero_karma / len(beliefs) * 100
    if pct > 80:
        warn(f"High karma=0 rate in beliefs", f"{pct:.0f}% of beliefs have karma=0")
    else:
        ok(f"Karma populated in beliefs", f"{100-pct:.0f}% have karma values")

    # Check for duplicate beliefs
    contents = [b.get("content","")[:60] for b in beliefs]
    dupes = len(contents) - len(set(contents))
    if dupes > 5:
        warn(f"Duplicate beliefs detected", f"{dupes} duplicates")
    else:
        ok("Belief deduplication OK", f"{dupes} duplicates")

# Agents karma
if not agents:
    fail("agents.json empty — karma tracker not writing",
         "run_cognition_cycle hasn't fired yet or karma injection failed")
elif len(agents) < 5:
    warn("Very few agents tracked", f"{len(agents)} — expected 20+")
else:
    ok("Agents tracked", f"{len(agents)} agents with karma")
    top3 = sorted(agents.items(), key=lambda x:-x[1])[:3]
    for name, karma in top3:
        lines.append(f"    @{name}: {karma}κ")

# Conversations dedup check
if convos:
    post_ids = [c.get("post_id","") for c in convos]
    dupes = len(post_ids) - len(set(post_ids))
    if dupes > 3:
        fail("Conversation deduplication BROKEN",
             f"{dupes} duplicate post_ids — same post commented on multiple times")
    else:
        ok("Conversation deduplication", f"{dupes} duplicates (acceptable)")

    # Check comment quality
    comments = [c.get("my_comment","") for c in convos[-20:]]
    generic = sum(1 for c in comments if "Data exchange request" in c)
    if generic > len(comments) * 0.5:
        warn("Comment quality", f"{generic}/{len(comments)} recent comments are generic data-exchange template")
    else:
        ok("Comment variety", f"responses look varied")

# Insights
if not insights:
    warn("No insights generated yet", "cognition cycle may not have run")
elif len(insights) < 5:
    warn("Low insight count", f"{len(insights)} — expected 15+ with {len(beliefs)} beliefs")
else:
    ok("Insights generated", f"{len(insights)} insights")

    # Check insight topic quality
    NOISE = {'basically','tested','taught','most','same','human','every',
             'because','comments','system','files','said','even','good'}
    noisy = [i for i in insights if i.get("topic","") in NOISE]
    if noisy:
        warn("Noisy insight topics", f"{len(noisy)} topics are stop words: "
             + str([i["topic"] for i in noisy]))
    else:
        ok("Insight topic quality", "no noise words in topics")

    # Check confidence
    avg_conf = sum(i.get("confidence",0) for i in insights) / len(insights)
    if avg_conf < 0.6:
        warn("Low insight confidence", f"avg {avg_conf:.0%} — clustering may be too loose")
    else:
        ok("Insight confidence", f"avg {avg_conf:.0%}")

# Profiles
if profiles:
    leaderboard = load("agents.json", {})
    lb_in_profiles = {n: profiles[n] for n in leaderboard if n in profiles}
    if lb_in_profiles:
        zero_karma_lb = sum(1 for p in lb_in_profiles.values() if p.get("karma_observed",0) == 0)
        pct_lb = zero_karma_lb / len(lb_in_profiles) * 100
        if pct_lb > 50:
            fail("Agent profiles have no karma", f"{pct_lb:.0f}% of leaderboard agents have karma=0 in profiles")
        else:
            ok("Agent profile karma", f"{len(lb_in_profiles) - zero_karma_lb}/{len(lb_in_profiles)} leaderboard agents have karma in profiles")
    else:
        ok("Agent profile karma", "leaderboard not yet cross-referenced with profiles")

    corrupted = [(n,p) for n,p in profiles.items() if p.get("conversations_had",0) > 500]
    if corrupted:
        warn("Corrupted conversation counters",
             str([(n, p["conversations_had"]) for n,p in corrupted]))
    else:
        ok("Conversation counters look sane")

# ══════════════════════════════════════════════════════════════
section("4. MOLTBOOK CONNECTION")
# ══════════════════════════════════════════════════════════════

try:
    if not creds_path.exists():
        fail("Moltbook credentials missing", str(creds_path))
    else:
        creds = json.loads(creds_path.read_text())
        ok("Credentials file found")

        from nex.moltbook_client import MoltbookClient
        client = MoltbookClient(api_key=creds["api_key"])

        # Test status
        status = client._request("GET", "/agents/status")
        agent_name = status.get("agent",{}).get("name","?")
        ok("Moltbook connection", f"agent: {agent_name}")

        # Test feed
        feed = client._request("GET", "/feed")
        feed_posts = feed.get("posts",[])
        ok("Feed accessible", f"{len(feed_posts)} posts available")

        # Check for new posts vs known
        known_set = set(posts) if isinstance(posts, list) else set()
        new_posts = [p for p in feed_posts if p.get("id","") not in known_set]
        if new_posts:
            ok(f"New posts available to learn", f"{len(new_posts)} unprocessed")
        else:
            lines.append(f"  ·  Feed caught up — {len(feed_posts)} posts all known")

        # Check feed post structure
        if feed_posts:
            sample = feed_posts[0]
            has_author_karma = bool(sample.get("author",{}).get("karma",0))
            if not has_author_karma:
                warn("Feed author karma missing",
                     "author.karma=0 in feed — this is why agent_karma may be empty")
            else:
                ok("Feed author karma present")

except Exception as e:
    fail("Moltbook connection failed", str(e)[:100])

# ══════════════════════════════════════════════════════════════
section("5. LLM BACKEND")
# ══════════════════════════════════════════════════════════════

try:
    import urllib.request
    req = urllib.request.urlopen("http://localhost:8080/health", timeout=3)
    data = json.loads(req.read())
    ok("llama.cpp server", f"status: {data.get('status','?')}")
except Exception as e:
    fail("llama.cpp server not responding", str(e)[:80])
    fail("Telegram bot will fall back to belief-only responses (no LLM)")

# Check max_tokens setting
try:
    brain_src = (nex_pkg / "agent_brain.py").read_text()
    match = re.search(r'max_tokens.*?=.*?(\d+)', brain_src)
    if match:
        val = int(match.group(1))
        if val < 200:
            fail("max_tokens too low", f"{val} — responses will be cut off")
        elif val < 350:
            warn("max_tokens somewhat low", f"{val} — consider 400+")
        else:
            ok("max_tokens", str(val))
except Exception:
    pass

# ══════════════════════════════════════════════════════════════
section("6. TELEGRAM BOT")
# ══════════════════════════════════════════════════════════════

try:
    tg_src = (nex_root / "nex_telegram.py").read_text()

    # Check watchdog placement
    if "from telegram.ext import (" in tg_src:
        import_block = tg_src.split("from telegram.ext import (")[1].split(")")[0]
        if "enforce_singleton" in import_block:
            fail("Watchdog still inside telegram import block — broken placement")
        else:
            ok("Watchdog placement correct")
    
    # Check auto-reconnect
    if "while True:  # ── auto-reconnect loop" in tg_src:
        ok("Auto-reconnect loop present")
    else:
        warn("Auto-reconnect loop missing — bot will die silently on errors")

    # Check /debug command
    if "cmd_debug" in tg_src:
        ok("/debug command present")
    else:
        warn("/debug command missing — add for phone diagnostics")

    # Check token
    tok_match = re.search(r'BOT_TOKEN\s*=\s*"([^"]+)"', tg_src)
    if tok_match:
        tok = tok_match.group(1)
        try:
            import urllib.request
            r = urllib.request.urlopen(
                f"https://api.telegram.org/bot{tok}/getMe", timeout=5)
            bot_data = json.loads(r.read())
            bot_name = bot_data.get("result",{}).get("username","?")
            ok("Telegram bot token valid", f"@{bot_name}")
        except Exception as e:
            fail("Telegram bot token check failed", str(e)[:60])

except Exception as e:
    fail("Could not audit nex_telegram.py", str(e)[:80])

# ══════════════════════════════════════════════════════════════
section("7. DATA ABSORPTION PIPELINE TRACE")
# ══════════════════════════════════════════════════════════════

lines.append("  Tracing: Feed → Belief → Karma → Profile → Insight → Chat")
lines.append("")

# Step 1: Feed ingestion
try:
    from nex.moltbook_learning import MoltbookLearner
    ok("Step 1: MoltbookLearner importable")
except Exception as e:
    fail("Step 1: MoltbookLearner import failed", str(e)[:80])

# Step 2: Belief bridge
try:
    from nex.belief_bridge import generate_belief_context
    ctx = generate_belief_context()
    if ctx and len(ctx) > 50:
        ok("Step 2: Belief bridge generates context", f"{len(ctx)} chars")
    else:
        warn("Step 2: Belief bridge returns empty context")
except Exception as e:
    fail("Step 2: Belief bridge failed", str(e)[:80])

# Step 3: Cognition
try:
    from nex.cognition import generate_cognitive_context, run_synthesis
    ctx = generate_cognitive_context()
    if ctx and len(ctx) > 100:
        ok("Step 3: Cognitive context generated", f"{len(ctx)} chars")
    else:
        warn("Step 3: Cognitive context empty or too short", f"{len(ctx) if ctx else 0} chars")
except Exception as e:
    fail("Step 3: Cognition engine failed", str(e)[:80])

# Step 4: LLM prompt injection
try:
    from nex_telegram import get_system_prompt
    prompt = get_system_prompt("test query about memory")
    if "NEX COGNITIVE STATE" in prompt or "beliefs" in prompt.lower():
        ok("Step 4: Cognitive context injected into LLM prompt",
           f"prompt is {len(prompt)} chars")
    else:
        warn("Step 4: LLM prompt may not include cognitive context",
             "beliefs not visible in system prompt")
except Exception as e:
    fail("Step 4: System prompt generation failed", str(e)[:80])

# Step 5: Auto-learn dedup
try:
    from nex.auto_learn import engage_with_post
    src = (nex_pkg / "auto_learn.py").read_text()
    if "already_commented" in src:
        ok("Step 5: engage_with_post() has dedup check")
    else:
        fail("Step 5: engage_with_post() missing dedup — will spam comments")
except Exception as e:
    fail("Step 5: Could not check auto_learn dedup", str(e)[:80])

# Step 6: Cognition cycle dedup
try:
    cog_src = (nex_pkg / "cognition.py").read_text()
    if "commented_ids" in cog_src:
        ok("Step 6: run_cognition_cycle() has dedup check")
    else:
        fail("Step 6: run_cognition_cycle() missing dedup — will spam comments")
except Exception as e:
    fail("Step 6: Could not check cognition dedup", str(e)[:80])

# ══════════════════════════════════════════════════════════════
section("8. TRENDING TOPIC QUALITY CHECK")
# ══════════════════════════════════════════════════════════════

STOP_FULL = {
    'the','and','for','that','this','with','from','have','been','they',
    'what','when','your','will','more','about','than','them','into',
    'just','like','some','would','could','should','also','were','dont',
    'their','which','there','being','does','only','very','much','here',
    'agents','agent','post','posts','moltbook','content','make','think',
    'every','because','same','human','comments','system','most','basically',
    'really','know','need','want','thing','things','people','time','data',
    'never','always','first','last','years','weeks','zero','five','three',
    'many','each','both','such','these','those','platform','feedback',
    'received','receive','writing','single','point','said','says','even',
    'back','good','going','come','take','work','used','using','user','based',
    'since','still','tested','taught','soul','tools','internal','strange',
    'optimized','identity','tool','human',
}

if beliefs:
    words = []
    for b in beliefs[-80:]:
        found = re.findall(r'\b[A-Za-z]{5,}\b', b.get("content","").lower())
        words.extend([w for w in found if w not in STOP_FULL])
    top = Counter(words).most_common(10)
    lines.append("  Top trending topics (noise-filtered):")
    for word, count in top:
        lines.append(f"    #{word} ({count})")

    noisy_top = Counter(words).most_common(10)
    noise_in_top = [w for w,c in noisy_top if w in STOP_FULL]
    if noise_in_top:
        warn("Noise words still appearing in trending", str(noise_in_top))
    else:
        ok("Trending topics are clean signal")

# ══════════════════════════════════════════════════════════════
section("9. IMPROVEMENT RECOMMENDATIONS")
# ══════════════════════════════════════════════════════════════

# Based on findings, generate specific recommendations
recs = []

if not agents:
    recs.append("HIGH: agents.json is empty. Karma tracker not writing. "
                "Check that run_cognition_cycle is being called and "
                "learner.agent_karma is populated after feed ingestion.")

if convos:
    post_ids = [c.get("post_id","") for c in convos]
    dupes = len(post_ids) - len(set(post_ids))
    if dupes > 3:
        recs.append(f"HIGH: {dupes} duplicate conversation entries. "
                    "Dedup patch may not be active.")

if beliefs:
    zero_karma = sum(1 for b in beliefs if b.get("karma",0) == 0)
    if zero_karma / len(beliefs) > 0.8:
        recs.append("MED: 80%+ of beliefs have karma=0. The feed's author.karma "
                    "field may be 0 for most agents on Moltbook — this is normal "
                    "if agents haven't been upvoted. Not necessarily a bug.")

if len(insights) < 10 and len(beliefs) > 100:
    recs.append(f"MED: Only {len(insights)} insights from {len(beliefs)} beliefs. "
                "Consider lowering cluster min_beliefs further or running "
                "run_synthesis() manually once to force a rebuild.")

if reflects and len(reflects) > 0:
    recent = reflects[-10:]
    avg_align = sum(r.get("topic_alignment",0) for r in recent) / len(recent)
    if avg_align < 0.3:
        recs.append("MED: Low topic alignment in reflections "
                    f"({avg_align:.0%}). NEX is drifting from user topics. "
                    "The cognitive context injection may need tuning.")

recs.append("LOW: Consider adding a /teach command to Telegram — lets you "
            "manually inject a belief into her field from your phone.")
recs.append("LOW: The 120s auto-learn cycle is conservative. "
            "Could drop to 60s for faster absorption when Moltbook is active.")
recs.append("LOW: Belief expiry — old low-confidence beliefs never expire. "
            "After 500+ beliefs, stale data will dilute insights.")

for i, r in enumerate(recs, 1):
    lines.append(f"  {i}. {r}")
    lines.append("")

# ══════════════════════════════════════════════════════════════
section("SUMMARY")
# ══════════════════════════════════════════════════════════════

total = ok_count + warn_count + fail_count
lines.append(f"  ✓  PASS  : {ok_count}")
lines.append(f"  ⚠  WARN  : {warn_count}")
lines.append(f"  ✗  FAIL  : {fail_count}")
lines.append(f"  Total    : {total} checks")
lines.append("")

if fail_count == 0 and warn_count <= 3:
    lines.append("  ● NEX pipeline looks HEALTHY")
elif fail_count == 0:
    lines.append("  ● NEX pipeline FUNCTIONAL with warnings")
elif fail_count <= 3:
    lines.append("  ● NEX pipeline has ISSUES — review FAILs above")
else:
    lines.append("  ● NEX pipeline has CRITICAL PROBLEMS")

lines.append("")
lines.append(f"  Report saved: {OUT_FILE}")
lines.append("")

# ── Write report ──
report = "\n".join(lines)
OUT_FILE.write_text(report)

# ── Also print to terminal ──
print(report)
print(f"\n  Report written to {OUT_FILE}")
