"""Acceso a la cámara con OpenCV, sin interfaz gráfica ni reconocimiento."""

from __future__ import annotations

import sys

import cv2
import numpy as np

CAMERA_UNAVAILABLE_MESSAGE = (
    "No se pudo abrir la cámara. Comprueba que está conectada, que ninguna otra "
    "aplicación la está usando y que Windows permite el acceso a la cámara."
)
ALREADY_OPEN_MESSAGE = "La cámara ya está iniciada."
NOT_OPEN_MESSAGE = "La cámara no está abierta."
FRAME_READ_MESSAGE = "No se pudo leer el fotograma."

DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480
_PROBE_ATTEMPTS = 3


class CameraError(Exception):
    """Error de acceso a la cámara."""


class CameraUnavailableError(CameraError):
    """La cámara no existe, está ocupada o el sistema no permite usarla."""


class CameraAlreadyOpenError(CameraError):
    """Se intentó abrir un dispositivo que ya está abierto."""


class CameraNotOpenError(CameraError):
    """Se pidió un fotograma sin una captura activa."""


class FrameReadError(CameraError):
    """OpenCV no entregó un fotograma válido."""


class CameraManager:
    """Abre un dispositivo, lee fotogramas y libera la cámara.

    La instancia debe usarse desde un solo hilo. La ventana no llama a estos
    métodos: lo hace el trabajador de captura.
    """

    def __init__(
        self,
        device_index: int = 0,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
    ) -> None:
        self._validate_device_index(device_index)
        self._validate_resolution(width, height)
        self._device_index = device_index
        self._width = width
        self._height = height
        self._capture: cv2.VideoCapture | None = None

    @property
    def device_index(self) -> int:
        return self._device_index

    @property
    def resolution(self) -> tuple[int, int]:
        return self._width, self._height

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    def open(self) -> None:
        """Abre la cámara una sola vez y comprueba que entrega imagen."""
        if self.is_open:
            raise CameraAlreadyOpenError(ALREADY_OPEN_MESSAGE)

        for backend in self._candidate_backends():
            capture = self._create_capture(self._device_index, backend)
            if not capture.isOpened():
                capture.release()
                continue
            try:
                self._configure(capture)
                if self._read_probe(capture):
                    self._capture = capture
                    return
            except Exception:
                capture.release()
                raise
            capture.release()

        raise CameraUnavailableError(CAMERA_UNAVAILABLE_MESSAGE)

    def read(self) -> np.ndarray:
        """Devuelve una copia BGR del fotograma más reciente."""
        capture = self._capture
        if capture is None or not capture.isOpened():
            raise CameraNotOpenError(NOT_OPEN_MESSAGE)

        ok, frame = capture.read()
        if not ok or frame is None or frame.size == 0:
            raise FrameReadError(FRAME_READ_MESSAGE)
        return frame.copy()

    def set_resolution(self, width: int, height: int) -> None:
        """Guarda la resolución y la aplica si la cámara ya está abierta."""
        self._validate_resolution(width, height)
        self._width = width
        self._height = height
        if self._capture is not None and self._capture.isOpened():
            self._configure(self._capture)

    def close(self) -> None:
        """Libera el dispositivo. Puede llamarse aunque ya esté cerrado."""
        capture = self._capture
        self._capture = None
        if capture is not None:
            capture.release()

    def _candidate_backends(self) -> list[int | None]:
        # DirectShow suele tener menos latencia en Windows. Si no abre o no
        # entrega fotogramas, se prueba el backend predeterminado.
        if sys.platform == "win32":
            return [int(cv2.CAP_DSHOW), None]
        return [None]

    def _create_capture(self, device_index: int, backend: int | None) -> cv2.VideoCapture:
        if backend is None:
            return cv2.VideoCapture(device_index)
        return cv2.VideoCapture(device_index, backend)

    def _configure(self, capture: cv2.VideoCapture) -> None:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(self._width))
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self._height))
        capture.set(cv2.CAP_PROP_FPS, 30)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _read_probe(self, capture: cv2.VideoCapture) -> bool:
        for _ in range(_PROBE_ATTEMPTS):
            ok, frame = capture.read()
            if ok and frame is not None and frame.size > 0:
                return True
        return False

    @staticmethod
    def _validate_device_index(device_index: int) -> None:
        if device_index < 0:
            raise ValueError("El índice de la cámara no puede ser negativo.")

    @staticmethod
    def _validate_resolution(width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("La resolución debe ser mayor que cero.")
