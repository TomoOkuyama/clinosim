"""Simulator phase runners sub-package.

Each file carries one top-level run_* phase extracted from
``clinosim/simulator/engine.py`` as part of the full-review Phase C
engine split (CRITICAL C2). The runners are called in sequence from
``run_beta`` with shared state threaded in explicitly.
"""
