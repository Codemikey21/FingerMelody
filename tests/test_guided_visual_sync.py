"""D4: aceptación temprana, jerarquía visual y cámara adaptable."""
import pytest
from fingermelody.interface.main_window import MainWindow
from test_guided_highway import PanelAudio


def test_early_partial_hit_updates_bar_once_and_arrival_never_impacts(qapp):
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    window.show()
    window._mode_selector.setCurrentIndex(1)
    window.start_session()
    qapp.processEvents()
    road = window._highway
    assert road.bar_rect(0, "E5").bottom() < road.activation_y()
    assert road.bar_opacity(0, False) > road.bar_opacity(1, False)
    assert road.bar_opacity(0, False) > road.bar_opacity(0, True)
    window._play_clicked_note("E5")
    assert audio.played == ["E5"]
    assert window._guide.index == 0
    assert list(road._bars())[:2] == [(0, "E5", True), (0, "C4", False)]
    assert road._impacts[0].note == "E5"
    assert road.particle_count() > 0
    assert road._ghosts and road._flashes
    assert "E5" in window._piano.lit_notes()
    assert window._guide_hint.text() == "Pendientes: C4 · Izquierda · Pulgar"
    window._play_clicked_note("E5")
    window._play_clicked_note("D4")
    assert audio.played == ["E5"]
    road.advance_visual(20)
    assert road._impacts == [] and road.particle_count() == 0
    assert road.waiting() and window._guide.index == 0
    assert road.bar_rect(0, "E5").bottom() == road.bar_rect(0, "C4").bottom()
    window.pause_session()
    before = road._scroll
    road.advance_visual(10)
    window.resume_session()
    assert road._scroll == before
    assert window._guide.step_state().pending_notes == ("C4",)
    window._play_clicked_note("C4")
    assert window._guide.index == 1 and audio.played == ["E5", "C4"]
    assert road._impacts[0].note == "C4"
    window._mode_selector.setCurrentIndex(0)
    assert not window._guide_hint.isVisible()
    assert road._steps == () and road.effect_count() == 0
    window.close()


@pytest.mark.parametrize("size", [(960,640), (1180,760), (1920,1080)])
def test_camera_avoids_all_preview_lanes_through_whole_song(qapp, size):
    window = MainWindow(audio_engine=PanelAudio())
    window.resize(*size)
    window.show()
    window._mode_selector.setCurrentIndex(1)
    window.start_session()
    qapp.processEvents()
    road = window._highway
    initial_top = road.y()
    for step in window._guide.steps:
        camera = window._camera_panel.geometry()
        assert camera.bottom() < window._piano.y()
        assert road.y() + road.activation_y() == window._piano.y()
        for note, rect in window._piano.white_rects():
            assert road.lane_center(note) == pytest.approx(rect.center().x(), abs=.5)
            if note in road.preview_notes():
                assert camera.bottom() < road.y() or camera.right() < rect.left() or camera.left() > rect.right()
        for note in step.notes:
            window._play_clicked_note(note)
    if size[0] == 1920:
        assert initial_top == 0
    else:
        assert initial_top <= 180
    window.close()
