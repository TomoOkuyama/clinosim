"""Unit tests for scenario_flags_from_protocol (Phase 2a J5 fix)."""
import pytest

from clinosim.modules.physiology.engine import scenario_flags_from_protocol


@pytest.mark.unit
def test_none_protocol_returns_all_false():
    flags = scenario_flags_from_protocol(None)
    assert flags == {"myocardial_injury": False, "causes_vte": False}


@pytest.mark.unit
def test_dict_protocol_reads_both_flags():
    flags = scenario_flags_from_protocol(
        {"causes_myocardial_injury": True, "causes_vte": True}
    )
    assert flags == {"myocardial_injury": True, "causes_vte": True}


@pytest.mark.unit
def test_dict_protocol_missing_keys_default_false():
    flags = scenario_flags_from_protocol({})
    assert flags == {"myocardial_injury": False, "causes_vte": False}


@pytest.mark.unit
def test_object_protocol_reads_attribute():
    """Pydantic disease-protocol objects expose flags as attributes."""
    class FakeProtocol:
        causes_myocardial_injury = True
        causes_vte = False
    flags = scenario_flags_from_protocol(FakeProtocol())
    assert flags == {"myocardial_injury": True, "causes_vte": False}


@pytest.mark.unit
def test_object_protocol_missing_attribute_defaults_false():
    class EmptyProtocol:
        pass
    flags = scenario_flags_from_protocol(EmptyProtocol())
    assert flags == {"myocardial_injury": False, "causes_vte": False}


@pytest.mark.unit
def test_keys_match_derive_lab_values_parameter_names():
    """The dict keys must match derive_lab_values parameter names so callers
    can splat with **flags. If derive_lab_values param is renamed, this
    test guards the contract."""
    import inspect

    from clinosim.modules.physiology.engine import derive_lab_values
    sig = inspect.signature(derive_lab_values)
    flags = scenario_flags_from_protocol(None)
    for key in flags:
        assert key in sig.parameters, (
            f"scenario_flags_from_protocol returned key '{key}' that is "
            f"not a derive_lab_values parameter"
        )
