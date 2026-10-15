"""Comprueba que los nombres se dibujan junto a la punta, sin alterar el fotograma."""

import numpy as np

from fingermelody.gestures.finger_detector import FingerDetector
from fingermelody.gestures.finger_overlay import draw_finger_labels
from fingermelody.vision.hand_tracker import HandFrame, TrackedHand


def _hand(label: str) -> TrackedHand:
    pixels = tuple((40 + index * 8, 80) for index in range(21))
    normalized = tuple((0.2, 0.2, 0.0) for _ in range(21))
    return TrackedHand(label, 0.9, normalized, pixels)


def test_labels_are_drawn_on_a_copy_near_the_fingertip():
    source = np.zeros((120, 200, 3), dtype=np.uint8)
    observed = FingerDetector().identify(HandFrame(hands=(_hand("Left"),), width=200, height=120))

    annotated = draw_finger_labels(source, observed.fingers)

    assert source.sum() == 0
    assert annotated.sum() > 0
    assert annotated[80, 40].sum() == 0


def test_untracked_fingers_are_not_drawn():
    source = np.zeros((80, 80, 3), dtype=np.uint8)
    hand = TrackedHand(
        "Right",
        0.9,
        tuple((0.5, 0.5, 0.0) for _ in range(4)),
        tuple((10, 10) for _ in range(4)),
    )
    observed = FingerDetector().identify(HandFrame(hands=(hand,), width=80, height=80))

    annotated = draw_finger_labels(source, observed.fingers)

    assert observed.fingers
    assert all(finger.tracked is False for finger in observed.fingers)
    assert annotated.sum() == 0
