#!/usr/bin/env python3
"""
nex_drain.py v4 — 3-process parallel crawler with absorb/digest cycle

Each worker is a separate process with its own Python interpreter,
asyncio event loop, and NexCrawler instance. WAL-mode SQLite handles
concurrent writes safely.

Usage:
  python3 nex_drain.py [N]   drain N cycles (default 10)
  --clear                    bypass 24hr cooldown cache
  --no-digest                skip opinion/tension/reflect synthesis
  --workers N                number of parallel crawlers (default 3)

Output per cycle:
  cycle 01 | reinforcement_learning(+12) + bayesian_inference(+12) + chinese_room(+12) = +36 | db=723 | 4.1s
"""
import nex_db_gatekeeper  # write-serialization + PRAGMA busy_timeout/WAL on every sqlite3.connect (fork workers inherit)
import sys, json, sqlite3, logging, inspect, traceback, time
import multiprocessing as mp
from pathlib import Path

# Must be at module level for multiprocessing to pickle correctly
logging.basicConfig(level=logging.WARNING, format="%(message)s")

NEX_DIR = Path(__file__).parent
sys.path.insert(0, str(NEX_DIR))
CFG = Path("~/.config/nex").expanduser()
DB  = CFG / "nex.db"

DIGEST_EVERY     = 3
ABSORB_CAP       = 60
DEFAULT_WORKERS  = 3

SEED_TOPICS = [
    # Wave 4 — fresh topics not yet in DB
    # Philosophy & logic
    ("modal logic possible worlds",          "philosophy"),
    ("phenomenology intentionality husserl", "philosophy"),
    ("enactivism embodied mind",             "philosophy"),
    ("extended mind thesis clark chalmers",  "philosophy"),
    ("autopoiesis maturana varela",          "complexity"),
    ("type theory dependent types",          "mathematics"),
    ("formal grammar chomsky hierarchy",     "mathematics"),
    ("paraconsistent logic dialethism",      "philosophy"),
    ("mereology part whole relations",       "philosophy"),
    ("philosophy of mathematics platonism",  "philosophy"),

    # Neuroscience & cognition
    ("default mode network self referential","neuroscience"),
    ("neurogenesis adult brain plasticity",  "neuroscience"),
    ("mirror neurons simulation theory",     "neuroscience"),
    ("cerebellum motor learning prediction", "neuroscience"),
    ("prefrontal cortex executive function", "neuroscience"),
    ("hippocampus spatial navigation memory","neuroscience"),
    ("dopamine reward prediction error",     "neuroscience"),
    ("attention schema theory consciousness","neuroscience"),
    ("embodied simulation grounded cognition","cognitive_science"),
    ("dual coding theory paivio",            "cognitive_science"),

    # AI safety & alignment deep cuts
    ("goodhart law metric gaming",           "ai_safety"),
    ("sycophancy reward model LLM",          "ai_safety"),
    ("sleeper agent backdoor neural network","ai_safety"),
    ("eliciting latent knowledge ELK",       "ai_safety"),
    ("natural abstraction hypothesis",       "ai_safety"),
    ("impact measures side effects AI",      "ai_safety"),
    ("approval directed agents",             "ai_safety"),
    ("debate AI safety amplification",       "ai_safety"),
    ("iterated amplification distillation",  "ai_safety"),
    ("scalable oversight weak supervision",  "ai_safety"),

    # ML theory
    ("PAC learning computational complexity","machine_learning"),
    ("VC dimension generalisation bound",    "machine_learning"),
    ("no free lunch theorem optimisation",   "machine_learning"),
    ("energy based models contrastive",      "machine_learning"),
    ("boltzmann machine restricted",         "machine_learning"),
    ("normalising flows density estimation", "machine_learning"),
    ("variational autoencoder latent space", "machine_learning"),
    ("neural tangent kernel infinite width", "machine_learning"),
    ("double descent modern bias variance",  "machine_learning"),
    ("conformal prediction uncertainty",     "machine_learning"),

    # Complexity & systems
    ("cybernetics feedback control systems", "complexity"),
    ("stigmergy indirect coordination",      "complexity"),
    ("complex adaptive systems holland",     "complexity"),
    ("percolation theory phase transition",  "complexity"),
    ("self-organised criticality bak",       "complexity"),
    ("network resilience robustness",        "complexity"),
    ("agent based modelling simulation",     "complexity"),
    ("dissipative structures prigogine",     "complexity"),

    # Neurosymbolic & hybrid AI
    ("neurosymbolic AI integration",         "ai_architecture"),
    ("program synthesis inductive learning", "ai_architecture"),
    ("abstract reasoning ARC benchmark",     "ai_architecture"),
    ("analogical reasoning structure mapping","cognitive_science"),
    ("concept learning one shot",            "machine_learning"),
    ("cognitive map tolman latent learning", "cognitive_science"),
    ("predictive mind andy clark",           "cognitive_science"),
    ("language of thought hypothesis fodor", "philosophy"),
    ("massive modularity evolutionary psych","cognitive_science"),
    ("bayesian brain helmholtz machine",     "neuroscience"),
]


