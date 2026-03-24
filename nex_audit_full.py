#!/usr/bin/env python3
"""
nex_audit_full.py — Full NEX system health audit
Run: python3 nex_audit_full.py
Checks all modules, DB, logs, LLM, platforms, training readiness.
"""

import sqlite3, json, os, re, subprocess, time, requests
from pathlib import Path
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────
DB        = Path.home() / '.config/nex/nex_data/nex.db'
CFG       = Path.home() / '.config/nex'
LLM_URL   = 'http://localhost:11434/v1/chat/completions'
LLM_MODEL = 'mistral-nex'

GREEN  = '\033[92m'
YELLOW = '\033[93m'
RED    = '\033[91m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
RESET  = '\033[0m'

results = []

def ok(label, detail=''):
    results.append(('OK', label, detail))
    print(f"  {GREEN}✓{RESET} {label:<45} {detail}")

def warn(label, detail=''):
    results.append(('WARN', label, detail))
    print(f"  {YELLOW}⚠{RESET} {label:<45} {detail}")

def fail(label, detail=''):
    results.append(('FAIL', label, detail))
    print(f"  {RED}✗{RESET} {label:<45} {detail}")

def section(title):
    print(f"\n{BOLD}{CYAN}{'─'*55}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*55}{RESET}")

print(f"\n{BOLD}NEX SYSTEM AUDIT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")

# ── 1. DB HEALTH ──────────────────────────────────────────────
section("1. DATABASE HEALTH")
try:
    db = sqlite3.connect(str(DB), timeout=5)
    db.row_factory = sqlite3.Row

    beliefs     = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    avg_conf    = db.execute("SELECT ROUND(AVG(confidence),3) FROM beliefs").fetchone()[0] or 0
    reflections = db.execute("SELECT COUNT(*) FROM reflections").fetchone()[0]
    # insights live in insights.json not DB
    import json as _j
    _ifile = Path.home() / '.config/nex/insights.json'
    insights = len(_j.loads(_ifile.read_text())) if _ifile.exists() else 0
    identity    = db.execute("SELECT COUNT(*) FROM beliefs WHERE is_identity=1").fetchone()[0]
    high_conf   = db.execute("SELECT COUNT(*) FROM beliefs WHERE confidence > 0.7").fetchone()[0]

    if beliefs > 500:    ok("Belief count",    f"{beliefs}")
    elif beliefs > 100:  warn("Belief count",  f"{beliefs} — low")
    else:                fail("Belief count",  f"{beliefs} — critically low")

    if avg_conf >= 0.55:    ok("avg_conf",   f"{avg_conf}")
    elif avg_conf >= 0.40:  warn("avg_conf", f"{avg_conf} — below target 0.60")
    else:                   fail("avg_conf", f"{avg_conf} — collapse risk")

    if reflections > 500:    ok("Reflections",   f"{reflections}")
    elif reflections > 100:  warn("Reflections", f"{reflections} — accumulating")
    else:                    fail("Reflections", f"{reflections} — too few for training")

    if insights > 50:   ok("Insights (JSON)",   f"{insights}")
    elif insights > 0:  warn("Insights (JSON)", f"{insights} — low")
    else:               fail("Insights (JSON)", "0 — empty")

    ok("Identity beliefs",       f"{identity} is_identity=1")
    ok("High confidence beliefs", f"{high_conf} > 0.70")

    phantom = db.execute("SELECT COUNT(*) FROM beliefs WHERE is_identity=1 AND (topic='' OR topic IS NULL)").fetchone()[0]
    if phantom == 0: ok("Phantom identity beliefs", "none")
    else:            fail("Phantom identity beliefs", f"{phantom} blank-topic identity beliefs")

    wal = Path(str(DB) + '-wal')
    if wal.exists():
        wal_mb = wal.stat().st_size / 1024 / 1024
        if wal_mb > 10: warn("WAL file", f"{wal_mb:.1f}MB — run PRAGMA wal_checkpoint")
        else:           ok("WAL file",   f"{wal_mb:.1f}MB")

    db.close()
except Exception as e:
    fail("Database", str(e))

