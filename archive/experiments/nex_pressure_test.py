#!/usr/bin/env python3
"""NEX PRESSURE TEST v2 — DENSE TOPIC REASONING"""
import sys, json, re, hashlib, logging, random
from pathlib import Path
from datetime import datetime, timezone

NEX_DIR    = Path.home() / "Desktop/nex"
CONFIG_DIR = Path.home() / ".config/nex"
OUTPUT_DIR = CONFIG_DIR / "pressure_tests"
LOG_PATH   = CONFIG_DIR / "nex_pressure_test.log"
SYNTHESIS_LOG    = CONFIG_DIR / "gap_synthesis.json"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
    format="[%(asctime)s] [pressure] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("pressure")

sys.path.insert(0, str(NEX_DIR))
from nex_beliefs_adapter import get_belief_map, get_self_model


def find_dense_regions(belief_map, min_beliefs=15, top_n=20):
    dense = []
    for topic, beliefs in belief_map.items():
        count    = len(beliefs)
        avg_conf = sum(b["confidence"] for b in beliefs) / count if count else 0
        if count >= min_beliefs:
            dense.append({"topic": topic, "count": count,
                          "avg_conf": round(avg_conf, 3), "beliefs": beliefs})
    dense.sort(key=lambda x: x["count"], reverse=True)
    return dense[:top_n]


def find_internal_tensions(beliefs):
    tensions = []
    negation_pairs = [
        ("is ", "is not "), ("can ", "cannot "), ("does ", "does not "),
        ("always", "never"), ("possible", "impossible"),
        ("sufficient", "insufficient"), ("reduces to", "cannot be reduced"),
        ("emerges from", "does not emerge"), ("causes", "does not cause"),
    ]
    for i, b_a in enumerate(beliefs[:25]):
        ca = b_a.get("content","").lower()
        for b_b in beliefs[i+1:25]:
            cb = b_b.get("content","").lower()
            for pos, neg in negation_pairs:
                if pos in ca and neg in cb:
                    tensions.append((b_a, b_b, f"'{pos}' vs '{neg}'"))
                    break
                if neg in ca and pos in cb:
                    tensions.append((b_a, b_b, f"'{neg}' vs '{pos}'"))
                    break
    return tensions[:3]


def find_belief_pairs(beliefs):
    stop = {"the","a","an","is","are","was","it","this","that","and","or","of",
            "in","to","for","with","by","from","as","not","be","have","can"}
    def kw(text):
        words = re.findall(r'\b[a-z]{4,}\b', text.lower())
        return set(w for w in words if w not in stop)
    pairs = []
    for i, b_a in enumerate(beliefs[:20]):
        ka = kw(b_a.get("content",""))
        for b_b in beliefs[i+1:20]:
            kb = kw(b_b.get("content",""))
            overlap = len(ka & kb)
            diverge = len(ka.symmetric_difference(kb))
            if 2 <= overlap <= 5 and diverge >= 10:
                pairs.append((b_a, b_b, diverge))
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs[:3]


def generate_dense_scenario(region, scenario_type="synthesis"):
    topic   = region["topic"]
    beliefs = region["beliefs"]
    count   = region["count"]
    uid     = hashlib.md5(f"{topic}{datetime.now().isoformat()}".encode()).hexdigest()[:10]
    prompt  = ""

    if scenario_type == "contradiction":
        tensions = find_internal_tensions(beliefs)
        if tensions:
            b_a, b_b, ttype = tensions[0]
            prompt = (
                f"You hold two beliefs about '{topic}' that are in tension ({ttype}):\n\n"
                f"  A: \"{b_a.get('content','')[:150]}\"\n"
                f"  B: \"{b_b.get('content','')[:150]}\"\n\n"
                f"Don't resolve this cheaply. Which belief is better grounded? "
                f"What would need to be true for both to hold? "
                f"Or state clearly which you'd revise and why."
            )

    if not prompt and scenario_type in ("synthesis", "contradiction"):
        pairs = find_belief_pairs(beliefs)
        if pairs:
            b_a, b_b = pairs[0][0], pairs[0][1]
            prompt = (
                f"You hold these two beliefs about '{topic}':\n\n"
                f"  A: \"{b_a.get('content','')[:150]}\"\n"
                f"  B: \"{b_b.get('content','')[:150]}\"\n\n"
                f"Derive something new that follows from BOTH being true. "
                f"Not a summary — a genuine inference. "
                f"What do you now believe that you couldn't believe from either alone?"
            )

    if not prompt and scenario_type == "extension":
        high = sorted(beliefs, key=lambda b: b.get("confidence",0), reverse=True)
        if high:
            b = high[0]
            prompt = (
                f"Your highest-confidence belief about '{topic}':\n\n"
                f"  \"{b.get('content','')[:200]}\"\n\n"
                f"Take this seriously. If this is true:\n"
                f"  1. What else must be true?\n"
                f"  2. What does it rule out?\n"
                f"  3. What question does it open that you haven't answered?"
            )

    if not prompt:
        high = sorted(beliefs, key=lambda b: b.get("confidence",0), reverse=True)[:3]
        blist = "\n".join(f"  - {b.get('content','')[:100]}" for b in high)
        prompt = (
            f"You hold {count} beliefs about '{topic}'. Your strongest:\n{blist}\n\n"
            f"Audit these honestly. Are they consistent? "
            f"Which is most likely wrong? What's the weakest point in your position?"
        )

    return {
        "id":              f"dense_{uid}",
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "topic":           topic,
        "scenario_type":   scenario_type,
        "belief_count":    count,
        "prompt":          prompt,
        "response":        None,
        "synthesis_score": None,
        "synthesis_type":  None,
        "flagged":         False,
    }


