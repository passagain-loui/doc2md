"""PyQt6 desktop interface for doc2md.

``theme`` is imported first so that ``main_window`` - which reads the palette
at class-definition time - always finds a fully initialized module.
"""

from doc2md.gui import theme
from doc2md.gui.main_window import ConversionWorker, DropZone, MainWindow, collect_files, run_gui

__all__ = [
    "ConversionWorker",
    "DropZone",
    "MainWindow",
    "collect_files",
    "run_gui",
    "theme",
]
