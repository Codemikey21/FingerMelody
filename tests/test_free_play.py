"""Modo libre: sesión, pausa, historial y ausencia de notas fantasma."""

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QPushButton

from fingermelody.gestures.gesture_engine import FingerGestureState, FingerPressEvent, GestureUpdate
from fingermelody.interface.camera_worker import FrameTiming
from fingermelody.interface.history_strip import NoteHistoryStrip
from fingermelody.interface.piano_widget import PianoWidget
from fingermelody.interface.preview_window import PreviewWindow
from fingermelody.music.session import (
    FREE_PLAY,
    GUIDED_PLAY,
    ORIGIN_CLICK,
    ORIGIN_GESTURE,
    PHASE_IDLE,
    PHASE_PAUSED,
    PHASE_PLAYING,
    MusicalEvent,
    SessionController,
    available_modes,
)
from fingermelody.vision.hand_tracker import HandViewState


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def session() -> tuple[SessionController, Clock]:
    clock = Clock()
    return SessionController(clock), clock


def test_only_free_play_is_available_and_other_modes_are_rejected():
    modes = available_modes()

    assert [item.code for item in modes] == [FREE_PLAY]
    assert modes[0].title == "Modo libre"
    with pytest.raises(ValueError):
        SessionController(mode="guided")


def test_session_start_pause_resume_and_finish_control_notes():
    motor, clock = session()
    gesture = MusicalEvent("C4", ORIGIN_GESTURE, "LEFT_THUMB")
    click = MusicalEvent("E4", ORIGIN_CLICK)

    assert motor.phase == PHASE_IDLE
    assert motor.submit(gesture) is None
    assert motor.start() is True
    assert motor.phase == PHASE_PLAYING
    assert motor.start() is False

    clock.now = 1.25
    first = motor.submit(gesture)
    assert first is not None
    assert first.elapsed_ms == 1250
    assert first.origin == ORIGIN_GESTURE
    assert first.finger_id == "LEFT_THUMB"
    assert motor.press_count == 1

    assert motor.pause() is True
    assert motor.phase == PHASE_PAUSED
    clock.now = 4.0
    assert motor.submit(gesture) is None
    assert motor.submit(click) is None
    assert motor.press_count == 1

    clock.now = 4.2
    assert motor.resume(["LEFT_THUMB"]) is True
    assert motor.phase == PHASE_PLAYING
    assert motor.submit(gesture) is None
    motor.release_finger("LEFT_THUMB")
    clock.now = 4.5
    again = motor.submit(gesture)
    assert again is not None
    assert again.elapsed_ms == 1550

    clock.now = 4.8
    clicked = motor.submit(click)
    assert clicked is not None
    assert clicked.origin == ORIGIN_CLICK
    assert clicked.finger_id is None
    assert {entry.note for entry in motor.history} == {"C4", "E4"}

    assert motor.finish() is True
    assert motor.phase == PHASE_IDLE
    assert motor.finished is True
    assert motor.submit(click) is None
    assert motor.finish() is False
    assert motor.pause() is False
    assert motor.resume() is False

    assert motor.start(["RIGHT_THUMB"]) is True
    assert motor.submit(MusicalEvent("A4", ORIGIN_GESTURE, "RIGHT_THUMB")) is None
    motor.release_finger("RIGHT_THUMB")
    assert motor.submit(MusicalEvent("A4", ORIGIN_GESTURE, "RIGHT_THUMB")) is not None


def test_pause_time_is_excluded_and_a_new_session_clears_history():
    motor, clock = session()
    motor.start()
    clock.now = 0.4
    motor.submit(MusicalEvent("D4", ORIGIN_CLICK))
    motor.pause()
    clock.now = 3.4
    motor.resume()
    clock.now = 3.6
    second = motor.submit(MusicalEvent("F4", ORIGIN_GESTURE, "LEFT_RING"))

    assert second is not None
    assert second.elapsed_ms == 600
    motor.reset_counters()
    assert motor.press_count == 0
    assert len(motor.history) == 2

    motor.finish()
    motor.start()
    assert motor.history == ()
    assert motor.press_count == 0
    assert motor.finished is False


def test_simultaneous_notes_keep_their_own_origin():
    motor, clock = session()
    motor.start()
    clock.now = 0.2
    left = motor.submit(MusicalEvent("C4", ORIGIN_GESTURE, "LEFT_THUMB"))
    right = motor.submit(MusicalEvent("A4", ORIGIN_GESTURE, "RIGHT_THUMB"))

    assert left is not None and right is not None
    assert [entry.finger_id for entry in motor.history] == ["LEFT_THUMB", "RIGHT_THUMB"]
    assert motor.press_count == 2
    assert motor.recent(1) == (right,)


class PanelAudio:
    def __init__(self) -> None:
        self.played: list[str] = []
        self.stopped = 0
        self.closed = 0
        self.available = True
        self.status_message = "Audio disponible"

    def initialize(self) -> bool:
        return True

    def set_volume(self, value: float) -> None:
        return None

    def play_note(self, name: str) -> bool:
        self.played.append(name)
        return True

    def stop_all(self) -> None:
        self.stopped += 1

    def shutdown(self) -> None:
        self.closed += 1


def _state(phase: str, highlight: bool) -> FingerGestureState:
    return FingerGestureState(
        "LEFT_THUMB",
        "Left",
        "thumb",
        "Pulgar",
        phase,
        "Flexionado" if phase == "HELD" else "Reposo",
        1,
        highlight,
        (12, 18),
    )


def _publish(window: PreviewWindow, state: FingerGestureState) -> None:
    image = QImage(4, 4, QImage.Format.Format_RGB888)
    window._worker._publish(
        image,
        None,
        HandViewState(),
        GestureUpdate(active=True, states=(state,)),
        FrameTiming(),
    )


