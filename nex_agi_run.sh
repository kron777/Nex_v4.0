#!/bin/bash
# GPU utilisation check — skip if GPU busy
GPU_UTIL=$(cat /sys/class/drm/card*/device/gpu_busy_percent 2>/dev/null | head -1)
if [ ! -z "$GPU_UTIL" ] && [ "$GPU_UTIL" -gt 60 ]; then
    echo "[AGI] GPU at ${GPU_UTIL}% — skipping this cycle to protect stability"
    exit 0
fi
# NEX AGI BRIDGE 3 — DIRECT RUNNER v2






cd /home/rr/Desktop/nex
python3 - << 'PYTHON'
import sys, json, random, time
from pathlib import Path

NEX_DIR    = Path.home() / "Desktop/nex"
CONFIG_DIR = Path.home() / ".config/nex"
sys.path.insert(0, str(NEX_DIR))

for mod in list(sys.modules.keys()):
    if 'nex_' in mod:
        del sys.modules[mod]

import nex_pressure_test as pt
from nex_beliefs_adapter import get_belief_map, get_self_model
from nex_chat import ask_nex

bmap  = get_belief_map()
dense = pt.find_dense_regions(bmap)
random.shuffle(dense)

types  = ["synthesis","contradiction","extension","self_audit"]
novel  = []
all_sc = []

print(f"[AGI] Testing 5 of {len(dense)} dense regions")

for i, region in enumerate(dense[:3]):  # reduced to 3 to protect GPU
    st       = types[i % len(types)]
    scenario = pt.generate_dense_scenario(region, scenario_type=st)
    try:
        resp = ask_nex(scenario["prompt"])
    except Exception as e:
        print(f"  [FAIL] {region['topic']}: {e}")
        continue
    scenario["response"] = resp
    if resp:
        sc, synth_type, notes = pt.score_synthesis(resp, scenario)
        scenario.update({"synthesis_score": sc, "synthesis_type": synth_type,
                         "score_notes": notes})
        flag = "✓" if synth_type in ("novel","analogy") and sc >= 0.55 else " "
        print(f"  [{flag}] {sc:.2f} {synth_type:12s} {region['topic']}")
        if synth_type in ("novel","analogy") and sc >= 0.55:
            scenario["flagged"] = True
            novel.append(scenario)
        all_sc.append(scenario)

synth = pt.load_synthesis_log()
synth.extend(all_sc)
pt.save_synthesis_log(synth)

if novel:
    earned = CONFIG_DIR / "nex_earned_beliefs.json"
    try: existing = json.loads(earned.read_text())
    except: existing = []
    for s in novel:
        sentences = [x.strip() for x in s.get("response","").split('.') if len(x.strip()) > 40]
        if sentences:
            existing.append({
                "content":    sentences[0][:300],
                "topic":      s["topic"],
                "confidence": min(0.75, s["synthesis_score"]),
                "source":     f"agi_run:{s['id']}",
                "origin":     "emergent_synthesis",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            })
    earned.write_text(json.dumps(existing, indent=2))

state_file = CONFIG_DIR / "nex_loop_state.json"
try: state = json.loads(state_file.read_text())
except: state = {}
state["cycle"]        = state.get("cycle", 0) + 1
state["total_earned"] = state.get("total_earned", 0) + len(novel)
state["last_run"]     = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
state_file.write_text(json.dumps(state, indent=2))

print(f"[AGI] Cycle {state['cycle']} complete — {len(novel)}/{len(all_sc)} flagged")
PYTHON
