"""Ventana principal. Coordina la cámara, el piano y un solo motor de audio."""

from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from fingermelody.audio.audio_engine import AudioEngine, AudioError
from fingermelody.gestures.gesture_engine import (
    PHASE_HELD,
    PHASE_PRESSED,
    GestureUpdate,
    format_gesture_column,
)
from fingermelody.interface.camera_panel import CameraPanel
from fingermelody.interface.camera_worker import CameraWorker
from fingermelody.interface.info_panel import InfoPanel, finger_caption
from fingermelody.interface.note_highway import NoteHighway
from fingermelody.interface.musical_scene import MusicalScene
from fingermelody.interface.piano_widget import PianoWidget
from fingermelody.interface.settings_dialog import SettingsDialog
from fingermelody.interface.styles import STYLESHEET, restyle
from fingermelody.music.note_mapper import NoteMapper
from fingermelody.music.session import (
    ORIGIN_CLICK,
    ORIGIN_GESTURE,
    PHASE_IDLE,
    PHASE_PAUSED,
    PHASE_PLAYING,
    HistoryEntry,
    MusicalEvent,
    SessionController,
)
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
        self._muted = False
        self._session = SessionController()
        self._mode = "free"
        self._event_floor_ms = None
        self._guided_history = deque(maxlen=48)
        self._guided_count_offset = 0
        self._guided_started = 0.0
        self._guided_pause_at = None
        self._guided_paused_span = 0.0
        self._played_keys: set[tuple[str, int]] = set()
        self._played_order: deque[tuple[str, int]] = deque()
        self._diagnostics = False
        self._settings_dialog = None
        self._diag_event = "Evento: —"
        self._diag_dispatch_ms: float | None = None
        self._diag_play_ms: float | None = None
        self._calibration_note = ""
        self._manager = CameraManager(device_index, width, height)
        self._worker = CameraWorker(self._manager, parent=self)
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
        """Detiene temporizadores, captura y audio antes de destruir la ventana."""
        for timer in self.findChildren(QTimer):
            timer.stop()
        if hasattr(self, "_highway"):
            self._highway.shutdown()
        if not self._audio_closed:
            self._audio.shutdown()
            self._audio_closed = True
        if self._closing and self._state == "idle" and not self._worker.isRunning():
            return
        self._closing = True
        if self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(2000)
        self._state = "idle"

    def closeEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        self.shutdown()
        event.accept()

    def showEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        super().showEvent(event)
        self._place_camera(reveal=True)

    def resizeEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        super().resizeEvent(event)
        self._place_camera(reveal=False)
        self._rescale_preview()
        self._sync_highway_lanes()

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
        self._volume_label = QLabel("Volumen 70 %")
        self._volume_label.setObjectName("volumeLabel")
        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setObjectName("volumeSlider")
        self._volume.setRange(0, 100)
        self._volume.setValue(70)
        self._volume.setFixedWidth(120)
        self._volume.valueChanged.connect(self._change_volume)
        settings = QPushButton("Configuración")
        settings.setObjectName("settingsButton")
        settings.clicked.connect(self._open_settings)

        self._info = InfoPanel()
        self._info.mode.setText("Modo libre")
        self._info.start_session.clicked.connect(self.start_session)
        self._info.pause_session.clicked.connect(self.pause_session)
        self._info.resume_session.clicked.connect(self.resume_session)
        self._info.finish_session.clicked.connect(self.finish_session)
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
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(title)
        self._mode_selector = QComboBox()
        self._mode_selector.setObjectName("modeSelector")
        self._mode_selector.addItem("Modo libre", "free")
        self._mode_selector.addItem("Modo guiado", "guided")
        self._mode_selector.setFixedWidth(140)
        self._mode_selector.setStyleSheet("QComboBox {background:#14172b; color:#bfeeff; border:1px solid #5763ac; border-radius:6px; padding:6px;}")
        self._mode_selector.currentIndexChanged.connect(self._select_mode)
        header.addWidget(self._mode_selector)
        header.addStretch(1)
        header.addWidget(self._volume_label)
        header.addWidget(self._volume)
        header.addWidget(settings)
        header.addWidget(self._info.session)

        self._camera_panel = CameraPanel(f"Dispositivo {device_index} · {width}×{height}")
        self._device_label = self._camera_panel.device
        self._preview = self._camera_panel.preview
        self._fps_label = self._camera_panel.fps
        self._preview.resized.connect(self._rescale_preview)
        self._start_button = QPushButton("Iniciar")
        self._start_button.setObjectName("startButton")
        self._start_button.clicked.connect(self.start_camera)
        self._stop_button = QPushButton("Detener")
        self._stop_button.setObjectName("stopButton")
        self._stop_button.clicked.connect(self.stop_camera)
        self._camera_panel._actions.addWidget(self._start_button)
        self._camera_panel._actions.addWidget(self._stop_button)
        details = QPushButton("Detalles")
        details.setObjectName("detailsButton")
        details.clicked.connect(self._open_details)
        self._camera_panel._actions.addWidget(details)

        self._piano = PianoWidget()
        self._piano.set_captions(
            {
                note_name: f"{note_name} · {finger_caption(finger)}"
                for finger, note_name in self._mapper.assignments()
            }
        )
        self._piano.note_pressed.connect(self._play_clicked_note)
        self._piano.lanes_changed.connect(self._sync_highway_lanes)
        self._apply_gestures(GestureUpdate.inactive())

        self._highway = NoteHighway()
        self._highway.resized.connect(self._sync_highway_lanes)

        self._stage = MusicalScene(self._highway, self._piano, self._camera_panel)
        session_row = QHBoxLayout()
        session_row.setSpacing(8)
        session_row.addWidget(self._info.start_session)
        session_row.addWidget(self._info.pause_session)
        session_row.addWidget(self._info.resume_session)
        session_row.addWidget(self._info.finish_session)
        self._guide_progress = QLabel("")
        self._guide_progress.hide()
        session_row.addWidget(self._guide_progress)
        session_row.addWidget(self._last_note)
        session_row.addStretch(1)
        session_row.addWidget(self._info.history, stretch=1)

        self._tracking_label = QLabel(IDLE_TRACKING_MESSAGE)
        self._tracking_label.setObjectName("trackingLabel")
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
        technical = QHBoxLayout()
        technical.setSpacing(8)
        technical.addWidget(self._mute_button)
        technical.addWidget(self._stop_audio)
        technical.addWidget(self._reset_button)
        technical.addWidget(self._diagnostic_button)
        self._details = QDialog(self)
        self._details.setObjectName("detailsDialog")
        self._details.setWindowTitle("Detalles")
        self._details.setModal(False)
        details_layout = QVBoxLayout(self._details)
        details_layout.setContentsMargins(16, 16, 16, 16)
        details_layout.setSpacing(8)
        details_layout.addWidget(self._tracking_label)
        details_layout.addWidget(self._last_finger)
        details_layout.addLayout(technical)
        details_layout.addWidget(self._info)
        self._details.resize(460, 640)
        self._details.hide()

        layout.addLayout(header)
        self._guide_hint = QLabel("")
        self._guide_hint.setWordWrap(True)
        self._guide_hint.setStyleSheet("color:#c5d6ee; padding:2px 4px;")
        self._guide_hint.hide()
        layout.addWidget(self._guide_hint)
        layout.addWidget(self._stage, stretch=1)
        layout.addLayout(session_row)
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

    def _place_camera(self, reveal: bool) -> None:
        """La escena mantiene libre el carril de la nota esperada."""
        if hasattr(self, "_stage"):
            self._stage.place_camera(reveal)

    def _open_details(self) -> None:
        self._details.show()
        self._details.raise_()

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
        self._release_open_fingers(update)
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
        token = self._guide.batch_token if self._mode == "guided" else None
        for event in events:
            if self._event_floor_ms is not None and event.timestamp_ms <= self._event_floor_ms:
                continue
            if not self._accept_press(event):
                continue
            note = self._mapper.note_name(event.finger_id)
            if not note:
                continue
            self._diag_dispatch_ms = dispatch_ms
            accepted = self._perform(
                MusicalEvent(note, ORIGIN_GESTURE, event.finger_id), expected_step=token
            )
            if accepted is None:
                if self._mode == "free":
                    self._diag_event = f"Evento {event.finger_id} → {note} (sin reproducción)"
                continue
            self._diag_event = f"Evento {event.finger_id} → {note}"

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
        self._perform(MusicalEvent(note_name, ORIGIN_CLICK))

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

    def _perform(self, event: MusicalEvent, *, expected_step=None) -> HistoryEntry | None:
        if self._mode == "guided":
            token = self._guide.batch_token if expected_step is None else expected_step
            result = self._guide.submit_result(event.note, event.finger_id, expected_step=token)
            if not result.accepted:
                self._diag_event = f"Guiado: {result.reason.value}"
                return None
            elapsed = time.monotonic() - self._guided_started - self._guided_paused_span
            accepted = HistoryEntry(event.note, event.finger_id, event.origin, round(elapsed * 1000))
            self._guided_history.append(accepted)
        else:
            accepted = self._session.submit(event)
        if accepted is None:
            return None
        started = time.perf_counter()
        self._play_note(accepted.note)
        self._diag_play_ms = (time.perf_counter() - started) * 1000.0
        self._show_performance(accepted)
        self._piano.pulse_click(accepted.note)
        self._stage.notify_note(accepted.note)
        if self._mode == "guided":
            self._update_buttons()
        return accepted

    def _show_performance(self, entry: HistoryEntry) -> None:
        self._press_count.setText(f"Pulsaciones: {self._controller().press_count - (self._guided_count_offset if self._mode == 'guided' else 0)}")
        self._last_note.setText(f"Última nota: {entry.note}")
        if entry.finger_id:
            self._last_finger.setText(f"Dedo: {finger_caption(entry.finger_id)}")
        else:
            self._last_finger.setText("Dedo: Teclado")
        self._refresh_history()

    def _refresh_history(self) -> None:
        rows = tuple(
            (
                entry.note,
                "gesto" if entry.origin == ORIGIN_GESTURE else "clic",
                entry.finger_id or "teclado",
            )
            for entry in (tuple(self._guided_history)[-4:] if self._mode == "guided" else self._session.recent(4))
        )
        self._info.history.set_rows(rows)

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

    def start_session(self) -> None:
        if self._controller().phase != PHASE_IDLE:
            return
        self._handle_press_events(self._worker.take_events())
        _image, _fps, _sequence, _hands, gestures, _timing = self._worker.latest()
        self._mark_input_boundary()
        if not self._controller().start(self._held_finger_ids(gestures)):
            return
        if self._mode == "guided":
            self._guided_history.clear()
            self._guided_count_offset = 0
            self._guided_started = time.monotonic()
            self._guided_pause_at = None
            self._guided_paused_span = 0.0
        self._last_note.setText("Última nota: —")
        self._last_finger.setText("Dedo: —")
        self._press_count.setText("Pulsaciones: 0")
        self._refresh_history()
        self._update_buttons()

    def pause_session(self) -> None:
        pending = self._worker.take_events()
        controller = self._controller()
        if not controller.pause():
            self._handle_press_events(pending)
            return
        self._handle_press_events(pending)
        if self._mode == "guided":
            self._guided_pause_at = time.monotonic()
        self._stop_sounds()
        self._update_buttons()

    def resume_session(self) -> None:
        controller = self._controller()
        if controller.phase != PHASE_PAUSED:
            return
        self._handle_press_events(self._worker.take_events())
        _image, _fps, _sequence, _hands, gestures, _timing = self._worker.latest()
        self._mark_input_boundary()
        if not controller.resume(self._held_finger_ids(gestures)):
            return
        if self._mode == "guided" and self._guided_pause_at is not None:
            self._guided_paused_span += time.monotonic() - self._guided_pause_at
            self._guided_pause_at = None
        self._update_buttons()

    def finish_session(self) -> None:
        pending = self._worker.take_events()
        controller = self._controller()
        if not controller.finish():
            self._handle_press_events(pending)
            return
        self._handle_press_events(pending)
        self._stop_sounds()
        self._update_buttons()

    def _mark_input_boundary(self) -> None:
        # También rechaza un fotograma que seguía procesándose al drenar la cola.
        self._event_floor_ms = int(time.monotonic() * 1000) if self._worker.isRunning() else None

    def _controller(self):
        return self._guide if self._mode == "guided" else self._session

    def _select_mode(self, index: int) -> None:
        mode = self._mode_selector.itemData(index)
        if mode == self._mode:
            return
        self._controller().finish()
        # Drenar sin reproducir; conservar deduplicación de eventos ya observados.
        for event in self._worker.take_events():
            self._accept_press(event)
        self._stop_sounds()
        self._highway.clear_transients()
        self._piano.set_gesture_notes(set())
        self._piano.advance(10)
        self._mark_input_boundary()
        self._mode = mode
        if mode == "guided":
            from fingermelody.music.guided import GuidedMode
            self._guide = GuidedMode()
            self._guided_history.clear()
            self._guided_count_offset = 0
        else:
            self._session = SessionController()
        self._stage.set_guided(mode == "guided")
        self._info.mode.setText("Modo guiado" if mode == "guided" else "Modo libre")
        self._last_note.setText("Última nota: —")
        self._last_finger.setText("Dedo: —")
        self._press_count.setText("Pulsaciones: 0")
        self._refresh_history()
        self._update_buttons()

    def _refresh_guided_view(self) -> None:
        guided = self._mode == "guided"
        self._guide_progress.setVisible(guided)
        self._guide_hint.setVisible(guided)
        if guided:
            self._highway.set_snapshot(self._guide.snapshot(), self._mapper)
            self._guide_progress.setText(f"Jingle Bells · {self._guide.index}/{self._guide.total}")
            state = self._guide.step_state()
            pending = "   |   ".join(self._highway.bar_label(n) for n in state.pending_notes) if state else "—"
            self._guide_hint.setText(f"Pendientes: {pending}")
            self._stage.arrange()
        else:
            self._highway.set_chart((), 0)
            self._highway.set_running(False)

    def _sync_highway_lanes(self) -> None:
        if hasattr(self, "_stage"):
            self._stage.sync_lanes()

    def _reset_press_count(self) -> None:
        if self._mode == "guided":
            self._guided_count_offset = self._guide.press_count
        else:
            self._session.reset_counters()
        self._press_count.setText("Pulsaciones: 0")
        self._piano.set_gesture_notes(set())
        self._worker.request_count_reset()

    def _held_finger_ids(self, update: GestureUpdate) -> set[str]:
        if not update.active:
            return set()
        return {
            state.finger_id
            for state in update.states
            if state.phase in {PHASE_PRESSED, PHASE_HELD}
        }

    def _release_open_fingers(self, update: GestureUpdate) -> None:
        controller = self._controller()
        if controller.phase != PHASE_PLAYING or not update.active:
            return
        held = self._held_finger_ids(update)
        for finger_id in tuple(controller.suppressed):
            if finger_id not in held:
                controller.release_finger(finger_id)

    def _session_caption(self) -> tuple[str, str]:
        controller = self._controller()
        phase = controller.phase
        if phase == PHASE_PLAYING:
            return "Activa", PHASE_PLAYING
        if phase == PHASE_PAUSED:
            return "Pausada", PHASE_PAUSED
        if controller.finished:
            return "Finalizada", "finished"
        return "En espera", PHASE_IDLE

    def _refresh_session_controls(self) -> None:
        phase = self._controller().phase
        self._info.start_session.setEnabled(phase == PHASE_IDLE)
        self._info.pause_session.setEnabled(phase == PHASE_PLAYING)
        self._info.resume_session.setEnabled(phase == PHASE_PAUSED)
        self._info.finish_session.setEnabled(phase != PHASE_IDLE)
        self._piano.setEnabled(phase == PHASE_PLAYING)
        caption, marker = self._session_caption()
        changed = False
        for badge in (self._info.session,):
            badge.setText(caption)
            if badge.property("phase") != marker:
                badge.setProperty("phase", marker)
                restyle(badge)
                changed = True
        if changed:
            self._fade_session_badge()

    def _fade_session_badge(self) -> None:
        """Fundido y pulso del badge. Solo corre al cambiar el estado."""
        self._info.session.fade_in()

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
        self._refresh_session_controls()
        self._refresh_guided_view()
