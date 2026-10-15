"""Vista de la cámara. No reconoce manos ni reproduce audio."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout


class PreviewLabel(QLabel):
    """Imagen del vídeo. Avisa cuando cambia su tamaño para conservar la proporción."""

    resized = Signal()

    def resizeEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        super().resizeEvent(event)
        self.resized.emit()


class CameraPanel(QFrame):
    """Vídeo en vivo, leyenda de color de cada mano y FPS."""

    def __init__(self, device_text: str) -> None:
        super().__init__()
        self.setObjectName("cameraPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(360)

        self.device = QLabel(device_text)
        self.device.setObjectName("deviceLabel")

        left = QLabel("Izquierda")
        left.setObjectName("leftLegend")
        right = QLabel("Derecha")
        right.setObjectName("rightLegend")
        legend = QHBoxLayout()
        legend.setContentsMargins(0, 0, 0, 0)
        legend.setSpacing(12)
        legend.addWidget(left)
        legend.addWidget(right)
        legend.addStretch(1)

        self.preview = PreviewLabel("La cámara está detenida")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(320, 240)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        self.fps = QLabel("FPS: —")
        self.fps.setObjectName("fpsLabel")
        self.fps.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        fps_row = QHBoxLayout()
        fps_row.setContentsMargins(0, 0, 0, 0)
        fps_row.addStretch(1)
        fps_row.addWidget(self.fps)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(self.device)
        layout.addLayout(legend)
        layout.addWidget(self.preview, stretch=1)
        layout.addLayout(fps_row)
