"""Progresión musical independiente de Qt, cámara y audio.

Aprendizaje conserva los aciertos parciales hasta completar el paso, incluso
al pausar. Coordinación reinicia el intento parcial al pausar o cuando llega
una nota válida después del plazo: esa nota inicia el siguiente intento.
Los sonidos ya emitidos no se deshacen; nunca se reproduce un acorde al cerrar
el paso. El consumidor reproduce solamente la nota de cada GuideHit.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from fingermelody.music.notes import NOTES_BY_NAME
from fingermelody.music.session import PHASE_IDLE, PHASE_PAUSED, PHASE_PLAYING

LEARNING = "learning"
COORDINATION = "coordination"


@dataclass(frozen=True)
class SongNote:
    """Entrada histórica de una sola nota, conservada por compatibilidad."""
    note: str
    beats: float


@dataclass(frozen=True)
class SongStep:
    """Definición inmutable. La primera nota es la melodía principal."""
    id: str
    notes: tuple[str, ...]
    beats: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "notes", tuple(self.notes))
        if not self.id or not self.notes or len(set(self.notes)) != len(self.notes):
            raise ValueError("El paso requiere identificador y notas distintas.")
        if any(note not in NOTES_BY_NAME for note in self.notes):
            raise ValueError("El paso contiene una nota no disponible.")
        if not math.isfinite(self.beats) or self.beats <= 0:
            raise ValueError("La duración debe ser positiva y finita.")

    @property
    def note(self) -> str:
        """Nota principal para consumidores antiguos de una sola barra."""
        return self.notes[0]


@dataclass(frozen=True)
class StepState:
    """Instantánea inmutable de un paso y su aceptación individual."""
    step: SongStep
    accepted_notes: frozenset[str]

    @property
    def pending_notes(self) -> tuple[str, ...]:
        return tuple(note for note in self.step.notes if note not in self.accepted_notes)

    @property
    def note_states(self) -> tuple[tuple[str, bool], ...]:
        return tuple((note, note in self.accepted_notes) for note in self.step.notes)

    @property
    def progress(self) -> float:
        return len(self.accepted_notes) / len(self.step.notes)

    @property
    def completed(self) -> bool:
        return not self.pending_notes


@dataclass(frozen=True)
class GuideHit:
    """Una nota recién aceptada, no una orden de reproducir todo el paso."""
    note: str
    index: int
    progress: int
    total: int
    step_id: str
    accepted_notes: frozenset[str]
    step_complete: bool


def jingle_bells() -> tuple[SongStep, ...]:
    """Arreglo B aprobado: 49 pasos, 28 díadas, 45 notas izquierdas y 32 derechas.

    Las frases 1, 2, 7 y 8 llevan E5 con C4/G4 de apoyo. El resto
    conserva la melodía original y los acompañamientos derechos aprobados.
    No se alteran las duraciones relativas (58 pulsos en total).
    """
    high = (("E5", 1), ("E5", 1), ("E5", 2))
    third = (("E4", 1), ("G4", 1), ("C4", 1), ("D4", 1), ("E4", 2))
    fourth = (("F4", 1),) * 4
    fifth = (("F4", 1), ("E4", 1), ("E4", 1), ("E4", 1))
    sixth = (("E4", 1), ("D4", 1), ("D4", 1), ("E4", 1), ("D4", 2), ("G4", 2))
    ending = (("G4", 1), ("G4", 1), ("F4", 1), ("D4", 1), ("C4", 2))
    # Posiciones de acompañamiento numeradas desde 1 dentro de cada frase.
    phrases = (
        (high, {1: "C4", 3: "G4"}),
        (high, {1: "C4", 3: "G4"}),
        (third, {1: "C5", 3: "E5", 5: "C5"}),
        (fourth, {1: "A4", 3: "C5"}),
        (fifth, {1: "A4", 2: "C5"}),
        (sixth, {1: "C5", 3: "B4", 6: "D5"}),
        (high, {1: "C4", 3: "G4"}),
        (high, {1: "C4", 3: "G4"}),
        (third, {1: "C5", 3: "E5", 5: "C5"}),
        (fourth, {1: "A4", 3: "C5"}),
        (fifth, {1: "A4", 2: "C5"}),
        (ending, {1: "B4", 3: "A4", 5: "E5"}),
    )
    result = []
    for melody, accompaniment in phrases:
        for position, (note, beats) in enumerate(melody, 1):
            notes = (note, accompaniment[position]) if position in accompaniment else (note,)
            result.append(SongStep(f"jb-{len(result) + 1:02d}", notes, beats))
    return tuple(result)


class GuidedMode:
    """Única autoridad del progreso. No reproduce audio ni consulta widgets."""

    def __init__(
        self,
        song: tuple[SongNote | SongStep, ...] | None = None,
        title: str = "Jingle Bells",
        *,
        coordination_mode: str = LEARNING,
        window_ms: float = 450,
        clock: Callable[[], float] | None = None,
    ) -> None:
        source = jingle_bells() if song is None else tuple(song)
        if not source:
            raise ValueError("La canción no tiene notas.")
        self._song = tuple(
            step if isinstance(step, SongStep) else SongStep(f"step-{i + 1}", (step.note,), step.beats)
            for i, step in enumerate(source)
        )
        if len({step.id for step in self._song}) != len(self._song):
            raise ValueError("Los identificadores de paso deben ser únicos.")
        if coordination_mode not in (LEARNING, COORDINATION):
            raise ValueError("Modalidad de coordinación desconocida.")
        if not math.isfinite(window_ms) or window_ms <= 0:
            raise ValueError("La ventana temporal debe ser positiva y finita.")
        self.title = title
        self.coordination_mode = coordination_mode
        self.window_ms = window_ms
        self._clock = clock or time.monotonic
        self._phase = PHASE_IDLE
        self._index = 0
        self._finished = False
        self._completed = False
        self._count = 0
        self._suppressed: set[str] = set()
        self._accepted = [set() for _ in self._song]
        self._attempt_started: float | None = None
        self._epoch = 0

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

    @property
    def steps(self) -> tuple[SongStep, ...]:
        return self._song

    @property
    def batch_token(self) -> tuple[int, int]:
        """Capturar una vez por lote y pasar a submit para impedir desbordes."""
        return self._epoch, self._index

    def step_state(self, index: int | None = None) -> StepState | None:
        position = self._index if index is None else index
        if position < 0 or position >= len(self._song):
            return None
        return StepState(self._song[position], frozenset(self._accepted[position]))

    def chart(self) -> tuple[tuple[str, float], ...]:
        """Proyección histórica de melodía; la vista multibarra corresponde a D."""
        return tuple((step.note, step.beats) for step in self._song)

    def current_note(self) -> str | None:
        state = self.step_state()
        return state.step.note if state else None

    def upcoming_note(self) -> str | None:
        state = self.step_state(self._index + 1)
        return state.step.note if state else None

    def start(self, held_finger_ids=()) -> bool:
        if self._phase != PHASE_IDLE:
            return False
        self._phase = PHASE_PLAYING
        self._finished = False
        self._completed = False
        self._index = 0
        self._count = 0
        self._accepted = [set() for _ in self._song]
        self._attempt_started = None
        self._epoch += 1
        self._suppressed = {finger_id for finger_id in held_finger_ids if finger_id}
        return True

    def _cancel_partial(self) -> None:
        if self._index < len(self._song):
            self._accepted[self._index].clear()
        self._attempt_started = None

    def pause(self) -> bool:
        if self._phase != PHASE_PLAYING:
            return False
        self._phase = PHASE_PAUSED
        self._epoch += 1
        if self.coordination_mode == COORDINATION:
            self._cancel_partial()
        return True

    def resume(self, held_finger_ids=()) -> bool:
        if self._phase != PHASE_PAUSED:
            return False
        self._phase = PHASE_PLAYING
        self._epoch += 1
        self._suppressed = {finger_id for finger_id in held_finger_ids if finger_id}
        return True

    def finish(self) -> bool:
        if self._phase == PHASE_IDLE:
            return False
        self._phase = PHASE_IDLE
        self._finished = True
        self._epoch += 1
        self._cancel_partial()
        self._suppressed.clear()
        return True

    def release_finger(self, finger_id: str) -> None:
        self._suppressed.discard(finger_id)

    def submit(
        self, note: str, finger_id: str | None = None,
        *, expected_step: tuple[int, int] | None = None,
    ) -> GuideHit | None:
        if self._phase != PHASE_PLAYING or self._index >= len(self._song):
            return None
        if expected_step is not None and expected_step != self.batch_token:
            return None
        if finger_id and finger_id in self._suppressed:
            return None
        step = self._song[self._index]
        if note not in step.notes:
            return None
        now = self._clock()
        if (self.coordination_mode == COORDINATION and self._attempt_started is not None
                and now - self._attempt_started > self.window_ms / 1000.0):
            self._cancel_partial()
        accepted = self._accepted[self._index]
        if note in accepted:
            return None
        if not accepted:
            self._attempt_started = now
        accepted.add(note)
        self._count += 1
        done = self._index
        step_complete = len(accepted) == len(step.notes)
        if step_complete:
            self._index += 1
            self._attempt_started = None
            if self._index >= len(self._song):
                self._completed = True
                self._phase = PHASE_IDLE
                self._finished = True
                self._suppressed.clear()
        return GuideHit(note, done, self._index, len(self._song), step.id,
                        frozenset(accepted), step_complete)
