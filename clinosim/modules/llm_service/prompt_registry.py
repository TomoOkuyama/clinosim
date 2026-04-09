"""Prompt template registry.

Loads YAML prompt definitions from ``clinosim/modules/llm_service/prompts/<lang>/<task>.yaml``
and renders them with ``string.Template`` (zero external dependency).

YAML format:

    task_type: discharge_summary
    version: 1
    max_tokens: 2000
    temperature: 0.4
    system: |
      You are an attending physician ...
    user_template: |
      Patient: ${age}yo ${sex}
      Admission: ${admission_date}
      ...

Missing variables raise ``KeyError`` so callers fail loudly rather than silently
producing malformed prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

import yaml

_DEFAULT_PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class PromptSpec:
    """Parsed YAML prompt template."""

    task_type: str
    language: str
    version: int = 1
    system: str = ""
    user_template: str = ""
    max_tokens: int = 1500
    temperature: float = 0.4
    description: str = ""

    def render(self, variables: dict[str, Any]) -> tuple[str, str]:
        """Render (system, user) prompts with variable substitution.

        Uses ``Template.substitute`` which raises KeyError on missing keys —
        we want to fail fast rather than emit a prompt with ``${missing}``.
        """
        sys_tmpl = Template(self.system)
        user_tmpl = Template(self.user_template)
        # Sanitize: all values must be strings for Template.substitute
        str_vars = {k: _stringify(v) for k, v in variables.items()}
        try:
            rendered_user = user_tmpl.substitute(str_vars)
        except KeyError as e:
            raise KeyError(
                f"Missing variable {e!r} when rendering prompt for "
                f"task_type={self.task_type!r} lang={self.language!r}. "
                f"Provided keys: {sorted(variables.keys())}"
            ) from e
        # System prompt is usually static; safe_substitute avoids breaking on
        # unrelated "${" sequences in natural-language instructions.
        rendered_system = sys_tmpl.safe_substitute(str_vars)
        return rendered_system, rendered_user


def _stringify(value: Any) -> str:
    """Convert a value into a prompt-safe string.

    - list → joined with newline + bullet
    - dict → key: value lines
    - None → empty string
    - anything else → str()
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "(none)"
        if all(isinstance(x, str) for x in value):
            return "\n".join(f"- {x}" for x in value)
        return "\n".join(f"- {_stringify(x)}" for x in value)
    if isinstance(value, dict):
        return "\n".join(f"{k}: {_stringify(v)}" for k, v in value.items())
    return str(value)


class PromptRegistry:
    """Collection of prompt specs keyed by (task_type, language)."""

    def __init__(self, prompts_dir: Path | None = None):
        self.prompts_dir = Path(prompts_dir) if prompts_dir else _DEFAULT_PROMPTS_DIR
        self._cache: dict[tuple[str, str], PromptSpec] = {}

    def get(self, task_type: str, language: str) -> PromptSpec:
        """Return the PromptSpec for a task/language, loading lazily.

        Falls back to English if the requested language is not available
        (mirrors ``clinosim.codes`` behavior — English-first with fallback).
        """
        key = (task_type, language)
        if key in self._cache:
            return self._cache[key]

        path = self.prompts_dir / language / f"{task_type}.yaml"
        if not path.exists() and language != "en":
            # Fallback to English
            path = self.prompts_dir / "en" / f"{task_type}.yaml"
        if not path.exists():
            raise FileNotFoundError(
                f"No prompt template for task_type={task_type!r} "
                f"language={language!r} (searched {self.prompts_dir})"
            )

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        spec = PromptSpec(
            task_type=data.get("task_type", task_type),
            language=language,
            version=int(data.get("version", 1)),
            system=data.get("system", "") or "",
            user_template=data.get("user_template", "") or "",
            max_tokens=int(data.get("max_tokens", 1500)),
            temperature=float(data.get("temperature", 0.4)),
            description=data.get("description", "") or "",
        )
        self._cache[key] = spec
        return spec

    def has(self, task_type: str, language: str) -> bool:
        try:
            self.get(task_type, language)
            return True
        except FileNotFoundError:
            return False
