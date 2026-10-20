"""AR(1) yaml: `initial.clamp` defaults to top-level `clamp` when omitted.

Deferred minor from the Phase 3 whole-branch review — the two clamp
blocks typically carry identical values, so making the initial variant
default to the step variant removes the DRY violation + divergence risk.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.modules.longitudinal import loader as loader_mod
from clinosim.modules.longitudinal.loader import load_attribute_specs

_YAML_NO_INITIAL_CLAMP = """\
attribute_id: test_latent
pattern: ar1
depends_on: []
clinical_scope:
  requires_chronic_codes: []
  requires_age_band: [0, 120]
latent_name: foo
ar1:
  phi: 0.9
  sigma: 0.2
  mean_reversion_target: 10.0
clamp: [5.0, 15.0]
initial:
  mu: 2.303
  sigma: 0.1
  # NB: no initial.clamp here — must default to top-level clamp [5.0, 15.0]
"""


@pytest.fixture(autouse=True)
def _clear_loader_cache():
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


@pytest.mark.unit
def test_ar1_yaml_without_initial_clamp_defaults_to_top_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    (tmp_path / "test_latent.yaml").write_text(_YAML_NO_INITIAL_CLAMP, encoding="utf-8")
    specs = load_attribute_specs()
    assert "test_latent" in specs
    body = specs["test_latent"].body
    assert body.clamp == [5.0, 15.0]
    assert body.initial_clamp == [5.0, 15.0], (
        f"initial_clamp must default to top-level clamp when omitted; got {body.initial_clamp}"
    )


@pytest.mark.unit
def test_ar1_yaml_with_explicit_initial_clamp_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit initial.clamp still wins over top-level clamp (backward compat)."""
    yaml_with_explicit = """\
attribute_id: test_latent_explicit
pattern: ar1
depends_on: []
clinical_scope: {requires_chronic_codes: [], requires_age_band: [0, 120]}
latent_name: foo
ar1: {phi: 0.9, sigma: 0.2, mean_reversion_target: 10.0}
clamp: [5.0, 15.0]
initial:
  mu: 2.303
  sigma: 0.1
  clamp: [4.0, 20.0]   # explicitly wider than step clamp
"""
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    (tmp_path / "test_latent_explicit.yaml").write_text(yaml_with_explicit, encoding="utf-8")
    specs = load_attribute_specs()
    body = specs["test_latent_explicit"].body
    assert body.clamp == [5.0, 15.0]
    assert body.initial_clamp == [4.0, 20.0]


# Also pin that the shipped bmi_drift.yaml + hba1c_trajectory.yaml still load
# cleanly after both have their redundant initial.clamp lines removed.
@pytest.mark.unit
def test_shipped_bmi_drift_yaml_no_longer_duplicates_clamp() -> None:
    yaml_path = (
        Path(__file__).resolve().parents[3]
        / "clinosim"
        / "locale"
        / "shared"
        / "longitudinal"
        / "anthropometry"
        / "bmi_drift.yaml"
    )
    raw = yaml.safe_load(yaml_path.read_text())
    assert raw["clamp"] == [13.0, 70.0]
    assert "clamp" not in (raw.get("initial") or {}), (
        f"bmi_drift.yaml::initial.clamp is redundant with top-level clamp; "
        f"expected removed, got {raw['initial'].get('clamp')}"
    )
