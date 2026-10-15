"""Sesión del modo libre. Recibe eventos musicales y no ve la cámara ni el audio.

El modo guiado vive en ``guided.py``. Esta sesión solo interpreta en libertad.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from fingermelody.music.notes import NOTES_BY_NAME

PHASE_IDLE = "idle"
PHASE_PLAYING = "playing"
PHASE_PAUSED = "paused"

ORIGIN_GESTURE = "gesture"
ORIGIN_CLICK = "click"

FREE_PLAY = "free"
_HISTORY_LIMIT = 48


@dataclass(frozen=True)
class PlayMode:
    """Un modo que la interfaz puede ofrecer porque ya tiene comportamiento."""

    code: str
    title: str


@dataclass(frozen=True)
class MusicalEvent:
    """Una nota que alguien quiere interpretar. No incluye imagen ni audio."""

    note: str
    origin: str
    finger_id: str | None = None


@dataclass(frozen=True)
class HistoryEntry:
    """Una nota aceptada en la sesión, con el tiempo desde el inicio útil."""

    note: str
    finger_id: str | None
    origin: str
    elapsed_ms: int


GUIDED_PLAY = "guided"


def available_modes() -> tuple[PlayMode, ...]:
    """Modos con comportamiento real. El guiado no usa SessionController."""
    return (
        PlayMode(FREE_PLAY, "Modo libre"),
    )


class SessionController:
    """Interpretación libre: inicia, pausa, reanuda y guarda un historial corto.

    El reloj es monotónico. El tiempo en pausa no entra en el historial.
    Un dedo marcado al reanudar no vuelve a contar hasta ``release_finger``.
    """

    def __init__(
        self,
        clock: Callable[[], float] | None = None,
        mode: str = FREE_PLAY,
    ) -> None:
        if mode != FREE_PLAY:
            raise ValueError("La sesión libre solo admite el modo libre.")
        self.mode = mode
        self._clock = clock or time.monotonic
        self._phase = PHASE_IDLE
        self._finished = False
        self._started_at: float | None = None
        self._pause_mark: float | None = None
        self._paused_span = 0.0
        self._count = 0
        self._history: deque[HistoryEntry] = deque(maxlen=_HISTORY_LIMIT)
        self._suppressed: set[str] = set()

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def press_count(self) -> int:
        return self._count

    @property
    def suppressed(self) -> frozenset[str]:
        return frozenset(self._suppressed)

    @property
    def history(self) -> tuple[HistoryEntry, ...]:
        return tuple(self._history)

    def recent(self, limit: int = 4) -> tuple[HistoryEntry, ...]:
        if limit < 1:
            return ()
        return tuple(self._history)[-limit:]

    def start(self, held_finger_ids: Iterable[str] = ()) -> bool:
        """Abre una sesión nueva. No reanuda una pausa.

        Los dedos que ya están flexionados no suenan hasta que se abren.
        """
        if self._phase != PHASE_IDLE:
            return False
        self._phase = PHASE_PLAYING
        self._finished = False
        self._started_at = self._clock()
        self._pause_mark = None
        self._paused_span = 0.0
        self._count = 0
        self._history.clear()
        self._suppressed = {finger_id for finger_id in held_finger_ids if finger_id}
        return True

    def pause(self) -> bool:
        if self._phase != PHASE_PLAYING:
            return False
        self._phase = PHASE_PAUSED
        self._pause_mark = self._clock()
        return True

    def resume(self, held_finger_ids: Iterable[str] = ()) -> bool:
        """Vuelve a interpretar. Los dedos ya flexionados quedan silenciados."""
        if self._phase != PHASE_PAUSED:
            return False
        if self._pause_mark is not None:
            self._paused_span += self._clock() - self._pause_mark
        self._pause_mark = None
        self._phase = PHASE_PLAYING
        self._suppressed = {finger_id for finger_id in held_finger_ids if finger_id}
        return True

    def finish(self) -> bool:
        if self._phase == PHASE_IDLE:
            return False
        if self._phase == PHASE_PAUSED and self._pause_mark is not None:
            self._paused_span += self._clock() - self._pause_mark
        self._pause_mark = None
        self._phase = PHASE_IDLE
        self._finished = True
        self._suppressed.clear()
        return True

    def reset_counters(self) -> None:
        """Pone a cero el contador de la sesión. El historial sigue."""
        self._count = 0

    def release_finger(self, finger_id: str) -> None:
        """El dedo ya no está flexionado: la próxima pulsación puede sonar."""
        self._suppressed.discard(finger_id)

    def submit(self, event: MusicalEvent) -> HistoryEntry | None:
        """Acepta la nota si la sesión está interpretando. None si no debe sonar."""
        if self._phase != PHASE_PLAYING:
            return None
        if event.note not in NOTES_BY_NAME or event.origin not in {ORIGIN_GESTURE, ORIGIN_CLICK}:
            return None
        if event.origin == ORIGIN_GESTURE:
            if not event.finger_id or event.finger_id in self._suppressed:
                return None
        entry = HistoryEntry(
            note=event.note,
            finger_id=event.finger_id if event.origin == ORIGIN_GESTURE else None,
            origin=event.origin,
            elapsed_ms=self._elapsed_ms(),
        )
        self._history.append(entry)
        self._count += 1
        return entry

    def _elapsed_ms(self) -> int:
        if self._started_at is None:
            return 0
        paused = self._paused_span
        if self._phase == PHASE_PAUSED and self._pause_mark is not None:
            paused += self._clock() - self._pause_mark
        elapsed = self._clock() - self._started_at - paused
        return int(round(max(0.0, elapsed) * 1000.0))
