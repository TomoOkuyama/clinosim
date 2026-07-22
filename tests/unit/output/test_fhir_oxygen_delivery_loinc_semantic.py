"""Regression pin for Issue #376: oxygen delivery Observation.component code.

The oxygen-therapy Observation (LOINC 3151-8 "Inhaled oxygen flow rate")
carries a `component[]` with the oxygen delivery device (e.g., "Nasal
cannula") as `valueString`. Pre-fix, the component code was LOINC 8478-0
"Mean blood pressure" — a completely unrelated LOINC, caught by the v24
external-validator obs tx=8181 sanity check as a `Wrong Display Name` error
because the emitted display ("Inhaled oxygen delivery system") did not
match the CodeSystem canonical ("Mean blood pressure").

Root cause: hand-authored code / display mismatch. The correct LOINC for
"device / method by which oxygen is delivered" is `107117-4` "Method of
oxygen delivery" (ACTIVE on tx.fhir.org, verified via NLM Clinical Table
Search + `tx.fhir.org/r4/CodeSystem/$lookup` on 2026-07-23).

This test guards the component code + display against both:
- Regression back to LOINC 8478-0 (the semantic mismatch).
- Any future refactor that silently changes the LOINC without updating
  the display to match the new CodeSystem canonical.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output._fhir_observations import _build_vital_observations

pytestmark = pytest.mark.unit


def _o2_obs_with_device(country: str) -> dict:
    """Return the O2 Observation resource emitted with a device present."""
    entries = _build_vital_observations(
        {
            "on_supplemental_oxygen": True,
            "oxygen_flow_rate_lpm": 2.5,
            "oxygen_delivery_device": "Nasal cannula",
            "timestamp": "2026-01-01T08:00:00",
        },
        patient_id="p1",
        index=0,
        country=country,
    )
    return next(e["resource"] for e in entries if e["resource"]["id"].endswith("-o2"))


def test_oxygen_component_code_is_method_of_oxygen_delivery_jp() -> None:
    """JP output: component[0].code.coding[0] MUST be LOINC 107117-4
    "Method of oxygen delivery" — NOT 8478-0 (which is "Mean blood
    pressure", the pre-Issue-#376 semantic bug)."""
    obs = _o2_obs_with_device("JP")
    comp = obs["component"][0]
    coding = comp["code"]["coding"][0]
    assert coding["system"].endswith("loinc.org")
    assert coding["code"] == "107117-4"
    assert coding["display"] == "Method of oxygen delivery"
    # Device string carried on valueString unchanged.
    assert comp["valueString"] == "Nasal cannula"


def test_oxygen_component_code_is_method_of_oxygen_delivery_us() -> None:
    """US output: same code + display (locale-neutral for this component)."""
    obs = _o2_obs_with_device("US")
    coding = obs["component"][0]["code"]["coding"][0]
    assert coding["code"] == "107117-4"
    assert coding["display"] == "Method of oxygen delivery"


def test_oxygen_component_never_uses_the_old_mean_bp_loinc() -> None:
    """Explicit anti-regression guard: LOINC 8478-0 must NEVER appear on
    the oxygen Observation.component (it is "Mean blood pressure",
    unrelated to oxygen delivery). Guards against a partial revert."""
    for country in ("JP", "US"):
        obs = _o2_obs_with_device(country)
        for comp in obs.get("component", []):
            for coding in comp.get("code", {}).get("coding", []):
                assert coding.get("code") != "8478-0", (
                    f"country={country}: component carries LOINC 8478-0 "
                    f"'Mean blood pressure' — unrelated to oxygen delivery. "
                    f"See Issue #376."
                )
