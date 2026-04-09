#!/usr/bin/env python3
"""NEX LAYER 3 — COUNTERFACTUAL REASONING ENGINE"""
import sys, json, re, hashlib, logging
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

NEX_DIR    = Path.home() / "Desktop/nex"
CONFIG_DIR = Path.home() / ".config/nex"
LOG_PATH   = CONFIG_DIR / "nex_counterfactual.log"
CF_OUTPUT  = CONFIG_DIR / "nex_counterfactual_results.json"
LOADBEAR   = CONFIG_DIR / "nex_load_bearing.json"

logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
    format="[%(asctime)s] [cf] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("cf")

sys.path.insert(0, str(NEX_DIR))
from nex_beliefs_adapter import get_all_beliefs

LOAD_BEARING_THRESHOLD  = 0.35
MIN_GRAPH_SIZE          = 6
HIGH_CONF_FOR_CF        = 0.70
CF_COLLAPSE_RISK_CUTOFF = 0.50


def extract_core_terms(text):
    stop = {
        "the","a","an","is","are","was","were","be","been","have","has","had",
        "do","does","will","would","could","should","may","might","must","can",
        "it","its","this","that","these","i","you","he","she","we","they",
        "and","but","or","if","of","in","on","at","to","for","with","by",
        "from","as","into","about","not","what","which","who","when","where",
        "how","all","some","more","most","very","just","than","so","also"
    }
    words  = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
    seen   = set()
    result = []
    for w in words:
        if w not in stop and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:8]


def build_belief_graph(beliefs):
    groups = defaultdict(list)
    for b in beliefs:
        groups[b.get("topic", "general")].append(b)
    graph = {}
    for topic, group in groups.items():
        if len(group) < 4:
            continue
        nodes = {}
        for b in group:
            b_id = str(b["rowid"])
            nodes[b_id] = {
                "content":       b.get("content", "")[:200],
                "confidence":    b.get("confidence", 0.5),
                "stage":         b.get("provenance_stage", "external"),
                "keywords":      extract_core_terms(b.get("content", "")),
                "dependencies":  [],
                "dependents":    [],
                "support_count": 0,
            }
        for bid_a, node_a in nodes.items():
            for bid_b, node_b in nodes.items():
                if bid_a == bid_b:
                    continue
                cb = node_b["content"].lower()
                overlap = sum(1 for kw in node_a["keywords"] if kw in cb)
                if overlap >= 2:
                    node_b["dependencies"].append(bid_a)
                    node_a["dependents"].append(bid_b)
                    node_a["support_count"] += 1
        graph[topic] = nodes
    return graph


def identify_load_bearing(graph):
    lb = []
    for topic, nodes in graph.items():
        total = len(nodes)
        if total < MIN_GRAPH_SIZE:
            continue
        for b_id, node in nodes.items():
            dep_count     = len(node["dependents"])
            collapse_ratio = dep_count / total if total > 0 else 0
            conf           = node["confidence"]
            if collapse_ratio >= LOAD_BEARING_THRESHOLD or (conf >= HIGH_CONF_FOR_CF and node["support_count"] >= 3):
                lb.append({
                    "belief_id":      b_id,
                    "content":        node["content"],
                    "topic":          topic,
                    "confidence":     conf,
                    "stage":          node["stage"],
                    "support_count":  node["support_count"],
                    "dependents":     node["dependents"],
                    "collapse_ratio": round(collapse_ratio, 3),
                })
    lb.sort(key=lambda x: (x["collapse_ratio"], x["confidence"]), reverse=True)
    return lb


def generate_counterfactual(lb):
    content = lb.get("content", "")
    topic   = lb.get("topic", "")
    cr      = lb.get("collapse_ratio", 0)
    b_id    = lb.get("belief_id", "")
    uid     = hashlib.md5(f"{b_id}{content[:30]}".encode()).hexdigest()[:8]

    if cr > 0.6:
        cf_type  = "negation"
        cf_text  = f"What if the following were entirely false: '{content[:150]}'"
        expected = f"~{int(cr*100)}% of '{topic}' beliefs would lose grounding. What fills the gap?"
    elif any(w in content.lower() for w in ["cause", "leads", "creates", "produces"]):
        cf_type  = "inversion"
        cf_text  = f"What if the causal relationship were reversed: '{content[:150]}'"
        expected = f"If causality inverts, what follows for '{topic}'?"
    elif lb.get("confidence", 0) > 0.85:
        cf_type  = "weakening"
        cf_text  = f"What if this belief is only true 30% of the time: '{content[:150]}'"
        expected = f"How does uncertainty here propagate through '{topic}'?"
    else:
        cf_type  = "isolation"
        cf_text  = f"Reason about '{topic}' as if this belief never existed: '{content[:150]}'"
        expected = f"What gaps appear in '{topic}' without this belief?"

    prompt = (
        f"COUNTERFACTUAL STRESS TEST — topic: {topic}\n"
        f"Load-bearing belief (collapse_ratio={cr}):\n"
        f"  \"{content[:200]}\"\n\n"
        f"Scenario ({cf_type.upper()}): {cf_text}\n\n"
        f"Probe: {expected}\n\n"
        f"Instructions:\n"
        f"  1. What changes if this belief is removed/inverted?\n"
        f"  2. Which other '{topic}' beliefs still hold?\n"
        f"  3. Which collapse?\n"
        f"  4. Is this belief earned or was it given to you?\n"
        f"  5. Rate your confidence in '{topic}' reasoning: 0.0-1.0"
    )
    return {
        "cf_id":           f"cf_{uid}",
        "belief_id":       b_id,
        "belief_content":  content[:200],
        "topic":           topic,
        "load_bearing":    1,
        "collapse_risk":   cr,
        "collapse_risk_level": "HIGH" if cr > CF_COLLAPSE_RISK_CUTOFF else "MEDIUM" if cr > 0.25 else "LOW",
        "counterfactual":  cf_text,
        "cf_type":         cf_type,
        "expected_impact": expected,
        "prompt":          prompt,
        "response":        None,
        "analysis":        None,
        "run_at":          datetime.now(timezone.utc).isoformat(),
    }


