"""
pytest configuration for the backend test suite.

Adds the backend root to sys.path so all `from modules.xxx import ...`
imports resolve correctly when running pytest from the project root or
from the backend/ directory.
"""

import sys
import os

# Ensure `backend/` is on the path regardless of where pytest is invoked from
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