# ── Worker function — runs in its own process ─────────────────────
def _crawl_worker(args):
    """
    Spawned as a separate process. Gets its own Python interpreter,
    asyncio event loop, and NexCrawler instance.
    Returns (topic, n_stored, url)
    """
    if len(args) == 4:
        topic, reason, url, nex_dir_str = args
    else:
        topic, reason, nex_dir_str = args
        url = None
    nex_dir = Path(nex_dir_str)

    import sys, logging
    sys.path.insert(0, str(nex_dir))
    logging.basicConfig(level=logging.WARNING)  # silence crawl4ai noise

    try:
        from nex.nex_crawler import NexCrawler, _resolve_search_url
        from nex.belief_store import get_db

        crawler = NexCrawler(belief_store=get_db)
        if url is None:
            url = _resolve_search_url(topic)
        n = crawler.on_knowledge_gap(topic=topic, search_url=url)
        return (topic, n or 0, url)
    except Exception as e:
        return (topic, 0, f"err:{e}")


# ── Helpers ───────────────────────────────────────────────────────
def _db_count():
    try:
        con = sqlite3.connect(str(DB))
        n = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0


def _clear_cooldown():
    f = CFG / "curiosity_queue.json"
    if not f.exists():
        print("  [cooldown] nothing to clear")
        return
    try:
        data = json.loads(f.read_text())
        changed = False
        for key in ["crawled_topics", "crawled"]:
            if key in data and data[key]:
                n = len(data[key])
                data[key] = {}
                changed = True
                print(f"  [cooldown] cleared {key} ({n} entries)")
        if changed:
            f.write_text(json.dumps(data, indent=2))
    except Exception as exc:
        print(f"  [cooldown] error: {exc}")


def _enqueue_seeds(engine, topics):
    q = getattr(engine, "_queue", None) or getattr(engine, "queue", None)
    if q is None:
        return 0
    fn = None
    for name in ["enqueue", "add", "push", "put"]:
        if hasattr(q, name):
            fn = getattr(q, name)
            break
    if fn is None:
        return 0
    params = list(inspect.signature(fn).parameters.keys())
    added = 0
    for topic, reason in topics:
        try:
            if "confidence" in params and "reason" in params:
                r = fn(topic, reason=reason, confidence=0.5)
            elif "reason" in params:
                r = fn(topic, reason=reason)
            elif len(params) >= 2:
                r = fn(topic, reason)
            else:
                r = fn(topic)
            if r is not False:
                added += 1
        except Exception:
            pass
    return added


def _pop_n_topics(engine, n):
    """
    Pop up to N distinct topics from q._queue (CuriosityItem list).
    Removes them from the queue so they won't be re-picked next cycle.
    Returns list of (topic, reason, url) tuples.
    """
    from nex.nex_crawler import _resolve_search_url

    q = getattr(engine, "_queue", None) or getattr(engine, "queue", None)
    if q is None:
        return []

    raw = getattr(q, "_queue", [])  # the actual list of CuriosityItem
    if not raw:
        return []

    popped = []
    seen_urls = set()
    to_remove = []

    for item in list(raw):  # iterate a copy
        if len(popped) >= n:
            break
        topic  = getattr(item, "topic",  None)
        reason = getattr(item, "reason", "general") or "general"
        if not topic:
            continue
        url = _resolve_search_url(topic)
        if url in seen_urls:
            continue  # same URL as another worker — skip
        seen_urls.add(url)
        popped.append((topic, reason, url))
        to_remove.append(item)

    # Remove consumed items from the live queue
    for item in to_remove:
        try:
            raw.remove(item)
        except ValueError:
            pass

    # Persist queue state
    try:
        q._save()
    except Exception:
        pass

    return popped


def _digest(label=""):
    tag = f" [{label}]" if label else ""
    ops = tens = ref = 0
    try:
        from nex.nex_opinions import refresh_opinions
        ops = refresh_opinions()
    except Exception:
        ops = "err"
    try:
        from nex.nex_contradiction_resolver import detect_and_log
        tens = detect_and_log(limit=500, max_new=20)
    except Exception:
        tens = 0
    try:
        from nex.nex_reflect import reflect_tick
        ref = reflect_tick()
    except Exception:
        ref = 0
    print(f"  digest{tag} → opinions:{ops} tensions:{tens} reflect:{ref}")


