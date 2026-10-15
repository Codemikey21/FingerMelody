"""Cápsulas de las últimas notas. No guarda imágenes ni toca el audio."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

_FADE_PER_SECOND = 6.0
_TICK_MS = 32


class NoteHistoryStrip(QWidget):
    """Lista corta de cápsulas. Una sola pintura, sin crear un widget por nota."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("historyStrip")
        self.setMinimumHeight(34)
        self.setMaximumHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._rows: tuple[tuple[str, str, str], ...] = ()
        self._opacity: dict[tuple[str, str, str], float] = {}
        self._font = QFont("Segoe UI", 10)
        self._font.setBold(True)
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._on_tick)

    def sizeHint(self) -> QSize:  # noqa: N802 - firma de Qt
        return QSize(280, 68)

    def set_rows(self, rows: tuple[tuple[str, str, str], ...]) -> None:
        """Cada fila es nota, origen visible y detalle. Las nuevas aparecen en fade."""
        fresh = tuple(rows)
        if fresh == self._rows:
            return
        alive = set(fresh)
        previous = self._opacity
        self._opacity = {row: previous.get(row, 0.0) for row in fresh}
        self._rows = fresh
        for row in list(previous):
            if row not in alive:
                previous.pop(row, None)
        self.setToolTip(self.caption())
        self._arm_timer()
        self.update()

    def caption(self) -> str:
        if not self._rows:
            return "Historial: —"
        return "\n".join(f"{note} · {origin} · {who}" for note, origin, who in self._rows)

    def opacity_of(self, row: tuple[str, str, str]) -> float:
        return self._opacity.get(row, 0.0)

    def advance(self, seconds: float) -> None:
        self._tick(max(0.0, seconds))

    def paintEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(self._font)
        if not self._rows:
            painter.setPen(QColor("#9aa3b5"))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "Historial: —")
            painter.end()
            return
        metrics = painter.fontMetrics()
        x = 0.0
        y = 2.0
        height = 28.0
        limit = max(1.0, float(self.width()))
        for row in self._rows:
            note, origin, _who = row
            width = min(limit, max(86.0, metrics.horizontalAdvance(f"{note}  {origin}") + 22.0))
            if x > 0.0 and x + width > limit:
                x = 0.0
                y += height + 6.0
            _paint_capsule(painter, QRectF(x, y, width, height), note, origin, self._opacity.get(row, 1.0))
            x += width + 6.0
        painter.end()

    def _on_tick(self) -> None:
        self._tick(_TICK_MS / 1000.0)

    def _tick(self, seconds: float) -> None:
        for row in self._rows:
            self._opacity[row] = min(1.0, self._opacity.get(row, 0.0) + seconds * _FADE_PER_SECOND)
        self._arm_timer()
        self.update()

    def _arm_timer(self) -> None:
        pending = any(self._opacity.get(row, 1.0) < 0.99 for row in self._rows)
        if pending and not self._timer.isActive():
            self._timer.start()
        elif not pending and self._timer.isActive():
            self._timer.stop()


def _paint_capsule(painter: QPainter, rect: QRectF, note: str, origin: str, opacity: float) -> None:
    painter.save()
    painter.setOpacity(max(0.0, min(1.0, opacity)))
    accent = QColor("#3ee0d0") if origin == "gesto" else QColor("#c4b6ff")
    painter.setPen(QPen(accent, 1))
    painter.setBrush(QColor("#222636"))
    painter.drawRoundedRect(rect, 12, 12)
    painter.setPen(QColor("#f4f1ff"))
    painter.drawText(rect.adjusted(8, 0, -8, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), note)
    painter.setPen(accent)
    painter.drawText(rect.adjusted(8, 0, -8, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), origin)
    painter.restore()
