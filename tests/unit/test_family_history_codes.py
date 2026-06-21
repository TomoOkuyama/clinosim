import pytest

from clinosim.codes import lookup

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("code", ["C50", "C18", "C34", "C61"])
def test_cancer_codes_resolve_us_and_jp(code):
    en = lookup("icd-10-cm", code, "en")
    assert en and en != code
    who = lookup("icd-10", code, "en")
    assert who and who != code
    assert lookup("icd-10-cm", code, "ja")  # JA present
