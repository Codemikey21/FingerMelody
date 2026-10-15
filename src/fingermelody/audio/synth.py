"""Muestras de un piano electrónico suave. No abre el dispositivo de audio."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fingermelody.music.notes import Note

_HARMONICS = (1.0, 0.48, 0.24, 0.12, 0.06)


@dataclass(frozen=True)
class SynthConfig:
    """Duración y nivel de las muestras. Se aplican al crearlas, no al pulsar."""

    sample_rate: int = 44100
    duration_ms: int = 450
    peak: float = 0.16
    attack_ms: int = 10
    decay_ms: int = 110
    sustain: float = 0.32
    release_ms: int = 150

    def __post_init__(self) -> None:
        if not 300 <= self.duration_ms <= 600:
            raise ValueError("La duración debe estar entre 300 y 600 ms.")
        if self.attack_ms + self.decay_ms + self.release_ms >= self.duration_ms:
            raise ValueError("El ataque, el decaimiento y la liberación no caben en la nota.")
        if not 0.0 < self.peak <= 0.25:
            raise ValueError("El pico de cada nota debe quedar holgado bajo la escala completa.")
        if not 0.0 < self.sustain < 1.0:
            raise ValueError("El sustain debe estar entre 0 y 1.")


def render_note(note: Note, config: SynthConfig | None = None) -> np.ndarray:
    """Devuelve PCM estéreo int16. Empieza y termina en silencio para evitar clics."""
    settings = config or SynthConfig()
    count = int(round(settings.sample_rate * settings.duration_ms / 1000.0))
    time = np.arange(count, dtype=np.float64) / settings.sample_rate
    wave = np.zeros(count, dtype=np.float64)
    for index, amplitude in enumerate(_HARMONICS, start=1):
        wave += amplitude * np.sin(2.0 * np.pi * note.frequency * index * time)
    peak = float(np.max(np.abs(wave)))
    if peak > 0.0:
        wave /= peak
    wave *= _envelope(count, settings) * settings.peak
    stereo = np.column_stack((wave, wave))
    pcm = np.clip(np.rint(stereo * 32767.0), -32767, 32767).astype(np.int16)
    return np.ascontiguousarray(pcm)


def _envelope(count: int, config: SynthConfig) -> np.ndarray:
    attack = _frames(config.attack_ms, config.sample_rate)
    decay = _frames(config.decay_ms, config.sample_rate)
    release = _frames(config.release_ms, config.sample_rate)
    if attack + decay + release >= count:
        release = max(1, count - attack - decay - 1)
    sustain_frames = count - attack - decay - release
    envelope = np.empty(count, dtype=np.float64)
    envelope[:attack] = np.linspace(0.0, 1.0, attack, endpoint=False)
    cursor = attack
    envelope[cursor : cursor + decay] = np.linspace(1.0, config.sustain, decay, endpoint=False)
    cursor += decay
    envelope[cursor : cursor + sustain_frames] = config.sustain
    envelope[-release:] = np.linspace(config.sustain, 0.0, release, endpoint=True)
    return envelope


def _frames(duration_ms: int, sample_rate: int) -> int:
    return max(1, int(round(sample_rate * duration_ms / 1000.0)))
