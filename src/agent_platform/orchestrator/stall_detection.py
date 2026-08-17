"""Stall-detection heuristics that refine the EXISTING FEEDBACK ->
IMPLEMENT_FIX / STUCK decision and the EXISTING IMPLEMENT write-
application step Phase 1 already has - no new states, no new
transitions, just additional signals for when the fix loop is going
nowhere before the raw iteration cap is hit (architecture-review-v2.md
section 1.9's "non-progress" signals, named there and implemented here
for the first time).
"""
from __future__ import annotations


def is_negligible_diff(previous_writes, new_writes) -> bool:
    if not previous_writes or not new_writes:
        return False
    prev = {w.path: w.content for w in previous_writes}
    new = {w.path: w.content for w in new_writes}
    return prev == new


def is_repeated_review_rejection(review_issue_history: tuple) -> bool:
    if len(review_issue_history) < 2:
        return False
    last_two = review_issue_history[-2:]
    if not last_two[0] or not last_two[1]:
        return False
    return frozenset(last_two[0]) == frozenset(last_two[1])


def is_repeated_identical_test_failure(validation_detail_history: tuple) -> bool:
    if len(validation_detail_history) < 2:
        return False
    last_two = validation_detail_history[-2:]
    return last_two[0] == last_two[1] and len(last_two[0]) > 0
