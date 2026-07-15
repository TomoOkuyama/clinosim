"""_fhir_conditions.py must handle a bare ChronicCondition dataclass, not just
str/dict shapes.

`chronic_list` is documented as `record["patient"]["chronic_conditions"]`,
which in production is always JSON-deserialized (str or dict per entry). But
the builder's `isinstance(chronic, str)` / `isinstance(chronic, dict)`
branches silently drop anything else via a trailing `else: continue` — if a
real ChronicCondition dataclass instance ever reached this function (e.g. a
future test constructing the record in-memory without a JSON round-trip),
it would vanish from FHIR output with no error (PR-90-class latent risk,
2026-07-02 grand design review finding, re-scoped this session — this was
originally mischaracterized as the dual-access pattern; it's actually a
str-vs-dict disambiguation with a genuine dataclass gap alongside it).
"""

import pytest

from clinosim.modules.output._fhir_conditions import _build_conditions
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit


def test_dataclass_chronic_condition_is_not_silently_dropped():
    record = {
        "patient": {
            "chronic_conditions": [
                ChronicCondition(code="I10", onset_date="2020-01-01", severity="mild"),
            ],
        },
        "encounters": [{"encounter_id": "E1", "encounter_type": "outpatient"}],
    }
    conditions = _build_conditions(record, "P1", "US")
    codes = [c["code"]["coding"][0]["code"] for c in conditions if "code" in c]
    assert any(code.startswith("I10") for code in codes), (
        f"dataclass ChronicCondition dropped from output; got codes: {codes}"
    )


def test_dataclass_chronic_condition_stage_is_emitted():
    record = {
        "patient": {
            "chronic_conditions": [
                ChronicCondition(code="N18.3", onset_date="2020-01-01", severity="moderate", stage="CKD G3a"),
            ],
        },
        "encounters": [{"encounter_id": "E1", "encounter_type": "outpatient"}],
    }
    conditions = _build_conditions(record, "P1", "US")
    n18 = next(c for c in conditions if c["code"]["coding"][0]["code"].startswith("N18"))
    assert n18["stage"][0]["summary"]["text"] == "CKD G3a"


def test_dict_chronic_condition_still_works():
    record = {
        "patient": {
            "chronic_conditions": [
                {"code": "E11.9", "onset_date": "2019-05-01", "severity": "mild"},
            ],
        },
        "encounters": [{"encounter_id": "E1", "encounter_type": "outpatient"}],
    }
    conditions = _build_conditions(record, "P1", "US")
    codes = [c["code"]["coding"][0]["code"] for c in conditions if "code" in c]
    assert any(code.startswith("E11") for code in codes)


def test_bare_string_chronic_condition_still_works():
    record = {
        "patient": {"chronic_conditions": ["I10"]},
        "encounters": [{"encounter_id": "E1", "encounter_type": "outpatient"}],
    }
    conditions = _build_conditions(record, "P1", "US")
    codes = [c["code"]["coding"][0]["code"] for c in conditions if "code" in c]
    assert any(code.startswith("I10") for code in codes)
