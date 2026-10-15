"""Indicadores de la sesión. No captura vídeo ni reproduce notas."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from fingermelody.gestures.finger_detector import FINGER_SPECS, finger_id


def finger_caption(finger_id_value: str) -> str:
    """Nombre visible de un identificador estable, por ejemplo LEFT_INDEX."""
    for hand, side in (("Left", "Izquierda"), ("Right", "Derecha")):
        for spec in FINGER_SPECS:
            if finger_id(hand, spec) == finger_id_value:
                return f"{spec.display_name} · {side} ({finger_id_value})"
    return finger_id_value


class InfoPanel(QFrame):
    """Última nota, manos, contador y estado de la cámara y del sonido."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("infoPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(300)
        self.setMaximumWidth(480)

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
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(self.last_note)
        layout.addWidget(self.last_finger)
        layout.addWidget(self.presses)
        layout.addWidget(self.hands)
        layout.addLayout(sides)
        layout.addWidget(self.fps)
        layout.addWidget(self.camera)
        layout.addWidget(self.audio)
        layout.addWidget(self.diagnostic)
        layout.addWidget(scroll, stretch=1)


def _finger_label(object_name: str) -> QLabel:
    label = QLabel()
    label.setObjectName(object_name)
    label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label
