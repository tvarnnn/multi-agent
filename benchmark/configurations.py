"""The two model-role configurations under comparison. Nothing else
differs between them in the harness - same tasks, same iteration caps,
same context limits, same validator composition, same session mode.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Configuration:
    name: str
    planner_model: str
    coder_model: str
    reviewer_model: str
    distinct_model_count: int


CONFIG_A = Configuration(
    name="Configuration A (3-role, Planner=Reviewer shared weights)",
    planner_model="phi4-reasoning:plus",
    coder_model="qwen2.5-coder:14b",
    reviewer_model="phi4-reasoning:plus",
    distinct_model_count=2,
)

CONFIG_B = Configuration(
    name="Configuration B (Planner/Coder/Reviewer all distinct weights)",
    planner_model="phi4-reasoning:plus",
    coder_model="qwen2.5-coder:14b",
    reviewer_model="llama3.1:8b",
    distinct_model_count=3,
)

CONFIGURATIONS = (CONFIG_A, CONFIG_B)

# Identical for both configurations - deliberately modest to bound
# worst-case wall-clock time for a 10-task x 2-configuration run while
# still exercising the fix loop and clarification loop for real.
MAX_OUTPUT_RETRIES = 2
MAX_CLARIFICATION_ROUNDS = 1
MAX_FIX_ITERATIONS = 2