# ── Main ──────────────────────────────────────────────────────────
def main():
    clear_mode = "--clear" in sys.argv
    no_digest  = "--no-digest" in sys.argv

    n_workers = DEFAULT_WORKERS
    for arg in sys.argv[1:]:
        if arg.startswith("--workers="):
            try:
                n_workers = int(arg.split("=")[1])
            except ValueError:
                pass

    n_cycles = 10
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            continue
        try:
            n_cycles = int(arg)
        except ValueError:
            pass

    print(f"\n  nex_drain v4 | {n_workers} parallel workers | digest every {DIGEST_EVERY}")
    print(f"  cycles={n_cycles}  clear={clear_mode}  digest={not no_digest}\n")

    if clear_mode:
        _clear_cooldown()

    # Init engine on main process (manages queue state)
    try:
        from nex.nex_crawler import NexCrawler
        from nex.belief_store import get_db
        _main_crawler = NexCrawler(belief_store=get_db)
        print("  [main] crawler ready ✓")
    except Exception:
        traceback.print_exc()
        sys.exit(1)

    from nex.nex_curiosity import CuriosityEngine
    engine = CuriosityEngine(_main_crawler)

    status = engine.status()
    if status.get("pending", 0) == 0:
        added = _enqueue_seeds(engine, SEED_TOPICS)
        print(f"  seeded {added} topics → {engine.status().get('pending',0)} pending")

    start = _db_count()
    print(f"  beliefs at start: {start}")
    print(f"  launching {n_workers}× worker processes...\n")

    session_new  = 0
    n_digests    = 0
    nex_dir_str  = str(NEX_DIR)

    # Use spawn context to avoid asyncio/fork issues on Linux
    ctx = mp.get_context("spawn")

    for cycle in range(n_cycles):

        # Absorb cap check
        if not no_digest and session_new >= ABSORB_CAP:
            print(f"  absorb cap ({session_new} new) — digesting...")
            _digest("cap")
            n_digests += 1
            session_new = 0

        # Re-seed if needed
        if engine.status().get("pending", 0) < n_workers:
            added = _enqueue_seeds(engine, SEED_TOPICS)
            if engine.status().get("pending", 0) == 0:
                print(f"  all topics on cooldown — run with --clear")
                break

        # Pop N topics from queue (peek without consuming)
        topics_batch = _pop_n_topics(engine, n_workers)
        if not topics_batch:
            # Fall back to sequential drain
            topics_batch = []
            for _ in range(n_workers):
                if engine.status().get("pending", 0) == 0:
                    break
                # Get topic name via engine status
                s = engine.status()
                topic_list = s.get("topics", [])
                if topic_list:
                    topics_batch.append((topic_list[0], "general"))

        if not topics_batch:
            print(f"  queue empty")
            break

        # Build worker args — each worker gets a distinct topic+url
        worker_args = []
        seen_worker_urls = set()
        for item in topics_batch[:n_workers]:
            if len(item) == 3:
                t, r, url = item
            else:
                t, r = item[0], item[1]
                from nex.nex_crawler import _resolve_search_url
                url = _resolve_search_url(t)
            if url not in seen_worker_urls:
                worker_args.append((t, r, url, nex_dir_str))
                seen_worker_urls.add(url)

        before = _db_count()
        t0 = time.time()

        # Run workers in parallel processes
        with ctx.Pool(processes=len(worker_args)) as pool:
            results = pool.map(_crawl_worker, worker_args)

        # Consume from engine queue (mark topics as crawled)
        for topic, n_stored, url in results:
            try:
                engine.mark_topic_crawled(topic)
            except Exception:
                pass
            # Also drain from queue to keep it consistent
            try:
                q = getattr(engine, "_queue", None) or getattr(engine, "queue", None)
                if q and hasattr(q, "mark_topic_crawled"):
                    q.mark_topic_crawled(topic)
            except Exception:
                pass

        after   = _db_count()
        n_new   = after - before
        elapsed = time.time() - t0
        session_new += n_new

        # Format output line
        parts = [f"{t[:25]}(+{n})" for t, n, _ in results]
        combined = " + ".join(parts)
        total_str = f"= +{n_new}"
        print(f"  cycle {cycle+1:02d} | {combined} {total_str} | db={after} | {elapsed:.1f}s")

        # Periodic digest
        if not no_digest and (cycle + 1) % DIGEST_EVERY == 0:
            _digest(f"c{cycle+1}")
            n_digests += 1

        if n_new == 0 and cycle > 3:
            print(f"  no new beliefs (dedup or empty queue)")
            break

    final = _db_count()
    print(f"\n  ── done ──")
    print(f"  beliefs: {start} → {final} (+{final - start})")
    print(f"  digests: {n_digests}")

    if not no_digest and (final - start) > 0:
        print(f"\n  final digest...")
        _digest("final")

    print(f"\n  run: python3 weaning_status.py")


if __name__ == "__main__":
    main()
