"""Plan-of-care LOINC specialization — Issue #1105 (C10 P2) partial.

Before this PR, 92.6% of JP Composition sections carrying LOINC
18776-5 ("Plan of care note") were the generic `計画` slug. The
section_catalog mapped every plan-family slug (`care_plan`,
`patient_education`, `treatment_plan`, `test_schedule`, `surgery_
schedule`, `follow_up`, etc.) to 18776-5 uniformly, so downstream
consumers relying on LOINC-based navigation lost the semantic
signal already present in the slug.

Fix: route the two slugs whose specific LOINC could be verified
against the NLM Clinical Tables API to their specific codes:

  - care_plan (看護計画)   → 64295-9 "Nurse Plan of Care Note"
  - patient_education (患者教育) → 34895-3 "Patient education and consents"

The issue-suggested LOINCs 18761-7, 18763-3, 18804-5, 18821-9 were
verified against the NLM API and found to be miscategorized (e.g.
18761-7 = "Transfer Summary Note", not "Treatment plan note"), so
those slugs stay at 18776-5 pending a follow-up with authoritative
LOINC search. Per `feedback_verify_fhir_profile_uri_from_spec` we
never emit an unverified code.
"""

from __future__ import annotations

import yaml


def _load_catalog() -> dict:
    from pathlib import Path

    p = (
        Path(__file__).resolve().parents[3]
        / "clinosim"
        / "modules"
        / "document"
        / "reference_data"
        / "section_catalog.yaml"
    )
    return yaml.safe_load(p.read_text())


def _load_loinc() -> dict:
    from pathlib import Path

    p = Path(__file__).resolve().parents[3] / "clinosim" / "codes" / "data" / "loinc.yaml"
    return yaml.safe_load(p.read_text())


def test_care_plan_routes_to_nurse_plan_of_care_loinc() -> None:
    cat = _load_catalog()
    assert cat["care_plan"]["loinc"] == "64295-9"


def test_patient_education_routes_to_education_loinc() -> None:
    cat = _load_catalog()
    assert cat["patient_education"]["loinc"] == "34895-3"


def test_new_loincs_are_registered_in_loinc_yaml() -> None:
    loinc = _load_loinc()
    codes = loinc.get("codes", {})
    assert "64295-9" in codes
    assert "34895-3" in codes
    # Verified via clinicaltables.nlm.nih.gov/api/loinc_items 2026-09-09.
    assert codes["64295-9"]["en"] == "Nurse Plan of Care Note"
    assert codes["34895-3"]["en"] == "Patient education and consents"


def test_generic_plan_slug_still_uses_18776_5() -> None:
    # The catch-all `plan` slug (SOAP note P) stays on the generic
    # LOINC — this PR only touches slugs whose specific LOINC is verified.
    cat = _load_catalog()
    assert cat["plan"]["loinc"] == "18776-5"


def test_unverified_plan_slugs_stay_at_18776_5() -> None:
    # Issue-suggested LOINCs for these slugs were verified false-positive
    # against the NLM API (e.g. 18761-7 = "Transfer Summary Note", not
    # "Treatment plan note"). Keep at generic until a real code is found.
    cat = _load_catalog()
    for slug in ("treatment_plan", "test_schedule", "surgery_schedule", "follow_up"):
        assert cat[slug]["loinc"] == "18776-5", f"{slug} was rerouted without verification"
