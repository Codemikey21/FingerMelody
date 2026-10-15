"""Arreglo aprobado y progresión bilateral con reloj controlado."""

from collections import Counter
from itertools import permutations

import pytest

from fingermelody.music.guided import COORDINATION, LEARNING, GuidedMode, SongNote, SongStep, jingle_bells
from fingermelody.music.note_mapper import NoteMapper


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def chord_song():
    return (SongStep("one", ("E5", "C4"), 1), SongStep("two", ("E5",), 2))


def test_approved_arrangement_every_phrase_and_duration():
    # Lista de revisión musical independiente del generador.
    phrases = (
        "E5+C4 E5 E5+G4:2",
        "E5+C4 E5 E5+G4:2",
        "E4+C5 G4 C4+E5 D4 E4+C5:2",
        "F4+A4 F4 F4+C5 F4",
        "F4+A4 E4+C5 E4 E4",
        "E4+C5 D4 D4+B4 E4 D4:2 G4+D5:2",
        "E5+C4 E5 E5+G4:2",
        "E5+C4 E5 E5+G4:2",
        "E4+C5 G4 C4+E5 D4 E4+C5:2",
        "F4+A4 F4 F4+C5 F4",
        "F4+A4 E4+C5 E4 E4",
        "G4+B4 G4 F4+A4 D4 C4+E5:2",
    )
    expected = []
    for phrase in phrases:
        for token in phrase.split():
            notes, _, duration = token.partition(":")
            expected.append((tuple(notes.split("+")), int(duration or 1)))
    song = jingle_bells()
    assert [(s.notes, s.beats) for s in song] == expected
    assert len(song) == len({s.id for s in song}) == 49
    assert sum(s.beats for s in song) == 58
    assert Counter(len(s.notes) for s in song) == {1: 21, 2: 28}
    mapping = dict(NoteMapper().assignments())
    assert tuple(mapping.values()) == ("C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5")
    inverse = {note: finger for finger, note in mapping.items()}
    hands = Counter(inverse[n].split("_")[0] for s in song for n in s.notes)
    assert hands == {"LEFT": 45, "RIGHT": 32}
    assert {n for s in song for n in s.notes} == set(inverse)
    assert all({inverse[n].split("_")[0] for n in s.notes} == {"LEFT", "RIGHT"}
               for s in song if len(s.notes) == 2)


@pytest.mark.parametrize("order", list(permutations(("E5", "C4"))))
def test_learning_accepts_either_order_once_without_time_limit(order):
    clock = Clock()
    guide = GuidedMode(chord_song(), clock=clock)
    assert guide.coordination_mode == LEARNING
    guide.start()
    hit = guide.submit(order[0])
    assert hit.note == order[0] and not hit.step_complete and hit.progress == 0
    assert guide.step_state().progress == 0.5
    assert dict(guide.step_state().note_states)[order[0]]
    assert guide.submit(order[0]) is None
    assert guide.submit("D4") is None
    clock.now = 100000
    assert guide.submit(order[0]) is None
    hit = guide.submit(order[1])
    assert hit.step_complete and hit.progress == 1
    assert guide.step_state(0).completed
    assert guide.press_count == 2
    assert guide.submit("E5").step_complete
    assert guide.completed and guide.index == 2
    assert guide.submit("E5") is None


@pytest.mark.parametrize("window_ms", [100, 450, 900])
def test_coordination_boundary_and_expired_attempt(window_ms):
    clock = Clock()
    guide = GuidedMode(chord_song(), coordination_mode=COORDINATION, window_ms=window_ms, clock=clock)
    guide.start()
    guide.submit("E5")
    clock.now = window_ms / 1000
    assert guide.submit("C4").step_complete
    guide.finish()
    clock.now = 0
    guide.start()
    guide.submit("E5")
    clock.now = window_ms / 1000 + 0.001
    hit = guide.submit("C4")
    assert not hit.step_complete
    assert hit.accepted_notes == {"C4"}
    assert guide.submit("C4") is None
    assert guide.submit("E5").step_complete
    assert guide.press_count == 3  # Tres notas reales aceptadas en dos intentos.


@pytest.mark.parametrize("mode", [LEARNING, COORDINATION])
def test_pause_held_fingers_restart_and_stale_batches(mode):
    guide = GuidedMode(chord_song(), coordination_mode=mode)
    guide.start()
    token = guide.batch_token
    guide.submit("E5")
    guide.pause()
    assert guide.submit("C4") is None
    assert guide.step_state().accepted_notes == ({"E5"} if mode == LEARNING else set())
    guide.resume(("LEFT_THUMB",))
    assert guide.submit("C4", "LEFT_THUMB") is None
    guide.release_finger("LEFT_THUMB")
    assert guide.submit("C4", "LEFT_THUMB", expected_step=token) is None
    assert guide.submit("C4", "LEFT_THUMB") is not None
    if mode == COORDINATION:
        guide.submit("E5")
    assert guide.index == 1
    guide.finish()
    guide.start()
    assert guide.index == guide.press_count == 0
    assert all(not guide.step_state(i).accepted_notes for i in range(guide.total))
    assert guide.submit("E5", expected_step=token) is None


def test_batch_cannot_spill_into_repeated_next_note():
    guide = GuidedMode(chord_song())
    guide.start()
    token = guide.batch_token
    assert guide.submit("C4", expected_step=token)
    assert guide.submit("E5", expected_step=token).step_complete
    assert guide.submit("E5", expected_step=token) is None
    assert guide.index == 1
    assert guide.submit("E5", expected_step=guide.batch_token).step_complete


def test_legacy_song_and_chart_still_supported():
    guide = GuidedMode((SongNote("C4", 1), SongNote("C4", 2)))
    assert guide.chart() == (("C4", 1), ("C4", 2))
    guide.start()
    assert guide.submit("C4").progress == 1
    assert guide.submit("C4").progress == 2
    assert guide.completed


def test_complete_isolated_arrangement_emits_exactly_77_acceptances():
    guide = GuidedMode()
    guide.start()
    accepted = []
    for index, step in enumerate(guide.steps):
        for note in reversed(step.notes):
            hit = guide.submit(note)
            assert hit is not None
            accepted.append(hit.note)
        assert guide.index == index + 1
    assert guide.completed
    assert len(accepted) == guide.press_count == 77
    assert guide.submit("E5") is None


@pytest.mark.parametrize("notes,beats", [((), 1), (("C4", "C4"), 1), (("F5",), 1), (("C4",), 0), (("C4",), float("nan"))])
def test_invalid_steps_are_rejected(notes, beats):
    with pytest.raises(ValueError):
        SongStep("invalid", notes, beats)


@pytest.mark.parametrize("kwargs", [{"window_ms": 0}, {"window_ms": float("inf")}, {"coordination_mode": "unknown"}])
def test_invalid_coordination_configuration(kwargs):
    with pytest.raises(ValueError):
        GuidedMode(**kwargs)
