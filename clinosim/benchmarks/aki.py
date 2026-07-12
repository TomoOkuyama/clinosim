"""AKI onset benchmark — labels + creatinine delta baseline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clinosim.benchmarks.harness import (
    BaselineReport,
    LabelRow,
    compute_auroc,
)
from clinosim.benchmarks.sepsis import _iter_structural_records


def _is_aki_encounter(rec: dict) -> bool:
    """AKI 一次診断の encounter か判定(disease_id or N17 系 code)。"""
    ce = rec.get("condition_event", {}) or {}
    if str(ce.get("disease_id", "")).lower() == "acute_kidney_injury":
        return True
    dx = rec.get("clinical_diagnosis", {}) or {}
    code = str(dx.get("admission_diagnosis_code", "")).upper()
    return code.startswith("N17") or code == "N19"


def _creatinine_delta(rec: dict) -> float | None:
    """入院時 baseline creatinine と入院中 peak の差(mg/dL)。

    KDIGO Stage 1 の criteria = SCr の 0.3 mg/dL 増加 or 1.5x 上昇。
    baseline は入院初日、peak は全期間 max。0.3 mg/dL 増を threshold にする。
    """
    labs = rec.get("lab_results", []) or []
    cr_values = [
        float(lab.get("value"))
        for lab in labs
        if lab.get("value") is not None
        and str(lab.get("lab_name", "")).lower() in {"creatinine", "cr"}
    ]
    if len(cr_values) < 2:
        return None
    baseline = cr_values[0]
    peak = max(cr_values)
    return float(peak - baseline)


def extract_aki_labels(cif_dir: str | Path) -> list[LabelRow]:
    """CIF から AKI 判定 label 集合を抽出。

    ``label=1`` = AKI 診断あり(``condition_event.disease_id ==
    "acute_kidney_injury"`` or ICD N17/N19)。
    context には ``creatinine_delta`` (peak - baseline mg/dL) を格納。
    """
    records: list[LabelRow] = []
    for rec in _iter_structural_records(Path(cif_dir)):
        patient_id = str(rec.get("patient", {}).get("patient_id", "") or "")
        encs = rec.get("encounters", []) or []
        enc_id = str((encs[0] if encs else {}).get("encounter_id", ""))
        label = 1 if _is_aki_encounter(rec) else 0
        ctx: dict[str, Any] = {"creatinine_delta": _creatinine_delta(rec)}
        records.append(LabelRow(
            patient_id=patient_id, encounter_id=enc_id,
            label=label, context=ctx,
        ))
    return records


def creatinine_delta_baseline(
    labels: list[LabelRow], threshold: float = 0.3,
) -> BaselineReport:
    """KDIGO Stage 1 SCr delta > threshold(mg/dL)で AKI を予測。

    context の ``creatinine_delta`` を score として AUROC を計算。
    欠測は 0(non-AKI 予測)。
    """
    if not labels:
        return BaselineReport(
            name="creatinine_delta", n=0, n_positive=0, prevalence=0.0,
            auroc=0.0, accuracy=0.0, positive_predicted_rate=0.0,
            rationale="empty label set",
        )
    y_true = [r.label for r in labels]
    y_score = [
        float(r.context.get("creatinine_delta") or 0.0)
        for r in labels
    ]
    auroc = compute_auroc(y_true, y_score)
    predicted = [1 if s > threshold else 0 for s in y_score]
    correct = sum(1 for yt, yp in zip(y_true, predicted) if yt == yp)
    n = len(labels)
    n_pos = sum(y_true)
    return BaselineReport(
        name="creatinine_delta",
        n=n,
        n_positive=n_pos,
        prevalence=n_pos / n,
        auroc=auroc,
        accuracy=correct / n,
        positive_predicted_rate=sum(predicted) / n,
        rationale=(
            f"KDIGO 2012 Stage 1 criterion: SCr rise of {threshold} mg/dL "
            "from baseline defines AKI. Uses raw delta as continuous score for "
            "AUROC and threshold rule for accuracy."
        ),
    )
