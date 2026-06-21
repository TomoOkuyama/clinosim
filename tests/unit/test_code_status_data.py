import dataclasses
from pathlib import Path

import pytest
import yaml

from clinosim.types.output import CIFPatientRecord

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[2] / "clinosim"


def test_cif_field_default():
    fields = {f.name for f in dataclasses.fields(CIFPatientRecord)}
    assert "code_status" in fields


def test_reference_tiers():
    d = yaml.safe_load(open(_ROOT / "modules/code_status/reference_data/code_status.yaml"))
    assert d["tiers"][0]["key"] == "full_code"
    assert [t["key"] for t in d["tiers"]] == ["full_code", "dnr", "dnr_dni", "comfort"]
    assert all(t.get("snomed") for t in d["tiers"])
    assert d["observable_snomed"]


@pytest.mark.parametrize("country", ["us", "jp"])
def test_rates_shape(country):
    d = yaml.safe_load(open(_ROOT / f"locale/{country}/code_status_rates.yaml"))
    for ctx in ("routine", "icu", "terminal"):
        bands = d["weights"][ctx]
        for band, w in bands.items():
            assert len(w) == 4 and abs(sum(w) - 1.0) < 1e-6
