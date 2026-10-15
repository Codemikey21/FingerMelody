"""Asociación configurable entre un dedo y una nota.

No reproduce sonido y no importa el motor de audio.
"""

from __future__ import annotations

from fingermelody.music.notes import NOTES_BY_NAME, Note

# Orden de la escala. La reproducción no depende de estos identificadores.
DEFAULT_FINGER_NOTES: tuple[tuple[str, str], ...] = (
    ("LEFT_THUMB", "C4"),
    ("LEFT_INDEX", "D4"),
    ("LEFT_MIDDLE", "E4"),
    ("LEFT_RING", "F4"),
    ("LEFT_PINKY", "G4"),
    ("RIGHT_THUMB", "A4"),
    ("RIGHT_INDEX", "B4"),
    ("RIGHT_MIDDLE", "C5"),
    ("RIGHT_RING", "D5"),
    ("RIGHT_PINKY", "E5"),
)


class NoteMapper:
    """Traduce un identificador de dedo a una nota de la escala."""

    def __init__(self, assignments: tuple[tuple[str, str], ...] | None = None) -> None:
        pairs = DEFAULT_FINGER_NOTES if assignments is None else assignments
        mapping: dict[str, str] = {}
        for finger_id, note_name in pairs:
            if note_name not in NOTES_BY_NAME:
                raise ValueError(f"Nota desconocida en la asociación: {note_name}")
            if finger_id in mapping:
                raise ValueError(f"El dedo {finger_id} está repetido.")
            mapping[finger_id] = note_name
        self._mapping = mapping

    def note_name(self, finger_id: str) -> str | None:
        """Nombre de la nota, o None si ese dedo no está asociado."""
        return self._mapping.get(finger_id)

    def note(self, finger_id: str) -> Note | None:
        name = self.note_name(finger_id)
        if name is None:
            return None
        return NOTES_BY_NAME[name]

    def assignments(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._mapping.items())
