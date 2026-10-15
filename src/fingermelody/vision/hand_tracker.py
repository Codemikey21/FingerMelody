"""Detección de manos con el Hand Landmarker de MediaPipe.

Hand Landmarker (Tasks, desde 0.10.5; esta instalación es 1.1.1) etiqueta la
mano del usuario cuando la imagen no está espejada. Un volteo horizontal
invierte esa etiqueta. CameraWorker voltea el fotograma una vez y crea el
tracker con mirrored_input=True, así que Left y Right quedan como la mano
anatómica. Los puntos siguen en las coordenadas de esa imagen espejada.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MODEL_FILENAME = "hand_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
MIN_MODEL_BYTES = 1_000_000
MIN_HANDEDNESS_SCORE = 0.5
LANDMARK_COUNT = 21
IDLE_TRACKING_MESSAGE = "Reconocimiento inactivo"
NO_HANDS_MESSAGE = "No hay manos visibles"
BOTH_HANDS_MESSAGE = "Ambas manos presentes"
ACTIVE_TRACKING_MESSAGE = "Reconocimiento activo"
UNCLASSIFIED_MESSAGE = "Mano detectada sin clasificación fiable"
MODEL_MISSING_MESSAGE = "No se encontró el modelo de manos."
MODEL_INVALID_MESSAGE = "El archivo del modelo de manos está dañado o incompleto."
MODEL_INIT_MESSAGE = "No se pudo iniciar el reconocimiento de manos."
FRAME_INVALID_MESSAGE = "El fotograma no es válido para reconocer manos."
DETECT_FAILED_MESSAGE = "No se pudo reconocer las manos en este fotograma."


class HandTrackerError(Exception):
    """Error controlable del reconocimiento de manos."""


@dataclass(frozen=True)
class TrackedHand:
    """Una mano detectada, con puntos normalizados y en píxeles."""

    label: str | None
    score: float | None
    normalized: tuple[tuple[float, float, float], ...]
    pixels: tuple[tuple[int, int] | None, ...]


@dataclass(frozen=True)
class HandFrame:
    """Resultado de una detección sobre un fotograma."""

    hands: tuple[TrackedHand, ...]
    width: int
    height: int


@dataclass(frozen=True)
class HandViewState:
    """Estado que la interfaz puede mostrar sin conocer MediaPipe."""

    active: bool = False
    hand_count: int = 0
    left_present: bool = False
    right_present: bool = False
    unclassified: int = 0
    message: str = IDLE_TRACKING_MESSAGE

    @property
    def both_present(self) -> bool:
        return self.left_present and self.right_present


class MonotonicMilliseconds:
    """Reloj en milisegundos, estrictamente creciente."""

    def __init__(self, now_ms=None) -> None:
        self._now_ms = now_ms or (lambda: int(time.monotonic() * 1000))
        self._last = -1

    def next_ms(self) -> int:
        current = int(self._now_ms())
        if current <= self._last:
            current = self._last + 1
        self._last = current
        return current


def default_model_path() -> Path:
    """Ruta del modelo dentro del repositorio."""
    return Path(__file__).resolve().parents[3] / "assets" / "models" / MODEL_FILENAME


def validate_model_file(path: Path) -> None:
    """Comprueba que el archivo existe y parece un paquete .task."""
    if not path.is_file():
        raise HandTrackerError(f"{MODEL_MISSING_MESSAGE} Ruta: {path}")
    if path.stat().st_size < MIN_MODEL_BYTES:
        raise HandTrackerError(MODEL_INVALID_MESSAGE)
    with path.open("rb") as handle:
        header = handle.read(16)
    if b"PK\x03\x04" not in header:
        raise HandTrackerError(MODEL_INVALID_MESSAGE)


def normalized_to_pixel(
    x: float,
    y: float,
    width: int,
    height: int,
) -> tuple[int, int] | None:
    """Convierte una coordenada normalizada a un píxel dentro de la imagen."""
    if width <= 1 or height <= 1:
        return None
    if x < -0.1 or x > 1.1 or y < -0.1 or y > 1.1:
        return None
    clamped_x = min(max(x, 0.0), 1.0)
    clamped_y = min(max(y, 0.0), 1.0)
    return (
        int(round(clamped_x * (width - 1))),
        int(round(clamped_y * (height - 1))),
    )


def anatomical_label(model_label: str | None, *, mirrored: bool) -> str | None:
    """Pasa la etiqueta del modelo a la mano anatómica del usuario.

    Sin espejo, Left y Right se conservan. Con el fotograma ya volteado en
    horizontal, se intercambian una sola vez. Una confianza insuficiente llega
    aquí como None y sigue sin etiqueta.
    """
    if model_label not in ("Left", "Right"):
        return None
    if mirrored:
        return "Right" if model_label == "Left" else "Left"
    return model_label


def to_view_state(frame: HandFrame) -> HandViewState:
    """Resume una detección para los indicadores de la ventana."""
    left = any(hand.label == "Left" for hand in frame.hands)
    right = any(hand.label == "Right" for hand in frame.hands)
    unclassified = sum(1 for hand in frame.hands if hand.label is None)
    count = len(frame.hands)
    if left and right:
        message = BOTH_HANDS_MESSAGE
    elif count == 0:
        message = NO_HANDS_MESSAGE
    elif not left and not right:
        message = UNCLASSIFIED_MESSAGE
    else:
        message = ACTIVE_TRACKING_MESSAGE
    return HandViewState(
        active=True,
        hand_count=count,
        left_present=left,
        right_present=right,
        unclassified=unclassified,
        message=message,
    )


class HandTracker:
    """Ejecuta el Hand Landmarker sobre fotogramas BGR.

    La instancia se usa desde un solo hilo. Se crea al empezar la captura y
    se cierra al detenerla; no se reconstruye en cada fotograma.
    """

    def __init__(
        self,
        model_path: Path | None = None,
        num_hands: int = 2,
        clock: MonotonicMilliseconds | None = None,
        image_factory=None,
        landmarker_factory=None,
        mirrored_input: bool = False,
    ) -> None:
        if num_hands < 1:
            raise ValueError("El número de manos debe ser al menos 1.")
        self._model_path = Path(model_path) if model_path is not None else default_model_path()
        self._num_hands = num_hands
        self._mirrored_input = mirrored_input
        self._clock = clock or MonotonicMilliseconds()
        self._image_factory = image_factory or _media_image
        self._landmarker_factory = landmarker_factory
        self._landmarker = None

    @property
    def num_hands(self) -> int:
        return self._num_hands

    @property
    def is_open(self) -> bool:
        return self._landmarker is not None

    def open(self) -> None:
        """Carga el modelo una sola vez."""
        if self._landmarker is not None:
            return
        validate_model_file(self._model_path)
        options = self._build_options()
        factory = self._landmarker_factory or _create_landmarker
        try:
            self._landmarker = factory(options)
        except (OSError, RuntimeError, ValueError) as exc:
            self._landmarker = None
            raise HandTrackerError(MODEL_INIT_MESSAGE) from exc

    def _build_options(self):
        from mediapipe.tasks.python.core.base_options import BaseOptions
        from mediapipe.tasks.python.vision.core.vision_task_running_mode import (
            VisionTaskRunningMode,
        )
        from mediapipe.tasks.python.vision.hand_landmarker import HandLandmarkerOptions

        return HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(self._model_path)),
            running_mode=VisionTaskRunningMode.VIDEO,
            num_hands=self._num_hands,
        )

    def detect(self, frame_bgr: np.ndarray) -> HandFrame:
        """Detecta hasta num_hands manos en un fotograma BGR."""
        if self._landmarker is None:
            raise HandTrackerError("El reconocedor de manos no está iniciado.")
        height, width = _validate_frame(frame_bgr)
        rgb = np.ascontiguousarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        timestamp_ms = self._clock.next_ms()
        try:
            image = self._image_factory(rgb)
            result = self._landmarker.detect_for_video(image, timestamp_ms)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HandTrackerError(DETECT_FAILED_MESSAGE) from exc
        return _parse_result(
            result,
            width,
            height,
            self._num_hands,
            mirrored=self._mirrored_input,
        )

    def close(self) -> None:
        """Libera el modelo. No propaga fallos del cierre."""
        landmarker = self._landmarker
        self._landmarker = None
        if landmarker is None:
            return
        try:
            landmarker.close()
        except Exception:
            return


def _create_landmarker(options):
    from mediapipe.tasks.python.vision.hand_landmarker import HandLandmarker

    return HandLandmarker.create_from_options(options)


def _media_image(rgb: np.ndarray):
    from mediapipe.tasks.python.vision.core.image import Image, ImageFormat

    return Image(ImageFormat.SRGB, rgb)


def _validate_frame(frame_bgr: np.ndarray) -> tuple[int, int]:
    if frame_bgr is None or not isinstance(frame_bgr, np.ndarray):
        raise HandTrackerError(FRAME_INVALID_MESSAGE)
    if frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3 or frame_bgr.size == 0:
        raise HandTrackerError(FRAME_INVALID_MESSAGE)
    height, width = int(frame_bgr.shape[0]), int(frame_bgr.shape[1])
    if width <= 1 or height <= 1:
        raise HandTrackerError(FRAME_INVALID_MESSAGE)
    return height, width


def _classify_hand(categories) -> tuple[str | None, float | None]:
    if not categories:
        return None, None
    best = max(categories, key=lambda category: category.score or 0.0)
    score = None if best.score is None else float(best.score)
    name = (best.category_name or "").strip().lower()
    if name not in {"left", "right"} or score is None or score < MIN_HANDEDNESS_SCORE:
        return None, score
    return ("Left" if name == "left" else "Right"), score


def _parse_result(
    result,
    width: int,
    height: int,
    num_hands: int,
    mirrored: bool = False,
) -> HandFrame:
    landmarks = list(getattr(result, "hand_landmarks", None) or [])
    handedness = list(getattr(result, "handedness", None) or [])
    hands: list[TrackedHand] = []
    for index, points in enumerate(landmarks[:num_hands]):
        categories = handedness[index] if index < len(handedness) else []
        label, score = _classify_hand(categories)
        label = anatomical_label(label, mirrored=mirrored)
        normalized: list[tuple[float, float, float]] = []
        pixels: list[tuple[int, int] | None] = []
        for point in points:
            x = getattr(point, "x", None)
            y = getattr(point, "y", None)
            z = getattr(point, "z", 0.0) or 0.0
            if x is None or y is None:
                normalized.append((0.0, 0.0, float(z)))
                pixels.append(None)
                continue
            normalized.append((float(x), float(y), float(z)))
            pixels.append(normalized_to_pixel(float(x), float(y), width, height))
        hands.append(
            TrackedHand(
                label=label,
                score=score,
                normalized=tuple(normalized),
                pixels=tuple(pixels),
            )
        )
    return HandFrame(hands=tuple(hands), width=width, height=height)
