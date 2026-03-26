#!/usr/bin/env python3
"""
run_py_se_wire.py — wires nex_signal_engine into run.py
Run from ~/Desktop/nex/: python3 run_py_se_wire.py
"""
from pathlib import Path

RUN = Path(__file__).parent / "run.py"
BAK = Path(__file__).parent / "run.py.pre_se_wire"
assert RUN.exists(), "run.py not found"

src = RUN.read_text()
if "_se_wire_applied" in src:
    print("✓ Already patched."); exit(0)

BAK.write_text(src)
print(f"✓ Backup: {BAK}")
ok = 0

# PATCH 1 — init after _ai init block
ANCHOR_1 = (
    "            except Exception as _ai_init_e:\n"
    "                print(f'  [AI] init failed: {_ai_init_e}')\n"
    "                _ai = None\n"
)
INSERT_1 = (
    "            except Exception as _ai_init_e:\n"
    "                print(f'  [AI] init failed: {_ai_init_e}')\n"
    "                _ai = None\n"
    "            # _se_wire_applied\n"
    "            try:\n"
    "                from nex_signal_engine import get_signal_engine as _get_se\n"
    "                _se = _get_se()\n"
    "                _se.init()\n"
    "            except Exception as _se_init_e:\n"
    "                print(f'  [SE] init failed: {_se_init_e}')\n"
    "                _se = None\n"
)
if ANCHOR_1 in src:
    src = src.replace(ANCHOR_1, INSERT_1, 1)
    print("✓ Patch 1: _se init injected"); ok += 1
else:
    print("✗ Patch 1 FAILED")

# PATCH 2 — se.tick() after _ai.tick() block
ANCHOR_2 = (
    "                        except Exception as _aite:\n"
    "                            print(f'  [AI] tick error: {_aite}')\n"
    "                        # ── 8. SELF-TRAINING WATERMARK CHECK ─────────────"
)
INSERT_2 = (
    "                        except Exception as _aite:\n"
    "                            print(f'  [AI] tick error: {_aite}')\n"
    "                        # ── SIGNAL ENGINE TICK ───────────────────────────\n"
    "                        try:\n"
    "                            if '_se' in dir() and _se is not None:\n"
    "                                _se_beliefs = (_query_beliefs(min_confidence=0.0, limit=500)\n"
    "                                               if _query_beliefs else [])\n"
    "                                _se.tick(cycle=cycle, beliefs=_se_beliefs, log_fn=nex_log)\n"
    "                        except Exception as _sete:\n"
    "                            print(f'  [SE] tick error: {_sete}')\n"
    "                        # ── 8. SELF-TRAINING WATERMARK CHECK ─────────────"
)
if ANCHOR_2 in src:
    src = src.replace(ANCHOR_2, INSERT_2, 1)
    print("✓ Patch 2: _se.tick() wired"); ok += 1
else:
    print("✗ Patch 2 FAILED")

# PATCH 3 — low-value filter gate before contradiction engine
ANCHOR_3 = "                        # ── CONTRADICTION ENGINE (#5) ─────────────────────"
INSERT_3 = (
    "                        # ── LOW-VALUE SIGNAL FILTER ──────────────────────\n"
    "                        try:\n"
    "                            if '_se' in dir() and _se is not None and '_avg_conf_real' in dir():\n"
    "                                _tension_proxy = min(1.0, len(conversations) / 20.0) if conversations else 0.3\n"
    "                                if not _se.should_process(_avg_conf_real, _tension_proxy):\n"
    "                                    nex_log('signal', f'[Signal] LOW VALUE cycle={cycle} conf={_avg_conf_real:.2f} — skipping heavy cognition')\n"
    "                                    time.sleep(120)\n"
    "                                    continue\n"
    "                        except Exception:\n"
    "                            pass\n"
    "                        # ── CONTRADICTION ENGINE (#5) ─────────────────────"
)
if ANCHOR_3 in src:
    src = src.replace(ANCHOR_3, INSERT_3, 1)
    print("✓ Patch 3: low-value filter gate wired"); ok += 1
else:
    print("✗ Patch 3 FAILED")

RUN.write_text(src)
print(f"\n{ok}/3 patches applied.")
print("Verify: python3 -m py_compile run.py")
