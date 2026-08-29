"""Regression guards for Issue #941 — Encounter.hospitalization.admitSource
and dischargeDisposition are populated on 100% of IMP encounters in the
dual-slot shape (EN-canonical `coding[0].display` + locale-resolved `.text`).

Pre-fix behaviour (v0.5.0): CIF path already resolved admit_source /
discharge_disposition into `emd`/`home`/`exp`, but the emit path only set
the raw `coding.code` — the JP `display` (when set) was later stripped by
`_strip_japanese_display_on_english_only_systems` because the HL7
admit-source / discharge-disposition CodeSystems are on the "English-only
CS" prefix allowlist, and `.text` was never populated. Any consumer that
scanned for `.text` OR `.coding[0].display` (a reasonable populated-ness
heuristic) reported 0/703 IMP encounters as having these two backbone DPC
fields.

Post-fix (this file guards):

1. Explicit CIF `admit_source="emd"` (post-ED admission) → admitSource has
   `code=emd`, EN canonical display on `coding[0].display`, JP display on
   `.text` (for JP output).
2. Explicit CIF `admit_source="outp"` (elective admission via outpatient
   clinic) → same dual-slot shape with code=outp.
3. Death encounter (`deceased=True`, no explicit `discharge_disposition`)
   → dischargeDisposition falls back to yaml `deceased_code="exp"` — no
   LEFT-JOIN with Patient.deceasedDateTime required for hospital-mortality
   analytics.
4. Normal completed encounter without explicit disposition →
   dischargeDisposition falls back to yaml `fallback_code="home"`.
5. Every finished IMP encounter has both fields populated (no more 0/703
   for the reporter's scan) — enforced at the yaml-fallback level even
   when the CIF has no explicit value.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_encounter_disposition_defaults
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter


def _hosp(resource: dict) -> dict:
    return resource.get("hospitalization") or {}


def _admit_concept(resource: dict) -> dict:
    return _hosp(resource).get("admitSource") or {}


def _dispo_concept(resource: dict) -> dict:
    return _hosp(resource).get("dischargeDisposition") or {}


def _build_imp(**overrides) -> dict:
    """Build a minimal IMP encounter dict, then apply per-test overrides."""
    base = {
        "encounter_id": "ENC-TEST-000001",
        "encounter_type": "inpatient",
        "status": "completed",
        "admission_datetime": "2026-01-15T10:00:00",
        "discharge_datetime": "2026-01-22T14:00:00",
        "chief_complaint": "Test admission",
        "attending_physician_id": "PRAC-000001",
    }
    base.update(overrides)
    return base


# ---------- 1. Explicit admit_source from CIF (ED admission → 'emd') ----------


@pytest.mark.parametrize("country,lang", [("JP", "ja"), ("US", "en")])
def test_admit_source_emd_dual_slot(country: str, lang: str) -> None:
    """Post-ED admission → admitSource has code=emd, EN canonical
    coding.display, locale-resolved text."""
    enc = _build_imp(admit_source="emd", discharge_disposition="home")
    r = _build_encounter(enc, patient_id="POP-000001", country=country)
    concept = _admit_concept(r)
    assert concept, "admitSource must be present on IMP"
    assert concept["coding"][0]["code"] == "emd"
    # EN canonical display on coding.display — survives the English-only-CS
    # strip walker and HAPI validation
    assert concept["coding"][0]["display"] == code_lookup("hl7-admit-source", "emd", "en")
    # .text carries the locale-resolved human-readable label
    assert concept["text"] == code_lookup("hl7-admit-source", "emd", lang)


# ---------- 2. Explicit admit_source from CIF (elective → 'outp') ----------


@pytest.mark.parametrize("country,lang", [("JP", "ja"), ("US", "en")])
def test_admit_source_outp_dual_slot(country: str, lang: str) -> None:
    """Elective admission via outpatient clinic → admitSource code=outp."""
    enc = _build_imp(admit_source="outp", discharge_disposition="home")
    r = _build_encounter(enc, patient_id="POP-000001", country=country)
    concept = _admit_concept(r)
    assert concept["coding"][0]["code"] == "outp"
    assert concept["coding"][0]["display"] == code_lookup("hl7-admit-source", "outp", "en")
    assert concept["text"] == code_lookup("hl7-admit-source", "outp", lang)


# ---------- 3. Death encounter → dischargeDisposition=exp fallback ----------


@pytest.mark.parametrize("country,lang", [("JP", "ja"), ("US", "en")])
def test_death_encounter_falls_back_to_expired(country: str, lang: str) -> None:
    """`deceased=True` with no explicit CIF `discharge_disposition` → falls
    back to the yaml-configured `deceased_code` ("exp") rather than to
    "home". Hospital-mortality analytics can `count(*) where
    dischargeDisposition = 'exp'` directly (no LEFT-JOIN with
    Patient.deceasedDateTime)."""
    enc = _build_imp(admit_source="emd")  # no discharge_disposition
    r = _build_encounter(enc, patient_id="POP-000001", country=country, deceased=True)
    concept = _dispo_concept(r)
    assert concept, "dischargeDisposition must be present on finished IMP"
    assert concept["coding"][0]["code"] == "exp"
    assert concept["coding"][0]["display"] == code_lookup("hl7-discharge-disposition", "exp", "en")
    assert concept["text"] == code_lookup("hl7-discharge-disposition", "exp", lang)


# ---------- 4. Normal completed encounter → dischargeDisposition=home ----------


@pytest.mark.parametrize("country,lang", [("JP", "ja"), ("US", "en")])
def test_normal_discharge_falls_back_to_home(country: str, lang: str) -> None:
    """Finished IMP with no explicit CIF `discharge_disposition` and
    `deceased=False` → dispo falls back to yaml `fallback_code` ("home")."""
    enc = _build_imp(admit_source="emd")  # no discharge_disposition
    r = _build_encounter(enc, patient_id="POP-000001", country=country, deceased=False)
    concept = _dispo_concept(r)
    assert concept["coding"][0]["code"] == "home"
    assert concept["coding"][0]["display"] == code_lookup("hl7-discharge-disposition", "home", "en")
    assert concept["text"] == code_lookup("hl7-discharge-disposition", "home", lang)


# ---------- 5. 100% populate: every finished IMP has both fields ----------


@pytest.mark.parametrize("country", ["JP", "US"])
def test_every_finished_imp_has_both_disposition_fields(country: str) -> None:
    """Reporter's exact scan: every finished IMP encounter has both
    `admitSource` and `dischargeDisposition` populated with a code AND a
    human-readable label (either `.text` or `.coding[0].display`), for
    every CIF-side combination the simulator can produce (explicit admit
    source, no admit source; explicit dispo, no dispo; deceased, not
    deceased)."""
    combos = [
        # (admit_source, discharge_disposition, deceased)
        ("emd", "home", False),
        ("outp", "home", False),
        ("emd", "exp", False),
        ("", "", False),  # both missing → falls back to other + home
        ("", "", True),  # both missing + deceased → other + exp
        ("emd", "", True),  # explicit admit, no dispo, deceased → emd + exp
        ("emd", "", False),  # explicit admit, no dispo, alive → emd + home
    ]
    for i, (adm, dispo, dead) in enumerate(combos):
        enc = _build_imp(encounter_id=f"ENC-CBO-{i:04d}", admit_source=adm, discharge_disposition=dispo)
        r = _build_encounter(enc, patient_id="POP-000001", country=country, deceased=dead)
        admit_cc = _admit_concept(r)
        dispo_cc = _dispo_concept(r)
        # Reporter's exact heuristic
        admit_populated = bool(admit_cc.get("text") or (admit_cc.get("coding") or [{}])[0].get("display"))
        dispo_populated = bool(dispo_cc.get("text") or (dispo_cc.get("coding") or [{}])[0].get("display"))
        assert admit_populated, f"combo {i}: admitSource is empty for reporter's scan → {admit_cc!r}"
        assert dispo_populated, f"combo {i}: dischargeDisposition is empty for reporter's scan → {dispo_cc!r}"


# ---------- Yaml is authoritative for the fallback codes ----------


def test_fallback_codes_are_yaml_driven() -> None:
    """Constants live in yaml (feedback_constants_live_in_external_config).
    The emit path must read `admit_source.fallback_code` and
    `discharge_disposition.fallback_code` / `deceased_code` from
    ``clinosim/locale/shared/encounter_disposition_defaults.yaml`` — not
    hardcode them."""
    cfg = load_encounter_disposition_defaults()
    assert cfg["admit_source"]["fallback_code"] == "other"
    assert cfg["admit_source"]["system_key"] == "hl7-admit-source"
    assert cfg["discharge_disposition"]["fallback_code"] == "home"
    assert cfg["discharge_disposition"]["deceased_code"] == "exp"
    assert cfg["discharge_disposition"]["system_key"] == "hl7-discharge-disposition"
    # JP-CLINS binding URLs are informational — pinned so a non-engineer
    # can update them without touching the emit code.
    assert cfg["admit_source"]["jp_clins_value_set"].startswith("http://jpfhir.jp/")
    assert cfg["discharge_disposition"]["jp_clins_value_set"].startswith("http://jpfhir.jp/")


# ---------- In-progress IMP legitimately has no dischargeDisposition ----------


def test_inprogress_imp_has_admit_source_but_no_discharge_disposition() -> None:
    """An IMP encounter still in-progress at snapshot end (no
    discharge_datetime, status=in-progress) MUST have admitSource populated
    but MUST NOT have dischargeDisposition (patient has not been
    discharged yet — the CodeableConcept would be a fabricated outcome).

    This is the semantically-correct behaviour for the 5 in-progress
    encounters in the JP p=1000 seed=500 baseline — they are NOT counted
    as bugs by Issue #941 (see verification block in the PR body).
    """
    enc = _build_imp(admit_source="emd", status="in-progress")
    enc.pop("discharge_datetime", None)
    r = _build_encounter(enc, patient_id="POP-000001", country="JP")
    assert _admit_concept(r), "in-progress IMP still needs admitSource (already admitted)"
    assert not _dispo_concept(r), "in-progress IMP MUST NOT have dischargeDisposition (not yet discharged)"
