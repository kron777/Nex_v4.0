#!/bin/bash
# ════════════════════════════════════════════════════════════════
# deploy_opener.sh — Wire DynamicResponseOpener into run.py
# Patches the actual LLM call site, not just post-processing.
# Usage:
#   mv ~/Downloads/nex_dynamic_opener.py ~/Desktop/nex/
#   mv ~/Downloads/deploy_opener.sh ~/Desktop/nex/
#   chmod +x ~/Desktop/nex/deploy_opener.sh
#   cd ~/Desktop/nex && source venv/bin/activate && ./deploy_opener.sh
# ════════════════════════════════════════════════════════════════
set -euo pipefail

NEX_DIR="$HOME/Desktop/nex"
RUN_PY="$NEX_DIR/run.py"
TS=$(date +%s)

echo "══════════════════════════════════════"
echo " NEX Dynamic Response Opener"
echo " Fixing 'As NEX...' at source"
echo "══════════════════════════════════════"

[[ -f "$RUN_PY" ]]                              || { echo "ERROR: run.py not found"; exit 1; }
[[ -f "$NEX_DIR/nex_dynamic_opener.py" ]]       || { echo "ERROR: nex_dynamic_opener.py not found"; exit 1; }

cp "$RUN_PY" "$RUN_PY.bak_opener_$TS"
echo "[✓] Backed up run.py"

# ── Find where system prompt / LLM messages are built ────────
echo "[*] Analysing run.py for LLM call sites..."
python3 - << 'PYEOF'
from pathlib import Path
import re

run_py = Path.home() / "Desktop/nex/run.py"
src    = run_py.read_text()
lines  = src.splitlines()

# Find key patterns
patterns = {
    "system_prompt":   r'system_prompt\s*=',
    "messages_array":  r'"role"\s*:\s*"system"',
    "llm_call":        r'(?:requests\.post|openai|completions\.create|chat/completions)',
    "generate_reply":  r'def\s+(?:generate|_generate|get_response|llm_reply|nex_reply)',
}

for name, pat in patterns.items():
    for i, ln in enumerate(lines):
        if re.search(pat, ln, re.IGNORECASE):
            print(f"  {name:20s} → line {i+1}: {ln.strip()[:80]}")
            break
PYEOF

# ── Patch: add opener import at top-level ────────────────────
python3 - << 'PYEOF'
import re, ast
from pathlib import Path

RUN  = Path.home() / "Desktop/nex/run.py"
src  = RUN.read_text()

if "nex_dynamic_opener" in src:
    print("[opener] Already patched — skipping import")
else:
    IMPORT = (
        "\n# ── Dynamic response opener ────────────────────────────\n"
        "try:\n"
        "    import sys as _sys\n"
        "    _sys.path.insert(0, '/home/rr/Desktop/nex')\n"
        "    from nex_dynamic_opener import get_opener as _get_opener\n"
        "    _opener = _get_opener()\n"
        "except Exception as _opener_ex:\n"
        "    print(f'[opener] Load failed: {_opener_ex}')\n"
        "    _opener = None\n"
    )
    # Inject after import signal
    m = re.search(r'import signal\n', src)
    if m:
        src = src[:m.end()] + IMPORT + src[m.end():]
        print("[opener] Import injected after 'import signal'")
    else:
        src = IMPORT + src
        print("[opener] Import prepended")

# ── Find system_prompt assignments and patch them ─────────────
lines   = src.splitlines(keepends=True)
patched = 0

for i, ln in enumerate(lines):
    stripped = ln.strip()
    # Look for system_prompt = "..." or system_prompt = f"..."
    if (re.match(r'\s*system_prompt\s*=\s*["\'\(f]', ln) and
            "get_opener" not in ln and "_opener" not in ln and
            patched < 3):  # patch up to 3 sites

        indent = len(ln) - len(ln.lstrip())
        pad    = " " * indent

        # Insert injection call after this line
        injection_line = (
            f"{pad}if '_opener' in dir() and _opener:\n"
            f"{pad}    system_prompt = _opener.inject_system_prompt(system_prompt)\n"
        )
        lines.insert(i + 1, injection_line)
        patched += 1
        print(f"[opener] System prompt patched at line {i+1}")

