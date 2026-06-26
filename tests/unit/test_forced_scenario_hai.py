"""Unit tests for ForcedScenario.force_hai_event (PR3b-1 Task 7b)."""
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


from clinosim.modules.hai.enricher import enrich_hai  # noqa: E402
from clinosim.types.device import DeviceRecord  # noqa: E402


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


# ===== PR-94 adversarial review fixes =====


@pytest.mark.unit
def test_enrich_hai_force_uppercase_hai_type_raises():
    """PR-94 fix: uppercase typo must raise loudly, not silently no-op."""
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
    """PR-94 fix: trailing whitespace must raise loudly."""
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
    """PR-94 fix: missing required keys must raise."""
    ctx, rec = _make_ctx_with_device(
        device_type="indwelling_catheter",
        force_hai_event={"hai_type": "cauti"},   # missing onset_offset_days + organism_snomed
    )
    with pytest.raises(ValueError, match="missing required keys"):
        enrich_hai(ctx)


# ===== PR-95 / Task 7 (PR3b-2): AD-16 exact-sequence pinning =====


class _CapturingRNG:
    """Wraps np.random.Generator and logs each draw method called."""
    def __init__(self, inner, log):
        self._inner = inner
        self._log = log

    def random(self, *a, **k):
        self._log.append(("random", None))
        return self._inner.random(*a, **k)

    def integers(self, *a, **k):
        self._log.append(("integers", None))
        return self._inner.integers(*a, **k)

    def choice(self, *a, **k):
        # PR3b-2 Adv #6 F1: log p=probs to detect YAML key-order shifts.
        p = k.get("p")
        if p is not None:
            self._log.append(("choice", tuple(round(float(x), 4) for x in p)))
        else:
            self._log.append(("choice", None))
        return self._inner.choice(*a, **k)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _capture_enrich_hai_draws(make_ctx_fn):
    """Run enrich_hai with rng capture; return ordered list of draw methods."""
    import numpy as np

    from clinosim.modules.hai import enricher as enricher_mod
    orig_default_rng = np.random.default_rng
    log: list[tuple] = []

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
    """PR-95 + PR3b-2 Task 7 (AD-16 RNG isolation, FORCED PATH ONLY):
    Verifies the forced path's own rng-method sequence is deterministic and
    accounts for the forced organism's antibiogram (CAUTI/E.coli/5 ABX → 8 draws).

    NOTE: forced and non-forced sequences are only equal when the forced
    organism has the same antibiogram size as the randomly-selected organism.
    For full AD-16 isolation tests, use a forced organism whose ABX count
    matches the known random outcome for this seed (CAUTI/E.faecalis would
    require 0 ABX to match the non-forced path's seed=42 outcome).

    Fixture: hai_type=cauti, organism=112283007 (E. coli).
    CAUTI/E.coli antibiogram has 5 entries (ceftriaxone, cefepime, meropenem,
    ciprofloxacin, trimethoprim_sulfamethoxazole) → 5 additional choice draws.
    Total: 3 (PR-95 firing path baseline) + 5 (PR3b-2 antibiogram) = 8 draws.
    """
    # CAUTI / E. coli (112283007): 5 antibiotic entries in hai_antibiogram.yaml
    # ceftriaxone, cefepime, meropenem, ciprofloxacin, trimethoprim_sulfamethoxazole
    # 3 (PR-95 baseline) + 5 (antibiogram cauti/112283007) = 8 total
    n_abx_cauti_ecoli = 5
    # CAUTI organism weights from hai_organisms.yaml (7 entries, sum=1.00)
    _cauti_org_probs = (0.27, 0.18, 0.16, 0.13, 0.1, 0.06, 0.1)
    # CAUTI/E.coli (112283007) antibiogram probs from hai_antibiogram.yaml
    # Order: ceftriaxone, cefepime, meropenem, ciprofloxacin, trimethoprim_sulfamethoxazole
    _cauti_ecoli_abg_probs = [
        (0.83, 0.02, 0.15),  # ceftriaxone
        (0.9, 0.02, 0.08),   # cefepime
        (0.99, 0.0, 0.01),   # meropenem
        (0.7, 0.05, 0.25),   # ciprofloxacin
        (0.7, 0.02, 0.28),   # trimethoprim_sulfamethoxazole
    ]
    expected_draws = (
        [("random", None), ("integers", None), ("choice", _cauti_org_probs)]
        + [("choice", probs) for probs in _cauti_ecoli_abg_probs]
    )

    forced_log, _ = _capture_enrich_hai_draws(lambda: _make_ctx_with_device(
        device_type="indwelling_catheter",
        force_hai_event={"hai_type": "cauti", "onset_offset_days": 3,
                         "organism_snomed": "112283007"},
    ))
    assert forced_log == expected_draws, (
        f"forced path rng-method sequence is {forced_log}; "
        f"must be {expected_draws} to match the non-forced firing path "
        "exactly (AD-16 RNG isolation). Each tuple is (method, p_or_None). "
        "3 baseline draws (PR-95) + 5 antibiogram draws (PR3b-2 cauti/112283007)."
    )


