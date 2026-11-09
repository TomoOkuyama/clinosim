"""Issue #3015: a JP resident is enrolled with the insurer of their residence.

国民健康保険 is run by the municipality of residence and 後期高齢者医療 by the
prefecture's 広域連合, so the 保険者番号 carries the residence's prefecture
code (柏市 → 12…, 東京都 → 13…).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.locale.loader import load_identity_config, resident_insurer_number
from clinosim.modules.identity.providers.jp import JPIdentityProvider
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_PREF_CODE = {"東京都": "13", "埼玉県": "11", "千葉県": "12", "神奈川県": "14"}


def _person(pid: str, age: int, state: str, city: str, occupation: str = "retired") -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="H1",
        age=age,
        sex="F",
        date_of_birth=date(2026 - age, 1, 1),
        occupation=occupation,
        state=state,
        city=city,
    )


def _enroll(members: list[PersonRecord]):
    return JPIdentityProvider().assign_household(members, np.random.default_rng(1), load_identity_config("JP"))


def test_a_kashiwa_residents_kokuho_insurer_starts_with_12() -> None:
    out = _enroll([_person("P1", 60, "千葉県", "柏市", occupation="unemployed")])
    assert out["P1"].category == "national"
    assert out["P1"].insurer_number == "120170"


def test_a_late_elderly_resident_is_with_the_prefecture_koiki_rengo() -> None:
    out = _enroll([_person("P1", 80, "神奈川県", "藤沢市")])
    assert out["P1"].category == "late_elderly"
    assert out["P1"].insurer_number == "39140009"


def test_every_jp_address_city_has_a_kokuho_insurer_of_its_prefecture() -> None:
    from clinosim.locale.loader import load_addresses

    for row in load_addresses("JP")["cities"]:
        pref, city = row["prefecture"], row["city"]
        kokuho = resident_insurer_number("JP", "national", pref, city)
        koki = resident_insurer_number("JP", "late_elderly", pref, city)
        assert kokuho and kokuho[:2] == _PREF_CODE[pref], (pref, city, kokuho)
        assert koki == f"39{_PREF_CODE[pref]}" + koki[4:] and len(koki) == 8, (pref, city, koki)


def test_insurer_numbers_carry_a_valid_check_digit() -> None:
    """保険者番号の検証番号: weights 2, 1, 2, … from the right, digit sums."""

    def valid(number: str) -> bool:
        body, check = number[:-1], int(number[-1])
        total = 0
        for i, ch in enumerate(reversed(body)):
            p = int(ch) * (2 if i % 2 == 0 else 1)
            total += p // 10 + p % 10
        return (10 - total % 10) % 10 == check

    cfg = load_identity_config("JP")
    for scheme in ("national", "late_elderly"):
        for entry in cfg["payers"][scheme]:
            assert valid(str(entry["number"])), entry


def test_coverage_turning_75_switches_to_the_residence_koiki_rengo() -> None:
    from clinosim.modules.output.fhir_r4.demographics.patient import _build_coverage_resources

    patient = {
        "patient_id": "POP-1",
        "sex": "F",
        "date_of_birth": "1951-05-01",
        "address": {"state": "埼玉県", "city": "川口市"},
        "identity": {
            "enrollments": [
                {"category": "national", "insurer_number": "110031", "member_id": "123456", "group_symbol": "1234"}
            ]
        },
    }
    encounters = [{"admission_datetime": "2026-09-01T09:00:00"}]
    payors = {
        r["payor"][0]["reference"]
        for r in _build_coverage_resources(patient, "JP", encounters)
        if r["resourceType"] == "Coverage"
    }
    assert payors == {"Organization/payer-110031", "Organization/payer-39110002"}
