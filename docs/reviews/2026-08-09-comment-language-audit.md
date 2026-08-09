# Source-code comment-language audit — 2026-08-09

**Scope**: every `clinosim/**/*.py` file, comment / docstring content
only (string literals, YAML data, and Japanese-language identifiers in
external spec vocabulary are out of scope for this audit).

**Baseline commit**: `master` after PRs #648 – #657 (post-Phase 4).

**Policy references**:

- [`docs/design-guides/documentation-and-code-quality-policy.md`](../design-guides/documentation-and-code-quality-policy.md)
  §4 (source-code comment language)
- Same policy §3 (self-contained OSS quality; prohibits session
  identifiers in any repo-committed document, including source-code
  comments)

**Purpose**: publish the baseline so subsequent per-module-group
cleanup PRs can be scoped, prioritised, and measured. This is a
**read-only audit** — no source-code comment is edited by the PR that
publishes this file.

## 1. What §4 requires

**Default**: English. Every comment (line comment, docstring, TODO /
FIXME marker, block comment) is written in English unless it falls
into one of three explicitly permitted Japanese-comment categories:

1. **JP-Core / JP-CLINS profile invariants** — spec-constraint
   documentation whose surrounding variable / element names come from
   the Japanese spec vocabulary.
2. **JLAC10 / JJ1017 / MEDIS code-system specifics** — quotations or
   explanations of Japanese code-system entries.
3. **Verbatim quotes from Japanese authoritative sources** —
   厚生労働省 通知, JAHIS technical reports, jpfhir.jp implementation
   guides. Quote in Japanese and add a one-line English gloss.

A comment that only says "Japanese output" or "JP handling" without
quoting the spec text does **not** qualify.

## 2. §3 constraint — no session identifiers

Independent of §4, policy §3 prohibits session identifiers
(`session-NN`, "last session", "previous session", etc.) in any
repo-committed document, including source-code comments.

Baseline count (reproduce):

```bash
python3 - <<'PY'
import re, pathlib
sess = re.compile(r'session[\s-]?\d+', re.IGNORECASE)
count = 0; files = set()
for f in sorted(pathlib.Path('clinosim').rglob('*.py')):
    text = f.read_text(encoding='utf-8')
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('#') or '"""' in line or "'''" in line:
            if sess.findall(line):
                count += len(sess.findall(line))
                files.add(str(f))
print(count, 'refs across', len(files), 'files')
PY
```

Result: **465 `session NN` references across 91 files** — every one is
a §3 violation that the sweep PRs must remove (not translate).

## 3. Baseline: Japanese comment characters

Reproduce:

```bash
python3 - <<'PY'
import re, pathlib
jp = re.compile(r'[぀-ヿ㐀-鿿]')
per_dir = {}; per_file = {}
for f in sorted(pathlib.Path('clinosim').rglob('*.py')):
    text = f.read_text(encoding='utf-8')
    n = 0
    in_ds = False
    for line in text.splitlines():
        s = line.strip()
        if '"""' in s or "'''" in s:
            n += len(jp.findall(line))
            if (s.count('"""') + s.count("'''")) % 2 == 1:
                in_ds = not in_ds
            continue
        if in_ds or s.startswith('#'):
            n += len(jp.findall(line))
    if n:
        per_file[str(f)] = n
        per_dir[str(f.parent).replace('clinosim/', '', 1)] = per_dir.get(str(f.parent).replace('clinosim/', '', 1), 0) + n
print('total', sum(per_dir.values()), 'chars in comments across', len(per_file), 'files')
PY
```

Result: **13,057 Japanese characters in comments across 99 files**.

### Per-directory rollup (top 15)

