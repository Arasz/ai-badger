"""Regression: the framework supports exactly four agents — claude, copilot, hermes, pi.

ADR-0016 removed junie support (0.82.0). These tests pin the three-agent scope so a
future re-addition has to be a deliberate decision that updates this file, the schemas,
and the catalog together.
"""
from conftest import _test_write


def test_agent_names_include_pi(load_script):
    """AGENT_NAMES includes pi as the fourth agent."""
    badger = load_script("engine/badger_lib.py")
    assert "pi" in badger.AGENT_NAMES
    assert len(badger.AGENT_NAMES) == 4


def test_detect_never_reports_junie(tmp_path, load_script, monkeypatch):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    monkeypatch.setattr(detect.Path, "home", staticmethod(lambda: tmp_path / "empty-home"))
    (tmp_path / ".junie").mkdir()
    _test_write(tmp_path / "AGENTS.md", "# guidance\n", encoding="utf-8")

    assert "junie" not in detect.detect_agents(tmp_path)


def test_agent_schemas_do_not_name_junie(root):
    for name in ("agents", "config", "manifest", "skills-source", "stack-mcp", "support"):
        text = (root / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8")
        assert "junie" not in text.lower(), f"schemas/{name}.schema.json still names junie"


def test_detect_reports_pi(tmp_path, load_script, monkeypatch):
    """detect_agents() includes pi when .pi/ directory exists."""
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    monkeypatch.setattr(detect.Path, "home", staticmethod(lambda: tmp_path / "empty-home"))
    (tmp_path / ".pi").mkdir()

    agents = detect.detect_agents(tmp_path)
    assert "pi" in agents


def test_pi_feature_directory_exists(root):
    """features/pi/ directory structure exists."""
    assert (root / "features" / "pi").is_dir()
    assert (root / "features" / "pi" / "stack.json").exists()