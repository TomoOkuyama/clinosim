"""Registry tests for lab_panels.yaml (PR1 CBC/BMP expansion).

The panel registry resolves a protocol order name (e.g. "CBC") to its canonical
component analytes that will be expanded into child orders by
``clinosim/simulator/inpatient.py:572-585``. Before PR1 the registry held only
ABG; this file pins the new CBC and BMP entries plus an ABG regression test.

The module-level ``@lru_cache(maxsize=1)`` on ``_lab_panels()`` can be pre-warmed
by other tests in the suite collection order — the autouse fixture below clears
it before every test in this file so the assertions always read the YAML on disk.
"""
import pytest

from clinosim.modules.observation import engine as _obs_engine
from clinosim.modules.observation.engine import lab_panel_components


@pytest.fixture(autouse=True)
def _clear_panel_cache():
    _obs_engine._lab_panels.cache_clear()
    yield
    _obs_engine._lab_panels.cache_clear()


@pytest.mark.unit
def test_abg_components_unchanged():
    # Sanity: the pre-existing ABG entry must not regress.
    assert lab_panel_components("ABG") == ["pH", "pCO2", "pO2", "HCO3"]


@pytest.mark.unit
def test_cbc_expands_to_four_canonical_components():
    # WBC, Hb, Hct, Plt — RBC intentionally omitted (physiology engine does
    # not derive RBC count; adding it would create silently-dropped children).
    assert lab_panel_components("CBC") == ["WBC", "Hb", "Hct", "Plt"]


@pytest.mark.unit
def test_bmp_expands_to_eight_canonical_components():
    # Cl and Ca are listed because they are canonical BMP components; the
    # scalar resulted path at inpatient.py drops them silently when they are
    # absent from derive_lab_values(), so this entry being correct is what
    # lets a follow-up PR add Cl/Ca to the engine without YAML changes.
    assert lab_panel_components("BMP") == [
        "Na", "K", "Cl", "HCO3", "BUN", "Creatinine", "Glucose", "Ca",
    ]
