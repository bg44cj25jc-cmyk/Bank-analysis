"""Force Qt's offscreen platform before PySide6 is imported anywhere.

The GUI tests must run on a build machine with no display. This has to happen
at collection time: once a QApplication exists the platform plugin is fixed.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
