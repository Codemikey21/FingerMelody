"""Forma y seguridad de las muestras, sin abrir el mezclador."""

import numpy as np
import pytest

from fingermelody.audio.synth import SynthConfig, render_note
from fingermelody.music.notes import NOTES_BY_NAME

_CONFIG = SynthConfig()


def test_samples_match_the_mixer_format_and_the_configured_duration():
    pcm = render_note(NOTES_BY_NAME["A4"], _CONFIG)
    expected = int(round(_CONFIG.sample_rate * _CONFIG.duration_ms / 1000.0))

    assert pcm.dtype == np.int16
    assert pcm.shape == (expected, 2)
    assert pcm.flags["C_CONTIGUOUS"]
    assert int(_CONFIG.duration_ms) == 450


def test_amplitude_stays_inside_a_safe_peak_and_the_edges_are_silent():
    pcm = render_note(NOTES_BY_NAME["C4"], _CONFIG)
    limit = int(_CONFIG.peak * 32767)

    assert int(np.max(np.abs(pcm))) <= limit
    assert int(np.max(np.abs(pcm))) > 1000
    assert int(pcm[0, 0]) == 0
    assert int(pcm[-1, 0]) == 0
    assert np.array_equal(pcm[:, 0], pcm[:, 1])


def test_the_fundamental_is_the_loudest_partial():
    note = NOTES_BY_NAME["A4"]
    pcm = render_note(note, _CONFIG).astype(np.float64)[:, 0]
    spectrum = np.abs(np.fft.rfft(pcm))
    frequencies = np.fft.rfftfreq(pcm.shape[0], 1.0 / _CONFIG.sample_rate)

    assert frequencies[int(np.argmax(spectrum))] == pytest.approx(note.frequency, rel=0.02)


def test_rendering_is_stable_across_the_scale():
    for note in NOTES_BY_NAME.values():
        first = render_note(note, _CONFIG)
        second = render_note(note, _CONFIG)
        assert np.array_equal(first, second)
        assert int(np.max(np.abs(first))) <= int(_CONFIG.peak * 32767)
