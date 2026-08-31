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
from clinosim.modules.output.fhir_r4.lib.common import (
    iter_diagnosis_mapping_targets,
    map_diagnosis_code,
)

pytestmark = pytest.mark.unit


# (internal code, expected US billable target)
US_MAPPINGS = [
    ("E78", "E78.5"),
    ("J44", "J44.9"),
    ("N18", "N18.9"),
    ("I50", "I50.9"),
    ("I48", "I48.91"),
    ("I25", "I25.10"),
    ("M81", "M81.0"),
    ("F00", "F03.90"),
    ("G20", "G20.C"),
    ("E03", "E03.9"),
    ("K21", "K21.9"),
    ("J45", "J45.909"),
    ("N40", "N40.0"),
    ("M17", "M17.9"),
    ("E10", "E10.9"),
    # past acute events carried as chronic background → history/old codes
    ("I21", "I25.2"),
    ("I26", "Z86.711"),
    ("I61", "Z86.73"),
    ("I63", "Z86.73"),
    ("I80", "Z86.718"),
    ("I82", "Z86.718"),
    ("M48", "Z87.311"),
    ("M80", "Z87.310"),
]


@pytest.mark.parametrize("internal,target", US_MAPPINGS)
def test_us_maps_internal_to_billable_target(internal: str, target: str) -> None:
    assert map_diagnosis_code(internal, "US") == target


@pytest.mark.parametrize("internal,target", US_MAPPINGS)
def test_us_targets_resolve_a_real_display(internal: str, target: str) -> None:
    # Every billable target must have an English display in icd-10-cm.yaml,
    # otherwise the Condition would emit "(display unavailable)".
    disp = lookup("icd-10-cm", target, "en")
    assert disp and disp != target


def test_every_us_target_resolves_a_real_display() -> None:
    # Guards the whole US map (chronic + history + primary specificity entries):
    # no mapped code may emit "(display unavailable)".  Since Issue #957 the
    # US map may hold sex-conditional dict values (currently only C50); we
    # flatten via iter_diagnosis_mapping_targets so both by_sex leaves and
    # the plain-string targets are validated.
    targets = set(iter_diagnosis_mapping_targets("US"))
    missing = [t for t in targets if not (lookup("icd-10-cm", t, "en") and lookup("icd-10-cm", t, "en") != t)]
    assert not missing, f"US targets without a display in icd-10-cm.yaml: {missing}"


def test_specific_primary_codes_pass_through_unchanged() -> None:
    # Disease primary diagnoses are already specific/billable; never remapped.
    for code in ["I21.9", "A41.9", "I63.9", "I50.9", "J44.1", "K35.80"]:
        assert map_diagnosis_code(code, "US") == code


def test_jp_mapping_folds_to_who_granularity() -> None:
    # JP maps internal codes to WHO ICD-10 (3-4 char). WHO category codes stay identity;
    # CM-granular internal codes (e.g. A41.01, S06.0X0A) fold to their WHO parent.
    import re

    jp_map = load_code_mapping("diagnosis", "JP")
    assert jp_map, "JP diagnosis map should be populated"
    who_format = re.compile(r"^[A-Z][0-9]{2}(\.[0-9])?$")
    for k, v in jp_map.items():
        assert who_format.match(v), f"JP map target must be WHO ICD-10 granularity, got {k} -> {v}"
    # WHO category codes pass through identity; CM granularity folds to the WHO parent.
    assert map_diagnosis_code("I21", "JP") == "I21"
    assert map_diagnosis_code("E78", "JP") == "E78"
    assert map_diagnosis_code("A41.01", "JP") == "A41.0"
    assert map_diagnosis_code("S06.0X0A", "JP") == "S06.0"


def test_empty_code_passes_through() -> None:
    assert map_diagnosis_code("", "US") == ""


def test_us_c50_maps_by_sex() -> None:
    """Issue #957 male-C50: US ICD-10-CM splits C50 into female-side
    (C50.9x1x — .911/.912/.919) vs male-side (C50.9x2x — .921/.922/.929)
    subcategories. ``map_diagnosis_code`` must route the internal ``C50``
    to the sex-appropriate billable leaf so male breast-cancer patients
    are not coded with a female-anatomy code."""
    assert map_diagnosis_code("C50", "US", sex="F") == "C50.919"
    assert map_diagnosis_code("C50", "US", sex="M") == "C50.929"
    # Backward compat: missing / unknown sex falls back to the female
    # unspecified leaf (the pre-Issue-957 behaviour, and the ~99%-of-cases
    # default). Every per-person caller SHOULD pass sex explicitly.
    assert map_diagnosis_code("C50", "US") == "C50.919"
    assert map_diagnosis_code("C50", "US", sex="") == "C50.919"


def test_jp_c50_identity_regardless_of_sex() -> None:
    """JP ICD-10 does not carry male/female subcategories at the C50
    code level — the code stays ``C50`` for both sexes. Passing sex must
    not alter the JP mapping."""
    assert map_diagnosis_code("C50", "JP", sex="F") == "C50"
    assert map_diagnosis_code("C50", "JP", sex="M") == "C50"
    assert map_diagnosis_code("C50", "JP") == "C50"


def test_c50_929_target_resolves_a_real_display() -> None:
    """The male-side target ``C50.929`` must have a real ICD-10-CM
    display, otherwise the Condition would emit '(display unavailable)'."""
    disp = lookup("icd-10-cm", "C50.929", "en")
    assert disp and disp != "C50.929"
