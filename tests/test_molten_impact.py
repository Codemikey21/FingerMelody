"""Los impactos son visuales, acotados y se extinguen sin avanzar la canción."""

from fingermelody.interface.note_highway import NoteHighway
from fingermelody.interface.piano_widget import PianoWidget


def test_arrival_waits_without_impact_audio_or_key_press(qapp):
    road = NoteHighway()
    piano = PianoWidget()
    road.impact_light_changed.connect(piano.set_impact_lights)
    emitted = []
    piano.note_pressed.connect(emitted.append)
    road.set_lanes((("E4", 120, 60),))
    road.set_chart((("E4", 1), ("E4", 1)), 0)
    road.set_running(True)
    road.advance_visual(2)
    assert road._impacts == []
    assert piano._impact_lights == {}
    assert road._index == 0
    assert emitted == []
    assert piano.lit_notes() == set()
    road.advance_visual(0.7)
    assert road._impacts == []
    assert piano._impact_lights == {}
    road.advance_visual(0.1)
    assert road._impacts == []
    road.set_chart(road._steps, 1)
    road.advance_visual(1)
    assert road._impacts == []
    road.shutdown()


def test_hit_replaces_same_lane_effect_and_shutdown_clears_reflection(qapp):
    road = NoteHighway()
    piano = PianoWidget()
    road.impact_light_changed.connect(piano.set_impact_lights)
    road.set_lanes((("E4", 120, 60),))
    road.set_chart((("E4", 1),), 0)
    for _ in range(30):
        road.notify_hit("E4")
    assert len(road._impacts) == 1
    assert road.particle_count() <= 36
    road.set_lanes((("E4", 260, 90),))
    assert road._impacts[0].note == "E4"
    assert road.lane_center("E4") == 260
    road.set_running(False)
    road.advance_visual(0.7)
    assert road.effect_count() == 0
    assert not road._timer.isActive()
    road.notify_hit("E4")
    road.shutdown()
    assert piano._impact_lights == {}
    assert not road._timer.isActive()
