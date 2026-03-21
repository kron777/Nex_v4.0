# ── CONFIG_DIR fix (injected by nex_fix.py) ───────────────────────────────
import os as _os
from pathlib import Path as _Path

_CONFIG_DIR = _Path(_os.environ.get("NEX_CONFIG_DIR",
                    _os.path.expanduser("~/.config/nex")))
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
# ─────────────────────────────────────────────────────────────────────────────

# Usage — add to any module that uses _CONFIG_DIR:
#   from patches.nex_config_dir_patch import _CONFIG_DIR
