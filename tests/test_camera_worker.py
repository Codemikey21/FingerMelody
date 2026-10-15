"""Pruebas del hilo de captura con un administrador simulado."""

import time

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy

from fingermelody.interface.camera_worker import (
    LOST_CONNECTION_MESSAGE,
    CameraWorker,
    bgr_frame_to_qimage,
)
from fingermelody.vision.camera_manager import (
    CAMERA_UNAVAILABLE_MESSAGE,
    CameraUnavailableError,
    FrameReadError,
)


class FakeManager:
    def __init__(self, frames=None, open_error=None):
        self._frames = [] if frames is None else list(frames)
        self._open_error = open_error
        self.opened = False
        self.close_count = 0

    @property
    def is_open(self):
        return self.opened and self.close_count == 0

    def open(self):
        if self._open_error is not None:
            raise self._open_error
        self.opened = True

    def close(self):
        self.close_count += 1

    def read(self):
        if not self._frames:
            raise FrameReadError("sin fotograma")
        return self._frames.pop(0)


def wait_for_spy(spy, qapp, timeout=3.0):
    deadline = time.monotonic() + timeout
    while spy.count() == 0 and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    return spy.count() > 0


def test_bgr_frame_becomes_an_owned_rgb_image(qapp):
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    frame[..., 0] = 255

    image = bgr_frame_to_qimage(frame)
    frame[..., 0] = 0
    color = QColor(image.pixel(0, 0))

    assert image.width() == 6
    assert image.height() == 4
    assert image.format() == QImage.Format.Format_RGB888
    assert (color.red(), color.green(), color.blue()) == (0, 0, 255)


def test_unavailable_camera_emits_error_and_does_not_close(qapp):
    manager = FakeManager(open_error=CameraUnavailableError(CAMERA_UNAVAILABLE_MESSAGE))
    worker = CameraWorker(manager)
    errors = QSignalSpy(worker.error_occurred)

    worker.start()
    assert wait_for_spy(errors, qapp)
    assert worker.wait(3000)

    assert errors.at(0)[0] == CAMERA_UNAVAILABLE_MESSAGE
    assert manager.close_count == 0


def test_repeated_read_failures_stop_and_release_the_camera(qapp):
    manager = FakeManager()
    worker = CameraWorker(manager)
    errors = QSignalSpy(worker.error_occurred)

    worker.start()
    assert wait_for_spy(errors, qapp)
    assert worker.wait(3000)

    assert errors.at(0)[0] == LOST_CONNECTION_MESSAGE
    assert manager.close_count == 1
    assert manager.opened is True


def test_fps_is_measured_from_frame_timestamps(qapp):
    worker = CameraWorker(FakeManager())

    assert worker._measure_fps(1.0) is None
    assert worker._measure_fps(1.5) == pytest.approx(2.0)
