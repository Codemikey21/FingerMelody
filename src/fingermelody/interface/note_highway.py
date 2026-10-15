"""Carretera de notas del modo guiado. No avanza la canción ni reproduce audio."""

from __future__ import annotations

import random
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

_PIXELS_PER_BEAT = 54.0
_LEAD_BEATS = 2.35
_VISUAL_BEATS_PER_SECOND = 2.05
_TICK_MS = 16
_SLOW_TICK_MS = 32
_MAX_PARTICLES = 36
_REDUCED_PARTICLES = 12
_BAR_COLORS = (QColor("#3ee0d0"), QColor("#6aa8ff"), QColor("#8b7cf7"))
_BAR_GLOW = (QColor("#d9fff8"), QColor("#d6e6ff"), QColor("#e4dcff"))


@dataclass
class _Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    total: float
    radius: float
    color: QColor


@dataclass
class _Ghost:
    x: float
    y: float
    width: float
    height: float
    life: float
    total: float
    color: QColor


@dataclass
class _Flash:
    x: float
    width: float
    life: float
    total: float


class NoteHighway(QWidget):
    """Barras que bajan hasta la línea y esperan. El índice lo impone quien llama."""

    resized = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("noteHighway")
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._lanes: dict[str, tuple[float, float]] = {}
        self._steps: tuple[tuple[str, float], ...] = ()
        self._index = 0
        self._scroll = -_LEAD_BEATS
        self._running = False
        self._paused_motion = False
        self._reduced = False
        self._slow = 0
        self._particles: list[_Particle] = []
        self._ghosts: list[_Ghost] = []
        self._flashes: list[_Flash] = []
        self._rng = random.Random(7)
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._on_tick)

    def resizeEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        super().resizeEvent(event)
        self.resized.emit()

    def set_lanes(self, lanes: tuple[tuple[str, float, float], ...]) -> None:
        """Cada carril es nota, centro horizontal y ancho de la tecla, en este widget."""
        self._lanes = {note: (center, width) for note, center, width in lanes}
        self.update()

    def lane_center(self, note: str) -> float | None:
        lane = self._lanes.get(note)
        if lane is None:
            return None
        return lane[0]

    def set_chart(self, steps: tuple[tuple[str, float], ...], index: int) -> None:
        """Recibe la canción y el índice ya decidido. No lo incrementa."""
        restarted = index == 0 and (not self._steps or self._index != 0)
        self._steps = tuple(steps)
        self._index = max(0, min(index, len(self._steps)))
        if restarted:
            self._scroll = -_LEAD_BEATS
        target = self._target_beat()
        if self._scroll > target:
            self._scroll = target
        self._arm_timer()
        self.update()

    def set_running(self, running: bool) -> None:
        """Con la sesión en pausa o sin iniciar, las barras no siguen bajando."""
        self._running = running
        self._paused_motion = not running
        self._arm_timer()
        self.update()

    def shutdown(self) -> None:
        """Detiene la animación al cerrar la ventana. No toca la canción."""
        self._running = False
        self._particles.clear()
        self._ghosts.clear()
        self._flashes.clear()
        self._timer.blockSignals(True)
        self._timer.stop()

    def notify_hit(self, note: str) -> None:
        """Efecto visual del acierto. No cambia el índice ni reproduce sonido."""
        rect = self.bar_rect(self._index)
        if rect is not None and self.current_note() == note:
            color = _BAR_COLORS[self._index % len(_BAR_COLORS)]
            self._ghosts.append(_Ghost(rect.x(), rect.y(), rect.width(), rect.height(), 0.42, 0.42, QColor(color)))
            self._flashes.append(_Flash(rect.center().x(), rect.width(), 0.28, 0.28))
        self._spawn(note)
        self._arm_timer()
        self.update()

    def advance_visual(self, seconds: float) -> None:
        """Un paso de la animación. El mismo camino que usa el temporizador."""
        self._step(max(0.0, seconds))

    def waiting(self) -> bool:
        if not self._running or self._index >= len(self._steps):
            return False
        return self._scroll >= self._target_beat() - 1e-4

    def activation_y(self) -> float:
        return max(24.0, float(self.height()) - 16.0)

    def current_note(self) -> str | None:
        if self._index >= len(self._steps):
            return None
        return self._steps[self._index][0]

    def bar_rect(self, index: int) -> QRectF | None:
        if index < 0 or index >= len(self._steps):
            return None
        note, beats = self._steps[index]
        lane = self._lanes.get(note)
        if lane is None:
            return None
        center, key_width = lane
        width = max(10.0, key_width * 0.62)
        height = max(18.0, beats * _PIXELS_PER_BEAT)
        start = self._beat_at(index)
        bottom = self.activation_y() - (start - self._scroll) * _PIXELS_PER_BEAT
        return QRectF(center - width / 2.0, bottom - height, width, height)

    def bar_bottom(self, index: int) -> float | None:
        rect = self.bar_rect(index)
        if rect is None:
            return None
        return rect.bottom()

    def particle_count(self) -> int:
        return len(self._particles)

    def effect_count(self) -> int:
        return len(self._particles) + len(self._ghosts) + len(self._flashes)

    def reduced_quality(self) -> bool:
        return self._reduced

    def paintEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#10131c"))
        painter.drawRect(self.rect())
        self._paint_bars(painter)
        self._paint_ghosts(painter)
        self._paint_line(painter)
        self._paint_particles(painter)
        painter.end()

    def _on_tick(self) -> None:
        self._step(self._timer.interval() / 1000.0)

    def _step(self, seconds: float) -> None:
        if self._running and self._index < len(self._steps):
            target = self._target_beat()
            if self._scroll < target:
                self._scroll = min(target, self._scroll + seconds * _VISUAL_BEATS_PER_SECOND)
        self._age(self._particles, seconds)
        self._age(self._ghosts, seconds)
        self._age(self._flashes, seconds)
        self._watch_quality(seconds)
        self._arm_timer()
        self.update()

    def _target_beat(self) -> float:
        if self._index >= len(self._steps):
            return self._beat_at(len(self._steps))
        return self._beat_at(self._index)

    def _beat_at(self, index: int) -> float:
        total = 0.0
        for position, (_note, beats) in enumerate(self._steps):
            if position >= index:
                break
            total += beats
        return total

    def _spawn(self, note: str) -> None:
        lane = self._lanes.get(note)
        if lane is None:
            return
        center, _width = lane
        amount = 4 if self._reduced else 6 + self._rng.randrange(7)
        cap = _REDUCED_PARTICLES if self._reduced else _MAX_PARTICLES
        y = self.activation_y()
        color = _BAR_COLORS[self._index % len(_BAR_COLORS)]
        for _ in range(amount):
            if len(self._particles) >= cap:
                self._particles.pop(0)
            life = 0.22 + self._rng.random() * 0.2
            self._particles.append(
                _Particle(
                    x=center + self._rng.uniform(-10.0, 10.0),
                    y=y + self._rng.uniform(-4.0, 4.0),
                    vx=self._rng.uniform(-22.0, 22.0),
                    vy=self._rng.uniform(-86.0, -36.0),
                    life=life,
                    total=life,
                    radius=self._rng.uniform(1.6, 3.2),
                    color=QColor(color),
                )
            )

    def _age(self, items: list, seconds: float) -> None:
        alive = []
        for item in items:
            item.life -= seconds
            if item.life <= 0:
                continue
            if isinstance(item, _Particle):
                item.x += item.vx * seconds
                item.y += item.vy * seconds
            elif isinstance(item, _Ghost):
                item.y += 18.0 * seconds
            alive.append(item)
        items[:] = alive

    def _watch_quality(self, seconds: float) -> None:
        if seconds > 0.034:
            self._slow += 1
        else:
            self._slow = max(0, self._slow - 1)
        reduced = self._slow >= 6
        if reduced != self._reduced:
            self._reduced = reduced
            self._timer.setInterval(_SLOW_TICK_MS if reduced else _TICK_MS)

    def _arm_timer(self) -> None:
        if self._busy():
            if not self._timer.isActive():
                self._timer.start()
            return
        if self._timer.isActive():
            self._timer.stop()

    def _busy(self) -> bool:
        if self._particles or self._ghosts or self._flashes:
            return True
        if not self._running or self._index >= len(self._steps):
            return False
        return self._scroll < self._target_beat() - 1e-4

    def _paint_bars(self, painter: QPainter) -> None:
        if not self._lanes:
            return
        view = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        for index in range(self._index, min(len(self._steps), self._index + 8)):
            rect = self.bar_rect(index)
            if rect is None or not rect.intersects(view):
                continue
            color = _BAR_COLORS[index % len(_BAR_COLORS)]
            glow = _BAR_GLOW[index % len(_BAR_GLOW)]
            if index == self._index and self.waiting():
                halo = QColor(glow)
                halo.setAlpha(70)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(halo)
                painter.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), 10, 10)
            if self._reduced:
                painter.setPen(QPen(glow, 1))
                painter.setBrush(color)
            else:
                gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                gradient.setColorAt(0.0, glow)
                gradient.setColorAt(1.0, color)
                painter.setPen(QPen(glow, 1.4))
                painter.setBrush(gradient)
            painter.drawRoundedRect(rect, 7, 7)

    def _paint_ghosts(self, painter: QPainter) -> None:
        for ghost in self._ghosts:
            painter.save()
            painter.setOpacity(max(0.0, ghost.life / ghost.total))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ghost.color)
            painter.drawRoundedRect(QRectF(ghost.x, ghost.y, ghost.width, ghost.height), 7, 7)
            painter.restore()

    def _paint_line(self, painter: QPainter) -> None:
        y = self.activation_y()
        painter.setPen(QPen(QColor("#3ee0d0"), 2))
        painter.drawLine(12, int(y), max(12, self.width() - 12), int(y))
        for flash in self._flashes:
            painter.save()
            painter.setOpacity(max(0.0, flash.life / flash.total))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f4f1ff"))
            painter.drawRoundedRect(QRectF(flash.x - flash.width, y - 5, flash.width * 2, 10), 4, 4)
            painter.restore()

    def _paint_particles(self, painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        for particle in self._particles:
            painter.save()
            painter.setOpacity(max(0.0, particle.life / particle.total))
            painter.setBrush(particle.color)
            painter.drawEllipse(QRectF(
                particle.x - particle.radius,
                particle.y - particle.radius,
                particle.radius * 2,
                particle.radius * 2,
            ))
            painter.restore()
