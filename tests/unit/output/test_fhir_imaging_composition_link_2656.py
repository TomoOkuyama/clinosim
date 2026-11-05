"""Issue #2656: an imaging report Composition references its DiagnosticReport."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.documents.imaging_report import _bb_imaging_report_compositions
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import RADIOLOGY_DR_ID_PREFIX, _bb_diagnostic_reports

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("country", ["us", "jp"])
def test_every_section_points_at_the_report_and_its_study(country: str) -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_fhir_radiology_dr import _make_ctx, _sample_study

    ctx = _make_ctx([_sample_study()], country=country)
    [dr] = [r for r in _bb_diagnostic_reports(ctx) if r["id"].startswith(RADIOLOGY_DR_ID_PREFIX)]
    [comp] = _bb_imaging_report_compositions(ctx)
    expected = [{"reference": f"DiagnosticReport/{dr['id']}"}, dr["imagingStudy"][0]]
    assert comp["section"]
    for section in comp["section"]:
        assert section["entry"] == expected