@pytest.mark.unit
def test_enrich_hai_non_forced_firing_path_baseline_sequence():
    """Verify the non-forced firing-path sequence has the correct structure.

    Uses a monkeypatched 100% firing rate via direct rates_cfg patch in
    enrich_hai module so the non-forced path deterministically fires.

    With seed=42 / patient_id='p1', _sample_organism for CAUTI selects
    E. faecalis (SNOMED 78065002), which has NO antibiogram entries in
    hai_antibiogram.yaml — so _append_hai_culture adds 0 additional choice
    draws. Total sequence: ['random', 'integers', 'choice'] (3 draws).

    NOTE: forced and non-forced sequences are only equal when the forced
    organism has the same antibiogram size as the randomly-selected organism.
    E.g., the forced CAUTI/E.coli path draws 8 (3 baseline + 5 antibiogram),
    while this non-forced CAUTI/E.faecalis path draws 3 (0 antibiogram).
    They are NOT equal in the common case; this test verifies the non-forced
    baseline structure only, not equality with the forced path.
    """
    import numpy as np
    from clinosim.modules.hai import enricher as enricher_mod

    captured: list[tuple] = []
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

    # seed=42 / p1 selects E. faecalis (78065002) — 0 antibiogram entries.
    # Total stays at 3 draws (baseline PR-95 sequence; no PR3b-2 extension here).
    _cauti_org_probs = (0.27, 0.18, 0.16, 0.13, 0.1, 0.06, 0.1)
    assert captured == [("random", None), ("integers", None), ("choice", _cauti_org_probs)], (
        f"non-forced firing path sequence is {captured}; expected "
        "[('random',None),('integers',None),('choice',_cauti_org_probs)]. "
        "If this differs, either the forced "
        "drain in enrich_hai's forced branch is out of sync (AD-16), or "
        "the stochastic organism selection changed (seed shift)."
    )


@pytest.mark.unit
def test_enrich_hai_force_short_line_days_skips_no_drain():
    """PR-95 fix: when device.line_days < 2, the non-forced path returns
    BEFORE drawing any rng. The forced path must also short-circuit with
    0 draws — NOT drain 3.
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


# ===== F-CRIT-2: PR3b-2 adversarial review — Task 6 run_forced injection gate =====


@pytest.mark.unit
def test_run_forced_auto_injects_force_hai_event_into_config(monkeypatch):
    """Task 6 fix (PR3b-2 Adv #4 F1): run_forced MUST inject force_hai_event
    scenario into config.forced_scenarios so enrich_hai can read it (PR-90
    class silent-no-op gate). This test does NOT require ICU transfers —
    we patch the registered "hai" enricher's run function to capture the
    ctx it receives and assert the scenario appears in
    ctx.config.forced_scenarios. Reverting the injection fix in engine.py
    (lines 478-481) should make this test FAIL loudly.
    """
    from clinosim.simulator import enrichers as enrichers_mod
    from clinosim.simulator.engine import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    # Ensure the enricher registry is initialised so _ENRICHERS["hai"] exists.
    enrichers_mod.register_builtin_enrichers()

    captured_configs: list = []
    orig_run = enrichers_mod._ENRICHERS["hai"].run

    def capture_ctx(ctx):
        captured_configs.append(list(getattr(ctx.config, "forced_scenarios", [])))
        return orig_run(ctx)

    # Monkeypatch the stored .run attribute; monkeypatch restores after test.
    monkeypatch.setattr(enrichers_mod._ENRICHERS["hai"], "run", capture_ctx)

    scenario = ForcedScenario(
        disease_id="bacterial_pneumonia", count=1,
        force_hai_event={
            "hai_type": "cauti",
            "onset_offset_days": 3,
            "organism_snomed": "112283007",
        },
    )
    config = SimulatorConfig(country="US", random_seed=42)
    run_forced(scenario, config=config)

    assert any(scenario in c for c in captured_configs), (
        "run_forced did not inject force_hai_event scenario into "
        "ctx.config.forced_scenarios — Task 6 injection is broken "
        "(PR-90 class silent no-op recurrence)"
    )
    # Caller's config must NOT be mutated
    assert config.forced_scenarios == [], (
        "run_forced mutated caller's config.forced_scenarios; "
        "expected model_copy to leave caller untouched"
    )
