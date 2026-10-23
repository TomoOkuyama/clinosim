"""Issue #1755: C50 breast cancer endocrine therapy mutex + age gate.

Pre-fix the C50 regimen in ``chronic_medications.yaml`` offered
Tamoxifen (SERM) and Anastrozole (aromatase inhibitor) as independent
Bernoulli draws (``probability: 0.4`` + ``0.3``). The two drugs are
clinically mutually exclusive endocrine options for ER+ breast cancer
per NCCN / ASCO guidelines (pick one, not both). Pre-fix 17 / 108
C50 patients (16 %) ended up on dual therapy.

Pre-fix anastrozole additionally landed on 8 premenopausal patients
(youngest 36 y). Aromatase inhibitors are contraindicated in
premenopausal women without ovarian suppression per NCCN.

Fix:
1. ``drug_class: breast_endocrine_therapy`` on both drugs +
   ``exclusive_classes: ["breast_endocrine_therapy"]`` at the block
   level → ``select_with_exclusive_classes`` picks at most one.
2. ``age_min: 50`` on anastrozole → premenopausal filter via the
   existing ``_shared.py`` age-gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_YAML = Path(__file__).resolve().parents[1].parent / "clinosim" / "locale" / "shared" / "chronic_medications.yaml"


def _load_c50_block() -> dict:
    with _YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("C50") or {}


# ----------------------------------------------------------------------------
# Mutex via drug_class + exclusive_classes
# ----------------------------------------------------------------------------


def test_c50_block_declares_breast_endocrine_mutex() -> None:
    """exclusive_classes at the C50 block level forces at-most-one
    selection among drugs declaring the matching drug_class."""
    block = _load_c50_block()
    exclusive = set(block.get("exclusive_classes") or [])
    assert "breast_endocrine_therapy" in exclusive


def test_tamoxifen_and_anastrozole_share_breast_endocrine_class() -> None:
    """Both C50 endocrine agents must carry the shared drug_class so
    the mutex picks exactly one at activation time."""
    block = _load_c50_block()
    tamoxifen = next((m for m in block.get("medications", []) if m.get("drug_id") == "tamoxifen"), None)
    anastrozole = next((m for m in block.get("medications", []) if m.get("drug_id") == "anastrozole"), None)
    assert tamoxifen is not None, "tamoxifen missing from C50 regimen"
    assert anastrozole is not None, "anastrozole missing from C50 regimen"
    assert tamoxifen.get("drug_class") == "breast_endocrine_therapy"
    assert anastrozole.get("drug_class") == "breast_endocrine_therapy"


# ----------------------------------------------------------------------------
# Age gate on anastrozole
# ----------------------------------------------------------------------------


def test_anastrozole_age_min_50_post_menopausal() -> None:
    """Anastrozole is contraindicated in premenopausal women without
    ovarian suppression. The 50 y floor is a conservative proxy for
    post-menopausal state (US median menopause age ~51)."""
    block = _load_c50_block()
    anastrozole = next((m for m in block.get("medications", []) if m.get("drug_id") == "anastrozole"), None)
    assert anastrozole is not None
    assert anastrozole.get("age_min") == 50


def test_tamoxifen_has_no_age_gate() -> None:
    """Tamoxifen remains available at any adult age — it is the
    preferred endocrine agent for premenopausal ER+ breast cancer."""
    block = _load_c50_block()
    tamoxifen = next((m for m in block.get("medications", []) if m.get("drug_id") == "tamoxifen"), None)
    assert tamoxifen is not None
    assert "age_min" not in tamoxifen
    assert "age_max" not in tamoxifen


# ----------------------------------------------------------------------------
# End-to-end: _shared.py filter respects the age gate + mutex
# ----------------------------------------------------------------------------


def test_premenopausal_patient_filters_out_anastrozole() -> None:
    """A 36 y female C50 patient (one of the pre-fix offending ages)
    must have anastrozole dropped by the ``select_with_exclusive_classes``
    age filter — only tamoxifen remains eligible."""
    import numpy as np

    from clinosim.modules._shared import select_with_exclusive_classes

    block = _load_c50_block()
    rng = np.random.default_rng(42)
    picks: list[dict] = list(
        select_with_exclusive_classes(
            block["medications"],
            exclusive_classes=set(block.get("exclusive_classes") or []),
            rng=rng,
            independent_mode="always",
            context="test",
            patient_age=36,
        )
    )
    drug_ids = {p.get("drug_id") for p in picks}
    assert "anastrozole" not in drug_ids
    # Tamoxifen may or may not be picked by the Bernoulli — the pin is
    # strictly that anastrozole is dropped by the age gate.


def test_postmenopausal_patient_picks_at_most_one_endocrine() -> None:
    """A 65 y post-menopausal C50 patient has BOTH drugs age-eligible,
    but the exclusive-class mutex ensures at most one lands on the
    regimen (never dual)."""
    import numpy as np

    from clinosim.modules._shared import select_with_exclusive_classes

    block = _load_c50_block()
    # Sweep 50 RNG seeds to confirm the mutex invariant holds in all draws.
    for seed in range(50):
        rng = np.random.default_rng(seed)
        picks = list(
            select_with_exclusive_classes(
                block["medications"],
                exclusive_classes=set(block.get("exclusive_classes") or []),
                rng=rng,
                independent_mode="always",
                context="test",
                patient_age=65,
            )
        )
        endocrine_picks = [p for p in picks if p.get("drug_class") == "breast_endocrine_therapy"]
        assert len(endocrine_picks) <= 1, f"seed={seed}: {len(endocrine_picks)} endocrine drugs picked (mutex violated)"
