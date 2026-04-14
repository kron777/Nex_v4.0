#!/usr/bin/env python3
"""NEX LAYER 4 — CLOSED LOOP ORCHESTRATOR"""
import sys, json, logging, importlib.util
from pathlib import Path
from datetime import datetime, timezone

NEX_DIR    = Path.home() / "Desktop/nex"
CONFIG_DIR = Path.home() / ".config/nex"
LOG_PATH   = CONFIG_DIR / "nex_closed_loop.log"
STATE_FILE = CONFIG_DIR / "nex_loop_state.json"
DRIVES_FILE = CONFIG_DIR / "nex_drives.json"

logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
    format="[%(asctime)s] [loop] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("loop")

sys.path.insert(0, str(NEX_DIR))
from nex_beliefs_adapter import (
    get_belief_map, get_all_beliefs, get_self_model,
    get_recent_absorb_content, get_high_confidence_beliefs,
    load_predictions, save_predictions
)


def load_mod(name, path):
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        log.error(f"load {name}: {e}")
        return None


def import_layers():
    # Force reload to pick up latest file changes
    import importlib, sys
    for mod in list(sys.modules.keys()):
        if 'nex_pressure' in mod or 'nex_belief_pred' in mod or 'nex_counter' in mod:
            del sys.modules[mod]
    pressure       = load_mod("nex_pressure_test",    NEX_DIR / "nex_pressure_test.py")
    prediction     = load_mod("nex_belief_prediction", NEX_DIR / "nex_belief_prediction.py")
    counterfactual = load_mod("nex_counterfactual",   NEX_DIR / "nex_counterfactual.py")
    return pressure, prediction, counterfactual


def load_state():
    try:
        return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_drives():
    try:
        return json.loads(DRIVES_FILE.read_text()) if DRIVES_FILE.exists() else {"primary": []}
    except Exception:
        return {"primary": []}


def save_drives(drives):
    DRIVES_FILE.write_text(json.dumps(drives, indent=2))


def fire_disturbance(topic, reason):
    try:
        from nex_destabilization import record_disturbance
        record_disturbance(topic, reason, level=0.6)
        return True
    except Exception:
        pass
    # Fallback: write to disturbance log file
    dist_file = CONFIG_DIR / "nex_disturbances.json"
    try:
        existing = json.loads(dist_file.read_text()) if dist_file.exists() else []
        existing.append({"topic": topic, "reason": reason, "level": 0.6,
                         "created_at": datetime.now(timezone.utc).isoformat()})
        dist_file.write_text(json.dumps(existing, indent=2))
        return True
    except Exception:
        return False


def propose_drive(topic, reason, source_id):
    import hashlib, time
    drive_id = f"emergent_{topic.replace(' ','_')}_{int(time.time())}"
    return {
        "id":          drive_id,
        "name":        f"explore_{topic.replace(' ','_')}",
        "description": f"Emerged from closed-loop: {reason[:100]}",
        "origin":      "emergent",
        "source":      f"closed_loop:{source_id}",
        "intensity":   0.6,
        "approved":    False,
        "created_at":  datetime.now(timezone.utc).isoformat(),
    }


# ── PHASES ────────────────────────────────────────────────────────────────────

def phase1_pressure(pressure, state, verbose):
    print("\n[LOOP] ── PHASE 1: PRESSURE TESTING ─────────────────")
    result = {"novel": [], "scenarios": 0}
    if not pressure:
        print("[LOOP] Layer 1 not available")
        return result
    try:
        bmap     = get_belief_map()
        sm       = get_self_model()
        sparse   = pressure.find_sparse_regions(bmap)
        print(f"[LOOP] Sparse regions: {len(sparse)}")
        import random
        _sparse = sparse[:20]
        random.shuffle(_sparse)
        for region in _sparse[:5]:
            topic    = region["topic"]
            adjacent = pressure.find_adjacent_beliefs(topic, bmap)
            scenario = pressure.generate_pressure_scenario(region, adjacent, sm)
            # Call ask_nex directly — more reliable than module import chain
            resp = None
            try:
                import sys; sys.path.insert(0, str(NEX_DIR))
                from nex_chat import ask_nex
                resp = ask_nex(scenario["prompt"])
            except Exception as _e:
                resp = pressure.run_through_soul_loop(scenario)
            scenario["response"] = resp
            result["scenarios"] += 1
            if resp:
                sc, st, notes = pressure.score_synthesis(resp, scenario)
                scenario.update({"synthesis_score": sc, "synthesis_type": st, "score_notes": notes})
                if st == "novel" and sc > 0.65:
                    result["novel"].append(scenario)
                    print(f"[LOOP] ✓ NOVEL: topic={topic} score={sc:.3f}")
                    log.info(f"novel: topic={topic} score={sc}")
        synth = pressure.load_synthesis_log()
        synth.extend([s for s in result["novel"]])
        pressure.save_synthesis_log(synth)
    except Exception as e:
        log.error(f"phase1: {e}")
        print(f"[LOOP] Phase 1 error: {e}")
    return result


