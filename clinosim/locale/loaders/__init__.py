"""Locale loader submodules (hardcoded-review Phase B1).

The historical ``clinosim.locale.loader`` module grew to 1120 lines with
~50 ``@lru_cache`` loaders fanned out across unrelated domains (names,
narrative, FHIR, demographics, …). This package holds the per-domain
loader submodules; ``locale/loader.py`` re-exports from them so every
existing ``from clinosim.locale.loader import load_X`` import keeps
working.
"""
