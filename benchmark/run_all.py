"""Top-level Phase 8 benchmark driver. Runs every (configuration, task)
pair exactly once against the real Ollama-backed orchestrator stack and
appends one JSON line per run to results/raw_results.jsonl as it
completes, so partial progress survives an interruption. Prints a
one-line progress marker per run to stdout for live monitoring.

Usage: python -m benchmark.run_all
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from benchmark.configurations import CONFIGURATIONS, MAX_CLARIFICATION_ROUNDS, MAX_FIX_ITERATIONS, MAX_OUTPUT_RETRIES
from benchmark.dataset import TASKS
from benchmark.runner import run_one

RESULTS_PATH = Path(__file__).resolve().parent / "results" / "raw_results.jsonl"


def main() -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"Phase 8 benchmark start. caps: output_retries={MAX_OUTPUT_RETRIES} "
          f"clarification_rounds={MAX_CLARIFICATION_ROUNDS} fix_iterations={MAX_FIX_ITERATIONS}", flush=True)
    print(f"writing to {RESULTS_PATH}", flush=True)
    total = len(CONFIGURATIONS) * len(TASKS)
    done = 0
    with RESULTS_PATH.open("a", encoding="utf-8") as out:
        for config in CONFIGURATIONS:
            for task in TASKS:
                t0 = time.monotonic()
                print(f"[{done + 1}/{total}] running {task.task_id} under {config.name} ...", flush=True)
                record = run_one(task, config)
                out.write(json.dumps(record) + "\n")
                out.flush()
                done += 1
                elapsed = time.monotonic() - t0
                print(f"[{done}/{total}] DONE {task.task_id} / {config.name}: "
                      f"final_state={record['final_state']} wall={elapsed:.1f}s "
                      f"calls={record['model_call_count']} swaps={record['model_swap_count']} "
                      f"ground_truth_passed={record['ground_truth']['passed'] if record['ground_truth'] else 'N/A'}",
                      flush=True)
    print("Phase 8 benchmark complete.", flush=True)


if __name__ == "__main__":
    main()
