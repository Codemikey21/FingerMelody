"""Resalte de la punta que acaba de pulsar. No escribe nombres sobre la imagen."""

from __future__ import annotations

import cv2
import numpy as np

from fingermelody.vision.hand_overlay import LEFT_COLOR, RIGHT_COLOR

_HIGHLIGHT = {"Left": LEFT_COLOR, "Right": RIGHT_COLOR}


def draw_press_highlights(frame_bgr: np.ndarray, states) -> np.ndarray:
    """Dibuja un aro alrededor de la punta. El círculo del landmark queda en el centro."""
    canvas = frame_bgr.copy()
    height, width = canvas.shape[:2]
    for state in states:
        if not getattr(state, "highlight", False) or state.tip_pixel is None:
            continue
        x, y = state.tip_pixel
        if not (0 <= int(x) < width and 0 <= int(y) < height):
            continue
        color = _HIGHLIGHT.get(getattr(state, "hand", None), (220, 220, 220))
        center = (int(x), int(y))
        cv2.circle(canvas, center, 13, color, 1, cv2.LINE_AA)
        cv2.circle(canvas, center, 8, color, 2, cv2.LINE_AA)
    return canvas
