"""Jingle Bells: el progreso lo decide la nota correcta, y la carretera solo lo dibuja."""

import pytest
from PySide6.QtWidgets import QLabel

from fingermelody.gestures.gesture_engine import FingerPressEvent
from fingermelody.interface.note_highway import NoteHighway
from fingermelody.interface.preview_window import PreviewWindow
from fingermelody.music.guided import GuidedMode, SongNote, jingle_bells


class PanelAudio:
    def __init__(self) -> None:
        self.played: list[str] = []
        self.stopped = 0
        self.closed = 0
        self.available = True
        self.status_message = "Audio disponible"

    def initialize(self) -> bool:
        return True

    def set_volume(self, _value: float) -> None:
        return None

    def play_note(self, name: str) -> bool:
        self.played.append(name)
        return True

    def stop_all(self) -> None:
        self.stopped += 1

    def shutdown(self) -> None:
        self.closed += 1


def _highway() -> NoteHighway:
    road = NoteHighway()
    road.resize(640, 220)
    road.set_lanes((("C4", 80.0, 36.0), ("E4", 180.0, 36.0), ("G4", 280.0, 36.0)))
    return road


def test_bars_follow_the_piano_lanes_and_wait_on_the_line(qapp):
    road = _highway()
    road.set_chart((("E4", 1.0), ("C4", 1.0)), 0)
    road.set_running(True)
    rect = road.bar_rect(0)

    assert rect is not None
    assert rect.center().x() == pytest.approx(road.lane_center("E4"))
    assert road.bar_bottom(0) < road.activation_y() - 20

    road.set_lanes((("C4", 140.0, 28.0), ("E4", 260.0, 28.0), ("G4", 360.0, 28.0)))
    moved = road.bar_rect(0)
    assert moved is not None
    assert moved.center().x() == pytest.approx(260.0)
    assert moved.width() < rect.width()

    road.advance_visual(2.0)
    parked = road.bar_bottom(0)
    assert road.waiting()
    assert parked == pytest.approx(road.activation_y(), abs=0.5)
    road.advance_visual(1.5)
    assert road.bar_bottom(0) == pytest.approx(parked, abs=0.5)
    assert road.current_note() == "E4"


def test_hit_spawns_particles_that_then_disappear(qapp):
    road = _highway()
    road.set_chart((("E4", 1.0), ("G4", 1.0)), 0)
    road.set_running(True)
    road.advance_visual(2.0)
    road.notify_hit("E4")

    assert 6 <= road.particle_count() <= 12
    assert road.effect_count() > road.particle_count()
    road.advance_visual(0.7)
    assert road.particle_count() == 0
    assert road.effect_count() == 0


def test_pause_freezes_the_descent(qapp):
    road = _highway()
    road.set_chart((("E4", 1.0),), 0)
    road.set_running(True)
    road.advance_visual(0.2)
    moving = road.bar_bottom(0)
    road.set_running(False)
    road.advance_visual(1.0)
    assert road.bar_bottom(0) == pytest.approx(moving, abs=0.5)
    assert road.waiting() is False


def test_guided_song_advances_only_on_the_expected_note():
    song = (SongNote("E4", 1), SongNote("E4", 1), SongNote("G4", 2))
    guide = GuidedMode(song)
    assert guide.current_note() == "E4"
    assert guide.upcoming_note() == "E4"
    assert jingle_bells()[0].note == "E4"

    assert guide.submit("E4") is None
    assert guide.start() is True
    assert guide.submit("C4") is None
    assert guide.index == 0
    assert guide.submit("E4", "LEFT_THUMB") is not None
    assert guide.index == 1
    guide.pause()
    assert guide.submit("E4") is None
    assert guide.index == 1
    guide.resume(("LEFT_MIDDLE",))
    assert guide.submit("E4", "LEFT_MIDDLE") is None
    guide.release_finger("LEFT_MIDDLE")
    hit = guide.submit("E4", "LEFT_MIDDLE")
    assert hit is not None
    assert hit.progress == 2
    assert guide.current_note() == "G4"
    assert guide.submit("G4") is not None
    assert guide.completed is True
    assert guide.phase == "idle"
    assert guide.submit("C4") is None


def test_guided_window_plays_once_and_free_mode_still_works(qapp):
    audio = PanelAudio()
    window = PreviewWindow(audio_engine=audio)
    window.resize(1100, 760)
    window.show()
    qapp.processEvents()
    window.select_guided_mode()
    qapp.processEvents()

    assert window.findChild(QLabel, "guideTitleLabel").text() == "Jingle Bells"
    assert window._highway.isVisible()
    assert window._highway.lane_center("E4") == pytest.approx(_mapped_center(window, "E4"), abs=1.5)
    wide = window._highway.lane_center("C4")
    window.resize(1400, 820)
    qapp.processEvents()
    window._sync_highway_lanes()
    assert window._highway.lane_center("C4") != pytest.approx(wide)
    assert window._highway.lane_center("C4") == pytest.approx(_mapped_center(window, "C4"), abs=1.5)

    window.start_session()
    window._piano.play_key("C4")
    assert audio.played == []
    assert window._guide.index == 0
    window._handle_press_events((FingerPressEvent("LEFT_MIDDLE", 9),))
    window._handle_press_events((FingerPressEvent("LEFT_MIDDLE", 9),))
    assert audio.played == ["E4"]
    assert window._guide.index == 1
    assert window._highway.particle_count() >= 6
    assert window.findChild(QLabel, "guideProgressLabel").text().startswith("1 /")

    window.pause_session()
    window._piano.play_key("E4")
    assert audio.played == ["E4"]
    assert audio.stopped == 1
    window.resume_session()
    window.select_free_mode()
    window.start_session()
    window._piano.play_key("C4")
    assert audio.played[-1] == "C4"
    assert window.findChild(QLabel, "modeLabel").text() == "Modo libre"
    window.close()
    qapp.processEvents()
    window.deleteLater()
    qapp.processEvents()


def _mapped_center(window, note: str) -> float:
    rect = next(item for name, item in window._piano.white_rects() if name == note)
    center = window._piano.mapToGlobal(rect.center().toPoint())
    return float(window._highway.mapFromGlobal(center).x())
