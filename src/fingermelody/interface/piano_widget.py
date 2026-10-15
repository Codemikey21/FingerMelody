"""Piano de las diez notas naturales. No reproduce audio: emite la nota pulsada."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QRadialGradient, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from fingermelody.interface.neon_palette import BACKGROUND, alpha, note_color

WHITE_NOTES = ("C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5")
# Tecla negra entre dos blancas cuando el intervalo es de un tono.
_BLACK_AFTER = frozenset({0, 1, 3, 4, 5, 7, 8})
_PULSE_HOLD = 0.16
_FADE_PER_SECOND = 2.5
_GLOW_PER_SECOND = 3.4
_TICK_MS = 32
_REST = QColor("#ebe7f6")


class PianoWidget(QWidget):
    """Teclado reconocible. Las teclas negras se dibujan y no suenan."""

    note_pressed = Signal(str)
    lanes_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("piano")
        self._integrated = False
        self._ambient_notes = {}
        self._impact_lights = {}
        self.setMinimumHeight(150)
        self.setMaximumHeight(190)
        self.setMinimumWidth(520)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gesture: set[str] = set()
        self._clicks: dict[str, float] = {}
        self._level: dict[str, float] = {}
        self._glow: dict[str, float] = {}
        self._captions: dict[str, str] = {}
        self._hover: str | None = None
        self._held: str | None = None
        self._font = QFont("Segoe UI", 10)
        self._font.setBold(True)
        self._last_tick = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._on_tick)

    def sizeHint(self) -> QSize:  # noqa: N802 - firma de Qt
        return QSize(900, 168)

    def resizeEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        super().resizeEvent(event)
        self.lanes_changed.emit()

    @property
    def note_names(self) -> tuple[str, ...]:
        return WHITE_NOTES

    def level(self, note: str) -> float:
        return self._level.get(note, 0.0)

    def glow(self, note: str) -> float:
        return self._glow.get(note, 0.0)

    def set_impact_lights(self, lighting: dict[str, float]) -> None:
        self._impact_lights = dict(lighting)
        self.update()

    def set_ambient_notes(self, lighting: dict[str, float]) -> None:
        """Reflejo de proximidad visual; no activa teclas ni emite notas."""
        if lighting != self._ambient_notes:
            self._ambient_notes = dict(lighting)
            self.update()

    def set_captions(self, captions: dict[str, str]) -> None:
        self._captions = dict(captions)

    def set_gesture_notes(self, notes: set[str]) -> None:
        """Ilumina las notas que el gesto tiene activas. No emite sonido."""
        cleaned = {note for note in notes if note in WHITE_NOTES}
        if cleaned == self._gesture:
            return
        for note in cleaned - self._gesture:
            self._level[note] = 1.0
        self._gesture = cleaned
        self._arm_timer()
        self.update()

    def pulse_click(self, note: str) -> None:
        """Enciende la tecla y deja que el brillo se apague con un desvanecimiento."""
        if note not in WHITE_NOTES:
            return
        self._clicks[note] = _PULSE_HOLD
        self._level[note] = 1.0
        self._glow[note] = 1.0
        self._arm_timer()
        self.update()

    def clear_clicks(self) -> None:
        """Suelta los clics. La tecla vuelve al reposo por el mismo desvanecimiento."""
        if not self._clicks:
            return
        self._clicks.clear()
        self._arm_timer()
        self.update()

    def advance(self, seconds: float) -> None:
        """Avanza el desvanecimiento. El temporizador usa el mismo paso."""
        self._tick(max(0.0, seconds))

    def lit_notes(self) -> set[str]:
        bright = {note for note, level in self._level.items() if level >= 0.2}
        return set(self._gesture) | set(self._clicks) | bright

    def play_key(self, note: str) -> None:
        """Mismo camino que un clic sobre la tecla blanca."""
        if note not in WHITE_NOTES:
            return
        self.note_pressed.emit(note)

    def white_rects(self) -> list[tuple[str, QRectF]]:
        area = QRectF(self.rect()) if self._integrated else QRectF(self.rect().adjusted(12, 12, -12, -12))
        count = len(WHITE_NOTES)
        gap = 4.0
        width = max(1.0, (area.width() - gap * (count - 1)) / count)
        rects: list[tuple[str, QRectF]] = []
        x = float(area.left())
        for name in WHITE_NOTES:
            rects.append((name, QRectF(x, float(area.top()), width, float(area.height()))))
            x += width + gap
        return rects

    def set_integrated(self, integrated: bool) -> None:
        self._integrated = integrated
        self.lanes_changed.emit()
        self.update()

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
        if self._integrated:
            painter.fillRect(self.rect(), QColor(BACKGROUND))
        else:
            painter.setPen(QPen(QColor("#2c3142"), 1))
            painter.setBrush(QColor("#141722"))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 16, 16)

        for name, rect in self.white_rects():
            level = self._level.get(name, 0.0)
            glow = self._glow.get(name, 0.0)
            sink = 5.0 * level
            key = rect.adjusted(0, sink * 0.45, 0, 0)
            if glow > 0.04:
                halo = note_color(name)
                halo.setAlpha(int(110 * glow))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(halo)
                painter.drawRoundedRect(key.adjusted(-3, -6, 3, 2), 12, 12)
            color = _mix(_REST, note_color(name), level)
            if name == self._held and level > 0.45:
                color = _mix(color, note_color(name).darker(120), 0.45)
            elif name == self._hover and level < 0.12:
                color = QColor("#f7f4ff")
            edge = _mix(QColor("#c9c4d8"), QColor("#241c40"), level)
            painter.setPen(QPen(edge, 1))
            if self._integrated:
                surface = QLinearGradient(key.topLeft(), key.bottomRight())
                surface.setColorAt(0, _mix(QColor("#8b96ae"), note_color(name), level))
                surface.setColorAt(0.16, _mix(QColor("#d0d5df"), note_color(name), level))
                surface.setColorAt(0.8, _mix(QColor("#959eaf"), note_color(name), level))
                surface.setColorAt(1, _mix(QColor("#606b81"), note_color(name), level))
                if name == self._hover and level < 0.12:
                    surface.setColorAt(0.5, QColor("#ecf3ff"))
                painter.setBrush(surface)
            else:
                painter.setBrush(color)
            painter.drawRoundedRect(key, 4 if self._integrated else 8, 4 if self._integrated else 8)
            painter.setPen(_mix(QColor("#1c2030"), QColor("#07141a"), level))
            font = QFont(self._font)
            font.setPointSize(8 if rect.width() < 48 else 10)
            painter.setFont(font)
            painter.drawText(
                key.adjusted(2, key.height() * 0.62, -2, -6),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                name,
            )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1b1c24"))
        for rect in self.black_rects():
            if self._integrated:
                shadow = rect.translated(4, 6)
                painter.setBrush(QColor(0, 0, 0, 75))
                painter.drawRoundedRect(shadow, 3, 3)
                surface = QLinearGradient(rect.topLeft(), rect.bottomRight())
                surface.setColorAt(0, QColor("#3b4356"))
                surface.setColorAt(0.25, QColor("#151a26"))
                surface.setColorAt(0.85, QColor("#060810"))
                surface.setColorAt(1, QColor("#303a4e"))
                painter.setBrush(surface)
            painter.drawRoundedRect(rect, 3, 3)
        if self._integrated:
            painter.setPen(Qt.PenStyle.NoPen)
            for name, rect in self.white_rects():
                strength = self._ambient_notes.get(name, 0.0)
                reflection = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * 0.58)
                color = note_color(name)
                reflection.setColorAt(0, alpha(color, int(75 + 145 * strength)))
                reflection.setColorAt(0.18, alpha(color, int(35 + 100 * strength)))
                reflection.setColorAt(1, alpha(color, 0))
                painter.fillRect(rect, reflection)
                power = self._impact_lights.get(name, 0.0)
                if power > 0:
                    painter.save()
                    painter.setClipRect(rect)
                    painter.translate(rect.center().x(), rect.top())
                    painter.scale(rect.width() * 0.48, rect.height() * 0.85)
                    liquid = QRadialGradient(0, 0, 1)
                    liquid.setColorAt(0, alpha(QColor("#ffffff"), round(255 * power)))
                    liquid.setColorAt(0.14, alpha(color.lighter(160), round(230 * power)))
                    liquid.setColorAt(0.5, alpha(color, round(170 * power)))
                    liquid.setColorAt(1, alpha(color, 0))
                    painter.setBrush(liquid)
                    painter.drawEllipse(QRectF(-1, -1, 2, 2))
                    painter.restore()
                    for offset, length in ((-0.17, 28), (0.07, 48), (0.22, 19)):
                        drip = QLinearGradient(0, rect.top(), 0, rect.top() + length)
                        drip.setColorAt(0, alpha(QColor("#eaffff"), round(230 * power)))
                        drip.setColorAt(1, alpha(color, 0))
                        painter.setBrush(drip)
                        painter.drawRoundedRect(QRectF(rect.center().x() + rect.width() * offset, rect.top(), 4, length), 2, 2)
        painter.end()

    def _on_tick(self) -> None:
        now = time.monotonic()
        self._tick(min(0.05, max(0.0, now - self._last_tick)))
        self._last_tick = now

    def _tick(self, dt: float) -> None:
        overflow: dict[str, float] = {}
        for note in list(self._clicks):
            self._clicks[note] -= dt
            if self._clicks[note] <= 0.0:
                overflow[note] = -self._clicks[note]
                del self._clicks[note]
        notes = set(self._level) | set(self._glow) | set(self._gesture) | set(self._clicks) | set(overflow)
        for note in notes:
            if note not in _WHITE:
                continue
            if note in self._gesture or note in self._clicks:
                level = 1.0
                glow = 1.0 if note in self._clicks else max(0.0, self._glow.get(note, 0.0) - dt * _GLOW_PER_SECOND)
            else:
                step = overflow.get(note, dt)
                level = max(0.0, self._level.get(note, 0.0) - step * _FADE_PER_SECOND)
                glow = max(0.0, self._glow.get(note, 0.0) - step * _GLOW_PER_SECOND)
            if level <= 0.001:
                self._level.pop(note, None)
            else:
                self._level[note] = level
            if glow <= 0.001:
                self._glow.pop(note, None)
            else:
                self._glow[note] = glow
        self._arm_timer()
        self.update()

    def _busy(self) -> bool:
        if self._clicks:
            return True
        if any(glow > 0.01 for glow in self._glow.values()):
            return True
        for note, level in self._level.items():
            if note not in self._gesture and level > 0.01:
                return True
        return any(self._level.get(note, 0.0) < 0.99 for note in self._gesture)

    def _arm_timer(self) -> None:
        if self._busy():
            if not self._timer.isActive():
                self._last_tick = time.monotonic()
                self._timer.start()
            return
        if self._timer.isActive():
            self._timer.stop()


_WHITE = frozenset(WHITE_NOTES)


def _mix(start: QColor, end: QColor, amount: float) -> QColor:
    blend = max(0.0, min(1.0, amount))
    return QColor(
        int(start.red() + (end.red() - start.red()) * blend),
        int(start.green() + (end.green() - start.green()) * blend),
        int(start.blue() + (end.blue() - start.blue()) * blend),
    )
