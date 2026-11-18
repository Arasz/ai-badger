"""The review-flow test design doc covers every acceptance criterion of the plan."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "work" / "2026-11-18-review-flow-test-design.md"
PLAN_ACS = ROOT / "tests" / "fixtures" / "review_flow" / "plan_acs.json"
STEP_IDS = {
    "skeleton", "store-table", "render", "diff-anchor", "flow-model", "rules-store",
    "flow-machine", "publish-github", "cli", "skill-doc", "catalog-wiring", "e2e",
}
PAIR = re.compile(r"^[a-z0-9-]+/ac\d+$")


def _rows():
    rows = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in ("step/ac",) or set(cells[0]) <= set("-: "):
            continue
        rows.append(cells)
    return rows


def test_header_is_exact():
    assert "| step/ac | test | failure mode | mutation |" in DOC.read_text(encoding="utf-8")


def test_every_step_id_appears():
    pairs = {r[0] for r in _rows()}
    assert STEP_IDS <= {p.split("/")[0] for p in pairs}


def test_every_row_is_complete_and_well_formed():
    rows = _rows()
    assert rows
    for pair, test, failure, mutation in rows:
        assert PAIR.match(pair), pair
        assert test and failure and mutation, pair
        assert "::" in test, pair


def test_every_plan_ac_is_covered():
    plan = json.loads(PLAN_ACS.read_text(encoding="utf-8"))
    assert set(plan) == STEP_IDS
    have = {r[0] for r in _rows()}
    missing = [f"{s}/{a}" for s, acs in plan.items() for a in acs if f"{s}/{a}" not in have]
    assert not missing
