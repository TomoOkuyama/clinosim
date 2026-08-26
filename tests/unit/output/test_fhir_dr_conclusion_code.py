"""Tests for DiagnosticReport.conclusionCode ↔ .conclusion / result flag consistency.

Issue #846: prior emit path set ``conclusionCode = 17621005`` (Normal) on
100 % of lab panel DRs regardless of any per-component ``H`` / ``L``
flags, because the flag was read from a ``_GroupedPanel.any_abnormal``
attribute that never existed on the ``NamedTuple``. 44.82 % of the
42,903 DRs in the JP p=10000 s500 sample carried ``参照範囲外`` in their
own ``.conclusion`` text while asserting Normal in ``conclusionCode``.

Fix: ``_build_lab_panel_conclusion`` now returns ``(text, has_abnormal)``
so a single walk over the panel's Observations drives both the free-text
summary and the SNOMED verdict — code and text are always internally
consistent by construction.

Both dataclass and dict order fixtures are exercised (PR-90 dual-access
discipline).
"""

from datetime import datetime

from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_lab_panel_reports
from clinosim.modules.output.fhir_r4.lib.common import BundleContext
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

_CBC_MEMBERS = ["WBC", "Hb", "Hct", "Plt"]
_ENC_ID = "enc-conc-846"
_PATIENT_ID = "pt-conc-846"
_T = datetime(2026, 6, 29, 8, 5)
_T_ISO = "2026-06-29T08:05:00"

SNOMED_NORMAL = "17621005"
SNOMED_ABNORMAL = "263654008"


def _make_panel_orders_dataclass(panel_key: str, members: list[str], flags: list[str]) -> list[Order]:
    """Order dataclass fixtures with per-component flags."""
    assert len(members) == len(flags)
    out = []
    for i, (name, flag) in enumerate(zip(members, flags)):
        o = Order(
            order_id=f"O{i}",
            encounter_id=_ENC_ID,
            patient_id=_PATIENT_ID,
            order_type=OrderType.LAB,
            order_code="X",
            display_name=name,
            ordered_datetime=_T,
            ordered_by="doc1",
            status=OrderStatus.RESULTED,
            panel_key=panel_key,
        )
        o.result = OrderResult(
            result_datetime=_T,
            performed_by="tech1",
            lab_name=name,
            value=6.0,
            unit="u",
            flag=flag,
        )
        out.append(o)
    return out


def _make_panel_orders_dict(panel_key: str, members: list[str], flags: list[str]) -> list[dict]:
    assert len(members) == len(flags)
    return [
        {
            "order_id": f"D{i}",
            "encounter_id": _ENC_ID,
            "patient_id": _PATIENT_ID,
            "order_type": "lab",
            "order_code": "X",
            "display_name": name,
            "urgency": "routine",
            "clinical_intent": "",
            "ordered_datetime": _T_ISO,
            "ordered_by": "doc1",
            "status": "resulted",
            "panel_key": panel_key,
            "result": {
                "result_datetime": _T_ISO,
                "performed_by": "tech1",
                "lab_name": name,
                "value": 6.0,
                "unit": "u",
                "flag": flag,
            },
        }
        for i, (name, flag) in enumerate(zip(members, flags))
    ]


def _ctx(orders: list) -> BundleContext:
    return BundleContext(
        record={"orders": orders},
        country="us",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id=_PATIENT_ID,
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id=_ENC_ID,
        patient_sex="",
    )


def _dr_verdict(dr: dict) -> str | None:
    for cc in (dr.get("conclusionCode") or [{}])[0].get("coding") or []:
        if cc.get("system") == "http://snomed.info/sct":
            return cc.get("code")
    return None


def _cbc_dr(orders: list) -> dict:
    reports = build_lab_panel_reports(_ctx(orders))
    # Issue #854 Bucket B (PR-diagnostic-report): DR.id is opaque, so
    # filter by the LAB_PANEL_DR_KEY_SYSTEM identifier structural-key
    # value (which retains the pre-#854 `{panel}-{enc}-{seq}` shape).
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import LAB_PANEL_DR_KEY_SYSTEM

    cbc = [
        r
        for r in reports
        if any(
            i.get("system") == LAB_PANEL_DR_KEY_SYSTEM and i.get("value", "").startswith("cbc-")
            for i in r.get("identifier", [])
        )
    ]
    assert len(cbc) == 1, f"expected 1 CBC DR, got {len(cbc)}"
    return cbc[0]


# --- All-normal → Normal verdict, no "out of range" text ---


def test_all_normal_flags_dataclass_normal_verdict():
    dr = _cbc_dr(_make_panel_orders_dataclass("CBC", _CBC_MEMBERS, ["", "", "", ""]))
    assert _dr_verdict(dr) == SNOMED_NORMAL
    assert "参照範囲外" not in dr.get("conclusion", "")
    assert "Out of reference range" not in dr.get("conclusion", "")


def test_all_normal_flags_dict_normal_verdict():
    dr = _cbc_dr(_make_panel_orders_dict("CBC", _CBC_MEMBERS, ["", "", "", ""]))
    assert _dr_verdict(dr) == SNOMED_NORMAL


# --- Any abnormal → Abnormal verdict + "out of range" text (issue #846 core) ---


def test_one_high_flag_dataclass_abnormal_verdict():
    dr = _cbc_dr(_make_panel_orders_dataclass("CBC", _CBC_MEMBERS, ["H", "", "", ""]))
    assert _dr_verdict(dr) == SNOMED_ABNORMAL, dr.get("conclusionCode")
    assert "Out of reference range" in dr["conclusion"] or "参照範囲外" in dr["conclusion"]


