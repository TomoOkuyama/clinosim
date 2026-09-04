"""C6 / Issue #1092: past-pregnancy marker must be Z87.59 (personal history),
not Z37.9 (which is the delivery-encounter outcome code).

Real charts use Z37.x only on the delivery encounter (paired with Z38.x on
the newborn). Carrying it on the mother's problem list years later is a
semantic misuse. The correct code for the historical marker is Z87.59
(Personal history of other complications of pregnancy, childbirth and the
puerperium).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions

pytestmark = pytest.mark.unit


def _record_with_delivered_pregnancy(country_note: str = "US") -> dict:
    return {
        "patient": {
            "patient_id": "P1",
            "sex": "F",
            "chronic_conditions": [],
            "state_periods": [
                {
                    "state_type": "pregnancy",
                    "start_date": "2025-01-01",
                    "end_date": "2025-10-01",
                    "outcome": "delivered",
                    "metadata": {"delivery_date": "2025-10-01"},
                    "period_seq": 0,
                }
            ],
        },
        "encounters": [
            {
                "encounter_id": "E1",
                "encounter_type": "outpatient",
                "admission_datetime": "2026-01-15T10:00:00",
                "attending_physician_id": "DR-1",
            }
        ],
    }


def _past_birth(conds: list[dict]) -> dict:
    for c in conds:
        if "past-birth" in c.get("id", ""):
            return c
    raise AssertionError(f"no past-birth Condition in {[c.get('id') for c in conds]}")


def test_us_past_birth_marker_is_z87_59_not_z37_9() -> None:
    conds = _build_conditions(_record_with_delivered_pregnancy(), "P1", "US")
    c = _past_birth(conds)
    codes = [cd.get("code") for cd in c["code"]["coding"]]
    # New: Z87.59 (personal history)
    assert "Z87.59" in codes, f"US past-birth marker should be Z87.59, got codes={codes}"
    # Regression guard: Z37 series must not be there anymore
    assert not any(str(cd).startswith("Z37") for cd in codes), (
        f"US past-birth marker leaked Z37 (delivery-encounter code); codes={codes}"
    )


def test_jp_past_birth_marker_is_z87_59_not_z37() -> None:
    conds = _build_conditions(_record_with_delivered_pregnancy(), "P1", "JP")
    c = _past_birth(conds)
    codes = [cd.get("code") for cd in c["code"]["coding"]]
    assert "Z87.59" in codes, f"JP past-birth marker should be Z87.59, got codes={codes}"
    assert not any(str(cd).startswith("Z37") for cd in codes), f"JP past-birth marker leaked Z37; codes={codes}"


def test_past_birth_identifier_and_id_unchanged() -> None:
    """The internal id / identifier scheme (``cond-past-birth-*`` /
    ``pregnancy-past-birth|*``) MUST stay stable — consumers key off it."""
    conds = _build_conditions(_record_with_delivered_pregnancy(), "P1", "US")
    c = _past_birth(conds)
    assert c["id"] == "cond-past-birth-P1-0"
    idents = [i.get("value") for i in c.get("identifier", [])]
    assert "pregnancy-past-birth|P1|0" in idents, idents


def test_past_birth_display_is_personal_history_wording() -> None:
    """Human-readable display should reflect the ``personal history`` scope,
    not the ``outcome of delivery`` scope."""
    conds = _build_conditions(_record_with_delivered_pregnancy(), "P1", "US")
    c = _past_birth(conds)
    text = (c.get("code", {}).get("text") or "").lower()
    display = (c["code"]["coding"][0].get("display") or "").lower()
    # Some form of "history" wording must appear
    assert "history" in text or "history" in display, (
        f"expected 'history'-flavored wording; text={text!r} display={display!r}"
    )
    # And the misuse phrasing must not
    assert "outcome of delivery" not in text and "outcome of delivery" not in display, (
        f"'outcome of delivery' phrasing leaked; text={text!r} display={display!r}"
    )


def test_multi_parity_gets_z87_59_per_period() -> None:
    """Two delivered pregnancies → two past-birth Conditions, both Z87.59."""
    rec = _record_with_delivered_pregnancy()
    rec["patient"]["state_periods"].append(
        {
            "state_type": "pregnancy",
            "start_date": "2023-01-01",
            "end_date": "2023-10-01",
            "outcome": "delivered",
            "metadata": {"delivery_date": "2023-10-01"},
            "period_seq": 1,
        }
    )
    conds = _build_conditions(rec, "P1", "US")
    past = [c for c in conds if "past-birth" in c.get("id", "")]
    assert len(past) == 2, f"expected 2 past-birth Conditions, got {len(past)}"
    for c in past:
        codes = [cd.get("code") for cd in c["code"]["coding"]]
        assert "Z87.59" in codes
