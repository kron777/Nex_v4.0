"""
nex/nex_belief_index.py — importlib shim (circular-import proof)
=================================================================
Loads ~/Desktop/nex/nex_belief_index.py by absolute path so Python
can never confuse it with this file, regardless of sys.path order.
DO NOT add logic here. Edit the root file only.
"""
import importlib.util as _util
import sys as _sys
from pathlib import Path as _Path

_ROOT    = _Path(__file__).resolve().parent.parent / "nex_belief_index.py"
_MODNAME = "nex_belief_index"

# Load and register under the canonical module name only if not already loaded
if _MODNAME not in _sys.modules:
    _spec = _util.spec_from_file_location(_MODNAME, str(_ROOT))
    _mod  = _util.module_from_spec(_spec)
    _sys.modules[_MODNAME] = _mod   # register BEFORE exec to break any re-entry
    _spec.loader.exec_module(_mod)  # NOW execute it so BeliefIndex etc. are defined

# Re-export everything from the root module so
# "from nex.nex_belief_index import BeliefIndex" works too
from nex_belief_index import *  # noqa: F401, F403
from nex_belief_index import (  # noqa: F401
    BeliefIndex,
    get_index,
    retrieve,
    retrieve_for_conversation,
    thin_topics,
    rich_topics,
)
