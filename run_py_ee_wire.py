#!/usr/bin/env python3
"""
run_py_ee_wire.py — wires nex_execution_engine into run.py
Run from ~/Desktop/nex/: python3 run_py_ee_wire.py
"""
from pathlib import Path

RUN = Path(__file__).parent / "run.py"
BAK = Path(__file__).parent / "run.py.pre_ee_wire"
assert RUN.exists(), "run.py not found"

src = RUN.read_text()
if "_ee_wire_applied" in src:
    print("✓ Already patched."); exit(0)

BAK.write_text(src)
print(f"✓ Backup: {BAK}")
ok = 0

# PATCH 1 — _ee init after _se init block
ANCHOR_1 = (
    "            except Exception as _se_init_e:\n"
    "                print(f'  [SE] init failed: {_se_init_e}')\n"
    "                _se = None\n"
)
INSERT_1 = (
    "            except Exception as _se_init_e:\n"
    "                print(f'  [SE] init failed: {_se_init_e}')\n"
    "                _se = None\n"
    "            # _ee_wire_applied\n"
    "            try:\n"
    "                from nex_execution_engine import get_execution_engine as _get_ee\n"
    "                _ee = _get_ee()\n"
    "                _ee.init()\n"
    "            except Exception as _ee_init_e:\n"
    "                print(f'  [EE] init failed: {_ee_init_e}')\n"
    "                _ee = None\n"
)
if ANCHOR_1 in src:
    src = src.replace(ANCHOR_1, INSERT_1, 1)
    print("✓ Patch 1: _ee init injected"); ok += 1
else:
    print("✗ Patch 1 FAILED")

# PATCH 2 — _ee.tick() after _se tick block
ANCHOR_2 = (
    "                        except Exception as _sete:\n"
    "                            print(f'  [SE] tick error: {_sete}')\n"
    "                        # ── 8. SELF-TRAINING WATERMARK CHECK ─────────────"
)
INSERT_2 = (
    "                        except Exception as _sete:\n"
    "                            print(f'  [SE] tick error: {_sete}')\n"
    "                        # ── EXECUTION ENGINE TICK ────────────────────────\n"
    "                        try:\n"
    "                            if '_ee' in dir() and _ee is not None:\n"
    "                                _ee_signals = _se.get_top_signals() if '_se' in dir() and _se else []\n"
    "                                _ee.tick(cycle=cycle, signals=_ee_signals, log_fn=nex_log)\n"
    "                        except Exception as _eete:\n"
    "                            print(f'  [EE] tick error: {_eete}')\n"
    "                        # ── 8. SELF-TRAINING WATERMARK CHECK ─────────────"
)
if ANCHOR_2 in src:
    src = src.replace(ANCHOR_2, INSERT_2, 1)
    print("✓ Patch 2: _ee.tick() wired"); ok += 1
else:
    print("✗ Patch 2 FAILED")

RUN.write_text(src)
print(f"\n{ok}/2 patches applied.")
print("Verify: python3 -m py_compile run.py")
