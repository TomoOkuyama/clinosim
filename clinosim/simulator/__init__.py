"""clinosim simulator — population-driven EHR data generation.

Public API:
  run_beta(config)       — population-driven simulation (main entry point)
  run_forced(scenario)   — generate specific disease/archetype (testing)
  run_alpha(config)      — backward-compatible single patient

CLI:
  clinosim generate -p 10000 -o ./output --format cif csv fhir
  clinosim test-disease bacterial_pneumonia --archetype treatment_resistant -n 5
"""

from clinosim.simulator.cli import main
from clinosim.simulator.engine import run_alpha, run_beta, run_forced
from clinosim.simulator.helpers import _load_all_disease_protocols

__all__ = [
    "run_alpha",
    "run_beta",
    "run_forced",
    "main",
    "_load_all_disease_protocols",
]
