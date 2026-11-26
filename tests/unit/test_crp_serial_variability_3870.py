"""Inpatient serial CRP variability (Issue #3870).

The per-draw biological noise of CRP used the within-subject CV of unselected
subjects (0.423) as independent noise on every inpatient draw, so a constant
true CRP gave consecutive-day results that differ more than three-fold in
about one pair in eight. Serial inpatient draws use a smaller CV from
``serial_biological_cv`` in ``lab_constants.yaml``; the course comes from the
physiological state, not from per-draw noise.
"""

from __future__ import annotations

import numpy as np

from clinosim.modules.observation import engine
from clinosim.modules.observation.engine import (
    BIOLOGICAL_CV,
    SERIAL_BIOLOGICAL_CV,
    apply_realistic_variability,
    generate_lab_result,
)


def _series(serial: bool, n: int = 4000, true: float = 150.0, lab: str = "CRP") -> np.ndarray:
    rng = np.random.default_rng(7)
    return np.array([generate_lab_result(lab, true, rng, serial=serial) for _ in range(n)], dtype=float)


def _extreme_pair_rate(x: np.ndarray) -> float:
    with np.errstate(divide="ignore"):
        ratio = x[1:] / x[:-1]
    return float(np.mean((ratio > 3) | (ratio < 1 / 3)))


def test_serial_crp_of_a_constant_state_varies_by_a_few_tens_of_percent_at_most() -> None:
    x = _series(serial=True)
    assert _extreme_pair_rate(x) == 0.0
    assert 0.05 < float(np.std(x) / np.mean(x)) < 0.20


def test_non_serial_crp_keeps_the_unselected_subject_variability() -> None:
    x = _series(serial=False)
    assert _extreme_pair_rate(x) > 0.05  # the defect the serial path removes
    assert abs(float(np.std(x) / np.mean(x)) - 0.43) < 0.06


def test_serial_cv_is_data_and_only_for_crp() -> None:
    assert set(SERIAL_BIOLOGICAL_CV) == {"CRP"}
    assert SERIAL_BIOLOGICAL_CV["CRP"] < BIOLOGICAL_CV["CRP"]


def test_serial_flag_leaves_every_other_analyte_unchanged() -> None:
    for lab, true in (("PCT", 3.0), ("BNP", 400.0), ("Lactate", 2.5), ("Creatinine", 1.2)):
        a = np.random.default_rng(3)
        b = np.random.default_rng(3)
        assert apply_realistic_variability(lab, true, a, serial=True) == apply_realistic_variability(lab, true, b)


def test_serial_flag_consumes_the_same_random_stream() -> None:
    a = np.random.default_rng(11)
    b = np.random.default_rng(11)
    apply_realistic_variability("CRP", 80.0, a, serial=True)
    apply_realistic_variability("CRP", 80.0, b, serial=False)
    assert a.random() == b.random()


def test_a_step_change_in_the_true_value_gives_a_monotone_lagged_course() -> None:
    rng = np.random.default_rng(5)
    true = [150, 150, 120, 90, 60, 40, 25, 15]
    out = [generate_lab_result("CRP", float(t), rng, serial=True) for t in true]
    assert all(later <= earlier * 1.35 for earlier, later in zip(out, out[1:], strict=False))
    assert out[-1] < out[0] / 3


def test_the_inpatient_lab_pipeline_asks_for_serial_variability(monkeypatch) -> None:
    from clinosim.simulator import lab_pipeline

    calls: list[bool] = []
    real = engine.generate_lab_result

    def spy(lab_name, true_value, rng, **kw):
        calls.append(bool(kw.get("serial")))
        return real(lab_name, true_value, rng, **kw)

    monkeypatch.setattr(lab_pipeline, "generate_lab_result", spy)
    from clinosim.simulator import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    run_forced(
        ForcedScenario(disease_id="bacterial_pneumonia", count=1, severity="moderate"),
        SimulatorConfig(random_seed=42, country="US"),
    )
    assert calls and all(calls)