# ── 2. LLM / OLLAMA ──────────────────────────────────────────
section("2. LLM / OLLAMA")
try:
    t0 = time.time()
    r = requests.post(LLM_URL, json={
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Reply with exactly: AUDIT_OK"}],
        "max_tokens": 10,
        "temperature": 0
    }, timeout=30)
    elapsed = round(time.time() - t0, 2)
    if r.status_code == 200:
        content = r.json()['choices'][0]['message']['content'].strip()
        ok("Ollama reachable", f"{elapsed}s response time")
        ok("LLM response",     f"'{content[:40]}'")
    else:
        fail("Ollama", f"HTTP {r.status_code}")
except requests.exceptions.ConnectionError:
    fail("Ollama", "Connection refused — is Ollama running?")
except Exception as e:
    fail("Ollama", str(e))

try:
    r = requests.get('http://localhost:11434/api/tags', timeout=5)
    if r.status_code == 200:
        models = [m['name'] for m in r.json().get('models', [])]
        if any('mistral-nex' in m for m in models):
            ok("mistral-nex model", "loaded")
        else:
            fail("mistral-nex model", f"not found — available: {models[:3]}")
except Exception as e:
    warn("Ollama model list", str(e))

# ── 3. PROCESSES ─────────────────────────────────────────────
section("3. PROCESSES")
try:
    out = subprocess.check_output(['pgrep', '-a', '-f', 'run.py'], text=True).strip()
    if out:
        ok("run.py", f"pid={out.split()[0]}")
    else:
        fail("run.py", "not running")
except subprocess.CalledProcessError:
    fail("run.py", "not running")

try:
    out = subprocess.check_output(['pgrep', '-a', '-f', 'ollama'], text=True).strip()
    if out: ok("ollama process", "running")
    else:   fail("ollama process", "not running")
except subprocess.CalledProcessError:
    fail("ollama process", "not running")

# ── 4. UPGRADE MODULES ───────────────────────────────────────
section("4. UPGRADE MODULES")
upgrade_dir = Path.home() / 'Desktop/nex/nex_upgrades'
expected = [
    'nex_upgrades_v2.py', 'nex_s7.py', 'nex_v65.py', 'nex_v72.py',
    'nex_v80.py', 'nex_u100.py', 'nex_r115.py', 'nex_e140.py',
    'nex_x160.py', 'nex_r181.py', 'nex_o223.py', 'nex_s620.py'
]
for mod in expected:
    p = upgrade_dir / mod
    if p.exists(): ok(f"Module {mod}", f"{p.stat().st_size//1024}KB")
    else:          fail(f"Module {mod}", "MISSING")

# ── 5. LOG SCAN ───────────────────────────────────────────────
section("5. LOG FILE SCAN")
logs = {
    'brain':  '/tmp/nex_brain.log',
    'v65':    '/tmp/nex_v65.log',
    'v72':    '/tmp/nex_v72.log',
    'v80':    '/tmp/nex_v80.log',
    'u100':   '/tmp/nex_u100.log',
    'r115':   '/tmp/nex_r115.log',
    'e140':   '/tmp/nex_e140.log',
    'x160':   '/tmp/nex_x160.log',
    'r181':   '/tmp/nex_r181.log',
    'o223':   '/tmp/nex_o223.log',
    's620':   '/tmp/nex_s620.log',
    'opener': '/tmp/nex_opener.log',
    'train':  '/tmp/nex_train.log',
}
error_kw = ['SyntaxError', 'Traceback', 'ImportError', 'AttributeError']

for name, logpath in logs.items():
    p = Path(logpath)
    if not p.exists():
        warn(f"Log [{name}]", "not found")
        continue
    age_min = (time.time() - p.stat().st_mtime) / 60
    recent  = '\n'.join(p.read_text(errors='ignore').splitlines()[-50:])
    errors  = [kw for kw in error_kw if kw in recent]
    if errors:
        fail(f"Log [{name}]", f"contains: {errors[0]}")
    elif age_min < 60:
        ok(f"Log [{name}]", f"active {age_min:.0f}min ago")
    else:
        warn(f"Log [{name}]", f"stale {age_min:.0f}min")

s620_err = Path('/tmp/nex_s620_err.txt')
if s620_err.exists() and s620_err.stat().st_size > 0:
    lines = [l for l in s620_err.read_text(errors='ignore').splitlines() if l.strip()]
    fail("S620 error file", lines[-1][:60] if lines else "has content")
