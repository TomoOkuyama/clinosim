"""Shared JP-CLINS lab coding package loader — pure SD/CS runtime view.

Extracts JP_Observation_LabResult_eCS slice information (from the SD)
and joins it with 17-digit codes (from CoreLabo / InfectionLabo
CodeSystems) at runtime. **All data returned by this loader is derived
strictly from the installed JP-CLINS package** — no clinosim-side
mapping, no bundled extract. The installed pkg is the single source of
truth; a committed extract would drift from pkg updates and would cause
downstream axes to measure clinosim's snapshot instead of the actual
spec. (The pkg license itself is CC0-1.0 per its ``package.json.license``
field, verified 2026-07-27; runtime-extract is driven by the drift
concern, not by license. Hotfix PR #394 originally cited CC BY-ND;
the license claim is corrected here, and the runtime-extract mechanic
remains valid regardless.)

Consumers:
- ``clinosim.eval.axes.jp_clins_lab_compliance`` (axis) — uses
  ``all_slices_by_system_display()`` to check emitted display against
  the SD's Fixed value set.
- ``clinosim.modules.output.fhir_r4.labs.coding_strategy`` (PR 3 CoreLabo /
  Uncoded emission) — will use ``slice_info(slice_name)`` to get the
  slice's Fixed display, VS URL, and the list of 17-digit code
  candidates with segment decomposition (5/4/3/3/2) for
  ``996``-preferred selection + specimen back-derivation.

License / responsibility boundary:
- **Loader = pure SD/CS view.** Never carries clinosim-side mappings.
- **clinosim-side ``analyte name → slice_name``** lives in
  ``_lab_coding_strategy._slice_name_for_analyte`` (PR 3), which
  builds a small mapping table (clinosim IP, commit-safe).

Universal join key:
- SD provides ``(slice_name, system_uri, Fixed_display, VS_url)``.
- CS provides ``(17-digit code, display, segments, designation_ja)``.
- The join key is ``(system_uri, display)`` — this is the same
  discriminator the eCS profile's Open slicing uses (``value:system``
  + ``value:display``), so uniqueness is guaranteed by the profile
  itself. CS parent codes are NOT a reliable join key: e.g. SD slice
  ``abo-bld`` maps to CS parent ``BLD-ABO`` (letter reversal), SD
  ``u-ac`` maps to CS parent ``U-A/C`` (contains slash).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

_ECS_SD_FILENAME = "StructureDefinition-JP-Observation-LabResult-eCS.json"
_CORELABO_JLAC10_CS_FILENAME = "CodeSystem-jp-clins-codesystem-jlac10-corelabo-cs.json"
_CORELABO_JLAC11_CS_FILENAME = "CodeSystem-jp-clins-codesystem-jlac11-corelabo-cs.json"
_INFECTIONLABO_JLAC10_CS_FILENAME = "CodeSystem-jp-clins-codesystem-jlac10-infectionlabo-cs.json"
_INFECTIONLABO_JLAC11_CS_FILENAME = "CodeSystem-jp-clins-codesystem-jlac11-infectionlabo-cs.json"

_JP_CLINS_PKG_ID = "clinical-information-sharing"
_JP_CLINS_PKG_VERSION = "1.12.0"
_JP_CLINS_TERMINOLOGY_PKG_ID = "jpfhir-terminology"
_JP_CLINS_TERMINOLOGY_PKG_VERSION = "2.2606.0"

_ENV_PKG_DIR = "CLINOSIM_JP_CLINS_PKG_DIR"

# Uncoded slice constants — from SD extraction, pinned as literals so
# the Uncoded emission does not require a runtime SD read for these
# single-value fields (the SD does carry them as Fixed values on the
# unCoded slice's system / code / display sub-elements). This is a
# de-minimis copy of publicly published FHIR spec constants (spec
# values, not clinosim IP), used to construct the Uncoded slice info
# when the SD is loaded — never as a bundled fallback substitute for
# the SD.
_UNCODED_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_Uncoded_CS"
_UNCODED_CODE = "99999999999999999"
_UNCODED_DISPLAY = "未標準化コード項目(JLAC)"

_LOCALCODE_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_ObsLabResult_LocalCode_CS"

# --------------------------------------------------------------------------- #
# JP-CLINS lab CS URI canonical registry — single source of truth.
#
# Owned here (not in the axis) so that adding a new JP-CLINS-defined
# lab CS URI is a one-line change consumed by every reader. Emission
# side (``_lab_coding_strategy``) does NOT read these — it obtains the
# correct URI dynamically via ``slice_info(slice_name).slice_system`` /
# ``localcode_system_uri()`` / ``uncoded_slice().slice_system`` (SD
# fixedUri driven). The axis (``eval.axes.jp_clins_lab_compliance``)
# reads these via the accessors below to keep the pre-migration set
# comparable at axis load time even when the pkg is missing (Metric 1
# / Metric 2 need a static set to compare emitted ``coding.system``
# against; deriving from SD would collapse the axis to N/A when the
# pkg is not installed, breaking the "0/0/0 pre-migration baseline vs
# 100% post-migration" distinction the axis docstring guarantees).

_CORELABO_JLAC10_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_CoreLabo_CS"
_CORELABO_JLAC11_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC11/JP_CLINS_ObsLabResult_CoreLabo_CS"
_INFECTIONLABO_JLAC10_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC10/JP_CLINS_ObsLabResult_InfectionLabo_CS"
_INFECTIONLABO_JLAC11_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/JLAC11/JP_CLINS_ObsLabResult_InfectionLabo_CS"
# Generic JLAC10 17-digit CodeSystem published by MEDIS. Not a
# JP-CLINS-authored CS but recognized by JP-CLINS as an acceptable
# ``coding.system`` for the jlac10LaboCode slice. Kept in the defined
# set so the axis's Metric 1 numerator matches this URI as well.
_JLAC10_GENERIC_SYSTEM = "http://medis.or.jp/CodeSystem/master-JLAC10-17digits"

# Full JP-CLINS-defined lab CS URI set (7 URIs) — axis Metric 1
# (CS 使用率) numerator match.
_JP_CLINS_DEFINED_SYSTEM_URIS: frozenset[str] = frozenset(
    {
        _CORELABO_JLAC10_SYSTEM,
        _CORELABO_JLAC11_SYSTEM,
        _INFECTIONLABO_JLAC10_SYSTEM,
        _INFECTIONLABO_JLAC11_SYSTEM,
        _UNCODED_SYSTEM,
        _LOCALCODE_SYSTEM,
        _JLAC10_GENERIC_SYSTEM,
    }
)

# Subset (5 URIs) that carries an SD Fixed-display constraint. Open
# slicing discriminator = system + display. LocalCode + jlac10LaboCode
# (MEDIS generic) do NOT have Fixed displays — they are permitted to
# carry site-local / analyte display text and are therefore excluded
# from the Fixed-display metric.
_FIXED_DISPLAY_SYSTEM_URIS: frozenset[str] = frozenset(
    {
        _CORELABO_JLAC10_SYSTEM,
        _CORELABO_JLAC11_SYSTEM,
        _INFECTIONLABO_JLAC10_SYSTEM,
        _INFECTIONLABO_JLAC11_SYSTEM,
        _UNCODED_SYSTEM,
    }
)


def jp_clins_defined_system_uris() -> frozenset[str]:
    """Return the canonical JP-CLINS-defined lab CS URI set (7 URIs).

    Consumed by ``eval.axes.jp_clins_lab_compliance`` Metric 1
    (CS 使用率). Emission-side callers MUST NOT use this — they get the
    correct URI via ``slice_info(slice_name).slice_system`` /
    ``localcode_system_uri()`` / ``uncoded_slice().slice_system`` so the
    emission path stays SD-driven and cannot drift from the SD.
    """
    return _JP_CLINS_DEFINED_SYSTEM_URIS


def jp_clins_fixed_display_system_uris() -> frozenset[str]:
    """Return the JP-CLINS lab CS URI subset (5 URIs) that carries an
    SD Fixed-display constraint.

    LocalCode + jlac10LaboCode (MEDIS generic URI) are excluded — their
    ``coding.display`` is permitted to carry site-local / analyte text,
    not the SD's Fixed value. Consumed by axis Metric 2 to bound the
    denominator to slice-typed codings.
    """
    return _FIXED_DISPLAY_SYSTEM_URIS


def jp_clins_localcode_system_uri() -> str:
    """Return the JP-CLINS LocalCode slice CS URI.

    Available regardless of pkg presence (spec-published constant, same
    literal as ``MissingPackage.localcode_system_uri()`` and
    ``EcsRuntimePackage.localcode_system_uri()``). Consumed by axis
    Metric 3 for LocalCode presence checking.
    """
    return _LOCALCODE_SYSTEM


# Specimen material CodeSystem (JLAC10) — spec verification
# (2026-07-26): 17-digit CoreLabo code's material segment (10-12桁目, e.g.
# "023") maps 1-1 to JP_ObservationSampleMaterialCodeJLAC10_CS codes
# (verified: 129 top + 57 nested + 1 depth-2 = 187 codes, all 9 material
# segments used by CoreLabo analytes resolve to CS displays 尿/全血/血清 etc).
# NO translation table needed — the material segment IS the specimen CS code.
_SPECIMEN_MATERIAL_CS_FILENAME = "CodeSystem-jp-observationsamplematerialcodejlac10-cs.json"
_SPECIMEN_MATERIAL_CS_URI = "http://jpfhir.jp/fhir/core/CodeSystem/JP_ObservationSampleMaterialCodeJLAC10_CS"


# --------------------------------------------------------------------------- #
# Types.


@dataclass(frozen=True)
class CodeSegments:
    """17-digit JLAC10 code boundary decomposition — 5 / 4 / 3 / 3 / 2.

    Example: ``3H015000002399801`` for K, material 023, method 998:
      ``analyte='3H015'``, ``identifier='0000'``, ``material='023'``,
      ``method='998'``, ``result_id='01'``.

    Method values pinned in the CoreLabo CS: ``998`` = method-agnostic
    (memo §H.3 rev: **preferred** — synthetic data does not
    simulate specific measurement methods, so 998 is the most honest
    selection); ``999`` = other; else a specific method (e.g. ``261``
    = potentiometry). Material segment is used by PR 3 to back-derive
    ``Observation.specimen.contained JP_Specimen.type`` from the code.
    """

    analyte: str
    identifier: str
    material: str
    method: str
    result_id: str

    @classmethod
    def from_code(cls, code: str) -> CodeSegments:
        assert len(code) == 17, f"expected 17-digit JLAC10 code, got {len(code)}: {code!r}"
        return cls(code[0:5], code[5:9], code[9:12], code[12:15], code[15:17])


@dataclass(frozen=True)
class LabCodeCandidate:
    """A single CoreLabo / InfectionLabo 17-digit concept.

    ``designation_ja`` is the **raw** Japanese designation from the CS
    ``concept.designation[language=ja].value``. It is intentionally
    NOT sanitized here (LocalCode display sanitization — whitespace
    strip per JP-CLINS spec — is a PR 3 emission-side concern; loader
    supplying raw preserves ``code.text`` fidelity, which permits
    whitespace).

    IMPORTANT display-usage boundary:
    - **CoreLabo/InfectionLabo slice ``coding.display``** MUST use
      ``LabSliceInfo.fixed_display`` (SD Fixed value, e.g. ``K``,
      ``WBC``, ``血液型-ABO``). ``designation_ja`` MUST NOT be used
      here — the slice discriminator is ``value:display``, and any
      non-Fixed display silently mis-matches → Tier 2 silent
      non-compliance (workspace:5 Gate 2 measurement).
    - **LocalCode slice ``coding.display``** MAY use ``designation_ja``
      after PR 3 whitespace sanitize.
    - **``code.text``** MAY use raw ``designation_ja`` (whitespace
      permitted per JP-CLINS spec).
    """

    code: str
    designation_ja: str | None
    segments: CodeSegments


@dataclass(frozen=True)
class LabSliceInfo:
    """SD + CS merged view for a single JP-CLINS lab slice.

    - ``slice_name``: SD-native identifier (e.g. ``coreLaboJLAC10/k``).
    - ``slice_system``: SD ``.system.fixedUri`` for the slice.
    - ``fixed_display``: SD ``.display.fixedString`` — the Fixed value
      that the slice's discriminator matches on. Callers MUST use this
      verbatim in ``coding.display`` for slice-compliant emit.
    - ``value_set_url``: SD ``.code.binding.valueSet`` **verbatim** —
      NOT mangled. If the SD carries the version suffix (``|1.1.0a``)
      it is preserved as-is; if not, it is preserved as-is. Loader
      never adds or strips a version segment (memo: version
      mismatch on ``$expand`` breaks binding resolution — SD is the
      single source of truth for the reference string).
    - ``codes``: joined CS concepts with segment decomposition.
      Immutable tuple for cache safety.
    """

    slice_name: str
    slice_system: str
    fixed_display: str
    value_set_url: str
    codes: tuple[LabCodeCandidate, ...]


# --------------------------------------------------------------------------- #
# Package protocol + implementations.


class LabCodingPackage(Protocol):
    """Shared contract consumed by axis + emission strategies."""

    def is_available(self) -> bool: ...

    def slice_info(self, slice_name: str) -> LabSliceInfo | None:
        """Return the SD/CS merged view for the given SD slice_name
        (e.g. ``coreLaboJLAC10/k``). Returns None when the slice is
        not in the SD."""

    def uncoded_slice(self) -> LabSliceInfo:
        """Return the JP-CLINS Uncoded slice info. Available whenever
        ``is_available()`` is True — the Uncoded slice's Fixed values
        are pinned to spec-published literals so no per-analyte CS
        lookup is required."""

    def all_slices_by_system_display(self) -> dict[tuple[str, str], str]:
        """``(system_uri, display) → slice_name`` pivot. axis Metric 2
        uses this to check ``coding.display`` against the SD's Fixed
        value set."""

    def localcode_system_uri(self) -> str:
        """LocalCode slice system URI, for PR 3 co-emission."""

    def specimen_material_cs_uri(self) -> str:
        """JLAC10 specimen material CodeSystem URI for
        ``Observation.specimen.contained JP_Specimen.type.coding`` +
        alignment verification against ``CoreLabo code.material segment``.
        Available even when pkg is missing (spec-published constant)."""

    def specimen_material_display(self, material_code: str) -> str | None:
        """Look up specimen material display (e.g. "023" → "血清") from
        the JLAC10 specimen material CS. Returns ``None`` if the pkg
        is unavailable or the material code is unknown."""


class MissingPackage:
    """Pkg-absent state — every method returns a no-op sentinel.

    axis surfaces ``Outcome.NA``; emission path in PR 1..2 does not
    call this loader (LegacyJSLM / LegacyLOINC strategies are
    pkg-independent by design)."""

    def is_available(self) -> bool:
        return False

    def slice_info(self, slice_name: str) -> LabSliceInfo | None:
        return None

    def uncoded_slice(self) -> LabSliceInfo:
        raise RuntimeError(
            "JP-CLINS pkg not installed — uncoded_slice not available. Install "
            f"'{_JP_CLINS_PKG_ID}#{_JP_CLINS_PKG_VERSION}' via the fhir CLI or "
            f"set ${_ENV_PKG_DIR}."
        )

    def all_slices_by_system_display(self) -> dict[tuple[str, str], str]:
        return {}

    def localcode_system_uri(self) -> str:
        return _LOCALCODE_SYSTEM

    def specimen_material_cs_uri(self) -> str:
        # Spec-published constant, safe to return even in pkg-absent state.
        return _SPECIMEN_MATERIAL_CS_URI

    def specimen_material_display(self, material_code: str) -> str | None:
        return None


class EcsRuntimePackage:
    """Runtime-parsed JP-CLINS eCS package.

    Constructed with paths to the SD JSON + the four CS JSONs
    (CoreLabo JLAC10/JLAC11 + InfectionLabo JLAC10/JLAC11). Parses
    lazily on first access via cached properties."""

    def __init__(
        self,
        sd_path: Path,
        corelabo_jlac10_cs_path: Path,
        corelabo_jlac11_cs_path: Path | None,
        infectionlabo_jlac10_cs_path: Path | None,
        infectionlabo_jlac11_cs_path: Path | None,
        specimen_material_cs_path: Path | None = None,
    ) -> None:
        self._sd_path = sd_path
        self._cs_paths = [
            corelabo_jlac10_cs_path,
            corelabo_jlac11_cs_path,
            infectionlabo_jlac10_cs_path,
            infectionlabo_jlac11_cs_path,
        ]
        self._specimen_material_cs_path = specimen_material_cs_path
        self._slices_by_name: dict[str, LabSliceInfo] | None = None
        self._by_system_display: dict[tuple[str, str], str] | None = None
        self._specimen_material_map: dict[str, str] | None = None

    def is_available(self) -> bool:
        return True

    def _ensure_loaded(self) -> None:
        if self._slices_by_name is not None:
            return
        # 1. Parse SD for slice info (name → system, fixed_display, VS URL)
        sd = json.loads(self._sd_path.read_text(encoding="utf-8"))
        sd_by_name: dict[str, dict[str, str]] = {}
        for el in sd.get("differential", {}).get("element", []):
            eid = el.get("id", "")
            if not eid.startswith("Observation.code.coding:"):
                continue
            rest = eid[len("Observation.code.coding:") :]
            if "." in rest:
                slice_name, sub = rest.split(".", 1)
            else:
                slice_name, sub = rest, ""
            entry = sd_by_name.setdefault(slice_name, {})
            if sub == "system" and el.get("fixedUri"):
                entry["system"] = el["fixedUri"]
            elif sub == "display" and el.get("fixedString"):
                entry["display"] = el["fixedString"]
            elif sub == "code" and el.get("binding", {}).get("valueSet"):
                # SD value_set reference — verbatim, no version mangling.
                entry["value_set"] = el["binding"]["valueSet"]
        # 2. Parse CS(es) for leaf codes with segments + designation_ja
        # Join key: (system_uri, display) → list of LabCodeCandidate
        codes_by_key: dict[tuple[str, str], list[LabCodeCandidate]] = {}
        for cs_path in self._cs_paths:
            if cs_path is None or not cs_path.exists():
                continue
            cs = json.loads(cs_path.read_text(encoding="utf-8"))
            system_uri = cs.get("url", "")

            def _walk(concepts: list[dict]) -> None:
                for c in concepts or []:
                    children = c.get("concept", [])
                    if children:
                        _walk(children)
                        continue
                    code = c.get("code", "")
                    display = c.get("display", "")
                    if not code or not display or len(code) != 17:
                        continue
                    designation_ja: str | None = None
                    for dg in c.get("designation", []):
                        if dg.get("language") == "ja":
                            designation_ja = dg.get("value")
                            break
                    try:
                        segments = CodeSegments.from_code(code)
                    except AssertionError:
                        continue
                    key = (system_uri, display)
                    codes_by_key.setdefault(key, []).append(
                        LabCodeCandidate(code=code, designation_ja=designation_ja, segments=segments)
                    )

            _walk(cs.get("concept", []))
        # 3. Merge SD slice info with CS codes via (system, display) join.
        slices_by_name: dict[str, LabSliceInfo] = {}
        by_system_display: dict[tuple[str, str], str] = {}
        for slice_name, meta in sd_by_name.items():
            system = meta.get("system", "")
            display = meta.get("display", "")
            if not system or not display:
                continue
            vs_url = meta.get("value_set", "")
            key = (system, display)
            codes = tuple(codes_by_key.get(key, ()))
            slices_by_name[slice_name] = LabSliceInfo(
                slice_name=slice_name,
                slice_system=system,
                fixed_display=display,
                value_set_url=vs_url,
                codes=codes,
            )
            by_system_display[key] = slice_name
        self._slices_by_name = slices_by_name
        self._by_system_display = by_system_display

    def slice_info(self, slice_name: str) -> LabSliceInfo | None:
        self._ensure_loaded()
        assert self._slices_by_name is not None  # for mypy
        return self._slices_by_name.get(slice_name)

    def uncoded_slice(self) -> LabSliceInfo:
        self._ensure_loaded()
        # Uncoded is one concept, pinned by spec; construct directly.
        segments = CodeSegments.from_code(_UNCODED_CODE)
        candidate = LabCodeCandidate(code=_UNCODED_CODE, designation_ja=_UNCODED_DISPLAY, segments=segments)
        return LabSliceInfo(
            slice_name="unCoded",
            slice_system=_UNCODED_SYSTEM,
            fixed_display=_UNCODED_DISPLAY,
            value_set_url="",  # SD has no VS binding on the unCoded slice
            codes=(candidate,),
        )

    def all_slices_by_system_display(self) -> dict[tuple[str, str], str]:
        self._ensure_loaded()
        assert self._by_system_display is not None
        return self._by_system_display

    def localcode_system_uri(self) -> str:
        return _LOCALCODE_SYSTEM

    def specimen_material_cs_uri(self) -> str:
        return _SPECIMEN_MATERIAL_CS_URI

    def specimen_material_display(self, material_code: str) -> str | None:
        """Look up specimen material code (e.g. "023") → display (e.g. "血清").

        Traverses the JLAC10 specimen material CS's 3-level hierarchy
        (129 top + 57 depth-1 + 1 depth-2 = 187 codes). Returns None if
        the code is not present or the CS file is unavailable.
        """
        self._ensure_specimen_material_loaded()
        assert self._specimen_material_map is not None
        return self._specimen_material_map.get(material_code)

    def _ensure_specimen_material_loaded(self) -> None:
        if self._specimen_material_map is not None:
            return
        out: dict[str, str] = {}
        if self._specimen_material_cs_path is not None and self._specimen_material_cs_path.exists():
            cs = json.loads(self._specimen_material_cs_path.read_text(encoding="utf-8"))

            def _walk(concepts: list[dict]) -> None:
                for c in concepts or []:
                    code = c.get("code", "")
                    display = c.get("display", "")
                    if code and display:
                        out[code] = display
                    _walk(c.get("concept", []))

            _walk(cs.get("concept", []))
        self._specimen_material_map = out


# --------------------------------------------------------------------------- #
# Package discovery.


def _find_pkg_files() -> tuple[Path, Path, Path | None, Path | None, Path | None, Path | None] | None:
    """Locate the SD + 4 CS JSONs + specimen material CS on disk.

    Search order (matches axis's pre-migration ``_find_ecs_sd_path``):
    1. ``$CLINOSIM_JP_CLINS_PKG_DIR`` — explicit override for the
       ``package/`` directory of the JP-CLINS clinical-information-sharing pkg.
    2. Standard ``fhir`` CLI cache under ``~/.fhir/packages/`` for both
       clinical-information-sharing (SD) and jpfhir-terminology (CS).
    3. Sibling ``../fhir-jp-validator`` dev fallback.

    Returns ``(sd_path, corelabo_jlac10_cs, corelabo_jlac11_cs,
    infectionlabo_jlac10_cs, infectionlabo_jlac11_cs, specimen_material_cs)``
    or None. CS paths may be None if that particular CS is unavailable —
    the loader gracefully degrades (fewer codes joined, but SD slices are
    still enumerated for axis Metric 1 / Metric 3)."""

    def _first_existing(*candidates: Path) -> Path | None:
        for c in candidates:
            if c.exists():
                return c
        return None

    # Candidate SD locations
    sd_candidates: list[Path] = []
    if env_val := os.environ.get(_ENV_PKG_DIR):
        sd_candidates.append(Path(env_val) / _ECS_SD_FILENAME)
    home_cache = Path.home() / ".fhir" / "packages"
    for sep in ("#", "-"):
        sd_candidates.append(
            home_cache / f"{_JP_CLINS_PKG_ID}{sep}{_JP_CLINS_PKG_VERSION}" / "package" / _ECS_SD_FILENAME
        )
    # PR2 (Issue #555): file moved from output/lab_coding_package.py to
    # output/fhir_r4/labs/coding_package.py (2 layers deeper) — parent depth
    # adjusted from 3 to 5 so repo_root still resolves to the workspace root
    # containing the sibling fhir-jp-validator/ checkout.
    repo_root = Path(__file__).resolve().parents[5]
    dev_root = repo_root.parent / "fhir-jp-validator" / "tx-server-build" / "terminology" / "fhir-server"
    sd_candidates.append(dev_root / f"{_JP_CLINS_PKG_ID}#{_JP_CLINS_PKG_VERSION}" / "package" / _ECS_SD_FILENAME)
    sd_path = _first_existing(*sd_candidates)
    if sd_path is None:
        return None

    # CS locations — jpfhir-terminology pkg
    cs_search_dirs: list[Path] = []
    if env_val := os.environ.get(_ENV_PKG_DIR):
        # env override may point at a bundle including CS
        cs_search_dirs.append(Path(env_val))
    for sep in ("#", "-"):
        cs_search_dirs.append(
            home_cache / f"{_JP_CLINS_TERMINOLOGY_PKG_ID}{sep}{_JP_CLINS_TERMINOLOGY_PKG_VERSION}" / "package"
        )
    cs_search_dirs.append(dev_root / f"{_JP_CLINS_TERMINOLOGY_PKG_ID}#{_JP_CLINS_TERMINOLOGY_PKG_VERSION}" / "package")

    def _find_cs(filename: str) -> Path | None:
        for d in cs_search_dirs:
            candidate = d / filename
            if candidate.exists():
                return candidate
        return None

    return (
        sd_path,
        _find_cs(_CORELABO_JLAC10_CS_FILENAME) or Path("<missing>"),
        _find_cs(_CORELABO_JLAC11_CS_FILENAME),
        _find_cs(_INFECTIONLABO_JLAC10_CS_FILENAME),
        _find_cs(_INFECTIONLABO_JLAC11_CS_FILENAME),
        _find_cs(_SPECIMEN_MATERIAL_CS_FILENAME),
    )


@lru_cache(maxsize=1)
def load_lab_coding_package() -> LabCodingPackage:
    """Return the shared package. Cached — call any number of times.

    Returns ``MissingPackage`` when the SD cannot be found; callers
    check ``is_available()`` or handle ``None`` from ``slice_info``.
    """
    found = _find_pkg_files()
    if found is None:
        return MissingPackage()
    sd_path, corelabo10, corelabo11, infection10, infection11, specimen_mat = found
    if not corelabo10.exists():
        # CoreLabo JLAC10 CS is required for CoreLabo emissions; without
        # it the package can still serve SD-only queries (axis Metric 1 /
        # 3) but not slice code lookups. Keep the package available but
        # note that slice_info(coreLabo…) will return LabSliceInfo with
        # empty codes tuple.
        corelabo10 = Path("<missing>")
    return EcsRuntimePackage(
        sd_path=sd_path,
        corelabo_jlac10_cs_path=corelabo10 if corelabo10.name != "<missing>" else Path("/nonexistent"),
        corelabo_jlac11_cs_path=corelabo11,
        infectionlabo_jlac10_cs_path=infection10,
        infectionlabo_jlac11_cs_path=infection11,
        specimen_material_cs_path=specimen_mat,
    )
