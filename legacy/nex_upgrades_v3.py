"""
nex_upgrades_v3.py — root shim → nex/nex_upgrades_v3.py
"""
import importlib.util as _util, sys as _sys
from pathlib import Path as _Path

_INNER = _Path(__file__).resolve().parent / "nex" / "nex_upgrades_v3.py"
_MODNAME = "nex_upgrades_v3_inner"

if _MODNAME not in _sys.modules:
    _spec = _util.spec_from_file_location(_MODNAME, str(_INNER))
    _mod  = _util.module_from_spec(_spec)
    _sys.modules[_MODNAME] = _mod
    _spec.loader.exec_module(_mod)
else:
    _mod = _sys.modules[_MODNAME]

from nex_upgrades_v3_inner import NexUpgradesV3, get_v3, upgrade  # noqa: F401

def __getattr__(name: str):
    return getattr(_mod, name)
