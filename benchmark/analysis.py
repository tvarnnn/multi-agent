"""Reads benchmark/results/raw_results.jsonl (produced by run_all.py) and
computes every metric PHASE8_REPORT.md reports on. Every function here is
a pure aggregation over already-collected MEASURED data - nothing in
this file runs a model or a tool call. Where a number is computed rather
than read directly off a raw field, it is a DERIVED metric; the report
labels each accordingly, not this file.
"""
from __future__ import annotations

import json
import statistics as stats
from pathlib import Path
from typing import Optional

RESULTS_PATH = Path(__file__).resolve().parent / "results" / "raw_results.jsonl"


def load_records(path: Path = RESULTS_PATH) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _mean(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return stats.mean(values) if values else None


def _median(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return stats.median(values) if values else None


def outcome_distribution(records: list[dict]) -> dict:
    by_config: dict = {}
    for r in records:
        by_config.setdefault(r["configuration"], {})
        by_config[r["configuration"]][r["final_state"]] = by_config[r["configuration"]].get(r["final_state"], 0) + 1
    return by_config


def iteration_and_latency_summary(records: list[dict]) -> dict:
    out: dict = {}
    for r in records:
        cfg = r["configuration"]
        out.setdefault(cfg, {"wall_clock_s": [], "model_call_count": [], "model_swap_count": [],
                              "tool_invocation_count": [], "state_transition_count": []})
        out[cfg]["wall_clock_s"].append(r["wall_clock_s"])
        out[cfg]["model_call_count"].append(r["model_call_count"])
        out[cfg]["model_swap_count"].append(r["model_swap_count"])
        out[cfg]["tool_invocation_count"].append(r["tool_invocation_count"])
        out[cfg]["state_transition_count"].append(r["state_transition_count"])
    summary = {}
    for cfg, series in out.items():
        summary[cfg] = {
            k: {"mean": _mean(v), "median": _median(v), "min": min(v) if v else None, "max": max(v) if v else None}
            for k, v in series.items()
        }
    return summary


def latency_breakdown_by_role(records: list[dict]) -> dict:
    out: dict = {}
    for r in records:
        cfg = r["configuration"]
        out.setdefault(cfg, {})
        for call in r["per_call"]:
            role = call["role"]
            out[cfg].setdefault(role, {
                "outer_total_s": [], "inner_generation_s": [], "context_retrieval_s": [],
                "ollama_load_duration_s": [], "ollama_eval_duration_s": [], "derived_prompt_processing_s": [],
            })
            bucket = out[cfg][role]
            bucket["outer_total_s"].append(call["outer_total_duration_s"])
            bucket["inner_generation_s"].append(call["inner_generation_duration_s"])
            bucket["context_retrieval_s"].append(call["context_retrieval_duration_s"])
            if "ollama_load_duration_ns" in call:
                bucket["ollama_load_duration_s"].append(call["ollama_load_duration_ns"] / 1e9)
                bucket["ollama_eval_duration_s"].append(call["ollama_eval_duration_ns"] / 1e9)
                bucket["derived_prompt_processing_s"].append(call["derived_prompt_processing_ns"] / 1e9)
    summary: dict = {}
    for cfg, roles in out.items():
        summary[cfg] = {}
        for role, series in roles.items():
            summary[cfg][role] = {k: {"mean": _mean(v), "median": _median(v), "n": len(v)} for k, v in series.items()}
    return summary


def model_swap_overhead(records: list[dict]) -> dict:
    out: dict = {}
    for r in records:
        cfg = r["configuration"]
        out.setdefault(cfg, {"swap_load_s": [], "no_swap_load_s": []})
        for call in r["per_call"]:
            if "ollama_load_duration_ns" not in call:
                continue
            load_s = call["ollama_load_duration_ns"] / 1e9
            if call["was_model_swap"]:
                out[cfg]["swap_load_s"].append(load_s)
            else:
                out[cfg]["no_swap_load_s"].append(load_s)
    summary = {}
    for cfg, series in out.items():
        swap_mean = _mean(series["swap_load_s"])
        no_swap_mean = _mean(series["no_swap_load_s"])
        summary[cfg] = {
            "swap_load_s_mean": swap_mean, "swap_n": len(series["swap_load_s"]),
            "no_swap_load_s_mean": no_swap_mean, "no_swap_n": len(series["no_swap_load_s"]),
            "derived_swap_overhead_s": (swap_mean - no_swap_mean) if (swap_mean is not None and no_swap_mean is not None) else None,
        }
    return summary


def vram_summary(records: list[dict]) -> dict:
    out: dict = {}
    for r in records:
        cfg = r["configuration"]
        out.setdefault(cfg, {"baseline_mib": [], "peak_mib": []})
        out[cfg]["baseline_mib"].append(r["vram_baseline_mib"])
        out[cfg]["peak_mib"].append(r["vram_peak_mib"])
    return {cfg: {"baseline_mean": _mean(v["baseline_mib"]), "peak_mean": _mean(v["peak_mib"]),
                  "peak_max": max([x for x in v["peak_mib"] if x is not None], default=None)}
            for cfg, v in out.items()}


def _confusion(pairs: list[tuple[str, bool]]) -> dict:
    tp = sum(1 for d, gt in pairs if d == "REJECT" and gt is False)   # correctly flagged a real problem
    tn = sum(1 for d, gt in pairs if d == "APPROVE" and gt is True)   # correctly approved good code
    fp = sum(1 for d, gt in pairs if d == "APPROVE" and gt is False)  # wrongly approved broken code
    fn = sum(1 for d, gt in pairs if d == "REJECT" and gt is True)    # wrongly rejected correct code
    n = tp + tn + fp + fn
    return {
        "n": n, "true_positive_correctly_rejected_bad": tp, "true_negative_correctly_approved_good": tn,
        "false_positive_wrongly_approved_bad": fp, "false_negative_wrongly_rejected_good": fn,
        "false_positive_rate": (fp / (fp + tn)) if (fp + tn) else None,
        "false_negative_rate": (fn / (fn + tp)) if (fn + tp) else None,
        "accuracy": ((tp + tn) / n) if n else None,
    }


def reviewer_internal_gate_agreement(records: list[dict]) -> dict:
    """Reviewer decision vs the orchestrator's OWN composite validator
    result, captured at every review cycle (per-cycle granularity)."""
    out: dict = {}
    malformed: dict = {}
    for r in records:
        cfg = r["configuration"]
        out.setdefault(cfg, [])
        malformed.setdefault(cfg, [0, 0])
        for call in r["per_call"]:
            if call["role"] != "reviewer":
                continue
            malformed[cfg][1] += 1
            d, vp = call["reviewer_decision"], call["validation_passed_at_review_time"]
            if d in ("APPROVE", "REJECT") and vp is not None:
                out[cfg].append((d, vp))
            else:
                malformed[cfg][0] += 1
    return {cfg: {**_confusion(pairs), "malformed_or_unparseable_reviewer_outputs": malformed[cfg][0],
                  "total_reviewer_calls": malformed[cfg][1]}
            for cfg, pairs in out.items()}


def reviewer_final_ground_truth_agreement(records: list[dict]) -> dict:
    """Reviewer's LAST decision in a run vs the harness's independently
    re-executed hidden-test ground truth for that task, for tasks where a
    ground truth is even applicable (excludes the two deliberately
    ambiguous tasks)."""
    out: dict = {}
    excluded: dict = {}
    for r in records:
        cfg = r["configuration"]
        out.setdefault(cfg, [])
        excluded.setdefault(cfg, 0)
        gt = r["ground_truth"]
        reviewer_calls = [c for c in r["per_call"] if c["role"] == "reviewer" and c["reviewer_decision"] in ("APPROVE", "REJECT")]
        if gt is None or not gt["applicable"] or not reviewer_calls:
            excluded[cfg] += 1
            continue
        last_decision = reviewer_calls[-1]["reviewer_decision"]
        out[cfg].append((last_decision, gt["passed"]))
    return {cfg: {**_confusion(pairs), "excluded_tasks_no_ground_truth_or_no_reviewer_call": excluded[cfg]}
            for cfg, pairs in out.items()}


def stall_detection_summary(records: list[dict]) -> dict:
    out: dict = {}
    for r in records:
        cfg = r["configuration"]
        out.setdefault(cfg, {"escalations": 0, "reasons": []})
        if r["final_state"] == "ESCALATE_TO_USER":
            out[cfg]["escalations"] += 1
            out[cfg]["reasons"].extend(r["stuck_reasons"])
    return out


def build_full_summary(records: list[dict]) -> dict:
    return {
        "n_records": len(records),
        "outcome_distribution": outcome_distribution(records),
        "iteration_and_latency": iteration_and_latency_summary(records),
        "latency_by_role": latency_breakdown_by_role(records),
        "model_swap_overhead": model_swap_overhead(records),
        "vram": vram_summary(records),
        "reviewer_internal_gate_agreement": reviewer_internal_gate_agreement(records),
        "reviewer_final_ground_truth_agreement": reviewer_final_ground_truth_agreement(records),
        "stall_detection": stall_detection_summary(records),
    }


if __name__ == "__main__":
    recs = load_records()
    summary = build_full_summary(recs)
    out_path = Path(__file__).resolve().parent / "results" / "analysis_summary.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
