"""Hilo de captura. Publica solo el fotograma más reciente para la interfaz."""

from __future__ import annotations

import time
from collections import deque

import cv2
import numpy as np
from PySide6.QtCore import QMutex, QThread, Signal
from PySide6.QtGui import QImage

from fingermelody.vision.camera_manager import (
    CameraError,
    CameraManager,
    FrameReadError,
)

LOST_CONNECTION_MESSAGE = (
    "Se perdió la conexión con la cámara. Comprueba el dispositivo o si otra "
    "aplicación la está usando."
)
MAX_CONSECUTIVE_READ_FAILURES = 5
_MIN_LOOP_MS = 16


def bgr_frame_to_qimage(frame: np.ndarray) -> QImage:
    """Convierte un fotograma BGR en una imagen RGB con búfer propio."""
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("El fotograma no está en BGR de 3 canales.")

    rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    height, width, channels = rgb.shape
    image = QImage(
        rgb.data,
        width,
        height,
        channels * width,
        QImage.Format.Format_RGB888,
    )
    return image.copy()


class CameraWorker(QThread):
    """Lee la cámara fuera del hilo de la interfaz."""

    error_occurred = Signal(str)
    capture_started = Signal()
    capture_stopped = Signal()

    def __init__(self, manager: CameraManager) -> None:
        super().__init__()
        self._manager = manager
        self._mutex = QMutex()
        self._latest_image: QImage | None = None
        self._fps: float | None = None
        self._sequence = 0
        self._frame_times: deque[float] = deque()

    def latest(self) -> tuple[QImage | None, float | None, int]:
        """Devuelve la última imagen, los FPS medidos y un contador de fotogramas."""
        self._mutex.lock()
        try:
            return self._latest_image, self._fps, self._sequence
        finally:
            self._mutex.unlock()

    def run(self) -> None:
        self._reset_snapshot()
        try:
            try:
                self._manager.open()
            except CameraError as exc:
                self.error_occurred.emit(str(exc))
                return

            if self.isInterruptionRequested():
                return

            self.capture_started.emit()
            self._capture_loop()
        finally:
            if self._manager.is_open:
                self._manager.close()
            self.capture_stopped.emit()

    def _capture_loop(self) -> None:
        failures = 0
        while not self.isInterruptionRequested():
            started = time.perf_counter()
            try:
                frame = self._manager.read()
            except FrameReadError:
                failures += 1
                if failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    self.error_occurred.emit(LOST_CONNECTION_MESSAGE)
                    return
                self.msleep(10)
                continue
            except CameraError as exc:
                self.error_occurred.emit(str(exc))
                return

            failures = 0
            try:
                image = bgr_frame_to_qimage(frame)
            except (ValueError, cv2.error):
                failures += 1
                if failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    self.error_occurred.emit(LOST_CONNECTION_MESSAGE)
                    return
                self.msleep(10)
                continue

            now = time.perf_counter()
            self._publish(image, self._measure_fps(now))
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if elapsed_ms < _MIN_LOOP_MS:
                self.msleep(_MIN_LOOP_MS - elapsed_ms)

    def _measure_fps(self, now: float) -> float | None:
        self._frame_times.append(now)
        cutoff = now - 1.0
        while self._frame_times and self._frame_times[0] < cutoff:
            self._frame_times.popleft()
        if len(self._frame_times) < 2:
            return None
        span = self._frame_times[-1] - self._frame_times[0]
        if span <= 0:
            return None
        return (len(self._frame_times) - 1) / span

    def _publish(self, image: QImage, fps: float | None) -> None:
        self._mutex.lock()
        try:
            self._latest_image = image
            self._fps = fps
            self._sequence += 1
        finally:
            self._mutex.unlock()

    def _reset_snapshot(self) -> None:
        self._mutex.lock()
        try:
            self._latest_image = None
            self._fps = None
            self._sequence = 0
            self._frame_times.clear()
        finally:
            self._mutex.unlock()
