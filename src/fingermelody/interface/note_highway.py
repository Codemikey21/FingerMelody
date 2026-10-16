"""Carretera de notas del modo guiado. No avanza la canción ni reproduce audio."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QRadialGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from fingermelody.interface.neon_palette import BACKGROUND, alpha, note_color
from fingermelody.music.guided import GuidedSnapshot
from fingermelody.music.note_mapper import NoteMapper
from fingermelody.music.session import PHASE_PLAYING

_PIXELS_PER_BEAT = 54.0
_LEAD_BEATS = 2.35
_VISUAL_BEATS_PER_SECOND = 2.05
_TICK_MS = 16
_SLOW_TICK_MS = 32


@dataclass
class _Particle:
    note: str
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


@dataclass
class _Impact:
    note: str
    life: float = 0.6
    total: float = 0.6
    strength: float = 1.0


class NoteHighway(QWidget):
    """Barras que bajan hasta la línea y esperan. El índice lo impone quien llama."""

    resized = Signal()
    illumination_changed = Signal(object)
    impact_light_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("noteHighway")
        self._snapshot: GuidedSnapshot | None = None
        self._labels: dict[str, str] = {}
        self._integrated = False
        self._background_key = None
        self._background = None
        self._bar_cache = {}
        self._trail = 0.0
        self._impacts: list[_Impact] = []
        self._surface_time = 0.0
        self._arrival_index = -1
        self._last_tick = time.monotonic()
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
        if event.oldSize().height() >= 0:
            previous_y = max(24.0, event.oldSize().height() - 16.0)
            for particle in self._particles:
                particle.y += self.activation_y() - previous_y
        self.resized.emit()

    def set_lanes(self, lanes: tuple[tuple[str, float, float], ...]) -> None:
        """Cada carril es nota, centro horizontal y ancho de la tecla, en este widget."""
        new_lanes = {note: (center, width) for note, center, width in lanes}
        for particle in self._particles:
            old = self._lanes.get(particle.note)
            new = new_lanes.get(particle.note)
            if old is not None and new is not None:
                particle.x += new[0] - old[0]
        self._lanes = new_lanes
        self._publish_illumination()
        self.update()

    def set_integrated(self, integrated: bool) -> None:
        self._integrated = integrated
        self.setStyleSheet("background: transparent;" if integrated else "")
        self.update()

    def lane_center(self, note: str) -> float | None:
        lane = self._lanes.get(note)
        if lane is None:
            return None
        return lane[0]

    def set_chart(self, steps: tuple[tuple[str, float], ...], index: int) -> None:
        """Recibe la canción y el índice ya decidido. No lo incrementa."""
        self._snapshot = None
        self._labels.clear()
        restarted = index == 0 and (not self._steps or self._index != 0)
        self._steps = tuple(steps)
        self._index = max(0, min(index, len(self._steps)))
        if restarted:
            self._arrival_index = -1
            self._impacts.clear()
            self.impact_light_changed.emit({})
            self._scroll = -_LEAD_BEATS
        target = self._target_beat()
        if self._scroll > target:
            self._scroll = target
        self._publish_illumination()
        self._arm_timer()
        self.update()

    def set_snapshot(self, snapshot: GuidedSnapshot, mapper: NoteMapper | None = None) -> None:
        """Consume el contrato completo; nunca acepta entradas ni avanza la música.

        Reenviar estados parciales o pausa/reanudación conserva el desplazamiento.
        Una canción nueva o un reinicio explícito comienza con anticipación.
        """
        previous = self._snapshot
        restarted = (previous is None
                     or tuple(s.step for s in previous.steps) != tuple(s.step for s in snapshot.steps)
                     or snapshot.index < previous.index
                     or (snapshot.index == 0 and previous.phase == "idle"
                         and snapshot.phase == PHASE_PLAYING))
        self._snapshot = snapshot
        self._steps = tuple((s.required_notes[0], s.relative_duration) for s in snapshot.steps)
        self._index = snapshot.index
        if restarted:
            self._scroll = -_LEAD_BEATS
            self._arrival_index = -1
        mapper = mapper or NoteMapper()
        hands = {"LEFT": "Izquierda", "RIGHT": "Derecha"}
        fingers = {"THUMB": "Pulgar", "INDEX": "Índice", "MIDDLE": "Medio",
                   "RING": "Anular", "PINKY": "Meñique"}
        self._labels = {}
        for state in snapshot.steps:
            for note in state.required_notes:
                assignments = mapper.assignments_for_note(note)
                descriptions = [f"{hands.get(a.hand, '?')} · {fingers.get(a.finger, a.finger_id)}"
                                for a in assignments]
                self._labels[note] = " / ".join(descriptions) or "Sin asignación"
        self.set_running(snapshot.phase == PHASE_PLAYING)
        self._publish_illumination()

    def bar_identities(self) -> tuple[tuple[str, str], ...]:
        """Identidades de todas las barras no completadas, incluidas las futuras."""
        if self._snapshot is None:
            return ()
        return tuple(n.identity for s in self._snapshot.steps[self._index:]
                     if not s.completed for n in s.visual_notes)

    def bar_label(self, note: str) -> str:
        return f"{note} · {self._labels.get(note, 'Sin asignación')}"

    def preview_notes(self) -> tuple[str, ...]:
        """Carriles de la anticipación visible, para ubicar la tarjeta de cámara."""
        return tuple(dict.fromkeys(note for _, note, _ in self._bars()))

    def bar_opacity(self, index: int, accepted: bool) -> float:
        return 0.24 if accepted else (1.0 if index == self._index else 0.36)

    def _bars(self):
        for index in range(self._index, min(len(self._steps), self._index + 8)):
            if self._snapshot is None:
                yield index, self._steps[index][0], False
            else:
                state = self._snapshot.steps[index]
                if not state.completed:
                    for visual in state.visual_notes:
                        yield index, visual.note, visual.accepted

    def set_running(self, running: bool) -> None:
        """Con la sesión en pausa o sin iniciar, las barras no siguen bajando."""
        self._running = running
        self._paused_motion = not running
        self._arm_timer()
        self.update()

    def clear_transients(self) -> None:
        self._impacts.clear()
        self._particles.clear()
        self._ghosts.clear()
        self._flashes.clear()
        self._trail = 0.0
        self._arrival_index = -1
        self.set_chart((), 0)
        self.set_running(False)
        self.impact_light_changed.emit({})
        self.update()

    def shutdown(self) -> None:
        """Detiene la animación al cerrar la ventana. No toca la canción."""
        self._running = False
        self._trail = 0.0
        self._impacts.clear()
        self.impact_light_changed.emit({})
        self._particles.clear()
        self._ghosts.clear()
        self._flashes.clear()
        self._timer.blockSignals(True)
        self._timer.stop()

    def notify_hit(self, note: str) -> None:
        """Efecto visual del acierto. No cambia el índice ni reproduce sonido."""
        rect = self.bar_rect(self._index, note)
        if rect is not None:
            color = note_color(note)
            if self._snapshot is not None:
                color = alpha(color, 40)  # No ocultar la marca de aceptación temprana.
            self._ghosts.append(_Ghost(rect.x(), rect.y(), rect.width(), rect.height(), 0.42, 0.42, QColor(color)))
            self._flashes.append(_Flash(rect.center().x(), rect.width(), 0.28, 0.28))
        self._add_impact(note, 1.0)
        self._spawn(note)
        self._arm_timer()
        self.update()

    def _add_impact(self, note: str, strength: float) -> None:
        if note not in self._lanes:
            return
        # Una sola reacción por carril; los aciertos rápidos no acumulan trabajo.
        self._impacts = [item for item in self._impacts if item.note != note]
        self._impacts.append(_Impact(note, strength=strength))
        self._publish_impact_light()

    def _publish_impact_light(self) -> None:
        self.impact_light_changed.emit({
            item.note: item.strength * (item.life / item.total) ** 1.3
            for item in self._impacts
        })

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

    def bar_rect(self, index: int, note: str | None = None) -> QRectF | None:
        if index < 0 or index >= len(self._steps):
            return None
        lead, beats = self._steps[index]
        note = lead if note is None else note
        required = (lead,) if self._snapshot is None else self._snapshot.steps[index].required_notes
        if note not in required:
            return None
        lane = self._lanes.get(note)
        if lane is None:
            return None
        center, key_width = lane
        width = max(10.0, min(64.0, key_width * 0.52))
        height = max(18.0, beats * _PIXELS_PER_BEAT - 8.0)
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
        return len(self._particles) + len(self._ghosts) + len(self._flashes) + len(self._impacts)

    def reduced_quality(self) -> bool:
        return self._reduced

    def paintEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_background(painter)
        self._paint_key_light(painter)
        self._paint_bars(painter)
        self._paint_ghosts(painter)
        self._paint_line(painter)
        self._paint_particles(painter)
        painter.end()

    def _on_tick(self) -> None:
        now = time.monotonic()
        self._step(min(0.05, max(0.0, now - self._last_tick)))
        self._last_tick = now

    def _step(self, seconds: float) -> None:
        if self._running or self._impacts:
            self._surface_time += seconds
        self._age(self._impacts, seconds)
        moving = self._running and self._index < len(self._steps) and not self.waiting()
        self._trail = min(1.0, self._trail + seconds * 6) if moving else max(0.0, self._trail - seconds * 4)
        if self._running and self._index < len(self._steps):
            target = self._target_beat()
            if self._scroll < target:
                self._scroll = min(target, self._scroll + seconds * _VISUAL_BEATS_PER_SECOND)
        self._publish_impact_light()
        self._age(self._particles, seconds)
        self._age(self._ghosts, seconds)
        self._age(self._flashes, seconds)
        self._publish_illumination()
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
        # Presupuesto por nota: repetir un dedo no elimina efectos de otros.
        self._particles = [p for p in self._particles if p.note != note]
        y = self.activation_y()
        color = note_color(note)
        for _ in range(amount):
            life = 0.22 + self._rng.random() * 0.2
            self._particles.append(
                _Particle(
                    note=note,
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
                self._last_tick = time.monotonic()
                self._timer.start()
            return
        if self._timer.isActive():
            self._timer.stop()

    def _busy(self) -> bool:
        if self._impacts or self._trail > 0 or self._particles or self._ghosts or self._flashes:
            return True
        if not self._running or self._index >= len(self._steps):
            return False
        return True

    def _publish_illumination(self) -> None:
        lighting = {}
        for index, note, accepted in self._bars():
            rect = self.bar_rect(index, note)
            if rect is None or rect.bottom() < 0:
                continue
            proximity = max(0.0, 1.0 - (self.activation_y() - rect.bottom()) / 260.0)
            strength = proximity * (0.18 if accepted else (1.0 if index == self._index else 0.45))
            lighting[note] = max(lighting.get(note, 0.0), strength)
        self.illumination_changed.emit(lighting)

    def _paint_background(self, painter: QPainter) -> None:
        height = int(self.activation_y()) if self._integrated else self.height()
        key = (self.width(), height, self.devicePixelRatioF(), tuple(self._lanes.items()))
        if key != self._background_key:
            ratio = self.devicePixelRatioF()
            pixmap = QPixmap(round(self.width() * ratio), round(height * ratio))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(QColor(BACKGROUND))
            canvas = QPainter(pixmap)
            for fraction, color in ((0.23, QColor("#006bff")), (0.73, QColor("#a600ed"))):
                glow = QRadialGradient(self.width() * fraction, height * 0.72, max(1, self.width() * 0.32))
                glow.setColorAt(0, alpha(color, 58))
                glow.setColorAt(0.45, alpha(color, 20))
                glow.setColorAt(1, alpha(color, 0))
                canvas.fillRect(0, 0, self.width(), height, glow)
            for note, (center, width) in self._lanes.items():
                color = note_color(note)
                guide = QLinearGradient(0, 0, 0, height)
                guide.setColorAt(0, alpha(color, 0))
                guide.setColorAt(1, alpha(color, 20))
                canvas.setPen(QPen(guide, 0.7))
                canvas.drawLine(int(center), 0, int(center), height)
            canvas.end()
            self._background = pixmap
            self._background_key = key
        painter.drawPixmap(0, 0, self._background)

    def _paint_key_light(self, painter: QPainter) -> None:
        """Luz continua de proximidad, sin partículas ni eventos musicales."""
        y = self.activation_y()
        for index, note, accepted in self._bars():
            rect = self.bar_rect(index, note)
            if rect is None:
                continue
            proximity = max(0.0, 1.0 - (y - rect.bottom()) / 300.0)
            if proximity <= 0:
                continue
            color = note_color(note)
            center, key_width = self._lanes[note]
            strength = proximity * (0.18 if accepted else (1.0 if index == self._index else 0.3))
            painter.save()
            painter.setClipRect(QRectF(0, 0, self.width(), y + 12))
            # Elipse radial alta: luz que emerge de la tecla y se disuelve arriba.
            painter.translate(center, y)
            painter.scale(max(24, key_width * 0.65), 220)
            glow = QRadialGradient(0, 0, 1)
            glow.setColorAt(0, alpha(color, round(170 * strength)))
            glow.setColorAt(0.18, alpha(color, round(100 * strength)))
            glow.setColorAt(0.55, alpha(color, round(35 * strength)))
            glow.setColorAt(1, alpha(color, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QRectF(-1, -1, 2, 2))
            painter.restore()
            painter.save()
            painter.translate(center, y)
            painter.scale(max(20, key_width * 0.6), 18)
            rim = QRadialGradient(0, 0, 1)
            rim.setColorAt(0, alpha(QColor("#e9faff"), round(240 * strength)))
            rim.setColorAt(0.25, alpha(color, round(190 * strength)))
            rim.setColorAt(1, alpha(color, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(rim)
            painter.drawEllipse(QRectF(-1, -1, 2, 2))
            painter.restore()

    def _paint_bars(self, painter: QPainter) -> None:
        if not self._lanes:
            return
        view = QRectF(self.rect())
        for index, note, accepted in self._bars():
            rect = self.bar_rect(index, note)
            if rect is None or not rect.adjusted(-40, -110, 40, 40).intersects(view):
                continue
            color = note_color(note)
            painter.save()
            painter.setOpacity(self.bar_opacity(index, accepted))
            painter.setPen(Qt.PenStyle.NoPen)
            if self._trail > 0:
                trail = QRectF(rect.left(), rect.top() - 100, rect.width(), 100)
                fade = QLinearGradient(trail.topLeft(), trail.bottomLeft())
                fade.setColorAt(0, alpha(color, 0))
                fade.setColorAt(1, alpha(color, int(75 * self._trail)))
                painter.fillRect(trail, fade)
            sprite = self._bar_sprite(rect, color)
            painter.drawPixmap(QPointF(rect.x() - 32, rect.y() - 32), sprite)
            painter.restore()
            if self._snapshot is not None:
                painter.save()
                painter.setOpacity(0.7 if accepted else (1.0 if index == self._index else 0.6))
                painter.setPen(QColor("#eafaff"))
                font = painter.font()
                font.setPixelSize(13 if index == self._index else 11)
                font.setBold(index == self._index)
                painter.setFont(font)
                label = ("✓ " if accepted else "") + note
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
                painter.restore()

    def _bar_sprite(self, source: QRectF, color: QColor) -> QPixmap:
        ratio = self.devicePixelRatioF()
        key = (source.width(), source.height(), color.rgba(), ratio, self._reduced)
        if key in self._bar_cache:
            return self._bar_cache[key]
        if len(self._bar_cache) >= 64:
            self._bar_cache.clear()
        sprite = QPixmap(math.ceil((source.width() + 64) * ratio), math.ceil((source.height() + 64) * ratio))
        sprite.setDevicePixelRatio(ratio)
        sprite.fill(Qt.GlobalColor.transparent)
        painter = QPainter(sprite)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(32, 32, source.width(), source.height())
        # Trazos concéntricos de baja opacidad: halo local, sin filtros.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        layers = ((16, 22), (7, 65)) if self._reduced else tuple((width, max(1, round(12 * (1 - width / 64) ** 3))) for width in range(60, 2, -2))
        for width, opacity in layers:
            painter.setPen(QPen(alpha(color, opacity), width))
            painter.drawRoundedRect(rect, 7, 7)
        core = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        core.setColorAt(0, alpha(color, 105))
        core.setColorAt(0.5, alpha(color, 52))
        core.setColorAt(1, alpha(color, 150))
        painter.setBrush(core)
        painter.setPen(QPen(color, 2.0))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        edge = QLinearGradient(rect.topLeft(), rect.bottomRight())
        edge.setColorAt(0, QColor("#f2fbff"))
        edge.setColorAt(0.35, color.lighter(155))
        edge.setColorAt(0.72, QColor("#ecfaff"))
        edge.setColorAt(1, color.lighter(140))
        painter.setPen(QPen(edge, 1.25))
        painter.drawRoundedRect(rect.adjusted(0.7, 0.7, -0.7, -0.7), 6, 6)
        painter.end()
        self._bar_cache[key] = sprite
        return sprite

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
        phase = self._surface_time
        surface = QPainterPath()
        step = 8 if self._reduced else 4
        for x in range(0, self.width() + step, step):
            wave = 1.6 * math.sin(x * 0.055 + phase * 3) + 1.1 * math.sin(x * 0.137 - phase * 4)
            for hit in self._impacts:
                center, width = self._lanes.get(hit.note, (0, 1))
                distance = (x - center) / max(24, width * 0.65)
                life = hit.life / hit.total
                wave += hit.strength * life * math.exp(-distance * distance * 3) * (
                    10 + 13 * math.sin(distance * 11 - (1 - life) * 14))
            if x == 0:
                surface.moveTo(x, y - wave)
            else:
                surface.lineTo(x, y - wave)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0, note_color("C4"))
        gradient.setColorAt(1, note_color("E5"))
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for width, opacity in ((20, 0.04), (12, 0.08), (6, 0.22), (2.5, 0.95)):
            painter.setOpacity(opacity)
            painter.setPen(QPen(gradient, width))
            painter.drawPath(surface)
        painter.setOpacity(0.7)
        painter.setPen(QPen(QColor("#e6f7ff"), 0.8))
        painter.drawPath(surface)
        painter.restore()
        for hit in self._impacts:
            self._paint_impact(painter, hit, y)

    def _paint_impact(self, painter: QPainter, hit: _Impact, y: float) -> None:
        lane = self._lanes.get(hit.note)
        if lane is None:
            return
        center, key_width = lane
        age = 1 - hit.life / hit.total
        power = hit.strength * (1 - age) ** 1.3
        color = note_color(hit.note)
        spread = min(72, key_width * 0.45)
        height = 120 + 100 * age
        painter.save()
        painter.translate(center, y)
        painter.setPen(Qt.PenStyle.NoPen)
        # Columna curva, más ancha arriba: volumen de humo/energía ascendente.
        plume = QPainterPath()
        plume.moveTo(-spread * 0.3, 3)
        plume.cubicTo(-spread * 0.1, -height * 0.5, -spread, -height * 0.6, -spread * 0.8, -height)
        plume.cubicTo(-spread * 0.2, -height * 1.12, spread * 0.8, -height * 0.95, spread, -height)
        plume.cubicTo(spread * 0.3, -height * 0.55, spread * 0.1, -height * 0.35, spread * 0.3, 3)
        plume.closeSubpath()
        beam = QLinearGradient(0, -height, 0, 6)
        beam.setColorAt(0, alpha(color, 0))
        beam.setColorAt(0.18, alpha(color, round(100 * power)))
        beam.setColorAt(0.7, alpha(color, round(150 * power)))
        beam.setColorAt(1, alpha(QColor("#efffff"), round(240 * power)))
        painter.setBrush(beam)
        for scale, opacity in ((1.22, 0.08), (1.1, 0.12), (1.0, 0.24), (0.8, 0.24), (0.58, 0.2)):
            painter.save()
            painter.scale(scale, 1)
            painter.setOpacity(opacity)
            painter.drawPath(plume)
            painter.restore()
        # Lenguas líquidas unidas a la base y gotas breves de trayectoria fija.
        splash = QPainterPath()
        splash.moveTo(-spread, 4)
        for i in range(7):
            x = -spread + i * spread / 3
            peak = (18 + 34 * (0.5 + 0.5 * math.sin(i * 2.7))) * (1 - age * 0.6)
            splash.cubicTo(x - 5, -3, x - 8, -peak, x, -peak)
            splash.cubicTo(x + 3, -peak, x + 2, 4, x + spread / 6, 3)
        splash.lineTo(spread, 8)
        splash.lineTo(-spread, 8)
        splash.closeSubpath()
        painter.setBrush(beam)
        painter.drawPath(splash)
        painter.setPen(QPen(alpha(QColor("#edfcff"), round(220 * power)), 1.2))
        painter.drawPath(splash)
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(5):
            x = (i - 2) * spread * 0.37 * (0.7 + age)
            top = -(28 + 16 * (i % 3) + 60 * age - 60 * age * age)
            painter.setBrush(alpha(color.lighter(165), round(220 * power)))
            painter.drawEllipse(QRectF(x - 2, top, 4, 7))
        core = QRadialGradient(0, 0, spread)
        core.setColorAt(0, alpha(QColor("#ffffff"), round(255 * power)))
        core.setColorAt(0.3, alpha(color.lighter(180), round(220 * power)))
        core.setColorAt(1, alpha(color, 0))
        painter.scale(1, 0.28)
        painter.setBrush(core)
        painter.drawEllipse(QRectF(-spread, -spread, spread * 2, spread * 2))
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
