"""Dark theme stylesheet and inline SVG icons for the PyQt6 interface.

Icons are defined as SVG source in this file and rasterized at runtime rather
than shipped as .png assets: one path definition renders crisply at every DPI
scaling factor, and the accent colour is substituted per call so an icon can be
recoloured for a disabled or hovered state without a second asset.

Nothing here imports Qt at module level, so the palette constants can be read
(and tested) in an environment with no display and no PyQt6 installed.
"""

from __future__ import annotations

# Tech-dark palette. Kept as plain constants so tests can assert on them and so
# the stylesheet below has a single source of truth.
BG = "#0F172A"
SURFACE = "#1E293B"
SURFACE_ALT = "#172033"
BORDER = "#334155"
ACCENT = "#06B6D4"
ACCENT_HOVER = "#22D3EE"
ACCENT_PRESSED = "#0891B2"
TEXT = "#E2E8F0"
TEXT_MUTED = "#94A3B8"
SUCCESS = "#10B981"
WARNING = "#F59E0B"
DANGER = "#EF4444"

STATUS_COLORS = {
    "queued": TEXT_MUTED,
    "converting": ACCENT,
    "success": SUCCESS,
    "skipped": WARNING,
    "error": DANGER,
    "warning": WARNING,
}

_ICONS: dict[str, str] = {
    # Rounded document with a folded corner.
    "document": (
        '<path d="M6 2.75h7.5L19.25 8.5v12.75a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5'
        'V4.25A1.5 1.5 0 0 1 6 2.75Z"/><path d="M13.5 2.75V8.5h5.75"/>'
    ),
    # Tray with a downward arrow: add / import files.
    "add": '<path d="M12 4v10m0 0 4-4m-4 4-4-4"/><path d="M4 17v2.5h16V17"/>',
    # Play triangle: start the batch.
    "convert": '<path d="M7 5.5 19 12 7 18.5Z"/>',
    # Square: cancel the running batch.
    "cancel": '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    # Two offset sheets: copy to clipboard.
    "copy": (
        '<rect x="9" y="9" width="11" height="12" rx="2"/>'
        '<path d="M15 5.5H6a2 2 0 0 0-2 2V16"/>'
    ),
    # Open folder.
    "folder": '<path d="M3.5 6.5h6l2 2.5h9v9.5a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5Z"/>',
    # Arrow leaving a bracket: hand off to the sandbox.
    "bridge": (
        '<path d="M13.5 4.5H19a1.5 1.5 0 0 1 1.5 1.5v12a1.5 1.5 0 0 1-1.5 1.5h-5.5"/>'
        '<path d="M3.5 12h10m0 0-3.5-3.5M13.5 12 10 15.5"/>'
    ),
    # Broom: sanitize / clear.
    "clear": '<path d="M4.5 19.5 12 12m3-3 4.5-4.5"/><path d="M4.5 19.5h6l3-3-3-3-6 6Z"/>',
}


def icon_svg(name: str, color: str = ACCENT, size: int = 20) -> bytes:
    """Return the raw SVG document for icon *name* stroked in *color*."""
    body = _ICONS.get(name, _ICONS["document"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="{size}" height="{size}" fill="none" stroke="{color}" '
        f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    ).encode("utf-8")


def make_icon(name: str, color: str = ACCENT, size: int = 20):
    """Rasterize icon *name* into a ``QIcon``.

    Returns an empty ``QIcon`` if Qt's SVG module is unavailable rather than
    raising: a missing icon must never stop the window from opening.
    """
    from PyQt6.QtCore import QSize, Qt
    from PyQt6.QtGui import QIcon, QPainter, QPixmap

    try:
        from PyQt6.QtSvg import QSvgRenderer
    except ImportError:  # pragma: no cover - PyQt6 always ships QtSvg
        return QIcon()

    renderer = QSvgRenderer(icon_svg(name, color, size))
    if not renderer.isValid():  # pragma: no cover - defensive
        return QIcon()

    # Render at 2x and let Qt downscale, so the icon stays sharp on the
    # 150%/200% display scaling that Windows laptops ship with by default.
    pixmap = QPixmap(QSize(size * 2, size * 2))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return QIcon(pixmap)


STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Leelawadee UI", "Noto Sans Thai", Arial, sans-serif;
    font-size: 13px;
}}

