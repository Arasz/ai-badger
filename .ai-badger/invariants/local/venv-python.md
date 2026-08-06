# Run Python through the repo .venv

Python commands in this repo (tests, tooling, gates) run with `.venv/bin/python3`
from the main checkout. Worktrees have no `.venv` of their own — invoke the main
checkout's `.venv/bin/python3` directly; the system `/usr/bin/python3` lacks the
required packages (jsonschema, pytest).
