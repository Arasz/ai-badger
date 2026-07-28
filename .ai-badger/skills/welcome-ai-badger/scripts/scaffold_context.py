"""The state a scaffold run shares between its collaborators.

One context object is the only channel between them: no collaborator reaches another
through `self` (docs/plans/2026-07-28-wave-6-scaffold-collaborators.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Set


def _discard_template_record(source: Path, dest: Path) -> None:
    """Default provenance sink: a context with no manifest behind it records nothing."""


@dataclass
class ScaffoldContext:
    """Every attribute a scaffold collaborator reads or writes, and nothing else."""

    root: Path
    target: Path
    aib: Path
    config: Dict[str, Any]
    index: Dict[str, Any]
    stacks: List[str]
    skills: List[str]
    excluded: Dict[str, Set[str]]
    overwrite: bool = False
    notes: List[str] = field(default_factory=list)
    # Filled by McpTools and read by TemplateRendering — the cache lives here so neither
    # collaborator has to know the other exists.
    merged_external_tools: List[Dict[str, Any]] = field(default_factory=list)
    external_tools_merged: bool = False
    # Manifest bookkeeping: shared state, not Scaffolder behaviour.
    record_template: Callable[[Path, Path], None] = _discard_template_record
