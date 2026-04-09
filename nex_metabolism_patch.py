#!/usr/bin/env python3
"""
nex_metabolism_patch.py
Run this ONCE to patch nex_source_router.py to read metabolism settings.
"""

import re
from pathlib import Path

SOURCE_ROUTER = Path.home() / "Desktop/nex/nex_source_router.py"
BACKUP        = Path.home() / "Desktop/nex/nex_source_router.py.bak"

METABOLISM_READER = '''
# ── Metabolism control — reads ~/.config/nex/metabolism.json ─────────────────
import json as _met_json
from pathlib import Path as _met_path

def _get_metabolism_intervals():
    """Read current metabolism intervals from config. Falls back to BALANCED."""
    _defaults = {
        "rss": 15, "hn_reddit": 30, "wikipedia": 60,
        "arxiv": 240, "youtube": 720, "crawl4ai": 360
    }
    try:
        cfg = _met_path("~/.config/nex/metabolism.json").expanduser()
        if cfg.exists():
            data = _met_json.loads(cfg.read_text())
            intervals = data.get("intervals", {})
            if intervals:
                return intervals
    except Exception:
        pass
    return _defaults
# ─────────────────────────────────────────────────────────────────────────────
'''

INTERVAL_PATCH = '''
    def _update_intervals_from_metabolism(self):
        """Reload intervals from metabolism config file."""
        intervals = _get_metabolism_intervals()
        from datetime import timedelta
        self._intervals = {
            "rss":       timedelta(minutes=intervals.get("rss", 15)),
            "hn_reddit": timedelta(minutes=intervals.get("hn_reddit", 30)),
            "wikipedia": timedelta(minutes=intervals.get("wikipedia", 60)),
            "arxiv":     timedelta(minutes=intervals.get("arxiv", 240)),
            "youtube":   timedelta(minutes=intervals.get("youtube", 720)),
            "crawl4ai":  timedelta(minutes=intervals.get("crawl4ai", 360)),
        }
'''

def patch():
    if not SOURCE_ROUTER.exists():
        print(f"❌ Not found: {SOURCE_ROUTER}")
        return

    # Backup
    BACKUP.write_text(SOURCE_ROUTER.read_text())
    print(f"✅ Backup saved: {BACKUP}")

    content = SOURCE_ROUTER.read_text()

    # 1. Add metabolism reader after imports
    if "_get_metabolism_intervals" not in content:
        insert_after = "log = logging.getLogger(\"nex.source_router\")"
        content = content.replace(insert_after, insert_after + "\n" + METABOLISM_READER)
        print("✅ Added metabolism reader")
    else:
        print("⚠️  Metabolism reader already present")

    # 2. Add method to SourceRouter class
    if "_update_intervals_from_metabolism" not in content:
        insert_before = "    def start(self):"
        content = content.replace(insert_before, INTERVAL_PATCH + "\n" + insert_before)
        print("✅ Added _update_intervals_from_metabolism method")
    else:
        print("⚠️  Method already present")

    # 3. Call metabolism update at top of _run loop
    old_run_start = "    def _run(self):\n        while not self._stop.is_set():\n            try:\n                now = datetime.now()"
    new_run_start = "    def _run(self):\n        while not self._stop.is_set():\n            try:\n                self._update_intervals_from_metabolism()  # reload metabolism settings\n                now = datetime.now()"
    if "self._update_intervals_from_metabolism" not in content:
        content = content.replace(old_run_start, new_run_start)
        print("✅ Patched _run loop to reload metabolism each cycle")
    else:
        print("⚠️  _run loop already patched")

    # Write patched file
    SOURCE_ROUTER.write_text(content)
    print(f"\n✅ Patch complete: {SOURCE_ROUTER}")
    print("   Restart NEX for changes to take effect:")
    print("   pkill -f 'run.py' && pkill -f 'nex_api.py' && pkill -f 'nex_scheduler.py' && sleep 2 && nex")

if __name__ == "__main__":
    patch()
