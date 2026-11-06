"""Issue #2735: monitoring labs come from the shared true-lab function."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.monitoring.enricher import _derive_true_labs_for_patient

pytestmark = pytest.mark.unit


def _patient() -> SimpleNamespace:
    return SimpleNamespace(
        patient_id="P1",
        sex="F",
        age=64,
        chronic_conditions=[SimpleNamespace(code="E11.9")],
        current_medications=[],
        longitudinal_history=[],
    )


def test_monitoring_hba1c_follows_the_longitudinal_hba1c(monkeypatch: pytest.MonkeyPatch) -> None:
    import clinosim.simulator.lab_pipeline as lp

    monkeypatch.setattr(lp, "hba1c_latent_at", lambda patient, when: 8.4)
    labs = _derive_true_labs_for_patient(_patient(), datetime(2025, 6, 1, 9))
    assert labs["HbA1c"] == pytest.approx(8.4)


def test_analytes_physiology_does_not_model_fall_back_to_reference_normals() -> None:
    labs = _derive_true_labs_for_patient(_patient(), datetime(2025, 6, 1, 9))
    assert "TSH" in labs and "PT_INR" in labs
