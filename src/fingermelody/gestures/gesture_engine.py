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
    """Ángulo en grados (menor = más flexión) y extensión de 0 a 1 (1 = recto).

    La oposición del pulgar es la distancia de la punta al índice, dividida por
    el largo de la palma. Un valor bajo acerca el pulgar a la palma.
    """

    press_angle: float
    release_angle: float
    press_extension: float
    release_extension: float
    press_opposition: float | None = None
    release_opposition: float | None = None


@dataclass(frozen=True)
class GestureConfig:
    """Parámetros de partida. Una calibración de reposo y flexión puede sustituirlos.

    El ángulo de los cuatro dedos queda en 125° porque una flexión de unos 100°
    nunca cruzaba el antiguo límite de 95°, y el suavizado de 0,45 tardaba
    varios fotogramas en acercarse. El pulgar no usa solo ese ángulo: con la
    punta lejos de la palma, la articulación MCP ya ronda 140° y la cadena no
    llega a 168° ni a una extensión de 0,98, así que no entraba en READY.
    """

    finger: JointThreshold = JointThreshold(125.0, 155.0, 0.90, 0.96)
    thumb: JointThreshold = JointThreshold(145.0, 168.0, 0.90, 0.98, 0.55, 0.82)
    smooth_alpha: float = 0.72
    press_frames: int = 2
    release_frames: int = 2
    rest_frames: int = 2
    cooldown_ms: int = 120
    highlight_ms: int = 280
    press_ms: int = 20
    release_ms: int = 20
    rest_ms: int = 30

    def __post_init__(self) -> None:
        for limits in (self.finger, self.thumb):
            if limits.press_angle >= limits.release_angle:
                raise ValueError("El ángulo de pulsación debe ser menor que el de liberación.")
            if limits.press_extension >= limits.release_extension:
                raise ValueError("La extensión de pulsación debe ser menor que la de liberación.")
            if (
                limits.press_opposition is not None
                and limits.release_opposition is not None
                and limits.press_opposition >= limits.release_opposition
            ):
                raise ValueError("La oposición de pulsación debe ser menor que la de liberación.")
        if not 0.0 < self.smooth_alpha <= 1.0:
            raise ValueError("El suavizado debe estar entre 0 y 1.")
        if min(self.press_frames, self.release_frames, self.rest_frames) < 1:
            raise ValueError("La confirmación necesita al menos un fotograma.")
        if min(self.press_ms, self.release_ms, self.rest_ms, self.cooldown_ms, self.highlight_ms) < 0:
            raise ValueError("Los tiempos no pueden ser negativos.")


