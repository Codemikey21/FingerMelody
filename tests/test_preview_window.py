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
    assert window.findChild(QLabel, "leftFingerPanel").text().startswith("MANO IZQUIERDA")
    assert "Pulgar — —" in window.findChild(QLabel, "leftFingerPanel").text()
    assert "Índice — —" in window.findChild(QLabel, "rightFingerPanel").text()
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


def test_finger_panel_lists_detected_fingers_without_calling_them_pressed(qapp):
    from fingermelody.gestures.finger_detector import FingerDetector, format_panel_column
    from fingermelody.vision.hand_tracker import HandFrame, TrackedHand

    pixels = tuple((10, 10) for _ in range(21))
    normalized = tuple((0.4, 0.4, 0.0) for _ in range(21))
    observed = FingerDetector().identify(
        HandFrame(
            hands=(
                TrackedHand("Left", 0.9, normalized, pixels),
                TrackedHand("Right", 0.9, normalized, pixels),
            ),
            width=64,
            height=64,
        )
    )
    window = PreviewWindow()
    window._apply_finger_panel(observed.panel)

    left = window.findChild(QLabel, "leftFingerPanel").text()
    right = window.findChild(QLabel, "rightFingerPanel").text()
    assert left == format_panel_column("MANO IZQUIERDA", observed.panel.left_lines, active=True)
    assert "Pulgar — Detectado" in left
    assert "Meñique — Detectado" in right
    assert "puls" not in left.casefold()
    window.close()
