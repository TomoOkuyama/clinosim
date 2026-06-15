"""Resident identifier & insurance enrollment types (AD-54).

Runtime dataclasses (AD-18). Country-neutral field names; Japanese concepts map to
generic fields (記号 → group_symbol, 枝番 → branch_number).

Privacy: ``NationalIdentity.national_id`` (JP 個人番号) may live in CIF for future
マイナ-workflow extensibility, but output adapters MUST default-exclude it. It is
never emitted to FHIR/CSV unless explicitly opted in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

__all__ = ["NationalIdentity", "InsuranceEnrollment", "IdentityTimeline"]


@dataclass
class NationalIdentity:
    """National identity attributes (JP: My Number card / マイナ保険証 state)."""

    country: str = ""
    national_id: str | None = None  # JP 個人番号 (12-digit). NEVER emitted to clinical output.
    has_id_card: bool = False  # JP マイナンバーカード保有
    id_card_linked_to_insurance: bool = False  # JP マイナ保険証 登録


@dataclass
class InsuranceEnrollment:
    """A period-bounded insurance qualification (FHIR Coverage source)."""

    country: str = ""
    category: str = ""  # JP: "employee" | "national" | "dependent" | "late_elderly"
    insurer_number: str = ""  # 保険者番号 → JP Core payor Organization.identifier
    member_id: str = ""  # 番号 (insured person number) → JP_Coverage_InsuredPersonNumber
    group_symbol: str | None = None  # 記号 → JP_Coverage_InsuredPersonSymbol
    branch_number: str | None = None  # 枝番 → JP_Coverage_InsuredPersonSubNumber / dependent
    valid_from: date | None = None  # None = unbounded (Phase 1 snapshot single enrollment)
    valid_to: date | None = None  # None = currently valid
    system_uri: str = ""  # FHIR Coverage system (resolved at output time)


@dataclass
class IdentityTimeline:
    """Per-resident identity + insurance history, held on Layer-1 PersonRecord."""

    national: NationalIdentity = field(default_factory=NationalIdentity)
    enrollments: list[InsuranceEnrollment] = field(default_factory=list)
    card_acquired_on: date | None = None  # マイナンバーカード取得日 (Phase 3)
    insurance_linked_on: date | None = None  # マイナ保険証 登録日 (Phase 3)

    def enrollment_on(self, when: date) -> InsuranceEnrollment | None:
        """Return the insurance enrollment valid on a given date.

        Phase 1 holds a single open-ended enrollment; this resolves correctly once
        Phase 2 adds period-bounded history.
        """
        for e in self.enrollments:
            after_start = e.valid_from is None or e.valid_from <= when
            before_end = e.valid_to is None or when <= e.valid_to
            if after_start and before_end:
                return e
        return self.enrollments[-1] if self.enrollments else None

    def current_enrollment(self) -> InsuranceEnrollment | None:
        """Return the most recent (currently valid) enrollment."""
        open_ended = [e for e in self.enrollments if e.valid_to is None]
        if open_ended:
            return open_ended[-1]
        return self.enrollments[-1] if self.enrollments else None
