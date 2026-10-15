"""Comprueba la ventana provisional sin abrir la cámara."""

from PySide6.QtWidgets import QLabel, QPushButton

from fingermelody.interface.preview_window import PreviewWindow


def test_preview_window_shows_camera_controls(qapp):
    window = PreviewWindow()
    window.show()
    qapp.processEvents()

    assert window.windowTitle() == "FingerMelody"
    assert window.findChild(QLabel, "titleLabel").text() == "FingerMelody"
    assert window.findChild(QLabel, "deviceLabel").text() == "Dispositivo 0 · 640×480"
    assert window.findChild(QPushButton, "startButton").text() == "Iniciar cámara"
    assert window.findChild(QPushButton, "stopButton").text() == "Detener cámara"
    assert window.findChild(QLabel, "statusLabel").text() == "Detenida"
    assert window.findChild(QLabel, "fpsLabel").text() == "FPS: —"
    assert window.findChild(QPushButton, "startButton").isEnabled()
    assert window.findChild(QPushButton, "stopButton").isEnabled() is False

    window.close()
    assert window._worker.isRunning() is False


def test_start_is_ignored_when_the_camera_is_already_live(qapp):
    window = PreviewWindow()

    window._state = "live"
    window.start_camera()

    assert window._worker.isRunning() is False
    assert window.findChild(QLabel, "statusLabel").text() == "La cámara ya está iniciada."
    window.close()
