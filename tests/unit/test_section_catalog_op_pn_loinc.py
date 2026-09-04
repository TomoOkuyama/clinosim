"""B7 (#1072) partial fix: op_/pn_ procedural sections use 29554-3.

Pre-fix, 10 op_/pn_ procedural body-text slugs (anesthesia, specimens,
blood_loss, equipment, postop_plan, consent, analgesia, complications)
used the generic 18776-5 "Plan of care note" catch-all instead of the
correct 29554-3 "Procedure narrative" — the LOINC the section-catalog
header explicitly designates for "surgical / procedural body text"
(see section_catalog.yaml line 42).

This mattered because sibling op_/pn_ slugs (op_course, op_findings,
pn_course, pn_procedure_name) already used 29554-3, so a Composition
carrying an operative note showed a mix of "Plan of care" and
"Procedure narrative" sections for what is clinically one document.
EHR viewers group section types via LOINC, so this misassignment
fragmented the operative-note display.

The 10 affected slugs are documented at the top of section_catalog.yaml's
LOINC selection guidance:
    29554-3 "Procedure narrative" — surgical / procedural body text
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_YAML = (
    Path(__file__).resolve().parents[2]
    / "clinosim"
    / "modules"
    / "document"
    / "reference_data"
    / "section_catalog.yaml"
)

_REASSIGNED_SLUGS = (
    "op_anesthesia",
    "op_specimens",
    "op_blood_loss",
    "op_equipment",
    "op_postop_plan",
    "pn_consent",
    "pn_analgesia",
    "pn_complications",
    "pn_specimens",
    "pn_postop_plan",
)


@pytest.fixture(scope="module")
def catalog() -> dict:
    with _YAML.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.mark.parametrize("slug", _REASSIGNED_SLUGS)
def test_op_pn_slug_uses_procedure_narrative_loinc(catalog: dict, slug: str) -> None:
    entry = catalog[slug]
    assert entry["loinc"] == "29554-3", f"{slug} must use 29554-3 (Procedure narrative), got {entry['loinc']!r}"


def test_op_slugs_have_consistent_loinc_family(catalog: dict) -> None:
    """All op_ slugs (excluding op_surgeon which is 51897-7 Care team) belong
    to the 29554-3 Procedure narrative family."""
    op_slugs = {s: e for s, e in catalog.items() if isinstance(e, dict) and s.startswith("op_")}
    for slug, entry in op_slugs.items():
        if slug == "op_surgeon":
            # Care team member — correctly on 51897-7
            assert entry["loinc"] == "51897-7"
        else:
            assert entry["loinc"] == "29554-3", f"op_ slug {slug!r} broke the 29554-3 invariant: {entry['loinc']!r}"


def test_pn_slugs_have_consistent_loinc_family(catalog: dict) -> None:
    """All pn_ slugs (excluding pn_performer which is 51897-7 Care team) belong
    to the 29554-3 Procedure narrative family."""
    pn_slugs = {s: e for s, e in catalog.items() if isinstance(e, dict) and s.startswith("pn_")}
    for slug, entry in pn_slugs.items():
        if slug == "pn_performer":
            assert entry["loinc"] == "51897-7"
        else:
            assert entry["loinc"] == "29554-3", f"pn_ slug {slug!r} broke the 29554-3 invariant: {entry['loinc']!r}"


def test_18776_5_catch_all_scope_shrunk(catalog: dict) -> None:
    """Regression guard against re-drift: 18776-5 must not grow back above 20
    entries. The pre-fix count was 27; this PR takes it to 17.
    A rising count is a signal that another PR is defaulting to the catch-all
    without checking the LOINC selection guidance in section_catalog.yaml
    header (lines 38-49). Increment this ceiling only with an explicit
    per-slug review."""
    count_18776_5 = sum(1 for e in catalog.values() if isinstance(e, dict) and e.get("loinc") == "18776-5")
    assert count_18776_5 <= 20, (
        f"18776-5 catch-all grew to {count_18776_5} entries — review the new "
        f"additions against section_catalog.yaml header lines 38-49 and pick a "
        f"more specific LOINC where possible."
    )
