"""Transiciones de pulsación con landmarks sintéticos, sin cámara ni modelo."""

import numpy as np
import pytest

from fingermelody.gestures.finger_detector import FINGER_SPECS, FingerJoint, TrackedFinger, finger_id
from fingermelody.gestures.gesture_engine import (
    PHASE_HELD,
    PHASE_LOST,
    PHASE_PRESSED,
    PHASE_READY,
    PHASE_RELEASED,
    VISUAL_HELD,
    VISUAL_LOST,
    VISUAL_PRESS,
    VISUAL_REST,
    FingerPressEvent,
    GestureConfig,
    GestureEngine,
    finger_curl,
)

FAST = dict(
    smooth_alpha=1.0,
    press_frames=2,
    release_frames=2,
    rest_frames=2,
    cooldown_ms=0,
    highlight_ms=0,
    press_ms=0,
    release_ms=0,
    rest_ms=0,
)


def chain(roles, bend_role, angle_deg):
    position = np.zeros(3)
    direction = np.array([1.0, 0.0, 0.0])
    coords = {}
    for index, role in enumerate(roles):
        if index == 0:
            coords[role] = (0.0, 0.0, 0.0)
            continue
        if roles[index - 1] == bend_role:
            delta = np.deg2rad(180.0 - angle_deg)
            cosine, sine = np.cos(delta), np.sin(delta)
            x, y = direction[0], direction[1]
            direction = np.array([cosine * x - sine * y, sine * x + cosine * y, 0.0])
        position = position + direction
        coords[role] = tuple(float(value) for value in position)
    return coords


