"""Named SNOMED CT concepts used in decision logic and emitters (Issue #2290).

Bare SNOMED literals in comparisons hide what they mean; these names make the
check readable and keep one definition per concept. Each code is registered
in ``codes/data/snomed-ct.yaml`` with its English and Japanese display
(verified against tx.fhir.org ``$lookup``).
"""

from __future__ import annotations

# ProcedureRecord.category_code
SURGICAL_PROCEDURE = "387713003"

# ProcedureRecord.outcome_code
PROCEDURE_PARTIALLY_SUCCESSFUL = "385670004"
PROCEDURE_UNSUCCESSFUL = "385671000"

# DiagnosticReport.conclusionCode
FINDING_NORMAL = "17621005"
FINDING_ABNORMAL = "263654008"
