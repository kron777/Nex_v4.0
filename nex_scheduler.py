#!/usr/bin/env python3
"""
nex_scheduler.py — NEX Tier 5 Scheduler v1.1
- Scheduled overnight domain saturation
- Cross-domain belief synthesis
- Belief export (JSON / CSV)
Runs as a standalone daemon alongside nex_api.py and nex_dashboard.py.

v1.1 changes:
  - Fixed saturation window logic: ran_today now checks window date not 24h
  - /scheduler/trigger and /scheduler/config POST require X-Admin-Secret
  - Added /scheduler/trigger job="refiner" option
  - datetime.utcnow() replaced with timezone-aware _now()/_now_iso()
  - Saturation prioritises empty/lowest domains first
  - domain_status in /scheduler/status now shows gap + done flag
"""
import os, sys, json, time, sqlite3, csv, io, threading, logging
from datetime import datetime, timedelta, timezone
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
DB_PATH     = Path("~/.config/nex/nex.db").expanduser()
SCHED_PATH  = Path("~/.config/nex/scheduler.json").expanduser()
EXPORT_PATH = Path("~/.config/nex/exports/").expanduser()

try:
    from flask import Flask, jsonify, request, Response
    from flask_cors import CORS
except ImportError:
    os.system(f"{sys.executable} -m pip install flask flask-cors --quiet")
    from flask import Flask, jsonify, request, Response
    from flask_cors import CORS

EXPORT_PORT  = 7825
ADMIN_SECRET = os.environ.get("NEX_ADMIN_SECRET", "nex-admin-2026")

app = Flask("nex_scheduler")
CORS(app)

# ── UTC helpers ────────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)

def _now_iso() -> str:
    return _now().isoformat()

def _local_hour() -> int:
    return datetime.now().hour  # local time for overnight window

# ── Admin auth ────────────────────────────────────────────────────────────────
def _is_admin() -> bool:
    secret = (request.headers.get("X-Admin-Secret")
              or request.args.get("admin_secret")
              or (request.get_json(silent=True) or {}).get("admin_secret"))
    return secret == ADMIN_SECRET

# ── DB helpers ────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def db_scalar(sql, params=()):
    try:
        conn = get_db()
        val  = conn.execute(sql, params).fetchone()[0]
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

def _domain_counts(domains: list) -> dict:
    return {d: db_scalar("SELECT COUNT(*) FROM beliefs WHERE topic = ?", (d,))
            for d in domains}

