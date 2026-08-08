"""FHIR R4 output subsystem — Issue #555.

Public facade for FHIR R4 bundle generation. The concrete builder and
post-processing implementations live under `fhir_r4/<domain>/` (PR2) and
`fhir_r4/post_process/` (PR3). Shared helpers live under `fhir_r4/lib/` (PR1).

During PR1 this module is a placeholder; PR1 Task 3 promotes the current
`fhir_r4_adapter.py` facade content into this __init__.
"""

from __future__ import annotations
