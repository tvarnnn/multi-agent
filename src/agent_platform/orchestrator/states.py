"""The Phase 1 lifecycle state machine, per architecture-review-v3's
revised state diagram. AWAITING_USER_INPUT (routine - the Planner needs
one fact from the user) and STUCK (abnormal - iteration exhaustion or a
detected stall) are deliberately distinct states, never merged - see
architecture-review-v3-agent-interaction.md section 1.3 for why.
"""
from __future__ import annotations

from enum import Enum


class State(Enum):
    RECEIVE_REQUEST = "RECEIVE_REQUEST"
    PLAN = "PLAN"
    AWAITING_USER_INPUT = "AWAITING_USER_INPUT"
    VALIDATE_PLAN = "VALIDATE_PLAN"
    IMPLEMENT = "IMPLEMENT"
    BLOCKED = "BLOCKED"
    RESOLVE_CLARIFICATION = "RESOLVE_CLARIFICATION"
    TEST = "TEST"
    REVIEW = "REVIEW"
    FEEDBACK = "FEEDBACK"
    IMPLEMENT_FIX = "IMPLEMENT_FIX"
    AMEND_REQUIREMENTS = "AMEND_REQUIREMENTS"
    FINAL_VALIDATION = "FINAL_VALIDATION"
    STUCK = "STUCK"
    ESCALATE_TO_USER = "ESCALATE_TO_USER"
    COMPLETE = "COMPLETE"


TERMINAL_STATES = frozenset({State.COMPLETE, State.ESCALATE_TO_USER})
