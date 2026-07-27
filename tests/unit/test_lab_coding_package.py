"""Unit tests for the shared JP-CLINS lab coding package loader.

Pins the pre-cover 11-item contract PR 2 committed to (see PR body /
docs review). The pkg is loaded at runtime (never bundled), so these
tests must run without depending on bundled extracts: anything that
requires the SD is skipped when the pkg is not installed. The pkg
license itself is CC0-1.0 (per ``package.json.license``, verified
2026-07-27); runtime-load is driven by the pkg-updates drift concern,
not by license."""

from __future__ import annotations

import pytest

from clinosim.modules.output.lab_coding_package import (
    CodeSegments,
    LabCodeCandidate,
    LabSliceInfo,
    MissingPackage,
    load_lab_coding_package,
)

# --------------------------------------------------------------------------- #
# CodeSegments — pure logic, no pkg dependency


def test_code_segments_from_code_5_4_3_3_2_boundary():
    """Session 67 memo boundary: 5 (analyte) / 4 (identifier) / 3 (material)
    / 3 (method) / 2 (result id) = 17 digits. Fixed against K analyte
    (session 67 memo example)."""
    seg = CodeSegments.from_code("3H015000002399801")
    assert seg.analyte == "3H015"
    assert seg.identifier == "0000"
    assert seg.material == "023"
    assert seg.method == "998"
    assert seg.result_id == "01"


def test_code_segments_rejects_non_17_digit():
    """The assert catches accidental non-17-digit inputs before they
    propagate to specimen back-derivation logic (PR 3)."""
    with pytest.raises(AssertionError, match="expected 17-digit"):
        CodeSegments.from_code("3H015")


def test_code_segments_glucose_bg_fbg_cbg_identifier_boundary():
    """Session 67 memo boundary verification — glucose 4-digit identifier
    field distinguishes BG (0000) / FBG (1300) / CBG (1299) — proves the
    5/4/3/3/2 boundary against a non-trivial identifier."""
    bg = CodeSegments.from_code("3D010000002327101")  # BG
    fbg = CodeSegments.from_code("3D010130002327101")  # FBG
    cbg = CodeSegments.from_code("3D010129902327101")  # CBG
    assert bg.identifier == "0000"
    assert fbg.identifier == "1300"
    assert cbg.identifier == "1299"
    assert bg.analyte == fbg.analyte == cbg.analyte == "3D010"


# --------------------------------------------------------------------------- #
# MissingPackage — pkg-absent contract


def test_missing_package_is_not_available():
    pkg = MissingPackage()
    assert pkg.is_available() is False


def test_missing_package_slice_info_returns_none():
    """Callers use ``pkg.slice_info(name) is None`` to detect
    slice-not-in-pkg; MissingPackage returns None for every slice_name
    (uniform behavior between "pkg not installed" and "slice not
    defined in a healthy pkg")."""
    pkg = MissingPackage()
    assert pkg.slice_info("coreLaboJLAC10/k") is None
    assert pkg.slice_info("some/nonexistent") is None


def test_missing_package_uncoded_raises_actionable_error():
    """The Uncoded slice is spec-pinned literals, but callers reaching
    for it via MissingPackage indicate that the pipeline expected an
    installed pkg — better to fail loudly than to hand out an
    orphaned literal slice info."""
    pkg = MissingPackage()
    with pytest.raises(RuntimeError, match="pkg not installed"):
        pkg.uncoded_slice()


def test_missing_package_localcode_uri_still_returned():
    """LocalCode system URI is spec-published and does not require a
    pkg install to know; MissingPackage returns it so PR 3 emission
    strategies can co-emit LocalCode slices even when only US path is
    active."""
    pkg = MissingPackage()
    assert "LocalCode" in pkg.localcode_system_uri()


def test_missing_package_all_slices_returns_empty():
    """Axis Metric 2 collapses to N/A when this returns {}."""
    pkg = MissingPackage()
    assert pkg.all_slices_by_system_display() == {}


# --------------------------------------------------------------------------- #
# EcsRuntimePackage — runtime SD/CS parsing (requires installed pkg)


@pytest.fixture
def _pkg_or_skip():
    pkg = load_lab_coding_package()
    if not pkg.is_available():
        pytest.skip("JP-CLINS pkg not installed — skipping runtime SD/CS tests")
    return pkg


def test_pkg_all_slices_count_matches_ecs_sd(_pkg_or_skip):
    """187 slices with Fixed display in eCS 1.12.0 SD:
    55 CoreLabo × 2 (JLAC10 + JLAC11) + 38 InfectionLabo × 2 + Uncoded (1)
    = 110 + 76 + 1 = 187. Locked so a downstream SD version bump
    surfaces as a test regression rather than silent shift."""
    pkg = _pkg_or_skip
    slices = pkg.all_slices_by_system_display()
    assert len(slices) == 187, f"expected 187 slices, got {len(slices)} (SD version may have changed)"


