"""AuditEngine — orchestrates per-Module audit checks across axes.

Discovery walks clinosim/modules/*/audit.py and side-effect-registers
each Module's spec. The engine then iterates the selected module x
axis matrix, calling each axis's run() with the spec + Cohort.
"""
from __future__ import annotations

from pathlib import Path

from clinosim.audit.axes import clinical, jp_language, silent_no_op, structural
from clinosim.audit.registry import discover, get_registered
from clinosim.audit.types import AuditResult, Cohort

_BUILTIN_AXES = ("structural", "jp_language", "clinical", "silent_no_op")
_AXIS_RUNNERS = {
    "structural": structural.run,
    "jp_language": jp_language.run,
    "clinical": clinical.run,
    "silent_no_op": silent_no_op.run,
}


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

        result = AuditResult(
            cohort_dir=self.cohort_dir,
            modules=selected_modules,
            axes=axes_to_run,
        )
        cohort = Cohort.open(self.cohort_dir)
        for axis in axes_to_run:
            runner = _AXIS_RUNNERS[axis]
            for module_name in selected_modules:
                axis_result = runner(registered[module_name], cohort)
                result.add(axis, module_name, axis_result)
        return result
