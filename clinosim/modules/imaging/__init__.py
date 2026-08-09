"""Imaging module (always-on, AD-55 supplement pattern).

Always enabled (near-essential clinical cascade). Only diseases whose
YAML declares ``imaging_orders[]`` populate ``extensions["imaging"]``;
diseases that do not trigger imaging are a clean no-op.

Public exports:
- ``ImagingStudyRecord`` / ``ImagingSeries`` / ``RadiologyReport`` (CIF
  types) — re-exported from ``clinosim.types.imaging``.
"""

from __future__ import annotations

from clinosim.types.imaging import ImagingSeries, ImagingStudyRecord, RadiologyReport

__all__ = [
    "ImagingSeries",
    "ImagingStudyRecord",
    "RadiologyReport",
]
