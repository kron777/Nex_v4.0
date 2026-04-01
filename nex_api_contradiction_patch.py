#!/usr/bin/env python3
"""
Wire contradiction_report() into /api/chat for Pro+ users.
Run once: python3 nex_api_contradiction_patch.py
"""
from pathlib import Path

path = Path("~/Desktop/nex/nex_api.py").expanduser()
src  = path.read_text()

if "contradiction_report" in src:
    print("Already patched.")
    exit(0)

OLD = '''            from nex_contradiction import detect_contradictions, contradiction_summary
            contradictions = detect_contradictions(query)
            contradiction_flag = contradiction_summary(contradictions)'''

NEW = '''            from nex_contradiction import (
                detect_contradictions, contradiction_summary, contradiction_report
            )
            contradictions     = detect_contradictions(query)
            contradiction_flag = contradiction_summary(contradictions)
            contradiction_rpt  = contradiction_report(contradictions)'''

if OLD not in src:
    print("ERROR: target not found")
    exit(1)

src = src.replace(OLD, NEW, 1)

# Also add contradiction_report to response payload
OLD2 = '        "contradictions":   contradictions,\n        "contradiction_flag": contradiction_flag,'
NEW2 = ('        "contradictions":        contradictions,\n'
        '        "contradiction_flag":    contradiction_flag,\n'
        '        "contradiction_report":  contradiction_rpt if tier_allows("reasoning_chain") else None,')

if OLD2 in src:
    src = src.replace(OLD2, NEW2, 1)

# Initialise contradiction_rpt before the try block
OLD3 = '    contradictions = []\n    contradiction_flag = None'
NEW3 = '    contradictions     = []\n    contradiction_flag  = None\n    contradiction_rpt   = {"detected": False, "count": 0, "conflicts": []}'

if OLD3 in src:
    src = src.replace(OLD3, NEW3, 1)

path.write_text(src)
print("PATCHED — contradiction_report() wired into /api/chat")
print("  Pro+ users now get structured conflict report in every response")
