"""Session 104 Issue #1168 — oncology + related chronic drugs must
localize to canonical Japanese katakana via drug_names_ja.yaml.

Pre-104 defect: `chronic_medications.yaml` declared drug_ja katakana
for 14 oncology / chronic drugs (Osimertinib / Sorafenib / Lenvatinib
et al.) that were NOT in `drug_names_ja.yaml`. The FHIR-adapter
`_localize_drug_name` post-processor + LLM narrative pipeline both key
on `drug_names_ja.yaml`, so these drugs leaked bare English into JP
output (Osimertinib 11× / Sorafenib 9× / Lenvatinib 9× on the H100
p=100 s=125 verify).

Post-104 fix: 14 entries added to drug_names_ja.yaml. These tests
pin the presence of the katakana mappings so a future edit does not
silently regress the leak.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

# Session 104 additions — (English canonical name, expected JA katakana).
_ONCOLOGY_MAPPINGS = [
    ("Anastrozole", "アナストロゾール"),
    ("Bicalutamide", "ビカルタミド"),
    ("Capecitabine", "カペシタビン"),
    ("Carboplatin", "カルボプラチン"),
    ("Folic acid", "葉酸"),
    ("Lenvatinib", "レンバチニブ"),
    ("Leucovorin", "ロイコボリン"),
    ("Leuprorelin", "リュープロレリン"),
    ("Osimertinib", "オシメルチニブ"),
    ("Oxaliplatin", "オキサリプラチン"),
    ("Pemetrexed", "ペメトレキセド"),
    ("Sorafenib", "ソラフェニブ"),
    ("Tamoxifen", "タモキシフェン"),
    ("Trastuzumab", "トラスツズマブ"),
]


@pytest.mark.parametrize("en, ja", _ONCOLOGY_MAPPINGS)
def test_session104_oncology_drug_localizes_to_katakana(en: str, ja: str) -> None:
    """`_localize_drug_name(en, "JP")` must return the canonical katakana."""
    got = _localize_drug_name(en, "JP")
    assert ja in got, (
        f"session-104 Issue #1168 regression: {en!r} did not localize to "
        f"katakana {ja!r} (got {got!r}) — check drug_names_ja.yaml"
    )


def test_us_localization_unchanged() -> None:
    """US localization is a pass-through — this fix is JP-only."""
    for en, _ in _ONCOLOGY_MAPPINGS:
        got = _localize_drug_name(en, "US")
        assert en in got, f"US localization changed for {en!r}: {got!r}"
