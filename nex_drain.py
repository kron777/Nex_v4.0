#!/usr/bin/env python3
"""
nex_drain.py — dual-threaded crawler with absorb/digest cycle

Usage:
  python3 nex_drain.py [N_CYCLES] [--clear] [--no-digest]

  --clear      bypass 24hr cooldown cache
  --no-digest  skip opinion/tension/reflect synthesis between crawl waves
  N_CYCLES     number of drain cycles (default 10)

Absorb/digest model:
  - Two crawler threads run concurrently per cycle
  - Every DIGEST_EVERY cycles: run opinions + contradiction resolver + reflect
  - If unsynthesized beliefs > ABSORB_CAP: pause crawling, digest first
"""
import sys, json, sqlite3, logging, inspect, traceback, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.WARNING, format="%(message)s")
NEX_DIR = Path(__file__).parent
sys.path.insert(0, str(NEX_DIR))
CFG = Path("~/.config/nex").expanduser()
DB  = CFG / "nex.db"

# ── Config ────────────────────────────────────────────────────────
DIGEST_EVERY = 3    # digest after every N crawl cycles
ABSORB_CAP   = 80   # pause crawling if this many undigested beliefs pending
THREAD_COUNT = 2    # concurrent crawler threads

SEED_TOPICS = [
    # Wave 1 — AI/ML core
    ("reinforcement learning",              "machine_learning"),
    ("transformer architecture",            "ai_architecture"),
    ("emergent behaviour complex systems",  "complexity"),
    ("bayesian inference",                  "reasoning"),
    ("meta-learning few-shot",              "machine_learning"),
    ("causal reasoning ai",                 "reasoning"),
    ("embodied cognition robotics",         "cognitive_science"),
    ("knowledge representation graphs",    "ai_architecture"),
    ("self-supervised learning",            "machine_learning"),
    ("neural scaling laws",                 "ai_research"),
    ("model interpretability xai",         "ai_safety"),
    ("active inference free energy",        "cognitive_science"),
    ("goal misgeneralisation ai",           "ai_safety"),
    ("recursive self-improvement",          "ai_safety"),
    ("ai consciousness hard problem",       "philosophy"),
    ("distributed cognition",               "cognitive_science"),
    ("information theory entropy",          "mathematics"),
    ("collective intelligence swarms",      "complexity"),
    ("formal verification software",        "computer_science"),
    ("quantum computing algorithms",        "computer_science"),
    ("constitutional ai alignment",         "ai_safety"),
    ("rlhf reward hacking",                 "ai_safety"),
    ("mechanistic interpretability",        "ai_safety"),
    ("world models prediction",             "ai_architecture"),
    ("memory consolidation sleep",          "neuroscience"),
    ("predictive processing brain",         "neuroscience"),
    ("language grounding symbols",          "cognitive_science"),
    ("multi-agent cooperation game theory", "reasoning"),
    ("attention transformer self-attention","ai_architecture"),
    ("contrastive learning representations","machine_learning"),
    # Wave 2 — AI safety deep
    ("sparse autoencoder features",         "ai_safety"),
    ("hopfield network associative memory", "neuroscience"),
    ("circuit analysis neural network",     "ai_safety"),
    ("superposition hypothesis polysemanticity", "ai_safety"),
    ("bitter lesson compute scaling",       "ai_research"),
    ("grokking delayed generalisation",     "ai_research"),
    ("in-context learning transformer",     "machine_learning"),
    ("chain of thought prompting",          "ai_architecture"),
    ("mixture of experts language model",   "ai_architecture"),
    ("retrieval augmented generation",      "ai_architecture"),
    ("graph neural network reasoning",      "machine_learning"),
    ("diffusion model score matching",      "machine_learning"),
    ("cooperative ai multi-agent safety",   "ai_safety"),
    ("mesa-optimisation inner alignment",   "ai_safety"),
    ("deceptive alignment ai problem",      "ai_safety"),
    ("corrigibility shutdown ai",           "ai_safety"),
    # Wave 3 — philosophy + neuroscience
    ("global workspace theory consciousness","neuroscience"),
    ("integrated information theory tononi","neuroscience"),
    ("free energy principle friston",       "neuroscience"),
    ("connectome brain mapping",            "neuroscience"),
    ("cellular automata computation",       "complexity"),
    ("strange attractor chaos dynamical",   "complexity"),
    ("nash equilibrium game theory",        "reasoning"),
    ("dual process theory kahneman",        "cognitive_science"),
    ("theory of mind mentalising",          "cognitive_science"),
    ("qualia phenomenal consciousness",     "philosophy"),
    ("chinese room argument searle",        "philosophy"),
    ("godel incompleteness theorem",        "mathematics"),
    ("kolmogorov complexity algorithmic",   "mathematics"),
    ("lottery ticket hypothesis pruning",   "machine_learning"),
]

# ── Helpers ───────────────────────────────────────────────────────
def _belief_count() -> int:
    try:
        con = sqlite3.connect(str(DB))
        n = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0

def _undigested_count() -> int:
    """Beliefs added since last opinion refresh — rough proxy."""
    try:
        con = sqlite3.connect(str(DB))
        n = con.execute("""
            SELECT COUNT(*) FROM beliefs
            WHERE last_reinforced IS NULL OR last_reinforced = 0
        """).fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0

def _clear_cooldown():
    for fname in ["curiosity_queue.json", "curiosity_state.json", "curiosity.json"]:
        f = CFG / fname
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text())
            changed = False
            for key in ["crawled_topics", "crawled"]:
                if key in data and data[key]:
                    data[key] = {}
                    changed = True
            if changed:
                f.write_text(json.dumps(data, indent=2))
                print(f"  [cooldown] cleared {fname}")
                return True
        except Exception as exc:
            print(f"  [cooldown] error: {exc}")
    print("  [cooldown] already clear")
    return False

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

