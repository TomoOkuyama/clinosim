import pytest

from clinosim.codes import lookup
from clinosim.modules.code_status.engine import load_reference

pytestmark = pytest.mark.unit


def test_all_tier_codes_resolve():
    ref = load_reference()
    for t in ref["tiers"]:
        disp = lookup("snomed-ct", t["snomed"], "en")
        assert disp and disp != t["snomed"]
    assert lookup("snomed-ct", ref["observable_snomed"], "en")
