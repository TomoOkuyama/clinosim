"""Designated-city addresses name the ward (Issue #3696)."""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.locale.loader import load_addresses
from clinosim.locale.loaders.fhir_identity import resident_insurer_number
from clinosim.modules.population._identity import _generate_household_address

DESIGNATED = ("横浜市", "川崎市", "さいたま市")
# Weight of each designated city before it was split into wards.
OLD_WEIGHT = {"横浜市": 15, "川崎市": 10, "さいたま市": 10}

# Every postal code below was checked against the Japan Post ken_all
# (utf_ken_all.csv, update of 2026-10-30): the 7-digit code is listed there with
# exactly this prefecture-city-ward.
VERIFIED_WARD_ZIPS: dict[str, tuple[str, ...]] = {
    "さいたま市大宮区": ("330-0801", "330-0804", "330-0836", "330-0844", "330-0852", "330-0856"),
    "さいたま市浦和区": ("330-0041", "330-0045", "330-0053", "330-0061", "330-0065", "330-0075"),
    "さいたま市南区": ("336-0015", "336-0021", "336-0025", "336-0032", "336-0036", "336-0043"),
    "さいたま市中央区": ("338-0001", "338-0003", "338-0005", "338-0007", "338-0012", "338-0014"),
    "さいたま市緑区": ("336-0903", "336-0913", "336-0923", "336-0936", "336-0967", "336-0977"),
    "さいたま市北区": ("331-0801", "331-0803", "331-0811", "331-0814", "331-0822", "331-0825"),
    "横浜市西区": ("220-0001", "220-0011", "220-0033", "220-0045", "220-0055", "220-0074"),
    "横浜市港北区": ("222-0001", "222-0013", "222-0032", "223-0051", "223-0058", "223-0066"),
    "横浜市青葉区": ("225-0001", "225-0014", "227-0031", "227-0042", "227-0053", "227-0067"),
    "横浜市都筑区": ("224-0001", "224-0014", "224-0028", "224-0041", "224-0054", "224-0066"),
    "横浜市神奈川区": ("221-0001", "221-0032", "221-0055", "221-0802", "221-0834", "221-0866"),
    "横浜市戸塚区": ("244-0001", "244-0802", "244-0811", "244-0816", "245-0061", "245-0067"),
    "川崎市川崎区": ("210-0001", "210-0023", "210-0814", "210-0833", "210-0852", "210-0869"),
    "川崎市中原区": ("211-0001", "211-0012", "211-0024", "211-0037", "211-0053", "211-0068"),
    "川崎市幸区": ("212-0001", "212-0007", "212-0016", "212-0026", "212-0052", "212-0058"),
    "川崎市高津区": ("213-0001", "213-0005", "213-0014", "213-0023", "213-0029", "213-0035"),
    "川崎市多摩区": ("214-0001", "214-0005", "214-0012", "214-0022", "214-0034", "214-0039"),
    "川崎市宮前区": ("216-0002", "216-0007", "216-0015", "216-0025", "216-0034", "216-0044"),
    "川崎市麻生区": ("215-0001", "215-0006", "215-0014", "215-0022", "215-0027", "215-0036"),
}


def _designated_entries() -> list[dict]:
    return [c for c in load_addresses("JP")["cities"] if c["city"].startswith(DESIGNATED)]


def test_every_designated_city_entry_names_a_ward() -> None:
    entries = _designated_entries()
    assert entries
    for entry in entries:
        assert entry["city"].endswith("区"), entry["city"]
        assert entry["city"] not in DESIGNATED


def test_zips_belong_to_the_ward() -> None:
    entries = _designated_entries()
    assert {e["city"] for e in entries} == set(VERIFIED_WARD_ZIPS)
    for entry in entries:
        assert entry["zips"], entry["city"]
        for zip_code in entry["zips"]:
            assert zip_code in VERIFIED_WARD_ZIPS[entry["city"]], (entry["city"], zip_code)


def test_ward_weights_sum_to_the_old_city_weight() -> None:
    for city, old in OLD_WEIGHT.items():
        total = sum(e["weight"] for e in _designated_entries() if e["city"].startswith(city))
        assert total == old, city


def test_generated_address_carries_ward_and_its_zip() -> None:
    addr_data = load_addresses("JP")
    rng = np.random.default_rng(3696)
    seen = 0
    for _ in range(400):
        addr = _generate_household_address(addr_data, rng)
        if addr["city"].startswith(DESIGNATED):
            seen += 1
            assert addr["city"].endswith("区")
            assert addr["postal_code"] in VERIFIED_WARD_ZIPS[addr["city"]]
    assert seen


@pytest.mark.parametrize(
    ("city", "number"),
    [("横浜市西区", "144006"), ("川崎市高津区", "145003"), ("さいたま市大宮区", "114009")],
)
def test_ward_resident_keeps_the_city_insurer(city: str, number: str) -> None:
    prefecture = "埼玉県" if city.startswith("さいたま") else "神奈川県"
    assert resident_insurer_number("JP", "national", prefecture, city) == number


def test_non_designated_city_insurer_unchanged() -> None:
    assert resident_insurer_number("JP", "national", "東京都", "世田谷区") == "130120"
