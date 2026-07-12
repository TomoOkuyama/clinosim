"""P2-15 benchmark harness unit tests (session 48).

Verify:
- compute_auroc arithmetic on synthetic data
- majority_baseline degenerate cases
- sepsis / aki label extractors read structural CIF
- lactate / creatinine baselines score correctly
"""
from __future__ import annotations

import json

import pytest


def _write_cif(tmp_path, records):
    """`tmp_path/structural/patients/{seq:04d}.json` に records を書き出す。"""
    patient_dir = tmp_path / "structural" / "patients"
    patient_dir.mkdir(parents=True)
    for i, r in enumerate(records):
        (patient_dir / f"{i:04d}.json").write_text(
            json.dumps(r, ensure_ascii=False), encoding="utf-8",
        )
    return tmp_path


@pytest.mark.unit
def test_auroc_perfect_separation():
    from clinosim.benchmarks import compute_auroc
    assert compute_auroc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0


@pytest.mark.unit
def test_auroc_random_scores_around_half():
    from clinosim.benchmarks import compute_auroc
    # 反転 → 0.0
    assert compute_auroc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0
    # 完全 tie → 0.5
    assert compute_auroc([0, 0, 1, 1], [0.5, 0.5, 0.5, 0.5]) == 0.5


@pytest.mark.unit
def test_auroc_degenerate_classes_return_half():
    """全て positive or 全て negative は AUROC 未定義、規約 0.5 を返す。"""
    from clinosim.benchmarks import compute_auroc
    assert compute_auroc([1, 1, 1], [0.1, 0.5, 0.9]) == 0.5
    assert compute_auroc([0, 0, 0], [0.1, 0.5, 0.9]) == 0.5


@pytest.mark.unit
def test_majority_baseline_rare_positive_predicts_negative():
    from clinosim.benchmarks import LabelRow, majority_baseline
    labels = [LabelRow("p", "e", 0, {}) for _ in range(9)] + [LabelRow("p", "e", 1, {})]
    r = majority_baseline(labels)
    assert r.n == 10
    assert r.n_positive == 1
    assert r.prevalence == 0.1
    assert r.positive_predicted_rate == 0.0
    assert r.accuracy == 0.9
    assert r.auroc == 0.5


@pytest.mark.unit
def test_majority_baseline_frequent_positive_predicts_positive():
    from clinosim.benchmarks import LabelRow, majority_baseline
    labels = [LabelRow("p", "e", 1, {}) for _ in range(6)] + [LabelRow("p", "e", 0, {}) for _ in range(4)]
    r = majority_baseline(labels)
    assert r.positive_predicted_rate == 1.0
    assert r.accuracy == 0.6


@pytest.mark.unit
def test_extract_sepsis_labels_reads_structural_cif(tmp_path):
    from clinosim.benchmarks import extract_sepsis_labels
    _write_cif(tmp_path, [
        {
            "patient": {"patient_id": "P1"},
            "encounters": [{"encounter_id": "E1"}],
            "condition_event": {"disease_id": "sepsis"},
            "clinical_diagnosis": {},
            "lab_results": [{"lab_name": "Lactate", "value": 4.5}],
        },
        {
            "patient": {"patient_id": "P2"},
            "encounters": [{"encounter_id": "E2"}],
            "condition_event": {"disease_id": "bacterial_pneumonia"},
            "clinical_diagnosis": {"admission_diagnosis_code": "J18.9"},
            "lab_results": [{"lab_name": "Lactate", "value": 1.5}],
        },
    ])
    labels = extract_sepsis_labels(tmp_path)
    assert len(labels) == 2
    label_map = {r.patient_id: r.label for r in labels}
    assert label_map == {"P1": 1, "P2": 0}