# ── Find LLM output and patch post-generation strip ──────────
# Look for where response text is extracted from LLM response
strip_patched = 0
for i, ln in enumerate(lines):
    # Common patterns where LLM text is extracted
    if (re.search(r'(?:reply|response|text|output|content)\s*=.*(?:choices|message|content|text)',
                  ln, re.IGNORECASE) and
            "_opener" not in ln and "strip_output" not in ln and
            strip_patched < 2):

        indent = len(ln) - len(ln.lstrip())
        pad    = " " * indent
        # Extract variable name being assigned
        m = re.match(r'\s*(\w+)\s*=', ln)
        if m:
            varname = m.group(1)
            if varname in ("reply", "response_text", "text", "output", "content",
                           "generated", "result", "resp_text"):
                strip_line = (
                    f"{pad}if '_opener' in dir() and _opener and isinstance({varname}, str):\n"
                    f"{pad}    {varname} = _opener.strip_output({varname})\n"
                )
                lines.insert(i + 1, strip_line)
                strip_patched += 1
                print(f"[opener] Strip patched at line {i+1} (var={varname})")

src = "".join(lines)

try:
    ast.parse(src)
    print("[opener] AST OK ✓")
except SyntaxError as e:
    all_lines = src.splitlines()
    print(f"[opener] SyntaxError line {e.lineno}: {e.msg}")
    for j in range(max(0, e.lineno-3), min(len(all_lines), e.lineno+3)):
        print(f"  {j+1:4d}  {all_lines[j]}")
    print("[opener] File NOT written")
    import sys; sys.exit(1)

RUN.write_text(src)
print(f"[opener] run.py written — {patched} prompt patches, {strip_patched} strip patches")
PYEOF

echo "[✓] run.py patched"

# ── Also patch nex_telegram.py and nex_discord.py reply funcs ─
python3 - << 'PYEOF'
import re
from pathlib import Path

NEX_DIR = Path.home() / "Desktop/nex"

for fname in ["nex_telegram.py", "nex_discord.py",
              "nex/agent_brain.py", "nex/nex_self.py"]:
    fpath = NEX_DIR / fname
    if not fpath.exists(): continue
    src = fpath.read_text()
    if "strip_output" in src or "nex_dynamic_opener" in src: continue

    # Find reply/response variable assignments after LLM calls
    lines   = src.splitlines(keepends=True)
    patched = 0

    for i, ln in enumerate(lines):
        if re.search(r'(?:reply|response|text|content)\s*=.*(?:choices|message|\.text|\.content)',
                     ln, re.IGNORECASE):
            m = re.match(r'\s*(\w+)\s*=', ln)
            if m:
                vn     = m.group(1)
                indent = len(ln) - len(ln.lstrip())
                pad    = " " * indent
                strip  = (
                    f"{pad}try:\n"
                    f"{pad}    from nex_dynamic_opener import get_opener as _gop\n"
                    f"{pad}    if isinstance({vn}, str): {vn} = _gop().strip_output({vn})\n"
                    f"{pad}except Exception: pass\n"
                )
                lines.insert(i + 1, strip)
                patched += 1
                if patched >= 2: break

    if patched:
        fpath.write_text("".join(lines))
        print(f"[opener] Patched {fname} ({patched} sites)")
PYEOF

# ── Syntax final check ────────────────────────────────────────
python3 -m py_compile "$RUN_PY" && echo "[✓] run.py syntax OK"
python3 -m py_compile "$NEX_DIR/nex_dynamic_opener.py" && echo "[✓] nex_dynamic_opener.py syntax OK"

# ── Git commit + push ─────────────────────────────────────────
cd "$NEX_DIR"
git add nex_dynamic_opener.py run.py nex_telegram.py nex_discord.py 2>/dev/null || true
git add nex/agent_brain.py nex/nex_self.py 2>/dev/null || true
git commit -m "dynamic opener: inject varied opening instructions into system prompt pre-LLM; strip 'As NEX/I believe/I think' post-generation; 20 opening injection variants rotated"
git push

echo ""
echo "══════════════════════════════════════"
echo " Dynamic opener deployed. Restart:"
echo "   pkill -f run.py; sleep 2; nex"
echo " Check:"
echo "   tail -f /tmp/nex_opener.log"
echo "══════════════════════════════════════"
