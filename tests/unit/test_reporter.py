"""Unit tests for clinosim.audit.reporter — Markdown render + file write."""
from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.audit.reporter import render_markdown, write_markdown
from clinosim.audit.types import (
    AuditFinding,
    AuditResult,
    AxisResult,
    Severity,
)


def _make_result():
    res = AuditResult(
        cohort_dir=Path("/tmp/cohort"), modules=["hai"], axes=["structural", "clinical"],
    )
    res.add(
        "structural", "hai",
        AxisResult(
            axis="structural", module="hai",
            info={"WBC_n": 100, "WBC_refRange_pct": 100.0},
        ),
    )
    res.add(
        "clinical", "hai",
        AxisResult(
            axis="clinical", module="hai",
            findings=[AuditFinding(Severity.WARN, "rare-event cohort", {"n": 3})],
            info={"baseline_WBC_p50": 12029},
        ),
    )
    return res


@pytest.mark.unit
def test_render_contains_summary_table():
    md = render_markdown(_make_result())
    assert "## Summary" in md
    assert "| Module | structural | clinical |" in md
    assert "| hai | PASS | WARN |" in md


@pytest.mark.unit
def test_render_contains_per_axis_sections():
    md = render_markdown(_make_result())
    assert "### Axis 1: structural" in md
    assert "### Axis 2: clinical" in md
    assert "WBC_n=100" in md


@pytest.mark.unit
def test_render_records_findings():
    md = render_markdown(_make_result())
    assert "WARN" in md
    assert "rare-event cohort" in md


@pytest.mark.unit
def test_write_markdown_creates_file_and_parent(tmp_path: Path):
    out = tmp_path / "subdir" / "audit.md"
    write_markdown(_make_result(), out)
    assert out.exists()
    assert "## Summary" in out.read_text()


@pytest.mark.unit
def test_render_marks_overall_status_at_top():
    res = _make_result()
    md = render_markdown(res)
    assert "Overall: WARN" in md
