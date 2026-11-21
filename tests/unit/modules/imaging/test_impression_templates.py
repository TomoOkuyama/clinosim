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
    # Language maps (Issue #2505).
    assert set(cr_normal["findings"]) >= {"en", "ja"}
    assert set(cr_normal["impression"]) >= {"en", "ja"}


def test_hemorrhagic_stroke_ct_head_abnormal_only():
    """Hemorrhagic stroke = always abnormal (any: 1.0); normal template optional."""
    t = load_impression_templates()
    hs = t["hemorrhagic_stroke"]
    assert "CT_head" in hs
    assert "abnormal" in hs["CT_head"]


def _ja_texts(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "ja" and isinstance(v, str):
                yield v
            else:
                yield from _ja_texts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _ja_texts(v)


def test_ja_impressions_avoid_literal_translations_3477():
    """'Lungs clear' must read as radiology Japanese, not word-by-word."""
    deny = ("両肺野明らか", "全区分静脈圧迫良好")
    texts = list(_ja_texts(load_impression_templates()))
    assert texts
    bad = sorted({t for t in texts for d in deny if d in t})
    assert not bad, bad
    assert any("両肺野に異常陰影なし、心陰影正常。" == t for t in texts)
