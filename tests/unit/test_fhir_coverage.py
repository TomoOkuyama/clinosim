"""Unit tests for JP Core Coverage FHIR output + privacy chokepoint (AD-54)."""

from __future__ import annotations

import json

import pytest

from clinosim.modules.output.fhir_r4.demographics.patient import (
    _build_coverage_resources,
    _build_patient,
    resolve_patient_id,
)

_NATIONAL_ID = "123456789018"

_PATIENT_JP = {
    "patient_id": "POP-000001",
    "sex": "M",
    "name": {"family_name": "山田", "given_name": "太郎"},
    "identity": {
        "national": {
            "country": "JP",
            "national_id": _NATIONAL_ID,
            "has_id_card": True,
            "id_card_linked_to_insurance": True,
        },
        "enrollments": [
            {
                "country": "JP",
                "category": "employee",
                "insurer_number": "01130012",
                "member_id": "12345678",
                "group_symbol": "1234",
                "branch_number": "01",
                "valid_from": None,
                "valid_to": None,
                "system_uri": "",
            }
        ],
        "card_acquired_on": None,
        "insurance_linked_on": None,
    },
}


@pytest.mark.unit
class TestCoverageBuilder:
    def test_emits_payer_org_and_coverage(self):
        res = _build_coverage_resources(_PATIENT_JP, "JP")
        kinds = [r["resourceType"] for r in res]
        assert kinds == ["Organization", "Coverage"]

    def test_coverage_core_fields(self):
        cov = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Coverage")
        assert cov["status"] == "active"
        assert cov["beneficiary"]["reference"] == f"Patient/{resolve_patient_id('POP-000001')}"
        assert cov["payor"][0]["reference"] == "Organization/payer-01130012"
        assert cov["subscriberId"] == "1234:12345678"
        assert cov["dependent"] == "01"
        assert cov["identifier"][0]["value"] == "01130012:1234:12345678:01"
        assert cov["meta"]["profile"][0].endswith("JP_Coverage")

    def test_coverage_type_is_text_label(self):
        cov = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Coverage")
        # text-only CodeableConcept (no fabricated coding)
        assert "coding" not in cov["type"]
        assert cov["type"]["text"] == "被用者保険（被保険者）"

    def test_coverage_relationship_self_for_subscriber(self):
        cov = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Coverage")
        assert cov["relationship"]["coding"][0]["code"] == "self"

    def test_jp_core_extensions(self):
        cov = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Coverage")
        ext_by_url = {e["url"]: e["valueString"] for e in cov["extension"]}
        symbol_url = next(u for u in ext_by_url if u.endswith("InsuredPersonSymbol"))
        number_url = next(u for u in ext_by_url if u.endswith("InsuredPersonNumber"))
        sub_url = next(u for u in ext_by_url if u.endswith("InsuredPersonSubNumber"))
        assert ext_by_url[symbol_url] == "1234"
        assert ext_by_url[number_url] == "12345678"
        assert ext_by_url[sub_url] == "01"

    def test_payer_org_identifier_and_name(self):
        org = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Organization")
        assert org["id"] == "payer-01130012"
        assert org["identifier"][0]["value"] == "01130012"
        assert "jp-insurer-number-namingsystem" in org["identifier"][0]["system"]
        # name resolved to the real insurer name (not the number)
        assert org["name"] == "全国健康保険協会 東京支部"

    def test_payer_org_type_coding(self):
        org = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Organization")
        coding = org["type"][0]["coding"][0]
        assert coding["code"] == "pay"
        assert coding["system"].endswith("organization-type")

    def test_reference_integrity_payor_resolves(self):
        res = _build_coverage_resources(_PATIENT_JP, "JP")
        org_ids = {f"Organization/{r['id']}" for r in res if r["resourceType"] == "Organization"}
        cov = next(r for r in res if r["resourceType"] == "Coverage")
        assert cov["payor"][0]["reference"] in org_ids

    def test_no_enrollments_returns_empty(self):
        patient = {"patient_id": "P", "identity": {"enrollments": []}}
        assert _build_coverage_resources(patient, "JP") == []

    def test_us_has_no_coverage_config(self):
        # US has no identity.yaml fhir_coverage block in Phase 1 → no Coverage emitted.
        assert _build_coverage_resources(_PATIENT_JP, "US") == []


