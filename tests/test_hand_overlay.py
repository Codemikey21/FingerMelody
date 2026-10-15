"""Pruebas del dibujo de manos sin MediaPipe."""

import numpy as np

from fingermelody.vision.hand_overlay import LEFT_COLOR, RIGHT_COLOR, draw_hands, mirror_selfie_frame
from fingermelody.vision.hand_tracker import TrackedHand


def test_mirror_moves_the_left_pixel_and_keeps_the_original():
    frame = np.zeros((2, 4, 3), dtype=np.uint8)
    frame[0, 0] = (1, 2, 3)

    mirrored = mirror_selfie_frame(frame)

    assert mirrored[0, -1].tolist() == [1, 2, 3]
    assert frame[0, 0].tolist() == [1, 2, 3]


def test_draw_hands_does_not_modify_the_source_frame():
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    hand = TrackedHand(
        label="Left",
        score=0.9,
        normalized=((0.5, 0.5, 0.0),),
        pixels=((20, 20),),
    )

    drawn = draw_hands(frame, (hand,))

    assert np.array_equal(frame, np.zeros((40, 40, 3), dtype=np.uint8))
    assert drawn[20, 20].tolist() != [0, 0, 0]
    assert drawn.shape == frame.shape


def test_draw_skips_points_outside_the_frame():
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    hand = TrackedHand(
        label=None,
        score=None,
        normalized=(),
        pixels=(None, (-4, 2), (100, 100)),
    )

    drawn = draw_hands(frame, (hand,))

    assert np.array_equal(drawn, frame)


def test_clustered_tips_keep_their_centers_and_the_image_has_no_labels():
    frame = np.zeros((90, 140, 3), dtype=np.uint8)
    pixels = tuple((28 + (index % 5) * 8, 36 + (index // 5) * 8) for index in range(21))
    left = TrackedHand("Left", 0.9, tuple((0.2, 0.2, 0.0) for _ in range(21)), pixels)
    right_pixels = tuple((x + 70, y) for x, y in pixels)
    right = TrackedHand("Right", 0.9, tuple((0.8, 0.2, 0.0) for _ in range(21)), right_pixels)

    drawn = draw_hands(frame, (left, right))

    for x, y in pixels:
        assert drawn[y, x].tolist() == list(LEFT_COLOR)
    for x, y in right_pixels:
        assert drawn[y, x].tolist() == list(RIGHT_COLOR)
    assert drawn[8, 28].tolist() == [0, 0, 0]
