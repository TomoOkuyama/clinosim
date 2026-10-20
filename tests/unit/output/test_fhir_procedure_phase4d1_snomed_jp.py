"""Phase 4d.1: `_build_procedure` resolves SNOMED + JP display for
yaml-sourced chronic followup procedures.

Phase 4d (#1701 partial, PR #1722) added CPAP + polysomnography emission
on the CIF ``ProcedureRecord`` path via ``outpatient.py``. The yaml
carried ``snomed:`` + ``name_ja:`` fields but ``_build_procedure`` did
not consult them — so FHIR emit shipped CPT-only coding and English
text for JP. This test pins the Phase 4d.1 fix:

* ``_build_procedure`` resolves ``procedure_type`` through
  :func:`resolve_procedure_snomed` and attaches the SNOMED coding as a
  secondary entry alongside the primary (CPT) coding when a match is
  found.
* JP output translates ``CPAP therapy`` / ``Polysomnography`` display
  text via ``drug_names_ja.yaml``.
"""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_med_terms_ja
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_med_terms_cache() -> None:
    load_med_terms_ja.cache_clear()


def _cpap_proc() -> dict[str, object]:
    """Phase 4d outpatient.py emits CPAP therapy as CPT 99503."""
    return {
        "procedure_id": "proc-4d1-cpap",
        "patient_id": "pt-g4730",
        "encounter_id": "enc-g4730",
        "procedure_type": "CPAP therapy",
        "procedure_code": "99503",
        "procedure_code_us": "99503",
        "start_datetime": "2026-06-15T09:00:00",
        "end_datetime": "2026-06-15T09:15:00",
    }


def _polysomno_proc() -> dict[str, object]:
    """Phase 4d outpatient.py emits polysomnography as CPT 95810."""
    return {
        "procedure_id": "proc-4d1-poly",
        "patient_id": "pt-g4730",
        "encounter_id": "enc-g4730",
        "procedure_type": "Polysomnography",
        "procedure_code": "95810",
        "procedure_code_us": "95810",
        "start_datetime": "2026-06-15T09:00:00",
        "end_datetime": "2026-06-15T09:15:00",
    }


def _snomed_codings(resource: dict) -> list[dict]:
    sct = "http://snomed.info/sct"
    return [c for c in resource["code"].get("coding", []) if c.get("system") == sct]


# === SNOMED attachment (both countries) ===


def test_us_cpap_procedure_attaches_snomed_47545007() -> None:
    """US output of CPAP (CPT 99503) carries SNOMED 47545007 secondary coding."""
    res = _build_procedure(_cpap_proc(), "pt-g4730", 0, "US")
    sct_codings = _snomed_codings(res)
    assert len(sct_codings) == 1
    assert sct_codings[0]["code"] == "47545007"
    assert sct_codings[0]["display"] == "Continuous positive airway pressure ventilation treatment"


def test_us_polysomnography_procedure_attaches_snomed_60554003() -> None:
    """US output of Polysomnography (CPT 95810) carries SNOMED 60554003
    (verified 2026-10-20 via tx.fhir.org $lookup)."""
    res = _build_procedure(_polysomno_proc(), "pt-g4730", 0, "US")
    sct_codings = _snomed_codings(res)
    assert len(sct_codings) == 1
    assert sct_codings[0]["code"] == "60554003"
    assert sct_codings[0]["display"] == "Polysomnography"


def test_jp_cpap_procedure_attaches_snomed_47545007() -> None:
    """JP output also carries SNOMED coding (international, country-agnostic)."""
    res = _build_procedure(_cpap_proc(), "pt-g4730", 0, "JP")
    sct_codings = _snomed_codings(res)
    assert len(sct_codings) == 1
    assert sct_codings[0]["code"] == "47545007"


# === JP display (drug_names_ja.yaml translation) ===


def test_jp_cpap_procedure_gets_japanese_text() -> None:
    """JP output of CPAP therapy translates to a Japanese display."""
    res = _build_procedure(_cpap_proc(), "pt-g4730", 0, "JP")
    text = res["code"]["text"]
    assert "CPAP" in text  # CPAP left verbatim (loanword)
    assert "療法" in text
    assert "therapy" not in text.lower()


def test_jp_polysomnography_procedure_gets_japanese_text() -> None:
    """JP output of Polysomnography translates to ポリソムノグラフィー."""
    res = _build_procedure(_polysomno_proc(), "pt-g4730", 0, "JP")
    text = res["code"]["text"]
    assert "ポリソムノグラフィー" in text
    assert "Polysomnography" not in text


# === Non-regression: non-yaml procedures still emit without SNOMED attach ===


def test_unmatched_procedure_type_does_not_add_snomed() -> None:
    """When ``procedure_type`` is not in the SNOMED crosswalk, no SNOMED
    coding is attached (consumers fall through to existing text-only or
    sibling-copy walker behaviour)."""
    proc = _cpap_proc()
    proc["procedure_type"] = "Some bespoke intervention with no crosswalk hit"
    proc["procedure_code"] = "99999"
    proc["procedure_code_us"] = "99999"
    res = _build_procedure(proc, "pt-g4730", 0, "US")
    assert _snomed_codings(res) == []
