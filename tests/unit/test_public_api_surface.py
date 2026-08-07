"""Locks the pinned OSS public API surface exposed by :mod:`clinosim.api`
(Issue #554). Any change to ``__all__`` must land in this test in the same
commit so a reviewer sees the effect on the OSS-stable surface at a glance.

Removals require a MAJOR version bump per the stability contract described in
``clinosim/api.py``. Additions require only a MINOR bump.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


EXPECTED_PUBLIC_SURFACE: frozenset[str] = frozenset(
    {
        "__version__",
        # Simulation
        "run_alpha",
        "run_beta",
        "run_forced",
        # Configuration
        "SimulatorConfig",
        # Output adapter registry
        "available_formats",
        "register_output_adapter",
        # FHIR R4
        "available_builders",
        "convert_cif_to_fhir",
        "register_bundle_builder",
    }
)


def test_public_api_matches_expected_surface():
    """`clinosim.api.__all__` must equal :data:`EXPECTED_PUBLIC_SURFACE`.

    A diff means either a MAJOR bump (removal) or a MINOR bump (addition) is
    warranted. Update ``EXPECTED_PUBLIC_SURFACE`` in the same PR and note the
    change in ``CHANGELOG.md``.
    """
    import clinosim.api

    actual = frozenset(clinosim.api.__all__)
    assert actual == EXPECTED_PUBLIC_SURFACE, (
        f"clinosim.api.__all__ diverged from EXPECTED_PUBLIC_SURFACE.\n"
        f"  added: {actual - EXPECTED_PUBLIC_SURFACE}\n"
        f"  removed: {EXPECTED_PUBLIC_SURFACE - actual}"
    )


def test_every_public_name_is_actually_importable():
    """Every name in ``clinosim.api.__all__`` must resolve as an attribute."""
    import clinosim.api

    for name in clinosim.api.__all__:
        assert hasattr(clinosim.api, name), f"clinosim.api.{name} missing at runtime"


def test_top_level_clinosim_declares_public_all():
    """The top-level ``clinosim`` package advertises ``__version__`` only.

    The wider public surface lives under ``clinosim.api`` — the top-level
    package intentionally exposes just the version so `import clinosim` stays
    cheap and does not eagerly import every heavy submodule.
    """
    import clinosim

    assert clinosim.__all__ == ["__version__"]
    assert isinstance(clinosim.__version__, str)
    assert clinosim.__version__.count(".") == 2  # SemVer MAJOR.MINOR.PATCH


def test_underscore_symbols_are_not_re_exported():
    """No underscore-prefixed symbol should leak into the pinned public API."""
    import clinosim.api

    for name in clinosim.api.__all__:
        assert not name.startswith("_") or name == "__version__", (
            f"clinosim.api.{name} looks internal but is exported publicly"
        )
