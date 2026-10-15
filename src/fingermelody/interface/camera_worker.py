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
from fingermelody.vision.hand_overlay import draw_hands, mirror_selfie_frame
from fingermelody.vision.hand_tracker import (
    DETECT_FAILED_MESSAGE,
    HandTracker,
    HandTrackerError,
    HandViewState,
    to_view_state,
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
    """Lee la cámara y reconoce manos fuera del hilo de la interfaz."""

    error_occurred = Signal(str)
    tracking_warning = Signal(str)
    capture_started = Signal()
    capture_stopped = Signal()

    def __init__(self, manager: CameraManager, tracker: HandTracker | None = None) -> None:
        super().__init__()
        self._manager = manager
        self._tracker = tracker
        self._mutex = QMutex()
        self._latest_image: QImage | None = None
        self._fps: float | None = None
        self._sequence = 0
        self._hands = HandViewState()
        self._frame_times: deque[float] = deque()
        self._tracking_fallback = HandViewState()

    def latest(self) -> tuple[QImage | None, float | None, int, HandViewState]:
        """Devuelve la última imagen, los FPS, la secuencia y el estado de las manos."""
        self._mutex.lock()
        try:
            return self._latest_image, self._fps, self._sequence, self._hands
        finally:
            self._mutex.unlock()

    def run(self) -> None:
        self._reset_snapshot()
        tracker = None
        try:
            try:
                self._manager.open()
            except CameraError as exc:
                self.error_occurred.emit(str(exc))
                return

            if self.isInterruptionRequested():
                return

            tracker = self._open_tracker()
            self.capture_started.emit()
            self._capture_loop(tracker)
        finally:
            if tracker is not None:
                tracker.close()
            if self._manager.is_open:
                self._manager.close()
            self.capture_stopped.emit()

    def _open_tracker(self):
        tracker = (
            self._tracker
            if self._tracker is not None
            else HandTracker(mirrored_input=True)
        )
        try:
            tracker.open()
        except HandTrackerError as exc:
            self._tracking_fallback = HandViewState(active=False, message=str(exc))
            self.tracking_warning.emit(str(exc))
            tracker.close()
            return None
        return tracker

    def _capture_loop(self, tracker) -> None:
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
                # Un solo volteo. El modelo y la ventana reciben esta copia.
                # mirrored_input corrige Left/Right; los puntos no se vuelven a reflejar.
                frame = mirror_selfie_frame(frame)
                frame, view = self._recognize(frame, tracker)
                image = bgr_frame_to_qimage(frame)
            except (HandTrackerError, ValueError, cv2.error):
                failures += 1
                if failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    self.error_occurred.emit(LOST_CONNECTION_MESSAGE)
                    return
                self.msleep(10)
                continue

            now = time.perf_counter()
            self._publish(image, self._measure_fps(now), view)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if elapsed_ms < _MIN_LOOP_MS:
                self.msleep(_MIN_LOOP_MS - elapsed_ms)

    def _recognize(self, frame: np.ndarray, tracker):
        if tracker is None:
            return frame, self._tracking_fallback
        try:
            detected = tracker.detect(frame)
        except HandTrackerError:
            return frame, HandViewState(active=False, message=DETECT_FAILED_MESSAGE)
        return draw_hands(frame, detected.hands), to_view_state(detected)

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

    def _publish(self, image: QImage, fps: float | None, hands: HandViewState) -> None:
        self._mutex.lock()
        try:
            self._latest_image = image
            self._fps = fps
            self._hands = hands
            self._sequence += 1
        finally:
            self._mutex.unlock()

    def _reset_snapshot(self) -> None:
        self._mutex.lock()
        try:
            self._latest_image = None
            self._fps = None
            self._sequence = 0
            self._hands = HandViewState()
            self._frame_times.clear()
        finally:
            self._mutex.unlock()