@pytest.mark.unit
class TestPrivacyChokepoint:
    def test_national_id_never_emitted(self):
        """national_id must not appear in any FHIR resource built from the patient."""
        coverage = _build_coverage_resources(_PATIENT_JP, "JP")
        patient = _build_patient(_PATIENT_JP, "JP")
        blob = json.dumps(coverage, ensure_ascii=False) + json.dumps(patient, ensure_ascii=False)
        assert _NATIONAL_ID not in blob


# Issue #923: age-gated Coverage.type + multi-FY Coverage.period.
def _patient_with_encounters(dob: str, category: str, encounters: list[dict]) -> dict:
    return {
        "patient_id": f"POP-DOB-{dob}",
        "sex": "F",
        "date_of_birth": dob,
        "name": {"family_name": "山田", "given_name": "花子"},
        "encounters": encounters,
        "identity": {
            "national": {
                "country": "JP",
                "national_id": "",
                "has_id_card": False,
                "id_card_linked_to_insurance": False,
            },
            "enrollments": [
                {
                    "country": "JP",
                    "category": category,
                    "insurer_number": "01130012" if category == "employee" else "131011",
                    "member_id": "12345678",
                    "group_symbol": "1234" if category == "employee" else None,
                    "branch_number": "01" if category == "employee" else None,
                    "valid_from": None,
                    "valid_to": None,
                    "system_uri": "",
                }
            ],
            "card_acquired_on": None,
            "insurance_linked_on": None,
        },
    }


def _covs(patient: dict, country: str = "JP", encounters=None, snapshot_date: str | None = None):
    from clinosim.modules.output.fhir_r4.demographics.patient import (
        _build_coverage_resources as build,
    )

    return [r for r in build(patient, country, encounters, snapshot_date) if r["resourceType"] == "Coverage"]


@pytest.mark.unit
class TestIssue923AgeGate:
    def test_75_plus_patient_gets_koki_koureisha(self):
        """A patient ≥75 at Coverage.period.start MUST be 後期高齢者医療制度,
        regardless of what the identity module originally assigned."""
        p = _patient_with_encounters(
            "1935-06-01",  # ~90 at 2025
            "dependent",  # identity said 被扶養者 — wrong for 75+
            [{"admission_datetime": "2025-06-15T10:00:00"}],
        )
        covs = _covs(p)
        assert len(covs) == 1
        assert covs[0]["type"]["text"] == "後期高齢者医療制度"
        # And swapped to the 後期高齢 payer
        assert covs[0]["payor"][0]["reference"] == "Organization/payer-39130083"

    def test_minor_never_gets_hihokensha(self):
        """A minor's Coverage.type MUST NOT be 被用者保険（被保険者）; if the
        underlying enrollment marked them employee, demote to 被扶養者."""
        p = _patient_with_encounters(
            "2015-04-01",  # ~10 in FY2025
            "employee",  # identity mistakenly assigned; must be corrected
            [{"admission_datetime": "2025-06-15T10:00:00"}],
        )
        covs = _covs(p)
        assert len(covs) == 1
        assert covs[0]["type"]["text"] != "被用者保険（被保険者）"
        assert covs[0]["type"]["text"] == "被用者保険（被扶養者）"

    def test_adult_employee_unchanged(self):
        """Age gates must NOT touch adults with correct enrollment."""
        p = _patient_with_encounters(
            "1985-01-15",  # ~40 in FY2025
            "employee",
            [{"admission_datetime": "2025-06-15T10:00:00"}],
        )
        covs = _covs(p)
        assert len(covs) == 1
        assert covs[0]["type"]["text"] == "被用者保険（被保険者）"


