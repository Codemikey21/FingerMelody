"""Indicadores de la sesión. No captura vídeo ni reproduce notas."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from fingermelody.gestures.finger_detector import FINGER_SPECS, finger_id
from fingermelody.interface.history_strip import NoteHistoryStrip


def finger_caption(finger_id_value: str) -> str:
    """Nombre visible de un identificador estable, por ejemplo LEFT_INDEX."""
    for hand, side in (("Left", "Izquierda"), ("Right", "Derecha")):
        for spec in FINGER_SPECS:
            if finger_id(hand, spec) == finger_id_value:
                return f"{spec.display_name} · {side} ({finger_id_value})"
    return finger_id_value


class InfoPanel(QFrame):
    """Datos técnicos. La escena principal no los muestra como columna fija."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("infoPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self.mode = QLabel("Jingle Bells")
        self.mode.setObjectName("modeLabel")
        self.session = SessionBadge("En espera")
        self.start_session = QPushButton("Iniciar sesión")
        self.start_session.setObjectName("startSessionButton")
        self.pause_session = QPushButton("Pausar")
        self.pause_session.setObjectName("pauseSessionButton")
        self.resume_session = QPushButton("Reanudar")
        self.resume_session.setObjectName("resumeSessionButton")
        self.finish_session = QPushButton("Finalizar")
        self.finish_session.setObjectName("finishSessionButton")
        self.history = NoteHistoryStrip()

        self.hands = QLabel("Manos: —")
        self.hands.setObjectName("handsLabel")
        self.left = QLabel("Izquierda: —")
        self.left.setObjectName("leftHandLabel")
        self.right = QLabel("Derecha: —")
        self.right.setObjectName("rightHandLabel")

        self.last_note = QLabel("Última nota: —")
        self.last_note.setObjectName("lastNoteLabel")
        self.last_note.setWordWrap(True)
        self.last_finger = QLabel("Dedo: —")
        self.last_finger.setObjectName("lastFingerLabel")
        self.last_finger.setWordWrap(True)
        self.presses = QLabel("Pulsaciones: 0")
        self.presses.setObjectName("pressCountLabel")
        self.fps = QLabel("FPS: —")
        self.fps.setObjectName("infoFpsLabel")
        self.camera = QLabel("Detenida")
        self.camera.setObjectName("statusLabel")
        self.camera.setWordWrap(True)
        self.audio = QLabel("")
        self.audio.setObjectName("audioStatus")
        self.audio.setWordWrap(True)
        self.diagnostic = QLabel("")
        self.diagnostic.setObjectName("diagnosticLabel")
        self.diagnostic.setWordWrap(True)
        self.diagnostic.hide()

        self.left_fingers = _finger_label("leftFingerPanel")
        self.right_fingers = _finger_label("rightFingerPanel")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("fingerHost")
        fingers = QVBoxLayout(inner)
        fingers.setContentsMargins(0, 0, 0, 0)
        fingers.setSpacing(8)
        fingers.addWidget(self.left_fingers)
        fingers.addWidget(self.right_fingers)
        scroll.setWidget(inner)

        sides = QHBoxLayout()
        sides.setContentsMargins(0, 0, 0, 0)
        sides.setSpacing(12)
        sides.addWidget(self.left)
        sides.addWidget(self.right)
        sides.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        layout.addWidget(self.mode)
        layout.addWidget(self.presses)
        layout.addWidget(self.hands)
        layout.addLayout(sides)
        layout.addWidget(self.fps)
        layout.addWidget(self.camera)
        layout.addWidget(self.audio)
        layout.addWidget(self.diagnostic)
        layout.addWidget(scroll, stretch=1)


class SessionBadge(QLabel):
    """Chip de estado. El fundido pinta solo esta etiqueta, durante unos 160 ms."""

    _COLORS = {
        "playing": ("#04221c", "#3ee0d0"),
        "paused": ("#2a1020", "#ffb4c0"),
        "finished": ("#1a1230", "#c4b6ff"),
        "idle": ("#c5cad6", "#242836"),
    }

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setObjectName("sessionStatusLabel")
        self.setProperty("phase", "idle")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._veil = 1.0
        self._pulse = 0.0
        self._font = QFont("Segoe UI", 10)
        self._font.setBold(True)
        self._timer = QTimer(self)
        self._timer.setInterval(32)
        self._timer.timeout.connect(self._tick)
        self.setMinimumSize(108, 26)

    def fade_in(self) -> None:
        self._veil = 0.35
        self._pulse = 1.0
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        phase = self.property("phase") or "idle"
        ink, fill = self._COLORS.get(phase, self._COLORS["idle"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._pulse > 0.04:
            ring = QColor(fill)
            ring.setAlpha(int(90 * self._pulse))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ring)
            grow = 4.0 * self._pulse
            painter.drawRoundedRect(self.rect().adjusted(int(-grow), int(-grow), int(grow), int(grow)), 13, 13)
        painter.setOpacity(self._veil)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(self.rect().adjusted(0, 1, -1, -1), 11, 11)
        painter.setPen(QColor(ink))
        painter.setFont(self._font)
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self.text())
        painter.end()

    def _tick(self) -> None:
        self._veil = min(1.0, self._veil + 0.14)
        self._pulse = max(0.0, self._pulse - 0.18)
        if self._veil >= 1.0 and self._pulse <= 0.0:
            self._timer.stop()
        self.update()


def _finger_label(object_name: str) -> QLabel:
    label = QLabel()
    label.setObjectName(object_name)
    label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label
