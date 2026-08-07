"""The catalog ships to strangers, so it must carry no real vault or account identifiers."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FEATURES = ROOT / "features"

UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")

# A placeholder is a UUID whose every hex digit is the same character. Real identifiers are
# not shaped that way, so this admits obviously-fake examples and nothing else.
PLACEHOLDER_RE = re.compile(r"\b([0-9a-f])\1{7}-(\1{4}-){3}\1{12}\b")

CREDENTIAL_RE = re.compile(
    r"""(
        gh[pousr]_[A-Za-z0-9]{16,}      # GitHub tokens
      | sk-[A-Za-z0-9]{20,}             # OpenAI-style keys
      | AKIA[0-9A-Z]{16}                # AWS access key ids
      | xox[baprs]-[A-Za-z0-9-]{10,}    # Slack tokens
    )""",
    re.VERBOSE,
)


def catalog_files():
    """Every tracked text file under features/, via git so untracked scratch is ignored."""
    out = subprocess.run(
        ["git", "ls-files", "features"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [ROOT / line for line in out.stdout.splitlines() if line]


def read(path):
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def test_no_real_uuid_identifiers_in_the_catalog():
    offenders = []
    for path in catalog_files():
        for match in UUID_RE.finditer(read(path)):
            if not PLACEHOLDER_RE.fullmatch(match.group(0)):
                offenders.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
    assert not offenders, (
            "the catalog ships to every consumer, so a real project/secret/tenant id in it is "
            "reconnaissance — replace with an all-same-digit placeholder:\n  "
            + "\n  ".join(offenders)
    )


def test_no_credential_shaped_strings_in_the_catalog():
    offenders = [
        f"{path.relative_to(ROOT)}: {match.group(0)[:12]}…"
        for path in catalog_files()
        for match in CREDENTIAL_RE.finditer(read(path))
    ]
    assert not offenders, "credential-shaped string in the catalog:\n  " + "\n  ".join(offenders)


@pytest.mark.parametrize(
    "sample",
    [
        "Project: `613165e6-7947-49e0-889b-b49d007c5b85`",
        "Secret id `f1d3c8e5-5391-4aef-8611-b49d007c8702`",
    ],
)
def test_the_uuid_check_could_fail(sample):
    """The identifiers 0.86.0 actually shipped must be caught, or the check proves nothing."""
    found = [m.group(0) for m in UUID_RE.finditer(sample)]
    assert found
    assert not any(PLACEHOLDER_RE.fullmatch(uuid) for uuid in found)


def test_the_uuid_check_admits_placeholders():
    for placeholder in ("00000000-0000-0000-0000-000000000000",
                        "11111111-1111-1111-1111-111111111111"):
        match = UUID_RE.search(placeholder)
        assert match and PLACEHOLDER_RE.fullmatch(match.group(0))


def test_the_credential_check_could_fail():
    assert CREDENTIAL_RE.search("AKIA" + "A" * 16)