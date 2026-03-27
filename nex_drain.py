#!/usr/bin/env python3
"""
nex_drain.py v3 — dual topic drain with absorb/digest cycle

Usage:
  python3 nex_drain.py [N]   drain N cycles (default 10)
  --clear                    bypass cooldown cache
  --no-digest                skip digest between crawl waves
"""
import sys, json, sqlite3, logging, inspect, traceback, time, asyncio
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(message)s")
NEX_DIR = Path(__file__).parent
sys.path.insert(0, str(NEX_DIR))
CFG = Path("~/.config/nex").expanduser()
DB  = CFG / "nex.db"

DIGEST_EVERY  = 3    # digest after every N crawl cycles
ABSORB_CAP    = 60   # max new beliefs before forcing a digest pause
TOPICS_PER_CYCLE = 2 # topics to drain per cycle (sequential, asyncio-safe)

SEED_TOPICS = [
    ("reinforcement learning",               "machine_learning"),
    ("transformer architecture",             "ai_architecture"),
    ("emergent behaviour complex systems",   "complexity"),
    ("bayesian inference",                   "reasoning"),
    ("meta-learning few-shot",               "machine_learning"),
    ("causal reasoning ai",                  "reasoning"),
    ("embodied cognition robotics",          "cognitive_science"),
    ("knowledge representation graphs",     "ai_architecture"),
    ("self-supervised learning",             "machine_learning"),
    ("neural scaling laws",                  "ai_research"),
    ("model interpretability xai",          "ai_safety"),
    ("active inference free energy",         "cognitive_science"),
    ("goal misgeneralisation ai",            "ai_safety"),
    ("recursive self-improvement",           "ai_safety"),
    ("ai consciousness hard problem",        "philosophy"),
    ("distributed cognition",                "cognitive_science"),
    ("information theory entropy",           "mathematics"),
    ("collective intelligence swarms",       "complexity"),
    ("formal verification software",         "computer_science"),
    ("quantum computing algorithms",         "computer_science"),
    ("constitutional ai alignment",          "ai_safety"),
    ("rlhf reward hacking",                  "ai_safety"),
    ("mechanistic interpretability",         "ai_safety"),
    ("world models prediction",              "ai_architecture"),
    ("memory consolidation sleep",           "neuroscience"),
    ("predictive processing brain",          "neuroscience"),
    ("language grounding symbols",           "cognitive_science"),
    ("multi-agent cooperation game theory",  "reasoning"),
    ("attention transformer self-attention", "ai_architecture"),
    ("contrastive learning representations", "machine_learning"),
    ("sparse autoencoder features",          "ai_safety"),
    ("hopfield network associative memory",  "neuroscience"),
    ("circuit analysis neural network",      "ai_safety"),
    ("superposition hypothesis polysemanticity", "ai_safety"),
    ("bitter lesson compute scaling",        "ai_research"),
    ("grokking delayed generalisation",      "ai_research"),
    ("in-context learning transformer",      "machine_learning"),
    ("chain of thought prompting",           "ai_architecture"),
    ("mixture of experts language model",    "ai_architecture"),
    ("retrieval augmented generation",       "ai_architecture"),
    ("graph neural network reasoning",       "machine_learning"),
    ("diffusion model score matching",       "machine_learning"),
    ("cooperative ai multi-agent safety",    "ai_safety"),
    ("mesa-optimisation inner alignment",    "ai_safety"),
    ("deceptive alignment ai problem",       "ai_safety"),
    ("corrigibility shutdown ai",            "ai_safety"),
    ("global workspace theory consciousness","neuroscience"),
    ("integrated information theory tononi", "neuroscience"),
    ("free energy principle friston",        "neuroscience"),
    ("connectome brain mapping",             "neuroscience"),
    ("cellular automata computation",        "complexity"),
    ("strange attractor chaos dynamical",    "complexity"),
    ("nash equilibrium game theory",         "reasoning"),
    ("dual process theory kahneman",         "cognitive_science"),
    ("theory of mind mentalising",           "cognitive_science"),
    ("qualia phenomenal consciousness",      "philosophy"),
    ("chinese room argument searle",         "philosophy"),
    ("godel incompleteness theorem",         "mathematics"),
    ("kolmogorov complexity algorithmic",    "mathematics"),
    ("lottery ticket hypothesis pruning",    "machine_learning"),
]


