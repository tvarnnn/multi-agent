"""Prompt construction, one function per role. Each function only ever
reads the fields Phase 1's orchestrator actually puts in that role's
context dict - Coder's builder never looks for a "request" key (raw user
conversation), Reviewer's builder never looks for a "summary" key from
CoderCompleted (the coder's own narrative framing of its work). Context
isolation here is enforced by what these functions choose to read, not by
trusting the caller to have already stripped anything.
"""
from __future__ import annotations


def build_planner_prompt(context: dict) -> str:
    if "blocking_questions" in context:
        spec = context["spec"]
        questions = "\n".join(f"- {q}" for q in context["blocking_questions"])
        return (
            "You are the Planner for an autonomous software engineering platform. "
            "The Coder is blocked and needs clarification before it can continue.\n\n"
            f"Current goals: {list(spec.goals)}\n"
            f"Current constraints: {list(spec.constraints)}\n"
            f"Current acceptance criteria: {list(spec.acceptance_criteria)}\n\n"
            f"Coder's blocking questions:\n{questions}\n\n"
            "Resolve these questions using only the information already available. "
            "If a genuinely new product decision is needed that only a human user could "
            'make, respond with kind "needs_user_input" and a single clear question. '
            'Otherwise respond with kind "spec" and the complete, updated goals, '
            "constraints, and acceptance_criteria (repeat unchanged fields as-is)."
        )
    request = context["request"]
    is_amendment = context.get("amendment", False)
    framing = "amend the existing" if is_amendment else "produce a new"
    return (
        f"You are the Planner for an autonomous software engineering platform. "
        f"Your job is to {framing} implementation specification from the user's request "
        f"below.\n\nUser request: {request}\n\n"
        'If the request is clear enough to specify, respond with kind "spec" and concrete '
        "goals, constraints, and acceptance_criteria as lists of short strings. Prefer at "
        "least one acceptance criterion of the form 'file:<relative-path>' naming a "
        "concrete file the implementation must create, since that is the only kind of "
        "criterion this platform can verify automatically right now. If a genuine product "
        'decision is missing that only the user can make, respond with kind '
        '"needs_user_input" and a single clear question instead.'
    )


def build_coder_prompt(context: dict) -> str:
    spec = context["spec"]
    feedback = context.get("reviewer_feedback")
    parts = [
        "You are the Coder for an autonomous software engineering platform. "
        "You implement the specification below by returning file writes as structured "
        "output - you do not have direct file access, only this structured response.\n\n"
        f"Specification version: {spec.version_label}\n"
        f"Goals: {list(spec.goals)}\n"
        f"Constraints: {list(spec.constraints)}\n"
        f"Acceptance criteria: {list(spec.acceptance_criteria)}\n"
    ]
    if feedback is not None:
        issues = "\n".join(
            f"- [{i.severity}] {i.file}: {i.description} (required fix: {i.required_fix})"
            for i in feedback.issues
        )
        parts.append(f"\nThe previous attempt was rejected by the reviewer:\n{issues}\n")
    parts.append(
        '\nIf you have enough information, respond with status "completed", the exact '
        f'spec_version_label "{spec.version_label}", a short summary, and file_writes '
        "(a list of {path, content} objects) implementing every acceptance criterion. "
        "If a genuine requirement is ambiguous and you cannot safely proceed, respond with "
        f'status "blocked", the exact spec_version_label "{spec.version_label}", a reason, '
        "what you attempted, and blocking_questions."
    )
    return "".join(parts)


def build_reviewer_prompt(context: dict) -> str:
    spec = context["spec"]
    coder_output = context["coder_output"]
    validation_result = context["validation_result"]
    files = "\n\n".join(
        f"--- {w.path} ---\n{w.content}" for w in coder_output.file_writes
    ) or "(no files were written)"
    validation_lines = "\n".join(validation_result.details) or "(no acceptance criteria to check)"
    return (
        "You are the Reviewer for an autonomous software engineering platform. "
        "You independently judge whether the implementation below satisfies the "
        "specification. You are not told why the Coder made its choices - judge the "
        "artifacts on their own merits.\n\n"
        f"Specification version: {spec.version_label}\n"
        f"Goals: {list(spec.goals)}\n"
        f"Constraints: {list(spec.constraints)}\n"
        f"Acceptance criteria: {list(spec.acceptance_criteria)}\n\n"
        f"Deterministic validation results:\n{validation_lines}\n\n"
        f"Files written:\n{files}\n\n"
        f'Respond with the exact spec_version_label "{spec.version_label}", a decision of '
        '"APPROVE" or "REJECT", requirements_met, security_ok, and validation_ok as '
        "booleans, and issues (a list of {severity, file, description, required_fix} "
        "objects, empty if none)."
    )
