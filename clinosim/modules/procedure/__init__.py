"""Procedure module — surgical/bedside procedure and rehabilitation generation."""

from clinosim.modules.procedure.engine import (
    ProcedureRecord,
    RehabSession,
    generate_bedside_procedures,
    generate_rehab_sessions,
    simulate_surgery,
)

__all__ = [
    "ProcedureRecord",
    "RehabSession",
    "generate_bedside_procedures",
    "generate_rehab_sessions",
    "simulate_surgery",
]
