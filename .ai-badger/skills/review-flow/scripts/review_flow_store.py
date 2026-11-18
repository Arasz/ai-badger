"""Review-flow persistence: one `review_flows` row per flow, read-validate-mutate-CAS.

Every read decodes and validates the payload as a `ReviewFlow`; every write validates the
mutated flow first and stores it under a compare-and-swap on the row revision. The tracking
root is `AI_BADGER_TRACKING_ROOT` when set, else the nearest ai-badger project's tracking dir.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Tuple

from pydantic import ValidationError

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import review_flow_model as model  # pylint: disable=wrong-import-position
import review_rules as rules_mod  # pylint: disable=wrong-import-position

TRACKING_ROOT_ENV = "AI_BADGER_TRACKING_ROOT"


def _load_badger_store() -> Any:
    """The store beside this file; another copy cached under the bare name is never used."""
    path = SCRIPT_DIR / "badger_store.py"
    cached = sys.modules.get("badger_store")
    if cached is not None and Path(getattr(cached, "__file__", "")).resolve() == path:
        return cached
    name = "review_flow_store._badger_store"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - the file ships beside this one
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


badger_store = _load_badger_store()


class FlowStoreError(RuntimeError):
    """A store refusal; `code` is the envelope code the CLI reports."""

    code = "store_error"


class FlowNotFound(FlowStoreError):
    """No flow with that id."""

    code = "not_found"


class FlowExists(FlowStoreError):
    """A different flow already uses that id."""

    code = "already_exists"


class FlowConflictError(FlowStoreError):
    """The row is not at the revision the caller expected; re-read and retry."""

    code = "conflict"


class FlowInvalid(FlowStoreError):
    """The stored payload, or the mutated flow, fails the `ReviewFlow` model."""

    code = "invalid_state"


# ------------------------------------------------------------------ root


def _project_root(start: Path) -> Optional[Path]:
    for ancestor in (start, *start.parents):
        if (ancestor / ".ai-badger" / "config.json").is_file():
            return _main_checkout(ancestor)
    return None


def _main_checkout(project: Path) -> Path:
    """The main checkout for a linked worktree that has its own marker, else `project`."""
    try:
        done = subprocess.run(["git", "-C", str(project), "worktree", "list", "--porcelain"],
                              capture_output=True, text=True, check=False, timeout=10,
                              env=rules_mod.git_env())
    except (OSError, subprocess.SubprocessError):
        return project
    first = next((line[len("worktree "):] for line in done.stdout.splitlines()
                  if line.startswith("worktree ")), None)
    main = Path(first).resolve() if first and done.returncode == 0 else None
    if main and main != project.resolve() and (main / ".ai-badger" / "config.json").is_file():
        return main
    return project


def tracking_root() -> Path:
    """`AI_BADGER_TRACKING_ROOT`, else `<project>/.ai-badger/task-tracking` from the cwd."""
    explicit = os.environ.get(TRACKING_ROOT_ENV)
    if explicit:
        return Path(explicit)
    project = _project_root(Path.cwd()) or Path.cwd()
    return project / ".ai-badger" / "task-tracking"


@contextlib.contextmanager
def _transaction() -> Iterator[Any]:
    """One BEGIN IMMEDIATE transaction on a fresh store: commit, or roll back on any error."""
    os.environ[TRACKING_ROOT_ENV] = str(tracking_root())
    try:
        store = badger_store.open_tracking()
        store.conn.execute("BEGIN IMMEDIATE")
    except (sqlite3.Error, OSError) as exc:
        raise FlowStoreError(f"tracking store unavailable: {exc}") from exc
    try:
        yield store
        store.conn.commit()
    except BaseException:
        store.conn.rollback()
        raise
    finally:
        store.close()


# ------------------------------------------------------------------ payloads


def payload_of(flow: "model.ReviewFlow") -> str:
    """The canonical stored JSON of a flow."""
    return flow.model_dump_json()


def _decode(flow_id: str, payload: str) -> "model.ReviewFlow":
    try:
        return model.ReviewFlow.model_validate(json.loads(payload))
    except (ValueError, ValidationError) as exc:
        raise FlowInvalid(f"stored flow {flow_id!r} is invalid: {exc}") from exc


def _validated(flow: Any) -> "model.ReviewFlow":
    try:
        return model.ReviewFlow.model_validate(flow.model_dump(mode="json"))
    except ValidationError as exc:
        raise FlowInvalid(f"the flow fails the model: {exc}") from exc


def _row(store: Any, flow_id: str) -> dict:
    row = store.flow_row(flow_id)
    if row is None:
        raise FlowNotFound(f"no review flow {flow_id!r}")
    return row


# ------------------------------------------------------------------ verbs


def get(flow_id: str) -> Tuple["model.ReviewFlow", int]:
    """The validated flow and its revision; `FlowNotFound` when absent."""
    with _transaction() as store:
        row = _row(store, flow_id)
        return _decode(flow_id, row["payload"]), row["revision"]


def create(flow: "model.ReviewFlow") -> Tuple[int, bool]:
    """Store a new flow at revision 0; an identical existing flow returns `(rev, False)`."""
    flow = _validated(flow)
    with _transaction() as store:
        row = store.flow_row(flow.flow_id)
        if row is not None:
            existing = _decode(flow.flow_id, row["payload"])
            if (existing.repo, existing.pr) != (flow.repo, flow.pr):
                raise FlowExists(f"flow {flow.flow_id!r} reviews {existing.repo}#{existing.pr}")
            return row["revision"], False
        return store.flow_upsert(flow.flow_id, payload_of(flow)), True


def update(flow_id: str, mutate: Callable[["model.ReviewFlow"], "model.ReviewFlow"],
           expected_revision: Optional[int] = None) -> Tuple["model.ReviewFlow", int, bool]:
    """Read, mutate, validate and CAS-write one flow; an unchanged flow writes nothing.

    Returns `(flow, revision, changed)`. A revision other than `expected_revision` (when given)
    raises `FlowConflictError`; whatever `mutate` raises propagates and nothing is written.
    """
    with _transaction() as store:
        row = _row(store, flow_id)
        if expected_revision is not None and row["revision"] != expected_revision:
            raise FlowConflictError(f"flow {flow_id!r} is at revision {row['revision']}, "
                                    f"not {expected_revision}; re-read and retry")
        current = _decode(flow_id, row["payload"])
        mutated = _validated(mutate(current))
        payload = payload_of(mutated)
        if payload == row["payload"]:
            return mutated, row["revision"], False
        try:
            revision = store.flow_upsert(flow_id, payload, expected_revision=row["revision"])
        except badger_store.FlowConflict as exc:
            raise FlowConflictError(str(exc)) from exc
        return mutated, revision, True