# ── LLM call ──────────────────────────────────────────────────────────────────
def llm(prompt: str, system: str = "", max_tokens: int = 300,
        temperature: float = 0.7) -> str:
    try:
        import requests as req
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            r = req.post("http://localhost:11434/api/chat", json={
                "model":   "mistral-nex",
                "messages": messages,
                "stream":  False,
                "options": {"num_predict": max_tokens, "temperature": temperature}
            }, timeout=60)
            if r.status_code == 200:
                return r.json().get("message", {}).get("content", "").strip()
        except:
            pass

        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        r = req.post("http://localhost:8080/completion", json={
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
        "enabled":           True,
        "start_hour":        2,
        "end_hour":          6,
        "target_per_domain": 200,
        "domains": ["finance","legal","climate","cardiology","oncology","neuroscience","free_will","machine_learning","alignment","ai"],
        "last_run":          None
    },
    "synthesis": {
        "enabled":           True,
        "interval_hours":    4,
        "pairs_per_run":     5,
        "min_confidence":    0.7,
        "last_run":          None,
        "total_synthesized": 0
    },
    "status":     "idle",
    "jobs_run":   0,
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
        "What is a key principle in cognitive neuroscience and memory formation?",
        "How does neuroplasticity enable learning and recovery from brain injury?",
        "Explain the role of the hippocampus in memory consolidation.",
        "What is the blood-brain barrier and why is it clinically important?",
        "Describe how dopamine pathways relate to reward, motivation and addiction.",
        "What are cortical oscillations and what cognitive functions do they support?",
        "Explain how sleep contributes to memory consolidation and synaptic homeostasis.",
        "What is the default mode network and when is it most active?",
        "Describe the role of mirror neurons in social cognition and empathy.",
        "How do action potentials propagate and what determines conduction velocity?",
        "What is the relationship between the amygdala and emotional memory?",
        "Explain the concept of neural pruning during development.",
        "What causes white matter degradation in aging and neurodegenerative disease?",
        "Describe the role of the prefrontal cortex in executive function.",
        "How does the cerebellum contribute to motor learning and timing?",
        "What is the gut-brain axis and how does it affect cognition and mood?",
        "Explain the role of GABA and glutamate in excitation-inhibition balance.",
        "What are the key mechanisms of neuroinflammation?",
        "Describe how optogenetics has advanced our understanding of neural circuits.",
        "What is predictive coding and how does it relate to perception?",
        "Explain the differences between episodic, semantic and procedural memory.",
    ],
    "free_will": [
        "Explain the compatibilist position on free will and determinism.",
        "What is the hard problem of free will and why does it matter?",
        "Describe how neuroscience has challenged traditional notions of free will.",
        "What is libertarian free will and what are its main philosophical problems?",
        "Explain how quantum indeterminacy relates to debates about free will.",
        "What is the difference between hard determinism and soft determinism?",
        "Describe the role of consciousness in decision-making and free will.",
        "What is the Frankfurt cases argument and what does it show about moral responsibility?",
        "Explain how the Libet experiments challenged our understanding of voluntary action.",
        "What is agent causation theory and how does it differ from event causation?",
    ],
    "alignment": [
        "Explain a key concept in AI alignment and corrigibility.",
        "What is the control problem in AI safety and why is it hard?",
        "Describe an important insight about value alignment in AI systems.",
        "What is inner alignment and how does it differ from outer alignment?",
        "Explain the role of interpretability in AI alignment research.",
        "What is mesa-optimisation and why does it matter for AI safety?",
        "Describe the orthogonality thesis and its implications for AI.",
        "What is the instrumental convergence thesis?",
        "Explain how RLHF attempts to solve the alignment problem.",
        "What is deceptive alignment and why is it a concern?",
    ],
    "machine_learning": [
        "Explain the bias-variance tradeoff in machine learning models.",
        "Describe the key principles behind gradient descent optimisation.",
        "What is overfitting and what techniques prevent it?",
        "Explain the difference between supervised, unsupervised and reinforcement learning.",
        "What is the curse of dimensionality and how does it affect ML models?",
        "Describe how backpropagation works in neural networks.",
        "What is attention mechanism and why did it revolutionise sequence modelling?",
        "Explain the role of regularisation in preventing model overfitting.",
        "What is transfer learning and why is it powerful in practice?",
        "Describe the key differences between generative and discriminative models.",
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


def saturate_domain(domain: str, target: int = 200, force: bool = False) -> int:
    current = db_scalar("SELECT COUNT(*) FROM beliefs WHERE topic = ?", (domain,))
    needed  = max(0, target - current)
    if needed == 0:
        log.info(f"Domain '{domain}' already at target ({current} beliefs)")
        return 0

    log.info(f"Saturating '{domain}': {current} → {target} ({needed} needed)")
    prompts      = DOMAIN_PROMPTS.get(domain, [])
    if not prompts:
        log.warning(f"No prompts defined for domain '{domain}'")
        return 0

    injected     = 0
    prompt_idx   = 0
    attempts     = 0
    max_attempts = needed * 3

    while injected < needed and attempts < max_attempts:
        prompt = prompts[prompt_idx % len(prompts)]
        prompt_idx += 1
        attempts   += 1

        result = llm(prompt, system=DOMAIN_SYSTEM, max_tokens=200, temperature=0.8)
        # Guard: strip anything after a double newline
        if result and chr(10)+chr(10) in result:
            result = result[:result.index(chr(10)+chr(10))].strip()
        if result and len(result) > 30 and len(result) < 400:
            ok = inject_belief(
                topic=domain,
                content=result,
                confidence=0.78,
                source="scheduler_saturation"
            )
            if ok:
                injected += 1
                if injected % 10 == 0:
                    log.info(f"  [{domain}] {injected}/{needed} injected")
            time.sleep(0.5)
        else:
            time.sleep(1)

    log.info(f"Domain '{domain}' saturation complete: +{injected} beliefs")
    return injected


def _ran_in_window_today(last_run_iso: str, start_hour: int, end_hour: int) -> bool:
    """
    True only if last_run falls within today's local saturation window hours.
    Prevents a daytime manual run from blocking tonight's 02:00-06:00 window.
    """
    if not last_run_iso:
        return False
    try:
        last = datetime.fromisoformat(last_run_iso)
        now  = datetime.now()
        return last.date() == now.date() and start_hour <= last.hour < end_hour
    except Exception:
        return False


def run_saturation_job(force: bool = False):
    """
    Run saturation for all under-target domains, lowest-count first.
    force=True skips the time-window check (used for manual triggers).
    Auto-disables saturation when all domains hit target to prevent
    quality degradation from excess fresh beliefs with rc=0/use=0.
    """
    sched  = load_schedule()
    config = sched.get("saturation", {})
    if not config.get("enabled", True):
        return

    target  = config.get("target_per_domain", 200)
    domains = config.get("domains", [])

    update_schedule({"status": "saturating"})
    log.info(f"=== Saturation job started (force={force}) — target {target}/domain ===")

    # Sort: empty domains first, then by ascending count
    counts          = _domain_counts(domains)
    domains_sorted  = sorted(
        [d for d in domains if counts.get(d, 0) < target],
        key=lambda d: counts.get(d, 0)
    )

    if not domains_sorted:
        log.info("All domains already at target — nothing to do")
        # Auto-disable saturation to prevent quality degradation
        with _sched_lock:
            sched = load_schedule()
            sched["saturation"]["enabled"] = False
            sched["saturation"]["disabled_reason"] = "all_domains_at_target"
            sched["saturation"]["last_run"] = _now_iso()
            sched["status"] = "idle"
            save_schedule(sched)
        log.info("Saturation auto-disabled — re-enable via /scheduler/config when new domains added")
        return
    else:
        log.info(f"Priority order: {[(d, counts[d]) for d in domains_sorted]}")

    total = 0
    for domain in domains_sorted:
        if not force:
            hour  = _local_hour()
            start = config.get("start_hour", 2)
            end   = config.get("end_hour",   6)
            if not (start <= hour < end):
                log.info(f"Outside saturation window ({start}–{end}h), stopping")
                break
        total += saturate_domain(domain, target)

    with _sched_lock:
        sched = load_schedule()
        sched["saturation"]["last_run"] = _now_iso()
        sched["jobs_run"] = sched.get("jobs_run", 0) + 1
        sched["status"]   = "idle"
        save_schedule(sched)

    log.info(f"=== Saturation complete: +{total} beliefs total ===")
    # Run annealing cycles after saturation to consolidate new beliefs
    try:
        from nex_annealing import run_annealing
        log.info("Running post-saturation annealing (20 cycles)...")
        ann_stats = run_annealing(n_cycles=20)
        log.info(f"Annealing complete: +{ann_stats['boosted']} boosted, {ann_stats['crystallised']} crystals")
    except Exception as _ae:
        log.warning(f"Annealing error: {_ae}")

    # Auto-refine after saturation
    try:
        from nex_belief_refiner import refine_corpus
        _ref = refine_corpus(dry_run=False, verbose=False)
        log.info(f"[refiner] dedup={_ref['dedup']['deduped']} "
                 f"boost={_ref['boost']['boosted']} "
                 f"decay={_ref['decay']['decayed']} "
                 f"rescore={_ref['rescore']['rescored']}")
    except Exception as _re:
        log.warning(f"[refiner] auto-refine failed: {_re}")


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-DOMAIN SYNTHESIS
# ══════════════════════════════════════════════════════════════════════════════
SYNTHESIS_SYSTEM = """You are NEX, synthesizing knowledge across domains.
Given two beliefs from different fields, generate ONE novel insight that connects them.
The insight must be genuinely cross-domain — not a restatement of either belief.
Respond with a single clear sentence or two. No preamble."""

def get_synthesis_candidates(min_confidence: float = 0.7) -> list:
    return db_query("""
        SELECT id, topic, content, confidence
        FROM beliefs
        WHERE confidence >= ? AND LENGTH(content) > 50
        ORDER BY RANDOM()
        LIMIT 200
    """, (min_confidence,))

def find_synthesis_pairs(candidates: list, n: int = 5) -> list:
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
    pairs, seen, attempts = [], set(), 0
    while len(pairs) < n and attempts < 100:
        attempts += 1
        t1, t2 = random.sample(topics, 2)
        if (t1, t2) in seen or (t2, t1) in seen:
            continue
        seen.add((t1, t2))
        pairs.append((random.choice(by_topic[t1]), random.choice(by_topic[t2])))
    return pairs

def synthesize_pair(b1: dict, b2: dict) -> str:
    prompt = (
        f"Domain A ({b1['topic']}):\n{b1['content']}\n\n"
        f"Domain B ({b2['topic']}):\n{b2['content']}\n\n"
        f"What novel cross-domain insight connects these two ideas?"
    )
    return llm(prompt, system=SYNTHESIS_SYSTEM, max_tokens=200, temperature=0.75).strip()

def run_synthesis_job():
    sched  = load_schedule()
    config = sched.get("synthesis", {})
    if not config.get("enabled", True):
        return

    n_pairs     = config.get("pairs_per_run", 5)
    min_conf    = config.get("min_confidence", 0.7)
    total_synth = config.get("total_synthesized", 0)

    update_schedule({"status": "synthesizing"})
    log.info(f"=== Cross-domain synthesis job: {n_pairs} pairs ===")

    candidates = get_synthesis_candidates(min_conf)
    if len(candidates) < 10:
        log.warning("Not enough high-confidence beliefs for synthesis")
        update_schedule({"status": "idle"})
        return

    pairs    = find_synthesis_pairs(candidates, n=n_pairs)
    injected = 0

    for b1, b2 in pairs:
        synthesis = synthesize_pair(b1, b2)
        if synthesis and len(synthesis) > 40:
            ok = inject_belief(
                topic=f"{b1['topic']}+{b2['topic']}",
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
        sched["synthesis"]["last_run"]          = _now_iso()
        sched["synthesis"]["total_synthesized"] = total_synth + injected
        sched["jobs_run"] = sched.get("jobs_run", 0) + 1
        sched["status"]   = "idle"
        save_schedule(sched)

    log.info(f"=== Synthesis complete: +{injected} cross-domain beliefs ===")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN SCHEDULER LOOP
# ══════════════════════════════════════════════════════════════════════════════
def scheduler_loop():
    log.info("Scheduler loop started")
    update_schedule({"started_at": _now_iso(), "status": "idle"})

    while True:
        try:
            sched = load_schedule()
            now   = _now()
            hour  = _local_hour()

            # ── Overnight saturation ──────────────────────────────────────
            sat = sched.get("saturation", {})
            if sat.get("enabled", True):
                start = sat.get("start_hour", 2)
                end   = sat.get("end_hour",   6)
                last  = sat.get("last_run")

                in_window   = start <= hour < end
                ran_tonight = _ran_in_window_today(last, start, end)

                if in_window and not ran_tonight:
                    log.info(f"Overnight window active ({hour}h) — launching saturation")
                    threading.Thread(
                        target=run_saturation_job,
                        daemon=True, name="saturation-job"
                    ).start()

            # ── Native opinions refresh ──────────────────────────────────
            op = sched.get("opinions", {})
            if op.get("enabled", True):
                interval = op.get("interval_hours", 6)
                last     = op.get("last_run")
                due      = True
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        due = (now - last_dt).total_seconds() >= interval * 3600
                    except Exception:
                        due = True
                if due:
                    def _run_opinions():
                        try:
                            from nex_native_opinions import update_all_opinions
                            update_all_opinions(verbose=False)
                            log.info("Native opinions refreshed")
                        except Exception as e:
                            log.error(f"Opinions job error: {e}")
                    threading.Thread(
                        target=_run_opinions,
                        daemon=True, name="opinions-job"
                    ).start()
                    with _sched_lock:
                        sched = load_schedule()
                        sched.setdefault("opinions", {})["last_run"] = _now_iso()
                        save_schedule(sched)

            # ── Cross-domain synthesis ────────────────────────────────────
            syn = sched.get("synthesis", {})
            if syn.get("enabled", True):
                interval = syn.get("interval_hours", 4)
                last     = syn.get("last_run")
                due      = True
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        due = (now - last_dt).total_seconds() >= interval * 3600
                    except Exception:
                        due = True
                if due:
                    log.info("Synthesis job due — launching")
                    threading.Thread(
                        target=run_synthesis_job,
                        daemon=True, name="synthesis-job"
                    ).start()

        except Exception as e:
            log.error(f"Scheduler loop error: {e}")

        time.sleep(60)

# ══════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/export/beliefs")
def export_beliefs():
    fmt      = request.args.get("format", "json").lower()
    topic    = request.args.get("topic")
    source   = request.args.get("source")
    min_conf = float(request.args.get("min_conf", 0.0))
    limit    = request.args.get("limit")

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
        out    = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=["id","topic","content","confidence","source"])
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            out.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=nex_beliefs.csv"}
        )
    return jsonify({
        "exported_at": _now_iso(),
        "count":       len(rows),
        "filters":     {"topic": topic, "source": source, "min_conf": min_conf},
        "beliefs":     rows
    })

