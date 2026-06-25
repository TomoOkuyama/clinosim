"""Markdown reporter for AuditResult.

Renders the per-module x per-axis grid + axis-level findings into a
Markdown string suitable for committing under docs/reviews/. The
reporter is pure — it does not mutate the AuditResult.
"""

from __future__ import annotations

from pathlib import Path

from clinosim.audit.types import (
    AuditFinding,
    AuditResult,
)


def _info_block(info: dict) -> str:
    if not info:
        return ""
    return "\n".join(f"- {k}={v}" for k, v in info.items())


def _findings_block(findings: list[AuditFinding]) -> str:
    if not findings:
        return ""
    lines = []
    for f in findings:
        line = f"- **{f.severity.value}** {f.message}"
        if f.detail:
            line += f" — {f.detail}"
        lines.append(line)
    return "\n".join(lines)


def render_markdown(result: AuditResult) -> str:
    parts: list[str] = []
    parts.append("# clinosim audit report\n")
    parts.append(f"**Overall: {result.overall_status()}**\n")
    parts.append(f"- Cohort: `{result.cohort_dir}`")
    parts.append(f"- Modules: {', '.join(result.modules) or '(none)'}")
    parts.append(f"- Axes: {', '.join(result.axes)}\n")

    parts.append("## Summary\n")
    header = "| Module | " + " | ".join(result.axes) + " |"
    sep = "|---|" + "|".join("---" for _ in result.axes) + "|"
    parts.append(header)
    parts.append(sep)
    for module in result.modules:
        row = [f"| {module} "]
        for axis in result.axes:
            r = result.results.get((axis, module))
            row.append(f"| {r.status if r else 'N/A'} ")
        parts.append("".join(row) + "|")
    parts.append("")

    for module in result.modules:
        passed = sum(
            1
            for axis in result.axes
            if (r := result.results.get((axis, module))) and r.status == "PASS"
        )
        parts.append(f"## {module} ({passed}/{len(result.axes)} PASS)\n")
        for i, axis in enumerate(result.axes, 1):
            r = result.results.get((axis, module))
            status = r.status if r else "N/A"
            parts.append(f"### Axis {i}: {axis} — {status}\n")
            if r is None:
                parts.append("- (no audit for this module on this axis)\n")
                continue
            f_block = _findings_block(r.findings)
            if f_block:
                parts.append(f_block)
            i_block = _info_block(r.info)
            if i_block:
                parts.append(i_block)
            parts.append("")

    return "\n".join(parts)


def write_markdown(result: AuditResult, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_markdown(result), encoding="utf-8")
