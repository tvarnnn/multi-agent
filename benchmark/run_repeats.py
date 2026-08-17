"""Repeats a small representative subset of tasks under both
configurations to get a second data point for variance - the primary
sweep (run_all.py) is n=1 per (task, configuration) cell, which is not
enough on its own to distinguish a real effect from run-to-run model
sampling noise. Results are appended to a SEPARATE file so the primary
dataset stays untouched.

Usage: python -m benchmark.run_repeats
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from benchmark.configurations import CONFIGURATIONS
from benchmark.dataset import TASKS
from benchmark.runner import run_one

RESULTS_PATH = Path(__file__).resolve().parent / "results" / "repeat_results.jsonl"
REPEAT_TASK_IDS = {"task01_simple_feature", "task02_bug_fix", "task08_seeded_defect"}


def main() -> None:
    tasks = [t for t in TASKS if t.task_id in REPEAT_TASK_IDS]
    total = len(CONFIGURATIONS) * len(tasks)
    done = 0
    with RESULTS_PATH.open("a", encoding="utf-8") as out:
        for config in CONFIGURATIONS:
            for task in tasks:
                t0 = time.monotonic()
                print(f"[{done + 1}/{total}] repeat: {task.task_id} under {config.name} ...", flush=True)
                record = run_one(task, config)
                record["repeat_run"] = True
                out.write(json.dumps(record) + "\n")
                out.flush()
                done += 1
                print(f"[{done}/{total}] DONE {task.task_id}/{config.name}: final_state={record['final_state']} "
                      f"wall={time.monotonic() - t0:.1f}s ground_truth_passed="
                      f"{record['ground_truth']['passed'] if record['ground_truth'] else 'N/A'}", flush=True)
    print("Repeat sweep complete.", flush=True)


if __name__ == "__main__":
    main()
