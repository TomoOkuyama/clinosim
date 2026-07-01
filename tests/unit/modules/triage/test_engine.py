"""Unit tests for triage engine(Tier 1 #3 α-min-2 PR1)."""

from __future__ import annotations

import numpy as np

from clinosim.modules.triage.engine import (
    SUPPORTED_ARRIVAL_MODES,
    SUPPORTED_LEVEL_SYSTEMS,
    load_triage_protocols,
    pick_arrival_mode,
    pick_triage_level,
)


def test_load_triage_protocols_returns_both_systems():
    p = load_triage_protocols()
    assert "JTAS" in p["triage_systems"]
    assert "ESI" in p["triage_systems"]


def test_supported_sets():
    assert SUPPORTED_LEVEL_SYSTEMS == frozenset({"JTAS", "ESI"})
    assert "walk-in" in SUPPORTED_ARRIVAL_MODES


def test_pick_triage_level_mild_jtas():
    """Mild severity → mostly level 4-5 (JTAS)."""
    rng = np.random.default_rng(42)
    counts = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    for _ in range(1000):
        level = pick_triage_level("mild", "JTAS", rng)
        counts[level] += 1
    # mild は 3-5 に集中(distribution 準拠)
    assert counts["1"] == 0
    assert counts["2"] == 0
    assert counts["4"] + counts["5"] >= 700  # 70%+


def test_pick_triage_level_severe_esi():
    """Severe severity → mostly level 1-2 (ESI)."""
    rng = np.random.default_rng(42)
    counts = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    for _ in range(1000):
        level = pick_triage_level("severe", "ESI", rng)
        counts[level] += 1
    # severe は 1-2 に集中
    assert counts["1"] + counts["2"] >= 700  # 70%+


def test_pick_arrival_mode_returns_valid():
    rng = np.random.default_rng(42)
    for _ in range(100):
        mode = pick_arrival_mode("moderate", rng)
        assert mode in SUPPORTED_ARRIVAL_MODES


def test_pick_triage_level_deterministic():
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    assert pick_triage_level("mild", "JTAS", rng1) == pick_triage_level("mild", "JTAS", rng2)


def test_triage_enricher_populates_ed_encounters():
    from types import SimpleNamespace
    from clinosim.modules.triage.engine import triage_enricher

    ed_enc = SimpleNamespace(
        encounter_id="ed1",
        encounter_type="emergency",
        severity="moderate",
        triage_data=None,
    )
    outpatient_enc = SimpleNamespace(
        encounter_id="op1",
        encounter_type="outpatient",
        severity="mild",
        triage_data=None,
    )
    inpatient_enc = SimpleNamespace(
        encounter_id="inp1",
        encounter_type="inpatient",
        severity="severe",
        triage_data=None,
    )
    record = SimpleNamespace(
        patient=SimpleNamespace(patient_id="pt1"),
        encounters=[ed_enc, outpatient_enc, inpatient_enc],
    )
    ctx = SimpleNamespace(
        master_seed=42,
        country="jp",
        records=[record],
    )
    triage_enricher(ctx)
    # ED encounter → triage_data populated
    assert ed_enc.triage_data is not None
    assert ed_enc.triage_data.level in {"1", "2", "3", "4", "5"}
    assert ed_enc.triage_data.level_system == "JTAS"  # JP → JTAS
    # non-ED → not touched
    assert outpatient_enc.triage_data is None
    assert inpatient_enc.triage_data is None


def test_triage_enricher_country_gates_esi_for_us():
    from types import SimpleNamespace
    from clinosim.modules.triage.engine import triage_enricher

    ed_enc = SimpleNamespace(
        encounter_id="ed1",
        encounter_type="emergency",
        severity="moderate",
        triage_data=None,
    )
    record = SimpleNamespace(
        patient=SimpleNamespace(patient_id="pt1"),
        encounters=[ed_enc],
    )
    ctx = SimpleNamespace(
        master_seed=42,
        country="us",
        records=[record],
    )
    triage_enricher(ctx)
    assert ed_enc.triage_data.level_system == "ESI"


def test_triage_enricher_deterministic():
    from types import SimpleNamespace
    from clinosim.modules.triage.engine import triage_enricher

    def _make():
        ed_enc = SimpleNamespace(
            encounter_id="ed1",
            encounter_type="emergency",
            severity="moderate",
            triage_data=None,
        )
        record = SimpleNamespace(
            patient=SimpleNamespace(patient_id="pt1"),
            encounters=[ed_enc],
        )
        return SimpleNamespace(master_seed=42, country="jp", records=[record])

    ctx1 = _make()
    ctx2 = _make()
    triage_enricher(ctx1)
    triage_enricher(ctx2)
    a = ctx1.records[0].encounters[0].triage_data
    b = ctx2.records[0].encounters[0].triage_data
    assert a.level == b.level
    assert a.arrival_mode == b.arrival_mode


def test_triage_enricher_reads_country_from_ctx_config_jp():
    """Production EnricherContext shape carries country at ctx.config.country
    (NOT ctx.country). This test pins the ctx.config.country resolution path
    so the JP cohort actually emits JTAS instead of silently defaulting to
    ESI (PR-90 class silent-no-op regression guard; fixed 2026-07-01).
    """
    from types import SimpleNamespace

    from clinosim.modules.triage.engine import triage_enricher

    ed_enc = SimpleNamespace(
        encounter_id="ed-prod-jp",
        encounter_type="emergency",
        severity="moderate",
        triage_data=None,
    )
    record = SimpleNamespace(
        patient=SimpleNamespace(patient_id="pt1"),
        encounters=[ed_enc],
    )
    # Production EnricherContext-shape ctx: country lives at ctx.config.country,
    # NOT at ctx.country.
    ctx = SimpleNamespace(
        master_seed=42,
        config=SimpleNamespace(country="JP"),
        records=[record],
    )
    triage_enricher(ctx)
    assert ed_enc.triage_data is not None
    assert ed_enc.triage_data.level_system == "JTAS", (
        "JP cohort must resolve country from ctx.config.country → JTAS "
        "(PR-90 regression guard)"
    )


def test_triage_enricher_reads_country_from_ctx_config_us():
    """Symmetric US production-shape test."""
    from types import SimpleNamespace

    from clinosim.modules.triage.engine import triage_enricher

    ed_enc = SimpleNamespace(
        encounter_id="ed-prod-us",
        encounter_type="emergency",
        severity="moderate",
        triage_data=None,
    )
    record = SimpleNamespace(
        patient=SimpleNamespace(patient_id="pt1"),
        encounters=[ed_enc],
    )
    ctx = SimpleNamespace(
        master_seed=42,
        config=SimpleNamespace(country="US"),
        records=[record],
    )
    triage_enricher(ctx)
    assert ed_enc.triage_data is not None
    assert ed_enc.triage_data.level_system == "ESI"
