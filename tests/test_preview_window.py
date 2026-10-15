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
    assert window.findChild(QLabel, "trackingLabel").text() == "Reconocimiento inactivo"
    assert window.findChild(QLabel, "handsLabel").text() == "Manos: —"
    assert window.findChild(QLabel, "leftHandLabel").text() == "Izquierda: —"
    assert window.findChild(QLabel, "rightHandLabel").text() == "Derecha: —"
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


def test_both_hands_update_the_indicators(qapp):
    from fingermelody.vision.hand_tracker import HandViewState

    window = PreviewWindow()
    window._apply_hand_state(
        HandViewState(
            active=True,
            hand_count=2,
            left_present=True,
            right_present=True,
            message="Ambas manos presentes",
        )
    )

    assert window.findChild(QLabel, "trackingLabel").text() == "Ambas manos presentes"
    assert window.findChild(QLabel, "handsLabel").text() == "Manos: 2"
    assert window.findChild(QLabel, "leftHandLabel").text() == "Izquierda: detectada"
    assert window.findChild(QLabel, "rightHandLabel").text() == "Derecha: detectada"
    window.close()
