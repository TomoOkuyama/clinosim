"""Simulator phases sub-package.

``run_beta`` (``clinosim/simulator/engine.py``) calls
:func:`_forward_loop.run_forward_loop`, which advances the simulation one
month at a time through a single date-ordered event queue. The other
files each carry one phase (healthcare calendar, ED visits, readmission,
post-discharge follow-up) as the schedule / dispatch functions the loop
calls: scheduling queues events, and dispatch runs each one when the loop
reaches its date. Shared state is threaded in explicitly via
``ForwardContext``.
"""
