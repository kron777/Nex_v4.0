#!/usr/bin/env python3
"""
Patch nex_belief_quality.py SOURCE_WEIGHTS to correctly weight self_research.
Run once: python3 fix_source_weights.py
"""
from pathlib import Path

path = Path("~/Desktop/nex/nex_belief_quality.py").expanduser()
src  = path.read_text()

old = '''SOURCE_WEIGHTS = {
    "arxiv":          1.0,
    "pubmed":         1.0,
    "wikipedia":      0.85,
    "auto_seeder":    0.70,
    "self_research":  0.70,
    "synthesis":      0.80,
    "human":          0.95,
    "groq":           0.65,
    "web":            0.60,
    "unknown":        0.50,
}'''

new = '''SOURCE_WEIGHTS = {
    "arxiv":               1.0,
    "pubmed":              1.0,
    "wikipedia":           0.85,
    "scheduler_saturation": 0.82,  # domain saturation — structured prompts
    "self_research":       0.88,   # NEX's own research — academic quality
    "synthesis":           0.80,
    "auto_seeder":         0.70,
    "human":               0.95,
    "groq":                0.65,
    "web":                 0.60,
    "unknown":             0.50,
}'''

if old in src:
    path.write_text(src.replace(old, new))
    print("PATCHED — source weights updated")
    print("  self_research:        0.70 → 0.88")
    print("  scheduler_saturation: (new) 0.82")
else:
    print("Pattern not found — check nex_belief_quality.py manually")
    print("Current SOURCE_WEIGHTS block:")
    for line in src.split('\n'):
        if 'SOURCE_WEIGHTS' in line or ('":' in line and any(k in line for k in ['arxiv','self','auto','human'])):
            print(f"  {line}")