@pytest.mark.unit
class TestIssue923MultiFY:
    def test_coverage_period_spans_all_encounters(self):
        """Every encounter's admission date must fall inside at least one
        emitted Coverage.period (0 uncovered rows was the whole point of #923)."""
        p = _patient_with_encounters(
            "1980-01-01",
            "employee",
            [
                {"admission_datetime": "2024-05-10T09:00:00"},  # FY2024
                {"admission_datetime": "2025-08-20T09:00:00"},  # FY2025
                {"admission_datetime": "2026-06-01T09:00:00"},  # FY2026
            ],
        )
        covs = _covs(p)
        # 3 fiscal years touched → 3 Coverage rows
        assert len(covs) == 3
        periods = [(c["period"]["start"], c["period"]["end"]) for c in covs]
        assert periods == [
            ("2024-04-01", "2025-03-31"),
            ("2025-04-01", "2026-03-31"),
            ("2026-04-01", "2027-03-31"),
        ]
        # Every encounter admission date must fall in ≥1 period.
        for enc_date in ("2024-05-10", "2025-08-20", "2026-06-01"):
            assert any(c["period"]["start"] <= enc_date <= c["period"]["end"] for c in covs), (
                f"encounter {enc_date} outside all Coverage.period rows"
            )

    def test_ages_across_75_boundary_gets_swapped(self):
        """A patient turning 75 mid-simulation gets 後期高齢者医療制度 from
        the FY containing the 75th birthday onward."""
        p = _patient_with_encounters(
            # Born 1951-05-01 → age at FY2025 end (2026-03-31) is 74; age at
            # FY2026 end (2027-03-31) is 75. The late-elderly gate uses the
            # period-end age so a patient turning 75 in FY2026 promotes only
            # from FY2026 onward and their FY2025 row stays 国保.
            "1951-05-01",
            "national",  # 国保 at generation time
            [
                {"admission_datetime": "2025-09-01T09:00:00"},  # FY2025 (age 74)
                {"admission_datetime": "2026-09-01T09:00:00"},  # FY2026 (age 75)
            ],
        )
        covs = _covs(p)
        assert len(covs) == 2
        types = [c["type"]["text"] for c in covs]
        assert types == ["国民健康保険", "後期高齢者医療制度"]

    def test_single_fy_patient_still_gets_one_row(self):
        """Single-FY encounters produce a single Coverage row (regression:
        we didn't multiply rows for the majority case)."""
        p = _patient_with_encounters(
            "1985-01-15",
            "employee",
            [
                {"admission_datetime": "2025-05-01T09:00:00"},
                {"admission_datetime": "2025-11-20T09:00:00"},
            ],
        )
        covs = _covs(p)
        assert len(covs) == 1
        assert covs[0]["period"] == {"start": "2025-04-01", "end": "2026-03-31"}


@pytest.mark.unit
class TestIssue923IdentitySampler:
    def test_all_minor_household_falls_back_to_national(self):
        """When a household has no adult, JPIdentityProvider must NOT pick a
        minor as 被保険者 — instead fall back to 国保."""
        import numpy as np

        from clinosim.locale.loader import load_identity_config
        from clinosim.modules.identity.providers.jp import JPIdentityProvider

        class _M:
            def __init__(self, pid, age, occupation="other"):
                self.person_id = pid
                self.age = age
                self.occupation = occupation

        provider = JPIdentityProvider()
        cfg = load_identity_config("JP")
        rng = np.random.default_rng(123)
        # Household of two minors — no adult.
        members = [_M("m1", 10), _M("m2", 15)]
        enrollments = provider.assign_household(members, rng, cfg)
        for e in enrollments.values():
            # Neither child can be marked "employee" (=被保険者).
            assert e.category != "employee"


