# Roadmap

The authoritative roadmap for **clinosim** lives on GitHub:

- **Open work**: [`gh issue list --state open`](https://github.com/TomoOkuyama/clinosim/issues) — every planned change is tracked here.
- **Priorities**: filter by label
  ([`priority:high`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Apriority%3Ahigh),
  [`priority:medium`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Apriority%3Amedium),
  [`priority:low`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Apriority%3Alow))
  or by area
  ([`data-quality`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Adata-quality),
  [`refactor`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Arefactor),
  [`oss-hygiene`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Aoss-hygiene),
  [`fhir`](https://github.com/TomoOkuyama/clinosim/issues?q=is%3Aopen+label%3Afhir),
  …).
- **Recently completed**: see the [CHANGELOG](https://github.com/TomoOkuyama/clinosim/blob/master/CHANGELOG.md).

Design notes and architectural decisions live under
[`docs/design-notes/`](https://github.com/TomoOkuyama/clinosim/tree/master/docs/design-notes)
and (as they harden)
[`docs/architecture/`](https://github.com/TomoOkuyama/clinosim/tree/master/docs/architecture).
Session-scoped historical prompts are archived under
[`docs/history/session-prompts/`](https://github.com/TomoOkuyama/clinosim/tree/master/docs/history/session-prompts).

## Contributing to the roadmap

- Propose a new item by opening a GitHub Issue with the appropriate labels.
- Reference the Issue number in any design note or PR that implements it —
  this keeps the roadmap connected to the code without duplicating status
  in a static file.
- See
  [CONTRIBUTING.md](https://github.com/TomoOkuyama/clinosim/blob/master/CONTRIBUTING.md)
  for the PR flow.
