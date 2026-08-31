"""Thin re-export of the canonical debug_log (P2.2): one copy lives in <root>/hooks/.

Executes the canonical module into this module's own namespace, so the sibling-import
pattern (``import debug_log``) and tests patching module globals both hit canonical code.
"""
from pathlib import Path as _Path
import importlib.util as _ilu

_canonical = _Path(__file__).resolve().parents[3] / "hooks" / "debug_log.py"
exec(compile(_canonical.read_text(encoding="utf-8"), str(_canonical), "exec"), globals())  # pylint: disable=exec-used
