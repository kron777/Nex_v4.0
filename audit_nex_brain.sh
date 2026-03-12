#!/bin/bash
echo "=== NEX BRAIN TERMINAL AUDIT ==="
echo "Date: $(date)"
echo ""

echo "--- 1. Log file status ---"
ls -la /tmp/nex_brain.log 2>/dev/null || echo "NO LOG FILE"
echo ""

echo "--- 2. Log file last 5 lines ---"
tail -5 /tmp/nex_brain.log 2>/dev/null || echo "EMPTY/MISSING"
echo ""

echo "--- 3. Is log growing? (wait 3s) ---"
S1=$(wc -c < /tmp/nex_brain.log 2>/dev/null || echo 0)
sleep 3
S2=$(wc -c < /tmp/nex_brain.log 2>/dev/null || echo 0)
echo "Before: $S1 bytes, After: $S2 bytes"
[ "$S2" -gt "$S1" ] && echo "LOG IS GROWING" || echo "LOG IS STATIC - BUFFERING ISSUE"
echo ""

echo "--- 4. run.py process ---"
ps aux | grep "run.py" | grep -v grep
echo ""

echo "--- 5. tail process running? ---"
ps aux | grep "tail -f" | grep -v grep
echo ""

echo "--- 6. Current nex alias ---"
grep "alias nex=" ~/.bashrc
echo ""
