"""Core security enums. LLMs never make security decisions - these three
enums are the entire vocabulary the deterministic evaluator uses, and no
model output is ever parsed into one of these values."""
from __future__ import annotations

from enum import Enum


class Role(Enum):
    PLANNER = "PLANNER"
    CODER = "CODER"
    REVIEWER = "REVIEWER"


class SessionMode(Enum):
    AUTO = "AUTO"
    CONFIRMATION = "CONFIRMATION"
    MANUAL = "MANUAL"


class ToolPermission(Enum):
    ALLOW = "ALLOW"
    CONFIRM = "CONFIRM"
    DENY = "DENY"


class OperatingMode(Enum):
    """What kind of session this is - orthogonal to Role (who's acting)
    and SessionMode (how much approval friction applies). Immutable for
    the lifetime of one Orchestrator instance; switching modes means
    starting a new session, never mutating this value in place."""
    CHAT = "CHAT"
    PLAN = "PLAN"
    CODE = "CODE"
    EDIT = "EDIT"
    REVIEW = "REVIEW"