@dataclass(frozen=True)
class Curl:
    """Medida geométrica de un dedo. El ángulo usa tres puntos; no usa la Y absoluta."""

    angle: float
    extension: float
    opposition: float | None = None


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
    angle: float | None = None
    extension: float | None = None
    opposition: float | None = None
    flex_ms: int | None = None


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
    opposition = None
    if finger.name == "thumb" and finger.anchors:
        opposition = _opposition(chain[-1], finger.anchors)
    return Curl(angle=float(min(angles)), extension=extension, opposition=opposition)


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
        self._rest: dict[str, Curl] = {}
        self._flex: dict[str, Curl] = {}

    def subscribe(self, listener: Callable[[FingerPressEvent], None]) -> None:
        """Registra un consumidor. Se llama en el hilo que actualiza el motor."""
        self._listeners.append(listener)

    def reset(self) -> None:
        """Olvida estados y contadores. Conserva suscriptores y la calibración."""
        self._last_timestamp = None
        self._fingers = _fresh_runtimes()

    def clear_press_counts(self) -> None:
        """Pone a cero los contadores visibles. La fase y los umbrales siguen igual."""
        for runtime in self._fingers:
            runtime.press_count = 0
            runtime.highlight_until = -1

    def capture_reference(self, fingers, kind: str) -> int:
        """Guarda la pose actual como reposo o como flexión. Devuelve cuántos dedos entraron."""
        if kind not in {"rest", "flex"}:
            raise ValueError("La referencia debe ser reposo o flexión.")
        target = self._rest if kind == "rest" else self._flex
        stored = 0
        for finger in fingers:
            curl = finger_curl(finger)
            if curl is None:
                continue
            target[finger.finger_id] = curl
            stored += 1
        return stored

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

    def _effective_limits(self, runtime) -> JointThreshold:
        base = _limits(self.config, runtime.name)
        rest = self._rest.get(runtime.finger_id)
        flexed = self._flex.get(runtime.finger_id)
        if rest is None or flexed is None:
            return base
        calibrated = _calibrated_threshold(base, rest, flexed)
        return base if calibrated is None else calibrated

    def _advance(self, runtime, finger: TrackedFinger | None, timestamp_ms: int):
        curl = finger_curl(finger)
        if curl is None:
            _mark_lost(runtime)
            return None
        runtime.tip_pixel = finger.tip_pixel
        alpha = self.config.smooth_alpha
        runtime.angle = _smooth(runtime.angle, curl.angle, alpha)
        runtime.extension = _smooth(runtime.extension, curl.extension, alpha)
        if curl.opposition is None:
            runtime.opposition = None
        else:
            runtime.opposition = _smooth(runtime.opposition, curl.opposition, alpha)
        limits = self._effective_limits(runtime)
        posture = _posture(runtime, limits)
        phase = runtime.phase

        if phase == PHASE_LOST:
            if posture == "extended":
                if runtime.rest_since_ms is None:
                    runtime.rest_since_ms = timestamp_ms
                runtime.extend_run += 1
                elapsed = timestamp_ms - runtime.rest_since_ms
                if runtime.extend_run >= self.config.rest_frames and _elapsed(elapsed, self.config.rest_ms):
                    runtime.phase = PHASE_READY
                    runtime.extend_run = 0
                    runtime.flex_run = 0
                    runtime.rest_since_ms = None
                    runtime.flex_since_ms = None
            else:
                runtime.extend_run = 0
                runtime.rest_since_ms = None
            return None

        if phase == PHASE_READY:
            if posture == "flexed":
                if runtime.flex_since_ms is None:
                    runtime.flex_since_ms = timestamp_ms
                runtime.flex_run += 1
                elapsed = timestamp_ms - runtime.flex_since_ms
                cooled = (
                    runtime.last_press_ms is None
                    or timestamp_ms - runtime.last_press_ms >= self.config.cooldown_ms
                )
                confirmed = runtime.flex_run >= self.config.press_frames and _elapsed(elapsed, self.config.press_ms)
                if confirmed and cooled:
                    runtime.phase = PHASE_PRESSED
                    runtime.flex_run = 0
                    runtime.extend_run = 0
                    runtime.last_press_ms = timestamp_ms
                    runtime.press_count += 1
                    runtime.highlight_until = timestamp_ms + self.config.highlight_ms
                    return FingerPressEvent(runtime.finger_id, timestamp_ms)
            else:
                runtime.flex_run = 0
                runtime.flex_since_ms = None
            return None

        if phase == PHASE_PRESSED:
            runtime.phase = PHASE_HELD
            runtime.extend_run = 0
            runtime.flex_run = 0
            runtime.release_since_ms = None
            return None

        if phase == PHASE_HELD:
            _hold_or_release(
                runtime,
                posture,
                self.config.release_frames,
                self.config.release_ms,
                timestamp_ms,
            )
            return None

        if phase == PHASE_RELEASED:
            if posture == "extended":
                runtime.phase = PHASE_READY
                runtime.flex_run = 0
                runtime.flex_since_ms = None
            elif posture == "flexed":
                runtime.phase = PHASE_HELD
                runtime.flex_since_ms = timestamp_ms
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
        self.opposition: float | None = None
        self.flex_since_ms: int | None = None
        self.rest_since_ms: int | None = None
        self.release_since_ms: int | None = None


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
    joint_flex = angle <= limits.press_angle and extension <= limits.press_extension
    joint_open = angle >= limits.release_angle and extension >= limits.release_extension
    opposition = runtime.opposition
    if (
        opposition is not None
        and limits.press_opposition is not None
        and limits.release_opposition is not None
    ):
        # La punta cerca de la palma es una pulsación aunque el IP siga abierto.
        if opposition <= limits.press_opposition or joint_flex:
            return "flexed"
        if opposition >= limits.release_opposition or joint_open:
            return "extended"
        return "ambiguous"
    if joint_flex:
        return "flexed"
    if joint_open:
        return "extended"
    return "ambiguous"


