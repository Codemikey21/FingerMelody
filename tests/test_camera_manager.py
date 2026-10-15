"""Pruebas del acceso a la cámara sin usar un dispositivo real."""

import numpy as np
import pytest

from fingermelody.vision import camera_manager
from fingermelody.vision.camera_manager import (
    ALREADY_OPEN_MESSAGE,
    CAMERA_UNAVAILABLE_MESSAGE,
    FRAME_READ_MESSAGE,
    NOT_OPEN_MESSAGE,
    CameraAlreadyOpenError,
    CameraManager,
    CameraNotOpenError,
    CameraUnavailableError,
    FrameReadError,
)


class ScriptedCapture:
    def __init__(self, opened=True, frames=None):
        self.opened = opened
        self.frames = [] if frames is None else list(frames)
        self.release_count = 0
        self.props = []

    def isOpened(self):
        return self.opened

    def release(self):
        self.release_count += 1
        self.opened = False

    def set(self, prop, value):
        self.props.append((int(prop), value))
        return True

    def read(self):
        if not self.frames:
            return False, None
        frame = self.frames.pop(0)
        if frame is None:
            return False, None
        return True, frame


@pytest.fixture
def single_backend(monkeypatch):
    monkeypatch.setattr(CameraManager, "_candidate_backends", lambda self: [None])


def install_captures(monkeypatch, captures):
    pending = list(captures)
    created = []

    def factory(*args, **kwargs):
        created.append(args)
        if not pending:
            raise AssertionError("Se intentó abrir la cámara más veces de las previstas.")
        return pending.pop(0)

    monkeypatch.setattr(camera_manager.cv2, "VideoCapture", factory)
    return created


def frame(value=0, shape=(4, 6, 3)):
    image = np.zeros(shape, dtype=np.uint8)
    image[..., 0] = value
    return image


def test_manager_starts_closed_with_default_configuration():
    manager = CameraManager()

    assert manager.device_index == 0
    assert manager.resolution == (640, 480)
    assert manager.is_open is False


def test_open_configures_resolution_and_reads_a_private_copy(single_backend, monkeypatch):
    delivered = frame(3)
    install_captures(monkeypatch, [ScriptedCapture(frames=[frame(1), delivered])])
    manager = CameraManager()

    manager.open()
    copied = manager.read()
    delivered[..., 0] = 9

    assert manager.is_open is True
    assert copied.shape == delivered.shape
    assert copied[0, 0, 0] == 3
    width = int(camera_manager.cv2.CAP_PROP_FRAME_WIDTH)
    height = int(camera_manager.cv2.CAP_PROP_FRAME_HEIGHT)
    props = manager._capture.props
    assert (width, 640.0) in props
    assert (height, 480.0) in props


def test_unavailable_camera_is_released(single_backend, monkeypatch):
    missing = ScriptedCapture(opened=False, frames=[])
    install_captures(monkeypatch, [missing])
    manager = CameraManager()

    with pytest.raises(CameraUnavailableError, match=CAMERA_UNAVAILABLE_MESSAGE):
        manager.open()

    assert missing.release_count == 1
    assert manager.is_open is False


def test_failed_backend_falls_back_to_the_next_one(monkeypatch):
    monkeypatch.setattr(CameraManager, "_candidate_backends", lambda self: [1, None])
    rejected = ScriptedCapture(opened=True, frames=[])
    accepted = ScriptedCapture(frames=[frame()])
    created = install_captures(monkeypatch, [rejected, accepted])
    manager = CameraManager(device_index=0)

    manager.open()

    assert [call[1] if len(call) > 1 else None for call in created] == [1, None]
    assert rejected.release_count == 1
    assert accepted.release_count == 0
    assert manager.is_open is True
    manager.close()


def test_windows_tries_directshow_before_the_default_backend(monkeypatch):
    monkeypatch.setattr(camera_manager.sys, "platform", "win32")

    backends = CameraManager()._candidate_backends()

    assert int(backends[0]) == int(camera_manager.cv2.CAP_DSHOW)
    assert backends[-1] is None


def test_read_failure_and_read_without_opening(single_backend, monkeypatch):
    install_captures(monkeypatch, [ScriptedCapture(frames=[frame(), None])])
    manager = CameraManager()
    closed = CameraManager()

    manager.open()
    with pytest.raises(FrameReadError, match=FRAME_READ_MESSAGE):
        manager.read()
    with pytest.raises(CameraNotOpenError, match=NOT_OPEN_MESSAGE):
        closed.read()


def test_close_is_idempotent_and_second_open_is_rejected(single_backend, monkeypatch):
    capture = ScriptedCapture(frames=[frame(), frame()])
    created = install_captures(monkeypatch, [capture])
    manager = CameraManager()

    manager.open()
    with pytest.raises(CameraAlreadyOpenError, match=ALREADY_OPEN_MESSAGE):
        manager.open()
    manager.close()
    manager.close()

    assert len(created) == 1
    assert capture.release_count == 1
    assert manager.is_open is False


def test_resolution_can_be_changed(single_backend, monkeypatch):
    capture = ScriptedCapture(frames=[frame()])
    install_captures(monkeypatch, [capture])
    manager = CameraManager(width=320, height=240)

    manager.open()
    manager.set_resolution(800, 600)

    assert manager.resolution == (800, 600)
    assert (int(camera_manager.cv2.CAP_PROP_FRAME_WIDTH), 800.0) in capture.props
    assert (int(camera_manager.cv2.CAP_PROP_FRAME_HEIGHT), 600.0) in capture.props
    with pytest.raises(ValueError):
        CameraManager(device_index=-1)
    with pytest.raises(ValueError):
        manager.set_resolution(0, 480)
