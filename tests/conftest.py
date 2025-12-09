"""
Pytest configuration file for test discovery and setup.

This file is automatically loaded by pytest before running tests.
"""

import sys
import os
from pathlib import Path

# Add project root to Python path so tests can import utils, veo_generator, etc.
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
