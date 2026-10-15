"""Ventana principal. Coordina la cámara, el piano y un solo motor de audio."""

from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from fingermelody.audio.audio_engine import AudioEngine, AudioError
from fingermelody.gestures.gesture_engine import GestureUpdate, format_gesture_column
from fingermelody.interface.camera_panel import CameraPanel
from fingermelody.interface.camera_worker import CameraWorker
from fingermelody.interface.info_panel import InfoPanel, finger_caption
from fingermelody.interface.piano_widget import PianoWidget
from fingermelody.interface.settings_dialog import SettingsDialog
from fingermelody.interface.styles import STYLESHEET, restyle
from fingermelody.music.note_mapper import NoteMapper
from fingermelody.vision.camera_manager import CameraManager
from fingermelody.vision.hand_tracker import (
    ACTIVE_TRACKING_MESSAGE,
    IDLE_TRACKING_MESSAGE,
    NO_HANDS_MESSAGE,
    HandViewState,
)

_QUIET_TRACKING = {IDLE_TRACKING_MESSAGE, NO_HANDS_MESSAGE, ACTIVE_TRACKING_MESSAGE}
_PLAYED_LIMIT = 64


class MainWindow(QMainWindow):
    """Cámara, piano e indicadores. El modelo sigue en el hilo de captura."""

    def __init__(
        self,
        device_index: int = 0,
        width: int = 640,
        height: int = 480,
        audio_engine: AudioEngine | None = None,
    ) -> None:
        super().__init__()
        self._state = "idle"
        self._closing = False
        self._error_message: str | None = None
        self._shown_sequence = 0
        self._current_image: QImage | None = None
        self._rescaling = False
        self._split_ready = False
        self._session_presses = 0
        self._muted = False
        self._played_keys: set[tuple[str, int]] = set()
        self._played_order: deque[tuple[str, int]] = deque()
        self._diagnostics = False
        self._settings_dialog = None
        self._diag_event = "Evento: —"
        self._diag_dispatch_ms: float | None = None
        self._diag_play_ms: float | None = None
        self._calibration_note = ""
        self._manager = CameraManager(device_index, width, height)
        self._worker = CameraWorker(self._manager)
        self._worker.capture_started.connect(self._on_capture_started)
        self._worker.capture_stopped.connect(self._on_capture_stopped)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.tracking_warning.connect(self._on_tracking_warning)
        self._worker.calibration_saved.connect(self._on_calibration_saved)
        self._warning_box: QMessageBox | None = None
        self._audio = audio_engine if audio_engine is not None else AudioEngine()
        self._mapper = NoteMapper()
        self._audio_closed = False

        self.setWindowTitle("FingerMelody")
        self.setStyleSheet(STYLESHEET)
        self.setMinimumSize(960, 640)
        self.resize(1180, 760)
        self._build_ui(device_index, width, height)
        self._update_buttons()
        self._worker.presses_detected.connect(self._on_presses_detected)

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
        self._set_fps("FPS: —")
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
        """Detiene la captura y el audio antes de cerrar la ventana."""
        if not self._audio_closed:
            self._audio.shutdown()
            self._audio_closed = True
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

    def showEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        super().showEvent(event)
        self._balance_split()

    def resizeEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        super().resizeEvent(event)
        self._balance_split()
        self._rescale_preview()

    def _build_ui(self, device_index: int, width: int, height: int) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        self._audio.initialize()
        self._audio.set_volume(0.7)

        title = QLabel("FingerMelody")
        title.setObjectName("titleLabel")
        self._camera_chip = QLabel("Cámara inactiva")
        self._camera_chip.setObjectName("cameraChip")
        self._tracking_label = QLabel(IDLE_TRACKING_MESSAGE)
        self._tracking_label.setObjectName("trackingLabel")
        self._volume_label = QLabel("Volumen 70 %")
        self._volume_label.setObjectName("volumeLabel")
        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setObjectName("volumeSlider")
        self._volume.setRange(0, 100)
        self._volume.setValue(70)
        self._volume.setFixedWidth(140)
        self._volume.valueChanged.connect(self._change_volume)
        settings = QPushButton("Configuración")
        settings.setObjectName("settingsButton")
        settings.clicked.connect(self._open_settings)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(title)
        header.addWidget(self._camera_chip)
        header.addWidget(self._tracking_label, stretch=1)
        header.addWidget(self._volume_label)
        header.addWidget(self._volume)
        header.addWidget(settings)

        self._camera_panel = CameraPanel(f"Dispositivo {device_index} · {width}×{height}")
        self._device_label = self._camera_panel.device
        self._preview = self._camera_panel.preview
        self._fps_label = self._camera_panel.fps
        self._preview.resized.connect(self._rescale_preview)

        self._info = InfoPanel()
        self._hands_label = self._info.hands
        self._left_label = self._info.left
        self._right_label = self._info.right
        self._last_note = self._info.last_note
        self._last_finger = self._info.last_finger
        self._press_count = self._info.presses
        self._info_fps = self._info.fps
        self._status_label = self._info.camera
        self._audio_status = self._info.audio
        self._audio_status.setText(self._audio.status_message)
        self._left_fingers = self._info.left_fingers
        self._right_fingers = self._info.right_fingers

        self._piano = PianoWidget()
        self._piano.set_captions(
            {
                note_name: f"{note_name} · {finger_caption(finger)}"
                for finger, note_name in self._mapper.assignments()
            }
        )
        self._piano.note_pressed.connect(self._play_clicked_note)
        self._apply_gestures(GestureUpdate.inactive())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("mainSplit")
        self._splitter = splitter
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._camera_panel)
        splitter.addWidget(self._info)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self._start_button = QPushButton("Iniciar cámara")
        self._start_button.setObjectName("startButton")
        self._start_button.clicked.connect(self.start_camera)
        self._stop_button = QPushButton("Detener cámara")
        self._stop_button.setObjectName("stopButton")
        self._stop_button.clicked.connect(self.stop_camera)
        self._mute_button = QPushButton("Silenciar audio")
        self._mute_button.setObjectName("muteButton")
        self._mute_button.clicked.connect(self._toggle_mute)
        self._stop_audio = QPushButton("Detener sonidos")
        self._stop_audio.setObjectName("stopAudioButton")
        self._stop_audio.clicked.connect(self._stop_sounds)
        self._reset_button = QPushButton("Reiniciar pulsaciones")
        self._reset_button.setObjectName("resetPressButton")
        self._reset_button.clicked.connect(self._reset_press_count)
        self._diagnostic_button = QPushButton("Diagnóstico")
        self._diagnostic_button.setObjectName("diagnosticButton")
        self._diagnostic_button.setCheckable(True)
        self._diagnostic_button.toggled.connect(self._toggle_diagnostics)
        self._stop_audio.setEnabled(self._audio.available)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self._start_button)
        controls.addWidget(self._stop_button)
        controls.addWidget(self._mute_button)
        controls.addWidget(self._stop_audio)
        controls.addWidget(self._reset_button)
        controls.addWidget(self._diagnostic_button)
        controls.addStretch(1)

        layout.addLayout(header)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self._piano)
        layout.addLayout(controls)
        self._sync_camera_chip()

    def _show_latest_frame(self) -> None:
        image, fps, sequence, hands, gestures, timing = self._worker.latest()
        self._handle_press_events(self._worker.take_events())
        if fps is not None:
            self._set_fps(f"FPS: {fps:.1f}")
        self._apply_hand_state(hands)
        self._apply_gestures(gestures)
        self._refresh_diagnostics(gestures, timing)
        if image is None or sequence == self._shown_sequence:
            return
        self._shown_sequence = sequence
        self._current_image = image
        self._paint_preview(image)

    def _on_presses_detected(self) -> None:
        if self._closing:
            self._worker.take_events()
            return
        self._handle_press_events(self._worker.take_events())
        _image, _fps, _sequence, hands, gestures, timing = self._worker.latest()
        self._apply_hand_state(hands)
        self._apply_gestures(gestures)
        self._refresh_diagnostics(gestures, timing)

    def _paint_preview(self, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image)
        target = self._preview.size()
        if target.width() > 0 and target.height() > 0:
            pixmap = pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        self._preview.setPixmap(pixmap)

    def _balance_split(self) -> None:
        if self._split_ready or not hasattr(self, "_splitter"):
            return
        total = self._splitter.width()
        if total < 400:
            return
        self._split_ready = True
        info = min(480, max(340, int(total * 0.36)))
        self._splitter.setSizes([max(1, total - info), info])

    def _rescale_preview(self) -> None:
        if self._rescaling or self._current_image is None:
            return
        self._rescaling = True
        try:
            self._paint_preview(self._current_image)
        finally:
            self._rescaling = False

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
        self._apply_hand_state(HandViewState())
        self._apply_gestures(GestureUpdate.inactive())
        if self._closing or self._error_message is not None:
            return
        self._set_status("Detenida")
        self._set_fps("FPS: —")

    def _apply_hand_state(self, state: HandViewState) -> None:
        self._tracking_label.setText(state.message)
        if state.both_present:
            tone = "ok"
        elif state.message not in _QUIET_TRACKING:
            tone = "warn"
        else:
            tone = "idle"
        self._tracking_label.setProperty("tone", tone)
        restyle(self._tracking_label)
        if state.message == IDLE_TRACKING_MESSAGE:
            self._hands_label.setText("Manos: —")
            self._left_label.setText("Izquierda: —")
            self._right_label.setText("Derecha: —")
            return
        self._hands_label.setText(f"Manos: {state.hand_count}")
        self._left_label.setText(
            "Izquierda: detectada" if state.left_present else "Izquierda: ausente"
        )
        self._right_label.setText(
            "Derecha: detectada" if state.right_present else "Derecha: ausente"
        )

    def _apply_gestures(self, update: GestureUpdate) -> None:
        left = tuple(state for state in update.states if state.hand == "Left")
        right = tuple(state for state in update.states if state.hand == "Right")
        self._left_fingers.setText(format_gesture_column("MANO IZQUIERDA", left, active=update.active))
        self._right_fingers.setText(format_gesture_column("MANO DERECHA", right, active=update.active))
        self._sync_piano(update)

    def _sync_piano(self, update: GestureUpdate) -> None:
        if not update.active:
            self._piano.set_gesture_notes(set())
            return
        notes = set()
        for state in update.states:
            if not state.highlight:
                continue
            name = self._mapper.note_name(state.finger_id)
            if name:
                notes.add(name)
        self._piano.set_gesture_notes(notes)

    def _handle_press_events(self, events) -> None:
        if not events:
            return
        clock = self._worker.event_clock()
        dispatch_ms = None if clock is None else (time.perf_counter() - clock) * 1000.0
        for event in events:
            if not self._accept_press(event):
                continue
            note = self._mapper.note_name(event.finger_id)
            if not note:
                continue
            started = time.perf_counter()
            self._play_note(note)
            self._diag_play_ms = (time.perf_counter() - started) * 1000.0
            self._diag_dispatch_ms = dispatch_ms
            self._diag_event = f"Evento {event.finger_id} → {note}"
            self._remember(note, finger_caption(event.finger_id))

    def _accept_press(self, event) -> bool:
        key = (event.finger_id, int(event.timestamp_ms))
        if key in self._played_keys:
            return False
        self._played_keys.add(key)
        self._played_order.append(key)
        while len(self._played_order) > _PLAYED_LIMIT:
            self._played_keys.discard(self._played_order.popleft())
        return True

    def _play_clicked_note(self, note_name: str) -> None:
        if self._play_note(note_name):
            self._remember(note_name, "Teclado")
        self._piano.pulse_click(note_name)

    def _play_note(self, note_name: str) -> bool:
        try:
            played = self._audio.play_note(note_name)
        except AudioError as exc:
            self._audio_status.setText(str(exc))
            self._audio_status.setProperty("error", "yes")
            restyle(self._audio_status)
            return False
        if not played:
            self._audio_status.setText(self._audio.status_message)
            self._audio_status.setProperty("error", "yes")
            restyle(self._audio_status)
            return False
        self._show_audio_status()
        return True

    def _show_audio_status(self) -> None:
        if self._muted and self._audio.available:
            text = "Audio en silencio"
        else:
            text = self._audio.status_message
        if self._audio_status.text() != text:
            self._audio_status.setText(text)
        if self._audio_status.property("error") != "no":
            self._audio_status.setProperty("error", "no")
            restyle(self._audio_status)

    def _remember(self, note_name: str, finger_text: str) -> None:
        self._session_presses += 1
        self._press_count.setText(f"Pulsaciones: {self._session_presses}")
        self._last_note.setText(f"Última nota: {note_name}")
        self._last_finger.setText(f"Dedo: {finger_text}")

    def _change_volume(self, value: int) -> None:
        if self._muted:
            self._volume_label.setText(f"Silencio · {value} %")
            return
        self._volume_label.setText(f"Volumen {value} %")
        self._apply_volume(value / 100.0)

    def _toggle_mute(self) -> None:
        self._muted = not self._muted
        self._mute_button.setText("Activar audio" if self._muted else "Silenciar audio")
        self._mute_button.setProperty("muted", "yes" if self._muted else "no")
        restyle(self._mute_button)
        if self._muted:
            self._apply_volume(0.0)
            self._volume_label.setText(f"Silencio · {self._volume.value()} %")
            if self._audio.available:
                self._audio_status.setText("Audio en silencio")
                self._audio_status.setProperty("error", "no")
                restyle(self._audio_status)
            return
        self._volume_label.setText(f"Volumen {self._volume.value()} %")
        self._apply_volume(self._volume.value() / 100.0)
        self._audio_status.setText(self._audio.status_message)
        self._audio_status.setProperty("error", "no")
        restyle(self._audio_status)

    def _apply_volume(self, value: float) -> None:
        try:
            self._audio.set_volume(value)
        except AudioError as exc:
            self._audio_status.setText(str(exc))

    def _stop_sounds(self) -> None:
        self._audio.stop_all()
        self._piano.clear_clicks()

    def _reset_press_count(self) -> None:
        self._session_presses = 0
        self._press_count.setText("Pulsaciones: 0")
        self._piano.set_gesture_notes(set())
        self._worker.request_count_reset()

    def _open_settings(self) -> None:
        if self._muted and self._audio.available:
            status = "Audio en silencio"
        else:
            status = self._audio.status_message
        dialog = SettingsDialog(
            self._mapper,
            status,
            self._device_label.text(),
            self,
            on_capture_rest=lambda: self._request_calibration("rest"),
            on_capture_flex=lambda: self._request_calibration("flex"),
        )
        self._settings_dialog = dialog
        if self._calibration_note:
            dialog.set_calibration_message(self._calibration_note)
        dialog.exec()
        self._settings_dialog = None

    def _request_calibration(self, kind: str) -> str:
        if not self._worker.isRunning():
            return "Inicia la cámara y mantén la pose delante del objetivo."
        self._worker.request_calibration(kind)
        if kind == "rest":
            return "Reposo pedido. Mantén los dedos extendidos un instante."
        return "Flexión pedida. Flexiona el pulgar y los dedos que quieras ajustar."

    def _on_calibration_saved(self, message: str) -> None:
        self._calibration_note = message
        if self._settings_dialog is not None:
            self._settings_dialog.set_calibration_message(message)

    def _toggle_diagnostics(self, enabled: bool) -> None:
        self._diagnostics = enabled
        self._info.diagnostic.setVisible(enabled)
        if enabled:
            _image, _fps, _sequence, _hands, gestures, timing = self._worker.latest()
            self._refresh_diagnostics(gestures, timing)

    def _refresh_diagnostics(self, gestures: GestureUpdate, timing) -> None:
        if not self._diagnostics:
            return
        lines: list[str] = []
        if gestures.active:
            for state in gestures.states:
                if state.phase == "LOST" and state.angle is None:
                    continue
                parts = [f"{state.display_name} {state.finger_id} {state.phase}"]
                if state.angle is not None:
                    parts.append(f"{state.angle:.0f}°")
                if state.extension is not None:
                    parts.append(f"ext {state.extension:.2f}")
                if state.opposition is not None:
                    parts.append(f"op {state.opposition:.2f}")
                if state.flex_ms:
                    parts.append(f"{state.flex_ms} ms")
                lines.append(" · ".join(parts))
        lines.append(self._diag_event)
        if timing is not None:
            lines.append(
                "Captura "
                f"{timing.capture_ms:.1f} ms · modelo {timing.inference_ms:.1f} ms · "
                f"geometría {timing.geometry_ms:.1f} ms · dibujo {timing.draw_ms:.1f} ms"
            )
        dispatch = "—" if self._diag_dispatch_ms is None else f"{self._diag_dispatch_ms:.1f} ms"
        play = "—" if self._diag_play_ms is None else f"{self._diag_play_ms:.2f} ms"
        lines.append(f"Hasta audio {dispatch} · play_note {play}")
        if self._calibration_note:
            lines.append(self._calibration_note)
        self._info.diagnostic.setText("\n".join(lines))

    def _on_tracking_warning(self, message: str) -> None:
        self._apply_hand_state(HandViewState(active=False, message=message))
        if self._closing:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("FingerMelody")
        box.setText(message)
        box.setModal(False)
        box.show()
        self._warning_box = box

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self._status_label.setText(text)
        self._status_label.setProperty("error", "yes" if error else "no")
        restyle(self._status_label)
        self._sync_camera_chip()

    def _set_fps(self, text: str) -> None:
        self._fps_label.setText(text)
        self._info_fps.setText(text)

    def _sync_camera_chip(self) -> None:
        if self._state == "live":
            text, state = "Cámara activa", "on"
        elif self._state in {"starting", "stopping"}:
            text, state = "Cámara en transición", "busy"
        else:
            text, state = "Cámara inactiva", "off"
        self._camera_chip.setText(text)
        self._camera_chip.setProperty("state", state)
        restyle(self._camera_chip)

    def _update_buttons(self) -> None:
        running = self._worker.isRunning()
        self._start_button.setEnabled(self._state == "idle" and not running)
        self._stop_button.setEnabled(running or self._state in {"starting", "live", "stopping"})
        self._sync_camera_chip()
