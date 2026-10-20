"""The ADR index's `Amended` column must be derived from the records, not remembered.

An ADR is never edited after acceptance, so the only place an amendment can live is the
index — and the index is a hand-maintained table, which is exactly the shape that drifts.
This test makes the column a *derived* field: every date and every ADR pointer it shows
must be one the record's own file carries, and a record whose file shows an amendment,
supersession or restatement cannot have an empty cell.

The rules it encodes:

  1. the table has an `Amended` column and every row has the header's cell count;
  2. the index lists every ADR file on disk exactly once (it mirrors the directory);
  3. a record with no amendment history in its file has `—` in the column, and a record
     with history names every date and every ADR the history mentions, and invents none.

Rule 3 is deliberately two-sided. The "names every date" side stops an amendment from
being invisible in the index; the "invents none" side stops the index from claiming a
change a record never had.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ADR_DIR = Path(__file__).resolve().parents[1] / "docs" / "adr"
INDEX = ADR_DIR / "README.md"

DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
ADR_REF = re.compile(r"\bADR-(\d{4})\b")

# Lines that record what happened TO this record. A record that *acts* on another
# (`**Supersedes:**`, `**Amends:**`) is not itself amended, so those shapes are excluded.
SELF_HISTORY = (
    re.compile(r"^#{2,}\s*Amendment\b"),
    re.compile(r"\*\*Amendment\b"),
    re.compile(r"\bAmended (?:by\b|\d{4}-\d{2}-\d{2})"),
    re.compile(r"\*\*Amended by:?\*\*"),
    re.compile(r"\*\*Superseded (?:by|in part by):?\*\*"),
    re.compile(r"\bSuperseded in part by \[?ADR-\d{4}"),
    re.compile(r"\bamended \d{4}-\d{2}-\d{2}"),
    re.compile(r"\*\*Status:\*\*.*\bSuperseded \("),
    re.compile(r"\brestated\b.*\bby\b.*ADR-\d{4}"),
    re.compile(r"\*\*Restated at\b"),
)


def _split_row(line: str) -> list[str]:
    """Split a table row on unescaped pipes only (`\\|` is content, not a column break)."""
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def _rows() -> list[tuple[int, list[str]]]:
    """Every table row of the index, as (line number, cells)."""
    rows = []
    for number, line in enumerate(INDEX.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("| ["):
            continue
        rows.append((number, _split_row(line)))
    return rows


def _header() -> list[str]:
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        if line.startswith("| #"):
            return _split_row(line)
    raise AssertionError("the ADR index has no header row")


AMENDMENT_SECTION = re.compile(r"^##\s+Amendments?\b")
SUB_HEADING = re.compile(r"^#{3,6}\s+")


def _history(path: Path) -> tuple[set[str], set[str]]:
    return _history_text(path.read_text(encoding="utf-8"))


def _history_text(text: str) -> tuple[set[str], set[str]]:
    """The dates and ADR numbers this record's own file records as its history.

    Two shapes are read. A line that names an amendment, a supersession or a restatement
    contributes its own dates and ADR pointers. An `## Amendment …` / `## Amendments …`
    section contributes the dates on its heading and on the sub-headings inside it — one
    entry per amendment. The section's prose is not read: a date mentioned in passing is
    not an amendment.
    """
    dates: set[str] = set()
    adrs: set[str] = set()
    in_amendment_section = False

    for line in text.splitlines():
        if line.startswith("## "):
            in_amendment_section = bool(AMENDMENT_SECTION.match(line))
            if in_amendment_section:
                dates.update(DATE.findall(line))
            continue
        if in_amendment_section:
            if SUB_HEADING.match(line):
                dates.update(DATE.findall(line))
            continue
        if not any(pattern.search(line) for pattern in SELF_HISTORY):
            continue
        dates.update(DATE.findall(line))
        adrs.update(ADR_REF.findall(line))
    return dates, adrs


def test_the_history_rule_reads_an_amendments_section_with_subheadings():
    """A record may file its amendments under a plural heading, one entry per sub-heading.

    The dates on the sub-headings are the amendment dates; a date mentioned in the section's
    prose is not, and a date on the record's own acceptance line is not either.
    """
    text = (
        "# 0001 — Example\n"
        "Date: 2026-01-01\n"
        "Status: Accepted\n"
        "## Amendments\n"
        "\n"
        "### 2026-02-03 — the first change\n"
        "\n"
        "prose that mentions 2026-04-05 in passing\n"
        "\n"
        "### 2026-06-07 — the second change\n"
    )
    dates, adrs = _history_text(text)
    assert dates == {"2026-02-03", "2026-06-07"}, dates
    assert not adrs, adrs


def test_the_index_has_an_amended_column():
    assert "Amended" in _header(), (
        "the ADR index needs an `Amended` column: an accepted ADR is never edited, so the "
        "index is the only place an amendment can be recorded"
    )


def test_every_row_has_the_headers_cell_count():
    width = len(_header())
    wrong = [f"line {number}: {len(cells)} cells" for number, cells in _rows() if len(cells) != width]
    assert not wrong, f"ADR index rows do not match the header's {width} columns: {wrong}"


def test_the_index_lists_every_adr_on_disk_once():
    on_disk = {path.name for path in ADR_DIR.glob("[0-9]*.md")}
    indexed = [cells[0] for _number, cells in _rows()]
    linked = {re.search(r"\(([^)]+)\)", link).group(1) for link in indexed}
    assert not on_disk - linked, f"docs/adr/README.md does not link: {sorted(on_disk - linked)}"
    assert not linked - on_disk, f"docs/adr/README.md links records that are gone: {sorted(linked - on_disk)}"
    assert len(indexed) == len(set(indexed)), "an ADR is listed twice in the index"


def test_the_amended_column_is_derived_from_the_record_it_summarises():
    problems = []
    for _number, cells in _rows():
        link, amended = cells[0], cells[_header().index("Amended")]
        filename = re.search(r"\(([^)]+)\)", link).group(1)
        path = ADR_DIR / filename
        if not path.exists():
            continue
        dates, adrs = _history(path)
        if not dates and not adrs:
            if amended != "—":
                problems.append(f"{filename}: the cell says {amended!r} but the record shows no amendment")
            continue
        if amended == "—":
            problems.append(f"{filename}: the record shows an amendment ({sorted(dates)} {sorted(adrs)}) and the cell is empty")
            continue
        missing = sorted(d for d in dates if d not in amended)
        missing_adrs = sorted(a for a in adrs if f"ADR-{a}" not in amended)
        if missing or missing_adrs:
            problems.append(f"{filename}: the cell omits {missing} {missing_adrs}")
        text = path.read_text(encoding="utf-8")
        invented = sorted(d for d in DATE.findall(amended) if d not in text)
        invented += sorted(f"ADR-{a}" for a in ADR_REF.findall(amended) if f"ADR-{a}" not in text)
        if invented:
            problems.append(f"{filename}: the cell names {invented}, which the record does not mention")
    assert not problems, "the `Amended` column drifted from the records:\n  " + "\n  ".join(problems)
