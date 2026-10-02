"""Write the project's .ai-badger/config.json at the end of a scaffold, keeping its data lock.

A re-scaffold rebuilds the config from detection, which knows nothing about `dataPolicy`, so an
existing lock is carried over — and an existing config that cannot be read as an object locks
too, as it does at runtime.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import badger_lib as bl


def write_config(aib: Path, config: Dict[str, Any], framework_version: str,
                 notes: List[str]) -> Dict[str, Any]:
    """Dump *config* stamped with *framework_version* to <aib>/config.json, keeping a lock; the
    config as written."""
    written = dict(config)
    written["frameworkVersion"] = framework_version
    note = _keep_data_policy(aib / "config.json", written)
    if note:
        notes.append(note)
    bl.dump_json(aib / "config.json", written)
    return written


def _keep_data_policy(path: Path, config: Dict[str, Any]) -> str:
    """Set `dataPolicy` on *config* from the on-disk *path* when it should stay locked; the note."""
    if "dataPolicy" in config or not os.path.lexists(path):
        return ""
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prior = None
    if not isinstance(prior, dict):
        why = "because the existing config could not be read as an object"
    elif "dataPolicy" in prior:
        why = "from the existing config"
    else:
        return ""
    config["dataPolicy"] = "local-only"
    return f"kept dataPolicy 'local-only' {why} (third-party egress stays locked)"
