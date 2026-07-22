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
from clinosim.modules.output._fhir_procedures import _build_procedure

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
    from clinosim.modules.output._fhir_localization import _localize_dosage_terms

    assert _localize_dosage_terms(already_jp) == already_jp
