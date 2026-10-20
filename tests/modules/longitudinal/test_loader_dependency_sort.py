"""`AttributeSpec` loader + DAG topological sort.

The engine executes attributes in dependency order per sim year
(§3.3 of the spec). Order is derived from yaml `depends_on` edges,
not from python registration order — so a cycle is a yaml authoring
error and raises at import.

See Phase 1 plan Task 3 brief + spec §4.2 for schema details.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.modules.longitudinal import loader as loader_mod
from clinosim.modules.longitudinal.loader import (
    AttributeSpec,
    load_attribute_specs,
    topological_order,
)


def _write_yaml(tmp_path: Path, name: str, body: str) -> None:
    """Write one per-attribute yaml into `tmp_path`."""
    (tmp_path / f"{name}.yaml").write_text(body, encoding="utf-8")


_MINIMAL_AR1_BODY = """
pattern: ar1
latent_name: foo
phi: 0.5
sigma: 0.1
mean_reversion_target: 1.0
clamp: [0.0, 10.0]
initial:
  mu: 0.0
  sigma: 0.1
  clamp: [-1.0, 10.0]
"""


@pytest.fixture
def isolated_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the loader from the real repo yaml so each test
    starts with an empty directory and a cleared lru_cache."""
    monkeypatch.setattr(loader_mod, "_LONGITUDINAL_DIR", tmp_path)
    load_attribute_specs.cache_clear()
    return tmp_path


def _write_attribute(dir_: Path, attribute_id: str, depends: list[str]) -> None:
    deps = "[]" if not depends else "[" + ", ".join(repr(d) for d in depends) + "]"
    _write_yaml(
        dir_,
        attribute_id,
        f"""
attribute_id: {attribute_id}
pattern: ar1
depends_on: {deps}
clinical_scope:
  requires_chronic_codes: []
  requires_age_band: [0, 120]
{_MINIMAL_AR1_BODY}
""",
    )


@pytest.mark.unit
def test_topological_order_respects_depends_on(isolated_loader: Path) -> None:
    """`b` depends on `a` ⇒ `a` comes before `b` in the order."""
    _write_attribute(isolated_loader, "a", depends=[])
    _write_attribute(isolated_loader, "b", depends=["a"])
    specs = load_attribute_specs()
    order = topological_order(specs)
    assert order.index("a") < order.index("b")


@pytest.mark.unit
def test_topological_order_cycle_raises(isolated_loader: Path) -> None:
    """`a → b → a` is a cycle; load must raise `ValueError`
    naming the cycle members so the yaml author can fix it."""
    _write_attribute(isolated_loader, "a", depends=["b"])
    _write_attribute(isolated_loader, "b", depends=["a"])
    with pytest.raises(ValueError, match="cycle"):
        specs = load_attribute_specs()
        topological_order(specs)


@pytest.mark.unit
def test_topological_order_missing_dependency_raises(isolated_loader: Path) -> None:
    """A `depends_on: [a]` with no `a` attribute is a yaml bug."""
    _write_attribute(isolated_loader, "b", depends=["a"])
    with pytest.raises(ValueError, match="unknown dependency"):
        specs = load_attribute_specs()
        topological_order(specs)


@pytest.mark.unit
def test_loader_validates_pattern_discriminator(isolated_loader: Path) -> None:
    """`pattern: unknown` must raise naming the valid patterns —
    silent dispatch to a missing handler would be a late-stage
    AttributeError in `advance_one_year`."""
    _write_yaml(
        isolated_loader,
        "bad",
        """
attribute_id: bad
pattern: unknown_pattern
depends_on: []
clinical_scope:
  requires_chronic_codes: []
  requires_age_band: [0, 120]
""",
    )
    with pytest.raises(ValueError, match="unknown_pattern"):
        load_attribute_specs()


@pytest.mark.unit
def test_loader_validates_required_frontmatter_fields(isolated_loader: Path) -> None:
    """A yaml missing `attribute_id` is a schema error — pydantic
    raises before the engine ever sees it."""
    _write_yaml(
        isolated_loader,
        "noid",
        """
pattern: ar1
depends_on: []
clinical_scope:
  requires_chronic_codes: []
  requires_age_band: [0, 120]
""",
    )
    with pytest.raises(ValueError):
        load_attribute_specs()


@pytest.mark.unit
def test_attribute_spec_exposes_pattern_body(isolated_loader: Path) -> None:
    """`AttributeSpec.body` must be the typed pattern-specific
    model (AR1Spec here) so the engine can call pattern functions
    without re-parsing the yaml."""
    _write_attribute(isolated_loader, "a", depends=[])
    specs = load_attribute_specs()
    spec: AttributeSpec = specs["a"]
    assert spec.pattern == "ar1"
    assert spec.body.phi == 0.5
    assert spec.body.sigma == 0.1
