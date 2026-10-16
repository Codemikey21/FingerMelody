"""Contrato de lectura y diagnósticos, sin dependencia del renderizado."""
from dataclasses import FrozenInstanceError

import pytest

from fingermelody.music.guided import (
    GuidedMode, SongStep, StepState, SubmissionReason as Reason,
)
from fingermelody.music.note_mapper import NoteMapper


def guide():
    return GuidedMode((SongStep("a", ("C4", "E5"), 2),
                       SongStep("b", ("E5",), 1)))


def test_snapshot_complete_arrangement_and_anatomy():
    controller = GuidedMode()
    snapshot = controller.snapshot()
    mapper = NoteMapper()
    assert snapshot.total == 49
    assert sum(len(s.required_notes) == 2 for s in snapshot.steps) == 28
    assert all(1 <= len(s.required_notes) <= 2 for s in snapshot.steps)
    for index, state in enumerate(snapshot.steps):
        assert (state.index, state.position, state.total) == (index, index + 1, 49)
        assert state.relative_duration == state.step.beats
        assert state.pending_notes == state.required_notes
        assert not state.completed
        if len(state.required_notes) == 2:
            assert {mapper.assignments_for_note(n)[0].hand
                    for n in state.required_notes} == {"LEFT", "RIGHT"}
    identities = [n.identity for s in snapshot.steps for n in s.visual_notes]
    assert len(identities) == len(set(identities)) == 77
    controller.start()
    controller.submit("E5")
    controller.finish()
    controller.start()
    assert [s.step_id for s in snapshot.steps] == [s.step_id for s in controller.snapshot().steps]


def test_snapshot_is_detached_immutable_and_read_has_no_side_effects():
    controller = guide()
    controller.start()
    before = controller.snapshot()
    controller.submit("C4")
    after = controller.snapshot()
    assert before.current.accepted_notes == frozenset()
    assert after.current.pending_notes == ("E5",)
    assert after.current.progress == .5
    assert [(n.identity, n.accepted) for n in after.current.visual_notes] == [
        (("a", "C4"), True), (("a", "E5"), False)]
    with pytest.raises(FrozenInstanceError):
        after.current.index = 4
    with pytest.raises(FrozenInstanceError):
        after.current.visual_notes[0].accepted = False
    with pytest.raises(AttributeError):
        after.current.accepted_notes.add("E5")
    controller._clock = lambda: pytest.fail("Una consulta no debe leer el reloj")
    assert controller.snapshot() == after
    assert controller.press_count == 1
    source = {"C4"}
    legacy = StepState(before.current.step, source)
    source.clear()
    assert legacy.accepted_notes == frozenset({"C4"})


def test_diagnostics_partial_pause_release_batch_and_completion():
    controller = guide()
    assert controller.submit_result("C4").reason == Reason.SESSION_INACTIVE
    controller.start(("LEFT_THUMB",))
    token = controller.batch_token
    result = controller.submit_result("C4", "LEFT_THUMB")
    assert result.reason == Reason.FINGER_PENDING_RELEASE and not result.accepted
    controller.release_finger("LEFT_THUMB")
    assert controller.submit_result("D4").reason == Reason.NOTE_NOT_REQUIRED
    first = controller.submit_result("C4", expected_step=token)
    assert first.reason == Reason.ACCEPTED and first.accepted
    assert first.state.pending_notes == ("E5",)
    assert controller.submit_result("C4").reason == Reason.ALREADY_ACCEPTED
    controller.pause()
    assert controller.snapshot().paused and controller.step_state().paused
    assert controller.submit_result("E5").reason == Reason.SESSION_PAUSED
    controller.resume()
    assert controller.step_state().accepted_notes == frozenset({"C4"})
    assert controller.submit_result("E5", expected_step=token).reason == Reason.STALE_BATCH
    token = controller.batch_token
    done = controller.submit_result("E5", expected_step=token)
    assert done.reason == Reason.STEP_COMPLETED and done.accepted
    assert done.state.completed and done.state.step_id == "a"
    assert controller.snapshot().current.step_id == "b"
    assert controller.snapshot().progress == .5
    assert controller.submit_result("E5", expected_step=token).reason == Reason.STALE_BATCH
    assert controller.press_count == 2
    assert controller.submit_result("E5").reason == Reason.STEP_COMPLETED
    assert controller.submit_result("E5").reason == Reason.SONG_COMPLETED
    assert controller.snapshot().current is None
    assert controller.snapshot().progress == 1
    assert controller.press_count == 3


def test_legacy_submit_and_chart_remain_compatible():
    old, new = guide(), guide()
    old.start()
    new.start()
    for note in ("D4", "E5", "E5", "C4", "E5"):
        assert old.submit(note) == new.submit_result(note).hit
        assert old.snapshot() == new.snapshot()
    assert old.chart() == (("C4", 2), ("E5", 1))


def test_inverse_mapping_all_ten_and_custom_ambiguity():
    mapper = NoteMapper()
    for finger_id, note in mapper.assignments():
        result, = mapper.assignments_for_note(note)
        assert result.note == note and result.finger_id == finger_id
        assert (result.hand, result.finger) == tuple(finger_id.split("_"))
        with pytest.raises(FrozenInstanceError):
            result.note = "D4"
    custom = NoteMapper((("LEFT_INDEX", "E5"), ("button", "E5")))
    first, second = custom.assignments_for_note("E5")
    assert first.hand == "LEFT" and first.finger == "INDEX"
    assert second.hand is None and second.finger is None
    assert custom.assignments_for_note("C4") == ()
    assert mapper.assignments_for_note("unknown") == ()