def rigid(coords, degrees, shift):
    radians = np.deg2rad(degrees)
    rotation = np.array(
        [
            [np.cos(radians), -np.sin(radians), 0.0],
            [np.sin(radians), np.cos(radians), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    offset = np.array(shift, dtype=float)
    return {
        role: tuple(float(value) for value in (rotation @ np.array(point) + offset))
        for role, point in coords.items()
    }


def finger(hand, name, angle, bend=None, tracked=True, drop_role=None, rotation=0.0, shift=(0.0, 0.0, 0.0)):
    spec = next(item for item in FINGER_SPECS if item.name == name)
    bend_role = bend or ("IP" if name == "thumb" else "PIP")
    coords = rigid(chain([role for _, role in spec.joints], bend_role, angle), rotation, shift)
    joints = []
    for index, role in spec.joints:
        if not tracked or role == drop_role:
            normalized = None
            pixel = None
        else:
            normalized = coords[role]
            pixel = (int(round(normalized[0] * 20 + 30)), int(round(normalized[1] * 20 + 30)))
        joints.append(FingerJoint(index, role, normalized, pixel))
    tip = joints[-1]
    usable = tracked and drop_role is None
    return TrackedFinger(
        finger_id=finger_id(hand, spec),
        hand=hand,
        name=spec.name,
        display_name=spec.display_name,
        indices=spec.indices,
        joints=tuple(joints),
        tip_normalized=tip.normalized,
        tip_pixel=tip.pixel if usable else None,
        tracked=usable,
    )


def engine(**overrides):
    values = dict(FAST)
    values.update(overrides)
    return GestureEngine(GestureConfig(**values))


def state_of(update, finger_id_):
    return next(state for state in update.states if state.finger_id == finger_id_)


def repeat(motor, sample, start, count):
    update = None
    for step in range(count):
        update = motor.update(sample, start + step)
    return update


def test_extended_finger_stays_at_rest_and_measure_ignores_translation():
    straight = finger("Left", "index", 180)
    moved = finger("Left", "index", 180, rotation=75, shift=(5.0, -2.0, 0.4))
    original = finger_curl(straight)
    transformed = finger_curl(moved)

    assert original.angle == pytest.approx(180.0, abs=1e-4)
    assert original.extension == pytest.approx(1.0, abs=1e-4)
    assert transformed.angle == pytest.approx(original.angle, abs=1e-4)
    assert transformed.extension == pytest.approx(original.extension, abs=1e-4)

    motor = engine()
    armed = repeat(motor, [straight], 0, 2)
    shifted = motor.update([moved], 10)

    assert state_of(armed, "LEFT_INDEX").phase == PHASE_READY
    assert state_of(armed, "LEFT_INDEX").visual == VISUAL_REST
    assert armed.events == ()
    assert shifted.events == ()
    assert state_of(shifted, "LEFT_INDEX").press_count == 0


def test_flexed_finger_enters_pressed_once_and_then_held():
    seen = []
    motor = engine()
    motor.subscribe(seen.append)
    repeat(motor, [finger("Left", "index", 180)], 0, 2)
    first = motor.update([finger("Left", "index", 70)], 10)
    pressed = motor.update([finger("Left", "index", 70)], 11)
    held_events = []
    for step in range(4):
        held = motor.update([finger("Left", "index", 70)], 12 + step)
        held_events.extend(held.events)

    assert finger_curl(finger("Left", "index", 70)).angle == pytest.approx(70.0, abs=1.0)
    assert state_of(first, "LEFT_INDEX").phase == PHASE_READY
    assert first.events == ()
    assert state_of(pressed, "LEFT_INDEX").phase == PHASE_PRESSED
    assert state_of(pressed, "LEFT_INDEX").visual == VISUAL_PRESS
    assert pressed.events == (FingerPressEvent("LEFT_INDEX", 11),)
    assert seen == [FingerPressEvent("LEFT_INDEX", 11)]
    assert held_events == []
    assert state_of(held, "LEFT_INDEX").phase == PHASE_HELD
    assert state_of(held, "LEFT_INDEX").visual == VISUAL_HELD
    assert state_of(held, "LEFT_INDEX").press_count == 1


def test_release_allows_a_later_press_of_the_same_finger():
    motor = engine()
    sample = [finger("Left", "middle", 180)]
    repeat(motor, sample, 0, 2)
    repeat(motor, [finger("Left", "middle", 60)], 10, 3)
    released = repeat(motor, sample, 20, 2)
    ready = motor.update(sample, 30)
    again = repeat(motor, [finger("Left", "middle", 60)], 40, 2)

    assert state_of(released, "LEFT_MIDDLE").phase == PHASE_RELEASED
    assert released.events == ()
    assert state_of(ready, "LEFT_MIDDLE").phase == PHASE_READY
    assert again.events == (FingerPressEvent("LEFT_MIDDLE", 41),)
    assert state_of(again, "LEFT_MIDDLE").press_count == 2


def test_values_near_the_threshold_do_not_flutter():
    motor = engine()
    repeat(motor, [finger("Left", "ring", 180)], 0, 2)
    events = []
    current = None
    for step, angle in enumerate((135, 140, 132, 145, 138, 136)):
        current = motor.update([finger("Left", "ring", angle)], 20 + step)
        events.extend(current.events)

    assert events == []
    assert state_of(current, "LEFT_RING").phase == PHASE_READY


def test_smoothing_blocks_a_single_sharp_bend():
    motor = engine(smooth_alpha=0.25, press_frames=1, rest_frames=1)
    motor.update([finger("Left", "index", 180)], 0)
    sudden = motor.update([finger("Left", "index", 60)], 1)

    assert sudden.events == ()
    assert state_of(sudden, "LEFT_INDEX").phase == PHASE_READY


def test_different_fingers_and_hands_press_independently():
    motor = engine()
    rest = [
        finger("Left", "index", 180),
        finger("Left", "pinky", 180),
        finger("Right", "index", 180, shift=(3.0, 1.0, 0.0)),
    ]
    repeat(motor, rest, 0, 2)
    flexed = [
        finger("Right", "index", 180, shift=(3.0, 1.0, 0.0)),
        finger("Left", "pinky", 65),
        finger("Left", "index", 65),
    ]
    pressed = repeat(motor, flexed, 10, 2)

    assert {event.finger_id for event in pressed.events} == {"LEFT_INDEX", "LEFT_PINKY"}
    assert state_of(pressed, "RIGHT_INDEX").phase == PHASE_READY
    assert state_of(pressed, "RIGHT_INDEX").press_count == 0
    assert state_of(pressed, "LEFT_INDEX").press_count == 1
    assert state_of(pressed, "LEFT_PINKY").press_count == 1


def test_lost_tracking_is_not_a_release_and_reappearance_needs_rest():
    motor = engine()
    repeat(motor, [finger("Right", "thumb", 180)], 0, 2)
    repeat(motor, [finger("Right", "thumb", 70)], 10, 3)
    lost = motor.update([], 20)
    still_down = repeat(motor, [finger("Right", "thumb", 70)], 30, 3)
    armed = repeat(motor, [finger("Right", "thumb", 180)], 40, 2)
    pressed = repeat(motor, [finger("Right", "thumb", 70)], 50, 2)

    assert state_of(lost, "RIGHT_THUMB").phase == PHASE_LOST
    assert state_of(lost, "RIGHT_THUMB").visual == VISUAL_LOST
    assert lost.events == ()
    assert state_of(lost, "RIGHT_THUMB").press_count == 1
    assert state_of(lost, "LEFT_INDEX").phase == PHASE_LOST
    assert still_down.events == ()
    assert state_of(still_down, "RIGHT_THUMB").phase == PHASE_LOST
    assert state_of(armed, "RIGHT_THUMB").phase == PHASE_READY
    assert pressed.events == (FingerPressEvent("RIGHT_THUMB", 51),)


def test_incomplete_landmarks_suspend_the_finger():
    motor = engine()
    whole = finger("Left", "index", 180)
    repeat(motor, [whole], 0, 2)
    missing = motor.update([finger("Left", "index", 70, drop_role="PIP")], 10)
    untracked = motor.update([finger("Left", "index", 70, tracked=False)], 11)

    assert missing.events == ()
    assert state_of(missing, "LEFT_INDEX").phase == PHASE_LOST
    assert untracked.events == ()
    assert state_of(untracked, "LEFT_INDEX").phase == PHASE_LOST


def test_thumb_uses_its_own_joints_and_thresholds():
    index_curl = finger_curl(finger("Left", "index", 120))
    thumb_ip = finger_curl(finger("Left", "thumb", 120, bend="IP"))
    thumb_mcp = finger_curl(finger("Left", "thumb", 80, bend="MCP"))

    assert index_curl.angle == pytest.approx(120.0, abs=1.0)
    assert thumb_ip.angle == pytest.approx(120.0, abs=1.0)
    assert thumb_mcp.angle == pytest.approx(80.0, abs=1.0)

    index_motor = engine()
    repeat(index_motor, [finger("Left", "index", 180)], 0, 2)
    index_held = repeat(index_motor, [finger("Left", "index", 140)], 10, 3)
    assert index_held.events == ()
    assert state_of(index_held, "LEFT_INDEX").phase == PHASE_READY

    thumb_motor = engine()
    repeat(thumb_motor, [finger("Left", "thumb", 180)], 0, 2)
    from_ip = repeat(thumb_motor, [finger("Left", "thumb", 120, bend="IP")], 10, 2)
    assert from_ip.events == (FingerPressEvent("LEFT_THUMB", 11),)

    other = engine()
    repeat(other, [finger("Right", "thumb", 180)], 0, 2)
    from_mcp = repeat(other, [finger("Right", "thumb", 80, bend="MCP")], 10, 2)
    assert from_mcp.events == (FingerPressEvent("RIGHT_THUMB", 11),)


def test_cooldown_follows_each_finger_clock_and_ignores_time_going_backwards():
    motor = engine(cooldown_ms=200)
    repeat(motor, [finger("Left", "index", 180)], 0, 2)
    first = []
    for step in range(3):
        first.extend(motor.update([finger("Left", "index", 60)], 100 + step).events)
    repeat(motor, [finger("Left", "index", 180)], 200, 3)
    early = repeat(motor, [finger("Left", "index", 60)], 250, 2)
    ignored = motor.update([finger("Left", "index", 60)], 100)
    late = []
    for step in range(2):
        late.extend(motor.update([finger("Left", "index", 60)], 500 + step).events)

    assert first == [FingerPressEvent("LEFT_INDEX", 101)]
    assert early.events == ()
    assert state_of(early, "LEFT_INDEX").press_count == 1
    assert ignored.events == ()
    assert state_of(ignored, "LEFT_INDEX").phase == state_of(early, "LEFT_INDEX").phase
    assert late == [FingerPressEvent("LEFT_INDEX", 500)]


def test_rotated_flexed_hand_still_presses_and_straight_hand_does_not():
    bent = finger("Left", "ring", 70)
    turned = finger("Left", "ring", 70, rotation=130, shift=(-4.0, 6.0, 1.0))
    assert finger_curl(turned).angle == pytest.approx(finger_curl(bent).angle, abs=1e-3)
    assert finger_curl(turned).extension == pytest.approx(finger_curl(bent).extension, abs=1e-3)

    motor = engine()
    repeat(motor, [finger("Left", "ring", 180, rotation=40, shift=(2.0, 2.0, 0.0))], 0, 2)
    pressed = repeat(motor, [turned], 10, 2)

    assert pressed.events == (FingerPressEvent("LEFT_RING", 11),)
    assert state_of(pressed, "LEFT_RING").phase == PHASE_PRESSED


def test_clear_press_counts_keeps_the_phase():
    motor = engine(highlight_ms=200)
    repeat(motor, [finger("Left", "index", 180)], 0, 2)
    held = repeat(motor, [finger("Left", "index", 60)], 10, 3)
    assert state_of(held, "LEFT_INDEX").press_count == 1
    assert state_of(held, "LEFT_INDEX").phase == PHASE_HELD

    motor.clear_press_counts()
    later = motor.update([finger("Left", "index", 60)], 13)
    state = state_of(later, "LEFT_INDEX")

    assert state.press_count == 0
    assert state.highlight is False
    assert state.phase == PHASE_HELD
    assert later.events == ()
