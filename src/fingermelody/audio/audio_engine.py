"""Reproducción de notas ya sintetizadas. No conoce dedos, gestos ni la interfaz.

El buffer de 512 muestras a 44100 Hz aporta unos 11,6 ms de cola interna.
Eso no incluye el retardo del controlador de Windows; no es una latencia acústica medida.
"""

from __future__ import annotations

from fingermelody.audio.synth import SynthConfig, render_note
from fingermelody.music.notes import SCALE, Note

SAMPLE_RATE = 44100
MIXER_BUFFER = 512
VOICE_CHANNELS = 16


class AudioError(Exception):
    """Petición de audio que el motor puede rechazar sin cerrar la aplicación."""


class PygameMixer:
    """Adaptador de pygame.mixer. Se inicializa una sola vez."""

    def __init__(self) -> None:
        self.frequency = SAMPLE_RATE
        self.size = -16
        self.channels = 2
        self.buffer = MIXER_BUFFER

    def init(self):
        import pygame

        if pygame.mixer.get_init() is None:
            pygame.mixer.pre_init(self.frequency, self.size, self.channels, self.buffer)
            pygame.mixer.init(
                frequency=self.frequency,
                size=self.size,
                channels=self.channels,
                buffer=self.buffer,
            )
        return pygame.mixer.get_init()

    def quit(self) -> None:
        import pygame

        if pygame.mixer.get_init() is not None:
            pygame.mixer.quit()

    def stop(self) -> None:
        import pygame

        if pygame.mixer.get_init() is not None:
            pygame.mixer.stop()

    def set_num_channels(self, count: int) -> None:
        import pygame

        pygame.mixer.set_num_channels(count)

    def make_sound(self, samples):
        import pygame

        return pygame.sndarray.make_sound(samples)

    def find_channel(self, force: bool = False):
        import pygame

        return pygame.mixer.find_channel(force)


class AudioEngine:
    """Reproduce notas precargadas. Una misma nota puede sonar otra vez al momento."""

    def __init__(
        self,
        notes: tuple[Note, ...] | None = None,
        *,
        mixer=None,
        synth_config: SynthConfig | None = None,
        voice_channels: int = VOICE_CHANNELS,
    ) -> None:
        catalog = SCALE if notes is None else notes
        self._catalog = {note.name: note for note in catalog}
        self._mixer = mixer if mixer is not None else PygameMixer()
        self._synth_config = synth_config or SynthConfig()
        self._voice_channels = voice_channels
        self._buffers: dict[str, object] = {}
        self._sounds: dict[str, object] = {}
        self._volume = 0.7
        self._ready = False
        self._available = False
        self._status = "Audio sin iniciar"

    @property
    def available(self) -> bool:
        return self._available

    @property
    def status_message(self) -> str:
        return self._status

    @property
    def volume(self) -> float:
        return self._volume

    def buffer(self, note: str):
        """Muestras PCM creadas en la inicialización."""
        if note not in self._buffers:
            raise AudioError(f"Nota desconocida: {note}")
        return self._buffers[note]

    def initialize(self) -> bool:
        """Sintetiza las notas y abre el mezclador. No se repite si ya está listo."""
        if self._ready:
            return True
        self._buffers = {
            name: render_note(note, self._synth_config) for name, note in self._catalog.items()
        }
        try:
            self._mixer.init()
            self._mixer.set_num_channels(self._voice_channels)
            for name, samples in self._buffers.items():
                sound = self._mixer.make_sound(samples)
                sound.set_volume(self._volume)
                self._sounds[name] = sound
        except Exception as exc:
            self._ready = False
            self._available = False
            self._sounds.clear()
            self._status = f"Audio no disponible. {exc}"
            self._close_mixer()
            return False
        self._ready = True
        self._available = True
        self._status = "Audio disponible"
        return True

    def play_note(self, note: str) -> bool:
        """Reproduce una nota ya cargada. No sintetiza ni abre el mezclador."""
        if note not in self._catalog:
            raise AudioError(f"Nota desconocida: {note}")
        if not self._ready:
            return False
        sound = self._sounds[note]
        channel = sound.play()
        if channel is not None:
            return True
        replacement = self._mixer.find_channel(True)
        if replacement is None:
            return False
        replacement.play(sound)
        return True

    def set_volume(self, volume: float) -> None:
        """Ajusta el volumen de las notas entre 0.0 y 1.0."""
        if volume < 0.0 or volume > 1.0:
            raise AudioError("El volumen debe estar entre 0.0 y 1.0.")
        self._volume = float(volume)
        for sound in self._sounds.values():
            sound.set_volume(self._volume)

    def stop_all(self) -> None:
        """Corta las notas que siguen sonando."""
        if not self._ready:
            return
        try:
            self._mixer.stop()
        except Exception:
            return

    def shutdown(self) -> None:
        """Libera el mezclador. Se puede llamar más de una vez."""
        self._ready = False
        self._available = False
        try:
            self._mixer.stop()
        except Exception:
            pass
        self._close_mixer()
        self._sounds.clear()
        self._buffers.clear()
        self._status = "Audio detenido"

    def _close_mixer(self) -> None:
        try:
            self._mixer.quit()
        except Exception:
            return
