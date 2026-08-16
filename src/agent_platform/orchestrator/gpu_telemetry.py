"""Best-effort GPU VRAM telemetry via nvidia-smi. Never raises - a
missing or misbehaving nvidia-smi degrades to "no telemetry available,"
never to a crash, since nothing about the orchestrator's correctness
depends on this succeeding.
"""
from __future__ import annotations

import subprocess
from typing import Callable, Optional


def query_gpu_memory(
    nvidia_smi: Callable[..., object] = subprocess.run,
) -> Optional[dict]:
    try:
        result = nvidia_smi(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except OSError:
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    try:
        used, total = result.stdout.strip().split(",")
        return {"used_mib": int(used.strip()), "total_mib": int(total.strip())}
    except (ValueError, AttributeError):
        return None
