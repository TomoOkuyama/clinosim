"""The delivery procedure records an estimated blood loss, mirrored in the
mother's ``extensions["delivery"]`` (Issue #3663, CIF part)."""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_perinatal_config
from tests.unit.simulator.test_perinatal_complication_coding import _CESAREAN, _VAGINAL, _deliver

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize(("pid", "mode"), [(_VAGINAL, "vaginal"), (_CESAREAN, "cesarean")])
def test_ebl_is_recorded_within_the_configured_band(pid: str, mode: str, country: str) -> None:
    rec = _deliver(pid, [], country=country)
    ebl = rec.procedures[0].estimated_blood_loss_ml
    band = load_perinatal_config()["delivery_outcome"]["ebl_ml"][mode]
    assert isinstance(ebl, int) and band["min"] <= ebl <= band["max"]
    assert rec.extensions["delivery"]["estimated_blood_loss_ml"] == ebl
    assert rec.extensions["delivery"]["mode"] == mode


def test_ebl_is_deterministic_and_varies_between_mothers() -> None:
    assert _deliver(_VAGINAL, []).procedures[0].estimated_blood_loss_ml == (
        _deliver(_VAGINAL, []).procedures[0].estimated_blood_loss_ml
    )
    values = {_deliver(f"POP-{i:06d}", []).procedures[0].estimated_blood_loss_ml for i in range(1, 40)}
    assert len(values) > 10


def test_cesarean_loses_more_blood_on_average() -> None:
    by_mode: dict[str, list[int]] = {"vaginal": [], "cesarean": []}
    for i in range(1, 300):
        rec = _deliver(f"POP-{i:06d}", [])
        by_mode[rec.extensions["delivery"]["mode"]].append(rec.procedures[0].estimated_blood_loss_ml)
    assert sum(by_mode["cesarean"]) / len(by_mode["cesarean"]) > sum(by_mode["vaginal"]) / len(by_mode["vaginal"]) + 200


def test_ebl_does_not_move_the_rest_of_the_record() -> None:
    a = _deliver(_VAGINAL, ["O14.9"])
    assert [o.order_id for o in a.orders] and a.vital_signs == _deliver(_VAGINAL, ["O14.9"]).vital_signs