QLabel#Title {{
    font-size: 21px;
    font-weight: 600;
    color: {ACCENT};
}}
QLabel#Subtitle {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}
QLabel#SectionLabel {{
    font-size: 11px;
    font-weight: 600;
    color: {TEXT_MUTED};
    letter-spacing: 1px;
}}

QFrame#Card {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

QFrame#DropZone {{
    background-color: {SURFACE_ALT};
    border: 2px dashed {BORDER};
    border-radius: 14px;
}}
QFrame#DropZone[hover="true"] {{
    background-color: {SURFACE};
    border: 2px dashed {ACCENT};
}}
QLabel#DropHint {{
    color: {TEXT_MUTED};
    font-size: 14px;
}}
QLabel#DropTitle {{
    color: {ACCENT};
    font-size: 17px;
    font-weight: 600;
}}

QLabel#QualityBadge {{
    padding: 3px 10px;
    border-radius: 10px;
    font-weight: 600;
    font-size: 11px;
    background-color: {SURFACE_ALT};
    color: {TEXT_MUTED};
}}
QLabel#QualityBadge[status="success"] {{ background-color: rgba(16, 185, 129, 0.15); color: {SUCCESS}; }}
QLabel#QualityBadge[status="warning"] {{ background-color: rgba(245, 158, 11, 0.15); color: {WARNING}; }}
QLabel#QualityBadge[status="error"] {{ background-color: rgba(239, 68, 68, 0.15); color: {DANGER}; }}
QLabel#QualityBadge[status="skipped"] {{ background-color: rgba(245, 158, 11, 0.15); color: {WARNING}; }}

QLabel#WarningBanner {{
    background-color: rgba(245, 158, 11, 0.12);
    border: 1px solid {WARNING};
    border-radius: 8px;
    padding: 8px 12px;
    color: {WARNING};
    font-weight: 600;
}}

QLabel#Thumbnail {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QLabel#MetaFooter {{
    font-size: 11px;
    color: {TEXT_MUTED};
    padding: 2px 0px;
}}

QPushButton {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 16px;
    color: {TEXT};
    font-weight: 600;
}}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT_HOVER}; }}
QPushButton:pressed {{ background-color: {SURFACE_ALT}; }}
QPushButton:disabled {{ color: #475569; border-color: #263449; }}

QPushButton#Primary {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: #04212B;
}}
QPushButton#Primary:hover {{ background-color: {ACCENT_HOVER}; color: #04212B; }}
QPushButton#Primary:pressed {{ background-color: {ACCENT_PRESSED}; }}
QPushButton#Primary:disabled {{ background-color: #1B3843; border-color: #1B3843; color: #4B6470; }}

QPushButton#Danger:hover {{ border-color: {DANGER}; color: {DANGER}; }}

QLineEdit, QComboBox, QSpinBox {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {ACCENT_PRESSED};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_PRESSED};
    outline: none;
}}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background-color: {SURFACE_ALT};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

QTreeWidget, QPlainTextEdit {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    selection-background-color: {ACCENT_PRESSED};
}}
QTreeWidget::item {{ padding: 5px 2px; }}
QHeaderView::section {{
    background-color: {SURFACE};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px 8px;
    font-weight: 600;
}}

QProgressBar {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    height: 20px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 7px;
}}

QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_PRESSED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER}; border-radius: 5px; min-width: 30px;
}}

QSplitter::handle {{ background: transparent; }}
QStatusBar {{ color: {TEXT_MUTED}; border-top: 1px solid {BORDER}; }}
QToolTip {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {ACCENT};
    padding: 5px;
}}
"""
