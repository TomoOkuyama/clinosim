"""Unit tests for ForcedScenario.force_hai_event (PR3b-1 Task 7b)."""
from datetime import date
from types import SimpleNamespace

import pytest

from clinosim.types.config import ForcedScenario


@pytest.mark.unit
def test_forced_scenario_default_no_force_hai():
    s = ForcedScenario(disease_id="sepsis")
    assert s.force_hai_event is None


@pytest.mark.unit
def test_forced_scenario_force_hai_event_dict():
    s = ForcedScenario(
        disease_id="sepsis",
        force_hai_event={
            "hai_type": "cauti",
            "onset_offset_days": 3,
            "organism_snomed": "112283007",
        },
    )
    assert s.force_hai_event["hai_type"] == "cauti"
    assert s.force_hai_event["onset_offset_days"] == 3
    assert s.force_hai_event["organism_snomed"] == "112283007"


@pytest.mark.unit
def test_forced_scenario_force_hai_event_missing_hai_type_accepted_at_dataclass():
    """Consumer (enrich_hai) is expected to validate hai_type ∈ HAI_TYPES;
    the dict itself accepts arbitrary shape so legacy callers don't break."""
    s = ForcedScenario(disease_id="sepsis", force_hai_event={"hai_type": "bogus"})
    assert s.force_hai_event["hai_type"] == "bogus"


from clinosim.modules.hai.enricher import enrich_hai
from clinosim.types.device import DeviceRecord


def _make_ctx_with_device(device_type: str, force_hai_event: dict | None):
    dev = DeviceRecord(
        device_id="d1",
        encounter_id="enc-1",
        device_type=device_type,
        snomed_code="23973005",
        placement_date="2026-01-05",
        removal_date="2026-01-15",
        placement_indication="test",
    )
    rec = SimpleNamespace(
        patient=SimpleNamespace(patient_id="p1"),
        extensions={"device": [dev]},
        microbiology=[],
    )
    forced = SimpleNamespace(
        disease_id="urinary_tract_infection", count=1, severity=None,
        archetype=None, complications=[], patient_overrides={},
        force_hai_event=force_hai_event,
    )
    cfg = SimpleNamespace(
        country="US", random_seed=42,
        time_range=("2026-01-01", "2026-12-31"),
        snapshot_date=None,
        forced_scenarios=[forced],
    )
    return SimpleNamespace(config=cfg, master_seed=42, records=[rec]), rec


@pytest.mark.unit
def test_enrich_hai_force_emits_one_event_per_matching_device():
    """force_hai_event with hai_type=cauti emits HAI for indwelling_catheter
    devices, ignoring Poisson sampling."""
    ctx, rec = _make_ctx_with_device(
        device_type="indwelling_catheter",
        force_hai_event={
            "hai_type": "cauti",
            "onset_offset_days": 3,
            "organism_snomed": "112283007",
        },
    )
    enrich_hai(ctx)
    hai = rec.extensions.get("hai", []) or []
    assert len(hai) == 1
    assert hai[0].hai_type == "cauti"
    assert hai[0].onset_date == "2026-01-08"  # placement 2026-01-05 + 3 days
    assert hai[0].organism_snomed == "112283007"


@pytest.mark.unit
def test_enrich_hai_force_mismatched_hai_type_no_emit():
    """force_hai_event with hai_type=vap but only catheter device → no emit."""
    ctx, rec = _make_ctx_with_device(
        device_type="indwelling_catheter",  # CAUTI mapping, not VAP
        force_hai_event={
            "hai_type": "vap",
            "onset_offset_days": 3,
            "organism_snomed": "3092008",
        },
    )
    enrich_hai(ctx)
    assert rec.extensions.get("hai", []) == []


# ===== PR-93 adversarial review fixes =====


@pytest.mark.unit
def test_enrich_hai_force_uppercase_hai_type_raises():
    """PR-93 fix: uppercase typo must raise loudly, not silently no-op."""
    ctx, rec = _make_ctx_with_device(
        device_type="indwelling_catheter",
        force_hai_event={
            "hai_type": "CAUTI",  # uppercase typo
            "onset_offset_days": 3,
            "organism_snomed": "112283007",
        },
    )
    with pytest.raises(ValueError, match="not in canonical HAI_TYPES"):
        enrich_hai(ctx)


@pytest.mark.unit
def test_enrich_hai_force_trailing_space_raises():
    """PR-93 fix: trailing whitespace must raise loudly."""
    ctx, rec = _make_ctx_with_device(
        device_type="indwelling_catheter",
        force_hai_event={
            "hai_type": "cauti ",
            "onset_offset_days": 3,
            "organism_snomed": "112283007",
        },
    )
    with pytest.raises(ValueError, match="not in canonical HAI_TYPES"):
        enrich_hai(ctx)


@pytest.mark.unit
def test_enrich_hai_force_missing_keys_raises():
    """PR-93 fix: missing required keys must raise."""
    ctx, rec = _make_ctx_with_device(
        device_type="indwelling_catheter",
        force_hai_event={"hai_type": "cauti"},   # missing onset_offset_days + organism_snomed
    )
    with pytest.raises(ValueError, match="missing required keys"):
        enrich_hai(ctx)


