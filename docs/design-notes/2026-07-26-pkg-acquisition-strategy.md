# Package Acquisition Strategy for JP-CLINS (Session 70 A2 Design)

**Date**: 2026-07-26  
**Status**: Design only (implementation deferred until decision)  
**Related**: Issue #418, Issue #410 (A gate scope), PR #421 (A1 validation complete)  
**Context**: Session 69 completed JP-CLINS eval gate (PR #421). CI now runs p=10 cohort + gate check successfully. Session 70 must design how to acquire SD + terminology packages for both CI and end-user workflows.

---

## Problem Statement

### Current State

JP-CLINS Lab Observation profile compliance requires two FHIR packages:
1. **clinical-information-sharing#1.12.0** (StructureDefinition + slicing info)
2. **jpfhir-terminology#2.2606.0** (CodeSystems: CoreLabo/InfectionLabo JLAC10/JLAC11 codes)

Current pkg discovery order (`lab_coding_package.py::_find_pkg_files`):
```
1. \$CLINOSIM_JP_CLINS_PKG_DIR (env var override)
2. ~/.fhir/packages/ (standard fhir CLI cache)
3. ../fhir-jp-validator dev fallback
```

### Blockers

**For CI**: PR #421's jp-clins-compliance job needs the packages at runtime. Current workaround is reliance on global `~/.fhir/packages/` or sibling validator checkout. This works locally but:
- CI runner has no pre-installed packages
- CI runner cannot access sibling repo outside the checked-out branch
- Downloads must happen per-run or be baked into Docker image

**For End Users**: No automated acquisition path. Users must:
1. Install `fhir` CLI separately
2. Manually run `fhir install clinical-information-sharing 1.12.0`
3. Manually run `fhir install jpfhir-terminology 2.2606.0`
4. Set `\$CLINOSIM_JP_CLINS_PKG_DIR` or rely on auto-detection

**Silent degradation**: If pkg is missing, generator silently falls back to legacy 5-digit JLAC10 OID (Issue #418). Without explicit pkg acquisition strategy, users cannot easily verify they have the correct version.

---

## Design Goals

1. **CI reproducibility**: jp-clins-compliance job must run in standard GitHub Actions runner without external setup
2. **User experience**: End users should be able to run `clinosim simulate --country JP` with minimal extra steps
3. **Offline resilience**: Downloaded packages should be cached locally to avoid repeated network calls
4. **Transparency**: Clear error messages when pkg acquisition fails
5. **Version pinning**: Deterministic versions (1.12.0 / 2.2606.0) to prevent drift
6. **Minimal dependencies**: Avoid new runtime requirements (ideally no new CLI tools)

---

## Option G1a: fhir CLI Integration

**Approach**: Use the FHIR CLI to query and install packages.

### Pros

- ✅ Reuses existing ecosystem (FHIR CLI is standard)
- ✅ Auto-downloads to `~/.fhir/packages`
- ✅ End users familiar with `fhir install` workflow

### Cons

- ❌ Requires `fhir` CLI in CI runner
- ⚠ Subprocess overhead (~1-2 sec per package)
- ⚠ Version resolution outside clinosim control

### Implementation Size

**Small** (~100 lines)

---

## Option G1b: Direct HTTPS Download + Cache

**Approach**: Directly download JSON files from GitHub release / package server, cache locally.

### Pros

- ✅ Zero runtime dependencies
- ✅ Minimal CI setup
- ✅ Local caching + offline-first
- ✅ Deterministic versions

### Cons

- ⚠ Custom download logic
- ⚠ URL maintenance burden
- ⚠ Network call per missing package

### Implementation Size

**Medium** (~200-300 lines)

---

## Recommended: Hybrid (G1a + G1b Fallback)

**Recommendation**: G1a (fhir CLI) as primary with G1b (direct download) as fallback.

### Advantages

- Primary: Leverages standard ecosystem
- Fallback: Ensures CI + offline users work
- Graceful degradation: Clear error if both fail

### Timeline (Next Sessions)

- **Session 71**: Implement G1a
- **Session 72**: Add G1b fallback
- **Session 73**: Integrate into CI

---

## Comparison Matrix

| Criterion | G1a | G1b | Hybrid |
|-----------|---|---|---|
| **CI ready** | ⚠ Needs setup | ✅ Yes | ✅ Yes |
| **Dependencies** | ❌ fhir CLI | ✅ None | ⚠ Optional |
| **User friendly** | ✅ Standard | ⚠ Custom | ✅ Both |
| **Offline** | ✅ Cached | ✅ Cached | ✅ Both |
| **Version control** | ⚠ fhir | ✅ Hardcoded | ✅ Hardcoded |
| **Code size** | ~100 | ~200 | ~400 |

---

## Open Questions

1. Do `clinical-information-sharing#1.12.0` and `jpfhir-terminology#2.2606.0` have structured GitHub releases?

2. What is package.fhir.org SLA?

3. Should CI cache packages in GitHub Actions artifacts?

4. How to handle version updates (automatic/manual)?

---

## Decision Template (Awaiting Approval)

**Please confirm**:
- [ ] Hybrid (G1a + G1b fallback) — RECOMMENDED
- [ ] G1a only (accept CI setup burden)
- [ ] G1b only (no fhir CLI dependency)
- [ ] Alternative approach

**If approved**, next session will implement with:
- [ ] Checksum verification (SHA256)
- [ ] Retry logic (backoff)
- [ ] Offline mode

---

**Session 70 A2 Design Complete**