# Issue #944: Coverage.status derived from period.end vs snapshot_date.
# Pre-#944: every Coverage row was hard-coded "active", regardless of whether
# its FY window had ended before the simulation cutoff. Post-#944: expired FY
# rows emit "cancelled"; the current FY (period.end >= snapshot) stays
# "active"; the FY endpoint itself is inclusive.
@pytest.mark.unit
class TestIssue944CoverageStatus:
    def test_derive_status_helper_expired_row_is_cancelled(self):
        from clinosim.modules.output.fhir_r4.demographics.patient import (
            _derive_coverage_status,
        )

        # FY ends 2025-03-31, snapshot 2026-03-31 → policy has expired.
        assert _derive_coverage_status("2025-03-31", "2026-03-31") == "cancelled"

    def test_derive_status_helper_current_row_is_active(self):
        from clinosim.modules.output.fhir_r4.demographics.patient import (
            _derive_coverage_status,
        )

        assert _derive_coverage_status("2026-03-31", "2025-06-01") == "active"

    def test_derive_status_helper_boundary_endpoint_inclusive(self):
        from clinosim.modules.output.fhir_r4.demographics.patient import (
            _derive_coverage_status,
        )

        # period.end == snapshot: the FY endpoint IS the last day of
        # coverage, so the row is still active on the snapshot itself.
        assert _derive_coverage_status("2026-03-31", "2026-03-31") == "active"

    def test_derive_status_helper_missing_snapshot_defaults_active(self):
        from clinosim.modules.output.fhir_r4.demographics.patient import (
            _derive_coverage_status,
        )

        # Backward compat with identity-only tests that don't plumb
        # snapshot_date through.
        assert _derive_coverage_status("2020-01-01", None) == "active"
        assert _derive_coverage_status(None, "2026-03-31") == "active"

    def test_expired_fy_row_emits_cancelled(self):
        """A single-FY patient whose FY ended before the snapshot must emit
        Coverage.status = "cancelled"."""
        p = _patient_with_encounters(
            "1985-01-15",
            "employee",
            [{"admission_datetime": "2024-05-10T09:00:00"}],  # FY2024 only
        )
        # Snapshot in FY2026 — FY2024 (ends 2025-03-31) is expired.
        covs = _covs(p, snapshot_date="2026-03-31")
        assert len(covs) == 1
        assert covs[0]["period"] == {"start": "2024-04-01", "end": "2025-03-31"}
        assert covs[0]["status"] == "cancelled"

    def test_current_fy_row_emits_active(self):
        """A single-FY patient whose FY spans the snapshot must emit
        Coverage.status = "active"."""
        p = _patient_with_encounters(
            "1985-01-15",
            "employee",
            [{"admission_datetime": "2025-05-01T09:00:00"}],
        )
        # Snapshot inside the FY2025 period.
        covs = _covs(p, snapshot_date="2025-10-01")
        assert len(covs) == 1
        assert covs[0]["period"] == {"start": "2025-04-01", "end": "2026-03-31"}
        assert covs[0]["status"] == "active"

    def test_multi_fy_patient_mixes_cancelled_and_active(self):
        """Regression: a patient with encounters across multiple FYs must
        get "cancelled" on the expired FY rows and "active" on the current
        FY row — never all-"active" (that was the #944 defect)."""
        p = _patient_with_encounters(
            "1980-01-01",
            "employee",
            [
                {"admission_datetime": "2024-05-10T09:00:00"},  # FY2024 (expired)
                {"admission_datetime": "2025-08-20T09:00:00"},  # FY2025 (current)
                {"admission_datetime": "2026-06-01T09:00:00"},  # FY2026 (future)
            ],
        )
        # Snapshot inside FY2025 — the FY2024 row is expired, FY2025 is
        # active, FY2026 has not started yet but its period.end
        # (2027-03-31) is still after the snapshot so it also reads as
        # active. What must never happen is an expired row still reading
        # active.
        covs = _covs(p, snapshot_date="2025-12-31")
        assert len(covs) == 3
        status_by_period = {c["period"]["end"]: c["status"] for c in covs}
        assert status_by_period["2025-03-31"] == "cancelled"
        assert status_by_period["2026-03-31"] == "active"
        assert status_by_period["2027-03-31"] == "active"

    def test_snapshot_none_preserves_pre_944_active(self):
        """Backward compat: callers that don't pass snapshot_date see the
        pre-#944 unconditional "active" (identity-only tests, non-standard
        callers). Explicit test so a future refactor cannot silently break
        the identity-module tests that assert status == "active"."""
        p = _patient_with_encounters(
            "1985-01-15",
            "employee",
            [{"admission_datetime": "2020-05-10T09:00:00"}],
        )
        covs = _covs(p)  # no snapshot_date
        assert len(covs) == 1
        assert covs[0]["status"] == "active"
