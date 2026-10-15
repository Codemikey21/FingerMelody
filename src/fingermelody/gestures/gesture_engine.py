"""Pulsación por dedo a partir de los landmarks ya identificados.

No carga un modelo, no conoce notas y no dibuja la cámara. Los ángulos y la
extensión son invariantes a un giro o una traslación de toda la mano.

Los umbrales de GestureConfig son un punto de partida para probar con la
cámara. No son una calibración universal: el anular y el meñique, en
particular, suelen moverse juntos y pueden necesitar umbrales propios más
adelante.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from fingermelody.gestures.finger_detector import FINGER_SPECS, TrackedFinger, finger_id

PHASE_READY = "READY"
PHASE_PRESSED = "PRESSED"
PHASE_HELD = "HELD"
PHASE_RELEASED = "RELEASED"
PHASE_LOST = "LOST"

VISUAL_REST = "Reposo"
VISUAL_PRESS = "Pulsación"
VISUAL_HELD = "Flexionado"
VISUAL_RELEASED = "Liberado"
VISUAL_LOST = "Seguimiento perdido"

_MIN_SEGMENT = 1e-6


@dataclass(frozen=True)
class JointThreshold:
    """Ángulo en grados (menor = más flexión) y extensión de 0 a 1 (1 = recto)."""

    press_angle: float
    release_angle: float
    press_extension: float
    release_extension: float


@dataclass(frozen=True)
class GestureConfig:
    """Parámetros iniciales. Sustituir este objeto es la vía de calibración."""

    finger: JointThreshold = JointThreshold(95.0, 155.0, 0.78, 0.94)
    thumb: JointThreshold = JointThreshold(145.0, 168.0, 0.90, 0.98)
    smooth_alpha: float = 0.45
    press_frames: int = 2
    release_frames: int = 2
    rest_frames: int = 3
    cooldown_ms: int = 150
    highlight_ms: int = 280

    def __post_init__(self) -> None:
        for limits in (self.finger, self.thumb):
            if limits.press_angle >= limits.release_angle:
                raise ValueError("El ángulo de pulsación debe ser menor que el de liberación.")
            if limits.press_extension >= limits.release_extension:
                raise ValueError("La extensión de pulsación debe ser menor que la de liberación.")
        if not 0.0 < self.smooth_alpha <= 1.0:
            raise ValueError("El suavizado debe estar entre 0 y 1.")
        if min(self.press_frames, self.release_frames, self.rest_frames) < 1:
            raise ValueError("La confirmación necesita al menos un fotograma.")
        if self.cooldown_ms < 0 or self.highlight_ms < 0:
            raise ValueError("Los tiempos no pueden ser negativos.")


@dataclass(frozen=True)
class Curl:
    """Medida geométrica de un dedo. El ángulo usa tres puntos; no usa la Y absoluta."""

    angle: float
    extension: float


@dataclass(frozen=True)
class FingerPressEvent:
    """Pulsación lista para un módulo musical. No incluye nota ni frecuencia."""

    finger_id: str
    timestamp_ms: int


@dataclass(frozen=True)
class FingerGestureState:
    """Estado de un dedo para la interfaz y para quien consuma el motor."""

    finger_id: str
    hand: str
    name: str
    display_name: str
    phase: str
    visual: str
    press_count: int
    highlight: bool
    tip_pixel: tuple[int, int] | None


@dataclass(frozen=True)
class GestureUpdate:
    """Resultado de un fotograma: diez estados y las pulsaciones nuevas."""

    active: bool = False
    states: tuple[FingerGestureState, ...] = ()
    events: tuple[FingerPressEvent, ...] = ()

    @staticmethod
    def inactive() -> GestureUpdate:
        return GestureUpdate()


def format_gesture_column(
    title: str,
    states: tuple[FingerGestureState, ...],
    *,
    active: bool,
) -> str:
    """Columna del panel. En reposo el contador sigue visible y no implica una nota."""
    if not active:
        rows = [f"{spec.display_name} — —" for spec in FINGER_SPECS]
    else:
        rows = [
            f"{state.display_name} ({state.finger_id}) — {state.visual} · {state.press_count}"
            for state in states
        ]
    return title + "\n" + "\n".join(rows)


def finger_curl(finger: TrackedFinger | None) -> Curl | None:
    """Ángulo de flexión y extensión normalizada, o None si el dedo no es usable."""
    if finger is None or not finger.tracked:
        return None
    if finger.name == "thumb":
        cmc = _point(finger, "CMC")
        mcp = _point(finger, "MCP")
        ip = _point(finger, "IP")
        tip = _point(finger, "TIP")
        if any(point is None for point in (cmc, mcp, ip, tip)):
            return None
        angles = (_angle(cmc, mcp, ip), _angle(mcp, ip, tip))
        chain = (cmc, mcp, ip, tip)
    else:
        mcp = _point(finger, "MCP")
        pip = _point(finger, "PIP")
        dip = _point(finger, "DIP")
        tip = _point(finger, "TIP")
        if any(point is None for point in (mcp, pip, dip, tip)):
            return None
        angles = (_angle(mcp, pip, dip), _angle(pip, dip, tip))
        chain = (mcp, pip, dip, tip)
    if any(angle is None for angle in angles):
        return None
    extension = _extension(chain)
    if extension is None:
        return None
    return Curl(angle=float(min(angles)), extension=extension)


class GestureEngine:
    """Máquina READY → PRESSED → HELD → RELEASED → READY, una por dedo.

    El evento sale solo al entrar en PRESSED. Perder el seguimiento pasa a
    LOST y no cuenta como liberación. Al volver, hace falta un reposo válido
    antes de otra pulsación.
    """

    def __init__(self, config: GestureConfig | None = None) -> None:
        self.config = config or GestureConfig()
        self._listeners: list[Callable[[FingerPressEvent], None]] = []
        self._last_timestamp: int | None = None
        self._fingers = _fresh_runtimes()

    def subscribe(self, listener: Callable[[FingerPressEvent], None]) -> None:
        """Registra un consumidor. Se llama en el hilo que actualiza el motor."""
        self._listeners.append(listener)

    def reset(self) -> None:
        """Olvida estados y contadores. No quita los suscriptores."""
        self._last_timestamp = None
        self._fingers = _fresh_runtimes()

    def update(
        self,
        fingers: tuple[TrackedFinger, ...] | list[TrackedFinger],
        timestamp_ms: int,
    ) -> GestureUpdate:
        """Avanza los diez dedos con la marca de tiempo del fotograma."""
        timestamp_ms = int(timestamp_ms)
        if self._last_timestamp is not None and timestamp_ms < self._last_timestamp:
            return self._snapshot(())
        self._last_timestamp = timestamp_ms
        incoming = _by_id(fingers)
        events: list[FingerPressEvent] = []
        for runtime in self._fingers:
            event = self._advance(runtime, incoming.get(runtime.finger_id), timestamp_ms)
            if event is not None:
                events.append(event)
        for event in events:
            for listener in self._listeners:
                listener(event)
        return self._snapshot(tuple(events))

    def _advance(self, runtime, finger: TrackedFinger | None, timestamp_ms: int):
        curl = finger_curl(finger)
        if curl is None:
            _mark_lost(runtime)
            return None
        runtime.tip_pixel = finger.tip_pixel
        alpha = self.config.smooth_alpha
        runtime.angle = _smooth(runtime.angle, curl.angle, alpha)
        runtime.extension = _smooth(runtime.extension, curl.extension, alpha)
        posture = _posture(runtime, _limits(self.config, runtime.name))
        phase = runtime.phase

        if phase == PHASE_LOST:
            if posture == "extended":
                runtime.extend_run += 1
                if runtime.extend_run >= self.config.rest_frames:
                    runtime.phase = PHASE_READY
                    runtime.extend_run = 0
                    runtime.flex_run = 0
            else:
                runtime.extend_run = 0
            return None

        if phase == PHASE_READY:
            if posture == "flexed":
                runtime.flex_run += 1
                cooled = (
                    runtime.last_press_ms is None
                    or timestamp_ms - runtime.last_press_ms >= self.config.cooldown_ms
                )
                if runtime.flex_run >= self.config.press_frames and cooled:
                    runtime.phase = PHASE_PRESSED
                    runtime.flex_run = 0
                    runtime.extend_run = 0
                    runtime.last_press_ms = timestamp_ms
                    runtime.press_count += 1
                    runtime.highlight_until = timestamp_ms + self.config.highlight_ms
                    return FingerPressEvent(runtime.finger_id, timestamp_ms)
            else:
                runtime.flex_run = 0
            return None

        if phase == PHASE_PRESSED:
            runtime.phase = PHASE_HELD
            runtime.extend_run = 0
            runtime.flex_run = 0
            return None

        if phase == PHASE_HELD:
            _hold_or_release(runtime, posture, self.config.release_frames)
            return None

        if phase == PHASE_RELEASED:
            if posture == "extended":
                runtime.phase = PHASE_READY
                runtime.flex_run = 0
            elif posture == "flexed":
                runtime.phase = PHASE_HELD
            return None
        return None

    def _snapshot(self, events: tuple[FingerPressEvent, ...]) -> GestureUpdate:
        timestamp = self._last_timestamp if self._last_timestamp is not None else 0
        states = tuple(_view(runtime, timestamp) for runtime in self._fingers)
        return GestureUpdate(active=True, states=states, events=events)


class _Runtime:
    def __init__(self, finger_id: str, hand: str, name: str, display_name: str) -> None:
        self.finger_id = finger_id
        self.hand = hand
        self.name = name
        self.display_name = display_name
        self.phase = PHASE_LOST
        self.angle: float | None = None
        self.extension: float | None = None
        self.flex_run = 0
        self.extend_run = 0
        self.last_press_ms: int | None = None
        self.press_count = 0
        self.highlight_until = -1
        self.tip_pixel: tuple[int, int] | None = None


def _fresh_runtimes() -> tuple[_Runtime, ...]:
    runtimes = []
    for hand in ("Left", "Right"):
        for spec in FINGER_SPECS:
            runtimes.append(_Runtime(finger_id(hand, spec), hand, spec.name, spec.display_name))
    return tuple(runtimes)


def _by_id(fingers) -> dict[str, TrackedFinger]:
    grouped: dict[str, TrackedFinger] = {}
    for finger in fingers:
        if finger.finger_id not in grouped:
            grouped[finger.finger_id] = finger
    return grouped


def _limits(config: GestureConfig, name: str) -> JointThreshold:
    if name == "thumb":
        return config.thumb
    return config.finger


def _posture(runtime: _Runtime, limits: JointThreshold) -> str:
    angle = runtime.angle
    extension = runtime.extension
    if angle is None or extension is None:
        return "ambiguous"
    if angle <= limits.press_angle and extension <= limits.press_extension:
        return "flexed"
    if angle >= limits.release_angle and extension >= limits.release_extension:
        return "extended"
    return "ambiguous"


def _hold_or_release(runtime: _Runtime, posture: str, release_frames: int) -> None:
    if posture == "extended":
        runtime.extend_run += 1
        if runtime.extend_run >= release_frames:
            runtime.phase = PHASE_RELEASED
            runtime.extend_run = 0
            runtime.flex_run = 0
        else:
            runtime.phase = PHASE_HELD
    else:
        runtime.phase = PHASE_HELD
        runtime.extend_run = 0


def _mark_lost(runtime: _Runtime) -> None:
    runtime.phase = PHASE_LOST
    runtime.angle = None
    runtime.extension = None
    runtime.flex_run = 0
    runtime.extend_run = 0
    runtime.tip_pixel = None


def _view(runtime: _Runtime, timestamp_ms: int) -> FingerGestureState:
    highlight = runtime.press_count > 0 and timestamp_ms <= runtime.highlight_until
    return FingerGestureState(
        finger_id=runtime.finger_id,
        hand=runtime.hand,
        name=runtime.name,
        display_name=runtime.display_name,
        phase=runtime.phase,
        visual=_visual(runtime.phase, highlight),
        press_count=runtime.press_count,
        highlight=highlight or runtime.phase == PHASE_PRESSED,
        tip_pixel=runtime.tip_pixel,
    )


def _visual(phase: str, highlight: bool) -> str:
    if phase == PHASE_LOST:
        return VISUAL_LOST
    if phase == PHASE_RELEASED:
        return VISUAL_RELEASED
    if highlight or phase == PHASE_PRESSED:
        return VISUAL_PRESS
    if phase == PHASE_HELD:
        return VISUAL_HELD
    return VISUAL_REST


def _smooth(previous: float | None, sample: float, alpha: float) -> float:
    if previous is None:
        return sample
    return alpha * sample + (1.0 - alpha) * previous


def _point(finger: TrackedFinger, role: str) -> np.ndarray | None:
    for joint in finger.joints:
        if joint.role != role or joint.normalized is None:
            continue
        values = np.asarray(joint.normalized[:3], dtype=float)
        if values.shape != (3,) or not np.all(np.isfinite(values)):
            return None
        return values
    return None


def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float | None:
    before = a - b
    after = c - b
    norm_before = float(np.linalg.norm(before))
    norm_after = float(np.linalg.norm(after))
    if norm_before < _MIN_SEGMENT or norm_after < _MIN_SEGMENT:
        return None
    cosine = float(np.dot(before, after) / (norm_before * norm_after))
    cosine = float(np.clip(cosine, -1.0, 1.0))
    return float(np.degrees(np.arccos(cosine)))


def _extension(chain: tuple[np.ndarray, ...]) -> float | None:
    segments = [
        float(np.linalg.norm(chain[index + 1] - chain[index]))
        for index in range(len(chain) - 1)
    ]
    length = float(sum(segments))
    if length < _MIN_SEGMENT:
        return None
    span = float(np.linalg.norm(chain[-1] - chain[0]))
    return span / length
