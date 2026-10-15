"""Comprueba que el proyecto arranca sin abrir la cámara ni reproducir audio."""

import subprocess
import sys


def test_main_reports_configured_environment(capsys):
    from fingermelody.main import main

    main()

    captured = capsys.readouterr()
    assert captured.out.strip() == "FingerMelody está correctamente configurado."


def test_module_entrypoint_runs():
    completed = subprocess.run(
        [sys.executable, "-m", "fingermelody.main"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "FingerMelody está correctamente configurado."
