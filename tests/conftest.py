"""Fija Qt en offscreen para que las pruebas no abran una ventana ni la cámara."""

import gc
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication
from shiboken6 import delete, isValid


@pytest.fixture(scope="session")
def qapp():
    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    yield application
    _release_test_qt(application)


def _release_test_qt(application: QApplication) -> None:
    """Cierra widgets e hilos antes de que el intérprete destruya Qt."""
    if not isValid(application):
        return
    for widget in list(application.topLevelWidgets()):
        if not isValid(widget):
            continue
        for timer in widget.findChildren(QTimer):
            timer.stop()
        shutdown = getattr(widget, "shutdown", None)
        if callable(shutdown):
            shutdown()
        widget.close()
    application.processEvents()
    for widget in list(application.topLevelWidgets()):
        if isValid(widget):
            delete(widget)
    gc.collect()
    for obj in gc.get_objects():
        if not isinstance(obj, QThread):
            continue
        try:
            if not isValid(obj):
                continue
            if obj.isRunning():
                obj.requestInterruption()
                obj.wait(2000)
            delete(obj)
        except RuntimeError:
            continue
    if isValid(application):
        delete(application)
