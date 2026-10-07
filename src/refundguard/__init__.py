"""RefundSense AI: policy retrieval, deterministic rules, and approved demo refunds."""

import os
import sys

# Required before importing ONNX Runtime: its official POSIX builds otherwise
# initialize external telemetry before disable_telemetry_events() can run.
if "onnxruntime" in sys.modules and os.getenv("ORT_DISABLE_TELEMETRY") != "1":
    raise RuntimeError("Restart with ORT_DISABLE_TELEMETRY=1 before importing ONNX Runtime")
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

__version__ = "0.1.0"
