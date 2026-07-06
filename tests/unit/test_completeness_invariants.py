"""FP-COMPLETENESS-GATE (capstone): durable regression guards for the FHIR-completeness
C1/C2/C3 properties established this session.

Fails loudly if any completeness win regresses — forbid turned off, an orphan key or
top-level diagnostic_difficulty reintroduced, severity_beta revived, a graded-stage
condition added without a physiological consumer (the I10-class no-op), or an FP-ARCH
closure reverted. Also keeps the C3 backlog honest via a curated allowlist.

Context: docs/design-notes/2026-07-06-fhir-completeness-and-data-model-unification.md
"""

import glob
import os
import re

import pytest
import yaml

from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.patient.activator import STAGE_SEVERITY

pytestmark = pytest.mark.unit

_YAML_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "clinosim", "modules", "disease", "reference_data"
)
_FILES = sorted(glob.glob(os.path.join(_YAML_DIR, "*.yaml")))


def _raw(f):
    with open(f) as fh:
        return yaml.safe_load(fh)


# ------------------------------------------------------------------ C1
def test_c1_disease_protocol_extra_forbid():
    assert DiseaseProtocol.model_config.get("extra") == "forbid", (
        "DiseaseProtocol must keep extra='forbid' (author-time silent-drop defense, AD-69)"
    )


def test_c1_no_top_level_diagnostic_difficulty():
    offenders = [os.path.basename(f) for f in _FILES if "diagnostic_difficulty" in _raw(f)]
    assert not offenders, f"diagnostic_difficulty must stay nested under diagnostic:; got {offenders}"


def test_c1_no_severity_beta_readers():
    hits = []
    for f in glob.glob("clinosim/**/*.py", recursive=True):
        with open(f) as fh:
            if re.search(r"severity_beta|severity_minimum", fh.read()):
                hits.append(f)
    assert not hits, f"severity_beta/severity_minimum retired; unexpected readers: {hits}"


def test_c1_every_disease_severity_distribution_wellformed():
    for f in _FILES:
        dist = (_raw(f).get("severity") or {}).get("distribution", {})
        cats = {"mild", "moderate", "severe"}
        assert cats <= set(dist), f"{os.path.basename(f)}: severity.distribution missing {cats - set(dist)}"
        assert sum(float(dist[c]) for c in cats) > 0, f"{os.path.basename(f)}: distribution sums to 0"


# ------------------------------------------------------------------ C2
# Graded-stage codes _generate_stage can emit — each MUST have a physiological consumer
# (a STAGE_SEVERITY entry) so no graded stage is a degenerate no-op (the I10 class).
_GRADED_STAGE_CODES = {"N18", "I50", "J44", "J45", "I10", "I25"}


def test_c2_every_graded_stage_condition_has_severity_consumer():
    missing = _GRADED_STAGE_CODES - set(STAGE_SEVERITY)
    assert not missing, (
        f"graded-stage conditions without a STAGE_SEVERITY consumer (degenerate stage "
        f"risk, I10-class): {missing}"
    )


# ------------------------------------------------------------------ C3
def test_c3_fp_arch1_closures_stay_closed():
    for name in ("heart_failure_exacerbation", "subdural_hematoma"):
        d = _raw(os.path.join(_YAML_DIR, f"{name}.yaml"))
        assert d.get("course_archetypes"), f"{name} lost its course_archetypes"
        assert d.get("complications"), f"{name} lost its complications"


# Curated backlog: diseases still lacking course_archetypes. EMPTY as of FP-ARCH-2/3
# (session 38) — all 32 diseases now author course_archetypes. A new disease shipping
# without them fails this test; if authoring one is intentionally deferred, add it here.
_COURSE_ARCHETYPE_BACKLOG: set[str] = set()


def test_c3_course_archetype_backlog_is_exactly_the_known_set():
    missing = {
        os.path.basename(f)[:-5] for f in _FILES if not _raw(f).get("course_archetypes")
    }
    assert missing == _COURSE_ARCHETYPE_BACKLOG, (
        f"course_archetypes backlog drifted. Missing now: {sorted(missing)}. "
        f"Expected: {sorted(_COURSE_ARCHETYPE_BACKLOG)}. If you authored one, remove it "
        f"from _COURSE_ARCHETYPE_BACKLOG; if a new disease lacks archetypes, add them."
    )