def test_one_low_flag_dict_abnormal_verdict():
    dr = _cbc_dr(_make_panel_orders_dict("CBC", _CBC_MEMBERS, ["", "L", "", ""]))
    assert _dr_verdict(dr) == SNOMED_ABNORMAL, dr.get("conclusionCode")
    assert "Out of reference range" in dr["conclusion"] or "参照範囲外" in dr["conclusion"]


def test_hh_critical_flag_abnormal_verdict():
    dr = _cbc_dr(_make_panel_orders_dataclass("CBC", _CBC_MEMBERS, ["", "", "HH", ""]))
    assert _dr_verdict(dr) == SNOMED_ABNORMAL


def test_ll_critical_flag_abnormal_verdict():
    dr = _cbc_dr(_make_panel_orders_dataclass("CBC", _CBC_MEMBERS, ["", "", "", "LL"]))
    assert _dr_verdict(dr) == SNOMED_ABNORMAL


def test_lowercase_flag_still_abnormal():
    """Flag comparison is case-insensitive (defensive against upstream drift)."""
    dr = _cbc_dr(_make_panel_orders_dataclass("CBC", _CBC_MEMBERS, ["h", "", "", ""]))
    assert _dr_verdict(dr) == SNOMED_ABNORMAL


def test_multiple_abnormal_flags_single_abnormal_verdict():
    """Multiple flagged components still emit ONE conclusionCode = Abnormal."""
    dr = _cbc_dr(_make_panel_orders_dataclass("CBC", _CBC_MEMBERS, ["H", "L", "H", ""]))
    assert _dr_verdict(dr) == SNOMED_ABNORMAL
    assert len(dr["conclusionCode"]) == 1


# --- Code / text single-walk invariant (issue #846 primary claim) ---


def test_conclusion_text_and_conclusion_code_never_disagree_dataclass():
    """Every DR emitted by build_lab_panel_reports keeps code ↔ text in sync."""
    for flags in (
        ["", "", "", ""],  # all normal
        ["H", "", "", ""],  # one high
        ["", "L", "", ""],  # one low
        ["H", "L", "", ""],  # mixed
        ["", "HH", "", ""],  # critical high
        ["LL", "", "", ""],  # critical low
    ):
        dr = _cbc_dr(_make_panel_orders_dataclass("CBC", _CBC_MEMBERS, flags))
        verdict = _dr_verdict(dr)
        conc = dr.get("conclusion", "")
        has_abn_marker = ("参照範囲外" in conc) or ("Out of reference range" in conc)
        if verdict == SNOMED_NORMAL:
            assert not has_abn_marker, f"Normal verdict but abnormal text: {conc!r}"
        elif verdict == SNOMED_ABNORMAL:
            assert has_abn_marker, f"Abnormal verdict but no abnormal marker: {conc!r}"


def test_non_abnormal_flag_labels_do_not_flip_verdict():
    """A non-abnormal flag string (e.g. 'N' explicit normal) stays Normal."""
    dr = _cbc_dr(_make_panel_orders_dataclass("CBC", _CBC_MEMBERS, ["N", "N", "N", "N"]))
    assert _dr_verdict(dr) == SNOMED_NORMAL


def test_empty_flag_stays_normal():
    dr = _cbc_dr(_make_panel_orders_dataclass("CBC", _CBC_MEMBERS, ["", "", "", ""]))
    assert _dr_verdict(dr) == SNOMED_NORMAL


# --- Imaging DR fallback: negation-aware conclusion (#846 fu) ---


def test_imaging_negated_normal_impression_ja():
    """Radiologist "認めず" — no abnormality found — commits to Normal."""
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
        _derive_imaging_conclusion_code,
    )

    coding = _derive_imaging_conclusion_code("今回撮像範囲内に急性期異常所見を認めず。", "ja")
    assert coding["coding"][0]["code"] == SNOMED_NORMAL


def test_imaging_negated_normal_impression_en():
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
        _derive_imaging_conclusion_code,
    )

    for phrase in (
        "No acute intracranial hemorrhage.",
        "No evidence of consolidation or effusion.",
        "Negative for fracture.",
        "Unremarkable chest radiograph.",
        "Within normal limits.",
    ):
        coding = _derive_imaging_conclusion_code(phrase, "en")
        assert coding["coding"][0]["code"] == SNOMED_NORMAL, phrase


def test_imaging_positive_abnormal_impression_ja():
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
        _derive_imaging_conclusion_code,
    )

    for phrase in (
        "右下葉に浸潤影を認める。",
        "L4椎体骨折を認める。",
        "肝右葉に3cm大の腫瘤を指摘する。",
    ):
        coding = _derive_imaging_conclusion_code(phrase, "ja")
        assert coding["coding"][0]["code"] == SNOMED_ABNORMAL, phrase


def test_imaging_positive_abnormal_impression_en():
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
        _derive_imaging_conclusion_code,
    )

    coding = _derive_imaging_conclusion_code("Right lower lobe consolidation.", "en")
    assert coding["coding"][0]["code"] == SNOMED_ABNORMAL


def test_imaging_empty_impression_normal():
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
        _derive_imaging_conclusion_code,
    )

    for text in ("", "   ", "\n\n"):
        coding = _derive_imaging_conclusion_code(text, "ja")
        assert coding["coding"][0]["code"] == SNOMED_NORMAL


def test_imaging_negation_overrides_abnormal_keyword():
    """The naive substring bug fixed by #846 fu — "no consolidation" was Abnormal."""
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
        _derive_imaging_conclusion_code,
    )

    assert _derive_imaging_conclusion_code("no acute consolidation.", "en")["coding"][0]["code"] == SNOMED_NORMAL
    assert _derive_imaging_conclusion_code("急性期異常所見を認めず。", "ja")["coding"][0]["code"] == SNOMED_NORMAL
