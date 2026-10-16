"""D3: despacho separado, un solo audio y transiciones seguras."""
import pytest
from PySide6.QtCore import QTimer
from fingermelody.interface.main_window import MainWindow
from fingermelody.gestures.gesture_engine import FingerPressEvent
from test_guided_highway import PanelAudio


def select(window, index=1):
    window._mode_selector.setCurrentIndex(index)


def test_selector_transition_preserves_hardware_settings_and_waits(qapp, monkeypatch):
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    window.show()
    qapp.processEvents()
    assert window._mode_selector.isVisible()
    assert window._mode == "free"
    worker, engine, manager = window._worker, window._worker._gesture_engine, window._manager
    monkeypatch.setattr(worker, "start", lambda: pytest.fail("Reinicio de cámara"))
    volumes = []
    monkeypatch.setattr(audio, "set_volume", volumes.append)
    window._volume.setValue(33)
    window._calibration_note = "Calibración guardada"
    window.start_session()
    window._play_clicked_note("C4")
    assert window._highway.effect_count() > 0
    worker.blockSignals(True)
    worker._queue_events((FingerPressEvent("LEFT_THUMB", 99),))
    worker.blockSignals(False)
    select(window)
    assert window._guide.phase == "idle"
    assert worker.take_events() == ()
    assert window._highway.effect_count() == 0
    assert not window._piano.lit_notes()
    assert audio.played == ["C4"]
    assert window._volume.value() == 33
    assert volumes == [0.33]
    assert window._calibration_note == "Calibración guardada"
    assert (window._worker, window._worker._gesture_engine, window._manager) == (worker, engine, manager)
    assert window._audio is audio
    window._play_clicked_note("E5")
    assert audio.played == ["C4"]
    select(window, 0)
    assert window._session.phase == "idle" and not window._session.finished
    assert window._highway._steps == ()
    window.close()
    assert audio.closed == 1
    assert not any(t.isActive() for t in window.findChildren(QTimer))


def test_one_token_per_batch_partial_and_individual_clicks(qapp, monkeypatch):
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    select(window)
    window.start_session()
    tokens = []
    submit = window._guide.submit_result
    def record(*args, **kwargs):
        tokens.append(kwargs["expected_step"])
        return submit(*args, **kwargs)
    monkeypatch.setattr(window._guide, "submit_result", record)
    events = (FingerPressEvent("LEFT_THUMB", 1), FingerPressEvent("RIGHT_PINKY", 1),
              FingerPressEvent("RIGHT_PINKY", 2))
    window._handle_press_events(events)
    assert len(tokens) == 3 and len(set(tokens)) == 1
    assert window._guide.index == 1
    assert audio.played == ["C4", "E5"]
    window._handle_press_events(events)
    assert audio.played == ["C4", "E5"]
    window._play_clicked_note("E5")
    assert window._guide.index == 2
    assert tokens[-1] != tokens[0]
    window._play_clicked_note("G4")
    assert window._guide.index == 2
    assert window._guide.step_state().pending_notes == ("E5",)
    assert list(window._highway._bars())[:2] == [(2, "E5", False), (2, "G4", True)]
    window._play_clicked_note("G4")
    assert audio.played == ["C4", "E5", "E5", "G4"]
    window.pause_session()
    pos = window._highway._scroll
    window._highway.advance_visual(20)
    assert window._highway._scroll == pos
    window._play_clicked_note("E5")
    assert len(audio.played) == 4
    window.resume_session()
    assert window._highway._scroll == pos
    window._play_clicked_note("E5")
    assert window._guide.index == 3
    assert len(audio.played) == 5
    assert len(window._guided_history) == 5
    assert window._guide_progress.text() == "Jingle Bells · 3/49"
    window.close()


def test_all_steps_finish_exactly_once_and_restart(qapp):
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    select(window)
    window.start_session()
    for step in window._guide.steps:
        for note in reversed(step.notes):
            window._play_clicked_note(note)
    assert window._guide.completed and window._guide.index == 49
    assert len(audio.played) == 77
    assert window._guide_progress.text() == "Jingle Bells · 49/49"
    assert not window._piano.isEnabled()
    assert window._highway.bar_identities() == ()
    window.start_session()
    assert window._guide.index == 0 and not window._guided_history
    window.close()


@pytest.mark.parametrize("size", [(960, 640), (1920, 1080)])
def test_guided_camera_band_and_lane_alignment(qapp, size):
    window = MainWindow(audio_engine=PanelAudio())
    window.resize(*size)
    window.show()
    select(window)
    qapp.processEvents()
    camera = window._camera_panel.geometry()
    if window._highway.y():
        assert camera.bottom() < window._highway.y()
    else:
        for note, rect in window._piano.white_rects():
            if note in window._highway.preview_notes():
                assert camera.right() < rect.left() or camera.left() > rect.right()
    assert window._highway.y() + window._highway.activation_y() == window._piano.y()
    for note, rect in window._piano.white_rects():
        assert window._highway.lane_center(note) == pytest.approx(rect.center().x(), abs=.5)
    window.close()


def test_held_finger_and_late_event_boundary(qapp, monkeypatch):
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    select(window)
    monkeypatch.setattr(window, "_held_finger_ids", lambda update: {"RIGHT_PINKY"})
    window.start_session()
    window._handle_press_events((FingerPressEvent("RIGHT_PINKY", 1),))
    assert audio.played == []
    window._guide.release_finger("RIGHT_PINKY")
    window._event_floor_ms = 100
    window._handle_press_events((FingerPressEvent("RIGHT_PINKY", 99),))
    assert audio.played == []
    window._handle_press_events((FingerPressEvent("RIGHT_PINKY", 101),))
    assert audio.played == ["E5"]
    window.close()
