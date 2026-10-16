"""La experiencia pública acepta notas libres y no carga canciones."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel

from fingermelody.gestures.gesture_engine import FingerPressEvent
from fingermelody.interface.main_window import MainWindow
from fingermelody.music.note_mapper import NoteMapper
from fingermelody.music.session import PHASE_IDLE
from test_guided_highway import PanelAudio


def test_startup_is_silent_free_and_keeps_empty_neon_scene(qapp, monkeypatch):
    import fingermelody.music.guided as guided
    def forbidden(*args, **kwargs):
        raise AssertionError("La ventana no debe cargar GuidedMode")
    monkeypatch.setattr(guided, "GuidedMode", forbidden)
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    window.show()
    qapp.processEvents()
    assert window._session.phase == PHASE_IDLE
    assert not hasattr(window, "_guide")
    assert not hasattr(window, "select_guided_mode")
    assert all("Jingle Bells" not in label.text() for label in window.findChildren(QLabel))
    for name in ("guideTitleLabel", "guideProgressLabel", "guideNextLabel"):
        assert window.findChild(QLabel, name) is None
    assert window._highway.isVisible()
    assert window._stage.isVisible() and window._piano.isVisible()
    assert window._camera_panel.isVisible()
    assert window._highway._steps == ()
    window._piano.play_key("C4")
    window._highway.advance_visual(10)
    assert audio.played == []
    assert window._highway.effect_count() == 0
    window.close()
    assert audio.closed == 1
    assert not any(t.isActive() for t in window.findChildren(QTimer))


def test_ten_fingers_in_one_batch_are_independent_and_deduplicated(qapp):
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    worker = window._worker
    engine = worker._gesture_engine
    window.start_session()
    assignments = NoteMapper().assignments()
    events = tuple(FingerPressEvent(finger, 100) for finger, note in assignments)
    window._handle_press_events(events)
    expected = [note for finger, note in assignments]
    assert audio.played == expected
    assert window._session.press_count == 10
    assert [entry.note for entry in window._session.history] == expected
    assert window._piano.lit_notes() == set(expected)
    window._handle_press_events(events)
    assert audio.played == expected
    window.pause_session()
    window._handle_press_events(tuple(FingerPressEvent(finger, 101) for finger, note in assignments))
    assert audio.played == expected
    window.resume_session()
    window._handle_press_events(tuple(FingerPressEvent(finger, 102) for finger, note in assignments))
    assert audio.played == expected * 2
    assert worker is window._worker and engine is worker._gesture_engine
    assert window._highway._steps == ()
    assert len(window._highway._impacts) == 10
    window._reset_press_count()
    assert window._session.press_count == 0
    assert len(window._session.history) == 20
    window.finish_session()
    window._piano.play_key("E5")
    assert audio.played == expected * 2
    window.close()


def test_all_ten_click_notes_are_accepted_without_sequence(qapp):
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    window.start_session()
    notes = tuple(reversed(window._piano.note_names))
    for note in notes:
        window._piano.play_key(note)
    assert audio.played == list(notes)
    assert all(entry.origin == "click" and entry.finger_id is None
               for entry in window._session.history)
    assert window._session.press_count == 10
    window.close()