def _digest(label=""):
    """Run opinions + contradiction resolver + reflect."""
    tag = f" [{label}]" if label else ""
    results = {}
    try:
        from nex.nex_opinions import refresh_opinions
        n = refresh_opinions()
        results["opinions"] = n
    except Exception as e:
        results["opinions"] = f"err({e})"
    try:
        from nex.nex_contradiction_resolver import detect_and_log
        n = detect_and_log(limit=500, max_new=20)
        results["tensions"] = n
    except Exception as e:
        results["tensions"] = f"err({e})"
    try:
        from nex.nex_reflect import reflect_tick
        n = reflect_tick()
        results["reflect"] = n
    except Exception:
        results["reflect"] = 0
    print(f"  digest{tag} → opinions:{results['opinions']} tensions:{results['tensions']} reflect:{results.get('reflect',0)}")
    return results

# ── Dual-threaded drain ───────────────────────────────────────────
def _crawl_one(crawler, topic, reason, url=None):
    """Crawl a single topic. Returns (topic, n_new_beliefs)."""
    try:
        from nex.nex_crawler import _resolve_search_url
        resolved = url or _resolve_search_url(topic)
        n = crawler.on_knowledge_gap(topic=topic, search_url=resolved)
        return topic, n or 0
    except Exception as e:
        return topic, 0

def _drain_dual(engine, crawler, n_cycles, digest_every, absorb_cap, no_digest):
    """Main drain loop — two topics per cycle, digest every N."""
    total_new = 0
    digest_count = 0

    for cycle in range(n_cycles):
        status = engine.status()
        pending = status.get("pending", 0)

        if pending == 0:
            added = _enqueue_seeds(engine, SEED_TOPICS)
            status = engine.status()
            pending = status.get("pending", 0)
            if pending == 0:
                print(f"  cooldown active — all topics on cooldown")
                break

        # Check absorb cap
        if not no_digest:
            undigested = _undigested_count()
            if undigested > absorb_cap:
                print(f"  absorb cap hit ({undigested} undigested) — digesting first...")
                _digest("cap")
                digest_count += 1

        # Pull two topics from queue
        queue = getattr(engine, "_queue", None) or getattr(engine, "queue", None)
        items = []
        drain_fn = getattr(queue, "drain", None)

        # Get next 2 items by calling engine drain twice on single-item batches
        # We do this by temporarily monkey-patching MAX_DRAIN or just calling twice
        before = _belief_count()

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=THREAD_COUNT) as pool:
            # Drain engine once to get up to 3 beliefs (1 topic), do twice
            futures = []
            for _ in range(THREAD_COUNT):
                status2 = engine.status()
                if status2.get("pending", 0) == 0:
                    break
                # We can't easily get 2 separate topics without patching drain
                # So we run engine.drain() in two threads — each gets different topic
                # since drain() pops from queue atomically
                futures.append(pool.submit(engine.drain))

            results = []
            for f in as_completed(futures):
                try:
                    results.append(f.result())
                except Exception as e:
                    results.append(0)

        after = _belief_count()
        n_new = after - before
        elapsed = time.time() - t0
        total_new += n_new

        # Compact output line
        print(f"  cycle {cycle+1:02d} | +{n_new:3d} beliefs | db={after} | {elapsed:.1f}s")

        # Digest every N cycles
        if not no_digest and (cycle + 1) % digest_every == 0:
            _digest(f"cycle {cycle+1}")
            digest_count += 1

        # Stop if no new beliefs (all deduped)
        if n_new == 0 and cycle > 2:
            print(f"  no new beliefs — queue exhausted or all deduped")
            break

    return total_new, digest_count

# ── Main ──────────────────────────────────────────────────────────
def main():
    clear_mode = "--clear" in sys.argv
    no_digest  = "--no-digest" in sys.argv

    n_cycles = 10
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            continue
        try:
            n_cycles = int(arg)
        except ValueError:
            pass

    print(f"\n  nex_drain v2 — {THREAD_COUNT} threads, digest every {DIGEST_EVERY} cycles")
    print(f"  cycles={n_cycles} clear={clear_mode} digest={not no_digest}\n")

    if clear_mode:
        _clear_cooldown()

    # Init crawler
    try:
        from nex.nex_crawler import NexCrawler
        from nex.belief_store import get_db
        crawler = NexCrawler(belief_store=get_db)
        print(f"  [crawler] ready (×{THREAD_COUNT} threads) ✓")
    except Exception:
        traceback.print_exc()
        sys.exit(1)

    # Init engine
    from nex.nex_curiosity import CuriosityEngine
    engine = CuriosityEngine(crawler)

    # Seed if empty
    status = engine.status()
    if status.get("pending", 0) == 0:
        added = _enqueue_seeds(engine, SEED_TOPICS)
        print(f"  seeded {added} topics → {engine.status().get('pending',0)} pending")

    start = _belief_count()
    print(f"  beliefs at start: {start}\n")

    # Run
    total_new, n_digests = _drain_dual(
        engine, crawler, n_cycles,
        digest_every=DIGEST_EVERY,
        absorb_cap=ABSORB_CAP,
        no_digest=no_digest
    )

    final = _belief_count()
    print(f"\n  ── done ──")
    print(f"  beliefs: {start} → {final} (+{final - start})")
    print(f"  digests run: {n_digests}")

    # Final digest
    if not no_digest and total_new > 0:
        print(f"\n  final digest...")
        _digest("final")

    print(f"\n  run: python3 weaning_status.py")

if __name__ == "__main__":
    main()