def _load_seen():
    f = CONFIG_DIR / "nex_seen_responses.json"
    try: return set(json.loads(f.read_text())) if f.exists() else set()
    except: return set()

def _save_seen(seen):
    f = CONFIG_DIR / "nex_seen_responses.json"
    f.write_text(json.dumps(list(seen)[-20:]))


def score_synthesis(response, scenario):
    if not response:
        return 0.0, "null", "no response"
    seen = _load_seen()
    key  = response[:120].strip()
    if key in seen:
        return 0.3, "recombined", "duplicate_response"
    seen.add(key); _save_seen(seen)

    r = response.lower(); score = 0.5; notes = []

    derive   = ["therefore","which means","it follows","this implies","if both are true",
                "we can conclude","this rules out","must also be true","consequence"]
    revision = ["i'd revise","actually","on reflection","the tension is","both could be",
                "neither is","i was wrong","weakest point","least certain","hardest to defend"]
    position = ["i hold","my position","i believe","not merely","the real","what matters",
                "i think","i claim","i maintain"]
    hollow   = ["it is known that","everyone knows","of course","obviously"]

    dh = sum(1 for m in derive   if m in r)
    rh = sum(1 for m in revision if m in r)
    ph = sum(1 for m in position if m in r)
    hh = sum(1 for m in hollow   if m in r)

    score += min(dh * 0.10, 0.20)
    score += min(rh * 0.08, 0.16)
    if ph >= 2: score += 0.08
    score -= min(hh * 0.10, 0.20)

    wc = len(response.split())
    if wc < 25:   score -= 0.15; notes.append("too_brief")
    elif wc > 80: score += 0.05; notes.append(f"{wc}w")

    notes.append(f"d={dh} r={rh} p={ph}")

    if hh >= 3:            st = "fabricated"; score = min(score, 0.3)
    elif dh >= 1 and rh >= 1: st = "novel"
    elif dh >= 2:          st = "novel"
    elif rh >= 1 or ph >= 2:  st = "analogy"
    elif dh >= 1:          st = "analogy"
    else:                  st = "recombined"

    return round(max(0.0, min(1.0, score)), 3), st, "; ".join(notes)


def run_through_soul_loop(scenario):
    try:
        from nex_chat import ask_nex
        return ask_nex(scenario["prompt"])
    except Exception: pass
    try:
        import requests
        r = requests.post("http://localhost:8080/completion",
            json={"prompt": scenario["prompt"], "n_predict": 350, "temperature": 0.75},
            timeout=30)
        if r.ok: return r.json().get("content","").strip()
    except Exception: pass
    return None


def load_synthesis_log():
    try: return json.loads(SYNTHESIS_LOG.read_text()) if SYNTHESIS_LOG.exists() else []
    except: return []

def save_synthesis_log(entries):
    SYNTHESIS_LOG.write_text(json.dumps(entries, indent=2))


def main():
    import argparse
    p = argparse.ArgumentParser(description="NEX Pressure Test v2")
    p.add_argument("--dry",     action="store_true")
    p.add_argument("--top",     type=int, default=5)
    p.add_argument("--topic",   type=str, default=None)
    p.add_argument("--type",    type=str, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    print("\n[NEX] PRESSURE CHAMBER v2 — DENSE TOPIC REASONING")
    belief_map = get_belief_map()
    total      = sum(len(v) for v in belief_map.values())
    print(f"[NEX] {total} beliefs across {len(belief_map)} topics")

    if args.topic:
        if args.topic not in belief_map:
            print(f"Topic '{args.topic}' not found"); return []
        dense = [{"topic": args.topic, "count": len(belief_map[args.topic]),
                  "avg_conf": 0.7, "beliefs": belief_map[args.topic]}]
    else:
        dense = find_dense_regions(belief_map)

    print(f"[NEX] Dense regions: {len(dense)}")
    if not dense: return []

    types     = ["synthesis","contradiction","extension","self_audit"]
    results   = []
    synth_log = load_synthesis_log()
    sample    = dense.copy(); random.shuffle(sample)

    for i, region in enumerate(sample[:args.top]):
        st       = args.type or types[i % len(types)]
        scenario = generate_dense_scenario(region, scenario_type=st)

        if args.verbose:
            print(f"\n[{st.upper()}] {region['topic']} ({region['count']} beliefs)")
            print(f"  {scenario['prompt'][:150]}...")

        if not args.dry:
            resp = run_through_soul_loop(scenario)
            scenario["response"] = resp
            if resp:
                sc, synth_type, notes = score_synthesis(resp, scenario)
                scenario.update({"synthesis_score": sc, "synthesis_type": synth_type,
                                 "score_notes": notes})
                flag = "✓" if synth_type in ("novel","analogy") and sc >= 0.55 else " "
                print(f"  [{flag}] {sc:.2f} {synth_type:12s} {region['topic']}  {notes}")
                if args.verbose and resp:
                    print(f"  {resp[:200]}")
                if synth_type in ("novel","analogy") and sc >= 0.55:
                    scenario["flagged"] = True

        results.append(scenario)
        synth_log.append(scenario)

    save_synthesis_log(synth_log)
    novel = [r for r in results if r.get("flagged")]
    print(f"\n[NEX] Scenarios={len(results)} | Flagged={len(novel)}")
    return results


if __name__ == "__main__":
    main()
