"""ECG and coronary angiography reports (Issue #3020).

An ECG is read for rhythm, rate, axis, intervals and ST-T changes, and a
coronary angiogram for the culprit lesion — not with the radiology impression
templates or the generic "no acute findings in the imaged field" report. The
content follows the patient's state: the stay's disease and ICD-10 code (the
acute-MI territory), a chronic atrial fibrillation diagnosis and the heart
rate recorded nearest the study. Data: ``reference_data/cardiac_reports.yaml``;
wording: ``cardiac_report.*`` in ``locale/shared/narrative_phrases.yaml``.
No RNG.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_validated_yaml
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.types.imaging import RadiologyReport

_YAML = Path(__file__).resolve().parent / "reference_data" / "cardiac_reports.yaml"
_ACUTE_MI = "acute_mi"


class _Ecg(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sinus_bradycardia_below: int = Field(gt=0)
    sinus_tachycardia_above: int = Field(gt=0)
    atrial_fibrillation_diseases: list[str]
    atrial_fibrillation_codes: list[str]
    acute_mi_st_pattern: dict[str, str] = Field(min_length=1)


class _CoronaryAngiography(BaseModel):
    model_config = ConfigDict(extra="forbid")

    culprit_by_code: dict[str, str] = Field(min_length=1)


class CardiacReports(BaseModel):
    """Shape of ``cardiac_reports.yaml``."""

    model_config = ConfigDict(extra="forbid")

    ecg: _Ecg
    coronary_angiography: _CoronaryAngiography


@lru_cache(maxsize=1)
def _config() -> CardiacReports:
    return CardiacReports.model_validate(load_validated_yaml(_YAML, CardiacReports))


def _by_code(table: dict[str, str], code: str) -> str | None:
    """The entry whose key is the longest prefix of ``code``."""
    hits = [k for k in table if code.upper().startswith(k.upper())]
    return table[max(hits, key=len)] if hits else None


def _study_time(order: Any) -> datetime | None:
    when = _o(order, "ordered_datetime", None)
    return when if isinstance(when, datetime) else None


def _heart_rate(record: Any, when: datetime | None) -> int | None:
    """Heart rate of the vital-sign set recorded nearest the study."""
    rows = [
        (v, _o(v, "timestamp", None))
        for v in (_o(record, "vital_signs", []) or [])
        if _o(v, "heart_rate", None) is not None
    ]
    rows = [(v, ts) for v, ts in rows if isinstance(ts, datetime)]
    if not rows:
        return None
    if when is None:
        return int(_o(rows[0][0], "heart_rate", 0))
    best = min(rows, key=lambda r: abs((r[1] - when).total_seconds()))
    return int(_o(best[0], "heart_rate", 0))


def _day_of_stay(record: Any, when: datetime | None) -> int:
    encs = _o(record, "encounters", []) or []
    admit = _o(encs[0], "admission_datetime", None) if encs else None
    if not isinstance(admit, datetime) or when is None:
        return 0
    return max(0, (when.date() - admit.date()).days)


def _stay_code(record: Any) -> str:
    dx = _o(record, "clinical_diagnosis", None)
    return str(_o(dx, "admission_diagnosis_code", "") or _o(dx, "discharge_diagnosis_code", "") or "")


def _disease_id(record: Any) -> str:
    return str((_o(record, "extensions", {}) or {}).get("_disease_id", "") or _o(record, "disease_id", "") or "")


def _chronic_codes(record: Any) -> list[str]:
    patient = _o(record, "patient", None)
    return [str(_o(c, "code", "") or c) for c in (_o(patient, "chronic_conditions", []) or [])]


def _is_acute_mi(record: Any) -> bool:
    return _disease_id(record) == _ACUTE_MI or _stay_code(record).upper().startswith("I21")


def _text(parts: list[tuple[str, dict[str, Any]]], lang: str) -> str:
    """Phrases joined as one sentence in ``lang``."""
    return t("list_sep.serial", lang).join(t(f"cardiac_report.{k}", lang, **kw) for k, kw in parts) + t(
        "list_sep.period", lang
    )


def _ecg_report(record: Any, order: Any, report_id: str) -> RadiologyReport:
    cfg = _config().ecg
    when = _study_time(order)
    hr = _heart_rate(record, when)
    af = _disease_id(record) in cfg.atrial_fibrillation_diseases or any(
        c.upper().startswith(tuple(cfg.atrial_fibrillation_codes)) for c in _chronic_codes(record)
    )
    if af:
        rhythm = "atrial_fibrillation"
    elif hr is not None and hr > cfg.sinus_tachycardia_above:
        rhythm = "sinus_tachycardia"
    elif hr is not None and hr < cfg.sinus_bradycardia_below:
        rhythm = "sinus_bradycardia"
    else:
        rhythm = "sinus"
    st = "none"
    impression = {
        "atrial_fibrillation": "atrial_fibrillation_rapid"
        if hr is not None and hr > cfg.sinus_tachycardia_above
        else "atrial_fibrillation",
        "sinus_tachycardia": "sinus_tachycardia",
        "sinus_bradycardia": "sinus_bradycardia",
        "sinus": "normal",
    }[rhythm]
    if _is_acute_mi(record):
        pattern = _by_code(cfg.acute_mi_st_pattern, _stay_code(record)) or "ischemic"
        # The admission ECG (and one ordered STAT on a later day for ongoing
        # ischemia) shows the acute pattern; later routine ECGs its evolution.
        acute = _day_of_stay(record, when) == 0 or "stat" in str(_o(order, "display_name", "") or "").lower()
        if acute:
            st, impression = pattern, pattern
        else:
            st = "evolving_elevation" if pattern.endswith("elevation") else "evolving"
            impression = "evolving"
    parts: list[tuple[str, dict[str, Any]]] = [(f"ecg_rhythm_{rhythm}", {})]
    if hr is not None:
        parts.append(("ecg_rate", {"hr": hr}))
    parts.append(("ecg_axis_normal", {}))
    parts.append(("ecg_intervals_normal_af" if af else "ecg_intervals_normal", {}))
    parts.append((f"ecg_st_{st}", {}))
    return RadiologyReport(
        report_id=report_id,
        status="final",
        findings_text=_text(parts, "en"),
        findings_text_ja=_text(parts, "ja"),
        impression_text=t(f"cardiac_report.ecg_impression_{impression}", "en"),
        impression_text_ja=t(f"cardiac_report.ecg_impression_{impression}", "ja"),
    )


def _coronary_angiography_report(record: Any, order: Any, report_id: str) -> RadiologyReport:
    if not _is_acute_mi(record):
        findings, impression = "cag_no_significant_stenosis", "cag_impression_no_significant_stenosis"
    elif "repeat" in str(_o(order, "display_name", "") or "").lower():
        findings, impression = "cag_residual", "cag_impression_residual"
    else:
        lesion = _by_code(_config().coronary_angiography.culprit_by_code, _stay_code(record)) or "lad"
        findings, impression = f"cag_culprit_{lesion}", "cag_impression_culprit"
    return RadiologyReport(
        report_id=report_id,
        status="final",
        findings_text=t(f"cardiac_report.{findings}", "en"),
        findings_text_ja=t(f"cardiac_report.{findings}", "ja"),
        impression_text=t(f"cardiac_report.{impression}", "en"),
        impression_text_ja=t(f"cardiac_report.{impression}", "ja"),
    )


def cardiac_report(modality: str, record: Any, order: Any, report_id: str) -> RadiologyReport | None:
    """The report of an ECG (modality ``ECG``) or a coronary angiogram (``XA``);
    ``None`` for any other modality, which keeps the radiology report."""
    if modality == "ECG":
        return _ecg_report(record, order, report_id)
    if modality == "XA":
        return _coronary_angiography_report(record, order, report_id)
    return None
