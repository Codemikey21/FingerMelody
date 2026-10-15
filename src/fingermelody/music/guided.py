"""Modo guiado. El progreso cambia solo cuando la nota tocada es la esperada.

No mide el ritmo, no reproduce audio y no dibuja la carretera de notas.
"""

from __future__ import annotations

from dataclasses import dataclass

from fingermelody.music.notes import NOTES_BY_NAME
from fingermelody.music.session import PHASE_IDLE, PHASE_PAUSED, PHASE_PLAYING

# Coro tradicional, reducido a las diez notas de la aplicación.
# El valor es la duración relativa: 1 negra, 2 blanca. No hay tempo que evaluar.
_JINGLE_BELLS: tuple[tuple[str, float], ...] = (
    ("E4", 1), ("E4", 1), ("E4", 2),
    ("E4", 1), ("E4", 1), ("E4", 2),
    ("E4", 1), ("G4", 1), ("C4", 1), ("D4", 1), ("E4", 2),
    ("F4", 1), ("F4", 1), ("F4", 1), ("F4", 1),
    ("F4", 1), ("E4", 1), ("E4", 1), ("E4", 1),
    ("E4", 1), ("D4", 1), ("D4", 1), ("E4", 1),
    ("D4", 2), ("G4", 2),
    ("E4", 1), ("E4", 1), ("E4", 2),
    ("E4", 1), ("E4", 1), ("E4", 2),
    ("E4", 1), ("G4", 1), ("C4", 1), ("D4", 1), ("E4", 2),
    ("F4", 1), ("F4", 1), ("F4", 1), ("F4", 1),
    ("F4", 1), ("E4", 1), ("E4", 1), ("E4", 1),
    ("G4", 1), ("G4", 1), ("F4", 1), ("D4", 1), ("C4", 2),
)


@dataclass(frozen=True)
class SongNote:
    """Una figura de la canción. La duración solo alimenta el largo de la barra."""

    note: str
    beats: float


@dataclass(frozen=True)
class GuideHit:
    """Acerto ya aplicado. El índice es el de la nota que acaba de completarse."""

    note: str
    index: int
    progress: int
    total: int


def jingle_bells() -> tuple[SongNote, ...]:
    """Melodía de Jingle Bells dentro de C4–E5."""
    return tuple(SongNote(note, beats) for note, beats in _JINGLE_BELLS)


class GuidedMode:
    """Fuente de verdad del modo guiado. La animación no puede avanzar la canción."""

    def __init__(self, song: tuple[SongNote, ...] | None = None, title: str = "Jingle Bells") -> None:
        steps = jingle_bells() if song is None else tuple(song)
        if not steps:
            raise ValueError("La canción no tiene notas.")
        for step in steps:
            if step.note not in NOTES_BY_NAME or step.beats <= 0:
                raise ValueError("La canción tiene una nota o una duración no válida.")
        self.title = title
        self._song = steps
        self._phase = PHASE_IDLE
        self._index = 0
        self._finished = False
        self._completed = False
        self._count = 0
        self._suppressed: set[str] = set()

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def completed(self) -> bool:
        return self._completed

    @property
    def index(self) -> int:
        return self._index

    @property
    def total(self) -> int:
        return len(self._song)

    @property
    def press_count(self) -> int:
        return self._count

    @property
    def suppressed(self) -> frozenset[str]:
        return frozenset(self._suppressed)

    def chart(self) -> tuple[tuple[str, float], ...]:
        return tuple((step.note, step.beats) for step in self._song)

    def current_note(self) -> str | None:
        if self._index >= len(self._song):
            return None
        return self._song[self._index].note

    def upcoming_note(self) -> str | None:
        following = self._index + 1
        if following >= len(self._song):
            return None
        return self._song[following].note

    def start(self, held_finger_ids=()) -> bool:
        if self._phase != PHASE_IDLE:
            return False
        self._phase = PHASE_PLAYING
        self._finished = False
        self._completed = False
        self._index = 0
        self._count = 0
        self._suppressed = {finger_id for finger_id in held_finger_ids if finger_id}
        return True

    def pause(self) -> bool:
        if self._phase != PHASE_PLAYING:
            return False
        self._phase = PHASE_PAUSED
        return True

    def resume(self, held_finger_ids=()) -> bool:
        if self._phase != PHASE_PAUSED:
            return False
        self._phase = PHASE_PLAYING
        self._suppressed = {finger_id for finger_id in held_finger_ids if finger_id}
        return True

    def finish(self) -> bool:
        if self._phase == PHASE_IDLE:
            return False
        self._phase = PHASE_IDLE
        self._finished = True
        self._suppressed.clear()
        return True

    def release_finger(self, finger_id: str) -> None:
        self._suppressed.discard(finger_id)

    def submit(self, note: str, finger_id: str | None = None) -> GuideHit | None:
        """Avanza solo si la nota es la que espera la canción."""
        if self._phase != PHASE_PLAYING or self._index >= len(self._song):
            return None
        if finger_id and finger_id in self._suppressed:
            return None
        if note != self._song[self._index].note:
            return None
        done = self._index
        self._index += 1
        self._count += 1
        if self._index >= len(self._song):
            self._completed = True
            self._phase = PHASE_IDLE
            self._finished = True
            self._suppressed.clear()
        return GuideHit(note, done, self._index, len(self._song))
