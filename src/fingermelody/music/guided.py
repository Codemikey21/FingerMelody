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
from enum import Enum

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
class VisualNoteState:
    step_id: str
    note: str
    accepted: bool

    @property
    def identity(self) -> tuple[str, str]:
        return self.step_id, self.note


@dataclass(frozen=True)
class StepState:
    """Instantánea inmutable de un paso y su aceptación individual."""
    step: SongStep
    accepted_notes: frozenset[str]
    index: int = 0
    total: int = 1
    phase: str = PHASE_IDLE

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted_notes", frozenset(self.accepted_notes))

    @property
    def step_id(self) -> str:
        return self.step.id

    @property
    def required_notes(self) -> tuple[str, ...]:
        return self.step.notes

    @property
    def relative_duration(self) -> float:
        return self.step.beats

    @property
    def position(self) -> int:
        """Posición humana desde 1; index se cuenta desde 0."""
        return self.index + 1

    @property
    def paused(self) -> bool:
        return self.phase == PHASE_PAUSED

    @property
    def visual_notes(self) -> tuple[VisualNoteState, ...]:
        return tuple(VisualNoteState(self.step.id, note, note in self.accepted_notes)
                     for note in self.step.notes)

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


@dataclass(frozen=True)
class GuidedSnapshot:
    steps: tuple[StepState, ...]
    index: int
    phase: str
    finished: bool
    completed: bool
    batch_token: tuple[int, int]

    @property
    def total(self) -> int:
        return len(self.steps)

    @property
    def current(self) -> StepState | None:
        return self.steps[self.index] if self.index < self.total else None

    @property
    def paused(self) -> bool:
        return self.phase == PHASE_PAUSED

    @property
    def progress(self) -> float:
        """Fracción de pasos completos; el parcial vive en StepState.progress."""
        return self.index / self.total


class SubmissionReason(str, Enum):
    ACCEPTED = "accepted"
    ALREADY_ACCEPTED = "already_accepted"
    NOTE_NOT_REQUIRED = "note_not_required"
    SESSION_PAUSED = "session_paused"
    FINGER_PENDING_RELEASE = "finger_pending_release"
    STALE_BATCH = "stale_batch"
    STEP_COMPLETED = "step_completed"
    SESSION_INACTIVE = "session_inactive"
    SONG_COMPLETED = "song_completed"


@dataclass(frozen=True)
class SubmissionResult:
    reason: SubmissionReason
    hit: GuideHit | None
    state: StepState | None

    @property
    def accepted(self) -> bool:
        return self.hit is not None


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
        return StepState(self._song[position], frozenset(self._accepted[position]),
                         position, self.total, self.phase)

    def snapshot(self) -> GuidedSnapshot:
        """Consulta sin reloj, audio ni cambios de estado; incluye todos los acordes."""
        states = tuple(StepState(step, frozenset(self._accepted[i]), i, self.total,
                                 self.phase) for i, step in enumerate(self._song))
        return GuidedSnapshot(states, self.index, self.phase, self.finished,
                              self.completed, self.batch_token)

    def chart(self) -> tuple[tuple[str, float], ...]:
        """Proyección histórica monofónica; usar snapshot para acordes completos."""
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
        """API histórica: cada llamada procesa un único evento."""
        return self.submit_result(note, finger_id, expected_step=expected_step).hit

    def submit_result(
        self, note: str, finger_id: str | None = None,
        *, expected_step: tuple[int, int] | None = None,
    ) -> SubmissionResult:
        """Procesa una vez y diagnostica; nunca reproduce ni diagnostica audio."""
        def reject(reason: SubmissionReason) -> SubmissionResult:
            return SubmissionResult(reason, None, self.step_state())

        if self._phase == PHASE_PAUSED:
            return reject(SubmissionReason.SESSION_PAUSED)
        if self._phase != PHASE_PLAYING or self._index >= len(self._song):
            return reject(SubmissionReason.SONG_COMPLETED if self.completed
                          else SubmissionReason.SESSION_INACTIVE)
        if expected_step is not None and expected_step != self.batch_token:
            return reject(SubmissionReason.STALE_BATCH)
        if finger_id and finger_id in self._suppressed:
            return reject(SubmissionReason.FINGER_PENDING_RELEASE)
        step = self._song[self._index]
        if note not in step.notes:
            return reject(SubmissionReason.NOTE_NOT_REQUIRED)
        now = self._clock()
        if (self.coordination_mode == COORDINATION and self._attempt_started is not None
                and now - self._attempt_started > self.window_ms / 1000.0):
            self._cancel_partial()
        accepted = self._accepted[self._index]
        if note in accepted:
            return reject(SubmissionReason.ALREADY_ACCEPTED)
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
        hit = GuideHit(note, done, self._index, len(self._song), step.id,
                       frozenset(accepted), step_complete)
        return SubmissionResult(SubmissionReason.STEP_COMPLETED if step_complete
                                else SubmissionReason.ACCEPTED, hit, self.step_state(done))
