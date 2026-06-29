"""Integration tests: ServiceRequest end-to-end (PR1)."""

import pytest

from clinosim.modules.output.fhir_r4_adapter import available_builders


@pytest.mark.integration
def test_service_request_builder_registered():
    """_bb_service_requests must appear in the builder registry after import."""
    builders = available_builders()
    assert "_bb_service_requests" in builders
