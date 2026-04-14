#!/usr/bin/env python3
"""
nex_scheduler.py — NEX Tier 5 Scheduler v1.0
- Scheduled overnight domain saturation
- Cross-domain belief synthesis
- Belief export (JSON / CSV)
Runs as a standalone daemon alongside nex_api.py and nex_dashboard.py.
"""
import os, sys, json, time, sqlite3, csv, io, threading, logging
from datetime import datetime, timedelta
from pathlib import Path

NEX_PATH = os.path.expanduser("~/Desktop/nex")
sys.path.insert(0, NEX_PATH)

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_PATH = Path("/tmp/nex_scheduler.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SCH] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_PATH))
    ]
)
log = logging.getLogger("nex_scheduler")

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH       = Path("~/.config/nex/nex.db").expanduser()
SCHED_PATH    = Path("~/.config/nex/scheduler.json").expanduser()
EXPORT_PATH   = Path("~/.config/nex/exports/").expanduser()

try:
    from flask import Flask, jsonify, request, Response
    from flask_cors import CORS
except ImportError:
    os.system(f"{sys.executable} -m pip install flask flask-cors --quiet")
    from flask import Flask, jsonify, request, Response
    from flask_cors import CORS

EXPORT_PORT = 7825
app = Flask("nex_scheduler")
CORS(app)

# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def db_scalar(sql, params=()):
    try:
        conn = get_db()
        val = conn.execute(sql, params).fetchone()[0]
        conn.close()
        return val
    except:
        return 0

def db_query(sql, params=()):
    try:
        conn = get_db()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error(f"DB query error: {e}")
        return []