@pytest.mark.unit
def test_lactate_threshold_baseline_scores_and_predicts(tmp_path):
    from clinosim.benchmarks import (
        extract_sepsis_labels, lactate_threshold_baseline,
    )
    _write_cif(tmp_path, [
        {
            "patient": {"patient_id": "P1"},
            "encounters": [{"encounter_id": "E1"}],
            "condition_event": {"disease_id": "sepsis"},
            "clinical_diagnosis": {},
            "lab_results": [{"lab_name": "Lactate", "value": 3.5}],
        },
        {
            "patient": {"patient_id": "P2"},
            "encounters": [{"encounter_id": "E2"}],
            "condition_event": {"disease_id": "acute_mi"},
            "clinical_diagnosis": {},
            "lab_results": [{"lab_name": "Lactate", "value": 1.0}],
        },
    ])
    labels = extract_sepsis_labels(tmp_path)
    r = lactate_threshold_baseline(labels)
    assert r.n == 2
    assert r.n_positive == 1
    # perfect separation (sepsis lactate 3.5 > non-sepsis 1.0)
    assert r.auroc == 1.0
    # threshold=2 → sepsis case predicted positive, other negative
    assert r.accuracy == 1.0
    assert r.positive_predicted_rate == 0.5


@pytest.mark.unit
def test_extract_aki_labels_and_creatinine_baseline(tmp_path):
    from clinosim.benchmarks import (
        creatinine_delta_baseline, extract_aki_labels,
    )
    _write_cif(tmp_path, [
        {
            "patient": {"patient_id": "P1"},
            "encounters": [{"encounter_id": "E1"}],
            "condition_event": {"disease_id": "acute_kidney_injury"},
            "clinical_diagnosis": {},
            "lab_results": [
                {"lab_name": "Creatinine", "value": 0.9},
                {"lab_name": "Creatinine", "value": 2.5},
            ],
        },
        {
            "patient": {"patient_id": "P2"},
            "encounters": [{"encounter_id": "E2"}],
            "condition_event": {"disease_id": "acute_mi"},
            "clinical_diagnosis": {},
            "lab_results": [
                {"lab_name": "Creatinine", "value": 1.0},
                {"lab_name": "Creatinine", "value": 1.1},
            ],
        },
    ])
    labels = extract_aki_labels(tmp_path)
    label_map = {r.patient_id: r.label for r in labels}
    assert label_map == {"P1": 1, "P2": 0}
    r = creatinine_delta_baseline(labels)
    assert r.n == 2
    assert r.n_positive == 1
    assert r.auroc == 1.0
    # threshold=0.3 → P1 delta=1.6 > 0.3 (positive), P2 delta=0.1 < 0.3 (negative)
    assert r.accuracy == 1.0


@pytest.mark.unit
def test_cli_dispatch_success(tmp_path, capsys):
    from clinosim.benchmarks.cli import dispatch_benchmark
    _write_cif(tmp_path, [{
        "patient": {"patient_id": "P1"},
        "encounters": [{"encounter_id": "E1"}],
        "condition_event": {"disease_id": "sepsis"},
        "clinical_diagnosis": {},
        "lab_results": [{"lab_name": "Lactate", "value": 3.0}],
    }])
    import argparse
    args = argparse.Namespace(task="sepsis", cif_dir=str(tmp_path), json=False)
    code = dispatch_benchmark(args)
    assert code == 0
    out = capsys.readouterr().out
    assert "sepsis" in out
    assert "AUROC" in out


@pytest.mark.unit
def test_cli_dispatch_missing_dir_returns_nonzero(tmp_path, capsys):
    from clinosim.benchmarks.cli import dispatch_benchmark
    import argparse
    args = argparse.Namespace(
        task="sepsis", cif_dir=str(tmp_path / "does-not-exist"), json=False,
    )
    code = dispatch_benchmark(args)
    assert code == 2


@pytest.mark.unit
def test_cli_dispatch_empty_cohort_returns_nonzero(tmp_path):
    from clinosim.benchmarks.cli import dispatch_benchmark
    (tmp_path / "structural" / "patients").mkdir(parents=True)
    import argparse
    args = argparse.Namespace(task="aki", cif_dir=str(tmp_path), json=False)
    code = dispatch_benchmark(args)
    assert code == 3
