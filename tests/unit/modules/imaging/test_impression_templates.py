"""Unit tests for impression_templates YAML loader/validator."""

from __future__ import annotations

from clinosim.modules.imaging.engine import load_impression_templates


def test_templates_cover_pneumonia_and_stroke():
    t = load_impression_templates()
    assert "bacterial_pneumonia" in t
    assert "aspiration_pneumonia" in t
    assert "hemorrhagic_stroke" in t


def test_bacterial_pneumonia_has_cr_and_ct_templates():
    t = load_impression_templates()
    bp = t["bacterial_pneumonia"]
    assert "CR_chest" in bp
    assert "CT_chest" in bp
    cr_normal = bp["CR_chest"]["normal"]
    assert "findings_en" in cr_normal
    assert "findings_ja" in cr_normal
    assert "impression_en" in cr_normal
    assert "impression_ja" in cr_normal


def test_hemorrhagic_stroke_ct_head_abnormal_only():
    """Hemorrhagic stroke = always abnormal (any: 1.0); normal template optional."""
    t = load_impression_templates()
    hs = t["hemorrhagic_stroke"]
    assert "CT_head" in hs
    assert "abnormal" in hs["CT_head"]