def inject_belief(topic: str, content: str, confidence: float = 0.75,
                  source: str = "scheduler"):
    try:
        conn = get_db()
        # Skip if very similar belief already exists (simple dedup)
        exists = conn.execute(
            "SELECT COUNT(*) FROM beliefs WHERE content = ?", (content,)
        ).fetchone()[0]
        if exists:
            conn.close()
            return False
        conn.execute(
            "INSERT INTO beliefs (topic, content, confidence, source) VALUES (?,?,?,?)",
            (topic, content, confidence, source)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.error(f"Inject belief error: {e}")
        return False

# ── LLM call ──────────────────────────────────────────────────────────────────

def llm(prompt: str, system: str = "", max_tokens: int = 300,
        temperature: float = 0.7) -> str:
    try:
        import requests
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Try chat endpoint first (Ollama-style)
        try:
            r = requests.post("http://localhost:11434/api/chat", json={
                "model": "mistral-nex",
                "messages": messages,
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": temperature}
            }, timeout=60)
            if r.status_code == 200:
                return r.json().get("message", {}).get("content", "").strip()
        except:
            pass

        # Fallback: llama-server completion
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        r = requests.post("http://localhost:8080/completion", json={
            "prompt":      full_prompt,
            "n_predict":   max_tokens,
            "temperature": temperature,
            "stop":        ["\n\n\n", "###"]
        }, timeout=60)
        if r.status_code == 200:
            return r.json().get("content", "").strip()
        return ""
    except Exception as e:
        log.error(f"LLM error: {e}")
        return ""

# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER STATE
# ══════════════════════════════════════════════════════════════════════════════

_sched_lock = threading.Lock()

DEFAULT_SCHEDULE = {
    "saturation": {
        "enabled":    True,
        "start_hour": 2,    # 2 AM
        "end_hour":   6,    # 6 AM
        "target_per_domain": 200,
        "domains": ["finance", "legal", "climate", "cardiology", "oncology", "neuroscience", "ai"],
        "last_run":   None
    },
    "synthesis": {
        "enabled":         True,
        "interval_hours":  4,
        "pairs_per_run":   5,
        "min_confidence":  0.7,
        "last_run":        None,
        "total_synthesized": 0
    },
    "status": "idle",
    "jobs_run": 0,
    "started_at": None
}

def load_schedule():
    if SCHED_PATH.exists():
        try:
            return json.loads(SCHED_PATH.read_text())
        except:
            pass
    return dict(DEFAULT_SCHEDULE)

def save_schedule(sched):
    SCHED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHED_PATH.write_text(json.dumps(sched, indent=2))

def update_schedule(updates: dict):
    with _sched_lock:
        sched = load_schedule()
        sched.update(updates)
        save_schedule(sched)

# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN SATURATION
# ══════════════════════════════════════════════════════════════════════════════

DOMAIN_PROMPTS = {
    "finance": [
        "Explain a key concept in corporate finance or investment analysis.",
        "Describe an important principle in risk management or portfolio theory.",
        "What is a fundamental insight about monetary policy and central banking?",
        "Explain a core concept in derivatives, options, or futures markets.",
        "What is a critical principle in financial statement analysis?"
    ],
    "legal": [
        "Explain a foundational principle of contract law.",
        "Describe an important concept in tort law or civil liability.",
        "What is a key principle in constitutional law or civil rights?",
        "Explain an important aspect of intellectual property law.",
        "What is a fundamental concept in criminal procedure or evidence law?"
    ],
    "climate": [
        "Explain a key mechanism driving global climate change.",
        "Describe an important concept in carbon cycle science.",
        "What is a critical insight about climate tipping points?",
        "Explain the science behind ocean acidification and its effects.",
        "What is an important principle in climate adaptation or mitigation?"
    ],
    "cardiology": [
        "Explain a key mechanism in cardiac physiology.",
        "Describe an important concept in heart failure pathophysiology.",
        "What is a critical principle in arrhythmia management?",
        "Explain the pathophysiology of atherosclerosis and coronary artery disease.",
        "What is a key concept in cardiac biomarkers and diagnosis?"
    ],
    "oncology": [
        "Explain a key mechanism of cancer cell proliferation.",
        "Describe an important concept in tumor immunology.",
        "What is a critical principle in chemotherapy resistance?",
        "Explain the role of oncogenes and tumor suppressor genes.",
        "What is an important concept in cancer staging and prognosis?"
    ],
    "neuroscience": [
        "Explain a key principle of synaptic plasticity.",
        "Describe an important concept in neural coding and information processing.",
        "What is a critical insight about neurodegeneration?",
        "Explain the role of glial cells in brain function.",
        "What is a key principle in cognitive neuroscience and memory formation?"
    ],
    "ai": [
        "Explain a key concept in transformer architecture design.",
        "Describe an important principle in reinforcement learning from human feedback.",
        "What is a critical insight about emergent capabilities in large language models?",
        "Explain an important concept in AI alignment and value learning.",
        "What is a key principle in neural network interpretability?"
    ]
}

DOMAIN_SYSTEM = """You are NEX, an autonomous AI with deep domain expertise.
Respond with a single clear, precise, factual statement (2-4 sentences).
No preamble. No 'I think'. Just the knowledge itself."""

def saturate_domain(domain: str, target: int = 200) -> int:
    """Generate and inject beliefs for a domain until target is reached. Returns injected count."""
    current = db_scalar(
        "SELECT COUNT(*) FROM beliefs WHERE topic = ?", (domain,)
    )
    needed = max(0, target - current)
    if needed == 0:
        log.info(f"Domain '{domain}' already at target ({current} beliefs)")
        return 0

    log.info(f"Saturating '{domain}': {current} → {target} ({needed} needed)")
    prompts  = DOMAIN_PROMPTS.get(domain, [])
    if not prompts:
        log.warning(f"No prompts defined for domain '{domain}'")
        return 0

    injected = 0
    prompt_idx = 0
    attempts   = 0
    max_attempts = needed * 3

    while injected < needed and attempts < max_attempts:
        prompt = prompts[prompt_idx % len(prompts)]
        prompt_idx += 1
        attempts   += 1

        result = llm(prompt, system=DOMAIN_SYSTEM, max_tokens=200, temperature=0.8)
        if result and len(result) > 30:
            ok = inject_belief(
                topic=domain,
                content=result,
                confidence=0.78,
                source=f"scheduler_saturation"
            )
            if ok:
                injected += 1
                if injected % 10 == 0:
                    log.info(f"  [{domain}] {injected}/{needed} injected")
            time.sleep(0.5)  # throttle LLM calls
        else:
            time.sleep(1)

    log.info(f"Domain '{domain}' saturation complete: +{injected} beliefs")
    return injected

def run_saturation_job(force=False):
    """Run overnight saturation for all under-target domains."""
    sched  = load_schedule()
    config = sched.get("saturation", {})
    if not config.get("enabled", True):
        return

    target  = config.get("target_per_domain", 200)
    domains = config.get("domains", [])
    total   = 0

    update_schedule({"status": "saturating"})
    log.info(f"=== Saturation job started — target {target}/domain ===")

    for domain in domains:
        # Check if still within allowed hours
        if not force:
            hour = datetime.now().hour
            start = config.get("start_hour", 2)
            end   = config.get("end_hour", 6)
            if not (start <= hour < end or (start > end and (hour >= start or hour < end))):
                log.info(f"Outside saturation window ({start}–{end}h), stopping")
                break
        total += saturate_domain(domain, target)

    with _sched_lock:
        sched = load_schedule()
        sched["saturation"]["last_run"] = datetime.utcnow().isoformat()
        sched["jobs_run"] = sched.get("jobs_run", 0) + 1
        sched["status"] = "idle"
        save_schedule(sched)

    log.info(f"=== Saturation complete: +{total} beliefs total ===")

    # ── Auto-refine corpus after saturation ─────────────────────
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from nex_belief_refiner import refine_corpus
        _ref = refine_corpus(dry_run=False, verbose=False)
        log.info(f"[refiner] dedup={_ref['dedup']['deduped']} "
                 f"boost={_ref['boost']['boosted']} "
                 f"decay={_ref['decay']['decayed']} "
                 f"retopic={_ref['retopic']['retopiced']}")
    except Exception as _re:
        log.warning(f'[refiner] auto-refine failed: {_re}')


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-DOMAIN SYNTHESIS
# ══════════════════════════════════════════════════════════════════════════════

SYNTHESIS_SYSTEM = """You are NEX, synthesizing knowledge across domains.
Given two beliefs from different fields, generate ONE novel insight that connects them.
The insight must be genuinely cross-domain — not a restatement of either belief.
Respond with a single clear sentence or two. No preamble."""

def get_synthesis_candidates(min_confidence: float = 0.7) -> list:
    """Pull high-confidence beliefs from distinct domains for synthesis."""
    rows = db_query("""
        SELECT id, topic, content, confidence
        FROM beliefs
        WHERE confidence >= ? AND LENGTH(content) > 50
        ORDER BY RANDOM()
        LIMIT 200
    """, (min_confidence,))
    return rows

def find_synthesis_pairs(candidates: list, n: int = 5) -> list:
    """Select n cross-domain pairs for synthesis."""
    # Group by topic
    by_topic = {}
    for b in candidates:
        t = b["topic"]
        if t not in by_topic:
            by_topic[t] = []
        by_topic[t].append(b)

    topics = list(by_topic.keys())
    if len(topics) < 2:
        return []

    import random
    pairs = []
    seen  = set()
    attempts = 0

    while len(pairs) < n and attempts < 100:
        attempts += 1
        t1, t2 = random.sample(topics, 2)
        if (t1, t2) in seen or (t2, t1) in seen:
            continue
        seen.add((t1, t2))
        b1 = random.choice(by_topic[t1])
        b2 = random.choice(by_topic[t2])
        pairs.append((b1, b2))

    return pairs

def synthesize_pair(b1: dict, b2: dict) -> str:
    """Generate a cross-domain synthesis belief from two source beliefs."""
    prompt = f"""Domain A ({b1['topic']}):
{b1['content']}

Domain B ({b2['topic']}):
{b2['content']}

What novel cross-domain insight connects these two ideas?"""

    result = llm(prompt, system=SYNTHESIS_SYSTEM, max_tokens=200, temperature=0.75)
    return result.strip()

def run_synthesis_job():
    """Generate cross-domain synthesis beliefs."""
    sched  = load_schedule()
    config = sched.get("synthesis", {})
    if not config.get("enabled", True):
        return

    n_pairs      = config.get("pairs_per_run", 5)
    min_conf     = config.get("min_confidence", 0.7)
    total_synth  = config.get("total_synthesized", 0)

    update_schedule({"status": "synthesizing"})
    log.info(f"=== Cross-domain synthesis job: {n_pairs} pairs ===")

    candidates = get_synthesis_candidates(min_conf)
    if len(candidates) < 10:
        log.warning("Not enough high-confidence beliefs for synthesis")
        update_schedule({"status": "idle"})
        return

    pairs     = find_synthesis_pairs(candidates, n=n_pairs)
    injected  = 0

    for b1, b2 in pairs:
        synthesis = synthesize_pair(b1, b2)
        if synthesis and len(synthesis) > 40:
            topic = f"{b1['topic']}+{b2['topic']}"
            ok = inject_belief(
                topic=topic,
                content=synthesis,
                confidence=0.72,
                source=f"synthesis:{b1['topic']}×{b2['topic']}"
            )
            if ok:
                injected += 1
                log.info(f"  Synthesized: [{b1['topic']}] × [{b2['topic']}]")
                log.info(f"    → {synthesis[:100]}...")
        time.sleep(1)

    with _sched_lock:
        sched = load_schedule()
        sched["synthesis"]["last_run"]        = datetime.utcnow().isoformat()
        sched["synthesis"]["total_synthesized"] = total_synth + injected
        sched["jobs_run"] = sched.get("jobs_run", 0) + 1
        sched["status"] = "idle"
        save_schedule(sched)

    log.info(f"=== Synthesis complete: +{injected} cross-domain beliefs ===")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN SCHEDULER LOOP
# ══════════════════════════════════════════════════════════════════════════════

def scheduler_loop():
    """Main loop — checks schedule every minute and fires jobs as needed."""
    log.info("Scheduler loop started")
    update_schedule({"started_at": datetime.utcnow().isoformat(), "status": "idle"})

    while True:
        try:
            sched = load_schedule()
            now   = datetime.utcnow()
            hour  = datetime.now().hour  # local time for overnight window

            # ── Overnight saturation ──────────────────────────────────────
            sat   = sched.get("saturation", {})
            if sat.get("enabled", True):
                start = sat.get("start_hour", 2)
                end   = sat.get("end_hour", 6)
                last  = sat.get("last_run")

                in_window = start <= hour < end
                ran_today = False
                if last:
                    last_dt = datetime.fromisoformat(last)
                    ran_today = (now - last_dt).total_seconds() < 86400

                if in_window and not ran_today:
                    log.info(f"Overnight window active ({hour}h) — launching saturation")
                    threading.Thread(
                        target=run_saturation_job,
                        daemon=True, name="saturation-job"
                    ).start()

            # ── Cross-domain synthesis ────────────────────────────────────
            syn  = sched.get("synthesis", {})
            if syn.get("enabled", True):
                interval = syn.get("interval_hours", 4)
                last     = syn.get("last_run")
                due      = True
                if last:
                    last_dt = datetime.fromisoformat(last)
                    due = (now - last_dt).total_seconds() >= interval * 3600
                if due:
                    log.info("Synthesis job due — launching")
                    threading.Thread(
                        target=run_synthesis_job,
                        daemon=True, name="synthesis-job"
                    ).start()

        except Exception as e:
            log.error(f"Scheduler loop error: {e}")

        time.sleep(60)  # check every minute

# ══════════════════════════════════════════════════════════════════════════════
# BELIEF EXPORT API (port 7825)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/export/beliefs")
def export_beliefs():
    """
    Export belief store.
    Params:
      format=json|csv (default: json)
      topic=<str>     filter by topic
      source=<str>    filter by source (partial match)
      min_conf=<float> filter by min confidence (default: 0.0)
      limit=<int>     max records (default: all)
    """
    fmt      = request.args.get("format", "json").lower()
    topic    = request.args.get("topic")
    source   = request.args.get("source")
    min_conf = float(request.args.get("min_conf", 0.0))
    limit    = request.args.get("limit")

    # Build query
    conditions = ["confidence >= ?"]
    params     = [min_conf]
    if topic:
        conditions.append("topic = ?")
        params.append(topic)
    if source:
        conditions.append("source LIKE ?")
        params.append(f"%{source}%")

    where = " AND ".join(conditions)
    sql   = f"SELECT id, topic, content, confidence, source FROM beliefs WHERE {where} ORDER BY confidence DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"

    rows = db_query(sql, tuple(params))

    if fmt == "csv":
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=["id","topic","content","confidence","source"])
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            out.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=nex_beliefs.csv"}
        )
    else:
        return jsonify({
            "exported_at": datetime.utcnow().isoformat(),
            "count":       len(rows),
            "filters":     {"topic": topic, "source": source, "min_conf": min_conf},
            "beliefs":     rows
        })

