"""Identidad de los dedos con landmarks sintéticos, sin cámara ni modelo."""

from fingermelody.gestures.finger_detector import (
    PRESS_NOT_EVALUATED,
    STATUS_ABSENT,
    STATUS_DETECTED,
    STATUS_UNTRACKED,
    FINGER_SPECS,
    FingerDetector,
    TrackedFinger,
)
from fingermelody.vision.hand_tracker import HandFrame, TrackedHand

LEFT_IDS = (
    "LEFT_THUMB",
    "LEFT_INDEX",
    "LEFT_MIDDLE",
    "LEFT_RING",
    "LEFT_PINKY",
)
RIGHT_IDS = (
    "RIGHT_THUMB",
    "RIGHT_INDEX",
    "RIGHT_MIDDLE",
    "RIGHT_RING",
    "RIGHT_PINKY",
)
DISPLAY_NAMES = ("Pulgar", "Índice", "Medio", "Anular", "Meñique")
OFFICIAL_INDICES = (
    (1, 2, 3, 4),
    (5, 6, 7, 8),
    (9, 10, 11, 12),
    (13, 14, 15, 16),
    (17, 18, 19, 20),
)


def make_hand(label: str, *, count: int = 21, x: float = 0.2, clear_pixels=()):
    normalized = tuple((x, 0.2 + index * 0.01, 0.0) for index in range(count))
    pixels = [(20 + index, 30 + index) for index in range(count)]
    for index in clear_pixels:
        if index < len(pixels):
            pixels[index] = None
    return TrackedHand(label, 0.95, normalized, tuple(pixels))


def frame_of(*hands: TrackedHand) -> HandFrame:
    return HandFrame(hands=hands, width=640, height=480)


def test_left_hand_has_five_anatomical_fingers():
    observed = FingerDetector().identify(frame_of(make_hand("Left", x=0.8)))
    left = [finger for finger in observed.fingers if finger.hand == "Left"]

    assert [finger.finger_id for finger in left] == list(LEFT_IDS)
    assert [finger.display_name for finger in left] == list(DISPLAY_NAMES)
    assert [finger.indices for finger in left] == list(OFFICIAL_INDICES)
    assert [finger.tracked for finger in left] == [True, True, True, True, True]
    assert [line.status for line in observed.panel.right_lines] == [STATUS_ABSENT] * 5
    assert observed.fingers[-1].finger_id == "LEFT_PINKY"


def test_right_hand_has_five_anatomical_fingers():
    observed = FingerDetector().identify(frame_of(make_hand("Right", x=0.1)))
    right = observed.fingers

    assert [finger.finger_id for finger in right] == list(RIGHT_IDS)
    assert [finger.indices for finger in right] == list(OFFICIAL_INDICES)
    assert [line.status for line in observed.panel.left_lines] == [STATUS_ABSENT] * 5
    assert all(line.status == STATUS_DETECTED for line in observed.panel.right_lines)


def test_both_hands_identify_ten_fingers_and_reserve_future_fields():
    observed = FingerDetector().identify(
        frame_of(make_hand("Left", x=0.2), make_hand("Right", x=0.7))
    )

    assert [finger.finger_id for finger in observed.fingers] == list(LEFT_IDS + RIGHT_IDS)
    assert all(line.status == STATUS_DETECTED for line in observed.panel.left_lines)
    assert all(line.status == STATUS_DETECTED for line in observed.panel.right_lines)
    sample = observed.fingers[0]
    assert isinstance(sample, TrackedFinger)
    assert sample.note is None
    assert sample.press_state == PRESS_NOT_EVALUATED
    assert sample.movement_history == ()
    assert sample.activation is None
    assert sample.joints[0].role == "CMC"
    assert sample.joints[-1].role == "TIP"
    assert sample.tip_pixel == sample.joints[-1].pixel