def _db_count():
    try:
        con = sqlite3.connect(str(DB))
        n = con.execute("SELECT COUNT(*) FROM beliefs").fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0


def _clear_cooldown():
    for fname in ["curiosity_queue.json"]:
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
                print(f"  [cooldown] cleared")
                return
        except Exception as exc:
            print(f"  [cooldown] error: {exc}")
    print("  [cooldown] already clear")


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
    tag = f" [{label}]" if label else ""
    ops = tens = ref = 0
    try:
        from nex.nex_opinions import refresh_opinions
        ops = refresh_opinions()
    except Exception as e:
        ops = f"err"
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

    print(f"\n  nex_drain v3 | {TOPICS_PER_CYCLE} topics/cycle | digest every {DIGEST_EVERY}")
    print(f"  cycles={n_cycles}  clear={clear_mode}  digest={not no_digest}\n")

    if clear_mode:
        _clear_cooldown()

    # Init crawler — must stay on main thread (asyncio)
    try:
        from nex.nex_crawler import NexCrawler
        from nex.belief_store import get_db
        crawler = NexCrawler(belief_store=get_db)
        print("  [crawler] ready ✓")
    except Exception:
        traceback.print_exc()
        sys.exit(1)

    from nex.nex_curiosity import CuriosityEngine
    engine = CuriosityEngine(crawler)

    status = engine.status()
    if status.get("pending", 0) == 0:
        added = _enqueue_seeds(engine, SEED_TOPICS)
        print(f"  seeded {added} topics → {engine.status().get('pending',0)} pending")

    start = _db_count()
    print(f"  beliefs at start: {start}\n")

    session_new = 0
    n_digests   = 0

    for cycle in range(n_cycles):

        # Check absorb cap — compare against session new beliefs
        if not no_digest and session_new >= ABSORB_CAP:
            print(f"  absorb cap ({session_new} new this session) — digesting...")
            _digest("cap")
            n_digests += 1
            session_new = 0  # reset counter after digest

        # Re-seed if empty
        if engine.status().get("pending", 0) == 0:
            added = _enqueue_seeds(engine, SEED_TOPICS)
            if engine.status().get("pending", 0) == 0:
                print(f"  all topics on cooldown — run with --clear to bypass")
                break

        # Drain TOPICS_PER_CYCLE topics sequentially (asyncio-safe)
        before = _db_count()
        t0 = time.time()

        topics_drained = []
        for _ in range(TOPICS_PER_CYCLE):
            if engine.status().get("pending", 0) == 0:
                break
            # Get topic name before draining (peek at queue)
            q = getattr(engine, "_queue", None) or getattr(engine, "queue", None)
            topic_name = "?"
            if q is not None:
                items = getattr(q, "_items", None) or getattr(q, "items", None) or []
                if items:
                    topic_name = getattr(items[0], "topic", "?")
            n = engine.drain()
            topics_drained.append(f"{topic_name}(+{n})")

        after   = _db_count()
        n_new   = after - before
        elapsed = time.time() - t0
        session_new += n_new

        topics_str = " | ".join(topics_drained) if topics_drained else "—"
        print(f"  cycle {cycle+1:02d} | {topics_str:<55} | db={after} | {elapsed:.1f}s")

        # Digest every N cycles
        if not no_digest and (cycle + 1) % DIGEST_EVERY == 0:
            _digest(f"c{cycle+1}")
            n_digests += 1

        if n_new == 0 and cycle > 3:
            print(f"  no new beliefs — dedup cap or queue empty")
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
