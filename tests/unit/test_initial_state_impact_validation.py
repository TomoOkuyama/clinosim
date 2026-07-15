"""FP-DELTA-VALIDATE: author-time validation of ``initial_state_impact``.

``apply_state_delta`` uses ``getattr(state, var, None)`` which silently
no-ops when a disease YAML declares a delta on a non-canonical state
variable. This sibling of the session 39 ``anion_gap_status`` fix
(silent-drop of GI acid-base axis) is closed by validating every
``initial_state_impact`` state-var key against the canonical set at YAML
load time.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestCanonicalStateVars:
    def test_canonical_set_matches_variable_range(self) -> None:
        """Canonical state vars must be discoverable as a single source."""
        from clinosim.modules.physiology.engine import canonical_state_vars

        got = canonical_state_vars()
        # 13 vars currently modeled — matches _variable_range keys
        assert "inflammation_level" in got
        assert "anion_gap_status" in got
        assert "sodium_status" in got
        assert "consciousness" not in got  # session 40 silent-drop
        assert "electrolyte_status" not in got  # session 40 silent-drop
        assert "neurological_status" not in got  # session 40 silent-drop


class TestValidateInitialStateImpact:
    def test_valid_all_canonical_vars_passes(self) -> None:
        from clinosim.modules.physiology.engine import _validate_initial_state_impact

        _validate_initial_state_impact(
            "test_disease",
            {"severe": {"inflammation_level": 0.5, "renal_function": -0.2}},
        )

    def test_empty_dict_passes(self) -> None:
        from clinosim.modules.physiology.engine import _validate_initial_state_impact

        _validate_initial_state_impact("test_disease", {})

    def test_empty_severity_deltas_passes(self) -> None:
        from clinosim.modules.physiology.engine import _validate_initial_state_impact

        _validate_initial_state_impact("test_disease", {"severe": {}})

    def test_unknown_state_var_raises(self) -> None:
        from clinosim.modules.physiology.engine import _validate_initial_state_impact

        with pytest.raises(ValueError, match=r"consciousness"):
            _validate_initial_state_impact(
                "diabetic_ketoacidosis",
                {"severe": {"consciousness": -0.3}},
            )

    def test_error_message_includes_disease_id(self) -> None:
        from clinosim.modules.physiology.engine import _validate_initial_state_impact

        with pytest.raises(ValueError, match=r"diabetic_ketoacidosis"):
            _validate_initial_state_impact(
                "diabetic_ketoacidosis",
                {"severe": {"electrolyte_status": -0.4}},
            )

    def test_error_message_lists_offending_vars(self) -> None:
        from clinosim.modules.physiology.engine import _validate_initial_state_impact

        with pytest.raises(ValueError) as exc:
            _validate_initial_state_impact(
                "test_disease",
                {"severe": {"electrolyte_status": -0.4, "consciousness": -0.3}},
            )
        msg = str(exc.value)
        assert "electrolyte_status" in msg
        assert "consciousness" in msg

    def test_error_message_includes_severity_key(self) -> None:
        from clinosim.modules.physiology.engine import _validate_initial_state_impact

        with pytest.raises(ValueError, match=r"moderate"):
            _validate_initial_state_impact(
                "hemorrhagic_stroke",
                {"moderate": {"neurological_status": -0.3}},
            )


class TestProductionYamlsAllValid:
    """After triaging the 5 known silent-drop entries, all production disease
    YAMLs must load cleanly. This guards against regression: a future YAML
    author adding a typo'd state_var key will be caught at load time.
    """

    def test_all_disease_yamls_load_without_state_var_error(self) -> None:
        from clinosim.modules.disease.protocol import load_all_disease_protocols

        load_all_disease_protocols.cache_clear()
        # If any YAML has an unknown state_var key, this raises.
        protocols = load_all_disease_protocols()
        assert len(protocols) >= 30


class TestValidateComplicationsStateImpact:
    def test_valid_state_impact_passes(self) -> None:
        from clinosim.modules.physiology.engine import _validate_complications_state_impact

        _validate_complications_state_impact(
            "test_disease",
            [{"name": "aki", "state_impact": {"renal_function": -0.2}}],
        )

    def test_empty_list_passes(self) -> None:
        from clinosim.modules.physiology.engine import _validate_complications_state_impact

        _validate_complications_state_impact("test_disease", [])

    def test_unknown_state_var_raises(self) -> None:
        from clinosim.modules.physiology.engine import _validate_complications_state_impact

        with pytest.raises(ValueError, match=r"electrolyte_status"):
            _validate_complications_state_impact(
                "diabetic_ketoacidosis",
                [{"name": "hypokalemia", "state_impact": {"electrolyte_status": -0.15}}],
            )

    def test_error_lists_all_offending_complications(self) -> None:
        from clinosim.modules.physiology.engine import _validate_complications_state_impact

        with pytest.raises(ValueError) as exc:
            _validate_complications_state_impact(
                "hemorrhagic_stroke",
                [
                    {"name": "hematoma_expansion", "state_impact": {"neurological_status": -0.15}},
                    {"name": "cerebral_edema", "state_impact": {"neurological_status": -0.10}},
                ],
            )
        assert "hematoma_expansion" in str(exc.value)
        assert "cerebral_edema" in str(exc.value)


class TestValidateCourseArchetypes:
    def test_valid_trajectory_passes(self) -> None:
        from clinosim.modules.clinical_course.engine import _validate_course_archetypes

        _validate_course_archetypes(
            "test_disease",
            {
                "smooth_recovery": {
                    "trajectory": {"inflammation_level": {0: 0.1}, "renal_function": {0: -0.1}},
                },
            },
        )

    def test_empty_dict_passes(self) -> None:
        from clinosim.modules.clinical_course.engine import _validate_course_archetypes

        _validate_course_archetypes("test_disease", {})

    def test_unknown_trajectory_var_raises(self) -> None:
        from clinosim.modules.clinical_course.engine import _validate_course_archetypes

        with pytest.raises(ValueError, match=r"neurological_status"):
            _validate_course_archetypes(
                "hemorrhagic_stroke",
                {"smooth_recovery": {"trajectory": {"neurological_status": {0: -0.05}}}},
            )

    def test_respiratory_fraction_rejected_as_trajectory(self) -> None:
        """respiratory_fraction is a routing axis, not day-evolving."""
        from clinosim.modules.clinical_course.engine import _validate_course_archetypes

        with pytest.raises(ValueError, match=r"respiratory_fraction"):
            _validate_course_archetypes(
                "test_disease",
                {"arch": {"trajectory": {"respiratory_fraction": {0: 0.5}}}},
            )


class TestTrajectoryStateVarsDerivedFromCanonical:
    def test_trajectory_set_is_canonical_minus_respiratory_fraction(self) -> None:
        """Set equality: tuple ordering is load-bearing for determinism (AD-16)
        but membership must match canonical minus respiratory_fraction."""
        from clinosim.modules.clinical_course.engine import TRAJECTORY_STATE_VARS
        from clinosim.modules.physiology.engine import canonical_state_vars

        assert frozenset(TRAJECTORY_STATE_VARS) == canonical_state_vars() - {"respiratory_fraction"}

    def test_trajectory_iteration_order_is_pinned(self) -> None:
        """AD-16: get_state_changes consumes rng inside the loop, so trajectory
        iteration order shifts RNG draws — pin the tuple to the pre-FP-DELTA-VALIDATE
        order so byte-diff regressions are caught by this guard rather than by
        e2e goldens hours later.
        """
        from clinosim.modules.clinical_course.engine import TRAJECTORY_STATE_VARS

        assert TRAJECTORY_STATE_VARS == (
            "inflammation_level",
            "volume_status",
            "renal_function",
            "perfusion_status",
            "cardiac_function",
            "hepatic_function",
            "anemia_level",
            "coagulation_status",
            "ph_status",
            "glucose_status",
            "sodium_status",
            "anion_gap_status",
        )


class TestLoadDiseaseProtocolFailsLoud:
    """Integration: load_disease_protocol should propagate the validation."""

    def test_yaml_with_unknown_state_var_raises_on_load(self, tmp_path, monkeypatch) -> None:
        import yaml as _yaml

        from clinosim.modules.disease import protocol as protocol_module

        bad = {
            "disease_id": "test_bad",
            "icd_codes": {"primary": "Z99"},
            "incidence": {"annual_per_100k": 1},
            "severity": {
                "distribution": {"mild": 1.0, "moderate": 0.0, "severe": 0.0},
                "modifiers": [],
            },
            "initial_state_impact": {
                "severe": {"consciousness": -0.3},  # silent-drop offender
            },
        }
        yaml_path = tmp_path / "test_bad.yaml"
        with yaml_path.open("w") as f:
            _yaml.safe_dump(bad, f)
        monkeypatch.setattr(protocol_module, "_REF_DIR", tmp_path)
        protocol_module.load_disease_protocol.cache_clear()
        with pytest.raises(ValueError, match=r"consciousness"):
            protocol_module.load_disease_protocol("test_bad")
