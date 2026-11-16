"""Shared fixtures for the longitudinal module tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs


@pytest.fixture(autouse=True)
def _isolate_attribute_spec_cache() -> Iterator[None]:
    """Clear the cached attribute specs before and after every test.

    Many tests here point ``_LONGITUDINAL_DIR`` at substitute YAML; without
    the teardown clear the substitute specs stay cached for whichever test
    the same worker runs next (Issue #3331).
    """
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()
