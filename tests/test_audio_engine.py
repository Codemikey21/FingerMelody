"""Motor de audio con un mezclador simulado. No usa altavoces."""

from pathlib import Path

import numpy as np
import pytest

from fingermelody.audio.audio_engine import VOICE_CHANNELS, AudioEngine, AudioError
from fingermelody.audio.synth import SynthConfig
from fingermelody.music.notes import SCALE


class FakeChannel:
    def __init__(self):
        self.played = []

    def play(self, sound):
        self.played.append(sound)


class FakeSound:
    def __init__(self, data, blocked):
        self.data = data
        self.blocked = blocked
        self.volume = None
        self.play_count = 0

    def set_volume(self, volume):
        self.volume = volume

    def play(self):
        self.play_count += 1
        if self.blocked:
            return None
        return FakeChannel()


class FakeMixer:
    def __init__(self, fail=False, blocked=False):
        self.fail = fail
        self.blocked = blocked
        self.init_count = 0
        self.quit_count = 0
        self.stop_count = 0
        self.channel_count = None
        self.sounds = []
        self.forced = []

    def init(self):
        self.init_count += 1
        if self.fail:
            raise RuntimeError("sin dispositivo")
        return (44100, -16, 2)

    def quit(self):
        self.quit_count += 1

    def stop(self):
        self.stop_count += 1

    def set_num_channels(self, count):
        self.channel_count = count

    def make_sound(self, samples):
        sound = FakeSound(samples, self.blocked)
        self.sounds.append(sound)
        return sound

    def find_channel(self, force=False):
        channel = FakeChannel()
        self.forced.append((force, channel))
        return channel


def engine(mixer, **kwargs):
    motor = AudioEngine(mixer=mixer, synth_config=SynthConfig(duration_ms=300), **kwargs)
    return motor


def test_initialize_preloads_every_note_once():
    mixer = FakeMixer()
    motor = engine(mixer)

    assert motor.initialize() is True
    assert motor.initialize() is True

    assert mixer.init_count == 1
    assert mixer.channel_count == VOICE_CHANNELS
    assert mixer.channel_count >= 10
    assert len(mixer.sounds) == len(SCALE)
    assert motor.buffer("A4").dtype == np.int16
    assert motor.available is True
    assert motor.status_message == "Audio disponible"


def test_play_replays_a_loaded_note_without_resynthesizing():
    mixer = FakeMixer()
    motor = engine(mixer)
    motor.initialize()
    sounds = list(mixer.sounds)

    assert motor.play_note("C4") is True
    assert motor.play_note("C4") is True
    assert motor.play_note("E5") is True

    assert sounds[0].play_count == 2
    assert len(mixer.sounds) == len(SCALE)


def test_unknown_note_is_rejected_and_a_missing_device_does_not_raise():
    mixer = FakeMixer()
    motor = engine(mixer)
    motor.initialize()
    with pytest.raises(AudioError, match="desconocida"):
        motor.play_note("C9")

    failed = FakeMixer(fail=True)
    silent = engine(failed)
    assert silent.initialize() is False
    assert silent.available is False
    assert "no disponible" in silent.status_message.casefold()
    assert silent.play_note("A4") is False
    assert failed.quit_count == 1


def test_volume_accepts_the_ends_of_the_range():
    mixer = FakeMixer()
    motor = engine(mixer)
    motor.initialize()

    motor.set_volume(0.0)
    motor.set_volume(1.0)

    assert motor.volume == 1.0
    assert all(sound.volume == 1.0 for sound in mixer.sounds)
    with pytest.raises(AudioError, match="volumen"):
        motor.set_volume(-0.1)
    with pytest.raises(AudioError, match="volumen"):
        motor.set_volume(1.1)


def test_simultaneous_notes_use_another_channel_when_the_mixer_is_full():
    mixer = FakeMixer(blocked=True)
    motor = engine(mixer)
    motor.initialize()

    assert motor.play_note("C4") is True
    assert motor.play_note("G4") is True
    assert len(mixer.forced) == 2
    assert all(force is True for force, _channel in mixer.forced)
    assert len(mixer.forced[0][1].played) == 1
    assert mixer.forced[0][1].played[0] is mixer.sounds[0]


def test_shutdown_releases_the_mixer_and_can_repeat():
    mixer = FakeMixer()
    motor = engine(mixer)
    motor.initialize()
    motor.play_note("D4")

    motor.stop_all()
    motor.shutdown()
    motor.shutdown()

    assert mixer.stop_count >= 1
    assert mixer.quit_count == 2
    assert motor.available is False
    assert motor.play_note("D4") is False
    with pytest.raises(AudioError, match="desconocida"):
        motor.buffer("D4")


def test_audio_engine_does_not_import_the_interface_or_mediapipe():
    source = Path(__file__).parents[1].joinpath("src/fingermelody/audio/audio_engine.py").read_text(
        encoding="utf-8"
    )
    synth = Path(__file__).parents[1].joinpath("src/fingermelody/audio/synth.py").read_text(encoding="utf-8")

    assert "PySide6" not in source
    assert "mediapipe" not in source
    assert "NoteMapper" not in source
    assert "PySide6" not in synth
