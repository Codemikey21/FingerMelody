"""Pulgar, asociación de notas y confirmación por tiempo, sin cámara."""

from fingermelody.gestures.finger_detector import FingerJoint, FingerSpec, TrackedFinger, finger_id
from fingermelody.gestures.gesture_engine import (
    PHASE_HELD,
    PHASE_LOST,
    PHASE_READY,
    FingerPressEvent,
    GestureEngine,
    finger_curl,
)
from fingermelody.music.note_mapper import DEFAULT_FINGER_NOTES, NoteMapper

THUMB = FingerSpec("thumb", "Pulgar", "THUMB", ((1, "CMC"), (2, "MCP"), (3, "IP"), (4, "TIP")))
WRIST = (0.0, 0.0, 0.0)
INDEX_MCP = (0.35, 0.85, 0.0)
MIDDLE_MCP = (0.0, 1.0, 0.0)
ANCHORS = (WRIST, INDEX_MCP, MIDDLE_MCP)
OPEN_JOINTS = {
    "CMC": (0.20, 0.22, 0.04),
    "MCP": (0.55, 0.32, 0.06),
    "IP": (0.78, 0.22, 0.04),
    "TIP": (1.00, 0.10, 0.0),
}
OPPOSED_JOINTS = {
    "CMC": (0.18, 0.22, 0.04),
    "MCP": (0.38, 0.42, 0.05),
    "IP": (0.40, 0.64, 0.04),
    "TIP": (0.36, 0.84, 0.02),
}


def thumb(hand, joints, anchors=ANCHORS):
    built = []
    for index, role in THUMB.joints:
        point = tuple(float(value) for value in joints[role])
        built.append(FingerJoint(index, role, point, (20, 20)))
    tip = built[-1]
    spec = THUMB
    return TrackedFinger(
        finger_id=finger_id(hand, spec),
        hand=hand,
        name=spec.name,
        display_name=spec.display_name,
        indices=spec.indices,
        joints=tuple(built),
        tip_normalized=tip.normalized,
        tip_pixel=tip.pixel,
        tracked=True,
        anchors=tuple(tuple(point) for point in anchors),
    )


def shifted_tip(ratio):
    """Acerca toda la cadena al índice sin doblar las articulaciones."""
    tip = OPEN_JOINTS["TIP"]
    delta = tuple(tip[index] - INDEX_MCP[index] for index in range(3))
    length = sum(value * value for value in delta) ** 0.5
    desired = tuple(INDEX_MCP[index] + delta[index] / length * ratio for index in range(3))
    shift = tuple(desired[index] - tip[index] for index in range(3))
    return {
        role: tuple(point[index] + shift[index] for index in range(3))
        for role, point in OPEN_JOINTS.items()
    }


def arm(motor, sample, start=0):
    motor.update(sample, start)
    return motor.update(sample, start + 40)


def test_open_thumb_reaches_ready_and_opposition_presses_c4_and_a4():
    mapper = NoteMapper()
    assert mapper.note_name("LEFT_THUMB") == "C4"
    assert mapper.note_name("RIGHT_THUMB") == "A4"
    assert dict(DEFAULT_FINGER_NOTES)["LEFT_INDEX"] == "D4"
    assert dict(DEFAULT_FINGER_NOTES)["RIGHT_PINKY"] == "E5"

    open_curl = finger_curl(thumb("Left", OPEN_JOINTS))
    opposed_curl = finger_curl(thumb("Left", OPPOSED_JOINTS))
    assert open_curl.opposition > 0.9
    assert opposed_curl.opposition < 0.2
    assert opposed_curl.extension > 0.90

    left = GestureEngine()
    armed = arm(left, [thumb("Left", OPEN_JOINTS)])
    pressed = left.update([thumb("Left", OPPOSED_JOINTS)], 100)
    confirmed = left.update([thumb("Left", OPPOSED_JOINTS)], 140)

    assert armed.events == ()
    assert next(state.phase for state in armed.states if state.finger_id == "LEFT_THUMB") == PHASE_READY
    assert pressed.events == ()
    assert confirmed.events == (FingerPressEvent("LEFT_THUMB", 140),)
    assert mapper.note_name(confirmed.events[0].finger_id) == "C4"

    right = GestureEngine()
    arm(right, [thumb("Right", OPEN_JOINTS)])
    right.update([thumb("Right", OPPOSED_JOINTS)], 100)
    confirmed_right = right.update([thumb("Right", OPPOSED_JOINTS)], 140)
    assert confirmed_right.events == (FingerPressEvent("RIGHT_THUMB", 140),)
    assert mapper.note_name("RIGHT_THUMB") == "A4"


