"""Report renderers — JSON (machine) + Markdown (human)."""

from __future__ import annotations

import json
from pathlib import Path

from clinosim.eval.engine import EvalAxisResult, EvalReport, Outcome


def render_json(report: EvalReport) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)


def render_markdown(report: EvalReport) -> str:
    lines: list[str] = []
    lines.append("# clinosim eval report")
    lines.append("")
    lines.append(f"- **Cohort**: `{report.cohort_dir}`")
    lines.append(f"- **Generated at**: {report.generated_at}")
    lines.append(
        f"- **Overall score**: **{report.overall_score:.1f} / 100** "
        f"({report.overall_status})"
    )
    lines.append("")

    lines.append("## Resource counts")
    lines.append("")
    for country, counts in report.resource_counts.items():
        lines.append(f"### {country or '(flat)'}")
        lines.append("")
        lines.append("| ResourceType | Count |")
        lines.append("|---|---:|")
        for rt, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {rt} | {n} |")
        lines.append("")

    for axis in report.axes:
        lines.extend(_render_axis(axis))
        lines.append("")
    return "\n".join(lines)


def _render_axis(axis: EvalAxisResult) -> list[str]:
    lines: list[str] = []
    lines.append(
        f"## Axis: {axis.axis} ({axis.country or '(flat)'}) — "
        f"**{axis.score:.1f} / 100** ({axis.status})"
    )
    lines.append("")
    lines.append("| Check | Outcome | Severity | Message |")
    lines.append("|---|---|---|---|")
    for c in axis.checks:
        icon = _outcome_icon(c.outcome)
        lines.append(
            f"| `{c.name}` | {icon} {c.outcome.value} | {c.severity.value} | {_escape_md(c.message)} |"
        )
    return lines


def _outcome_icon(outcome: Outcome) -> str:
    return {
        Outcome.PASS: "✅",
        Outcome.WARN: "⚠️",
        Outcome.FAIL: "❌",
        Outcome.NA: "—",
    }[outcome]


def _escape_md(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def write_json(report: EvalReport, path: Path) -> None:
    Path(path).write_text(render_json(report), encoding="utf-8")


def write_markdown(report: EvalReport, path: Path) -> None:
    Path(path).write_text(render_markdown(report), encoding="utf-8")