def _hold_or_release(
    runtime: _Runtime,
    posture: str,
    release_frames: int,
    release_ms: int,
    timestamp_ms: int,
) -> None:
    if posture == "extended":
        if runtime.release_since_ms is None:
            runtime.release_since_ms = timestamp_ms
        runtime.extend_run += 1
        elapsed = timestamp_ms - runtime.release_since_ms
        if runtime.extend_run >= release_frames and _elapsed(elapsed, release_ms):
            runtime.phase = PHASE_RELEASED
            runtime.extend_run = 0
            runtime.flex_run = 0
            runtime.release_since_ms = None
            runtime.flex_since_ms = None
        else:
            runtime.phase = PHASE_HELD
    else:
        runtime.phase = PHASE_HELD
        runtime.extend_run = 0
        runtime.release_since_ms = None


def _mark_lost(runtime: _Runtime) -> None:
    runtime.phase = PHASE_LOST
    runtime.angle = None
    runtime.extension = None
    runtime.opposition = None
    runtime.flex_run = 0
    runtime.extend_run = 0
    runtime.flex_since_ms = None
    runtime.rest_since_ms = None
    runtime.release_since_ms = None
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
        angle=runtime.angle,
        extension=runtime.extension,
        opposition=runtime.opposition,
        flex_ms=None if runtime.flex_since_ms is None else timestamp_ms - runtime.flex_since_ms,
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


def _elapsed(elapsed_ms: int, required_ms: int) -> bool:
    return required_ms <= 0 or elapsed_ms >= required_ms


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


def _opposition(tip: np.ndarray, anchors: tuple[tuple[float, float, float], ...]) -> float | None:
    """Distancia de la punta al MCP del índice, relativa al largo de la palma."""
    if len(anchors) < 3:
        return None
    wrist = np.asarray(anchors[0][:3], dtype=float)
    index_mcp = np.asarray(anchors[1][:3], dtype=float)
    middle_mcp = np.asarray(anchors[2][:3], dtype=float)
    if not all(np.all(np.isfinite(point)) for point in (wrist, index_mcp, middle_mcp, tip)):
        return None
    palm = float(np.linalg.norm(middle_mcp - wrist))
    if palm < _MIN_SEGMENT:
        palm = float(np.linalg.norm(index_mcp - wrist))
    if palm < _MIN_SEGMENT:
        return None
    return float(np.linalg.norm(tip - index_mcp) / palm)


def _calibrated_threshold(base: JointThreshold, rest: Curl, flexed: Curl) -> JointThreshold | None:
    """Punto medio entre la pose abierta y la pose flexionada de esa persona."""
    press_angle = base.press_angle
    release_angle = base.release_angle
    if flexed.angle < rest.angle - 15.0:
        press_angle = (rest.angle + flexed.angle) / 2.0
        release_angle = max(press_angle + 12.0, min(rest.angle - 4.0, rest.angle))
    press_extension = base.press_extension
    release_extension = base.release_extension
    if flexed.extension < rest.extension - 0.04:
        press_extension = (rest.extension + flexed.extension) / 2.0
        release_extension = max(press_extension + 0.03, min(rest.extension - 0.01, rest.extension))
    press_opposition = base.press_opposition
    release_opposition = base.release_opposition
    if (
        rest.opposition is not None
        and flexed.opposition is not None
        and flexed.opposition < rest.opposition - 0.08
    ):
        press_opposition = (rest.opposition + flexed.opposition) / 2.0
        release_opposition = max(press_opposition + 0.12, rest.opposition - 0.05)
    if press_angle >= release_angle or press_extension >= release_extension:
        return None
    if (
        press_opposition is not None
        and release_opposition is not None
        and press_opposition >= release_opposition
    ):
        return None
    return JointThreshold(
        press_angle,
        release_angle,
        press_extension,
        release_extension,
        press_opposition,
        release_opposition,
    )


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
