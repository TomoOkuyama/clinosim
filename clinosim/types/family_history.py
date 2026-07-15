"""Family history of disease — first-degree relative records (AD-55 Base).

Codes only (AD-30): relationship is an HL7 v3-RoleCode (MTH/FTH/NSIB), conditions
are ICD base codes. Display is resolved at output time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FamilyMemberHistoryRecord:
    relationship: str  # v3-RoleCode: MTH | FTH | NSIB
    sex: str  # "male" | "female"
    deceased: bool = False
    condition_codes: list[str] = field(default_factory=list)  # ICD base codes
