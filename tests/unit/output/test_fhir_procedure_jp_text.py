"""Issue #360 G6: Procedure.code.text JP localization for supportive-care items.

Pins JP-locale translation of the ``{type}: {detail}`` composite text that
inpatient supportive-care Procedure resources fall back to when the CIF
record does not carry a K-code.

Concrete failure this test guards
---------------------------------
Before the fix (commit ``8b85ed45``, 2026-07-20), JP output emitted:

    {"code": {"text": "O2: Nasal cannula SpO2 >= 94%"}}

The composite English text (assembled at
``clinosim/modules/order/engine.py`` line 385 from disease-YAML
``supportive[]`` items) reached ``Procedure.code.text`` unchanged on JP
output. iris4h-ai's Clinical Cockpit displayed English protocol text on
what should be a Japanese procedures chart.

The fix runs the fallback display through ``_localize_dosage_terms`` on
JP output — sibling to the JP-localization already applied to
MedicationRequest / MedicationAdministration display text.
"""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_med_terms_ja
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_med_terms_cache() -> None:
    """Ensure each test sees the current med_terms_ja.yaml (this module edits
    the YAML in the same PR)."""
    load_med_terms_ja.cache_clear()


def _proc(display_name: str) -> dict[str, object]:
    """Build a minimal supportive-care Procedure input matching the
    order-engine composite pattern ``{type}: {detail}``."""
    return {
        "procedure_type": display_name,
        "encounter_id": "enc-1",
        "procedure_id": "proc-1",
        "start_datetime": "2026-06-15T09:00:00",
    }


# === JP output: composite text translated via _localize_dosage_terms ===


def test_jp_o2_supportive_procedure_gets_japanese_prefix() -> None:
    """The Issue #360 G6 core assertion: JP output of the v19 offender text
    ``"O2: Nasal cannula SpO2 >= 94%"`` now surfaces as Japanese in
    ``Procedure.code.text``."""
    res = _build_procedure(_proc("O2: Nasal cannula SpO2 >= 94%"), "pt-1", 0, "JP")
    text = res["code"]["text"]
    assert "酸素投与" in text
    assert "経鼻カニューラ" in text
    # Original English tokens should be replaced, not left as-is
    assert "O2:" not in text
    assert "Nasal cannula" not in text


def test_jp_iv_fluid_supportive_gets_japanese_prefix() -> None:
    """``IV_fluid: ...`` prefix translates to ``輸液``."""
    res = _build_procedure(_proc("IV_fluid: Normal saline 1000ml over 6h"), "pt-1", 0, "JP")
    assert "輸液" in res["code"]["text"]
    assert "IV_fluid" not in res["code"]["text"]


def test_jp_continuous_telemetry_gets_japanese_prefix() -> None:
    """``continuous_telemetry: ...`` prefix translates to ``心電図モニター``."""
    res = _build_procedure(_proc("continuous_telemetry: 24h monitoring"), "pt-1", 0, "JP")
    assert "心電図モニター" in res["code"]["text"]
    assert "continuous_telemetry" not in res["code"]["text"]


def test_jp_nutritional_support_gets_japanese_prefix() -> None:
    res = _build_procedure(_proc("nutritional_support: Early enteral feeding"), "pt-1", 0, "JP")
    assert "栄養サポート" in res["code"]["text"]


# === US output: unchanged (English composite preserved) ===


def test_us_supportive_procedure_text_is_unchanged() -> None:
    """US output must NOT translate — the composite English text is the
    expected form for US charts. Guards against accidental global
    localization that would break US tests."""
    res = _build_procedure(_proc("O2: Nasal cannula SpO2 >= 94%"), "pt-1", 0, "US")
    assert res["code"]["text"] == "O2: Nasal cannula SpO2 >= 94%"


# === Idempotence: coded procedures get translated K-code display, which is
# already Japanese and the extra localization pass is a no-op ===


def test_jp_already_japanese_display_is_idempotent() -> None:
    """Sanity: passing an already-Japanese display through the localizer
    doesn't corrupt it (idempotence — the map targets English tokens
    only). Guards against a future map entry that would accidentally
    match a Japanese substring."""
    # A K-code-resolved Japanese display would look like this
    already_jp = "尿道カテーテル挿入"
    # Simulate: proc has a procedure_code that resolves to already_jp;
    # we can achieve this via primary_code fallback. Simpler: exercise
    # the localizer helper directly.
    from clinosim.modules.output.fhir_r4.lib.localization import _localize_dosage_terms

    assert _localize_dosage_terms(already_jp) == already_jp


# === Issue #861: order-derived Procedure.code.text JA localization ===
#
# Three CIF Order.display_name templates hit the inline_bb.py:697 emit
# site (`_code_text = _localize_drug_name(display, ctx.country)`) without
# any yaml entry pre-#861, so they shipped as English on JP output:
#
#   - "compression stocking: Graduated compression stocking on unaffected leg"  (8 recs)
#   - "cervical immobilization: Cervical collar until cleared"                  (6 recs)
#   - "Emergent dialysis stat"                                                  (1 rec)
#
# Total 15 / 3,011 Procedure resources (0.50%). Fix: add drug_names_ja.yaml
# entries for the cleaned form (post-":" split) so the existing
# _localize_drug_name step-2 (strip-prefix + exact-match) resolves them.


def test_jp_localize_compression_stocking_full_string() -> None:
    """The Issue #861 offender ``"compression stocking: Graduated compression stocking on unaffected leg"``
    now resolves to JA via drug_names_ja.yaml exact-match on the cleaned
    (post-":") form."""
    from clinosim.locale.loader import load_drug_names_ja
    from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

    load_drug_names_ja.cache_clear()
    result = _localize_drug_name("compression stocking: Graduated compression stocking on unaffected leg", "JP")
    assert result == "弾性ストッキング(患側外・段階的圧迫)", f"got {result!r}"


def test_jp_localize_cervical_collar_full_string() -> None:
    from clinosim.locale.loader import load_drug_names_ja
    from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

    load_drug_names_ja.cache_clear()
    result = _localize_drug_name("cervical immobilization: Cervical collar until cleared", "JP")
    assert result == "頚椎固定(頚椎カラー・画像判定まで)", f"got {result!r}"


def test_jp_localize_emergent_dialysis_stat() -> None:
    """No ``:`` prefix here — the exact-match on the whole normalized string
    resolves at step 1 of _localize_drug_name."""
    from clinosim.locale.loader import load_drug_names_ja
    from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

    load_drug_names_ja.cache_clear()
    result = _localize_drug_name("Emergent dialysis stat", "JP")
    assert result == "緊急透析", f"got {result!r}"


def test_us_issue_861_strings_pass_through_unchanged() -> None:
    """US output must NOT translate these — the English form is the correct
    surface for US charts."""
    from clinosim.locale.loader import load_drug_names_ja
    from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

    load_drug_names_ja.cache_clear()
    for en in (
        "compression stocking: Graduated compression stocking on unaffected leg",
        "cervical immobilization: Cervical collar until cleared",
        "Emergent dialysis stat",
    ):
        assert _localize_drug_name(en, "US") == en


def test_drug_names_ja_contains_all_issue_861_forms() -> None:
    """Every Issue #861 phrase has a cleaned-form entry in the yaml."""
    from clinosim.locale.loader import load_drug_names_ja

    load_drug_names_ja.cache_clear()
    ja_dict = load_drug_names_ja()
    for cleaned in (
        "graduated compression stocking on unaffected leg",
        "cervical collar until cleared",
        "emergent dialysis stat",
    ):
        assert cleaned in ja_dict, f"missing JA entry for {cleaned!r}"
