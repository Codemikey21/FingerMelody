"""Regresiones visuales: repetición, estela y contraste del neón."""

import pytest
from PySide6.QtGui import QImage, QPainter

from fingermelody.interface.note_highway import NoteHighway
from fingermelody.interface.piano_widget import PianoWidget


def road():
    widget = NoteHighway()
    widget.resize(600, 500)
    widget.set_lanes((("E4", 180.0, 90.0),))
    widget.set_chart((("E4", 1.0), ("E4", 1.0), ("E4", 2.0)), 0)
    widget.set_running(True)
    return widget


def test_repeated_notes_remain_separate_and_move_continuously(qapp):
    widget = road()
    before = widget.bar_bottom(0)
    for _ in range(10):
        previous = widget.bar_bottom(0)
        widget.advance_visual(0.016)
        assert 0 < widget.bar_bottom(0) - previous < 2
    assert widget.bar_bottom(0) > before
    assert widget.bar_rect(1).bottom() < widget.bar_rect(0).top()
    widget.advance_visual(2)
    assert widget.bar_bottom(0) == pytest.approx(widget.activation_y())
    widget.set_chart(widget._steps, 1)
    next_bottom = widget.bar_bottom(1)
    widget.advance_visual(0.016)
    assert 0 < widget.bar_bottom(1) - next_bottom < 2
    widget.shutdown()


def test_trail_fades_without_spawning_particles_or_changing_progress(qapp):
    widget = road()
    widget.advance_visual(0.1)
    assert widget._trail > 0
    widget.set_running(False)
    bottom = widget.bar_bottom(0)
    widget.advance_visual(0.5)
    assert widget._trail == 0
    assert widget.effect_count() == 0
    assert widget.bar_bottom(0) == bottom
    assert widget._index == 0
    assert not widget._timer.isActive()
    widget.shutdown()


def test_neon_edges_are_brighter_than_core_and_future_notes(qapp):
    widget = road()
    widget.advance_visual(2)
    widget.advance_visual(0.5)
    # Aislar las barras: la luz de proximidad ilumina intencionalmente el
    # núcleo al llegar al piano, y no debe confundirse con su contraste propio.
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(0xff03050d)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    widget._paint_bars(painter)
    painter.end()
    def edge_value(rect):
        return max(image.pixelColor(round(rect.left()) + dx, round(rect.center().y())).value()
                   for dx in (-1, 0, 1, 2))
    current = widget.bar_rect(0)
    future = widget.bar_rect(1)
    assert edge_value(current) > image.pixelColor(current.center().toPoint()).value() + 80
    assert edge_value(current) > edge_value(future) + 30
    widget.shutdown()


def test_approaching_light_reflects_without_playing_or_pressing_a_key(qapp):
    widget = road()
    piano = PianoWidget()
    widget.illumination_changed.connect(piano.set_ambient_notes)
    emitted = []
    piano.note_pressed.connect(emitted.append)
    widget.advance_visual(0.016)
    initial = piano._ambient_notes["E4"]
    widget.advance_visual(2)
    assert piano._ambient_notes["E4"] > initial
    assert piano._ambient_notes["E4"] == pytest.approx(1)
    assert emitted == []
    assert piano.lit_notes() == set()
    assert widget._index == 0
    widget.set_chart(widget._steps, len(widget._steps))
    assert piano._ambient_notes == {}
    widget.shutdown()
