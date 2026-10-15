"""Ventana provisional para ver la cámara, sin piano ni reconocimiento."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from fingermelody.interface.camera_worker import CameraWorker
from fingermelody.vision.camera_manager import CameraManager

_DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1b1b1f;
    color: #f2f2f2;
    font-size: 14px;
}
QLabel#titleLabel {
    font-size: 22px;
    font-weight: 600;
}
QLabel#deviceLabel, QLabel#fpsLabel {
    color: #c8c8d0;
}
QLabel#preview {
    background-color: #101014;
    border: 1px solid #34343a;
    color: #9a9aa3;
}
QPushButton {
    background-color: #2a2a31;
    border: 1px solid #45454e;
    border-radius: 6px;
    padding: 8px 18px;
}
QPushButton:hover {
    background-color: #35353e;
}
QPushButton:disabled {
    color: #8a8a93;
    background-color: #24242a;
}
QPushButton#startButton {
    background-color: #2f5d50;
    border: 1px solid #3e7a68;
}
QPushButton#startButton:hover {
    background-color: #387062;
}
QPushButton#startButton:disabled {
    background-color: #24242a;
    color: #8a8a93;
    border: 1px solid #45454e;
}
QPushButton#stopButton:enabled {
    background-color: #5c3336;
    border: 1px solid #7d4a4e;
}
"""


class PreviewWindow(QMainWindow):
    """Muestra el vídeo en directo y controla el inicio y la parada."""

    def __init__(
        self,
        device_index: int = 0,
        width: int = 640,
        height: int = 480,
    ) -> None:
        super().__init__()
        self._state = "idle"
        self._closing = False
        self._error_message: str | None = None
        self._shown_sequence = 0
        self._manager = CameraManager(device_index, width, height)
        self._worker = CameraWorker(self._manager)
        self._worker.capture_started.connect(self._on_capture_started)
        self._worker.capture_stopped.connect(self._on_capture_stopped)
        self._worker.error_occurred.connect(self._on_error)

        self.setWindowTitle("FingerMelody")
        self.setStyleSheet(_DARK_STYLESHEET)
        self.resize(720, 640)
        self._build_ui(device_index, width, height)
        self._update_buttons()

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._show_latest_frame)

    def start_camera(self) -> None:
        if self._state != "idle" or self._worker.isRunning():
            self._set_status("La cámara ya está iniciada.", error=True)
            return

        self._error_message = None
        self._state = "starting"
        self._set_status("Abriendo cámara…")
        self._fps_label.setText("FPS: —")
        self._update_buttons()
        self._worker.start()

    def stop_camera(self) -> None:
        if self._state == "idle" and not self._worker.isRunning():
            return

        self._state = "stopping"
        self._set_status("Deteniendo cámara…")
        self._update_buttons()
        self._timer.stop()
        if self._worker.isRunning():
            self._worker.requestInterruption()
            if not self._worker.wait(2000):
                self._set_status("La cámara está tardando en detenerse.", error=True)
                self._update_buttons()
                return
        self._finish_stop()

    def shutdown(self) -> None:
        """Detiene la captura antes de cerrar la ventana."""
        if self._closing and self._state == "idle" and not self._worker.isRunning():
            return
        self._closing = True
        self._timer.stop()
        if self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(2000)
        self._state = "idle"

    def closeEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        self.shutdown()
        event.accept()

    def _build_ui(self, device_index: int, width: int, height: int) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("FingerMelody")
        title.setObjectName("titleLabel")

        self._device_label = QLabel(f"Dispositivo {device_index} · {width}×{height}")
        self._device_label.setObjectName("deviceLabel")

        self._preview = QLabel("La cámara está detenida")
        self._preview.setObjectName("preview")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(640, 480)
        self._preview.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self._status_label = QLabel("Detenida")
        self._status_label.setObjectName("statusLabel")
        self._fps_label = QLabel("FPS: —")
        self._fps_label.setObjectName("fpsLabel")

        info = QHBoxLayout()
        info.addWidget(self._status_label)
        info.addStretch(1)
        info.addWidget(self._fps_label)

        self._start_button = QPushButton("Iniciar cámara")
        self._start_button.setObjectName("startButton")
        self._start_button.clicked.connect(self.start_camera)
        self._stop_button = QPushButton("Detener cámara")
        self._stop_button.setObjectName("stopButton")
        self._stop_button.clicked.connect(self.stop_camera)

        buttons = QHBoxLayout()
        buttons.addWidget(self._start_button)
        buttons.addWidget(self._stop_button)
        buttons.addStretch(1)

        layout.addWidget(title)
        layout.addWidget(self._device_label)
        layout.addWidget(self._preview, stretch=1)
        layout.addLayout(info)
        layout.addLayout(buttons)

    def _show_latest_frame(self) -> None:
        image, fps, sequence = self._worker.latest()
        if fps is not None:
            self._fps_label.setText(f"FPS: {fps:.1f}")
        if image is None or sequence == self._shown_sequence:
            return

        self._shown_sequence = sequence
        pixmap = QPixmap.fromImage(image)
        target = self._preview.size()
        if target.width() > 0 and target.height() > 0:
            pixmap = pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        self._preview.setPixmap(pixmap)

    def _on_capture_started(self) -> None:
        if self._closing:
            self._worker.requestInterruption()
            return
        self._state = "live"
        self._set_status("En vivo")
        self._timer.start()
        self._update_buttons()

    def _on_capture_stopped(self) -> None:
        self._finish_stop()

    def _on_error(self, message: str) -> None:
        self._error_message = message
        self._timer.stop()
        self._state = "idle"
        self._set_status(message, error=True)
        self._update_buttons()
        if not self._closing:
            QMessageBox.warning(self, "FingerMelody", message)

    def _finish_stop(self) -> None:
        self._timer.stop()
        self._state = "idle"
        self._update_buttons()
        if self._closing or self._error_message is not None:
            return
        self._set_status("Detenida")
        self._fps_label.setText("FPS: —")

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self._status_label.setText(text)
        self._status_label.setStyleSheet("color: #ff8a80;" if error else "color: #f2f2f2;")

    def _update_buttons(self) -> None:
        running = self._worker.isRunning()
        self._start_button.setEnabled(self._state == "idle" and not running)
        self._stop_button.setEnabled(running or self._state in {"starting", "live", "stopping"})
