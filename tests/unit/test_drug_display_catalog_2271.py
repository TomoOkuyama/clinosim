"""Drug names come from the drug catalog everywhere (Issue #2271)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.codes.drugs import drug_display
from clinosim.modules.drug_safety.classifier import _load_mappings, japanese_display
from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def test_no_yaml_carries_drug_ja() -> None:
    offenders = [
        str(p.relative_to(_ROOT))
        for p in (_ROOT / "clinosim").rglob("*.yaml")
        if any(line.lstrip().startswith("drug_ja:") or ", drug_ja:" in line for line in p.read_text().splitlines())
    ]
    assert not offenders, offenders


def test_every_drug_safety_drug_has_a_catalog_japanese_name() -> None:
    missing = [name for name in _load_mappings() if not drug_display(name, "ja")]
    assert not missing, missing


@pytest.mark.parametrize("name", ["Diazepam", "Unfractionated Heparin", "Dabigatran", "Nifedipine"])
def test_fhir_and_drug_safety_show_the_same_japanese_name(name: str) -> None:
    assert _localize_drug_name(name, "JP") == japanese_display(name) == drug_display(name, "ja")


def test_drug_display_reads_a_leading_name_with_a_dose() -> None:
    assert drug_display("Rivaroxaban 20mg", "ja") == "リバーロキサバン"
    assert drug_display("Rivaroxaban 20mg", "en") == "Rivaroxaban"
    assert drug_display("Not a drug", "ja") is None


def test_narrative_home_med_uses_the_stored_japanese_name() -> None:
    from clinosim.modules.document.narrative._template_helpers import _render_home_med_name

    assert _render_home_med_name({"drug_name": "Amlodipine", "drug_name_ja": "アムロジピン"}, "ja") == "アムロジピン"