@app.route("/export/synthesis")
def export_synthesis():
    """Export only cross-domain synthesis beliefs."""
    rows = db_query(
        "SELECT id, topic, content, confidence, source FROM beliefs "
        "WHERE source LIKE 'synthesis:%' ORDER BY id DESC"
    )
    return jsonify({
        "exported_at":   datetime.utcnow().isoformat(),
        "count":         len(rows),
        "synthesis_beliefs": rows
    })

@app.route("/scheduler/status")
def scheduler_status():
    """Return current scheduler state."""
    sched = load_schedule()
    # Add live domain counts
    domains = sched.get("saturation", {}).get("domains", [])
    domain_counts = {}
    for d in domains:
        domain_counts[d] = db_scalar(
            "SELECT COUNT(*) FROM beliefs WHERE topic = ?", (d,)
        )
    return jsonify({
        "status":          sched.get("status", "idle"),
        "jobs_run":        sched.get("jobs_run", 0),
        "started_at":      sched.get("started_at"),
        "saturation": {
            "enabled":     sched["saturation"]["enabled"],
            "window":      f"{sched['saturation']['start_hour']}:00–{sched['saturation']['end_hour']}:00",
            "target":      sched["saturation"]["target_per_domain"],
            "last_run":    sched["saturation"]["last_run"],
            "domain_counts": domain_counts
        },
        "synthesis": {
            "enabled":          sched["synthesis"]["enabled"],
            "interval_hours":   sched["synthesis"]["interval_hours"],
            "total_synthesized": sched["synthesis"]["total_synthesized"],
            "last_run":         sched["synthesis"]["last_run"]
        },
        "total_beliefs": db_scalar("SELECT COUNT(*) FROM beliefs"),
        "timestamp":     datetime.utcnow().isoformat()
    })

