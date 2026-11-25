"""Unit tests for diagnosis engine."""

import pytest

from clinosim.modules.diagnosis.engine import (
    DifferentialDiagnosis,
    _display,
    get_current_diagnosis_code,
    initialize_differential,
    update_differential,
)


@pytest.mark.unit
class TestDiagnosis:
    def test_initial_differential(self):
        diff = initialize_differential("bacterial_pneumonia", age=72)
        assert len(diff.candidates) > 0
        assert diff.candidates[0].disease_code == "bacterial_pneumonia"
        total = sum(c.probability for c in diff.candidates)
        assert total == pytest.approx(1.0, abs=0.01)

    def test_bayesian_update_positive_cxr(self):
        diff = initialize_differential()
        initial_prob = diff.candidates[0].probability

        diff = update_differential(diff, [("chest_xray_consolidation", True)])
        # Positive CXR should increase bacterial pneumonia probability
        assert diff.candidates[0].probability > initial_prob

    def test_bayesian_update_confirms(self):
        diff = initialize_differential()
        # Stack positive findings
        diff = update_differential(
            diff,
            [
                ("chest_xray_consolidation", True),
                ("procalcitonin_elevated", True),
                ("crp_above_100", True),
            ],
            confirmation_threshold=0.90,
        )
        assert diff.confirmed is True
        assert diff.working_diagnosis == "bacterial_pneumonia"

    def test_negative_findings_reduce_probability(self):
        diff = initialize_differential()
        initial_prob = diff.candidates[0].probability
        diff = update_differential(diff, [("chest_xray_consolidation", False)])
        assert diff.candidates[0].probability < initial_prob

    def test_diagnosis_code_progression(self):
        diff = initialize_differential()
        # Initial: top candidate is bacterial_pneumonia at prior 0.45 → fall back to top progression
        code, name = get_current_diagnosis_code(diff)
        assert code == "J18.9"  # falls back to progression[0] for top candidate

        # One positive CXR → bacterial pneumonia probability jumps above 0.5
        diff = update_differential(diff, [("chest_xray_consolidation", True)])
        assert diff.working_diagnosis == "bacterial_pneumonia"
        code, name = get_current_diagnosis_code(diff)
        assert code in ("J18.9", "J18.1")  # unspecified or lobar

        # More findings → high confidence → most specific non-organism code
        diff = update_differential(
            diff,
            [
                ("procalcitonin_elevated", True),
                ("crp_above_100", True),
            ],
        )
        code, name = get_current_diagnosis_code(diff)
        # Issue #3645: confidence alone never gives the organism-specific J13;
        # that code follows a pneumococcal isolate (organism_pneumonia_codes.yaml).
        assert code == "J18.1"

    def test_probabilities_always_sum_to_one(self):
        diff = initialize_differential()
        for finding in ["chest_xray_consolidation", "procalcitonin_elevated", "wbc_elevated"]:
            diff = update_differential(diff, [(finding, True)])
            total = sum(c.probability for c in diff.candidates)
            assert total == pytest.approx(1.0, abs=0.01)

    def test_r69_fallback_display_resolves_via_code_system(self, monkeypatch):
        """R69 fallback display must route through _display() (AD-30), not a raw literal.

        An empty differential (no candidates, no working diagnosis) triggers the
        last-resort R69 branch in get_current_diagnosis_code. We monkeypatch
        _display so a raw "Illness, unspecified" literal would fail this test,
        proving the fallback resolves display via the code system resolver.
        """
        sentinel = "RESOLVED_VIA_DISPLAY"
        monkeypatch.setattr(
            "clinosim.modules.diagnosis.engine._display",
            lambda icd_code: sentinel,
        )
        empty = DifferentialDiagnosis(candidates=[], working_diagnosis=None)
        code, name = get_current_diagnosis_code(empty)
        assert code == "R69"
        assert name == sentinel

    def test_r69_fallback_display_matches_code_system(self):
        """The R69 fallback display equals the code-system resolution for R69."""
        empty = DifferentialDiagnosis(candidates=[], working_diagnosis=None)
        code, name = get_current_diagnosis_code(empty)
        assert code == "R69"
        assert name == _display("R69")


@pytest.mark.unit
class TestRepeatedFindings:
    """A finding's likelihood ratio counts once per differential (Issue #3820).

    The daily loop feeds every day's new draw of the same test. Serial
    results of one test are not independent evidence, and a marker that
    falls under treatment is a response, not a diagnosis: re-applying the
    negative CRP ratio each day turned treated bacterial pneumonia into
    viral pneumonia by day 4."""

    def test_a_repeated_finding_does_not_move_the_posterior_again(self):
        diff = update_differential(initialize_differential(), [("crp_above_100", False)])
        once = {c.disease_code: c.probability for c in diff.candidates}
        diff = update_differential(diff, [("crp_above_100", False)])
        assert {c.disease_code: c.probability for c in diff.candidates} == pytest.approx(once)

    def test_a_finding_repeated_in_one_update_counts_once(self):
        single = update_differential(initialize_differential(), [("crp_above_100", False)])
        double = update_differential(initialize_differential(), [("crp_above_100", False), ("crp_above_100", False)])
        assert [c.probability for c in double.candidates] == pytest.approx([c.probability for c in single.candidates])

    def test_treated_pneumonia_keeps_its_diagnosis_as_markers_fall(self):
        diff = update_differential(
            initialize_differential("bacterial_pneumonia", age=72),
            [("chest_xray_consolidation", True), ("crp_above_100", True), ("wbc_above_15000", True)],
        )
        for _ in range(10):  # ten days of falling markers under antibiotics
            diff = update_differential(diff, [("crp_above_100", False), ("wbc_above_15000", False)])
        assert diff.working_diagnosis == "bacterial_pneumonia"
