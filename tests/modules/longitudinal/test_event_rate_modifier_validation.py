"""Final-review Important: rate_modifiers typo detection.

Pre-fix: rate_modifiers was `list[dict[str, Any]]` with no structural
validation. A yaml author who misspells `operatpor` (typo for operator)
or forgets `factor` silently gets a no-op modifier. Post-fix: pydantic
RateModifier model with extra="forbid" fails fast at import time.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clinosim.modules.longitudinal.patterns.event import EventSpec


@pytest.mark.unit
def test_event_spec_rejects_rate_modifier_missing_factor():
    with pytest.raises(ValidationError, match="factor"):
        EventSpec(
            event_name="x",
            emits_icd="E11.21",
            base_annual_rate=0.1,
            rate_modifiers=[{"when": {"attribute": "hba1c", "operator": ">", "value": 9.0}}],
        )


@pytest.mark.unit
def test_event_spec_rejects_rate_modifier_missing_when_operator():
    with pytest.raises(ValidationError, match="operator"):
        EventSpec(
            event_name="x",
            emits_icd="E11.21",
            base_annual_rate=0.1,
            rate_modifiers=[{"when": {"attribute": "hba1c", "value": 9.0}, "factor": 3.0}],
        )


@pytest.mark.unit
def test_event_spec_rejects_rate_modifier_extra_top_level_key():
    """A typo'd top-level key (e.g. 'facture' instead of 'factor') must
    not silently become a no-op modifier."""
    with pytest.raises(ValidationError):
        EventSpec(
            event_name="x",
            emits_icd="E11.21",
            base_annual_rate=0.1,
            rate_modifiers=[
                {
                    "when": {"attribute": "hba1c", "operator": ">", "value": 9.0},
                    "facture": 3.0,  # typo
                }
            ],
        )


@pytest.mark.unit
def test_event_spec_accepts_well_formed_rate_modifier():
    """Baseline — the real yaml shape must still validate."""
    spec = EventSpec(
        event_name="x",
        emits_icd="E11.21",
        base_annual_rate=0.1,
        rate_modifiers=[
            {"when": {"attribute": "hba1c", "operator": ">", "value": 9.0}, "factor": 3.0}
        ],
    )
    assert len(spec.rate_modifiers) == 1
