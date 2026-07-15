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

_YAML_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "clinosim", "modules", "disease", "reference_data")
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
        f"graded-stage conditions without a STAGE_SEVERITY consumer (degenerate stage risk, I10-class): {missing}"
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
    missing = {os.path.basename(f)[:-5] for f in _FILES if not _raw(f).get("course_archetypes")}
    assert missing == _COURSE_ARCHETYPE_BACKLOG, (
        f"course_archetypes backlog drifted. Missing now: {sorted(missing)}. "
        f"Expected: {sorted(_COURSE_ARCHETYPE_BACKLOG)}. If you authored one, remove it "
        f"from _COURSE_ARCHETYPE_BACKLOG; if a new disease lacks archetypes, add them."
    )


# ============================================================
# P2-13 PR1: JP-CLINS eCS profile URL emission gate
# ============================================================


@pytest.fixture(scope="session")
def jp_bacterial_pneumonia_resources(tmp_path_factory):
    """AD-66 canonical patient profile → in-process CIF → FHIR → resource list.

    Runs run_forced + write_cif + convert_cif_to_fhir directly (no subprocess)
    against the JP bacterial pneumonia canonical fixture, using a small
    catchment override so we get enough patients for all dense JP-CLINS
    resource types to appear at least once. Session-scoped for reuse.
    """
    import json
    from pathlib import Path

    from clinosim.modules.output.cif_writer import write_cif
    from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir
    from clinosim.simulator.engine import run_forced
    from clinosim.types.config import SimulatorConfig, load_patient_profile

    profile_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "patient_profiles" / "jp_inpatient_bacterial_pneumonia.yaml"
    )
    profile = load_patient_profile(str(profile_path))
    scenario = profile.to_forced_scenario()
    # Override count to 5 to increase the chance that all 4 dense JP-CLINS
    # types appear (Procedure especially can be sparse at count=1).
    scenario = scenario.__class__(**{**scenario.__dict__, "count": 5})
    config = SimulatorConfig(
        random_seed=profile.random_seed,
        country=profile.country,
        hospital_scale=profile.hospital_scale,
        catchment_population=5,
    )
    dataset = run_forced(scenario, config)

    outroot = tmp_path_factory.mktemp("jp-clins-invariant")
    cif_dir = str(outroot / "cif")
    fhir_dir = str(outroot / "fhir_r4")
    write_cif(dataset, cif_dir)
    convert_cif_to_fhir(cif_dir, fhir_dir, country=profile.country)

    resources: list[dict] = []
    for ndjson_path in sorted(Path(fhir_dir).glob("*.ndjson")):
        with open(ndjson_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                resources.append(json.loads(line))
    return resources


class TestJpClinsProfileEmissionInvariants:
    """P2-13 PR1: JP-CLINS eCS profile URL emission gate.

    For a country=JP cohort, every emitted resource of a JP-CLINS-registered
    resource type MUST carry the JP-CLINS eCS profile URL in meta.profile[].
    Filter: Observation only when category=laboratory (vitals stay JP Core).

    JP-CLINS v1.12.0 covers 5 resource types (Condition, AllergyIntolerance,
    Observation.LabResult, MedicationRequest, Procedure). DiagnosticReport is
    NOT in JP-CLINS scope; lab results are emitted only as Observation.LabResult.

    Uses AD-66 canonical patient profile fixture via in-process run_forced +
    convert_cif_to_fhir. No subprocess.
    """

    def test_jp_bacterial_pneumonia_cohort_has_clins_profiles(self, jp_bacterial_pneumonia_resources):
        from clinosim.modules.output.fhir_r4_adapter import (
            _JP_CLINS_PROFILES,
            _is_lab_observation,
        )

        # Dense JP-CLINS resource types for an inpatient bacterial pneumonia
        # cohort. AllergyIntolerance is sparse (pool may be empty; profile
        # check is vacuously true if empty).
        expected_dense = {"Condition", "Observation", "MedicationRequest", "Procedure"}
        seen_dense: set[str] = set()

        for r in jp_bacterial_pneumonia_resources:
            rt = r["resourceType"]
            if rt not in _JP_CLINS_PROFILES:
                continue
            if rt == "Observation" and not _is_lab_observation(r):
                continue
            profs = r.get("meta", {}).get("profile", [])
            expected = _JP_CLINS_PROFILES[rt][0]
            assert expected in profs, f"{rt}/{r.get('id')} missing {expected}, got {profs}"
            if rt in expected_dense:
                seen_dense.add(rt)

        missing = expected_dense - seen_dense
        assert not missing, f"expected dense JP-CLINS resource types missing from cohort: {missing}"

    def test_diagnostic_report_gets_no_clins_profile(self, jp_bacterial_pneumonia_resources):
        """JP-CLINS v1.12.0 does not publish a DiagnosticReport profile."""
        clins_root = "http://jpfhir.jp/fhir/eCS/StructureDefinition/"
        for r in jp_bacterial_pneumonia_resources:
            if r["resourceType"] != "DiagnosticReport":
                continue
            profs = r.get("meta", {}).get("profile", [])
            assert not any(p.startswith(clins_root) for p in profs), (
                f"DiagnosticReport {r.get('id')} leaked JP-CLINS profile: {profs}"
            )
