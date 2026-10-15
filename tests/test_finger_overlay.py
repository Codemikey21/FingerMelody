"""El aro de pulsación no tapa el círculo del landmark ni escribe texto."""

import numpy as np

from fingermelody.gestures.finger_overlay import draw_press_highlights
from fingermelody.gestures.gesture_engine import FingerGestureState
from fingermelody.vision.hand_overlay import LEFT_COLOR, draw_hands
from fingermelody.vision.hand_tracker import TrackedHand


def _press(hand: str, tip: tuple[int, int]) -> FingerGestureState:
    return FingerGestureState(
        f"{hand.upper()}_INDEX",
        hand,
        "index",
        "Índice",
        "PRESSED",
        "Pulsación",
        1,
        True,
        tip,
    )


def test_press_ring_leaves_the_landmark_center_visible():
    source = np.zeros((60, 60, 3), dtype=np.uint8)
    tip = (20, 24)
    hand = TrackedHand("Left", 0.9, ((0.3, 0.4, 0.0),), (tip,))
    drawn = draw_hands(source, (hand,))

    annotated = draw_press_highlights(drawn, (_press("Left", tip),))

    assert source.sum() == 0
    assert annotated[tip[1], tip[0]].tolist() == list(LEFT_COLOR)
    assert annotated.sum() > drawn.sum()


def test_press_highlight_skips_a_missing_tip_and_does_not_invent_a_point():
    source = np.zeros((40, 40, 3), dtype=np.uint8)
    state = _press("Right", (20, 20))
    hidden = FingerGestureState(
        "RIGHT_THUMB",
        "Right",
        "thumb",
        "Pulgar",
        "LOST",
        "Seguimiento perdido",
        0,
        False,
        None,
    )

    annotated = draw_press_highlights(source, (hidden, state))

    assert source.sum() == 0
    assert annotated[20, 20].tolist() == [0, 0, 0]
    assert annotated.sum() > 0
