"""Apariencia de la ventana. Se aplica una vez, no en cada fotograma."""

STYLESHEET = """
QMainWindow, QWidget {
    background-color: #12141c;
    color: #f2f3f7;
    font-family: "Segoe UI", "Segoe UI Variable", sans-serif;
    font-size: 14px;
}
QLabel#titleLabel {
    font-size: 22px;
    font-weight: 700;
    color: #f7f5ff;
}
QLabel#cameraChip {
    border-radius: 11px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 600;
}
QLabel#cameraChip[state="on"] {
    color: #04221c;
    background-color: #3ee0d0;
}
QLabel#cameraChip[state="off"] {
    color: #c5cad6;
    background-color: #242836;
}
QLabel#cameraChip[state="busy"] {
    color: #1a1230;
    background-color: #c4b6ff;
}
QLabel#trackingLabel {
    color: #f2f3f7;
    font-size: 13px;
}
QLabel#trackingLabel[tone="ok"] {
    color: #3ee0d0;
}
QLabel#trackingLabel[tone="warn"] {
    color: #ffb4c0;
}
QLabel#deviceLabel, QLabel#infoFpsLabel, QLabel#volumeLabel {
    color: #9aa3b5;
    font-size: 12px;
}
QLabel#fpsLabel {
    color: #d8fff8;
    background-color: rgba(8, 10, 16, 190);
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 12px;
}
QLabel#leftLegend {
    color: #80c6b0;
    font-size: 12px;
    font-weight: 600;
}
QLabel#rightLegend {
    color: #cca870;
    font-size: 12px;
    font-weight: 600;
}
QLabel#statusLabel, QLabel#audioStatus, QLabel#lastNoteLabel, QLabel#lastFingerLabel,
QLabel#pressCountLabel, QLabel#handsLabel, QLabel#leftHandLabel, QLabel#rightHandLabel,
QLabel#sessionStatusLabel {
    font-size: 13px;
}
QLabel#modeLabel {
    color: #c4b6ff;
    font-size: 13px;
    font-weight: 700;
}
QLabel#sessionStatusLabel[phase="playing"] {
    color: #3ee0d0;
}
QLabel#sessionStatusLabel[phase="paused"] {
    color: #ffb4c0;
}
QLabel#historyLabel {
    color: #c5cad6;
    font-size: 12px;
}
QLabel#statusLabel[error="yes"], QLabel#audioStatus[error="yes"] {
    color: #ff8f9a;
}
QLabel#lastNoteLabel {
    font-size: 18px;
    font-weight: 600;
    color: #f4f1ff;
}
QFrame#cameraPanel, QFrame#infoPanel {
    background-color: #171a24;
    border: 1px solid #2c3142;
    border-radius: 16px;
}
QLabel#preview {
    background-color: #0c0e14;
    border: 1px solid #2a3144;
    border-radius: 12px;
    color: #9aa3b5;
}
QLabel#leftFingerPanel, QLabel#rightFingerPanel {
    color: #d5d8e4;
    font-size: 12px;
    background-color: #12141c;
    border: 1px solid #2c3142;
    border-radius: 10px;
    padding: 8px 10px;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget, QWidget#fingerHost {
    background: transparent;
}
QSplitter::handle {
    background-color: #2a2f3e;
    width: 6px;
    margin: 8px 0;
    border-radius: 3px;
}
QPushButton {
    background-color: #222636;
    color: #f2f3f7;
    border: 1px solid #343a4e;
    border-radius: 10px;
    padding: 8px 14px;
}
QPushButton:hover {
    background-color: #2c3148;
    border-color: #8b7cf7;
}
QPushButton:pressed {
    background-color: #3a2f66;
    padding-top: 9px;
    padding-bottom: 7px;
}
QPushButton:disabled {
    color: #7d8496;
    background-color: #1a1d27;
    border-color: #2a2f3c;
}
QPushButton#startButton {
    background-color: #6d5ef5;
    border-color: #8b7cf7;
    color: #f8f7ff;
    font-weight: 600;
}
QPushButton#startButton:hover {
    background-color: #7d70f7;
}
QPushButton#startButton:pressed {
    background-color: #5648d4;
}
QPushButton#startButton:disabled {
    background-color: #1a1d27;
    color: #7d8496;
    border-color: #2a2f3c;
}
QPushButton#startSessionButton {
    background-color: #6d5ef5;
    border-color: #8b7cf7;
    color: #f8f7ff;
    font-weight: 600;
}
QPushButton#startSessionButton:hover {
    background-color: #7d70f7;
}
QPushButton#startSessionButton:disabled {
    background-color: #1a1d27;
    color: #7d8496;
    border-color: #2a2f3c;
}
QPushButton#stopButton:enabled {
    background-color: #3a2438;
    border-color: #6d4a72;
}
QPushButton#muteButton[muted="yes"] {
    background-color: #2a2348;
    border-color: #8b7cf7;
    color: #ddd6ff;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #2a2f3e;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #8b7cf7;
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #3ee0d0;
}
QDialog {
    background-color: #171a24;
}
QLabel#dialogTitle {
    font-size: 18px;
    font-weight: 700;
}
QLabel#assignmentLabel, QLabel#settingsAudio, QLabel#settingsDevice, QLabel#settingsNote {
    color: #d5d8e4;
    font-size: 13px;
}
QToolTip {
    background-color: #1c2030;
    color: #f2f3f7;
    border: 1px solid #8b7cf7;
    padding: 4px 8px;
}
"""


def restyle(widget) -> None:
    """Aplica un cambio de propiedad dinámica sin recargar la hoja de estilo."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
