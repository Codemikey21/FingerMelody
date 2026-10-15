"""Vista de la cámara. No reconoce manos ni reproduce audio."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
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
        self.setMinimumSize(248, 168)
        self.setMaximumSize(320, 230)
        self._halo = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(32)
        self._timer.timeout.connect(self._tick)

        self.device = QLabel(device_text)
        self.device.setObjectName("deviceLabel")

        left = QLabel("Izquierda", self)
        left.setObjectName("leftLegend")
        right = QLabel("Derecha", self)
        right.setObjectName("rightLegend")
        left.hide()
        right.hide()

        self.preview = PreviewLabel("La cámara está detenida")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(200, 84)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.fps = QLabel("FPS: —")
        self.fps.setObjectName("fpsLabel")
        self.fps.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        fps_row = QHBoxLayout()
        fps_row.setContentsMargins(0, 0, 0, 0)
        fps_row.addStretch(1)
        fps_row.addWidget(self.fps)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addWidget(self.device)
        layout.addWidget(self.preview, stretch=1)
        layout.addLayout(fps_row)
        self._actions = QHBoxLayout()
        self._actions.setContentsMargins(0, 0, 0, 0)
        self._actions.setSpacing(6)
        layout.addLayout(self._actions)

    def reveal(self) -> None:
        """Aparición del halo. No tapa el vídeo ni corre mientras está en reposo."""
        self._halo = 1.0
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        super().paintEvent(event)
        if self._halo <= 0.04:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor("#3ee0d0")
        color.setAlpha(int(120 * self._halo))
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -3, -3), 16, 16)
        painter.end()

    def _tick(self) -> None:
        self._halo = max(0.0, self._halo - 0.08)
        if self._halo <= 0.0:
            self._timer.stop()
        self.update()
