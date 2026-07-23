"""Cross-system code-data integrity (AD-57 data-quality review).

Guards the codes/data/*.yaml against the two classes of defect found during the
CIF/FHIR data-quality review: duplicate YAML keys (silently last-wins, with
conflicting display text) and verbose LOINC long-names leaking into `display`.
"""

import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

import clinosim

_DATA = Path(clinosim.__file__).parent / "codes" / "data"
_LOCALE = Path(clinosim.__file__).parent / "locale"


def _raw_code_keys(path: Path) -> list[str]:
    """Code keys as written in the file (pre-dedup), to catch duplicate keys."""
    keys, in_codes = [], False
    for ln in path.read_text().splitlines():
        if re.match(r"^codes:\s*$", ln):
            in_codes = True
            continue
        if in_codes and re.match(r"^  [^ #].*:\s*$", ln):
            keys.append(ln.strip().rstrip(":"))
    return keys


@pytest.mark.unit
@pytest.mark.parametrize("path", sorted(_DATA.glob("*.yaml")), ids=lambda p: p.name)
class TestCodeSystemFiles:
    def test_no_duplicate_keys(self, path):
        dups = {k: c for k, c in Counter(_raw_code_keys(path)).items() if c > 1}
        assert not dups, f"{path.name} has duplicate code keys (last-wins bug): {dups}"

    def test_every_code_has_english(self, path):
        codes = yaml.safe_load(path.read_text()).get("codes", {})
        no_en = [c for c, e in codes.items() if not (isinstance(e, dict) and e.get("en"))]
        assert not no_en, f"{path.name} codes missing `en`: {no_en}"


@pytest.mark.unit
class TestDrugMapping:
    """RxNorm drug-mapping integrity (CODES-6/CODES-7). Mirrors the LOINC guard:
    every emitted RxCUI must resolve in rxnorm.yaml, and no two distinct drugs may
    share a CUI (the Amoxicillin/Clavulanate + Azithromycin -> 18631 collision)."""

    def test_us_mapped_rxcuis_present(self):
        rxnorm = yaml.safe_load((_DATA / "rxnorm.yaml").read_text())["codes"]
        us = yaml.safe_load((_LOCALE / "us/code_mapping_drug.yaml").read_text())
        missing = {n: c for n, c in us.items() if c not in rxnorm}
        assert not missing, f"US-mapped RxCUIs absent from rxnorm.yaml: {missing}"

    def test_no_two_drugs_share_a_rxcui(self):
        us = yaml.safe_load((_LOCALE / "us/code_mapping_drug.yaml").read_text())
        by_code: dict[str, list[str]] = {}
        for name, code in us.items():
            by_code.setdefault(code, []).append(name)
        collisions = {c: names for c, names in by_code.items() if len(names) > 1}
        assert not collisions, f"distinct drugs mapped to the same RxCUI: {collisions}"


@pytest.mark.unit
class TestLoincDisplay:
    def test_us_mapped_codes_present_and_clean(self):
        """Guard: every LOINC code emitted for a US-mapped analyte MUST be
        registered in loinc.yaml. Historically this test also enforced a
        "clean clinical short name" invariant (no LONG_COMMON_NAME
        `[Mass/volume] in Serum or Plasma` fragments), but under strict HAPI
        validation the LONG_COMMON_NAME is the CodeSystem canonical for
        LOINC and clinosim must emit it to pass tx=8181 validation
        (Issue #380 / session 66). The clean-name invariant conflicted
        with spec conformance, so it was removed here; `text` field on
        Observation.code carries the human-readable label instead.
        """
        loinc = yaml.safe_load((_DATA / "loinc.yaml").read_text())["codes"]
        us = yaml.safe_load((_LOCALE / "us/code_mapping_lab.yaml").read_text())
        missing = {n: c for n, c in us.items() if c not in loinc}
        assert not missing, f"US-mapped LOINC codes absent from loinc.yaml: {missing}"
