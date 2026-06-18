"""Diagnosis code mapping — internal chronic/history base code → billable ICD-10-CM (US).

Regression for the 2026-06 ICD review finding that locale/<c>/code_mapping_diagnosis.yaml
was dead config (load_code_mapping never called for "diagnosis"), so US emitted non-billable
3-char category codes (I50, I21, ...) and WHO-only codes (F00). The map is now wired into the
FHIR adapter; US translates to billable CM leaves, JP stays identity (output unchanged).
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup
from clinosim.locale.loader import load_code_mapping
from clinosim.modules.output.fhir_r4_adapter import _map_diagnosis_code

pytestmark = pytest.mark.unit


# (internal code, expected US billable target)
US_MAPPINGS = [
    ("E78", "E78.5"), ("J44", "J44.9"), ("N18", "N18.9"), ("I50", "I50.9"),
    ("I48", "I48.91"), ("I25", "I25.10"), ("M81", "M81.0"), ("F00", "F03.90"),
    ("G20", "G20.C"), ("E03", "E03.9"), ("K21", "K21.9"), ("J45", "J45.909"),
    ("N40", "N40.0"), ("M17", "M17.9"), ("E10", "E10.9"),
    # past acute events carried as chronic background → history/old codes
    ("I21", "I25.2"), ("I26", "Z86.711"), ("I61", "Z86.73"), ("I63", "Z86.73"),
    ("I80", "Z86.718"), ("I82", "Z86.718"), ("M48", "Z87.311"), ("M80", "Z87.310"),
]


@pytest.mark.parametrize("internal,target", US_MAPPINGS)
def test_us_maps_internal_to_billable_target(internal: str, target: str) -> None:
    assert _map_diagnosis_code(internal, "US") == target


@pytest.mark.parametrize("internal,target", US_MAPPINGS)
def test_us_targets_resolve_a_real_display(internal: str, target: str) -> None:
    # Every billable target must have an English display in icd-10-cm.yaml,
    # otherwise the Condition would emit "(display unavailable)".
    disp = lookup("icd-10-cm", target, "en")
    assert disp and disp != target


def test_every_us_target_resolves_a_real_display() -> None:
    # Guards the whole US map (chronic + history + primary specificity entries):
    # no mapped code may emit "(display unavailable)".
    us_map = load_code_mapping("diagnosis", "US")
    missing = [t for t in set(us_map.values())
               if not (lookup("icd-10-cm", t, "en") and lookup("icd-10-cm", t, "en") != t)]
    assert not missing, f"US targets without a display in icd-10-cm.yaml: {missing}"


def test_specific_primary_codes_pass_through_unchanged() -> None:
    # Disease primary diagnoses are already specific/billable; never remapped.
    for code in ["I21.9", "A41.9", "I63.9", "I50.9", "J44.1", "K35.80"]:
        assert _map_diagnosis_code(code, "US") == code


def test_jp_mapping_is_identity() -> None:
    # JP uses WHO ICD-10 category codes as-is; wiring must not change JP output.
    jp_map = load_code_mapping("diagnosis", "JP")
    assert jp_map, "JP diagnosis map should be populated (identity)"
    for k, v in jp_map.items():
        assert k == v, f"JP map must be identity, got {k} -> {v}"
    # And unmapped codes pass through too.
    assert _map_diagnosis_code("I21", "JP") == "I21"
    assert _map_diagnosis_code("E78", "JP") == "E78"


def test_empty_code_passes_through() -> None:
    assert _map_diagnosis_code("", "US") == ""
