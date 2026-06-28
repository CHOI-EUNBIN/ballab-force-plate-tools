"""Shared pytest setup for the core-engine regression tests.

Adds the project root (the parent of ``core/``) to ``sys.path`` so the tests can
``import core.*`` no matter what directory pytest is launched from. These tests
are headless and pure-numpy: they never import Qt, so the engine can be verified
without launching the app.
"""

import os
import sys

# tests/ lives directly under the project root; add that root to sys.path.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
