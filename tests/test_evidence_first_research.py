"""A research finding carries how it is known, and the HTML view cannot outlive the record (P2).

Checked across 177 installed skill descriptions: none owns *findings with provenance*. The five
existing report producers emit decisions, sequences or rubric scores — none says what we found,
how we know it, and what stayed open. That gap is what this skill fills.

The load-bearing rule is that every claim is graded, and the grades are a closed set. A report
where "we measured 3.1x" and "it should be about 3x" look alike is the failure this prevents —
this session shipped a cost claim that turned out to be four times the measured figure, and the
only reason it was caught was someone re-deriving it by hand.

The markdown record is the artefact. The HTML is a view rendered from it, written outside the
repository: a generated page that gets committed becomes a second source of truth, and within a
month nobody can say which one is current.
"""
from __future__ import annotations

import pytest

SCRIPT = "features/common/skills/evidence-first-research/scripts/render_report.py"

RECORD = """# Research: does the fast lane actually save time

**Date:** 2026-08-01
**Question:** How long does the pre-push gate take, and what would skipping lanes save?

## Findings

### F1 — The whole gate takes 75 seconds [MEASURED]

Timed three consecutive pushes on this machine.

**Evidence:** `.lefthook/pre-push/verify.sh` run directly; 14s + 12s + 49s.

### F2 — The gate was already selective [READ]

`_lanes_for` has routed by changed path since it was written.

**Evidence:** `.lefthook/pre-push/verify.sh:120-160`.

### F3 — Most pushes are docs-only [INFERRED]

Reasoning from the changelog cadence, not from a count of pushes.

### F4 — Windows behaves the same [UNVERIFIED]

**Evidence:** none — no Windows machine was available.

## Still open

- Whether the 49s pytest lane is dominated by collection or by the tests themselves.
"""


@pytest.fixture(name="renderer")
def _renderer(load_script):
    return load_script(SCRIPT)


class TestEveryFindingIsGraded:
    """The grades are a closed set; an ungraded claim is the thing this skill exists to stop."""

    def test_the_grades_are_exactly_these_four(self, renderer):
        assert renderer.GRADES == ("MEASURED", "READ", "INFERRED", "UNVERIFIED")

    def test_each_finding_keeps_its_grade(self, renderer):
        findings = renderer.parse_findings(RECORD)

        assert [f["grade"] for f in findings] == ["MEASURED", "READ", "INFERRED", "UNVERIFIED"]
        assert [f["id"] for f in findings] == ["F1", "F2", "F3", "F4"]

    def test_an_ungraded_finding_is_refused(self, renderer):
        record = "## Findings\n\n### F1 — a claim with no grade\n\nbody\n"

        with pytest.raises(ValueError, match="F1"):
            renderer.parse_findings(record)

    def test_an_unknown_grade_is_refused(self, renderer):
        """`[PROBABLY]` must fail loudly, not pass through as a fifth grade nobody defined."""
        record = "## Findings\n\n### F1 — a claim [PROBABLY]\n\nbody\n"

        with pytest.raises(ValueError, match="PROBABLY"):
            renderer.parse_findings(record)

    def test_a_measured_finding_without_evidence_is_refused(self, renderer):
        """MEASURED is the strongest claim available; it may not be the cheapest to write."""
        record = "## Findings\n\n### F1 — 75 seconds [MEASURED]\n\nno evidence line here\n"

        with pytest.raises(ValueError, match="F1"):
            renderer.parse_findings(record)

    def test_an_unverified_finding_needs_no_evidence(self, renderer):
        """Saying you did not check is itself honest; demanding a citation for it is not."""
        record = "## Findings\n\n### F1 — Windows is the same [UNVERIFIED]\n\nnobody looked\n"

        assert renderer.parse_findings(record)[0]["grade"] == "UNVERIFIED"


class TestTheReportIsSelfContained:
    """A strict CSP and an offline reader: nothing may be fetched at view time."""

    def test_no_external_host_is_referenced(self, renderer):
        html = renderer.render(RECORD)

        for scheme in ("http://", "https://", "//cdn", "src=\"//"):
            assert scheme not in html, f"the rendered page reaches for {scheme}"

    def test_the_charts_are_inline_svg(self, renderer):
        html = renderer.render(RECORD)

        assert "<svg" in html
        assert "<script src" not in html

    def test_the_question_and_every_finding_survive_rendering(self, renderer):
        html = renderer.render(RECORD)

        assert "does the fast lane actually save time" in html
        for finding in ("F1", "F2", "F3", "F4"):
            assert finding in html

    def test_what_stayed_open_is_rendered(self, renderer):
        """A research report that drops its open questions is a report that claims completeness."""
        html = renderer.render(RECORD)

        assert "collection" in html