def test_pkg_slice_info_k_has_expected_shape(_pkg_or_skip):
    """K slice = CoreLabo JLAC10 canonical example.

    Fixed display 'K', slice_system is CoreLabo JLAC10 CS URL,
    codes tuple non-empty, all codes have segments and matching
    designation_ja."""
    pkg = _pkg_or_skip
    info = pkg.slice_info("coreLaboJLAC10/k")
    assert info is not None
    assert info.fixed_display == "K"
    assert "JP_CLINS_ObsLabResult_CoreLabo_CS" in info.slice_system
    assert len(info.codes) >= 10, f"K slice should have ~14 codes in CoreLabo 2026.03.31, got {len(info.codes)}"
    # Every code carries a designation_ja + 5/4/3/3/2 segment structure
    for c in info.codes:
        assert c.designation_ja is not None
        assert c.designation_ja == "カリウム(K)", f"unexpected designation: {c.designation_ja!r}"
        assert len(c.code) == 17
        assert c.segments.analyte == "3H015"


def test_pkg_slice_info_k_contains_998_methods(_pkg_or_skip):
    """998-preferred rule (session 67 memo §H.3 rev): the K slice must
    have at least one code with method='998' (method-agnostic) per
    material. PR 3 strategy will filter by this in code selection."""
    pkg = _pkg_or_skip
    info = pkg.slice_info("coreLaboJLAC10/k")
    assert info is not None
    m998 = [c for c in info.codes if c.segments.method == "998"]
    assert len(m998) >= 1, "K slice must have at least one method=998 code"
    # And material=023 with method=998 is the memo's specific example
    assert any(c.segments.material == "023" and c.segments.method == "998" for c in info.codes)


def test_pkg_slice_info_abo_bld_bridges_reversed_cs_parent_code(_pkg_or_skip):
    """SD slice 'abo-bld' maps to CS parent 'BLD-ABO' (letter reversal).
    The loader uses (system, display) as universal join key rather than
    matching CS parent codes, so this cross-name bridge works
    automatically. This test pins that the loader handles the
    non-normalizable SD↔CS naming through (system, display) join."""
    pkg = _pkg_or_skip
    info = pkg.slice_info("coreLaboJLAC10/abo-bld")
    assert info is not None
    assert info.fixed_display == "血液型-ABO"
    assert len(info.codes) > 0, "abo-bld slice must join to BLD-ABO CS parent's codes"


def test_pkg_uncoded_slice_spec_pinned_literals(_pkg_or_skip):
    """Uncoded slice values pinned by spec; even with the SD present,
    the loader returns the same literal shape."""
    pkg = _pkg_or_skip
    info = pkg.uncoded_slice()
    assert info.slice_name == "unCoded"
    assert "Uncoded" in info.slice_system
    assert info.fixed_display == "未標準化コード項目(JLAC)"
    assert len(info.codes) == 1
    assert info.codes[0].code == "99999999999999999"


def test_pkg_value_set_url_preserved_verbatim(_pkg_or_skip):
    """Session 67 memo constraint: SD's binding.valueSet is preserved
    exactly, including any version suffix (``|1.1.0a``). Loader MUST
    NOT add or strip a version segment — SD is the single source of
    truth for the reference string."""
    pkg = _pkg_or_skip
    info = pkg.slice_info("coreLaboJLAC10/k")
    assert info is not None
    # Sample assertion: the URL is non-empty and contains the version
    # suffix as the SD carries it (1.1.0a in eCS 1.12.0).
    assert info.value_set_url != ""
    assert "|1.1.0" in info.value_set_url, (
        "SD carries |1.1.0a suffix; loader must preserve verbatim (session 67 memo constraint)"
    )


# --------------------------------------------------------------------------- #
# Cache / singleton behavior


def test_load_lab_coding_package_is_singleton():
    p1 = load_lab_coding_package()
    p2 = load_lab_coding_package()
    assert p1 is p2, "load_lab_coding_package must return the same instance (lru_cache)"


# --------------------------------------------------------------------------- #
# LabCodeCandidate / LabSliceInfo — immutability


def test_lab_slice_info_is_frozen():
    """cache-safe: callers cannot mutate the returned singleton."""
    info = LabSliceInfo(
        slice_name="test",
        slice_system="urn:test",
        fixed_display="X",
        value_set_url="",
        codes=(
            LabCodeCandidate(
                code="12345678901234567", designation_ja=None, segments=CodeSegments.from_code("12345678901234567")
            ),
        ),
    )
    with pytest.raises(AttributeError):
        info.slice_name = "changed"  # type: ignore[misc]


def test_lab_code_candidate_is_frozen():
    seg = CodeSegments.from_code("12345678901234567")
    cand = LabCodeCandidate(code="12345678901234567", designation_ja="test", segments=seg)
    with pytest.raises(AttributeError):
        cand.code = "changed"  # type: ignore[misc]
