"""Escala temperada y asociación de dedos, sin audio."""

from pathlib import Path

import pytest

from fingermelody.gestures.finger_detector import FINGER_SPECS, finger_id
from fingermelody.music.note_mapper import DEFAULT_FINGER_NOTES, NoteMapper
from fingermelody.music.notes import A4_HZ, SCALE, equal_tempered_frequency

_PUBLISHED = {
    "C4": 261.63,
    "D4": 293.66,
    "E4": 329.63,
    "F4": 349.23,
    "G4": 392.00,
    "A4": 440.00,
    "B4": 493.88,
    "C5": 523.25,
    "D5": 587.33,
    "E5": 659.25,
}


def test_scale_has_the_ten_notes_at_equal_temperament():
    assert [note.name for note in SCALE] == list(_PUBLISHED)
    for note in SCALE:
        expected = equal_tempered_frequency(note.semitones_from_a4)
        assert note.frequency == pytest.approx(expected)
        assert note.frequency == pytest.approx(A4_HZ * 2.0 ** (note.semitones_from_a4 / 12.0))
        assert note.frequency == pytest.approx(_PUBLISHED[note.name], abs=0.015)


def test_default_fingers_map_to_the_prepared_notes():
    mapper = NoteMapper()
    finger_ids = [finger_id(hand, spec) for hand in ("Left", "Right") for spec in FINGER_SPECS]

    assert [finger for finger, _note in mapper.assignments()] == finger_ids
    assert dict(mapper.assignments()) == dict(DEFAULT_FINGER_NOTES)
    assert mapper.note("LEFT_THUMB").name == "C4"
    assert mapper.note("RIGHT_PINKY").frequency == pytest.approx(SCALE[-1].frequency)
    assert mapper.note_name("LEFT_KNEE") is None


def test_mapping_can_change_without_touching_playback():
    mapper = NoteMapper((("LEFT_INDEX", "A4"),))

    assert mapper.note_name("LEFT_INDEX") == "A4"
    assert mapper.note_name("LEFT_THUMB") is None


def test_unknown_note_in_the_mapping_is_rejected():
    with pytest.raises(ValueError, match="desconocida"):
        NoteMapper((("LEFT_THUMB", "C9"),))


def test_music_modules_do_not_depend_on_the_interface_or_the_audio_device():
    root = Path(__file__).parents[1] / "src" / "fingermelody"
    for relative in ("music/notes.py", "music/note_mapper.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "PySide6" not in source
        assert "pygame" not in source
        assert "mediapipe" not in source
