"""Hilo de captura. Publica solo el fotograma más reciente para la interfaz."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np
from PySide6.QtCore import QMutex, QThread, Signal
from PySide6.QtGui import QImage

from fingermelody.vision.camera_manager import (
    CameraError,
    CameraManager,
    FrameReadError,
)
from fingermelody.gestures.finger_detector import FingerDetector
from fingermelody.gestures.finger_overlay import draw_press_highlights
from fingermelody.gestures.gesture_engine import FingerPressEvent, GestureEngine, GestureUpdate
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
_MIN_LOOP_MS = 1


@dataclass(frozen=True)
class FrameTiming:
    """Tiempos de un fotograma. play_note y el audio audible no entran aquí."""

    capture_ms: float = 0.0
    inference_ms: float = 0.0
    geometry_ms: float = 0.0
    draw_ms: float = 0.0
    queued_at: float | None = None


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
    presses_detected = Signal()
    calibration_saved = Signal(str)

    def __init__(self, manager: CameraManager, tracker: HandTracker | None = None) -> None:
        super().__init__()
        self._manager = manager
        self._tracker = tracker
        self._mutex = QMutex()
        self._latest_image: QImage | None = None
        self._fps: float | None = None
        self._sequence = 0
        self._hands = HandViewState()
        self._fingers = GestureUpdate.inactive()
        self._pending_events: list[FingerPressEvent] = []
        self._event_clock: float | None = None
        self._timing = FrameTiming()
        self._reset_counts = False
        self._calibration: str | None = None
        self._finger_detector = FingerDetector()
        self._gesture_engine = GestureEngine()
        self._frame_times: deque[float] = deque()
        self._tracking_fallback = HandViewState()

    def take_events(self) -> tuple[FingerPressEvent, ...]:
        """Entrega las pulsaciones nuevas y vacía la cola. Una sola vez cada una."""
        self._mutex.lock()
        try:
            events = tuple(self._pending_events)
            self._pending_events.clear()
            return events
        finally:
            self._mutex.unlock()

    def request_calibration(self, kind: str) -> None:
        """Pide guardar la pose del próximo fotograma: rest o flex."""
        if kind not in {"rest", "flex"}:
            raise ValueError("La calibración admite reposo o flexión.")
        self._mutex.lock()
        try:
            self._calibration = kind
        finally:
            self._mutex.unlock()

    def event_clock(self) -> float | None:
        """Instante monotonic en el que se encoló la última pulsación."""
        self._mutex.lock()
        try:
            return self._event_clock
        finally:
            self._mutex.unlock()

    def request_count_reset(self) -> None:
        """Pide al hilo de captura que ponga a cero los contadores, sin reiniciar fases."""
        self._mutex.lock()
        try:
            self._reset_counts = True
        finally:
            self._mutex.unlock()

    def _consume_count_reset(self) -> bool:
        self._mutex.lock()
        try:
            pending = self._reset_counts
            self._reset_counts = False
            return pending
        finally:
            self._mutex.unlock()

    def latest(
        self,
    ) -> tuple[QImage | None, float | None, int, HandViewState, GestureUpdate, FrameTiming]:
        """Devuelve la última imagen, los FPS, la secuencia, las manos, los gestos y los tiempos."""
        self._mutex.lock()
        try:
            return (
                self._latest_image,
                self._fps,
                self._sequence,
                self._hands,
                self._fingers,
                self._timing,
            )
        finally:
            self._mutex.unlock()

    def _consume_calibration(self) -> str | None:
        self._mutex.lock()
        try:
            kind = self._calibration
            self._calibration = None
            return kind
        finally:
            self._mutex.unlock()

    def run(self) -> None:
        self._gesture_engine.reset()
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
                read_started = time.perf_counter()
                frame = self._manager.read()
                capture_ms = (time.perf_counter() - read_started) * 1000.0
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
                frame, view, fingers, timing = self._recognize(frame, tracker, capture_ms)
                image = bgr_frame_to_qimage(frame)
            except (HandTrackerError, ValueError, cv2.error):
                failures += 1
                if failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    self.error_occurred.emit(LOST_CONNECTION_MESSAGE)
                    return
                self.msleep(10)
                continue

            now = time.perf_counter()
            self._publish(image, self._measure_fps(now), view, fingers, timing)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if elapsed_ms < _MIN_LOOP_MS:
                self.msleep(_MIN_LOOP_MS - elapsed_ms)

    def _recognize(self, frame: np.ndarray, tracker, capture_ms: float):
        if tracker is None:
            timing = FrameTiming(capture_ms=capture_ms)
            return frame, self._tracking_fallback, GestureUpdate.inactive(), timing
        try:
            infer_started = time.perf_counter()
            detected = tracker.detect(frame)
            inference_ms = (time.perf_counter() - infer_started) * 1000.0
        except HandTrackerError:
            timing = FrameTiming(capture_ms=capture_ms)
            return frame, HandViewState(active=False, message=DETECT_FAILED_MESSAGE), GestureUpdate.inactive(), timing
        geo_started = time.perf_counter()
        observed = self._finger_detector.identify(detected)
        kind = self._consume_calibration()
        if kind is not None:
            stored = self._gesture_engine.capture_reference(observed.fingers, kind)
            label = "Reposo guardado" if kind == "rest" else "Flexión guardada"
            self.calibration_saved.emit(f"{label}: {stored} dedos.")
        if self._consume_count_reset():
            self._gesture_engine.clear_press_counts()
        gestures = self._gesture_engine.update(observed.fingers, int(time.monotonic() * 1000))
        geometry_ms = (time.perf_counter() - geo_started) * 1000.0
        queued_at = self._queue_events(gestures.events)
        draw_started = time.perf_counter()
        annotated = draw_hands(frame, detected.hands)
        annotated = draw_press_highlights(annotated, gestures.states)
        draw_ms = (time.perf_counter() - draw_started) * 1000.0
        timing = FrameTiming(
            capture_ms=capture_ms,
            inference_ms=inference_ms,
            geometry_ms=geometry_ms,
            draw_ms=draw_ms,
            queued_at=queued_at,
        )
        return annotated, to_view_state(detected), gestures, timing

    def _queue_events(self, events: tuple[FingerPressEvent, ...]) -> float | None:
        """Encola las pulsaciones y avisa a la interfaz antes de dibujar."""
        if not events:
            return None
        clock = time.perf_counter()
        self._mutex.lock()
        try:
            self._pending_events.extend(events)
            self._event_clock = clock
        finally:
            self._mutex.unlock()
        self.presses_detected.emit()
        return clock

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

    def _publish(
        self,
        image: QImage,
        fps: float | None,
        hands: HandViewState,
        fingers: GestureUpdate,
        timing: FrameTiming,
    ) -> None:
        self._mutex.lock()
        try:
            self._latest_image = image
            self._fps = fps
            self._hands = hands
            self._fingers = fingers
            self._timing = timing
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
            self._fingers = GestureUpdate.inactive()
            self._pending_events.clear()
            self._event_clock = None
            self._timing = FrameTiming()
            self._reset_counts = False
            self._calibration = None
            self._frame_times.clear()
        finally:
            self._mutex.unlock()
