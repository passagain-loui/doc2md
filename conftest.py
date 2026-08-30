"""pytest configuration shared by every test module."""

import os
import sys
from pathlib import Path

# Add project root to sys.path for imports
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Qt needs a platform plugin before the first QApplication is constructed. The
# GUI tests never call show(), so the offscreen plugin is enough and keeps the
# suite runnable over SSH, in CI, and inside the packaging job.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
