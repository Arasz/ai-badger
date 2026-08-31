"""TDD stub — implemented to green by P0.2 after tests/test_badger_store.py goes red."""
from __future__ import annotations

SCHEMA_VERSION = 1


def _now() -> str:
    raise NotImplementedError


def tracking_db_path() -> "object":
    raise NotImplementedError


def user_db_path() -> "object":
    raise NotImplementedError


def audit_db_path() -> "object":
    raise NotImplementedError
