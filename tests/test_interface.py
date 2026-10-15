"""Ventana, piano y controles sin cámara ni altavoces."""

import pytest
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton

from fingermelody.gestures.gesture_engine import FingerGestureState, FingerPressEvent, GestureUpdate
from fingermelody.interface.piano_widget import WHITE_NOTES, PianoWidget
from fingermelody.interface.camera_worker import FrameTiming
from fingermelody.interface.preview_window import PreviewWindow
from fingermelody.interface.settings_dialog import SettingsDialog
from fingermelody.music.note_mapper import NoteMapper
from fingermelody.vision.hand_tracker import HandViewState


class PanelAudio:
    def __init__(self):
        self.played = []
        self.volume = None
        self.stopped = 0
        self.closed = 0
        self.available = True
        self.status_message = "Audio disponible"

    def initialize(self):
        return True

    def set_volume(self, value):
        self.volume = value

    def play_note(self, name):
        self.played.append(name)
        return True

    def stop_all(self):
        self.stopped += 1

    def shutdown(self):
        self.closed += 1


def _lit_thumb(note_event=False):
    state = FingerGestureState(
        finger_id="LEFT_THUMB",
        hand="Left",
        name="thumb",
        display_name="Pulgar",
        phase="HELD",
        visual="Pulsación",
        press_count=1,
        highlight=True,
        tip_pixel=(12, 18),
    )
    events = (FingerPressEvent("LEFT_THUMB", 40),) if note_event else ()
    return GestureUpdate(active=True, states=(state,), events=events)


def test_piano_uses_the_chromatic_layout(qapp):
    piano = PianoWidget()
    piano.resize(1000, 170)
    whites = piano.white_rects()
    blacks = piano.black_rects()
    gap = QPointF(
        (whites[2][1].right() + whites[3][1].left()) / 2,
        whites[2][1].top() + 6,
    )

    assert [name for name, _rect in whites] == list(WHITE_NOTES)
    assert len(blacks) == 7
    assert piano.note_at(whites[0][1].center()) == "C4"
    assert piano.note_at(whites[-1][1].center()) == "E5"
    assert piano.note_at(blacks[0].center()) is None
    assert piano.note_at(gap) is None
    assert all(not black.contains(gap) for black in blacks)


def test_click_plays_once_and_gesture_light_does_not_play_again(qapp):
    audio = PanelAudio()
    window = PreviewWindow(audio_engine=audio)
    window.show()
    window.resize(1180, 760)
    qapp.processEvents()
    note = window._piano.white_rects()[0][1].center().toPoint()

    window.select_free_mode()
    window.start_session()
    QTest.mouseClick(window._piano, Qt.MouseButton.LeftButton, pos=note)
    window._apply_gestures(_lit_thumb())
    window._handle_press_events(_lit_thumb(note_event=True).events)
    window._apply_gestures(_lit_thumb(note_event=True))
    window._handle_press_events(_lit_thumb(note_event=True).events)

    assert audio.played == ["C4", "C4"]
    assert "C4" in window._piano.lit_notes()
    assert window.findChild(QLabel, "lastNoteLabel").text() == "Última nota: C4"
    assert "LEFT_THUMB" in window.findChild(QLabel, "lastFingerLabel").text()
    assert window.findChild(QLabel, "pressCountLabel").text() == "Pulsaciones: 2"
    window.close()


def test_volume_mute_and_press_reset(qapp):
    audio = PanelAudio()
    window = PreviewWindow(audio_engine=audio)
    window.select_free_mode()
    window._volume.setValue(40)
    window.findChild(QPushButton, "muteButton").click()
    window._volume.setValue(55)
    muted = audio.volume
    window.findChild(QPushButton, "muteButton").click()
    window.start_session()
    window._handle_press_events((FingerPressEvent("RIGHT_PINKY", 3),))
    window.findChild(QPushButton, "resetPressButton").click()
    window._handle_press_events((FingerPressEvent("RIGHT_PINKY", 3),))

    assert muted == 0
    assert audio.volume == pytest.approx(0.55)
    assert audio.played == ["E5"]
    assert window.findChild(QLabel, "pressCountLabel").text() == "Pulsaciones: 0"
    assert window.findChild(QLabel, "audioStatus").text() == "Audio disponible"
    assert window._worker._reset_counts is True
    window.close()


def test_resize_keeps_the_camera_aspect(qapp):
    audio = PanelAudio()
    window = PreviewWindow(audio_engine=audio)
    image = QImage(640, 480, QImage.Format.Format_RGB888)
    image.fill(QColor("#112233"))
    window.show()
    window.resize(1000, 700)
    qapp.processEvents()
    window._worker._publish(image, 24.0, HandViewState(), GestureUpdate.inactive(), FrameTiming())
    window._show_latest_frame()
    window.resize(1280, 860)
    qapp.processEvents()

    pixmap = window._preview.pixmap()
    assert pixmap is not None
    assert pixmap.width() <= window._preview.width() + 1
    assert pixmap.height() <= window._preview.height() + 1
    assert pixmap.width() / pixmap.height() == pytest.approx(4 / 3, rel=0.04)
    assert window._piano.width() > 500
    assert window.findChild(QLabel, "fpsLabel").text() == "FPS: 24.0"
    assert window.findChild(QLabel, "infoFpsLabel").text() == "FPS: 24.0"
    window.close()
    assert audio.closed == 1


def test_settings_lists_the_finger_mapping(qapp):
    dialog = SettingsDialog(NoteMapper(), "Audio disponible", "Dispositivo 0 · 640×480")
    text = dialog.findChild(QLabel, "assignmentLabel").text()

    assert "C4" in text
    assert "E5" in text
    assert "LEFT_THUMB" in text
    assert dialog.findChild(QLabel, "settingsAudio").text() == "Audio disponible"

    audio = PanelAudio()
    window = PreviewWindow(audio_engine=audio)
    window.show()

    def close_dialog():
        active = qapp.activeModalWidget()
        assert active is not None
        assert "D4" in active.findChild(QLabel, "assignmentLabel").text()
        active.accept()

    QTimer.singleShot(0, close_dialog)
    window.findChild(QPushButton, "settingsButton").click()
    window.close()