| Directory | JP chars in comments | Category default per §4 |
|---|---:|---|
| `simulator/` | 1,793 | **Translate** (simulator core is non-JP business logic) |
| `modules/output/fhir_r4/documents/` | 1,437 | **Retain most** (JP-CLINS Composition profile invariants) |
| `modules/document/narrative/` | 1,431 | **Case-by-case** (mixed template + narrative internals) |
| `modules/health_checkup/` | 1,329 | **Retain most** (JP opt-in module — 労働安全衛生法 事業者健診 invariants) |
| `modules/output/fhir_r4/labs/` | 963 | **Retain most** (JLAC10 code-system specifics) |
| `modules/output/fhir_r4/medications/` | 952 | **Retain most** (JP-CLINS MedicationRequest / YJ / HOT invariants) |
| `modules/output/fhir_r4/post_process/` | 823 | **Retain most** (JP-CLINS validator error refs, JP display strings) |
| `modules/output/fhir_r4/lib/` | 652 | **Retain most** (JP-Core / JP-CLINS profile URIs, JP display strings) |
| `types/` | 502 | **Case-by-case** (some JP-CLINS field docstrings, some project-phase notes) |
| `eval/axes/` | 453 | **Case-by-case** (mostly JP FHIR path evaluation notes) |
| `modules/imaging/` | 426 | **Case-by-case** (JJ1017 references retain, Python-arch notes translate) |
| `modules/output/fhir_r4/encounters/` | 395 | **Case-by-case** |
| `modules/output/fhir_r4/conditions/` | 327 | **Case-by-case** (ICD-10-JP / SNOMED coding) |
| `modules/output/fhir_r4/demographics/` | 266 | **Case-by-case** (JP Patient / Practitioner fields) |
| `modules/document/` | 228 | **Case-by-case** |

### Top-20 files by JP-comment chars

| File | JP chars | Category |
|---|---:|---|
| `modules/document/narrative/template_generator.py` | 1,396 | Case-by-case (translate Python-internals notes; retain JP display-fallback string constants such as `_GENERIC_FALLBACK_JA = "特記事項なし"` which are output data, not comments) |
| `simulator/memoize.py` | 1,378 | **Translate** (simulator-core memoisation explanation) |
| `modules/health_checkup/engine.py` | 1,230 | Retain (JP opt-in module invariants, 健診項目 spec) |
| `modules/output/fhir_r4/documents/composition.py` | 1,157 | Retain (JP-CLINS Composition profile invariants, HL7 fixedUri references) |
| `modules/output/fhir_r4/medications/medications.py` | 952 | Retain (JP-CLINS MedicationRequest MS / fixedString invariants, YJ / HOT / MEDIS coding dispatch) |
| `modules/output/fhir_r4/post_process/populate.py` | 492 | Retain (JP display strings `製剤量` / `日`; JP validator error refs) |
| `modules/output/fhir_r4/lib/common.py` | 341 | Retain (JP display strings `社会歴`; JP_ConditionSeverity_CS invariants) |
| `eval/axes/clinical.py` | 340 | Case-by-case (retain JP FHIR emit-path judgement notes; translate session-identifier refs) |
| `types/document.py` | 305 | Case-by-case (retain 厚労省4帳票 spec anchor; translate β-JP-1 project-phase notes) |
| `modules/output/fhir_r4/labs/diagnostic_report.py` | 284 | Retain (JLAC10 / LOINC dual-coding invariants) |
| `modules/imaging/inference.py` | 277 | **Translate** (call-site inference logic; not JJ1017-specific) |
| `simulator/diff.py` | 265 | **Translate** (simulator internals) |
| `modules/output/fhir_r4/labs/microbiology.py` | 262 | Retain (JP-CLINS microbiology profile) |
| `modules/output/fhir_r4/documents/document_reference_checkup.py` | 259 | Retain (JP-eCheckup DocumentReference invariants) |
| `modules/output/fhir_r4/conditions/conditions.py` | 252 | Retain (ICD-10-JP / SNOMED coding invariants) |
| `modules/output/fhir_r4/labs/imaging_study.py` | 213 | Retain (JJ1017 / DICOM coding) |
| `modules/output/fhir_r4/encounters/facility.py` | 210 | Retain (JP-CLINS Location / Organization) |
| `seeding.py` | 175 | **Translate** (RNG sub-seeding internals) |
| `modules/output/fhir_r4/demographics/practitioner.py` | 171 | Retain (JP-Core Practitioner invariants) |
| `modules/output/fhir_r4/encounters/encounter.py` | 166 | Retain (JP-CLINS Encounter profile) |

## 4. Cleanup PR roadmap

Follow-up PRs, ordered by pragmatic ease of review (each with a
scoped module-group so the diff stays focused):

