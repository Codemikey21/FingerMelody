"""D2: acordes visuales sin integración pública ni audio automático."""
import pytest
from fingermelody.interface.main_window import MainWindow
from fingermelody.music.guided import GuidedMode
from fingermelody.music.note_mapper import NoteMapper
from test_guided_highway import PanelAudio


def test_chord_alignment_wait_partial_pause_resize_and_silence(qapp):
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    window.show()
    qapp.processEvents()
    road = window._highway
    guide = GuidedMode()
    guide.start()
    road.set_snapshot(guide.snapshot(), NoteMapper())
    assert len(road.bar_identities()) == 77
    assert road.bar_identities()[:2] == (("jb-01", "E5"), ("jb-01", "C4"))
    assert road.bar_label("E5") == "E5 · Derecha · Meñique"
    assert road.bar_label("C4") == "C4 · Izquierda · Pulgar"
    for size in ((960, 640), (1400, 850)):
        window.resize(*size)
        qapp.processEvents()
        for note in ("E5", "C4"):
            key = dict(window._piano.white_rects())[note]
            bar = road.bar_rect(0, note)
            assert bar.center().x() == pytest.approx(key.center().x(), abs=.5)
            assert bar.width() <= key.width()
        assert road.bar_rect(0, "E5").bottom() == road.bar_rect(0, "C4").bottom()
        assert road.bar_rect(0, "E5").height() == road.bar_rect(0, "C4").height()
    road.advance_visual(.1)
    guide.pause()
    road.set_snapshot(guide.snapshot())
    before = road.bar_rect(0, "E5")
    road.advance_visual(40)
    assert road.bar_rect(0, "E5") == before
    guide.resume()
    road.set_snapshot(guide.snapshot())
    assert road.bar_rect(0, "E5") == before
    road.advance_visual(100)
    for note in ("E5", "C4"):
        assert road.bar_rect(0, note).bottom() == road.activation_y()
    before = road.bar_rect(0, "E5")
    road.advance_visual(1000)
    assert road.bar_rect(0, "E5") == before
    assert guide.index == 0
    guide.submit("E5")
    road.set_snapshot(guide.snapshot())
    assert list(road._bars())[:2] == [(0, "E5", True), (0, "C4", False)]
    assert road.bar_rect(0, "E5") == before
    road.grab()  # Ejecuta el pintado de la marca y de ambas etiquetas.
    guide.submit("C4")
    road.set_snapshot(guide.snapshot())
    assert ("jb-01", "E5") not in road.bar_identities()
    assert ("jb-02", "E5") in road.bar_identities()
    assert road.bar_rect(1, "E5").bottom() < road.activation_y()
    assert audio.played == []
    window.close()


def test_restart_and_legacy_clear_snapshot(qapp):
    window = MainWindow(audio_engine=PanelAudio())
    road = window._highway
    guide = GuidedMode()
    guide.start()
    road.set_snapshot(guide.snapshot())
    road.advance_visual(100)
    guide.finish()
    road.set_snapshot(guide.snapshot())
    guide.start()
    road.set_snapshot(guide.snapshot())
    assert road._scroll < 0
    road.set_chart((), 0)
    assert road.bar_identities() == ()
    assert road._snapshot is None
    window.close()