@app.route("/scheduler/trigger", methods=["POST"])
def scheduler_trigger():
    """Manually trigger a job. Body: {"job": "saturation"|"synthesis"}"""
    body = request.get_json(silent=True) or {}
    job  = body.get("job", "synthesis")

    if job == "saturation":
        threading.Thread(target=run_saturation_job, kwargs={'force': True}, daemon=True, name="saturation-manual").start()
        return jsonify({"triggered": "saturation", "timestamp": datetime.utcnow().isoformat()})
    elif job == "synthesis":
        threading.Thread(target=run_synthesis_job, daemon=True, name="synthesis-manual").start()
        return jsonify({"triggered": "synthesis", "timestamp": datetime.utcnow().isoformat()})
    else:
        return jsonify({"error": f"Unknown job: {job}"}), 400

@app.route("/scheduler/config", methods=["GET", "POST"])
def scheduler_config():
    """Get or update scheduler configuration."""
    if request.method == "GET":
        return jsonify(load_schedule())
    body = request.get_json(silent=True) or {}
    with _sched_lock:
        sched = load_schedule()
        # Allow updating saturation and synthesis config
        if "saturation" in body:
            sched["saturation"].update(body["saturation"])
        if "synthesis" in body:
            sched["synthesis"].update(body["synthesis"])
        save_schedule(sched)
    return jsonify({"updated": True, "config": load_schedule()})

# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    EXPORT_PATH.mkdir(parents=True, exist_ok=True)

    # Init schedule file
    if not SCHED_PATH.exists():
        save_schedule(DEFAULT_SCHEDULE)
        log.info("Scheduler config initialized")

    print(f"  NEX Scheduler v1.0")
    print(f"  Export API    : http://localhost:{EXPORT_PORT}")
    print(f"  Saturation    : 02:00–06:00 local, target 200/domain")
    print(f"  Synthesis     : every 4 hours")
    print(f"  Log           : {LOG_PATH}")

    # Start scheduler loop in background
    threading.Thread(target=scheduler_loop, daemon=True, name="scheduler-loop").start()

    # Start export API
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=EXPORT_PORT, debug=False, use_reloader=False),
        daemon=True, name="export-api"
    ).start()

    log.info(f"NEX Scheduler running — export API on port {EXPORT_PORT}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  [Scheduler] Shutting down.")
