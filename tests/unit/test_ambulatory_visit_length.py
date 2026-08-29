"""Unit tests for Issue #927 — per-visit-type outpatient (AMB) length.

Pre-fix (v0.5.0): every outpatient encounter had ``length.value`` drawn
from a uniform ``rng.integers(15, 45)`` regardless of visit purpose,
excluding the 5-10 min return-visit peak that dominates real JP
primary-care volume.

Post-fix: length is drawn from a per-visit-type triangular distribution
whose parameters live in
``clinosim/locale/<country>/ambulatory_visit_length.yaml``. This suite
verifies:

* both JP and US configs load and satisfy the ``0 < min <= mode <= max``
  invariant, and JP follow-up sits below JP screening / post-discharge
  (the qualitative fix promised by the issue);
* the sampler routes through the deterministic RNG proxy
  (``clinosim.determinism.default_rng``), not ``np.random.default_rng``
  directly, so the fix is bit-reproducible;
* chronic follow-up encounters cluster in the short (< 20 min) tail
  and health-screening encounters cluster in the long (> 20 min) tail —
  the two histograms produce distinctly different modes, closing the
  #927 "all AMB encounters share a single flat distribution" defect;
* the per-encounter sub-RNG isolates the length draw from the caller's
  master ``opd_rng`` so downstream RNG consumers keep their pre-fix
  byte-shape;
* the seeding helper is deterministic and encounter-id-sensitive
  (sibling AD-16 rule to ``individual_lab_seed``).

Home-visit / inpatient length logic is intentionally NOT touched by
this fix — this module has no corresponding sampler to invoke, so the
scope-guard is enforced by inspection of ``clinosim.simulator.outpatient``
(the sampler is only called from ``_simulate_outpatient_visit`` which
handles the four AMB visit types).
"""

from __future__ import annotations

import statistics

import pytest

from clinosim.locale.loader import load_ambulatory_visit_length
from clinosim.seeding import ambulatory_visit_length_seed
from clinosim.simulator.outpatient import _sample_ambulatory_visit_length_minutes


class TestYamlConfigs:
    def test_jp_config_loads_and_validates(self) -> None:
        cfg = load_ambulatory_visit_length("JP")
        assert "default" in cfg
        assert "visit_types" in cfg
        for vt in ("chronic_followup", "post_discharge", "pediatric_visit", "health_screening"):
            assert vt in cfg["visit_types"], f"JP config missing visit_type {vt!r}"

    def test_us_config_loads_and_validates(self) -> None:
        cfg = load_ambulatory_visit_length("US")
        assert "default" in cfg
        for vt in ("chronic_followup", "post_discharge", "pediatric_visit", "health_screening"):
            assert vt in cfg["visit_types"], f"US config missing visit_type {vt!r}"

    def test_jp_follow_up_below_screening(self) -> None:
        """The whole point of #927: 再診 must be shorter than 初診-like
        health screening. Enforce that the yaml keeps that ordering."""
        cfg = load_ambulatory_visit_length("JP")
        cf = cfg["visit_types"]["chronic_followup"]
        hs = cfg["visit_types"]["health_screening"]
        assert cf["mode"] < hs["mode"]
        assert cf["max"] < hs["mode"]

    def test_us_follow_up_below_screening(self) -> None:
        cfg = load_ambulatory_visit_length("US")
        cf = cfg["visit_types"]["chronic_followup"]
        hs = cfg["visit_types"]["health_screening"]
        assert cf["mode"] < hs["mode"]
        assert cf["max"] < hs["mode"]

    def test_all_buckets_satisfy_min_mode_max_invariant(self) -> None:
        for country in ("JP", "US"):
            cfg = load_ambulatory_visit_length(country)
            buckets = list(cfg["visit_types"].values()) + [cfg["default"]]
            for b in buckets:
                assert 0 < b["min"] <= b["mode"] <= b["max"]


class TestSeedingHelper:
    def test_is_deterministic(self) -> None:
        s1 = ambulatory_visit_length_seed("ENC-abc")
        s2 = ambulatory_visit_length_seed("ENC-abc")
        assert s1 == s2

    def test_is_encounter_id_sensitive(self) -> None:
        assert ambulatory_visit_length_seed("ENC-1") != ambulatory_visit_length_seed("ENC-2")

    def test_seed_in_uint32_range(self) -> None:
        for enc in ("ENC-a", "ENC-b", "enc-0000287dc6d0", "x" * 128):
            s = ambulatory_visit_length_seed(enc)
            assert 0 <= s < 2**32