def test_free_play_window_blocks_pause_and_skips_a_held_finger_on_resume(qapp):
    audio = PanelAudio()
    window = PreviewWindow(audio_engine=audio)
    buttons = {name: window.findChild(QPushButton, name) for name in (
        "startSessionButton",
        "pauseSessionButton",
        "resumeSessionButton",
        "finishSessionButton",
    )}

    assert window.findChild(QLabel, "modeLabel").text() == "Modo libre"
    assert window.findChild(QPushButton, "freeModeButton") is None
    assert window.findChild(QPushButton, "guidedButton") is None
    assert window._highway.isHidden() is False
    assert buttons["startSessionButton"].isEnabled()
    assert not buttons["pauseSessionButton"].isEnabled()
    window._piano.play_key("C4")
    assert audio.played == []

    buttons["startSessionButton"].click()
    assert window.findChild(QLabel, "sessionStatusLabel").text() == "Activa"
    assert window.findChild(QLabel, "sessionStatusLabel").property("phase") == "playing"
    window._handle_press_events((
        FingerPressEvent("LEFT_THUMB", 1),
        FingerPressEvent("RIGHT_THUMB", 1),
    ))
    window._handle_press_events((FingerPressEvent("LEFT_THUMB", 1),))
    window._piano.play_key("E4")

    assert audio.played == ["C4", "A4", "E4"]
    history = window._info.history.caption()
    assert "C4 · gesto · LEFT_THUMB" in history
    assert "A4 · gesto · RIGHT_THUMB" in history
    assert "E4 · clic · teclado" in history
    assert window.findChild(QLabel, "pressCountLabel").text() == "Pulsaciones: 3"
    assert window.findChild(QLabel, "lastNoteLabel").text() == "Última nota: E4"

    buttons["pauseSessionButton"].click()
    assert window.findChild(QLabel, "sessionStatusLabel").text() == "Pausada"
    assert audio.stopped == 1
    window._piano.play_key("D4")
    window._handle_press_events((FingerPressEvent("LEFT_INDEX", 4),))
    assert audio.played == ["C4", "A4", "E4"]
    window._apply_gestures(GestureUpdate(active=True, states=(_state("HELD", True),)))
    assert "C4" in window._piano.lit_notes()

    _publish(window, _state("HELD", True))
    buttons["resumeSessionButton"].click()
    window._handle_press_events((FingerPressEvent("LEFT_THUMB", 8),))
    assert audio.played == ["C4", "A4", "E4"]

    ready = GestureUpdate(active=True, states=(_state("READY", False),))
    window._apply_gestures(ready)
    window._handle_press_events((FingerPressEvent("LEFT_THUMB", 9),))
    assert audio.played[-1] == "C4"

    buttons["finishSessionButton"].click()
    assert window.findChild(QLabel, "sessionStatusLabel").text() == "Finalizada"
    window._piano.play_key("G4")
    assert "G4" not in audio.played
    assert buttons["startSessionButton"].isEnabled()
    window.close()


def test_session_controls_keep_the_existing_calibration(qapp):
    from tests.test_gesture_engine import finger

    audio = PanelAudio()
    window = PreviewWindow(audio_engine=audio)
    engine = window._worker._gesture_engine
    rest = [finger("Left", "index", 180)]
    flexed = [finger("Left", "index", 70)]
    assert engine.capture_reference(rest, "rest") == 1
    assert engine.capture_reference(flexed, "flex") == 1

    window.start_session()
    window.pause_session()
    window.resume_session()
    window.finish_session()
    window.findChild(QPushButton, "resetPressButton").click()

    assert "LEFT_INDEX" in engine._rest
    assert "LEFT_INDEX" in engine._flex
    armed = engine.update(rest, 0)
    engine.update(rest, 40)
    engine.update(flexed, 80)
    pressed = engine.update(flexed, 120)
    assert armed.events == ()
    assert pressed.events
    assert pressed.events[0].finger_id == "LEFT_INDEX"
    window.close()


def test_key_pulse_fades_back_and_a_held_gesture_stays_lit(qapp):
    piano = PianoWidget()
    piano.resize(900, 170)
    piano.pulse_click("C4")

    assert piano.level("C4") == pytest.approx(1.0)
    assert piano.glow("C4") == pytest.approx(1.0)
    assert "C4" in piano.lit_notes()

    piano.advance(0.16)
    assert piano.level("C4") == pytest.approx(1.0)
    piano.advance(0.12)
    assert 0.45 < piano.level("C4") < 0.95
    assert piano.glow("C4") < piano.level("C4")
    piano.advance(0.7)
    assert piano.level("C4") == 0.0
    assert piano.glow("C4") == 0.0
    assert "C4" not in piano.lit_notes()

    piano.set_gesture_notes({"E4"})
    assert piano.level("E4") == pytest.approx(1.0)
    piano.advance(0.4)
    assert piano.level("E4") == pytest.approx(1.0)
    piano.set_gesture_notes(set())
    piano.advance(0.12)
    assert 0.45 < piano.level("E4") < 0.95
    piano.advance(0.7)
    assert "E4" not in piano.lit_notes()


def test_history_capsules_fade_in_without_rebuilding_rows(qapp):
    strip = NoteHistoryStrip()
    strip.resize(320, 70)
    row = ("C4", "gesto", "LEFT_THUMB")
    strip.set_rows((row, ("E4", "clic", "teclado")))

    assert strip.opacity_of(row) == 0.0
    assert "C4 · gesto · LEFT_THUMB" in strip.caption()
    assert "E4 · clic · teclado" in strip.caption()
    strip.advance(0.2)
    assert strip.opacity_of(row) == pytest.approx(1.0)
    strip.set_rows(())
    assert strip.caption() == "Historial: —"
