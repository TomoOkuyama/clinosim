"""The side of an acute stroke, one canonical value per stay (Issue #3557).

The CIF records the stroke and its severity but not the hemisphere, so the side
is derived from a hash of the encounter id (no random draw) and shared by every
consumer: the admission exam (side of the weakness) and the head imaging
reports (side of the lesion). The lesion lies in the hemisphere opposite to the
weakness (a corticospinal deficit is contralateral to its lesion), so right
weakness with left gaze deviation is a left-hemisphere (left MCA territory)
lesion.
"""

from __future__ import annotations

import hashlib

#: The two sides; ``_OPPOSITE`` maps weakness side to lesion side.
_OPPOSITE = {"right": "left", "left": "right"}


def stroke_weakness_side(encounter_id: str) -> str:
    """``"right"`` or ``"left"``: the side of the stay's focal weakness,
    fixed by the encounter id (the same in every document of the stay)."""
    digest = hashlib.sha256(f"{encounter_id}|stroke_side".encode()).hexdigest()
    return "right" if int(digest, 16) % 2 == 0 else "left"


def stroke_lesion_side(encounter_id: str) -> str:
    """``"left"`` or ``"right"``: the hemisphere of the stay's lesion, the side
    opposite to :func:`stroke_weakness_side`."""
    return _OPPOSITE[stroke_weakness_side(encounter_id)]
