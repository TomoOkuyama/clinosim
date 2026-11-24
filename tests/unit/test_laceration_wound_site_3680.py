"""Minor-laceration ED visits record the wound site (Issue #3680).

The visit is coded by site (the injury chapter codes an open wound by region),
the order-derived wound-care Procedures carry the site as bodySite, the ED note
states the same site, and a hand image is ordered only for a hand or finger
wound.
"""

from __future__ import annotations

import copy
from collections import Counter
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from clinosim.codes import code_exists, lookup
from clinosim.codes.loader import system_key_for
from clinosim.modules.document.narrative import _template_helpers as th
from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,
    load_encounter_condition,
    matching_diagnosis_variant_indices,
    study_in_site,
    visit_body_site,
)
from clinosim.modules.output.fhir_r4.lib.inline_bb import _visit_wound_site
from clinosim.simulator.emergency import ed_diagnosis_code, ed_diagnosis_variant

pytestmark = pytest.mark.unit

_SPEC = load_encounter_condition("minor_laceration")
_VARIANTS = _SPEC["diagnosis_variants"]


def _patient() -> SimpleNamespace:
    return SimpleNamespace(chronic_conditions=[])


def test_no_laceration_visit_is_coded_unspecified_injury() -> None:
    for country in ("US", "JP"):
        codes = {ed_diagnosis_code(_SPEC, _patient(), country=country, encounter_id=f"ENC-{i}") for i in range(300)}
        assert not any(c.startswith("T14.9") for c in codes), codes
        assert len(codes) == len(_VARIANTS)


def test_every_variant_has_its_own_jp_code_and_a_site() -> None:
    jp = [v["codes"]["jp"] for v in _VARIANTS]
    assert len(set(jp)) == len(jp)
    assert all(v.get("site") and v.get("body_site_snomed") for v in _VARIANTS)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_code_and_body_site_is_registered(country: str) -> None:
    system = system_key_for("diagnosis", country)
    for v in _VARIANTS:
        assert code_exists(system, v["codes"][country.lower()], exact=True), v
        assert lookup("snomed-ct", v["body_site_snomed"], "en"), v


def test_weights_sum_to_one() -> None:
    assert abs(sum(v["weight"] for v in _VARIANTS) - 1.0) < 1e-9


def test_variant_is_drawn_without_rng_and_matches_the_code() -> None:
    counts: Counter[str] = Counter()
    for i in range(2000):
        enc = f"ENC-{i}"
        variant = ed_diagnosis_variant(_SPEC, enc)
        assert variant is not None
        assert ed_diagnosis_code(_SPEC, _patient(), country="JP", encounter_id=enc) == variant["codes"]["jp"]
        counts[variant["site"]] += 1
    assert 0.40 < (counts["hand"] + counts["finger"]) / 2000 < 0.52


def test_procedure_body_site_follows_the_visit_code() -> None:
    for country in ("US", "JP"):
        for v in _VARIANTS:
            assert visit_body_site(_VARIANTS, v["codes"][country.lower()]) == v["body_site_snomed"]
    assert visit_body_site(_VARIANTS, "T14.90XA") == ""


def _record(code: str, name: str = "minor_laceration") -> dict:
    return {
        "condition_event": {"ground_truth_diseases": [name]},
        "encounters": [{"encounter_id": "ENC-1", "admission_diagnosis_code": code}],
        "clinical_diagnosis": {"admission_diagnosis_code": code, "discharge_diagnosis_code": code},
    }


def test_fhir_wound_site_comes_from_the_encounters_protocol() -> None:
    v = _VARIANTS[5]
    assert _visit_wound_site(_record(v["codes"]["us"]), "ENC-1") == v["body_site_snomed"]
    assert _visit_wound_site(_record(v["codes"]["jp"]), "ENC-1") == v["body_site_snomed"]
    # A disease record or a protocol without variants has no wound site.
    assert _visit_wound_site(_record("I21.9", "acute_mi"), "ENC-1") == ""
    assert _visit_wound_site(_record("T23.201A", "minor_burn"), "ENC-1") == ""


@pytest.mark.parametrize(("country", "lang"), [("US", "en"), ("JP", "ja")])
def test_ed_note_names_the_site_of_the_coded_diagnosis(country: str, lang: str) -> None:
    tmpl = _SPEC["narrative"]["ed_note_template"]
    sites = tmpl["variants"]["wound__site"][lang]
    assert len(sites) == len(_VARIANTS)
    for i, v in enumerate(_VARIANTS):
        code = v["codes"][country.lower()]
        ctx = SimpleNamespace(
            encounter=SimpleNamespace(encounter_id="ENC-9"),
            encounter_protocol=SimpleNamespace(diagnosis_variants=_VARIANTS),
            diagnoses=[SimpleNamespace(admission_diagnosis_code=code)],
        )
        assert matching_diagnosis_variant_indices(_VARIANTS, code) == [i]
        # the shared lookup picks the list entry of the coded variant
        assert th._diagnosis_variant_indices(ctx) == [i]


def test_hand_imaging_only_for_hand_and_finger_visits() -> None:
    [img] = [i for i in _SPEC["workup"]["imaging"] if i["test"] == "Hand_Xray"]
    for v in _VARIANTS:
        assert study_in_site(img, v) == (v["site"] in {"hand", "finger"})
    assert study_in_site({"test": "X"}, None)
    assert not study_in_site(img, None)


def test_validator_requires_a_code_for_every_country() -> None:
    data = copy.deepcopy(_SPEC)
    del data["diagnosis_variants"][0]["codes"]["jp"]
    with pytest.raises(ValidationError, match="jp"):
        EncounterConditionProtocol.model_validate(data)


def test_variant_lists_must_match_the_variants() -> None:
    data = copy.deepcopy(_SPEC)
    data["narrative"]["ed_note_template"]["variants"]["wound__site"]["en"].pop()
    data["narrative"]["ed_note_template"]["variants"]["wound__site"]["ja"].pop()
    with pytest.raises(ValidationError, match="wound__site"):
        EncounterConditionProtocol.model_validate(data)
