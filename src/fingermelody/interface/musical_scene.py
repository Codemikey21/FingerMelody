"""Composición continua de carretera, teclado y cámara flotante."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from fingermelody.interface.neon_palette import BACKGROUND
from fingermelody.interface.camera_panel import CameraPanel
from fingermelody.interface.note_highway import NoteHighway
from fingermelody.interface.piano_widget import PianoWidget


class MusicalScene(QWidget):
    """Comparte geometría visual sin intervenir en notas, gestos ni audio."""

    def __init__(self, highway: NoteHighway, piano: PianoWidget, camera: CameraPanel) -> None:
        super().__init__()
        self.setObjectName("musicalScene")
        self.setMinimumHeight(370)
        self.highway = highway
        self.piano = piano
        self.camera = camera
        for widget in (piano, highway, camera):
            widget.setParent(self)
        highway.impact_light_changed.connect(piano.set_impact_lights)
        highway.illumination_changed.connect(piano.set_ambient_notes)
        piano.set_integrated(True)
        highway.set_integrated(True)
        highway.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._camera_placed = False

    def notify_note(self, note: str) -> None:
        """Reacciona a una nota aceptada; nunca reproduce ni genera música."""
        if note not in self.piano.note_names:
            return
        self.sync_lanes()
        self.highway.notify_hit(note)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(BACKGROUND))
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.arrange()

    def arrange(self) -> None:
        # Un solapamiento de 16 px conserva la parte inferior de los destellos.
        # activation_y() queda exactamente en el comienzo de las teclas.
        piano_height = max(150, min(190, round(self.height() * 0.27)))
        keyboard_top = self.height() - piano_height
        self.piano.setGeometry(0, keyboard_top, self.width(), piano_height)
        self.highway.setGeometry(0, 0, self.width(), keyboard_top + 16)
        self.highway.raise_()
        self.sync_lanes()

    def sync_lanes(self) -> None:
        lanes = []
        for note, rect in self.piano.white_rects():
            point = self.piano.mapTo(self, rect.center().toPoint())
            local = self.highway.mapFrom(self, point)
            lanes.append((note, float(local.x()), float(rect.width())))
        self.highway.set_lanes(tuple(lanes))
        self.place_camera()

    def place_camera(self, reveal: bool = False) -> None:
        if self.width() < 520:
            return
        card_w = min(292, max(248, round(self.width() * 0.24)))
        card_h = min(206, max(168, self.piano.y() - 24))
        # Posición estable: en interpretación libre no existe nota objetivo.
        x = self.width() - card_w - 12
        previous = self.camera.pos()
        self.camera.setGeometry(x, 12, card_w, card_h)
        self.camera.raise_()
        if reveal or (self._camera_placed and previous != QPoint(x, 12)):
            self.camera.reveal()
        self._camera_placed = True