class _CapturingRNG:
    """Wraps np.random.Generator and logs each draw method called."""
    def __init__(self, inner, log):
        self._inner = inner
        self._log = log

    def random(self, *a, **k):
        self._log.append("random")
        return self._inner.random(*a, **k)

    def integers(self, *a, **k):
        self._log.append("integers")
        return self._inner.integers(*a, **k)

    def choice(self, *a, **k):
        self._log.append("choice")
        return self._inner.choice(*a, **k)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _capture_enrich_hai_draws(make_ctx_fn):
    """Run enrich_hai with rng capture; return ordered list of draw methods."""
    import numpy as np
    from clinosim.modules.hai import enricher as enricher_mod
    orig_default_rng = np.random.default_rng
    log: list[str] = []

    def capture_rng(*args, **kwargs):
        return _CapturingRNG(orig_default_rng(*args, **kwargs), log)

    enricher_mod.np.random.default_rng = capture_rng
    try:
        ctx, rec = make_ctx_fn()
        enrich_hai(ctx)
        return list(log), rec
    finally:
        enricher_mod.np.random.default_rng = orig_default_rng


@pytest.mark.unit
def test_enrich_hai_force_consumes_exact_firing_path_sequence():
    """PR-94 adversarial review fix (AD-16 RNG isolation, STRICT):
    forced path's rng-method sequence must EXACTLY equal the non-forced
    FIRING path's known sequence: random (sample_hai_onset Poisson check)
    + integers (sample_hai_onset onset_offset) + choice (_sample_organism).
    Earlier permissive `>=` accepted over-draining; the over-drained
    earlier draws (random, integers, random) didn't even use choice as
    the 3rd-call equivalent of _sample_organism.
    """
    forced_log, _ = _capture_enrich_hai_draws(lambda: _make_ctx_with_device(
        device_type="indwelling_catheter",
        force_hai_event={"hai_type": "cauti", "onset_offset_days": 3,
                         "organism_snomed": "112283007"},
    ))
    # The exact firing-path sequence (sample_hai_onset always-on random +
    # firing-branch integers, then _sample_organism's choice):
    assert forced_log == ["random", "integers", "choice"], (
        f"forced path rng-method sequence is {forced_log}; "
        "must be ['random', 'integers', 'choice'] to match the non-forced "
        "firing path exactly (AD-16 RNG isolation)"
    )


@pytest.mark.unit
def test_enrich_hai_non_forced_firing_path_sequence_matches_forced():
    """Verify the firing-path sequence is indeed ['random','integers','choice'].

    Uses a monkeypatched 100% firing rate via direct rates_cfg patch in
    enrich_hai module so the non-forced path deterministically fires.
    """
    import numpy as np
    from clinosim.modules.hai import enricher as enricher_mod

    captured: list[str] = []
    orig_default_rng = np.random.default_rng

    def capture_rng(*args, **kwargs):
        return _CapturingRNG(orig_default_rng(*args, **kwargs), captured)

    # Patch load_hai_rates AT THE CALLSITE in enricher_mod (it was
    # imported via `from ... import load_hai_rates` so the name is
    # bound in enricher's namespace).
    rates_high = {"hai_rates": {hai: {"per_day_risk": 1.0}
                                for hai in ("clabsi", "cauti", "vap")}}
    orig_load = enricher_mod.load_hai_rates
    enricher_mod.load_hai_rates = lambda: rates_high
    enricher_mod.np.random.default_rng = capture_rng
    try:
        ctx, _ = _make_ctx_with_device(
            device_type="indwelling_catheter", force_hai_event=None,
        )
        enrich_hai(ctx)
    finally:
        enricher_mod.load_hai_rates = orig_load
        enricher_mod.np.random.default_rng = orig_default_rng

    assert captured == ["random", "integers", "choice"], (
        f"non-forced firing path sequence is {captured}; expected "
        "['random','integers','choice']. If this differs, the forced "
        "drain in enrich_hai's forced branch is out of sync."
    )


@pytest.mark.unit
def test_enrich_hai_force_short_line_days_skips_no_drain():
    """PR-94 adversarial review fix: when device.line_days < 2, the
    non-forced path returns BEFORE drawing any rng. The forced path
    must also short-circuit with 0 draws — NOT drain 3.
    """
    import numpy as np
    from clinosim.modules.hai import enricher as enricher_mod
    from clinosim.types.device import DeviceRecord

    log: list[str] = []
    orig = np.random.default_rng
    enricher_mod.np.random.default_rng = lambda *a, **k: _CapturingRNG(orig(*a, **k), log)
    try:
        # device line_days = 1 (< 2)
        dev = DeviceRecord(
            device_id="d1", encounter_id="enc-1",
            device_type="indwelling_catheter",
            snomed_code="23973005",
            placement_date="2026-01-05",
            removal_date="2026-01-06",   # 1 day
            placement_indication="test",
        )
        rec = SimpleNamespace(
            patient=SimpleNamespace(patient_id="p1"),
            extensions={"device": [dev]}, microbiology=[],
        )
        forced = SimpleNamespace(
            disease_id="x", count=1, severity=None, archetype=None,
            complications=[], patient_overrides={},
            force_hai_event={"hai_type": "cauti", "onset_offset_days": 3,
                             "organism_snomed": "112283007"},
        )
        cfg = SimpleNamespace(country="US", random_seed=42,
                              time_range=("2026-01-01", "2026-12-31"),
                              snapshot_date=None, forced_scenarios=[forced])
        ctx = SimpleNamespace(config=cfg, master_seed=42, records=[rec])
        enrich_hai(ctx)
    finally:
        enricher_mod.np.random.default_rng = orig

    assert log == [], (
        f"forced path on a < 2-day device line consumed rng draws {log!r}; "
        "must short-circuit before any draw to match non-forced behaviour"
    )
    assert rec.extensions.get("hai", []) == []
