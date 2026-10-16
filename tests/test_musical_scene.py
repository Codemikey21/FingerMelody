"""Geometría compartida y acceso al teclado de la escena musical."""

import pytest
from PySide6.QtCore import QPoint, QRectF
from PySide6.QtWidgets import QApplication

from fingermelody.interface.main_window import MainWindow
from test_guided_highway import PanelAudio


@pytest.mark.parametrize("size", [(960, 640), (1180, 760), (1920, 1080)])
def test_scene_joins_every_lane_to_the_keyboard(qapp, size):
    window = MainWindow(audio_engine=PanelAudio())
    window.resize(*size)
    window.show()
    qapp.processEvents()
    scene = window._stage
    piano = window._piano
    highway = window._highway

    assert piano.width() == highway.width() == scene.width()
    assert piano.x() == highway.x() == 0
    assert piano.geometry().bottom() == scene.rect().bottom()
    for note, rect in piano.white_rects():
        top = piano.mapTo(scene, rect.topLeft().toPoint()).y()
        assert top == pytest.approx(highway.y() + highway.activation_y())
        assert highway.lane_center(note) == pytest.approx(rect.center().x(), abs=0.5)
    assert piano.white_rects()[0][1].left() == 0
    assert piano.white_rects()[-1][1].right() == pytest.approx(scene.width())
    assert window._info.history.parentWidget() is window.centralWidget()
    assert window._info.start_session.parentWidget() is window.centralWidget()
    window.close()


def test_camera_leaves_every_expected_lane_clear_after_resize(qapp):
    window = MainWindow(audio_engine=PanelAudio())
    window.show()
    for size in ((960, 640), (1400, 820)):
        window.resize(*size)
        qapp.processEvents()
        for note in window._piano.note_names:
            window._highway.set_chart(((note, 1.0),), 0)
            window._stage.sync_lanes()
            rect = next(rect for name, rect in window._piano.white_rects() if name == note)
            lane = QRectF(rect.x(), 0, rect.width(), window._piano.y())
            camera = window._camera_panel.geometry()
            assert camera.right() == window._stage.width() - 13
            assert window._stage.rect().contains(camera)
            assert camera.bottom() < window._piano.y()
    window.close()


def test_overlap_preserves_mouse_access_and_hit_effects(qapp):
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    window.show()
    qapp.processEvents()
    rect = next(rect for note, rect in window._piano.white_rects() if note == "E4")
    point = QPoint(round(rect.center().x()), 8)
    assert QApplication.widgetAt(window._piano.mapToGlobal(point)) is window._piano
    window.start_session()
    window._highway.advance_visual(2)
    window._piano.play_key("E4")
    assert audio.played == ["E4"]
    assert window._highway.effect_count() > 0
    assert window._piano.glow("E4") > 0
    window.close()
