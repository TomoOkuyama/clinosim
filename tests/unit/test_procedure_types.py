"""MOD-3: ProcedureRecord / RehabSession live in clinosim/types/ (shared types rule).

The dataclasses were moved out of clinosim/modules/procedure/engine.py into
clinosim/types/procedure.py. Guard that the canonical definition is in types/ and
that every historical import path resolves to the SAME class object (no accidental
re-definition / shadow copy).
"""

import pytest

from clinosim.modules.procedure import ProcedureRecord as ViaPkg
from clinosim.modules.procedure import RehabSession as RehabViaPkg
from clinosim.modules.procedure.engine import ProcedureRecord as ViaEngine
from clinosim.modules.procedure.engine import RehabSession as RehabViaEngine
from clinosim.types import ProcedureRecord as ViaTypesPkg
from clinosim.types.procedure import ProcedureRecord, RehabSession


@pytest.mark.unit
class TestProcedureTypeLocation:
    def test_canonical_module_is_types(self):
        assert ProcedureRecord.__module__ == "clinosim.types.procedure"
        assert RehabSession.__module__ == "clinosim.types.procedure"

    def test_all_import_paths_are_the_same_object(self):
        assert ViaEngine is ProcedureRecord
        assert ViaPkg is ProcedureRecord
        assert ViaTypesPkg is ProcedureRecord
        assert RehabViaEngine is RehabSession
        assert RehabViaPkg is RehabSession

    def test_dataclass_fields_intact(self):
        rec = ProcedureRecord(procedure_id="P1", procedure_code="K0461")
        assert rec.procedure_id == "P1"
        assert rec.asa_class == 2  # default preserved
        assert RehabSession(therapy_type="OT").therapy_type == "OT"
