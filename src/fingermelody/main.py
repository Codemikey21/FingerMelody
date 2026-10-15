"""Punto de entrada de FingerMelody."""

from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication, QMessageBox
from shiboken6 import delete, isValid

from fingermelody.interface.main_window import MainWindow


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Lee el dispositivo y la resolución de la captura."""
    parser = argparse.ArgumentParser(description="FingerMelody")
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Índice de la cámara. La cámara principal es 0.",
    )
    parser.add_argument("--width", type=int, default=640, help="Ancho del fotograma.")
    parser.add_argument("--height", type=int, default=480, help="Alto del fotograma.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Abre la ventana principal de FingerMelody."""
    args = parse_args(argv)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("FingerMelody")
    app.setStyle("Fusion")
    try:
        window = MainWindow(args.camera, args.width, args.height)
    except ValueError as exc:
        QMessageBox.critical(None, "FingerMelody", str(exc))
        _release_qt(app, None)
        raise SystemExit(1) from exc

    app.aboutToQuit.connect(window.shutdown)
    window.show()
    code = app.exec()
    _release_qt(app, window)
    raise SystemExit(code)


def _release_qt(app: QApplication, window: MainWindow | None) -> None:
    """Destruye la interfaz mientras Python y Qt siguen vivos."""
    if window is not None and isValid(window) and isValid(app):
        try:
            app.aboutToQuit.disconnect(window.shutdown)
        except (RuntimeError, TypeError):
            pass
    if window is not None and isValid(window):
        window.shutdown()
        window.close()
    if isValid(app):
        app.processEvents()
    if window is not None and isValid(window):
        delete(window)
    if isValid(app):
        delete(app)


if __name__ == "__main__":
    main()
