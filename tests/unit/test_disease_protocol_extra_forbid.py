"""FP-YAML-3: DiseaseProtocol rejects unknown top-level keys (extra="forbid").

Author-time defense against the C1 silent-drop class — an unrecognized YAML key
(typo or unwired field) now raises at load instead of being silently dropped.
Precondition: all orphan top-level keys resolved (diagnostic_difficulty moved to
nested — chain 1; archetype_modifiers wired — FP-YAML-2b; rehabilitation /
differential_diagnosis / precipitants / prerequisite deleted — this chain).
"""

import glob
import os

import pytest

from clinosim.modules.disease.protocol import DiseaseProtocol, load_disease_protocol

pytestmark = pytest.mark.unit

_YAML_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "clinosim", "modules", "disease", "reference_data")
_IDS = [os.path.basename(f)[:-5] for f in glob.glob(os.path.join(_YAML_DIR, "*.yaml"))]
_ORPHANS = ("rehabilitation", "differential_diagnosis", "precipitants", "prerequisite")


def test_unknown_top_level_key_raises():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DiseaseProtocol(
            disease_id="x",
            icd_codes={},
            incidence={},
            severity={"distribution": {}},
            totally_unknown_key=123,
        )


@pytest.mark.parametrize("disease_id", _IDS)
def test_no_orphan_top_level_keys(disease_id):
    import yaml

    with open(os.path.join(_YAML_DIR, f"{disease_id}.yaml")) as f:
        raw = yaml.safe_load(f)
    present = [k for k in _ORPHANS if k in raw]
    assert not present, f"{disease_id}: orphan top-level keys still present: {present}"


@pytest.mark.parametrize("disease_id", _IDS)
def test_all_disease_yamls_load(disease_id):
    load_disease_protocol(disease_id)  # must not raise under extra="forbid"
