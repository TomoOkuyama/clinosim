"""Issue #1815 fix + Phase 3.β.5: CCHD screening-site SNOMED
authority alignment.

Pre-fix the newborn CCHD pulse-oximetry FHIR emit path carried a
module-local dict in ``modules/newborn/fhir_emit.py`` that mapped the
right-side clinical measurements to left-side SNOMED CT concepts:

- ``right_hand`` → ``368208006`` (SNOMED "Left upper arm structure") ← wrong
- ``foot``       → ``22335008``  (SNOMED "Structure of left foot")   ← wrong

Both codes verified against tx.fhir.org $lookup against the SNOMED CT
International Edition. The hardcoded ``display`` strings
(``"Right upper arm"`` / ``"Foot"``) further masked the drift from
reviewers reading the ndjson at a glance.

Fix:
- Register the correct SNOMED concepts in ``snomed-ct.yaml`` authority
  (``368209003`` Right upper arm structure, ``56459004`` Foot
  structure), with EN + JA displays.
- Create the CCHD site catalog + resolver (now ``snomed-maps.yaml`` ``cchd_site``, Phase 3.β.5
  pattern), retiring the module-local dict.
- Retire the stale display strings — all FHIR emit displays now flow
  through ``code_lookup("snomed-ct", <code>, lang)`` against the
  authority yaml.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.codes.snomed import snomed_for, snomed_map

pytestmark = pytest.mark.unit


# ----------------------------------------------------------------------------
# Authority alignment — codes in snomed-ct.yaml with EN + JA
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,expected_en,expected_ja",
    [
        ("368209003", "Right upper arm structure", "右上腕"),
        ("56459004", "Foot structure", "足部"),
    ],
)
def test_cchd_body_site_codes_registered_in_snomed_authority(code: str, expected_en: str, expected_ja: str) -> None:
    """Both CCHD body-site codes must have EN+JA displays in the
    snomed-ct.yaml authority — regression guard against future
    retirement."""
    assert code_lookup("snomed-ct", code, "en") == expected_en
    assert code_lookup("snomed-ct", code, "ja") == expected_ja


# ----------------------------------------------------------------------------
# Catalog resolver
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "site,expected_code",
    [
        ("right_hand", "368209003"),
        ("foot", "56459004"),
    ],
)
def test_resolve_cchd_site_snomed_known(site: str, expected_code: str) -> None:
    assert snomed_for("cchd_site", site) == expected_code


def test_resolve_cchd_site_snomed_unknown_returns_none() -> None:
    assert snomed_for("cchd_site", "left_hand") is None
    assert snomed_for("cchd_site", "") is None


def test_all_cchd_sites_matches_catalog() -> None:
    assert tuple(sorted(snomed_map("cchd_site"))) == ("foot", "right_hand")


# ----------------------------------------------------------------------------
# #1815 bug — pre-fix wrong-laterality codes must stay retired
# ----------------------------------------------------------------------------


def test_wrong_laterality_codes_no_longer_mapped() -> None:
    """The pre-fix dict carried 368208006 (Left upper arm) and
    22335008 (Left foot). Both must stay out of the CCHD catalog —
    regression guard against reintroduction."""
    catalog = snomed_map("cchd_site")
    offenders = [(site, code) for site, code in catalog.items() if code in {"368208006", "22335008"}]
    assert not offenders, f"left-laterality SNOMED codes still mapped: {offenders}"


def test_newborn_fhir_emit_module_no_longer_exports_wrong_dict() -> None:
    """Prevent accidental reintroduction of the retired SoT dict."""
    from clinosim.modules.newborn import fhir_emit as _nf

    assert not hasattr(_nf, "_CCHD_SITE_SNOMED"), (
        '_CCHD_SITE_SNOMED was retired in #1815 — use clinosim.codes.snomed.snomed_for("cchd_site", ...) instead'
    )


# ----------------------------------------------------------------------------
# End-to-end: FHIR emit path produces right-sided SNOMED coding
# ----------------------------------------------------------------------------


def test_cchd_pulse_ox_emit_right_hand_uses_right_upper_arm_snomed() -> None:
    """The emit path produces a FHIR Observation with
    ``bodySite.coding.code = 368209003`` (not the pre-fix 368208006)
    for ``right_hand`` measurements, with the catalog-resolved EN
    display."""
    from clinosim.modules.newborn.fhir_emit import _bb_newborn_cchd_pulse_ox

    _ctx_module = type("Ctx", (), {})()
    _ctx_module.patient_id = "POP-cchd-1"
    _ctx_module.country = "us"
    _ctx_module.primary_enc_id = "ENC-cchd-1"
    _ctx_module.record = {
        "extensions": {
            "newborn": {
                "cchd_pulse_ox": [
                    {"site": "right_hand", "value_pct": 97, "loinc": "59408-5"},
                    {"site": "foot", "value_pct": 98, "loinc": "59408-5"},
                ]
            }
        }
    }
    obs = _bb_newborn_cchd_pulse_ox(_ctx_module)
    assert len(obs) == 2
    by_site = {o["bodySite"]["coding"][0]["code"]: o for o in obs}
    assert "368209003" in by_site, "right_hand should emit SNOMED 368209003 (Right upper arm)"
    assert "56459004" in by_site, "foot should emit SNOMED 56459004 (Foot structure)"
    # Pre-fix wrong codes must be absent.
    assert "368208006" not in by_site
    assert "22335008" not in by_site
    # Display comes from authority yaml, not the retired hardcoded strings.
    assert by_site["368209003"]["bodySite"]["coding"][0]["display"] == "Right upper arm structure"
    assert by_site["56459004"]["bodySite"]["coding"][0]["display"] == "Foot structure"
