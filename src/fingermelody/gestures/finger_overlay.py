"""Nombres de los dedos sobre la imagen ya anotada. No detecta ni clasifica."""

from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from fingermelody.gestures.finger_detector import TrackedFinger
from fingermelody.vision.hand_overlay import LEFT_COLOR, RIGHT_COLOR

# BGR, apagados para conservar el fondo oscuro. El mismo color vale en las dos manos.
FINGER_COLORS = {
    "thumb": (120, 166, 186),
    "index": (166, 176, 122),
    "middle": (150, 168, 146),
    "ring": (168, 146, 160),
    "pinky": (146, 156, 176),
}

_HAND_COLORS = {"Left": LEFT_COLOR, "Right": RIGHT_COLOR}
_FONT = None
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)


def draw_finger_labels(
    frame_bgr: np.ndarray,
    fingers: tuple[TrackedFinger, ...] | list[TrackedFinger],
) -> np.ndarray:
    """Escribe el nombre junto a la punta. Omite dedos sin seguimiento."""
    canvas = frame_bgr.copy()
    height, width = canvas.shape[:2]
    placed: list[tuple[int, int, int, int]] = []
    labels = []
    for finger in fingers:
        if not finger.tracked or finger.tip_pixel is None:
            continue
        if finger.hand not in _HAND_COLORS or finger.name not in FINGER_COLORS:
            continue
        text = finger.display_name
        text_size = _text_size(text)
        if text_size is None:
            continue
        text_width, text_height = text_size
        origin = _place_label(finger.tip_pixel, text_width, text_height, width, height, placed)
        if origin is None:
            continue
        labels.append((origin, text, finger.name, finger.hand, text_width, text_height))
    if not labels:
        return canvas
    _paint_labels(canvas, labels)
    return canvas


def _text_size(text: str) -> tuple[int, int] | None:
    font = _load_font()
    if font is None:
        (width, height), _baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        return width, height
    box = font.getbbox(text)
    return box[2] - box[0], box[3] - box[1]


def _place_label(tip, text_width, text_height, width, height, placed):
    box_width = text_width + 8
    box_height = text_height + 8
    x = min(max(tip[0] - box_width // 2, 0), max(width - box_width, 0))
    y = tip[1] - 12 - box_height
    if y < 0:
        y = min(tip[1] + 12, max(height - box_height, 0))
    for _step in range(6):
        rect = (x, y, box_width, box_height)
        if not any(_overlaps(rect, other) for other in placed):
            placed.append(rect)
            return x, y
        y -= box_height + 2
        if y < 0:
            y = min(tip[1] + 12, max(height - box_height, 0))
            x = min(x + box_width // 2, max(width - box_width, 0))
    return None


def _overlaps(first, second) -> bool:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _paint_labels(canvas, labels) -> None:
    font = _load_font()
    if font is None:
        for (x, y), text, name, hand, text_width, text_height in labels:
            _paint_ascii(canvas, x, y, text, name, hand, text_width, text_height)
        return
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb)
    draw = ImageDraw.Draw(image)
    for (x, y), text, name, hand, text_width, text_height in labels:
        hand_color = _rgb(_HAND_COLORS[hand])
        finger_color = _rgb(FINGER_COLORS[name])
        draw.rectangle(
            (x, y, x + text_width + 8, y + text_height + 8),
            fill=(20, 20, 24),
            outline=hand_color,
        )
        draw.text((x + 4, y + 2), text, font=font, fill=finger_color)
    canvas[:] = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def _paint_ascii(canvas, x, y, text, name, hand, text_width, text_height) -> None:
    cv2.rectangle(
        canvas,
        (x, y),
        (x + text_width + 8, y + text_height + 8),
        (20, 20, 24),
        -1,
    )
    cv2.rectangle(
        canvas,
        (x, y),
        (x + text_width + 8, y + text_height + 8),
        _HAND_COLORS[hand],
        1,
    )
    cv2.putText(
        canvas,
        text,
        (x + 4, y + text_height + 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        FINGER_COLORS[name],
        1,
        cv2.LINE_AA,
    )


def _rgb(bgr: tuple[int, int, int]) -> tuple[int, int, int]:
    blue, green, red = bgr
    return red, green, blue


def _load_font():
    global _FONT
    if _FONT is False:
        return None
    if _FONT is not None:
        return _FONT
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            _FONT = ImageFont.truetype(path, 14)
            return _FONT
    _FONT = False
    return None
