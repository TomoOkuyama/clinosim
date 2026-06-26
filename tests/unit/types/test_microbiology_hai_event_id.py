from clinosim.types.microbiology import MicrobiologyResult


def test_hai_event_id_defaults_to_empty_string():
    result = MicrobiologyResult()
    assert result.hai_event_id == ""


def test_hai_event_id_can_be_populated():
    result = MicrobiologyResult(hai_event_id="hai-enc1-clabsi-0")
    assert result.hai_event_id == "hai-enc1-clabsi-0"


def test_hai_event_id_does_not_break_existing_fields():
    result = MicrobiologyResult(
        encounter_id="enc1",
        specimen="blood",
        organism_snomed="3092008",
        hai_event_id="hai-enc1-clabsi-0",
    )
    assert result.encounter_id == "enc1"
    assert result.specimen == "blood"
    assert result.organism_snomed == "3092008"