def phase2_candidates(novel, state, verbose):
    print("\n[LOOP] ── PHASE 2: CANDIDATE BELIEF EXTRACTION ──────")
    result = {"candidates": [], "written": 0}
    if not novel:
        print("[LOOP] No novel syntheses to process")
        return result
    # Write novel synthesis as earned beliefs to a log file
    earned_file = CONFIG_DIR / "nex_earned_beliefs.json"
    try:
        existing = json.loads(earned_file.read_text()) if earned_file.exists() else []
    except Exception:
        existing = []
    for scenario in novel:
        resp  = scenario.get("response", "")
        topic = scenario.get("topic", "general")
        score = scenario.get("synthesis_score", 0)
        if not resp or score < 0.65:
            continue
        sentences = [s.strip() for s in resp.split('.') if len(s.strip()) > 40]
        if not sentences:
            continue
        candidate = {
            "content":    sentences[0][:300],
            "topic":      topic,
            "confidence": min(0.75, score),
            "source":     f"closed_loop:{scenario['id']}",
            "origin":     "emergent_synthesis",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        result["candidates"].append(candidate)
        existing.append(candidate)
        result["written"] += 1
        state["total_earned"] = state.get("total_earned", 0) + 1
        print(f"[LOOP] ✓ Earned belief logged: topic={topic}")
    earned_file.write_text(json.dumps(existing, indent=2))
    return result


def phase3_predictions(prediction, candidates, state, verbose):
    print("\n[LOOP] ── PHASE 3: PREDICTION CYCLE ─────────────────")
    result = {"new_preds": 0, "confirmed": 0, "disconfirmed": 0}
    if not prediction:
        print("[LOOP] Layer 2 not available")
        return result
    try:
        preds         = load_predictions()
        content_batch = get_recent_absorb_content(hours=48)
        for cand in candidates:
            fake = {"rowid": f"loop_{cand['source']}", "content": cand["content"],
                    "topic": cand["topic"], "confidence": cand["confidence"]}
            derived = prediction.derive_predictions(fake)
            preds.extend(derived)
            result["new_preds"] += len(derived)
        pending = [p for p in preds if p.get("result") == "pending"]
        for pred in pending[:20]:
            if prediction.check_expiry(pred):
                pred["result"] = "expired"
                continue
            pred = prediction.test_prediction_against_content(pred, content_batch)
            if pred["result"] == "confirmed":
                result["confirmed"] += 1
            elif pred["result"] == "disconfirmed":
                result["disconfirmed"] += 1
        save_predictions(preds)
        print(f"[LOOP] New={result['new_preds']}  Confirmed={result['confirmed']}  Disconfirmed={result['disconfirmed']}")
    except Exception as e:
        log.error(f"phase3: {e}")
        print(f"[LOOP] Phase 3 error: {e}")
    return result


def phase4_drives(p3, novel, state, verbose):
    print("\n[LOOP] ── PHASE 4: DISTURBANCES & DRIVES ────────────")
    result = {"disturbances": 0, "drives": 0}
    if p3["disconfirmed"] > 0:
        reason = f"{p3['disconfirmed']} predictions disconfirmed — epistemic tension"
        if fire_disturbance("belief_coherence", reason):
            result["disturbances"] += 1
            state["total_disturbances"] = state.get("total_disturbances", 0) + 1
            print("[LOOP] ✓ Disturbance fired: belief_coherence")
    drives  = load_drives()
    existing_names = {d.get("name", "") for d in drives.get("primary", [])}
    new_drives = []
    for scenario in novel:
        topic = scenario.get("topic", "")
        if not topic:
            continue
        name = f"explore_{topic.replace(' ','_')}"
        if name not in existing_names:
            drive = propose_drive(topic,
                f"Novel synthesis (score={scenario.get('synthesis_score',0):.2f})",
                scenario["id"])
            new_drives.append(drive)
            result["drives"] += 1
            state["total_drives"] = state.get("total_drives", 0) + 1
            print(f"[LOOP] ✓ Drive proposed: {name} (pending approval)")
            log.info(f"drive proposed: {name}")
    if new_drives:
        drives["primary"] = drives.get("primary", []) + new_drives
        save_drives(drives)
    return result


def phase5_cf(counterfactual, state, verbose):
    print("\n[LOOP] ── PHASE 5: COUNTERFACTUAL SPOT CHECK ─────────")
    result = {"checked": 0, "quality": "skipped"}
    if not counterfactual:
        print("[LOOP] Layer 3 not available")
        return result
    if state.get("cycle", 0) % 3 != 0:
        print("[LOOP] CF skipped this cycle (runs every 3 cycles)")
        return result
    try:
        beliefs = get_all_beliefs()
        graph   = counterfactual.build_belief_graph(beliefs)
        lb_list = counterfactual.identify_load_bearing(graph)
        if lb_list:
            lb   = lb_list[0]
            cf   = counterfactual.generate_counterfactual(lb)
            resp = counterfactual.run_cf_through_soul_loop(cf)
            if resp:
                analysis         = counterfactual.analyse_cf_response(resp, cf)
                result["checked"] = 1
                result["quality"] = analysis["quality"]
                print(f"[LOOP] CF: topic={lb['topic']}  risk={lb['collapse_ratio']:.2f}  quality={analysis['quality']}")
    except Exception as e:
        log.error(f"phase5: {e}")
        print(f"[LOOP] Phase 5 error: {e}")
    return result


def main():
    import argparse
    p = argparse.ArgumentParser(description="NEX Closed Loop Orchestrator")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--dry",     action="store_true")
    args = p.parse_args()

    print("\n" + "█" * 65)
    print("  NEX CLOSED LOOP ORCHESTRATOR — STARTING")
    print("█" * 65)

    state = load_state()
    state["cycle"]    = state.get("cycle", 0) + 1
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    log.info(f"=== CYCLE {state['cycle']} START ===")

    pressure, prediction, counterfactual = import_layers()
    n = sum([pressure is not None, prediction is not None, counterfactual is not None])
    print(f"[LOOP] Layers loaded: {n}/3")

    p1 = phase1_pressure(pressure, state, args.verbose)
    p2 = phase2_candidates(p1["novel"], state, args.verbose)
    p3 = phase3_predictions(prediction, p2["candidates"], state, args.verbose)
    # Belief revision — learn from disconfirmed predictions
    try:
        import sys; sys.path.insert(0, str(NEX_DIR))
        import nex_belief_revision as br
        br.main()
    except Exception as e:
        log.error(f"belief revision: {e}")

    p4 = phase4_drives(p3, p1["novel"], state, args.verbose)
    # Cross-domain bridge — every 5 cycles
    if state.get("cycle", 0) % 5 == 0:
        try:
            import nex_cross_domain_bridge as cdb
            cdb.main()
        except Exception as e:
            log.error(f"cross_domain_bridge: {e}")

    p5 = phase5_cf(counterfactual, state, args.verbose)

    state["phase_log"] = state.get("phase_log", [])[-50:]
    save_state(state)

    print("\n" + "═" * 65)
    print(f"  NEX CLOSED LOOP — CYCLE {state['cycle']} COMPLETE")
    print("═" * 65)
    print(f"  Sparse regions tested:    {p1['scenarios']}")
    print(f"  Novel syntheses:          {len(p1['novel'])}")
    print(f"  Earned beliefs logged:    {p2['written']}")
    print(f"  Predictions derived:      {p3['new_preds']}")
    print(f"  Confirmed:                {p3['confirmed']}")
    print(f"  Disconfirmed:             {p3['disconfirmed']}")
    print(f"  Disturbances fired:       {p4['disturbances']}")
    print(f"  Drives proposed:          {p4['drives']}")
    print(f"  CF quality:               {p5['quality']}")
    print(f"\n  Total earned:             {state.get('total_earned',0)}")
    print(f"  Total disturbances:       {state.get('total_disturbances',0)}")
    print(f"  Total drives:             {state.get('total_drives',0)}")
    print("═" * 65 + "\n")
    log.info(f"=== CYCLE {state['cycle']} COMPLETE ===")


if __name__ == "__main__":
    main()
