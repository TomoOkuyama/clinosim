"""Issue #3646: a repeat study of a body site agrees with an earlier abnormal read
while the finding persists, and may normalise only after the resolution window."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.imaging.engine import (
    _select_report_template,
    abnormal_persists_days,
    imaging_enricher,
    imaging_report_is_abnormal,
    load_body_sites,
)
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit

T0 = datetime(2026, 3, 1, 9, 0)


def _snomed(site: str) -> str:
    return load_body_sites()[site]["snomed"]


def _order(n: int, modality: str, site: str, when: datetime, rate: float) -> Order:
    return Order(
        order_id=f"ORD-E1-I{n:02d}",
        encounter_id="E1",
        patient_id="P1",
        order_type=OrderType.IMAGING,
        display_name=f"{modality} {site}",
        ordered_datetime=when,
        status=OrderStatus.PLACED,
        imaging_modality=modality,
        imaging_body_site_code=_snomed(site),
        imaging_spec_meta={"abnormal_rate_by_severity": {"any": rate}},
    )


def _run(disease: str, orders: list[Order]) -> list:
    record = SimpleNamespace(
        patient_id="P1",
        orders=orders,
        extensions={"_disease_id": disease},
        severity="moderate",
        clinical_diagnosis=SimpleNamespace(admission_diagnosis_code=""),
    )
    imaging_enricher(SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace()))
    return record.extensions["imaging"]


def _abnormal(disease: str, study) -> bool:
    r = study.report
    return bool(
        imaging_report_is_abnormal(
            disease, study.modality_code, study.body_site_snomed, (r.impression_text, r.impression_text_ja)
        )
    )


def test_ct_after_an_abnormal_chest_xray_reads_abnormal() -> None:
    orders = [
        _order(1, "CR", "chest", T0, 1.0),
        _order(2, "CT", "chest", T0 + timedelta(days=1), 0.0),
    ]
    studies = _run("bacterial_pneumonia", orders)
    assert [_abnormal("bacterial_pneumonia", s) for s in studies] == [True, True]


def test_the_first_study_of_a_site_follows_the_rate() -> None:
    studies = _run("bacterial_pneumonia", [_order(1, "CR", "chest", T0, 0.0)])
    assert not _abnormal("bacterial_pneumonia", studies[0])


def test_a_normal_read_may_be_followed_by_an_abnormal_one() -> None:
    orders = [_order(1, "CR", "chest", T0, 0.0), _order(2, "CT", "chest", T0 + timedelta(days=1), 1.0)]
    studies = _run("bacterial_pneumonia", orders)
    assert [_abnormal("bacterial_pneumonia", s) for s in studies] == [False, True]


def test_a_read_after_the_window_follows_the_rate_again() -> None:
    gap = timedelta(days=abnormal_persists_days("bacterial_pneumonia") + 1)
    orders = [_order(1, "CR", "chest", T0, 1.0), _order(2, "CR", "chest", T0 + gap, 0.0)]
    studies = _run("bacterial_pneumonia", orders)
    assert [_abnormal("bacterial_pneumonia", s) for s in studies] == [True, False]


def test_another_body_site_is_unaffected() -> None:
    orders = [_order(1, "CT", "chest", T0, 1.0), _order(2, "CT", "head", T0 + timedelta(days=1), 0.0)]
    studies = _run("traffic_accident_severe", orders)
    assert [_abnormal("traffic_accident_severe", s) for s in studies] == [True, False]


def test_orders_listed_out_of_time_order_keep_their_ids_and_order() -> None:
    later = _order(1, "CT", "chest", T0 + timedelta(days=1), 0.0)
    earlier = _order(2, "CR", "chest", T0, 1.0)
    studies = _run("bacterial_pneumonia", [later, earlier])
    assert [s.order_id for s in studies] == [later.order_id, earlier.order_id]
    assert [s.study_id for s in studies] == ["imgst-E1-1", "imgst-E1-2"]
    # the earlier (abnormal) study is read first, so the later one agrees with it
    assert _abnormal("bacterial_pneumonia", studies[0])


def test_the_prior_read_does_not_move_the_random_stream() -> None:
    rng_a, rng_b = np.random.default_rng(7), np.random.default_rng(7)
    args = ("bacterial_pneumonia", "CT", "chest", "moderate", {"any": 0.0})
    kind, _ = _select_report_template(*args, rng_a, prior_abnormal=False)
    kind2, _ = _select_report_template(*args, rng_b, prior_abnormal=True)
    assert (kind, kind2) == ("normal", "abnormal")
    assert rng_a.random() == rng_b.random()
