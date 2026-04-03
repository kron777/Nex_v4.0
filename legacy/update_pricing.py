#!/usr/bin/env python3
"""Update pricing across nex_api.py in all locations."""
from pathlib import Path
import re

path = Path("~/Desktop/nex/nex_api.py").expanduser()
src  = path.read_text()

replacements = [
    # Admin UI dropdown
    ('PERSONAL — $199',          'PERSONAL — $199 one-time'),
    ('PROFESSIONAL — $2,500/mo', 'PROFESSIONAL — $299/mo'),
    ('ENTERPRISE — $15,000/mo',  'ENTERPRISE — $499/mo'),
    # /api/version route
    ('"$199 one-time"',          '"$199 one-time"'),   # unchanged
    ('"$2,500/month"',           '"$299/month"'),
    ('"$15,000/month"',          '"$499/month"'),
    # send_key_email price lookup
    ('"professional": "$2,500/month"', '"professional": "$299/month"'),
    ('"enterprise":   "$15,000/month"', '"enterprise":   "$499/month"'),
    # Any other string occurrences
    ('$2,500/mo',   '$299/mo'),
    ('$2,500/month','$299/month'),
    ('$15,000/mo',  '$499/mo'),
    ('$15,000/month','$499/month'),
    ('$2500',       '$299'),
    ('$15000',      '$499'),
]

changes = 0
for old, new in replacements:
    if old in src and old != new:
        count = src.count(old)
        src   = src.replace(old, new)
        changes += count
        print(f"  {count}x  {old!r:45} → {new!r}")

path.write_text(src)
print(f"\nTotal replacements: {changes}")
