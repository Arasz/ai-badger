"""Ownership boundaries for native Codex discovery outputs."""
from pathlib import Path


def symlink_parent(path: Path, root: Path) -> bool:
    """True if an output or intermediate project directory is a symlink."""
    return any(part.is_symlink() for part in (path, *path.parents) if part != root and root in part.parents)
