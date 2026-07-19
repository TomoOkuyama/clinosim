"""Regression tests for YJ-code `ja` displays (session 58 Chain #5).

The tx-server backing fhir-jp-validator registers each YJ code with its full
製剤名 (product name + dosage form + strength, full-width digits) in the
`http://capstandard.jp/iyaku.info/CodeSystem/YJ-code` CodeSystem. clinosim's
previously-emitted generic-name-with-brand form (e.g. `セレコキシブ（セレコックス）`)
was not a registered synonym → 445 v4 fullset errors.

This test locks the 9 YJ codes clinosim currently emits (from the fragment
loaded on tx-server-build 2026-07-18) against the tx-registered `ja` display.
Silent-sibling-sweep pattern (session 47 rule) — all 9 codes are fixed
together even though only 3 were flagged at production scale.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup

pytestmark = pytest.mark.unit


# tx-server-registered YJ 12-digit codes → `ja` 製剤名 display. Verified against
# `jpfhir-terminology 2.2606.0` / `CodeSystem-jp-medicationcodeyj-cs.json`
# on 2026-07-18.
_TX_REGISTERED_YJ_JA_DISPLAY: dict[str, str] = {
    "1149037F1020": "セレコックス錠１００ｍｇ",
    "1169101F1120": "ネオドパストン配合錠Ｌ１００",
    "1124031Q1024": "ドルミカムシロップ２ｍｇ／ｍＬ",
    "1119400A1031": "ケタラール静注用２００ｍｇ",
    "1139010F1024": "イーケプラ錠２５０ｍｇ",
    "1149019C1149": "ロキソニン細粒１０％",
    "1119402A1022": "１％ディプリバン注",
    "1147002F1013": "ジクロフェナクナトリウム２５ｍｇ錠",
    "1139403A1020": "ロラピタ静注２ｍｇ",
}


@pytest.mark.parametrize("code,expected_ja", sorted(_TX_REGISTERED_YJ_JA_DISPLAY.items()))
def test_yj_code_ja_display_matches_tx_registered(code: str, expected_ja: str) -> None:
    actual = lookup("yj", code, "ja")
    assert actual == expected_ja, (
        f"YJ code {code!r}: clinosim emits ja display {actual!r} but the "
        f"tx-server-registered 製剤名 is {expected_ja!r}. Update yj.yaml or verify the "
        f"tx-server's CodeSystem loadout."
    )
