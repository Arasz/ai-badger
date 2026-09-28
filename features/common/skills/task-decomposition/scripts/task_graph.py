"""Graph operations over a `TaskPlan` (ready sets, waves, guards, checklist).

Reserved by S2 so the module path is frozen (DR6); the operations land in S5. Import-clean by
design: nothing here imports the server, the store or the vendored `badger_store.py`, so both
this module and `task_plan_model.py` load without a tracking store present.
"""
from __future__ import annotations

__all__: list = []
