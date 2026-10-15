"""Pruebas del Hand Landmarker sin cámara ni modelo real."""

from pathlib import Path

import numpy as np
import pytest

from fingermelody.vision.hand_tracker import (
    MIN_HANDEDNESS_SCORE,
    MIN_MODEL_BYTES,
    MODEL_INIT_MESSAGE,
    MODEL_INVALID_MESSAGE,
    BOTH_HANDS_MESSAGE,
    NO_HANDS_MESSAGE,
    UNCLASSIFIED_MESSAGE,
    HandFrame,
    HandTracker,
    HandTrackerError,
    MonotonicMilliseconds,
    anatomical_label,
    normalized_to_pixel,
    to_view_state,
    validate_model_file,
)


class FakeCategory:
    def __init__(self, name, score):
        self.category_name = name
        self.score = score


class FakePoint:
    def __init__(self, x, y, z=0.0):
        self.x = x
        self.y = y
        self.z = z


class FakeResult:
    def __init__(self, handedness, landmarks):
        self.handedness = handedness
        self.hand_landmarks = landmarks


class FakeLandmarker:
    def __init__(self):
        self.closed = False
        self.calls = []
        self.result = FakeResult([], [])
        self.error = None

    def detect_for_video(self, image, timestamp_ms):
        if self.error is not None:
            raise self.error
        self.calls.append((image, timestamp_ms))
        return self.result

    def close(self):
        self.closed = True
        raise RuntimeError("fallo de cierre")


def write_model(path: Path, valid: bool = True) -> None:
    if valid:
        path.write_bytes(b"\x00\x00PK\x03\x04" + b"x" * MIN_MODEL_BYTES)
    else:
        path.write_bytes(b"not-a-model")


def hand_points(x=0.5, y=0.25):
    return [FakePoint(x, y, 0.1) for _ in range(21)]


def test_missing_and_invalid_model_are_rejected(tmp_path):
    missing = tmp_path / "hand_landmarker.task"
    with pytest.raises(HandTrackerError, match="No se encontró el modelo"):
        validate_model_file(missing)

    invalid = tmp_path / "bad.task"
    write_model(invalid, valid=False)
    with pytest.raises(HandTrackerError, match=MODEL_INVALID_MESSAGE):
        validate_model_file(invalid)

    short = tmp_path / "short.task"
    short.write_bytes(b"PK\x03\x04short")
    with pytest.raises(HandTrackerError, match=MODEL_INVALID_MESSAGE):
        HandTracker(short).open()


def test_open_configures_video_mode_for_two_hands(tmp_path):
    model = tmp_path / "hand_landmarker.task"
    write_model(model)
    created = {}

    def create(options):
        created["options"] = options
        return FakeLandmarker()

    tracker = HandTracker(model, landmarker_factory=create)

    tracker.open()

    assert tracker.num_hands == 2
    assert created["options"].num_hands == 2
    assert created["options"].running_mode.name == "VIDEO"
    assert tracker.is_open is True


def test_initialization_error_does_not_keep_the_detector(tmp_path):
    model = tmp_path / "hand_landmarker.task"
    write_model(model)

    def create(options):
        raise RuntimeError("modelo dañado")

    tracker = HandTracker(model, landmarker_factory=create)

    with pytest.raises(HandTrackerError, match=MODEL_INIT_MESSAGE):
        tracker.open()

    assert tracker.is_open is False


def test_timestamps_are_strictly_increasing():
    values = iter([10, 10, 11, 9])
    clock = MonotonicMilliseconds(lambda: next(values))

    assert [clock.next_ms() for _ in range(4)] == [10, 11, 12, 13]


def test_detect_without_hands_and_advances_timestamps(tmp_path):
    model = tmp_path / "hand_landmarker.task"
    write_model(model)
    landmarker = FakeLandmarker()
    clock = MonotonicMilliseconds(lambda: 5)
    tracker = HandTracker(
        model,
        clock=clock,
        image_factory=lambda rgb: rgb,
        landmarker_factory=lambda options: landmarker,
    )
    tracker.open()
    frame = np.zeros((48, 64, 3), dtype=np.uint8)

    first = tracker.detect(frame)
    second = tracker.detect(frame)

    assert first.hands == ()
    assert to_view_state(first).message == NO_HANDS_MESSAGE
    assert [call[1] for call in landmarker.calls] == [5, 6]
    assert second.hands == ()


def test_one_hand_converts_coordinates_and_ignores_low_confidence(tmp_path):
    model = tmp_path / "hand_landmarker.task"
    write_model(model)
    landmarker = FakeLandmarker()
    landmarker.result = FakeResult(
        [[FakeCategory("Left", MIN_HANDEDNESS_SCORE - 0.1)]],
        [hand_points(0.0, 1.0)],
    )
    tracker = HandTracker(
        model,
        image_factory=lambda rgb: rgb,
        landmarker_factory=lambda options: landmarker,
    )
    tracker.open()

    detected = tracker.detect(np.zeros((11, 21, 3), dtype=np.uint8))

    assert len(detected.hands) == 1
    hand = detected.hands[0]
    assert hand.label is None
    assert hand.score == pytest.approx(0.4)
    assert hand.pixels[0] == (0, 10)
    assert len(hand.normalized) == 21
    view = to_view_state(detected)
    assert view.hand_count == 1
    assert view.left_present is False
    assert view.right_present is False
    assert view.message == UNCLASSIFIED_MESSAGE


