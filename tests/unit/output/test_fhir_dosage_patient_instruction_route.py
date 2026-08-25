"""Tests for route-aware ``Dosage.patientInstruction`` (Issue #848).

Prior emit derived the JA ``patientInstruction`` phrase from the
frequency label alone and every generated template ended in
``"内服してください"`` ("take orally") — so a saline IV drip (route
``静注``) shipped with ``PI="毎日1回、指示された時間帯に内服してください"``
and the two fields inside one resource disagreed on the route
(33.0 % of populated JP PI, saline 100% wrong at 838 records).

Fix: ``_resolve_patient_instruction_ja`` picks the phrasing template
from the route family (parenteral / inhalation / rectal / patch /
topical / eye drop / oral) and folds in the frequency only for oral.
Unknown routes yield the empty string so the caller drops
``patientInstruction`` rather than emit a contradiction.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.lib.common import (
    _resolve_patient_instruction_ja,
    build_dosage_instruction,
)

# --- route resolver directly ---


def test_pi_oral_ja_composes_freq_phrase():
    assert _resolve_patient_instruction_ja("経口", "qd", 1) == "毎日1回、指示された時間帯に内服してください"
    assert _resolve_patient_instruction_ja("経口", "bid", 2) == "毎日2回、朝・夕の指示された時間帯に内服してください"
    assert (
        _resolve_patient_instruction_ja("経口", "tid", 3) == "毎日3回、朝・昼・夕の指示された時間帯に内服してください"
    )


def test_pi_parenteral_ja_nurse_administered():
    for route in ("静注", "点滴", "皮下注", "皮下", "筋注", "静脈"):
        assert _resolve_patient_instruction_ja(route, "qd", 1) == "医師の指示のもと、看護師が投与します", route


def test_pi_inhalation_ja():
    assert _resolve_patient_instruction_ja("吸入", "bid", 2) == "指示された方法で吸入してください"


def test_pi_rectal_ja():
    for route in ("直腸", "坐薬", "座薬"):
        assert _resolve_patient_instruction_ja(route, "qd", 1) == "指示された時間に直腸内に挿入してください"


def test_pi_transdermal_patch_ja():
    assert _resolve_patient_instruction_ja("貼付", "qd", 1) == "指示された部位に貼付してください"


def test_pi_topical_ointment_ja():
    for route in ("塗布", "外用", "軟膏"):
        assert _resolve_patient_instruction_ja(route, "qd", 1) == "指示された部位に塗布してください"


def test_pi_eye_drop_ja():
    assert _resolve_patient_instruction_ja("点眼", "qid", 4) == "指示された時間に点眼してください"


def test_pi_sublingual_ja_is_not_oral_swallow():
    """Sublingual is patient-administered but under the tongue — not `内服`."""
    result = _resolve_patient_instruction_ja("舌下", "prn", None)
    assert result == "指示された時に舌下に投与してください"


def test_pi_unknown_route_returns_empty():
    """Unknown route → empty → caller omits patientInstruction (Issue #848
    recommendation: an absent field is preferable to a contradiction)."""
    assert _resolve_patient_instruction_ja("", "qd", 1) == ""
    assert _resolve_patient_instruction_ja(None, "qd", 1) == ""


# --- integrated build_dosage_instruction ---


def _dose(route: str, freq: str = "qd", freq_per_day: int | None = 1) -> dict:
    return build_dosage_instruction(
        {
            "dose_quantity": 100,
            "dose_unit": "mL",
            "frequency": freq,
            "frequency_per_day": freq_per_day,
            "route": route,
        },
        country="JP",
    )


def test_build_dosage_iv_saline_no_more_take_orally():
    """Saline (Issue #848 sample) — 静注 → nurse-administered, not 内服."""
    d = _dose("IV", freq="qd", freq_per_day=1)
    assert d["patientInstruction"] == "医師の指示のもと、看護師が投与します"


def test_build_dosage_oral_still_oral():
    d = _dose("PO", freq="qd", freq_per_day=1)
    assert d["patientInstruction"] == "毎日1回、指示された時間帯に内服してください"


def test_build_dosage_inhaled_is_inhalation_verb():
    d = _dose("INH", freq="bid", freq_per_day=2)
    assert d["patientInstruction"] == "指示された方法で吸入してください"


def test_build_dosage_transdermal_patch_is_patch_verb():
    d = build_dosage_instruction(
        {
            "dose_quantity": 1,
            "dose_unit": "枚",
            "frequency": "qd",
            "frequency_per_day": 1,
            "route": "貼付",
        },
        country="JP",
    )
    assert d["patientInstruction"] == "指示された部位に貼付してください"


def test_build_dosage_authored_instruction_still_wins():
    """Issue #476 opt-in pattern preserved — CIF-authored
    `patient_instruction` overrides the derived phrase, regardless of route."""
    d = build_dosage_instruction(
        {
            "dose_quantity": 500,
            "dose_unit": "mL",
            "frequency": "qd",
            "frequency_per_day": 1,
            "route": "静注",
            "patient_instruction": "24時間かけて緩徐投与",
        },
        country="JP",
    )
    assert d["patientInstruction"] == "24時間かけて緩徐投与"


def test_build_dosage_timing_labels_are_route_independent():
    """`qhs` / `ac` / `pc` / `qam` / `qpm` / `prn` describe WHEN — no
    route dependency; they emit unchanged (were correct pre-#848)."""
    for freq, expected in [("qhs", "就寝前"), ("ac", "食前"), ("pc", "食後"), ("prn", "頓用（必要時）")]:
        d = build_dosage_instruction(
            {
                "dose_quantity": 10,
                "dose_unit": "mg",
                "frequency": freq,
                "route": "PO",
            },
            country="JP",
        )
        assert d["patientInstruction"] == expected, freq


def test_build_dosage_iv_with_no_route_string_omits_pi():
    """Route ``""`` yields no PI (Issue #848 alternative — omit rather than
    emit a template that would contradict the resource's own route)."""
    d = build_dosage_instruction(
        {
            "dose_quantity": 100,
            "dose_unit": "mL",
            "frequency": "unknown-freq-token",
            "route": "",
        },
        country="JP",
    )
    # No PI key at all
    assert "patientInstruction" not in (d or {})
