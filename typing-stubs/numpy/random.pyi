"""Local numpy stub shim (session 52 Type check chain).

numpy>=2.5 stubs use PEP 695 ``type X = Y`` syntax which requires
``python_version = "3.12"``; parsing them under our target 3.11 hard-fails
with ``[syntax]`` and halts mypy before any of our source is checked.
This shim replaces the real stub with ``Any`` so mypy sees ``numpy`` as
untyped. Remove once mypy backports PEP 695 stub parsing OR the project's
minimum Python bumps to 3.12.
"""
from typing import Any

def __getattr__(name: str) -> Any: ...