class TestTheProvenanceChartCountsWhatIsThere:
    """The headline chart is the grade mix; it must come from the record, not be decorative."""

    def test_the_mix_is_counted_from_the_findings(self, renderer):
        mix = renderer.provenance_mix(renderer.parse_findings(RECORD))

        assert mix == {"MEASURED": 1, "READ": 1, "INFERRED": 1, "UNVERIFIED": 1}

    def test_a_grade_with_no_findings_is_still_named(self, renderer):
        """A zero that is not drawn reads as a grade nobody considered."""
        record = "## Findings\n\n### F1 — a claim [INFERRED]\n\nbody\n"

        mix = renderer.provenance_mix(renderer.parse_findings(record))

        assert mix == {"MEASURED": 0, "READ": 0, "INFERRED": 1, "UNVERIFIED": 0}


class TestTheFiveChartKinds:
    """Each kind is declared in the record and rendered as SVG; an unknown kind is refused."""

    def test_every_kind_renders(self, renderer):
        for kind, body in renderer.EXAMPLE_CHARTS.items():
            svg = renderer.render_chart(kind, body)

            assert svg.startswith("<svg"), f"{kind} did not render"
            assert "</svg>" in svg

    def test_the_kinds_are_exactly_five(self, renderer):
        assert len(renderer.CHART_KINDS) == 5

    def test_an_unknown_kind_is_refused(self, renderer):
        with pytest.raises(ValueError, match="pie"):
            renderer.render_chart("pie", "a: 1\n")

    def test_a_bar_chart_carries_its_values(self, renderer):
        svg = renderer.render_chart("bars", "title: seconds\npytest: 49\npylint: 12\n")

        assert "pytest" in svg and "49" in svg
        assert "pylint" in svg and "12" in svg


class TestTheHtmlIsWrittenOutsideTheRepository:
    """A generated view that gets committed becomes a second source of truth."""

    def test_the_default_output_is_not_under_the_repo(self, renderer, tmp_path):
        target = renderer.output_path(tmp_path, "2026-08-01-fast-lane")

        assert tmp_path not in target.parents
        assert target.name.endswith(".html")

    def test_writing_refuses_a_path_inside_the_repository(self, renderer, tmp_path):
        inside = tmp_path / "docs" / "work" / "x.html"
        inside.parent.mkdir(parents=True)

        with pytest.raises(ValueError, match="inside"):
            renderer.write_report(RECORD, inside, repo_root=tmp_path)

    def test_writing_outside_the_repository_succeeds(self, renderer, tmp_path):
        outside = tmp_path.parent / f"{tmp_path.name}-out" / "report.html"

        written = renderer.write_report(RECORD, outside, repo_root=tmp_path)

        assert written.is_file()
        assert "does the fast lane" in written.read_text(encoding="utf-8")


class TestADefaultSkillArrivesWithoutBeingNamed:
    """Delivered is not discoverable (#261) — the regression this class was written for.

    `evidence-first-research` moved from `optIn` to `default` in 0.169.0 (ADR-0028), so the
    contract it pins changed: it arrives with the default catalog rather than by
    `config.include.skills`. Discoverability — the half #261 actually shipped broken — is
    unchanged, and it is what these tests keep watching.
    """

    SKILL = "evidence-first-research"

    def _scaffolded(self, bl, root, make_scaffolder):
        from scaffold_helpers import _config  # noqa: PLC0415  (test-local helper)

        skills = bl.default_skills_in(root / "features" / "common" / "skills")
        target = make_scaffolder.target
        make_scaffolder(config=_config(agents=["claude"]), skills=skills).run(
            generated_at="2026-08-01T00:00:00Z")
        return target

    def test_it_is_in_the_default_catalog(self, load_script, root):
        bl = load_script("engine/badger_lib.py")

        assert self.SKILL in bl.default_skills_in(root / "features" / "common" / "skills")

    def test_it_is_delivered_and_discoverable(self, load_script, root, make_scaffolder):
        bl = load_script("engine/badger_lib.py")
        target = self._scaffolded(bl, root, make_scaffolder)

        assert (target / ".ai-badger" / "skills" / self.SKILL / "SKILL.md").is_file()
        link = target / ".claude" / "skills" / self.SKILL
        assert link.exists(), f".claude/skills/{self.SKILL} is absent — the agent cannot find it"
        assert (link / "SKILL.md").is_file(), "the discovery link resolves to nothing"

    def test_the_renderer_and_references_travel_with_it(self, load_script, root, make_scaffolder):
        """A skill whose script did not ship is a procedure step that cannot be run."""
        bl = load_script("engine/badger_lib.py")
        target = self._scaffolded(bl, root, make_scaffolder)
        home = target / ".ai-badger" / "skills" / self.SKILL

        assert (home / "scripts" / "render_report.py").is_file()
        assert (home / "references" / "provenance.md").is_file()
        assert (home / "references" / "report-template.md").is_file()


class TestTheChecksCouldFail:
    """Every refusal above must be reachable, or the parser is a pass-through."""

    def test_the_valid_record_parses_clean(self, renderer):
        assert len(renderer.parse_findings(RECORD)) == 4

    def test_a_record_with_no_findings_section_is_refused(self, renderer):
        with pytest.raises(ValueError, match="Findings"):
            renderer.parse_findings("# Research: nothing\n\nno findings here\n")
