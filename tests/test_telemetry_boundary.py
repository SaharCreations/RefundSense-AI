"""Telemetry opt-out must precede ONNX Runtime initialization."""

import os
import subprocess
import sys


def test_package_sets_telemetry_opt_out_before_runtime_import():
    env = dict(os.environ)
    env.pop("ORT_DISABLE_TELEMETRY", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import refundguard, os, sys; "
            'assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"; '
            'assert "onnxruntime" not in sys.modules',
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_unsafe_preinitialized_runtime_requires_restart():
    env = dict(os.environ)
    env.pop("ORT_DISABLE_TELEMETRY", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            'import sys, types; sys.modules["onnxruntime"]=types.ModuleType("onnxruntime"); '
            "import refundguard",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Restart with ORT_DISABLE_TELEMETRY=1" in result.stderr
