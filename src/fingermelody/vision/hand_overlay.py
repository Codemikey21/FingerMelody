"""Dibujo de landmarks. No detecta manos ni decide su clasificación."""

from __future__ import annotations

import cv2
import numpy as np

from fingermelody.vision.hand_tracker import TrackedHand

# Misma topología que HandLandmarksConnections.HAND_CONNECTIONS de MediaPipe.
HAND_CONNECTIONS = (
    (0, 1),
    (0, 5),
    (9, 13),
    (13, 17),
    (5, 9),
    (0, 17),
    (1, 2),
    (2, 3),
    (3, 4),
    (5, 6),
    (6, 7),
    (7, 8),
    (9, 10),
    (10, 11),
    (11, 12),
    (13, 14),
    (14, 15),
    (15, 16),
    (17, 18),
    (18, 19),
    (19, 20),
)

LEFT_COLOR = (164, 176, 122)
RIGHT_COLOR = (120, 156, 186)
UNKNOWN_COLOR = (150, 150, 150)


def mirror_selfie_frame(frame_bgr: np.ndarray) -> np.ndarray:
    """Copia el fotograma espejado en horizontal, como una cámara frontal."""
    return cv2.flip(frame_bgr, 1)


def draw_hands(frame_bgr: np.ndarray, hands: tuple[TrackedHand, ...] | list[TrackedHand]) -> np.ndarray:
    """Dibuja puntos y conexiones sobre una copia del fotograma."""
    canvas = frame_bgr.copy()
    height, width = canvas.shape[:2]
    for hand in hands:
        color = _color_for(hand.label)
        _draw_connections(canvas, hand.pixels, color, width, height)
        _draw_points(canvas, hand.pixels, color, width, height)
        if hand.label:
            _draw_label(canvas, hand.label, hand.pixels, color, width, height)
    return canvas


def _color_for(label: str | None) -> tuple[int, int, int]:
    if label == "Left":
        return LEFT_COLOR
    if label == "Right":
        return RIGHT_COLOR
    return UNKNOWN_COLOR


def _inside(point: tuple[int, int] | None, width: int, height: int) -> bool:
    if point is None:
        return False
    x, y = point
    return 0 <= x < width and 0 <= y < height


def _draw_connections(canvas, pixels, color, width: int, height: int) -> None:
    for start, end in HAND_CONNECTIONS:
        if start >= len(pixels) or end >= len(pixels):
            continue
        if not _inside(pixels[start], width, height) or not _inside(pixels[end], width, height):
            continue
        cv2.line(canvas, pixels[start], pixels[end], color, 2, cv2.LINE_AA)


def _draw_points(canvas, pixels, color, width: int, height: int) -> None:
    for point in pixels:
        if not _inside(point, width, height):
            continue
        cv2.circle(canvas, point, 3, color, -1, cv2.LINE_AA)


def _draw_label(canvas, text: str, pixels, color, width: int, height: int) -> None:
    anchor = next((point for point in pixels if _inside(point, width, height)), None)
    if anchor is None:
        return
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.5
    thickness = 1
    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
    x = min(max(anchor[0], 0), max(width - text_width - 8, 0))
    y = min(max(anchor[1] - 10, text_height + 6), max(height - baseline - 2, text_height + 6))
    cv2.rectangle(
        canvas,
        (x, y - text_height - 6),
        (x + text_width + 8, y + baseline + 2),
        (20, 20, 24),
        -1,
    )
    cv2.putText(canvas, text, (x + 4, y), font, scale, color, thickness, cv2.LINE_AA)
