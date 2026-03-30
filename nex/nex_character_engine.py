"""
nex/nex_character_engine.py — re-export shim
=============================================
Canonical implementation: ~/Desktop/nex/nex_character_engine.py

This shim exists so both import styles resolve to the same singleton:
    from nex_character_engine import get_engine      # root-level callers
    from nex.nex_character_engine import get_engine  # package-level callers

DO NOT add logic here. Edit the root file only.
"""

# Ensure the NEX root directory is on sys.path BEFORE the import so Python
# finds ~/Desktop/nex/nex_character_engine.py and not this shim (avoids
# circular import regardless of how sys.path is ordered at call time).
import sys as _sys
from pathlib import Path as _Path

_nex_root = str(_Path(__file__).resolve().parent.parent)
if _nex_root not in _sys.path:
    _sys.path.insert(0, _nex_root)

# Now safe to import — will always hit the root file
from nex_character_engine import (  # noqa: F401, E402
    CharacterEngine,
    BeliefRetriever,
    StanceReader,
    DriveReader,
    BridgeDetector,
    StyleEngine,
    ConversationMemory,
    get_engine,
    generate_post,
    generate_reflection,
    generate_thought,
    generate_response,
    TEMPLATES,
    MODES,
    QUESTIONS,
)

import nex_character_engine as _root_mod  # noqa: E402

def __getattr__(name: str):
    """Forward any other attribute lookups to the root module."""
    return _root_mod.__getattr__(name)
