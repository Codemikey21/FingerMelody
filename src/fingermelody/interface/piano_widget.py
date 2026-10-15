"""Piano de las diez notas naturales. No reproduce audio: emite la nota pulsada."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

WHITE_NOTES = ("C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5")
# Tecla negra entre dos blancas cuando el intervalo es de un tono.
_BLACK_AFTER = frozenset({0, 1, 3, 4, 5, 7, 8})
_CLICK_SECONDS = 0.22


class PianoWidget(QWidget):
    """Teclado reconocible. Las teclas negras se dibujan y no suenan."""

    note_pressed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("piano")
        self.setMinimumHeight(150)
        self.setMaximumHeight(190)
        self.setMinimumWidth(520)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gesture: set[str] = set()
        self._clicks: dict[str, float] = {}
        self._captions: dict[str, str] = {}
        self._hover: str | None = None
        self._held: str | None = None
        self._font = QFont("Segoe UI", 10)
        self._font.setBold(True)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._expire_clicks)

    def sizeHint(self) -> QSize:  # noqa: N802 - firma de Qt
        return QSize(900, 168)

    @property
    def note_names(self) -> tuple[str, ...]:
        return WHITE_NOTES

    def set_captions(self, captions: dict[str, str]) -> None:
        self._captions = dict(captions)

    def set_gesture_notes(self, notes: set[str]) -> None:
        """Ilumina las notas que el gesto tiene activas. No emite sonido."""
        cleaned = {note for note in notes if note in WHITE_NOTES}
        if cleaned == self._gesture:
            return
        self._gesture = cleaned
        self.update()

    def pulse_click(self, note: str) -> None:
        """Mantiene la tecla iluminada un instante después del clic."""
        if note not in WHITE_NOTES:
            return
        self._clicks[note] = time.monotonic() + _CLICK_SECONDS
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def clear_clicks(self) -> None:
        if not self._clicks:
            return
        self._clicks.clear()
        self._timer.stop()
        self.update()

    def lit_notes(self) -> set[str]:
        alive = {note for note, until in self._clicks.items() if until > time.monotonic()}
        return set(self._gesture) | alive

    def play_key(self, note: str) -> None:
        """Mismo camino que un clic sobre la tecla blanca."""
        if note not in WHITE_NOTES:
            return
        self.note_pressed.emit(note)

    def white_rects(self) -> list[tuple[str, QRectF]]:
        area = self.rect().adjusted(12, 12, -12, -12)
        count = len(WHITE_NOTES)
        gap = 4.0
        width = max(1.0, (area.width() - gap * (count - 1)) / count)
        rects: list[tuple[str, QRectF]] = []
        x = float(area.left())
        for name in WHITE_NOTES:
            rects.append((name, QRectF(x, float(area.top()), width, float(area.height()))))
            x += width + gap
        return rects

    def black_rects(self) -> list[QRectF]:
        whites = self.white_rects()
        rects: list[QRectF] = []
        for index, (_name, rect) in enumerate(whites):
            if index not in _BLACK_AFTER:
                continue
            following = whites[index + 1][1]
            width = rect.width() * 0.62
            height = rect.height() * 0.58
            center = (rect.right() + following.left()) / 2.0
            rects.append(QRectF(center - width / 2.0, rect.top(), width, height))
        return rects

    def note_at(self, pos) -> str | None:
        point = QPointF(pos)
        for black in self.black_rects():
            if black.contains(point):
                return None
        for name, rect in self.white_rects():
            if rect.contains(point):
                return name
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        if event.button() != Qt.MouseButton.LeftButton:
            return
        note = self.note_at(event.position())
        self._held = note
        if note is not None:
            self.play_key(note)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        self._held = None
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        note = self.note_at(event.position())
        if note == self._hover:
            return
        self._hover = note
        self.setToolTip(self._captions.get(note, "") if note else "")
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        self._hover = None
        self._held = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#2c3142"), 1))
        painter.setBrush(QColor("#141722"))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 16, 16)

        now = time.monotonic()
        for name, rect in self.white_rects():
            lit = name in self._gesture or self._clicks.get(name, 0) > now
            if lit:
                color = QColor("#6d5ef5") if name == self._held else QColor("#3ee0d0")
            elif name == self._hover:
                color = QColor("#f7f4ff")
            else:
                color = QColor("#ebe7f6")
            painter.setPen(QPen(QColor("#241c40") if lit else QColor("#c9c4d8"), 1))
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(QColor("#07141a") if lit else QColor("#1c2030"))
            font = QFont(self._font)
            font.setPointSize(8 if rect.width() < 48 else 10)
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(2, rect.height() * 0.62, -2, -6),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                name,
            )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1b1c24"))
        for rect in self.black_rects():
            painter.drawRoundedRect(rect, 5, 5)
        painter.end()

    def _expire_clicks(self) -> None:
        now = time.monotonic()
        expired = [note for note, until in self._clicks.items() if until <= now]
        if not expired:
            return
        for note in expired:
            del self._clicks[note]
        if not self._clicks:
            self._timer.stop()
        self.update()
