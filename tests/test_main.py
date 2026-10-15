"""Comprueba el arranque de la aplicación sin abrir la cámara."""

import os
import subprocess
import sys
import time

from fingermelody.main import parse_args


def test_parse_args_uses_the_primary_camera_and_default_resolution():
    args = parse_args([])

    assert args.camera == 0
    assert args.width == 640
    assert args.height == 480


def test_parse_args_accepts_device_and_resolution():
    args = parse_args(["--camera", "2", "--width", "320", "--height", "240"])

    assert (args.camera, args.width, args.height) == (2, 320, 240)


def test_module_entrypoint_stays_running_without_a_camera():
    completed = subprocess.run(
        [sys.executable, "-m", "fingermelody.main", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--camera" in completed.stdout

    process = subprocess.Popen(
        [sys.executable, "-m", "fingermelody.main"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    f"La aplicación terminó con código {process.returncode}\n{stdout}\n{stderr}"
                )
            time.sleep(0.1)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
