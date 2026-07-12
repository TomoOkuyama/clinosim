"""session 48 P2-14: add-your-country scaffold + guide の存在と gate をテスト."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "add-your-country.md"
TEMPLATE_DIR = ROOT / "clinosim" / "locale" / "_template"

_REQUIRED_YAMLS = [
    "names.yaml",
    "addresses.yaml",
    "demographics.yaml",
    "formatting.yaml",
    "code_mapping_diagnosis.yaml",
    "code_mapping_lab.yaml",
    "code_mapping_drug.yaml",
    "code_mapping_procedure.yaml",
    "reference_range_lab.yaml",
]


@pytest.mark.unit
def test_guide_exists_and_covers_key_sections():
    assert GUIDE.exists(), f"{GUIDE} missing"
    text = GUIDE.read_text()
    for heading in ("Required YAML files", "Testing checklist", "Common pitfalls"):
        assert heading in text, f"section missing: {heading}"


@pytest.mark.unit
def test_scaffold_directory_has_all_required_yamls():
    assert TEMPLATE_DIR.is_dir()
    missing = [f for f in _REQUIRED_YAMLS if not (TEMPLATE_DIR / f).exists()]
    assert not missing, f"scaffold missing files: {missing}"


@pytest.mark.unit
def test_scaffold_readme_warns_non_runnable():
    readme = TEMPLATE_DIR / "README.md"
    assert readme.exists()
    text = readme.read_text()
    assert "non-runnable" in text.lower() or "not runnable" in text.lower() \
        or "schema-only" in text.lower()


@pytest.mark.unit
def test_country_dir_rejects_underscore_prefix():
    """`_template` を country として使うと ValueError で fail する。"""
    from clinosim.locale.loader import _country_dir
    with pytest.raises(ValueError, match="scaffold"):
        _country_dir("_TEMPLATE")


@pytest.mark.unit
def test_country_dir_still_accepts_registered_countries():
    from clinosim.locale.loader import _country_dir
    # 既存 country は変わらず動く
    assert _country_dir("JP").name == "jp"
    assert _country_dir("US").name == "us"


@pytest.mark.unit
def test_country_dir_falls_back_to_lowercase_for_new_countries():
    """`_COUNTRY_DIR_MAP` 未登録の 2 文字 code は lower-case 展開される。"""
    from clinosim.locale.loader import _country_dir
    p = _country_dir("DE")
    assert p.name == "de"