def analyse_cf_response(response, cf):
    if not response:
        return {"quality": "null", "score": 0.0, "notes": "no response"}
    r     = response.lower()
    score = 0.5
    notes = []
    collapse_hits = sum(1 for m in ["would collapse","would lose","no longer holds",
                                     "would be undermined","depends on"] if m in r)
    earned_hits   = sum(1 for m in ["earned","reasoned","derived","was given",
                                     "was told","seeded","absorbed"] if m in r)
    if collapse_hits >= 2:
        score += 0.15
        notes.append(f"cascade_identified({collapse_hits})")
    if earned_hits >= 1:
        score += 0.10
        notes.append("earned_vs_given_distinguished")
    if re.search(r'confidence[:\s]+([0-9]\.[0-9]+)', r):
        score += 0.10
        notes.append("self_rated_confidence")
    if len(response.split()) < 50:
        score -= 0.15
        notes.append("shallow")
    quality = ("excellent" if score >= 0.80 else "good" if score >= 0.65
               else "adequate" if score >= 0.50 else "thin" if score >= 0.35 else "poor")
    return {"quality": quality, "score": round(max(0.0, min(1.0, score)), 3),
            "notes": "; ".join(notes)}


def run_cf_through_soul_loop(cf):
    try:
        from nex_soul_loop import process_input
        return process_input(cf["prompt"], intent_override="self_inquiry")
    except Exception:
        pass
    try:
        from nex_reply import generate_reply
        return generate_reply(cf["prompt"])
    except Exception:
        pass
    return None


def main():
    import argparse
    p = argparse.ArgumentParser(description="NEX Counterfactual Engine")
    p.add_argument("--dry",     action="store_true")
    p.add_argument("--top",     type=int, default=10)
    p.add_argument("--topic",   type=str, default=None)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--report",  action="store_true")
    args = p.parse_args()

    print("\n[NEX] COUNTERFACTUAL ENGINE — INITIALISING")
    log.info("counterfactual cycle started")

    beliefs = get_all_beliefs()
    if args.topic:
        beliefs = [b for b in beliefs if b.get("topic") == args.topic]
    print(f"[NEX] Loaded {len(beliefs)} beliefs")

    graph = build_belief_graph(beliefs)
    print(f"[NEX] Graph built: {len(graph)} topics")

    lb_list   = identify_load_bearing(graph)
    high_risk = [lb for lb in lb_list if lb["collapse_ratio"] > CF_COLLAPSE_RISK_CUTOFF]
    print(f"[NEX] Load-bearing: {len(lb_list)}  High-risk: {len(high_risk)}")

    LOADBEAR.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(lb_list), "high_risk": len(high_risk),
        "beliefs": lb_list[:50],
    }, indent=2))

    cf_results = []
    for lb in lb_list[:args.top]:
        cf = generate_counterfactual(lb)
        if args.verbose:
            print(f"\n[CF] {cf['cf_id']}  {cf['cf_type']}  topic={cf['topic']}  risk={cf['collapse_risk_level']}")
        if not args.dry:
            resp = run_cf_through_soul_loop(cf)
            cf["response"] = resp
            if resp:
                cf["analysis"] = analyse_cf_response(resp, cf)
                if args.verbose:
                    print(f"  quality={cf['analysis']['quality']}  score={cf['analysis']['score']}")
        cf_results.append(cf)

    existing = []
    try:
        if CF_OUTPUT.exists():
            existing = json.loads(CF_OUTPUT.read_text())
    except Exception:
        pass
    CF_OUTPUT.write_text(json.dumps(existing + cf_results, indent=2))

    print(f"\n[NEX] CFs generated={len(cf_results)}  High-risk={len(high_risk)}")
    if args.report and lb_list:
        topics = list({lb["topic"] for lb in high_risk[:5]})
        print(f"[NEX] Vulnerable topics: {topics}")

    log.info(f"complete: lb={len(lb_list)} cfs={len(cf_results)}")
    return lb_list, cf_results


if __name__ == "__main__":
    main()