def test_thumb_states_repeat_after_release_and_ignore_a_small_motion():
    motor = GestureEngine()
    sample = [thumb("Left", OPEN_JOINTS)]
    arm(motor, sample)
    motor.update([thumb("Left", OPPOSED_JOINTS)], 100)
    pressed = motor.update([thumb("Left", OPPOSED_JOINTS)], 140)
    held = motor.update([thumb("Left", OPPOSED_JOINTS)], 180)
    motor.update(sample, 300)
    motor.update(sample, 340)
    released = motor.update(sample, 380)
    ready = motor.update(sample, 420)
    motor.update([thumb("Left", OPPOSED_JOINTS)], 560)
    again = motor.update([thumb("Left", OPPOSED_JOINTS)], 600)

    def phase(update):
        return next(state.phase for state in update.states if state.finger_id == "LEFT_THUMB")

    assert pressed.events == (FingerPressEvent("LEFT_THUMB", 140),)
    assert held.events == ()
    assert phase(held) == PHASE_HELD
    assert released.events == ()
    assert phase(ready) == PHASE_READY
    assert again.events == (FingerPressEvent("LEFT_THUMB", 600),)

    other = GestureEngine()
    arm(other, sample)
    mild = shifted_tip(0.75)
    assert finger_curl(thumb("Left", mild)).opposition > 0.7
    other.update([thumb("Left", mild)], 200)
    ignored = other.update([thumb("Left", mild)], 240)
    assert ignored.events == ()
    assert phase(ignored) == PHASE_READY


def test_thumb_loss_does_not_emit_and_other_fingers_stay_independent():
    from tests.test_gesture_engine import finger

    motor = GestureEngine()
    both = [thumb("Left", OPEN_JOINTS), finger("Left", "index", 172)]
    arm(motor, both)
    lost = motor.update([finger("Left", "index", 172)], 100)
    still = motor.update([thumb("Left", OPPOSED_JOINTS)], 140)
    motor.update(both, 300)
    motor.update(both, 340)
    armed = motor.update(both, 380)
    motor.update([thumb("Left", OPPOSED_JOINTS), finger("Left", "index", 172)], 450)
    pressed = motor.update([thumb("Left", OPPOSED_JOINTS), finger("Left", "index", 110)], 490)

    def phase(update, finger_id_):
        return next(state.phase for state in update.states if state.finger_id == finger_id_)

    assert lost.events == ()
    assert phase(lost, "LEFT_THUMB") == PHASE_LOST
    assert still.events == ()
    assert phase(still, "LEFT_THUMB") == PHASE_LOST
    assert phase(armed, "LEFT_THUMB") == PHASE_READY
    assert {event.finger_id for event in pressed.events} == {"LEFT_THUMB"}
    assert phase(pressed, "LEFT_INDEX") == PHASE_READY