@app.route("/export/synthesis")
def export_synthesis():
    rows = db_query(
        "SELECT id, topic, content, confidence, source FROM beliefs "
        "WHERE source LIKE 'synthesis:%' ORDER BY id DESC"
    )
    return jsonify({
        "exported_at":       _now_iso(),
        "count":             len(rows),
        "synthesis_beliefs": rows
    })

@app.route("/scheduler/status")
def scheduler_status():
    sched   = load_schedule()
    domains = sched.get("saturation", {}).get("domains", [])
    counts  = _domain_counts(domains)
    target  = sched["saturation"].get("target_per_domain", 200)

    domain_status = {
        d: {
            "count": counts[d],
            "gap":   max(0, target - counts[d]),
            "done":  counts[d] >= target
        }
        for d in domains
    }

    return jsonify({
        "status":     sched.get("status", "idle"),
        "jobs_run":   sched.get("jobs_run", 0),
        "started_at": sched.get("started_at"),
        "saturation": {
            "enabled":       sched["saturation"]["enabled"],
            "window":        f"{sched['saturation']['start_hour']}:00–{sched['saturation']['end_hour']}:00",
            "target":        target,
            "last_run":      sched["saturation"]["last_run"],
            "domain_counts": counts,
            "domain_status": domain_status,
        },
        "synthesis": {
            "enabled":           sched["synthesis"]["enabled"],
            "interval_hours":    sched["synthesis"]["interval_hours"],
            "total_synthesized": sched["synthesis"]["total_synthesized"],
            "last_run":          sched["synthesis"]["last_run"]
        },
        "total_beliefs": db_scalar("SELECT COUNT(*) FROM beliefs"),
        "timestamp":     _now_iso()
    })

