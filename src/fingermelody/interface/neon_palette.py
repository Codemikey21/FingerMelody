"""Colores estables por nota compartidos por carretera y piano."""
from PySide6.QtGui import QColor

BACKGROUND = "#03050d"
_COLORS = dict(zip(
    ("C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5"),
    ("#18dfff", "#20caff", "#329aff", "#268eff", "#407dff",
     "#9560ff", "#af57ff", "#c24fff", "#cd51ff", "#df60ff"),
))


def note_color(note: str) -> QColor:
    return QColor(_COLORS.get(note, "#329aff"))


def alpha(color: QColor, opacity: int) -> QColor:
    result = QColor(color)
    result.setAlpha(opacity)
    return result
