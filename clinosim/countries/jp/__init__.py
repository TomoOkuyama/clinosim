"""Japan-only algorithms (docs/design-guides/country-profile-spec.md §4).

Each module registers a named implementation with
:func:`clinosim.country_profile.register_implementation`; the JP country
profile (``clinosim/locale/jp/country.yaml`` ``implementations``) selects it.
The modules are imported through ``IMPLEMENTATION_MODULES`` in
``clinosim/country_profile.py`` (explicit registration, no discovery).
"""
