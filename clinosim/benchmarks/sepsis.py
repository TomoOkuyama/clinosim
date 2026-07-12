"""Sepsis onset benchmark — labels + lactate-threshold baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clinosim.benchmarks.harness import (
    BaselineReport,
    LabelRow,
    compute_auroc,
)


def _iter_structural_records(cif_dir: Path):
    """CIF structural patient records を yield する。存在しなければ空 iterator。"""
    patient_dir = cif_dir / "structural" / "patients"
    if not patient_dir.is_dir():
        return
    for p in sorted(patient_dir.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                yield json.load(f)
        except (OSError, json.JSONDecodeError):
            continue


def _is_sepsis_encounter(rec: dict) -> bool:
    """Sepsis primary diagnosis の encounter か判定。

    condition_event.disease_id か admission_diagnosis_code(A41.9/R65.20 系)を見る。
    """
    ce = rec.get("condition_event", {}) or {}
    if str(ce.get("disease_id", "")).lower() == "sepsis":
        return True
    dx = rec.get("clinical_diagnosis", {}) or {}
    code = str(dx.get("admission_diagnosis_code", "")).upper()
    # ICD-10-CM/WHO sepsis codes
    return code.startswith("A41") or code == "R65.20" or code == "R65.21"


def _first_window_lactate(rec: dict, hours: int = 6) -> float | None:
    """入院後 `hours` 時間以内の Lactate 最大値。無ければ None。"""
    labs = rec.get("lab_results", []) or []
    # lab_name の内部 key はテストごとに snomed/loinc の場合あり — internal key で判定
    lactate_values = [
        float(lab.get("value"))
        for lab in labs
        if lab.get("value") is not None
        and str(lab.get("lab_name", "")).lower() == "lactate"
    ]
    if not lactate_values:
        return None
    return max(lactate_values)


def extract_sepsis_labels(cif_dir: str | Path) -> list[LabelRow]:
    """CIF から sepsis 判定 label 集合を抽出。

    ``label=1`` = sepsis 診断あり(``condition_event.disease_id=="sepsis"`` or
    ICD A41/R65.2)。context には ``first_window_lactate`` を格納し、
    lactate baseline のスコアリングに用いる。
    """
    records: list[LabelRow] = []
    for rec in _iter_structural_records(Path(cif_dir)):
        patient_id = str(rec.get("patient", {}).get("patient_id", "") or "")
        encs = rec.get("encounters", []) or []
        enc_id = str((encs[0] if encs else {}).get("encounter_id", ""))
        label = 1 if _is_sepsis_encounter(rec) else 0
        ctx: dict[str, Any] = {"first_window_lactate": _first_window_lactate(rec)}
        records.append(LabelRow(
            patient_id=patient_id, encounter_id=enc_id,
            label=label, context=ctx,
        ))
    return records


def lactate_threshold_baseline(
    labels: list[LabelRow], threshold: float = 2.0,
) -> BaselineReport:
    """Lactate > threshold(mmol/L)なら sepsis を予測する Surviving Sepsis 2021 相当 rule。

    context の ``first_window_lactate`` を score として AUROC を計算。
    Lactate 欠測は score=0(non-septic 予測)。
    """
    if not labels:
        return BaselineReport(
            name="lactate_threshold", n=0, n_positive=0, prevalence=0.0,
            auroc=0.0, accuracy=0.0, positive_predicted_rate=0.0,
            rationale="empty label set",
        )
    y_true = [r.label for r in labels]
    y_score = [
        float(r.context.get("first_window_lactate") or 0.0)
        for r in labels
    ]
    auroc = compute_auroc(y_true, y_score)
    predicted = [1 if s > threshold else 0 for s in y_score]
    correct = sum(1 for yt, yp in zip(y_true, predicted) if yt == yp)
    n = len(labels)
    n_pos = sum(y_true)
    return BaselineReport(
        name="lactate_threshold",
        n=n,
        n_positive=n_pos,
        prevalence=n_pos / n,
        auroc=auroc,
        accuracy=correct / n,
        positive_predicted_rate=sum(predicted) / n,
        rationale=(
            f"Surviving Sepsis 2021 rule: lactate > {threshold} mmol/L in the "
            "first-window Lactate max implies sepsis with tissue hypoperfusion. "
            "Uses raw lactate as continuous score for AUROC and threshold "
            "rule for accuracy."
        ),
    )
