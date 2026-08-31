"""Strip forbidden / mismatched coding fragments.

Extracted from ``_fhir_post_process.py`` (Issue #555 PR3, folds Issue #556).

Two independent scrub passes:

- ``_strip_forbidden_observation_reference_range_extensions`` — remove
  extensions from ``Observation.referenceRange[*]`` paths that
  ``JP_Observation_LabResult_eCS`` locks to ``max=0``.
- ``_strip_japanese_display_on_english_only_systems`` — remove ``display``
  from ``Coding`` entries on English-only CodeSystems when the display
  contains Japanese characters (HAPI Validator "Wrong Display Name"
  regression defense; the CodeableConcept-level ``text`` field survives).
"""

from __future__ import annotations

from typing import Any


def _strip_forbidden_observation_reference_range_extensions(resource: dict) -> None:
    """Remove `extension` / `modifierExtension` from every
    `Observation.referenceRange[*]` (and `.low` / `.high`, plus
    `Observation.component[*].referenceRange[*]` mirrored paths).

    Rationale:

    - `JP_Observation_LabResult_eCS` (JP-CLINS 1.13.0) locks
      `Observation.referenceRange.extension` (and `modifierExtension`,
      `low.extension`, `high.extension`) to `max=0`; the same lock
      applies to `component[*].referenceRange.*`. Any extension emitted
      on these paths violates the profile, regardless of URL.
    - clinosim previously emitted a `referenceRangeSource` extension
      whose URL was not registered anywhere in the JP-CLINS 1.13.0 /
      jp-core 1.2.0 / jpfhir-terminology 2.2606.0 packages
      (fhir-jp-validator 2026-07-17 §【最優先 2】surfaced 31,006
      errors from this). The emit site in `_fhir_common.build_reference_range`
      no longer writes it, but this walker is the second layer of the
      silent-no-op defense: any cached CIF re-exported after the fix,
      or a hypothetical future builder that reintroduces a sub-extension,
      would still be scrubbed.

    Universal (US Observation also benefits — the extension was already
    JP-gated, but stripping is a no-op on non-existent fields).
    Idempotent.
    """
    if resource.get("resourceType") != "Observation":
        return

    def _scrub(rrs: Any) -> None:
        if not isinstance(rrs, list):
            return
        for rr in rrs:
            if not isinstance(rr, dict):
                continue
            rr.pop("extension", None)
            rr.pop("modifierExtension", None)
            for side in ("low", "high"):
                sub = rr.get(side)
                if isinstance(sub, dict):
                    sub.pop("extension", None)
                    sub.pop("modifierExtension", None)

    _scrub(resource.get("referenceRange"))
    for comp in resource.get("component") or []:
        if isinstance(comp, dict):
            _scrub(comp.get("referenceRange"))


# iris4h-ai feedback V4/V5 P2 A: display 省略対象の「英語 display のみ」
# CodeSystem prefix 一覧。ここに含まれる system の Coding.display に日本語
# 文字が入っていた場合、post-emit walker が display を削除する。
# 出典:各 CodeSystem 公式定義(LOINC.org / SNOMED International /
# HL7 terminology / DICOM / UCUM / HL7 FHIR sid)は英語 display のみ定義
# しており、日本語文字を含む display は HAPI Validator に「Wrong Display
# Name」として rejected される。
#
# JP-specific CodeSystem(JP Core / JP-CLINS / MEDIS HOT / YJ code /
# clinosim custom)は本 prefix に含まれず、日本語 display が preserve される。
_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES: tuple[str, ...] = (
    "http://loinc.org",
    "http://snomed.info/sct",
    "http://terminology.hl7.org/",
    "http://hl7.org/fhir/",
    "http://dicom.nema.org/",
    "http://unitsofmeasure.org",
)


def _contains_japanese_char(text: str) -> bool:
    """Return True if `text` contains at least one CJK Unified Ideograph /
    Hiragana / Katakana / halfwidth-fullwidth character.

    ASCII-only strings return False, so display fields that already carry a
    valid English label are left untouched by the P2 A walker.
    """
    for ch in text:
        cp = ord(ch)
        if (
            0x3040 <= cp <= 0x309F  # Hiragana
            or 0x30A0 <= cp <= 0x30FF  # Katakana
            or 0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
            or 0xFF00 <= cp <= 0xFFEF  # Halfwidth and Fullwidth Forms
        ):
            return True
    return False


def _strip_japanese_display_on_english_only_systems(node: Any) -> None:
    """Recursively drop `display` from Coding entries on English-only
    CodeSystems when the display contains Japanese characters.

    Called only on JP output. Duck-types Coding via `system` + `code` +
    `display` all being non-empty strings; matches both
    `CodeableConcept.coding[]` entries and Coding-typed fields
    (e.g. `ImagingStudy.series[].modality`). The enclosing
    CodeableConcept's `text` field is not touched, so the Japanese
    human-readable label survives there.

    Non-standard CodeSystem URIs (JP Core CS / JP-CLINS CS / MEDIS HOT /
    YJ code / clinosim custom) are outside the prefix allowlist and are
    preserved as-is.

    Idempotent — re-running on already-normalized data has no effect
    (the walker only touches entries whose `display` still contains
    Japanese characters).
    """
    if isinstance(node, dict):
        sys_ = node.get("system")
        code_ = node.get("code")
        disp = node.get("display")
        if (
            isinstance(sys_, str)
            and isinstance(code_, str)
            and isinstance(disp, str)
            and disp
            and sys_.startswith(_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES)
            and _contains_japanese_char(disp)
        ):
            del node["display"]
        for value in node.values():
            if isinstance(value, (dict, list)):
                _strip_japanese_display_on_english_only_systems(value)
    elif isinstance(node, list):
        for item in node:
            _strip_japanese_display_on_english_only_systems(item)
