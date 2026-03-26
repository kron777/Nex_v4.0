#!/usr/bin/env python3
"""
patch_cognition.py  —  Wires nex_homeostasis into nex/cognition.py
Run from /home/rr/Desktop/nex/:  python patch_cognition.py

Makes 3 targeted edits:
  1. Cooldown multiplier in run_synthesis() cluster priority sort
  2. belief_fitness() gate in promote_insights_to_beliefs()
  3. merge + mutate pass in scan_contradictions()
"""

import sys, shutil
from pathlib import Path

TARGET = Path(__file__).parent / "nex" / "cognition.py"
if not TARGET.exists():
    print(f"[ERROR] {TARGET} not found — run from /home/rr/Desktop/nex/")
    sys.exit(1)

backup = TARGET.with_suffix(".py.pre_homeostasis")
shutil.copy2(TARGET, backup)
print(f"  [backup] → {backup.name}")

src = TARGET.read_text()

PATCHES = []

# ── PATCH 1: Cooldown multiplier in cluster priority ────────────────────────
# Current sort key: size_score + drive_score
# We multiply by _hm.topic_priority() cooldown factor
OLD1 = """    def _cluster_priority(item):
        name, cluster = item
        size_score  = len(cluster["beliefs"])
        drive_score = _drive_topic_weights.get(name, 0) * 200  # drive boost
        return size_score + drive_score"""

NEW1 = """    def _cluster_priority(item):
        name, cluster = item
        size_score  = len(cluster["beliefs"])
        drive_score = _drive_topic_weights.get(name, 0) * 200  # drive boost
        base        = size_score + drive_score
        # Homeostasis cooldown multiplier — recently-synthesised topics get reduced priority
        try:
            import sys as _hms, os as _hmo
            _hms.path.insert(0, _hmo.path.join(_hmo.path.dirname(__file__), ".."))
            from nex_homeostasis import get_homeostasis as _ghm
            _hm_inst = _ghm()
            _cycle_proxy = int(__import__("time").time() / 30) % 100000
            base = _hm_inst.topic_priority(name, _cycle_proxy, base)
        except Exception:
            pass
        return base"""

PATCHES.append((OLD1, NEW1, "cooldown multiplier in cluster priority"))


# ── PATCH 2: belief_fitness gate in promote_insights_to_beliefs ─────────────
# Current gate: conf < min_confidence or count < min_beliefs
# Add: fitness gate from homeostasis
OLD2 = """            if conf < min_confidence or count < min_beliefs:
                continue
            if not summary or len(summary) < 20:
                continue"""

NEW2 = """            if conf < min_confidence or count < min_beliefs:
                continue
            if not summary or len(summary) < 20:
                continue
            # Homeostasis fitness gate — weak insights don't get promoted
            try:
                import sys as _fgs, os as _fgo
                _fgs.path.insert(0, _fgo.path.join(_fgo.path.dirname(__file__), ".."))
                from nex_homeostasis import get_homeostasis as _fghm
                _fit = _fghm().belief_fitness(ins)
                if _fit < 0.40:
                    _dbg("synth", f"[fitness] insight [{topic}] fitness={_fit:.2f} below threshold — skip promotion")
                    continue
            except Exception:
                pass"""

PATCHES.append((OLD2, NEW2, "belief_fitness gate in promote_insights_to_beliefs"))


# ── PATCH 3: merge + mutate pass at end of scan_contradictions ──────────────
# Add after the existing contradiction save, before return logs
OLD3 = """    if found > 0:
            save_json(CONTRADICTIONS_PATH, contradictions[-5000:])
            save_json(BELIEFS_PATH, beliefs)
            logs.append(("contra", f"Found {found} belief contradictions — decayed lower-confidence sides"))

    except Exception as e:
        logs.append(("warn", f"Contradiction scan error: {e}"))

    return logs"""

NEW3 = """    if found > 0:
            save_json(CONTRADICTIONS_PATH, contradictions[-5000:])
            save_json(BELIEFS_PATH, beliefs)
            logs.append(("contra", f"Found {found} belief contradictions — decayed lower-confidence sides"))

    except Exception as e:
        logs.append(("warn", f"Contradiction scan error: {e}"))

    # Homeostasis: merge + mutate pass on insights after contradiction resolution
    try:
        import sys as _ems, os as _emo
        _ems.path.insert(0, _emo.path.join(_emo.path.dirname(__file__), ".."))
        from nex_homeostasis import get_homeostasis as _emghm
        _hm_ev = _emghm()
        _ins_path = os.path.join(CONFIG_DIR, "insights.json")
        _raw_ins  = load_json(_ins_path, [])
        if _raw_ins:
            _evolved  = _hm_ev.evolve_insights(_raw_ins)
            if len(_evolved) != len(_raw_ins):
                save_json(_ins_path, _evolved)
                logs.append(("hm", f"[evolve] insights: {len(_raw_ins)} → {len(_evolved)} after merge/mutate"))
    except Exception as _eme:
        pass

    return logs"""

PATCHES.append((OLD3, NEW3, "merge + mutate pass in scan_contradictions"))


# ── Apply ────────────────────────────────────────────────────────────────────
applied = 0
for old, new, label in PATCHES:
    if old in src:
        src = src.replace(old, new, 1)
        print(f"  [✓] {label}")
        applied += 1
    else:
        print(f"  [!] SKIP (anchor not found): {label}")

TARGET.write_text(src)
print(f"\n  {applied}/{len(PATCHES)} patches applied → {TARGET.name}")
print(f"  Backup: {backup.name}")
