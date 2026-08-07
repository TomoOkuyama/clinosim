"""Pinned OSS-stable public API for **clinosim**.

Symbols re-exported here are guaranteed stable across MINOR releases; removals
require a MAJOR bump. Any breaking-change proposal starts with an Issue that
labels this file. See :doc:`docs/roadmap.md` for tracking.

The stability contract:

* Names in ``__all__`` will not disappear without a deprecation cycle.
* Signatures accept an ever-widening set of arguments over the MINOR line
  (added kwargs with defaults) but never lose a positional parameter.
* Return types stay type-compatible in the strict-covariant sense (never
  narrow to a non-Optional; never remove an attribute a caller could observe).

Anything not in this module is internal — importing it directly (even if
technically possible) means opting into every refactor the maintainer ships.
"""

from __future__ import annotations

from clinosim import __version__

# Output adapter registry
from clinosim.modules.output.adapter import (
    available_formats,
    register_output_adapter,
)

# FHIR R4 bundle builder registry
from clinosim.modules.output.fhir_r4_adapter import (
    available_builders,
    convert_cif_to_fhir,
    register_bundle_builder,
)

# Simulation entry points
from clinosim.simulator.engine import run_alpha, run_beta, run_forced

# Configuration
from clinosim.types.config import SimulatorConfig

__all__ = [
    "__version__",
    # Simulation
    "run_alpha",
    "run_beta",
    "run_forced",
    # Configuration
    "SimulatorConfig",
    # Output adapter registry
    "available_formats",
    "register_output_adapter",
    # FHIR R4
    "available_builders",
    "convert_cif_to_fhir",
    "register_bundle_builder",
]
