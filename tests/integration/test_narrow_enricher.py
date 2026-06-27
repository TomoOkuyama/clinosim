"""PR3b-3: enrich_antibiotic Pass 2 E2E tests (narrow / de-escalation)."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP
from clinosim.modules.antibiotic.enricher import enrich_antibiotic
from clinosim.modules.hai import HAI_TYPES
from clinosim.types.encounter import OrderStatus
from clinosim.types.hai import HAIEvent
from clinosim.types.microbiology import MicrobiologyResult, SusceptibilityResult


def _make_ctx(records: list, snapshot_iso: str = "2026-12-31"):
    cfg = SimpleNamespace(
        country="US", snapshot_date=snapshot_iso,
        time_range=("2026-01-01", snapshot_iso),
    )
    return SimpleNamespace(config=cfg, master_seed=42, records=records)


def _make_record(
    hai_type: str,
    organism_snomed: str,
    susc: list[tuple[str, str]],
    onset_date: str = "2026-01-10",
    reported_offset_days: int = 2,
):
    """Build a synthetic record with a single HAI event + culture."""
    ev = HAIEvent(
        hai_id=f"hai-{hai_type}-test",
        encounter_id="enc-test",
        hai_type=hai_type,
        source_device_id="dev-1",
        icd10_code="X.0",  # unused in PR3b-3
        snomed_code="0",
        onset_date=onset_date,
        organism_snomed=organism_snomed,
        culture_specimen_id="spec-1",
    )
    onset_dt = datetime.fromisoformat(onset_date)
    reported_dt = onset_dt + timedelta(days=reported_offset_days)
    micro = MicrobiologyResult(
        encounter_id="enc-test",
        specimen="blood", specimen_snomed="119297000", test_loinc="600-7",
        collected_datetime=onset_dt,
        reported_datetime=reported_dt,
        growth=True,
        organism_snomed=organism_snomed,
        susceptibilities=[
            SusceptibilityResult(
                antibiotic_loinc=ANTIBIOTIC_LOINC_LOOKUP[k],
                interpretation=i,
            ) for k, i in susc
        ],
        hai_event_id=ev.hai_id,
    )
    return SimpleNamespace(
        patient=SimpleNamespace(patient_id="p-test"),
        encounters=[],
        orders=[],
        medication_administrations=[],
        microbiology=[micro],
        extensions={"hai": [ev]},
    )


@pytest.mark.integration
def test_clabsi_mssa_switch_to_cefazolin() -> None:
    """Case (i): empirical = vanc + pip-tazo, MSSA (cefazolin S) → SWITCH.
    Both empirical regimens discontinued at reported_datetime, new narrowed
    cefazolin regimen added with intent='narrowed'."""
    rec = _make_record(
        hai_type=HAI_TYPES[0],  # clabsi
        organism_snomed="3092008",  # S.aureus
        susc=[
            ("vancomycin", "S"),
            ("cefazolin", "S"),  # MSSA
            ("piperacillin_tazobactam", "S"),
        ],
    )
    ctx = _make_ctx([rec])
    enrich_antibiotic(ctx)

    regimens = rec.extensions["antibiotic"]
    # 2 empirical (vanc + pip-tazo) + 1 narrowed (cefazolin) = 3
    assert len(regimens) == 3

    empirical = [r for r in regimens if r.intent == "empirical"]
    narrowed = [r for r in regimens if r.intent == "narrowed"]
    assert len(empirical) == 2
    assert len(narrowed) == 1
    assert narrowed[0].drug_key == "cefazolin"
    # 14 total course - elapsed.days. Empirical start = onset_date 08:00
    # (_ORDER_HOUR), reported = onset+2d 00:00 → elapsed.days = 1 → narrow = 13.
    assert narrowed[0].duration_days == 13

    # All empirical have discontinuation_datetime set to reported_datetime
    reported = datetime(2026, 1, 12)  # onset 2026-01-10 + 2 days
    for r in empirical:
        assert r.discontinuation_datetime == reported

    # Orders: 2 empirical (status=STOPPED) + 1 narrowed (status=ACCEPTED) = 3
    med_orders = [o for o in rec.orders if o.order_type.value == "medication"]
    assert len(med_orders) == 3
    stopped = [o for o in med_orders if o.status == OrderStatus.STOPPED]
    assert len(stopped) == 2

    # MAR: empirical truncated (2-day worth each), narrow runs from day 2 to 14
    mar_count = len(rec.medication_administrations)
    assert mar_count > 0


@pytest.mark.integration
def test_clabsi_mrsa_elimination() -> None:
    """Case (ii): empirical = vanc + pip-tazo, MRSA (cefazolin R, vanc S)
    → ELIMINATION. Vanc continues unchanged, pip-tazo discontinued. No new
    narrowed regimen."""
    rec = _make_record(
        hai_type=HAI_TYPES[0],  # clabsi
        organism_snomed="3092008",
        susc=[
            ("vancomycin", "S"),
            ("cefazolin", "R"),  # MRSA
            ("piperacillin_tazobactam", "S"),
        ],
    )
    ctx = _make_ctx([rec])
    enrich_antibiotic(ctx)

    regimens = rec.extensions["antibiotic"]
    # 2 empirical, no new narrowed
    assert len(regimens) == 2
    assert all(r.intent == "empirical" for r in regimens)

    vanc = next(r for r in regimens if r.drug_key == "vancomycin")
    pip = next(r for r in regimens if r.drug_key == "piperacillin_tazobactam")
    assert vanc.discontinuation_datetime is None  # kept
    assert pip.discontinuation_datetime == datetime(2026, 1, 12)  # discontinued

    # Order status: vanc=ACCEPTED, pip=STOPPED
    vanc_order = next(o for o in rec.orders if "vancomycin" in o.display_name.lower())
    pip_order = next(o for o in rec.orders if "piperacillin" in o.display_name.lower())
    assert vanc_order.status == OrderStatus.ACCEPTED
    assert pip_order.status == OrderStatus.STOPPED


@pytest.mark.integration
def test_cauti_ecoli_esbl_neg_no_change() -> None:
    """Case (iii): empirical = ceftriaxone, ESBL- (ceftriaxone S, AND it is
    the only empirical drug, AND it equals the narrow target).
    Note: this requires ceftriaxone to be the narrow target chosen by the
    ladder, which means TMP-SMX must be R or absent. To force case (iii)
    we feed only ceftriaxone S; the ladder walk finds TMP-SMX (top of
    CAUTI ladder) absent → skips → ciprofloxacin absent → skips →
    ceftriaxone S → target=ceftriaxone == single empirical → NO_CHANGE."""
    rec = _make_record(
        hai_type=HAI_TYPES[1],  # cauti
        organism_snomed="112283007",  # E.coli
        susc=[("ceftriaxone", "S")],
    )
    ctx = _make_ctx([rec])
    enrich_antibiotic(ctx)

    regimens = rec.extensions["antibiotic"]
    assert len(regimens) == 1
    assert regimens[0].drug_key == "ceftriaxone"
    assert regimens[0].intent == "empirical"
    assert regimens[0].discontinuation_datetime is None

    med_orders = [o for o in rec.orders if o.order_type.value == "medication"]
    assert len(med_orders) == 1
    assert med_orders[0].status == OrderStatus.ACCEPTED


@pytest.mark.integration
def test_cauti_ecoli_esbl_pos_switch_to_meropenem() -> None:
    """Case (i): empirical = ceftriaxone, ESBL+ (ceftriaxone R), narrow ladder
    walks down to find meropenem S → SWITCH from ceftriaxone to meropenem."""
    rec = _make_record(
        hai_type=HAI_TYPES[1],  # cauti
        organism_snomed="112283007",
        susc=[
            ("trimethoprim_sulfamethoxazole", "R"),
            ("ciprofloxacin", "R"),
            ("ceftriaxone", "R"),  # ESBL+
            ("cefepime", "R"),
            ("meropenem", "S"),
        ],
    )
    ctx = _make_ctx([rec])
    enrich_antibiotic(ctx)

    regimens = rec.extensions["antibiotic"]
    assert len(regimens) == 2
    narrowed = [r for r in regimens if r.intent == "narrowed"]
    assert len(narrowed) == 1
    assert narrowed[0].drug_key == "meropenem"

    # Empirical ceftriaxone discontinued
    empirical = [r for r in regimens if r.intent == "empirical"]
    assert empirical[0].drug_key == "ceftriaxone"
    assert empirical[0].discontinuation_datetime == datetime(2026, 1, 12)


@pytest.mark.integration
def test_snapshot_before_reported_no_narrow() -> None:
    """AD-32: if snapshot < reported_datetime, narrow decision is skipped
    (empirical continues, no discontinuation)."""
    rec = _make_record(
        hai_type=HAI_TYPES[1],
        organism_snomed="112283007",
        susc=[("ceftriaxone", "S")],
        onset_date="2026-01-10",
        reported_offset_days=2,
    )
    ctx = _make_ctx([rec], snapshot_iso="2026-01-11")  # snapshot before reported (1/12)
    enrich_antibiotic(ctx)

    regimens = rec.extensions["antibiotic"]
    assert len(regimens) == 1
    assert regimens[0].discontinuation_datetime is None  # narrow skipped


@pytest.mark.integration
def test_fhir_medicationrequest_status_stopped_for_discontinued_empirical() -> None:
    """SWITCH case: empirical orders get FHIR status='stopped',
    narrowed order gets FHIR status='active'."""
    from dataclasses import asdict

    from clinosim.modules.output._fhir_medications import _build_medication_request

    rec = _make_record(
        hai_type=HAI_TYPES[0],
        organism_snomed="3092008",
        susc=[
            ("vancomycin", "S"),
            ("cefazolin", "S"),
            ("piperacillin_tazobactam", "S"),
        ],
    )
    ctx = _make_ctx([rec])
    enrich_antibiotic(ctx)

    med_orders = [o for o in rec.orders if o.order_type.value == "medication"]
    statuses = []
    for o in med_orders:
        d = asdict(o)
        d["status"] = o.status.value
        d["order_type"] = o.order_type.value
        mr = _build_medication_request(d, "p-test", "US", encounter_id="enc-test")
        statuses.append((d["display_name"], mr["status"]))

    stopped_count = sum(1 for _, s in statuses if s == "stopped")
    active_count = sum(1 for _, s in statuses if s == "active")
    assert stopped_count == 2
    assert active_count == 1


@pytest.mark.integration
def test_fhir_medicationrequest_status_cancelled_pin() -> None:
    """Regression pin (adversarial-1 I-C1): cancelled OrderStatus must map to
    FHIR MedicationRequest.status='cancelled' (existing behavior; previously
    not pinned by any test so a future _map_order_status_to_fhir edit could
    silently drop the mapping)."""
    from clinosim.modules.output._fhir_medications import _map_order_status_to_fhir
    assert _map_order_status_to_fhir("cancelled") == "cancelled"
    assert _map_order_status_to_fhir("stopped") == "stopped"
    assert _map_order_status_to_fhir("accepted") == "active"
    assert _map_order_status_to_fhir("placed") == "active"
    # Unknown / future values fall back to "active" — documented in helper
    assert _map_order_status_to_fhir("future_status") == "active"