else:
    ok("S620 error file", "clean")

# ── 6. TICK CHAIN ────────────────────────────────────────────
section("6. TICK CHAIN VERIFICATION")
run_py = Path.home() / 'Desktop/nex/run.py'
try:
    src = run_py.read_text(errors='ignore')
    # trainer and o223 are shallow early ticks — exclude from order check
    ticks = ['_s7.tick(', '_v65.tick(', '_v72.tick(', '_v80.tick(',
             '_u100.tick(', '_r115.tick(', '_e140.tick(', '_x160.tick(',
             '_r181.tick(', '_tick_s620(', '_v2.tick(']
    positions = {t: src.find(t) for t in ticks}
    missing = [t for t, pos in positions.items() if pos == -1]
    if missing:
        fail("Tick chain", f"missing: {missing}")
    else:
        # Check order
        prev_pos = -1
        order_ok = True
        for t in ticks:
            if positions[t] < prev_pos:
                fail("Tick order", f"{t} out of order")
                order_ok = False
                break
            prev_pos = positions[t]
        if order_ok:
            ok("Tick chain", f"all {len(ticks)} ticks present and ordered")

    if '_s620_loaded' in src:
        ok("S620 tick guard", "_s620_loaded present")
    else:
        warn("S620 tick guard", "missing")

except Exception as e:
    fail("Tick chain", str(e))

# ── 7. DIRECTIVE CONFIG ───────────────────────────────────────
section("7. DIRECTIVE CONFIG")
dir_py = Path.home() / 'Desktop/nex/nex/nex_directives.py'
try:
    src = dir_py.read_text()
    checks = {
        'D12_MAX_REINFORCEMENTS':  ('8',    None),
        'D20_CONF_DROP_THRESHOLD': ('0.12', '0.08'),
        'D20_FREEZE_CYCLES':       ('3',    '5'),
    }
    for var, (expected, old) in checks.items():
        m = re.search(rf'{var}\s*=\s*([0-9.]+)', src)
        if m:
            val = m.group(1)
            if val == expected:    ok(f"{var}", f"= {val}")
            elif old and val==old: warn(f"{var}", f"= {val} (should be {expected})")
            else:                  warn(f"{var}", f"= {val}")
        else:
            fail(f"{var}", "not found")
except Exception as e:
    fail("Directives", str(e))

# ── 8. S602 DECAY RATE ────────────────────────────────────────
section("8. S620 CONFIG")
s620_py = Path.home() / 'Desktop/nex/nex_upgrades/nex_s620.py'
try:
    src = s620_py.read_text()
    m = re.search(r'DECAY_RATE\s*=\s*([0-9.]+)', src)
    if m:
        rate = float(m.group(1))
        if rate <= 0.001:   ok("S602 DECAY_RATE", f"{rate} — safe")
        elif rate <= 0.003: warn("S602 DECAY_RATE", f"{rate} — may cause D20 loop")
        else:               fail("S602 DECAY_RATE", f"{rate} — too high")
    else:
        warn("S602 DECAY_RATE", "not found")
except Exception as e:
    fail("S620 config", str(e))

# ── 9. PERSISTENT CONFIG ─────────────────────────────────────
section("9. PERSISTENT CONFIG FILES")
cfg_files = [
    'strategies.json', 'policy.json', 'benchmarks.json', 'action_impact.json',
    'reward_state.json', 'style_memory.json', 'goal_tracker.json',
    'belief_lineage.json', 'failure_memory.json', 'social_models.json', 'meta_params.json'
]
for fname in cfg_files:
    p = CFG / fname
    if p.exists():
        try:
            json.loads(p.read_text())
            ok(f"{fname}", f"{p.stat().st_size} bytes")
        except json.JSONDecodeError:
            fail(f"{fname}", "CORRUPT JSON")
    else:
        warn(f"{fname}", "not yet created")