def test_official_joint_roles_match_each_finger():
    observed = FingerDetector().identify(frame_of(make_hand("Left")))
    expected_roles = {
        "thumb": ("CMC", "MCP", "IP", "TIP"),
        "index": ("MCP", "PIP", "DIP", "TIP"),
        "middle": ("MCP", "PIP", "DIP", "TIP"),
        "ring": ("MCP", "PIP", "DIP", "TIP"),
        "pinky": ("MCP", "PIP", "DIP", "TIP"),
    }

    for finger, spec in zip(observed.fingers, FINGER_SPECS, strict=True):
        assert [joint.role for joint in finger.joints] == list(expected_roles[spec.name])
        assert [joint.index for joint in finger.joints] == list(spec.indices)


def test_hand_order_and_screen_side_do_not_change_identity():
    left_on_the_right = make_hand("Left", x=0.92)
    right_on_the_left = make_hand("Right", x=0.05)
    detector = FingerDetector()

    first = detector.identify(frame_of(left_on_the_right, right_on_the_left))
    second = detector.identify(frame_of(right_on_the_left, left_on_the_right))

    assert [finger.finger_id for finger in first.fingers] == list(LEFT_IDS + RIGHT_IDS)
    assert [finger.finger_id for finger in second.fingers] == [finger.finger_id for finger in first.fingers]
    assert first.fingers[0].hand == "Left"
    assert first.fingers[0].tip_normalized[0] == 0.92
    assert first.fingers[5].hand == "Right"
    assert first.fingers[5].tip_normalized[0] == 0.05


def test_missing_hand_drops_its_fingers_and_keeps_the_other():
    detector = FingerDetector()
    both = detector.identify(frame_of(make_hand("Left"), make_hand("Right")))
    only_left = detector.identify(frame_of(make_hand("Left", x=0.33)))

    assert [finger.finger_id for finger in both.fingers] == list(LEFT_IDS + RIGHT_IDS)
    assert [finger.finger_id for finger in only_left.fingers] == list(LEFT_IDS)
    assert [line.status for line in only_left.panel.right_lines] == [STATUS_ABSENT] * 5
    assert only_left.fingers[1].tip_normalized[0] == 0.33


def test_no_hands_and_unclassified_hand_leave_both_sides_absent():
    detector = FingerDetector()
    empty = detector.identify(HandFrame(hands=(), width=640, height=480))
    unlabeled = detector.identify(frame_of(make_hand(None)))

    assert empty.fingers == ()
    assert unlabeled.fingers == ()
    assert [line.status for line in empty.panel.left_lines] == [STATUS_ABSENT] * 5
    assert [line.status for line in unlabeled.panel.right_lines] == [STATUS_ABSENT] * 5


def test_incomplete_or_invalid_landmarks_are_not_tracked():
    short = make_hand("Left", count=10)
    broken = make_hand("Right", clear_pixels=(8,))
    broken_norm = TrackedHand(
        "Left",
        0.9,
        tuple((float("nan"), 0.2, 0.0) if index == 4 else (0.2, 0.2, 0.0) for index in range(21)),
        tuple((10, 10) for _ in range(21)),
    )
    detector = FingerDetector()

    left = detector.identify(frame_of(short))
    right = detector.identify(frame_of(broken))
    invalid = detector.identify(frame_of(broken_norm))

    assert [finger.tracked for finger in left.fingers] == [True, True, False, False, False]
    assert [line.status for line in left.panel.left_lines] == [
        STATUS_DETECTED,
        STATUS_DETECTED,
        STATUS_UNTRACKED,
        STATUS_UNTRACKED,
        STATUS_UNTRACKED,
    ]
    assert right.fingers[1].finger_id == "RIGHT_INDEX"
    assert right.fingers[1].tracked is False
    assert right.panel.right_lines[1].status == STATUS_UNTRACKED
    assert right.fingers[0].tracked is True
    assert invalid.fingers[0].finger_id == "LEFT_THUMB"
    assert invalid.fingers[0].tracked is False
    assert invalid.fingers[1].tracked is True