def test_two_hands_keep_model_labels(tmp_path):
    model = tmp_path / "hand_landmarker.task"
    write_model(model)
    landmarker = FakeLandmarker()
    landmarker.result = FakeResult(
        [[FakeCategory("Right", 0.91)], [FakeCategory("Left", 0.87)]],
        [hand_points(0.2, 0.3), hand_points(0.8, 0.4)],
    )
    tracker = HandTracker(
        model,
        image_factory=lambda rgb: rgb,
        landmarker_factory=lambda options: landmarker,
        mirrored_input=False,
    )
    tracker.open()

    detected = tracker.detect(np.zeros((20, 30, 3), dtype=np.uint8))
    view = to_view_state(detected)

    assert [hand.label for hand in detected.hands] == ["Right", "Left"]
    assert detected.hands[0].pixels[0] == normalized_to_pixel(0.2, 0.3, 30, 20)
    assert view.both_present is True
    assert view.hand_count == 2
    assert view.message == BOTH_HANDS_MESSAGE


@pytest.mark.parametrize(
    ("model_label", "mirrored", "expected"),
    [
        ("Left", False, "Left"),
        ("Right", False, "Right"),
        ("Left", True, "Right"),
        ("Right", True, "Left"),
        (None, False, None),
        (None, True, None),
    ],
)
def test_anatomical_label_swaps_only_a_mirrored_frame(model_label, mirrored, expected):
    assert anatomical_label(model_label, mirrored=mirrored) == expected


def test_mirrored_frame_reports_the_users_hands_without_moving_landmarks(tmp_path):
    model = tmp_path / "hand_landmarker.task"
    write_model(model)
    landmarker = FakeLandmarker()
    landmarker.result = FakeResult(
        [[FakeCategory("Left", 0.93)], [FakeCategory("Right", 0.9)]],
        [hand_points(0.2, 0.3), hand_points(0.8, 0.4)],
    )
    tracker = HandTracker(
        model,
        image_factory=lambda rgb: rgb,
        landmarker_factory=lambda options: landmarker,
        mirrored_input=True,
    )
    tracker.open()
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    frame[0, 0] = (10, 20, 30)

    detected = tracker.detect(frame)
    view = to_view_state(detected)

    assert [hand.label for hand in detected.hands] == ["Right", "Left"]
    assert detected.hands[0].pixels[0] == normalized_to_pixel(0.2, 0.3, 30, 20)
    assert detected.hands[1].pixels[0] == normalized_to_pixel(0.8, 0.4, 30, 20)
    assert landmarker.calls[0][0][0, 0].tolist() == [30, 20, 10]
    assert view.left_present is True
    assert view.right_present is True
    assert view.both_present is True
    assert view.message == BOTH_HANDS_MESSAGE


def test_mirror_does_not_label_a_low_confidence_hand(tmp_path):
    model = tmp_path / "hand_landmarker.task"
    write_model(model)
    landmarker = FakeLandmarker()
    landmarker.result = FakeResult(
        [[FakeCategory("Left", MIN_HANDEDNESS_SCORE - 0.1)]],
        [hand_points(0.25, 0.25)],
    )
    tracker = HandTracker(
        model,
        image_factory=lambda rgb: rgb,
        landmarker_factory=lambda options: landmarker,
        mirrored_input=True,
    )
    tracker.open()

    detected = tracker.detect(np.zeros((20, 30, 3), dtype=np.uint8))

    assert detected.hands[0].label is None
    assert to_view_state(detected).message == UNCLASSIFIED_MESSAGE


def test_normalized_coordinates_and_invalid_frame(tmp_path):
    assert normalized_to_pixel(0.0, 0.0, 640, 480) == (0, 0)
    assert normalized_to_pixel(1.0, 1.0, 640, 480) == (639, 479)
    assert normalized_to_pixel(0.5, 0.5, 640, 480) == (320, 240)
    assert normalized_to_pixel(1.4, 0.2, 640, 480) is None

    model = tmp_path / "hand_landmarker.task"
    write_model(model)
    tracker = HandTracker(
        model,
        image_factory=lambda rgb: rgb,
        landmarker_factory=lambda options: FakeLandmarker(),
    )
    tracker.open()
    with pytest.raises(HandTrackerError, match="fotograma"):
        tracker.detect(np.zeros((10, 10), dtype=np.uint8))


def test_close_is_safe_when_the_detector_fails_to_close(tmp_path):
    model = tmp_path / "hand_landmarker.task"
    write_model(model)
    landmarker = FakeLandmarker()
    tracker = HandTracker(model, landmarker_factory=lambda options: landmarker)
    tracker.open()

    tracker.close()
    tracker.close()

    assert landmarker.closed is True
    assert tracker.is_open is False


def test_detect_error_is_reported_without_dropping_the_clock(tmp_path):
    model = tmp_path / "hand_landmarker.task"
    write_model(model)
    landmarker = FakeLandmarker()
    landmarker.error = RuntimeError("fallo puntual")
    tracker = HandTracker(
        model,
        clock=MonotonicMilliseconds(lambda: 1),
        image_factory=lambda rgb: rgb,
        landmarker_factory=lambda options: landmarker,
    )
    tracker.open()
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    with pytest.raises(HandTrackerError, match="No se pudo reconocer"):
        tracker.detect(frame)
    landmarker.error = None
    detected = tracker.detect(frame)

    assert isinstance(detected, HandFrame)
    assert [call[1] for call in landmarker.calls] == [2]
