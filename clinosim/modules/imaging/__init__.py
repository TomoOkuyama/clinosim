"""Imaging module (Tier 1 #2 always-on Module, AD-55 PR3b-1 supplement pattern).

Always enabled (near-essential clinical cascade — disease YAML imaging_orders[]
発火 disease のみ extensions["imaging"] が populate されるので、無発火 disease では
clean no-op)。

Public exports:
- ImagingStudyRecord / ImagingSeries / RadiologyReport (CIF types) — re-export
  from clinosim.types.imaging.
"""

from __future__ import annotations

from clinosim.types.imaging import ImagingSeries, ImagingStudyRecord, RadiologyReport

__all__ = [
    "ImagingSeries",
    "ImagingStudyRecord",
    "RadiologyReport",
]
