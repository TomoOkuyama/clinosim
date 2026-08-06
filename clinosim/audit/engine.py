"""AuditEngine — orchestrates per-Module audit checks across axes.

Discovery walks clinosim/modules/*/audit.py and side-effect-registers
each Module's spec. The engine then iterates the selected module x
axis matrix, calling each axis's run() with the spec + Cohort.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from clinosim.audit.axes import clinical, jp_language, silent_no_op, structural
from clinosim.audit.registry import ModuleAuditSpec, discover, get_registered
from clinosim.audit.types import AuditResult, AxisResult, Cohort

_BUILTIN_AXES = ("structural", "jp_language", "clinical", "silent_no_op")

# Per-module axes: called once per (axis × module) with the module's
# ``ModuleAuditSpec`` and the cohort.
_PER_MODULE_RUNNERS: dict[str, Callable[[ModuleAuditSpec, Cohort], AxisResult]] = {
    "structural": structural.run,
    "clinical": clinical.run,
    "silent_no_op": silent_no_op.run,
}

# Cohort-level axes: called once per cohort with ``None`` for the spec.
# Their result is attached to a synthetic ``"_cohort_"`` module row so
# the reporter grid still has a cell to render.
_COHORT_RUNNERS: dict[str, Callable[[ModuleAuditSpec | None, Cohort], AxisResult]] = {
    "jp_language": jp_language.run,
}

_COHORT_MODULE_SENTINEL = "_cohort_"


class AuditEngine:
    def __init__(
        self,
        cohort_dir: Path | str,
        modules: list[str] | None = None,
        axes: list[str] | None = None,
    ):
        self.cohort_dir = Path(cohort_dir)
        self.module_filter = modules
        self.axis_filter = axes

    def run(self) -> AuditResult:
        discover()
        registered = get_registered()
        if self.module_filter is None:
            selected_modules = list(registered)
        else:
            selected_modules = [m for m in self.module_filter if m in registered]
        axes_to_run = self.axis_filter or list(_BUILTIN_AXES)

        # ``result.modules`` gets the cohort-level sentinel appended
        # below when a cohort-level axis runs. Pass a fresh copy so we
        # do not mutate ``selected_modules`` (which the per-module
        # loop iterates against ``registered``).
        result = AuditResult(
            cohort_dir=self.cohort_dir,
            modules=list(selected_modules),
            axes=axes_to_run,
        )
        cohort = Cohort.open(self.cohort_dir)
        for axis in axes_to_run:
            if axis in _COHORT_RUNNERS:
                cohort_runner = _COHORT_RUNNERS[axis]
                axis_result = cohort_runner(None, cohort)
                result.add(axis, _COHORT_MODULE_SENTINEL, axis_result)
                if _COHORT_MODULE_SENTINEL not in result.modules:
                    result.modules.append(_COHORT_MODULE_SENTINEL)
                continue
            per_module_runner = _PER_MODULE_RUNNERS[axis]
            for module_name in selected_modules:
                axis_result = per_module_runner(registered[module_name], cohort)
                result.add(axis, module_name, axis_result)
        return result