class TestSamplerDistribution:
    """Statistical checks over 400 draws per visit type. Deterministic:
    every draw's sub-RNG is seeded from a unique encounter_id, and the
    seed formula (``ambulatory_visit_length_seed``) is pinned."""

    N = 400

    def _draw(self, visit_type: str, country: str) -> list[int]:
        return [
            _sample_ambulatory_visit_length_minutes(visit_type, country, f"enc-{visit_type}-{i:04d}")
            for i in range(self.N)
        ]

    @pytest.mark.parametrize("country", ["JP", "US"])
    def test_all_samples_respect_yaml_bounds(self, country: str) -> None:
        cfg = load_ambulatory_visit_length(country)
        for visit_type, bucket in cfg["visit_types"].items():
            xs = self._draw(visit_type, country)
            assert all(x >= 1 for x in xs)
            # Rounding lets the outer int touch the [min-0.5, max+0.5] band.
            assert min(xs) >= max(1, int(round(bucket["min"] - 0.5)))
            assert max(xs) <= int(round(bucket["max"] + 0.5))

    def test_jp_chronic_followup_short_tail(self) -> None:
        xs = self._draw("chronic_followup", "JP")
        # Yaml: min=5 mode=9 max=20. Median should sit near the mode,
        # never in the pre-fix 25-30 min plateau.
        med = statistics.median(xs)
        assert med <= 13, f"JP chronic_followup median={med} — expected short return-visit peak"
        # No sample should breach the yaml upper bound.
        assert max(xs) <= 20

    def test_jp_health_screening_long_tail(self) -> None:
        xs = self._draw("health_screening", "JP")
        # Yaml: min=20 mode=30 max=45.
        med = statistics.median(xs)
        assert 25 <= med <= 35, f"JP health_screening median={med}"
        assert min(xs) >= 19

    def test_jp_two_modes_are_distinguishable(self) -> None:
        """Closes the #927 signature: chronic_followup and health_screening
        must NOT share the same distribution shape."""
        cf = self._draw("chronic_followup", "JP")
        hs = self._draw("health_screening", "JP")
        assert statistics.median(cf) + 10 <= statistics.median(hs)

    def test_us_chronic_followup_short_tail(self) -> None:
        xs = self._draw("chronic_followup", "US")
        # Yaml: min=8 mode=15 max=25.
        med = statistics.median(xs)
        assert 10 <= med <= 20, f"US chronic_followup median={med}"

    def test_us_health_screening_long_tail(self) -> None:
        xs = self._draw("health_screening", "US")
        # Yaml: min=25 mode=35 max=55.
        med = statistics.median(xs)
        assert 30 <= med <= 42, f"US health_screening median={med}"

    def test_unknown_visit_type_falls_back_to_default(self) -> None:
        xs = [
            _sample_ambulatory_visit_length_minutes("no_such_visit_type", "JP", f"enc-{i:04d}") for i in range(self.N)
        ]
        cfg = load_ambulatory_visit_length("JP")
        default = cfg["default"]
        assert all(default["min"] - 1 <= x <= default["max"] + 1 for x in xs)


class TestDeterminismAndRngShape:
    def test_repeated_call_is_bit_identical(self) -> None:
        # Same (visit_type, country, encounter_id) → same integer.
        a = _sample_ambulatory_visit_length_minutes("chronic_followup", "JP", "enc-fixed-001")
        b = _sample_ambulatory_visit_length_minutes("chronic_followup", "JP", "enc-fixed-001")
        assert a == b

    def test_sampler_does_not_use_numpy_default_rng_directly(self) -> None:
        """AGENTS.md Cross-platform RNG proxy rule (v0.5.0+): every RNG
        must go through ``clinosim.determinism.default_rng``, not
        ``np.random.default_rng``. Guard by source inspection."""
        import inspect

        from clinosim.simulator import outpatient

        src = inspect.getsource(outpatient._sample_ambulatory_visit_length_minutes)
        assert "np.random.default_rng" not in src
        assert "numpy.random.default_rng" not in src
        assert "determinism.default_rng" in src

    def test_master_rng_is_not_consumed_by_length_draw(self) -> None:
        """Per-encounter sub-RNG must isolate the length draw. If the
        sampler ever accidentally consumes a ``rng`` argument passed in,
        this test will need to change — that itself is the guardrail:
        the sampler intentionally takes NO ``rng`` parameter."""
        import inspect

        from clinosim.simulator import outpatient

        sig = inspect.signature(outpatient._sample_ambulatory_visit_length_minutes)
        assert "rng" not in sig.parameters, (
            "sampler must NOT accept a caller RNG — the sub-RNG derived from "
            "encounter_id is the whole point of the RNG-shape guarantee"
        )