def test_two_thumbs_press_together_and_frame_spacing_uses_monotonic_time():
    motor = GestureEngine()
    arm(motor, [thumb("Left", OPEN_JOINTS), thumb("Right", OPEN_JOINTS)])
    motor.update([thumb("Left", OPPOSED_JOINTS), thumb("Right", OPPOSED_JOINTS)], 100)
    pressed = motor.update([thumb("Left", OPPOSED_JOINTS), thumb("Right", OPPOSED_JOINTS)], 140)
    assert {event.finger_id for event in pressed.events} == {"LEFT_THUMB", "RIGHT_THUMB"}

    paced = GestureEngine()
    arm(paced, [thumb("Left", OPEN_JOINTS)])
    early = paced.update([thumb("Left", OPPOSED_JOINTS)], 100)
    too_soon = paced.update([thumb("Left", OPPOSED_JOINTS)], 110)
    later = paced.update([thumb("Left", OPPOSED_JOINTS)], 130)
    assert early.events == ()
    assert too_soon.events == ()
    assert later.events == (FingerPressEvent("LEFT_THUMB", 130),)

    wide = GestureEngine()
    wide.update([thumb("Left", OPEN_JOINTS)], 0)
    ready = wide.update([thumb("Left", OPEN_JOINTS)], 80)
    wide.update([thumb("Left", OPPOSED_JOINTS)], 200)
    fired = wide.update([thumb("Left", OPPOSED_JOINTS)], 280)
    assert ready.events == ()
    assert fired.events == (FingerPressEvent("LEFT_THUMB", 280),)


def test_index_bend_confirms_quickly_and_a_shallow_bend_does_not():
    from tests.test_gesture_engine import finger, state_of

    motor = GestureEngine()
    motor.update([finger("Left", "index", 172)], 0)
    motor.update([finger("Left", "index", 172)], 40)
    motor.update([finger("Left", "index", 110)], 100)
    second = motor.update([finger("Left", "index", 110)], 133)
    third = motor.update([finger("Left", "index", 110)], 166)

    assert second.events == () or third.events
    fired = second.events or third.events
    assert fired == (FingerPressEvent("LEFT_INDEX", fired[0].timestamp_ms),)
    assert fired[0].timestamp_ms - 100 <= 70

    shallow = GestureEngine()
    shallow.update([finger("Left", "index", 172)], 0)
    shallow.update([finger("Left", "index", 172)], 40)
    last = None
    for step in range(8):
        last = shallow.update([finger("Left", "index", 140)], 100 + step * 33)
        assert last.events == ()
    assert state_of(last, "LEFT_INDEX").phase == PHASE_READY


def test_calibration_accepts_a_personal_thumb_flexion():
    motor = GestureEngine()
    rest = [thumb("Left", OPEN_JOINTS)]
    personal = [thumb("Left", shifted_tip(0.70))]
    playing = [thumb("Left", shifted_tip(0.62))]
    assert motor.capture_reference(rest, "rest") == 1
    assert motor.capture_reference(personal, "flex") == 1

    plain = GestureEngine()
    arm(plain, rest)
    plain.update(playing, 100)
    without = plain.update(playing, 140)

    arm(motor, rest)
    motor.update(playing, 100)
    with_reference = motor.update(playing, 140)

    assert without.events == ()
    assert with_reference.events == (FingerPressEvent("LEFT_THUMB", 140),)


def test_gesture_note_reaches_audio_once(qapp):
    from fingermelody.interface.preview_window import PreviewWindow

    class PanelAudio:
        def __init__(self):
            self.played = []
            self.available = True
            self.status_message = "Audio disponible"

        def initialize(self):
            return True

        def set_volume(self, value):
            return None

        def play_note(self, name):
            self.played.append(name)
            return True

        def stop_all(self):
            return None

        def shutdown(self):
            return None

    audio = PanelAudio()
    window = PreviewWindow(audio_engine=audio)
    window.select_free_mode()
    window.start_session()
    event = FingerPressEvent("LEFT_THUMB", 15)
    window._handle_press_events((event,))
    window._handle_press_events((event,))
    window._handle_press_events((FingerPressEvent("RIGHT_THUMB", 16),))
    window._diagnostic_button.setChecked(True)

    assert audio.played == ["C4", "A4"]
    text = window._info.diagnostic.text()
    assert "RIGHT_THUMB" in text
    assert "A4" in text
    assert "play_note" in text
    window.close()