# ── 10. TRAINING READINESS ────────────────────────────────────
section("10. TRAINING READINESS")
try:
    db = sqlite3.connect(str(DB), timeout=5)
    b  = db.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
    c  = db.execute("SELECT AVG(confidence) FROM beliefs").fetchone()[0] or 0
    r  = db.execute("SELECT COUNT(*) FROM reflections WHERE LENGTH(nex_response) > 60").fetchone()[0]
    db.close()

    print(f"  {'Beliefs':30} {b:>6}  (light≥200, hectic≥600)")
    print(f"  {'avg_conf':30} {c:.3f}  (light≥0.50, hectic≥0.55)")
    print(f"  {'Usable reflections':30} {r:>6}  (light≥500, hectic≥1500)")

    if b >= 600 and c >= 0.55 and r >= 1500:
        ok("Training trigger", "HECTIC READY")
    elif b >= 200 and c >= 0.50 and r >= 500:
        ok("Training trigger", "LIGHT READY")
    else:
        gaps = []
        if b < 200:  gaps.append(f"beliefs {b}/200")
        if c < 0.50: gaps.append(f"conf {c:.2f}/0.50")
        if r < 500:  gaps.append(f"reflections {r}/500")
        warn("Training trigger", f"not ready — need: {', '.join(gaps)}")

    pairs = Path.home() / 'Desktop/nex/nex_training_pairs.json'
    if pairs.exists():
        try:
            d = json.loads(pairs.read_text())
            ok("Training pairs file", f"{len(d)} pairs")
        except:
            warn("Training pairs file", "invalid JSON")
    else:
        warn("Training pairs file", "not generated")

except Exception as e:
    fail("Training readiness", str(e))

# ── 11. LORA ADAPTER ─────────────────────────────────────────
section("11. LORA ADAPTER")
lora   = Path.home() / 'Desktop/nex/nex_lora.gguf'
adpt   = Path.home() / 'Desktop/nex/nex_adapter'
mfile  = Path.home() / 'Desktop/nex/Modelfile.nex'

if lora.exists():  ok("nex_lora.gguf",  f"{lora.stat().st_size//1024//1024}MB")
else:              fail("nex_lora.gguf", "missing")

if adpt.exists():  ok("nex_adapter/",   f"{len(list(adpt.glob('*')))} files")
else:              warn("nex_adapter/",  "missing")

if mfile.exists(): ok("Modelfile.nex",  "present")
else:              fail("Modelfile.nex", "missing")

# ── 12. O201 WINDOW ──────────────────────────────────────────
section("12. OBSERVATION WINDOW (O201)")
obs = CFG / 'observation.json'
if obs.exists():
    try:
        data = json.loads(obs.read_text())
        started = data.get('started') or data.get('start_time') or data.get('timestamp')
        if started:
            start_dt  = datetime.fromisoformat(str(started)[:19])
            end_dt    = start_dt + timedelta(hours=48)
            remaining = end_dt - datetime.now()
            if remaining.total_seconds() > 0:
                hrs = remaining.total_seconds() / 3600
                warn("O201 window", f"ACTIVE — {hrs:.1f}h remaining (ends {end_dt.strftime('%b %d %H:%M')})")
            else:
                ok("O201 window", f"COMPLETE — ended {abs(int(remaining.total_seconds()/3600))}h ago")
        else:
            ok("O201 observation.json", "exists")
    except Exception as e:
        warn("O201 observation.json", f"unreadable: {e}")
else:
    warn("O201 observation.json", "not found")

# ── SUMMARY ───────────────────────────────────────────────────
section("AUDIT SUMMARY")
total  = len(results)
n_ok   = sum(1 for r in results if r[0] == 'OK')
n_warn = sum(1 for r in results if r[0] == 'WARN')
n_fail = sum(1 for r in results if r[0] == 'FAIL')

print(f"\n  Total : {total}  |  {GREEN}OK: {n_ok}{RESET}  |  {YELLOW}WARN: {n_warn}{RESET}  |  {RED}FAIL: {n_fail}{RESET}")

if n_fail == 0 and n_warn <= 3:
    print(f"\n  {GREEN}{BOLD}★  NEX IS HEALTHY{RESET}\n")
elif n_fail == 0:
    print(f"\n  {YELLOW}{BOLD}◆  NEX OK WITH WARNINGS{RESET}\n")
else:
    print(f"\n  {RED}{BOLD}✗  NEX HAS ISSUES{RESET}")
    print(f"\n  {RED}Failures:{RESET}")
    for r in results:
        if r[0] == 'FAIL':
            print(f"    {RED}✗{RESET} {r[1]}: {r[2]}")
    print()
