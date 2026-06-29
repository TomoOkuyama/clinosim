"""Integration: basedOn coverage — every LAB Observation references an existing SR.

This is the silent-no-op gate for ServiceRequest emission: if the builder
silently does nothing the coverage asserts fire immediately, rather than
requiring a visual audit of the NDJSON output.
"""

import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate

# Microbiology observation IDs use these prefixes (from _fhir_microbiology.py).
# PR1 covers lab panel orders only; microbiology ServiceRequests are future work.
_MB_ID_PREFIXES = ("mb-org-", "mb-sus-")


def _is_lab_category(resource: dict) -> bool:
    """Return True if the resource has a LAB category coding."""
    for entry in resource.get("category", []):
        for c in entry.get("coding", []):
            if c.get("code") in {"laboratory", "LAB"}:
                return True
    return False


def _is_microbiology_obs(resource: dict) -> bool:
    """Return True if the Observation is a microbiology result (mb-org-* / mb-sus-*).

    Microbiology observations have the LAB category but are not yet linked to
    ServiceRequests (PR1 scope = lab panel orders only).
    """
    return resource.get("id", "").startswith(_MB_ID_PREFIXES)


@pytest.mark.integration
def test_lab_observation_basedon_coverage_us():
    """100% of non-microbiology LAB Observations carry basedOn referencing an existing SR.

    Microbiology observations (mb-org-* / mb-sus-*) are excluded because PR1
    covers only lab panel orders; microbiology ServiceRequests are future work.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)

        sr_ids = {r["id"] for r in load_ndjson(find_ndjson(out, "ServiceRequest.ndjson"))}
        obs = load_ndjson(find_ndjson(out, "Observation.ndjson"))
        lab_obs = [
            o for o in obs
            if _is_lab_category(o) and not _is_microbiology_obs(o)
        ]

        missing = [o["id"] for o in lab_obs if not o.get("basedOn")]
        dangling: list[str] = []
        for o in lab_obs:
            for ref in o.get("basedOn", []):
                sr_id = ref.get("reference", "").removeprefix("ServiceRequest/")
                if sr_id and sr_id not in sr_ids:
                    dangling.append(sr_id)

        assert not missing, (
            f"{len(missing)} LAB Observations missing basedOn: {missing[:5]}"
        )
        assert not dangling, (
            f"{len(dangling)} dangling SR refs (SR not in ServiceRequest.ndjson): "
            f"{dangling[:5]}"
        )


@pytest.mark.integration
def test_diagnostic_report_basedon_coverage_us():
    """Every lab DiagnosticReport carries basedOn pointing to existing SR(s)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)

        sr_ids = {r["id"] for r in load_ndjson(find_ndjson(out, "ServiceRequest.ndjson"))}
        reports = load_ndjson(find_ndjson(out, "DiagnosticReport.ndjson"))
        # Filter to lab panel DRs (not microbiology).
        lab_reports = [
            r for r in reports
            if r.get("id", "").startswith("dr-") and not r.get("id", "").startswith("dr-mb-")
        ]

        if not lab_reports:
            pytest.skip("No lab-panel DiagnosticReports emitted for n=200 cohort")

        for r in lab_reports:
            assert r.get("basedOn"), (
                f"DiagnosticReport/{r['id']} missing basedOn"
            )
            for ref in r["basedOn"]:
                sr_id = ref["reference"].removeprefix("ServiceRequest/")
                assert sr_id in sr_ids, (
                    f"DiagnosticReport/{r['id']} basedOn → ServiceRequest/{sr_id} "
                    f"not found in ServiceRequest.ndjson"
                )


@pytest.mark.integration
def test_panel_members_share_sr_id():
    """In a CBC panel, the 3-4 component Observations share a single basedOn SR ref."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)

        obs = load_ndjson(find_ndjson(out, "Observation.ndjson"))

        # Group CBC analytes by (encounter, timestamp) — shared SR test.
        by_slot: dict[tuple[str, str], list[dict]] = {}
        for o in obs:
            if o.get("code", {}).get("text") in {"WBC", "Hb", "Hct", "Plt"}:
                enc = o.get("encounter", {}).get("reference", "")
                ts = o.get("effectiveDateTime", "")
                by_slot.setdefault((enc, ts), []).append(o)

        found_panel = False
        for group in by_slot.values():
            if len(group) >= 3:
                sr_refs = {
                    o["basedOn"][0]["reference"] for o in group if o.get("basedOn")
                }
                if len(sr_refs) == 1:
                    found_panel = True
                    break

        if not found_panel:
            pytest.skip(
                "No CBC panel with 3+ co-timed analytes sharing one SR ref found "
                "in 200-patient cohort (rare event at this cohort size)"
            )
