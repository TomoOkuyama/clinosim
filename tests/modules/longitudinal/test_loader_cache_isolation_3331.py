"""Issue #3331: a test that points ``_LONGITUDINAL_DIR`` at substitute data
must not leave those specs in the ``load_attribute_specs`` cache for the
tests that run after it in the same worker.

The two tests run in file order: the first fills the cache from a temporary
directory without clearing it on teardown (as the ``test_engine.py``
fixtures did); the second reads the shipped specs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.modules.longitudinal import loader as loader_mod
from clinosim.modules.longitudinal.loader import load_attribute_specs

_SUBSTITUTE_YAML = """
attribute_id: substitute_only
pattern: ar1
depends_on: []
clinical_scope: {requires_chronic_codes: [], requires_age_band: [0, 120]}
latent_name: substitute_only
ar1: {phi: 0.9, sigma: 0.1, mean_reversion_target: 1.0}
clamp: [0.0, 2.0]
initial: {mu: 1.0, sigma: 0.1}
"""


@pytest.mark.unit
def test_a_substitute_dir_fills_the_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    load_attribute_specs.cache_clear()
    (tmp_path / "substitute_only.yaml").write_text(_SUBSTITUTE_YAML, encoding="utf-8")
    assert set(load_attribute_specs()) == {"substitute_only"}


@pytest.mark.unit
def test_b_later_test_reads_the_shipped_specs() -> None:
    specs = load_attribute_specs()
    assert "substitute_only" not in specs
    assert "hba1c" in specs
