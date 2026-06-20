"""MOD-2: PersonRecord / LifeEvent / HospitalizationSummary live in clinosim/types/.

Moved out of clinosim/modules/population/engine.py into clinosim/types/population.py
(the behaviour-bearing Household / PopulationRegistry stay in the module). Guard that
the canonical definition is in types/ and every historical import path is the SAME object.
"""

import pytest

from clinosim.modules.population import PersonRecord as ViaPkg
from clinosim.modules.population.engine import LifeEvent as ViaEngine
from clinosim.modules.population.engine import PersonRecord as PRViaEngine
from clinosim.types import PersonRecord as ViaTypesPkg
from clinosim.types.population import HospitalizationSummary, LifeEvent, PersonRecord


@pytest.mark.unit
class TestPopulationTypeLocation:
    def test_canonical_module_is_types(self):
        for cls in (HospitalizationSummary, PersonRecord, LifeEvent):
            assert cls.__module__ == "clinosim.types.population"

    def test_all_import_paths_are_the_same_object(self):
        assert PRViaEngine is PersonRecord
        assert ViaPkg is PersonRecord
        assert ViaTypesPkg is PersonRecord
        assert ViaEngine is LifeEvent

    def test_dataclass_fields_intact(self):
        from datetime import date

        p = PersonRecord(person_id="P1", household_id="H1", age=70, sex="M",
                          date_of_birth=date(1955, 1, 1))
        assert p.blood_type == "A"  # default preserved
        assert p.hospitalization_history == []
        assert LifeEvent(person_id="P1", event_type="ed_visit",
                         timestamp=date(2025, 1, 1)).encounter_type == "inpatient"
