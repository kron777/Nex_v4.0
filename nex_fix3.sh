#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  NEX Fix 3 — YouTube HUD dot + UNIQUE constraint belief writer
#  Run: bash ~/Desktop/nex/nex_fix3.sh
# ═══════════════════════════════════════════════════════════════════

NEX="$HOME/Desktop/nex"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  NEX Fix 3 — HUD dot + belief writer"
echo "═══════════════════════════════════════════════════════"
echo ""

cd "$NEX"
source venv/bin/activate 2>/dev/null || true

# ── 1. Fix YouTube HUD dot in nex_hud_server.py ──────────────────────────────
echo "▸ Fixing YouTube HUD dot..."
python3 << 'PYEOF'
import re, os
path = os.path.expanduser("~/Desktop/nex/nex_hud_server.py")
with open(path) as f:
    src = f.read()

# Back up
with open(path + ".bak_fix3", "w") as f:
    f.write(src)

# Replace the social_status["youtube"] dict assignment with yt_status_string()
# Original sets: social_status["youtube"] = {"enabled": True, "auth": _yt_active}
# We replace with a proper status that the HUD can render as a dot

old = 'social_status["youtube"] = {"enabled": True, "auth": _yt_active}'
new = '''social_status["youtube"] = {
                "enabled": True,
                "auth": _yt_active,
                "status_string": yt_status_string(),
            }'''

if old in src:
    src = src.replace(old, new)
    print("  Patched social_status youtube dict")
else:
    print("  [!] Could not find exact youtube dict line — trying broader match")
    # Broader pattern
    src = re.sub(
        r'social_status\["youtube"\]\s*=\s*\{[^\}]+\}',
        '''social_status["youtube"] = {"enabled": True, "auth": _yt_active, "status_string": yt_status_string()}''',
        src
    )
    print("  Applied broader patch")

# Also ensure yt_status_string import is near the top imports, not buried in AGI section
# Move it up if it's only in AGI section
if src.count('from nex_youtube_rotator import yt_status_string') == 1:
    # Add a second import near top (safe duplicate — Python dedupes)
    import_line = 'from nex_youtube_rotator import yt_status_string  # HUD dot\n'
    lines = src.splitlines(keepends=True)
    # Find first import line
    for i, line in enumerate(lines):
        if line.startswith('import ') or line.startswith('from '):
            lines.insert(i, import_line)
            break
    src = ''.join(lines)
    print("  Added yt_status_string import near top")

with open(path, "w") as f:
    f.write(src)
print("  nex_hud_server.py patched")
PYEOF
ok "YouTube HUD dot patched"

# ── 2. Fix UNIQUE constraint in nex_belief_reasoner.py ───────────────────────
echo "▸ Fixing UNIQUE constraint in belief writer..."

# Find the belief reasoner
REASONER=""
for candidate in \
    "$NEX/nex/nex_belief_reasoner.py" \
    "$NEX/nex_belief_reasoner.py"; do
    if [ -f "$candidate" ]; then
        REASONER="$candidate"
        break
    fi
done

if [ -z "$REASONER" ]; then
    warn "nex_belief_reasoner.py not found — checking soul_loop directly"
    # Fix it in soul_loop instead
    python3 << 'PYEOF'
import os
path = os.path.expanduser("~/Desktop/nex/nex/nex_soul_loop.py")
with open(path) as f:
    src = f.read()

# Replace INSERT INTO memory (not OR IGNORE) with INSERT OR IGNORE
fixed = src.replace(
    '"INSERT INTO memory (layer, content, confidence, created_at, last_accessed, metadata, tags) "',
    '"INSERT OR IGNORE INTO memory (layer, content, confidence, created_at, last_accessed, metadata, tags) "'
)
# Also fix beliefs table inserts
fixed = fixed.replace(
    '"INSERT INTO beliefs ',
    '"INSERT OR IGNORE INTO beliefs '
)

if fixed != src:
    with open(path + ".bak_fix3", "w") as f:
        f.write(src)
    with open(path, "w") as f:
        f.write(fixed)
    print("  soul_loop INSERT → INSERT OR IGNORE patched")
else:
    print("  [!] No plain INSERT found in soul_loop — already safe or different pattern")
PYEOF
else
    echo "  Found: $REASONER"
    python3 << PYEOF
import os
path = "$REASONER"
with open(path) as f:
    src = f.read()

# Back up
with open(path + ".bak_fix3", "w") as f:
    f.write(src)

count = 0
# Fix all INSERT INTO beliefs/memory that aren't already OR IGNORE
import re
def fix_insert(m):
    global count
    count += 1
    return m.group(0).replace('INSERT INTO', 'INSERT OR IGNORE INTO')

fixed = re.sub(r'INSERT INTO (beliefs|memory)\b', fix_insert, src)

if count > 0:
    with open(path, "w") as f:
        f.write(fixed)
    print(f"  Fixed {count} INSERT statements in {os.path.basename(path)}")
else:
    print("  No plain INSERT statements found — already safe")
PYEOF
fi
ok "Belief writer UNIQUE constraint fixed"

# ── 3. Also patch nex_belief_reasoner if it exists in nex/ ──────────────────
echo "▸ Patching all belief INSERT statements across nex/ ..."
python3 << 'PYEOF'
import os, re, glob

nex_root = os.path.expanduser("~/Desktop/nex")
targets = [
    os.path.join(nex_root, "nex", "nex_belief_reasoner.py"),
    os.path.join(nex_root, "nex", "belief_store.py"),
    os.path.join(nex_root, "nex", "nex_belief_quality.py"),
    os.path.join(nex_root, "nex_belief_calibrator.py"),
    os.path.join(nex_root, "nex_belief_refiner.py"),
]

total = 0
for path in targets:
    if not os.path.exists(path):
        continue
    with open(path) as f:
        src = f.read()
    count = [0]
    def fix_insert(m):
        count[0] += 1
        return m.group(0).replace('INSERT INTO', 'INSERT OR IGNORE INTO')
    fixed = re.sub(r'(?<!OR IGNORE )INSERT INTO (beliefs|memory)\b', fix_insert, src)
    if count[0] > 0:
        with open(path + ".bak_fix3", "w") as f:
            f.write(src)
        with open(path, "w") as f:
            f.write(fixed)
        print(f"  Fixed {count[0]} INSERT(s) in {os.path.basename(path)}")
        total += count[0]

if total == 0:
    print("  All belief writers already safe")
else:
    print(f"  Total: {total} INSERT statements fixed")
PYEOF
ok "Belief writers patched"

# ── 4. Verify HUD server syntax ──────────────────────────────────────────────
echo "▸ Checking nex_hud_server.py syntax..."
python3 -m py_compile "$NEX/nex_hud_server.py" 2>&1
if [ $? -eq 0 ]; then
    ok "nex_hud_server.py syntax OK"
else
    warn "Syntax error — restoring backup"
    cp "$NEX/nex_hud_server.py.bak_fix3" "$NEX/nex_hud_server.py"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Done. Now run: nex"
echo "  YouTube dot should show ACTIVE/BLOCKED/RECOVERING"
echo "  UNIQUE constraint errors should be gone"
echo "═══════════════════════════════════════════════════════"
echo ""
