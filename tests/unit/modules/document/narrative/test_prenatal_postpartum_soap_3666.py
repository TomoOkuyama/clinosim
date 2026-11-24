"""Issue #3666: the prenatal (Z34) and postpartum (Z39) outpatient SOAP write
pregnancy findings (gestational age, fetal assessment, days since delivery,
puerperal findings) instead of only the visit reason and the chronic problems.
"""

from __future__ import annotations

import re

import pytest

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative._visit_reason import visit_kind
from tests.unit.modules.document.narrative.test_visit_reason_soap_3249 import _record, _soap

pytestmark = pytest.mark.unit

_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_IMPERATIVE = re.compile(r"\b(assess|evaluate|check|ensure|confirm)\b", re.I)

_PERIOD = {
    "state_type": "pregnancy",
    "start_date": "2026-01-05",
    "end_date": "2026-10-12",
    "outcome": "delivered",
    "metadata": {"lmp": "2026-01-05", "edd": "2026-10-12", "delivered_on": "2026-10-12", "complications": []},
}


def _visit(code: str, when: str, lang_country: str) -> dict:
    record = _record(
        country=lang_country,
        visit_type="chronic_followup",
        condition=code,
        dx=code,
        chronic=["E66.3"],
        age_dob=__import__("datetime").date(1996, 1, 1),
        when=when,
    )
    record["patient"]["state_periods"] = [dict(_PERIOD)]
    return record


@pytest.mark.parametrize("country", ["US", "JP"])
def test_prenatal_visit_has_a_kind(country: str) -> None:
    from types import SimpleNamespace

    ctx = SimpleNamespace(visit_type="chronic_followup", visit_condition_id="Z34")
    assert visit_kind(ctx) == "prenatal"
    ctx = SimpleNamespace(visit_type="chronic_followup", visit_condition_id="Z39")
    assert visit_kind(ctx) == "postpartum"


def test_prenatal_soap_states_gestational_age_and_fetal_assessment_en() -> None:
    soap = _soap(_visit("Z34", "2026-06-22T10:00:00", "US"), "US")
    text = " ".join(soap.values())
    assert "24w0d" in soap["S"] + soap["A"]
    assert "fundal height" in soap["O"].lower() and "fetal heart" in soap["O"].lower()
    assert "fetal movements" in soap["O"].lower()
    assert "36 weeks" in soap["P"]  # the next scheduled prenatal visit
    assert not _CJK.search(text)
    assert not _IMPERATIVE.search(text)


def test_prenatal_soap_ja() -> None:
    soap = _soap(_visit("Z34", "2026-06-22T10:00:00", "JP"), "JP")
    assert "妊娠24週0日" in soap["S"] + soap["A"]
    assert "胎児心拍" in soap["O"] and "子宮底" in soap["O"]
    assert "妊娠36週" in soap["P"]


def test_last_prenatal_visit_has_no_next_prenatal_line() -> None:
    soap = _soap(_visit("Z34", "2026-09-14T10:00:00", "US"), "US")  # 36 weeks
    assert "36w0d" in soap["S"] + soap["A"]
    assert "next prenatal visit" not in soap["P"].lower()


def test_prenatal_soap_without_a_pregnancy_period_states_no_gestational_age() -> None:
    record = _visit("Z34", "2026-06-22T10:00:00", "US")
    record["patient"]["state_periods"] = []
    soap = _soap(record, "US")
    assert "weeks" not in soap["S"] + soap["A"]


def test_postpartum_soap_states_days_since_delivery_and_puerperal_findings_en() -> None:
    soap = _soap(_visit("Z39", "2026-10-19T10:00:00", "US"), "US")
    text = " ".join(soap.values())
    assert "7 days after delivery" in soap["S"] + soap["A"]
    assert "uterus" in soap["O"].lower() and "wound" in soap["O"].lower()
    assert "28 days" in soap["P"]  # the next postpartum visit
    assert not _CJK.search(text)
    assert not _IMPERATIVE.search(text)


def test_postpartum_soap_ja() -> None:
    soap = _soap(_visit("Z39", "2026-10-19T10:00:00", "JP"), "JP")
    assert "分娩後7日" in soap["S"] + soap["A"]
    assert "子宮" in soap["O"] and "創部" in soap["O"]
    assert "28日" in soap["P"]


def test_postpartum_does_not_state_a_screening_result_the_record_lacks() -> None:
    soap = _soap(_visit("Z39", "2026-11-09T10:00:00", "US"), "US")
    text = " ".join(soap.values()).lower()
    assert "epds" not in text and "score" not in text
    assert "28 days after delivery" in soap["S"] + soap["A"]


def test_other_visit_kinds_unchanged() -> None:
    record = _record(
        country="US",
        visit_type="chronic_followup",
        condition="I10",
        dx="I10",
        chronic=["I10"],
        when="2026-06-22T10:00:00",
    )
    assert (
        visit_kind(__import__("types").SimpleNamespace(visit_type="chronic_followup", visit_condition_id="I10")) == ""
    )
    soap = _soap(record, "US")
    assert "gestational" not in " ".join(soap.values()).lower()
    assert t("fallback.generic_fallback", "en")


def test_early_prenatal_visit_states_no_fundal_height_or_fetal_movements() -> None:
    soap = _soap(_visit("Z34", "2026-03-30T10:00:00", "US"), "US")  # 12 weeks
    assert "12w0d" in soap["S"] + soap["A"]
    assert "fetal heart" in soap["O"].lower()
    assert "fundal" not in soap["O"].lower() and "movements" not in soap["O"].lower()
