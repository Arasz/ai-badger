# Adjustments — Dynamic Dispatch Pattern

Each subdirectory (`hermes/`, `copilot/`) contains agent-specific adjustment
scripts that customize the scaffolded output for a particular AI coding agent.

## How it works

1. `scaffold.py::run_adjustments()` iterates over `config["agents"]`
2. For each agent, loads `features/<agent>/adjustments/adjustment.json`
3. Dynamically imports each script listed in the manifest via `importlib.util`
4. Calls `adjust(context)` — returns `{'applied': bool, 'files': list, 'notes': str}`

## Why static analysis can't trace this

The call chain is: `scaffold.py` → `importlib.util.spec_from_file_location()` →
`mod.adjust(context)`. No direct import or call edge exists in the source code,
so code-review-graph (and any static analyzer) flags `adjust()` as dead code.

## Adding a new adjustment

1. Create `features/<agent>/adjustments/adjust_<feature>.py` with an
   `adjust(context: dict) -> dict` function
2. Add an entry to `features/<agent>/adjustments/adjustment.json`
3. The scaffold will pick it up automatically
