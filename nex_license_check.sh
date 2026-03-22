#!/bin/bash
# NEX LICENSE CHECK v2 — auto-kills stuck port, no stderr suppression
NEX_DIR="$HOME/.nex"
KEY_FILE="$NEX_DIR/license.key"
VALIDATOR="$(dirname "$0")/nex_license_validator.py"

# Kill any stuck license server
fuser -k 17749/tcp 2>/dev/null; sleep 0.3

# If key file exists, validate silently first
if [[ -f "$KEY_FILE" ]]; then
    python3 "$VALIDATOR"
    exit $?
fi

# No key — run full validator (opens browser + waits)
python3 "$VALIDATOR"
exit $?
