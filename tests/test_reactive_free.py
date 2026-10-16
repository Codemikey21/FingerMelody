"""Efectos libres independientes del audio y con presupuesto por nota."""

from collections import Counter

from fingermelody.interface.main_window import MainWindow
from test_guided_highway import PanelAudio


def test_polyphony_retrigger_pause_and_decay(qapp):
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    window.show()
    qapp.processEvents()
    window.start_session()
    road = window._highway
    notes = window._piano.note_names
    for note in notes:
        window._piano.play_key(note)
    assert audio.played == list(notes)
    assert {hit.note for hit in road._impacts} == set(notes)
    counts = Counter(p.note for p in road._particles)
    assert set(counts) == set(notes)
    assert all(6 <= amount <= 12 for amount in counts.values())
    others = [hit for hit in road._impacts if hit.note != "C4"]
    for _ in range(20):
        window._piano.play_key("C4")
    assert len(road._impacts) == 10
    assert all(any(hit is other for hit in road._impacts) for other in others)
    assert road.particle_count() <= 120
    before = len(audio.played)
    road.advance_visual(0.1)
    window.resize(1400, 850)
    qapp.processEvents()
    for note, rect in window._piano.white_rects():
        assert abs(road.lane_center(note) - rect.center().x()) <= 0.5
    window.pause_session()
    for note in notes:
        window._piano.play_key(note)
    assert len(audio.played) == before
    road.advance_visual(1)
    assert road.effect_count() == 0
    assert window._piano._impact_lights == {}
    assert not road._timer.isActive()
    assert road._steps == ()
    assert len(audio.played) == before
    window.close()
    assert audio.closed == 1


def test_invalid_or_idle_input_does_not_animate(qapp):
    audio = PanelAudio()
    window = MainWindow(audio_engine=audio)
    window._piano.play_key("E5")
    window._stage.notify_note("F9")
    assert window._highway.effect_count() == 0
    window.start_session()
    window._piano.play_key("F9")
    assert audio.played == []
    assert window._highway.effect_count() == 0
    window._piano.play_key("E5")
    assert audio.played == ["E5"]
    assert window._highway._impacts[0].note == "E5"
    assert window._piano._impact_lights["E5"] > 0
    window.close()
