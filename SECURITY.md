# Security Policy

## Supported versions

clinosim is an independent personal project on a pre-1.0 release track.
Security fixes are only backported to the **most recent released
version**. Anything older should upgrade first.

| Version | Supported |
|---------|-----------|
| 0.2.x   | ✅ |
| < 0.2   | ❌ |

## Reporting a vulnerability

**Please do not report security issues by opening a public GitHub Issue,
GitHub Discussion, or pull request.** Public reports let attackers know
about the problem before a fix is available.

Instead, report vulnerabilities privately through GitHub's built-in
**Security Advisories** channel:

- Go to
  [https://github.com/TomoOkuyama/clinosim/security/advisories/new](https://github.com/TomoOkuyama/clinosim/security/advisories/new)
  and file a draft advisory.
- Include a clear description of the issue, the impact (what data /
  behavior can be compromised), a proof-of-concept or minimal
  reproduction, and any known mitigation.

Draft advisories are only visible to you and the project maintainer
until they are published.

## What counts as a security issue

Because clinosim is a **synthetic data generator** and does not touch
real patient data, the interesting security surface is small but not
empty. Please **do** report:

- Code execution / injection via malformed YAML, template, or CLI input.
- Dependency vulnerabilities that clinosim materially exposes (not
  transitive noise that never reaches user input).
- Path-traversal or arbitrary-write in the CIF / FHIR output writers.
- Determinism-affecting issues that would silently corrupt reproducible
  research output (treated as a data-integrity vulnerability).

Please **do not** report:

- Concerns that generated synthetic data "resembles" a real person —
  the data is randomly generated from population-level distributions
  and any resemblance is coincidental. See the README disclaimer.
- Requests to add authentication / authorization — clinosim is a CLI,
  not a service.

## Response timeline

This is a personal project with no on-call rotation, so please be
patient. Best-effort targets:

| Step | Target |
|---|---|
| Acknowledgement | 5 business days |
| Assessment & severity | 10 business days |
| Fix or mitigation released | 90 days from acknowledgement, or coordinated with the reporter |
| Public advisory published | After a fix is released |

Reporters are credited by name in the published advisory unless they
prefer to remain anonymous.

## Scope

This policy covers the `clinosim` package on the master branch of this
repository and the wheel / sdist artifacts published from it. It does
not cover third-party forks or downstream distributions.
