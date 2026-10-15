"""Datos reales de la sesión. Las notas y el sintetizador no se modifican aquí.

Guardar reposo o flexión solo pide una referencia al motor de gestos."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from fingermelody.interface.info_panel import finger_caption
from fingermelody.interface.styles import STYLESHEET
from fingermelody.music.note_mapper import NoteMapper


class SettingsDialog(QDialog):
    """Muestra la asociación dedo-nota, el dispositivo y el estado del audio."""

    def __init__(
        self,
        mapper: NoteMapper,
        audio_status: str,
        device_text: str,
        parent=None,
        on_capture_rest=None,
        on_capture_flex=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowTitle("Configuración")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setStyleSheet(STYLESHEET)

        title = QLabel("Configuración")
        title.setObjectName("dialogTitle")
        audio = QLabel(audio_status)
        audio.setObjectName("settingsAudio")
        audio.setWordWrap(True)
        device = QLabel(device_text)
        device.setObjectName("settingsDevice")
        device.setWordWrap(True)
        mapping = QLabel(_mapping_text(mapper))
        mapping.setObjectName("assignmentLabel")
        mapping.setWordWrap(True)
        mapping.setTextFormat(Qt.TextFormat.PlainText)
        mapping.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        note = QLabel(
            "Las teclas blancas son las notas naturales de la escala. "
            "Las teclas negras solo muestran la distribución del teclado."
        )
        note.setObjectName("settingsNote")
        note.setWordWrap(True)
        self._calibration = QLabel("Sin calibración. Los umbrales de partida siguen activos.")
        self._calibration.setObjectName("calibrationStatus")
        self._calibration.setWordWrap(True)
        rest = QPushButton("Guardar reposo")
        rest.setObjectName("captureRestButton")
        rest.clicked.connect(lambda: self._capture(on_capture_rest))
        flexed = QPushButton("Guardar flexión")
        flexed.setObjectName("captureFlexButton")
        flexed.clicked.connect(lambda: self._capture(on_capture_flex))
        close = QPushButton("Cerrar")
        close.setObjectName("closeSettingsButton")
        close.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(audio)
        layout.addWidget(device)
        layout.addWidget(mapping)
        layout.addWidget(note)
        layout.addWidget(self._calibration)
        layout.addWidget(rest)
        layout.addWidget(flexed)
        layout.addWidget(close)

    def set_calibration_message(self, message: str) -> None:
        self._calibration.setText(message)

    def _capture(self, callback) -> None:
        if callback is None:
            self._calibration.setText("La calibración se activa desde la ventana principal.")
            return
        self._calibration.setText(callback())


def _mapping_text(mapper: NoteMapper) -> str:
    lines = ["Asociación de dedos"]
    for finger, note_name in mapper.assignments():
        lines.append(f"{finger_caption(finger)} → {note_name}")
    return "\n".join(lines)
