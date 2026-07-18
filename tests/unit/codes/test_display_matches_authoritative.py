"""Cross-check `clinosim/codes/data/*.yaml` displays against authoritative
snapshots in `clinosim/codes/authoritative/`.

This is the 5th layer of the silent-no-op defense (session 58 Phase 1):

1. canonical constants at module level
2. `_validate_*` YAML loader validators (import-time fail-loud)
3. `normalize_probabilities(fallback="raise")`
4. reverse-coverage (forward + staleness)
5. **authoritative cross-check** — curated display vs original terminology
   source, with a documented override allowlist for deliberate clinical
   shorthand.

Fragment-content semantics: snapshots inherit their source CodeSystem's
`content == "fragment"` mode. Codes not present in the snapshot may still be
valid on the tx-server; the test SKIPs them (unable to verify) rather than
FAILing (invalid). See `clinosim/codes/authoritative/README.md`.

Framework template PR ships YJ only; SNOMED / ICD-10 / MEDIS / BCP-47 land
in follow-up PRs by registering their (`data_yaml_name`, `snapshot_file`,
`allowlist_key`) tuples in `_SYSTEMS_UNDER_CROSS_CHECK`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from clinosim.codes.loader import _load_system

pytestmark = pytest.mark.unit


_REPO_ROOT = Path(__file__).resolve().parents[3]
_AUTHORITATIVE_DIR = _REPO_ROOT / "clinosim" / "codes" / "authoritative"
_ALLOWLIST_PATH = Path(__file__).parent / "authoritative_override_allowlist.yaml"


# Systems whose `data/*.yaml` is cross-checked against a snapshot. Extend this
# tuple as each additional code system migrates into the framework (SNOMED,
# ICD-10, MEDIS keyNumber, BCP-47, LOINC).
_SYSTEMS_UNDER_CROSS_CHECK: tuple[dict, ...] = (
    {
        "system_key": "yj",
        "snapshot_file": "yj_tx_fragment.json",
        # Which language field in the clinosim YAML is expected to match the
        # snapshot's `display`. YJ 製剤名 is Japanese only on the tx-server.
        "compare_lang": "ja",
    },
)


def _load_snapshot(filename: str) -> dict[str, Any]:
    path = _AUTHORITATIVE_DIR / filename
    with path.open() as f:
        return json.load(f)


def _load_allowlist() -> dict[str, dict[str, dict[str, Any]]]:
    with _ALLOWLIST_PATH.open() as f:
        loaded = yaml.safe_load(f) or {}
    # Normalise every key to a dict for uniform access.
    return {k: (v or {}) for k, v in loaded.items()}


def _build_authoritative_display_map(snapshot: dict[str, Any]) -> dict[str, set[str]]:
    """`{code: {display + designation values}}` — every allowed spelling per code.

    A curated display matching any of these is treated as authoritative-verified.
    """
    result: dict[str, set[str]] = {}
    for concept in snapshot.get("concept", []):
        code = concept.get("code")
        if not isinstance(code, str):
            continue
        allowed = {concept.get("display")}
        for des in concept.get("designation", []) or []:
            val = des.get("value") if isinstance(des, dict) else None
            if isinstance(val, str) and val:
                allowed.add(val)
        result[code] = {s for s in allowed if isinstance(s, str) and s}
    return result


# ---------------------------------------------------------------------------
# Per-system fixtures + a parametrized sweep over every registered system.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def allowlist() -> dict[str, dict[str, dict[str, Any]]]:
    return _load_allowlist()


@pytest.mark.parametrize("registration", _SYSTEMS_UNDER_CROSS_CHECK)
def test_curated_displays_match_authoritative(registration: dict, allowlist: dict) -> None:
    """Every clinosim code whose entry is present in the authoritative snapshot
    must match the snapshot's display (or a registered synonym / an allowlisted
    override). Codes outside the fragment are treated as unable-to-verify.
    """
    system_key = registration["system_key"]
    compare_lang = registration["compare_lang"]

    snapshot = _load_snapshot(registration["snapshot_file"])
    authoritative = _build_authoritative_display_map(snapshot)
    overrides = allowlist.get(system_key, {}) or {}

    system_data = _load_system(system_key)
    assert system_data is not None, f"code system {system_key!r} not loadable"
    codes = system_data.codes

    verified: list[str] = []
    unverifiable: list[str] = []
    drifted: list[tuple[str, str, set[str]]] = []
    allowlisted: list[str] = []

    for code, translations in codes.items():
        code_str = str(code)
        if code_str not in authoritative:
            unverifiable.append(code_str)
            continue
        curated_display = translations.get(compare_lang) if isinstance(translations, dict) else None
        if not isinstance(curated_display, str) or not curated_display:
            # No display in the target language — nothing to compare; treat as
            # unverifiable (a separate coverage test asserts required-lang presence).
            unverifiable.append(code_str)
            continue
        authoritative_options = authoritative[code_str]
        if curated_display in authoritative_options:
            verified.append(code_str)
            continue
        # Not a direct match — check the override allowlist.
        override = overrides.get(code_str)
        if (
            isinstance(override, dict)
            and override.get("lang") == compare_lang
            and override.get("clinosim_display") == curated_display
            and override.get("rationale")
        ):
            allowlisted.append(code_str)
            continue
        drifted.append((code_str, curated_display, authoritative_options))

    if drifted:
        msg = [
            f"[{system_key}] curated display drift detected against authoritative snapshot "
            f"{registration['snapshot_file']!r}. Update the curated display, or register "
            f"a documented override in tests/unit/codes/authoritative_override_allowlist.yaml.",
        ]
        for code_str, curated, options in drifted:
            options_preview = " | ".join(sorted(options))
            msg.append(f"  {code_str}: curated={curated!r} authoritative={options_preview!r}")
        pytest.fail("\n".join(msg))

    # No drift — smoke output for visibility (verified/allowlisted/unverifiable
    # counts help maintainers see coverage growth across snapshot refreshes).
    print(
        f"\n[{system_key}] verified={len(verified)} allowlisted={len(allowlisted)} "
        f"unverifiable(fragment-missing)={len(unverifiable)}"
    )


def test_allowlist_entries_have_required_fields(allowlist: dict) -> None:
    """Every allowlist entry must carry a clinical rationale — a comment alone
    would not be visible to reviewers checking the CI signal."""
    for system_key, per_system in allowlist.items():
        assert isinstance(per_system, dict), f"{system_key} allowlist must be a mapping"
        for code, entry in per_system.items():
            assert isinstance(entry, dict), f"allowlist[{system_key!r}][{code!r}] must be a mapping"
            for required in ("lang", "clinosim_display", "authoritative_display", "rationale", "registered_at"):
                assert entry.get(required), f"allowlist[{system_key!r}][{code!r}] missing required field {required!r}"


def test_snapshot_metadata_present() -> None:
    """Every snapshot must document its source + fetch date so maintainers can
    reproduce the extraction later."""
    for registration in _SYSTEMS_UNDER_CROSS_CHECK:
        snapshot = _load_snapshot(registration["snapshot_file"])
        meta = snapshot.get("metadata") or {}
        for required in ("source_package", "source_url", "source_file", "extracted_at"):
            assert meta.get(required), f"snapshot {registration['snapshot_file']!r} missing metadata.{required}"
