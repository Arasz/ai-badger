"""The state a scaffold run shares between its collaborators.

One context object is the only channel between them: no collaborator reaches another
through `self`.
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
    # The mcp catalog's side of the same channel: every server a stack's stack-mcp.json names,
    # carrying the `instructions` its features/<stack>/mcp/<name>/server.md holds (ADR-0014).
    mcp_described: List[Dict[str, Any]] = field(default_factory=list)
    mcp_described_filled: bool = False
    # Manifest bookkeeping: shared state, not Scaffolder behaviour.
    record_template: Callable[[Path, Path], None] = _discard_template_record
