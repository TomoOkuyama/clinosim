"""Output module — CIF writers + pluggable format adapters (AD-58) + FHIR bundle
builders (AD-56). Re-exports the public registration entry points."""

from clinosim.modules.output.adapter import register_output_adapter
from clinosim.modules.output.fhir_r4_adapter import (
    available_builders,
    register_bundle_builder,
)

__all__ = [
    "register_output_adapter",
    "register_bundle_builder",
    "available_builders",
]
