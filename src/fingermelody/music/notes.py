"""Notas de la escala temperada. No genera audio ni conoce dedos."""

from __future__ import annotations

from dataclasses import dataclass

A4_HZ = 440.0
_SEMITONES = {
    "C4": -9,
    "D4": -7,
    "E4": -5,
    "F4": -4,
    "G4": -2,
    "A4": 0,
    "B4": 2,
    "C5": 3,
    "D5": 5,
    "E5": 7,
}


@dataclass(frozen=True)
class Note:
    """Una nota con su frecuencia calculada desde A4 = 440 Hz."""

    name: str
    semitones_from_a4: int

    @property
    def frequency(self) -> float:
        return A4_HZ * 2.0 ** (self.semitones_from_a4 / 12.0)


def equal_tempered_frequency(semitones_from_a4: int) -> float:
    """Frecuencia temperada. El semitono 0 es A4."""
    return A4_HZ * 2.0 ** (semitones_from_a4 / 12.0)


SCALE: tuple[Note, ...] = tuple(
    Note(name, semitones) for name, semitones in _SEMITONES.items()
)
NOTES_BY_NAME: dict[str, Note] = {note.name: note for note in SCALE}