- **PR-B — `simulator/` sweep** — ~1,793 chars to translate, plus
  most of the 465 session-identifier violations are here. Highest
  translation ROI; no JP-CLINS content to worry about.
- **PR-C — `modules/document/narrative/` sweep** — ~1,431 chars.
  Case-by-case; retain the JP display-string constants and any
  narrative content that quotes JP clinical vocabulary; translate
  Python-architecture notes.
- **PR-D — `types/` + `eval/axes/` + `modules/imaging/` sweep** —
  ~1,300 chars combined. Mix of clinical-adjacent and project-phase
  notes; case-by-case.
- **PR-E — Session-identifier scrub across the retained-JP files** —
  the 465 `session NN` references that survive the earlier PRs (all
  the fhir_r4/ and health_checkup/ files whose Japanese content is
  §4-permitted). Removes the §3 violations without touching the
  §4-permitted content.
- **PR-F (optional)** — final pass: any file that gains a JP
  identifier or fresh JP comment during the campaign gets a §4
  compliance check.

Estimated split of the 13,057 JP-comment chars:

| Disposition | Estimated share | Estimated char count |
|---|---:|---:|
| Retain per §4 (JP-CLINS / JLAC10 / JJ1017 / MEDIS / verbatim spec quote) | ~55 – 65 % | ~7,000 – 8,500 |
| Translate per §4 (default English) | ~30 – 40 % | ~4,000 – 5,500 |
| Remove per §3 (session identifiers, project-phase gossip) | ~5 – 10 % | ~700 – 1,300 |

## 5. Retention decision rules (concrete)

Reviewer applies the following to each JP-comment site during a
sweep PR:

- **Retain** when the comment:
  - documents a JP-CLINS / JP-Core profile invariant (MS elements,
    fixedString / fixedUri, required binding, cardinality that comes
    from `jpfhir.jp`);
  - quotes / explains a JLAC10 / JJ1017 / MEDIS entry that will
    appear in the emitted resource;
  - is a verbatim quotation from 厚生労働省 通知, JAHIS technical
    report, or jpfhir.jp implementation guide (must carry a one-line
    English gloss below the quote).
- **Translate** when the comment:
  - explains simulator / audit / eval internals in Python terms
    (`memoize.py`, `diff.py`, `seeding.py`, `inference.py`, etc.);
  - describes a Python architecture decision without any JP spec
    anchor (e.g. "N806 lint violation avoidance", "opt-in gate");
  - contains a JP idiom that has an obvious English equivalent
    ("特記事項なし" as `_GENERIC_FALLBACK_JA` is a string literal, not
    a comment — leave the *literal* alone; but a comment saying
    「特記事項なしをフォールバック」 becomes `"no special findings"
    fallback`).
- **Remove** when the comment contains:
  - a `session NN` reference (`session 47`, `session 59`, etc.);
  - a project-phase gossip anchor with no permanent meaning
    ("β-JP-1 chain 1a", "α-min-2 で追加");
  - a TODO / FIXME that has been superseded by later work.

When the same comment mixes categories, split the line: keep the
spec-anchored sentence, translate or remove the rest.

## 6. Non-goals

- The sweep does not touch string literals used as OUTPUT data
  (e.g. Japanese display strings emitted into FHIR, JP narrative
  templates, JP config values). Those are data, not comments.
- Docstrings inside JP-only modules where the entire docstring is a
  spec-invariant explanation may keep their Japanese narrative as
  one block, with an English one-line summary at the top of the
  docstring.

## 7. Success criteria (per sweep PR)

- Every JP-comment site under the PR's module group has been
  reviewed and either retained (per §4), translated (per §4), or
  removed (per §3).
- No `session NN` reference remains in any file touched by the PR.
- Unit tests and integration tests pass; comment-only edits should
  not affect any output.
- The PR body links back to this audit report and states which
  files it touched and which category each JP-content site fell into.

## Change history

- **2026-08-09** — Baseline established. Published as PR-A of the
  comment-sweep campaign for [Issue #641](https://github.com/TomoOkuyama/clinosim/issues/641).
  Follow-up PRs land the actual sweeps per §4-5 of this report.