@app.route("/scheduler/trigger", methods=["POST"])
def scheduler_trigger():
    """Trigger a job manually. Requires X-Admin-Secret header."""
    if not _is_admin():
        return jsonify({"error": "Admin access denied"}), 403

    body = request.get_json(silent=True) or {}
    job  = body.get("job", "synthesis")

    if job == "saturation":
        threading.Thread(
            target=run_saturation_job, kwargs={"force": True},
            daemon=True, name="saturation-manual"
        ).start()
        return jsonify({"triggered": "saturation", "force": True, "timestamp": _now_iso()})

    elif job == "synthesis":
        threading.Thread(
            target=run_synthesis_job,
            daemon=True, name="synthesis-manual"
        ).start()
        return jsonify({"triggered": "synthesis", "timestamp": _now_iso()})

    elif job == "refiner":
        def _run_refiner():
            try:
                from nex_belief_refiner import refine_corpus
                result = refine_corpus(dry_run=False, verbose=False)
                log.info(f"[refiner] manual run complete: {result}")
            except Exception as e:
                log.error(f"[refiner] manual trigger error: {e}")
        threading.Thread(target=_run_refiner, daemon=True, name="refiner-manual").start()
        return jsonify({"triggered": "refiner", "timestamp": _now_iso()})

    elif job == "arxiv_seed":
        domain = body.get("domain")   # optional — None seeds all three
        def _run_arxiv():
            try:
                from nex_arxiv_seeder import scheduler_hook
                result = scheduler_hook(domains=[domain] if domain else None)
                log.info(f"[arxiv] seed complete: {result}")
            except Exception as e:
                log.error(f"[arxiv] seed error: {e}")
        threading.Thread(target=_run_arxiv, daemon=True, name="arxiv-seed").start()
        return jsonify({
            "triggered": "arxiv_seed",
            "domain":    domain or "all",
            "timestamp": _now_iso()
        })

    else:
        return jsonify({"error": f"Unknown job: '{job}'. Use: saturation|synthesis|refiner|arxiv_seed"}), 400

@app.route("/scheduler/config", methods=["GET", "POST"])
def scheduler_config():
    if request.method == "GET":
        return jsonify(load_schedule())
    if not _is_admin():
        return jsonify({"error": "Admin access denied"}), 403
    body = request.get_json(silent=True) or {}
    with _sched_lock:
        sched = load_schedule()
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

    if not SCHED_PATH.exists():
        save_schedule(DEFAULT_SCHEDULE)
        log.info("Scheduler config initialized")

    print(f"  NEX Scheduler v1.1")
    print(f"  Export API : http://localhost:{EXPORT_PORT}")
    print(f"  Saturation : 02:00–06:00 local, target 200/domain (empties first)")
    print(f"  Synthesis  : every 4 hours")
    print(f"  Trigger    : POST /scheduler/trigger (requires X-Admin-Secret)")
    print(f"  Log        : {LOG_PATH}")

    threading.Thread(target=scheduler_loop, daemon=True, name="scheduler-loop").start()
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=EXPORT_PORT, debug=False, use_reloader=False),
        daemon=True, name="export-api"
    ).start()

    log.info(f"NEX Scheduler v1.1 running — export API on port {EXPORT_PORT}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  [Scheduler] Shutting down.")
