"""Write the project's .ai-badger/config.json at the end of a scaffold, keeping its data lock.

A re-scaffold rebuilds the config from detection, which knows nothing about `dataPolicy`, so an
existing lock is carried over — and an existing config that cannot be read as an object locks
too, as it does at runtime. A prior object form that the schema accepts is kept verbatim; any
other prior value is written back as the plain `local-only` lock.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import badger_lib as bl

LOCAL_ONLY = "local-only"


def write_config(aib: Path, config: Dict[str, Any], framework_version: str,
                 notes: List[str], root: Path) -> Dict[str, Any]:
    """Dump *config* stamped with *framework_version* to <aib>/config.json, keeping a lock that
    *root*'s config schema accepts; the config as written."""
    written = dict(config)
    written["frameworkVersion"] = framework_version
    note = _keep_data_policy(aib / "config.json", written, root)
    if note:
        notes.append(note)
    bl.dump_json(aib / "config.json", written)
    return written


def _keep_data_policy(path: Path, config: Dict[str, Any], root: Path) -> str:
    """Set `dataPolicy` on *config* from the on-disk *path* when it should stay locked; the note."""
    if "dataPolicy" in config or not os.path.lexists(path):
        return ""
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prior = None
    if not isinstance(prior, dict):
        why = "because the existing config could not be read as an object"
    elif "dataPolicy" not in prior:
        return ""
    elif isinstance(prior["dataPolicy"], dict) and _valid_policy(prior["dataPolicy"], root):
        config["dataPolicy"] = prior["dataPolicy"]
        return "kept dataPolicy with its allowHosts from the existing config"
    elif isinstance(prior["dataPolicy"], dict):
        why = ("from the existing config; its object form was invalid, so its allowHosts "
               "allowlist was dropped")
    else:
        why = "from the existing config"
    config["dataPolicy"] = LOCAL_ONLY
    return f"kept dataPolicy '{LOCAL_ONLY}' {why} (third-party egress stays locked)"


def _valid_policy(policy: Dict[str, Any], root: Path) -> bool:
    """Whether *policy* satisfies the `dataPolicy` subschema of *root*'s config schema."""
    schema = bl.load_json(root / "schemas" / "config.schema.json")
    return not bl.validate(policy, schema["properties"]["dataPolicy"])
