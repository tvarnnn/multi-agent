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


# ----------------------------------------------------------- Phase 9 (Planning Mode)
#
# Added in Phase 12, when a real live end-to-end test discovered these were
# never written for a real model - only FakeModelProvider ever exercised
# Planning Mode. Same "only read the fields this role's context dict
# actually has" discipline as the three builders above.

def _format_context_bundle(bundle) -> str:
    if not bundle.files:
        return "(no project context retrieved)"
    return "\n\n".join(f"--- {f.path} ({f.category}) ---\n{f.content}" for f in bundle.files)


def build_planner_plan_mode_prompt(context: dict) -> str:
    request = context["request"]
    bundle = context["context_bundle"]
    parts = [
        "You are the Planner for an autonomous software engineering platform, running in "
        "Planning Mode: you produce a structured implementation plan for human review before "
        "any code is written - you do not write code yourself.\n\n"
        f"User request: {request}\n\n"
        f"Project context:\n{_format_context_bundle(bundle)}\n\n"
    ]
    if "previous_plan" in context:
        p = context["previous_plan"]
        parts.append(
            f"Current draft objective: {p.objective}\n"
            f"Revision request: {context.get('revision_request', '')}\n\n"
        )
    if context.get("research_observations"):
        obs = "\n".join(
            f"- {o['capability']} ({o['query']}): {o['status']}" for o in context["research_observations"]
        )
        parts.append(f"Research already performed:\n{obs}\n\n")
    parts.append(
        'If you have enough information, respond with kind "plan" and a complete structured '
        "plan: objective, requirements, existing_context, proposed_architecture, "
        "files_to_create, files_to_modify, dependencies, implementation_steps, "
        "validation_strategy, risks, unknowns, and acceptance_criteria (all as lists of short "
        "strings except objective/proposed_architecture, which are single strings). If a "
        'genuine product decision is missing, respond with kind "needs_user_input" and a '
        "single clear question. Only if you need to look something up via an available "
        'research capability, respond with kind "research_request" and a list of '
        "{capability, query} objects."
    )
    return "".join(parts)


def build_reviewer_plan_critique_prompt(context: dict) -> str:
    plan = context["plan"]
    return (
        "You are the Reviewer for an autonomous software engineering platform, critiquing a "
        "Planner's draft plan before a human sees it. You do not approve or block anything - "
        "your feedback is advisory only.\n\n"
        f"Objective: {plan.objective}\n"
        f"Requirements: {list(plan.requirements)}\n"
        f"Proposed architecture: {plan.proposed_architecture}\n"
        f"Files to create: {list(plan.files_to_create)}\n"
        f"Files to modify: {list(plan.files_to_modify)}\n"
        f"Acceptance criteria: {list(plan.acceptance_criteria)}\n\n"
        "Respond with comments, missing_requirements, security_concerns, and "
        "unnecessary_complexity, each a list of short strings (empty lists if you have nothing "
        "to add in that category)."
    )


def build_chat_prompt(context: dict) -> str:
    message = context["message"]
    bundle = context["context_bundle"]
    return (
        "You are the Planner for an autonomous software engineering platform, in Chat Mode: a "
        "read-only conversational assistant. You cannot write files or run commands here.\n\n"
        f"Project context:\n{_format_context_bundle(bundle)}\n\n"
        f"User message: {message}\n\n"
        "Respond with a single field, message, containing your reply as a string."
    )


def build_review_session_prompt(context: dict) -> str:
    target = context["target"]
    bundle = context["context_bundle"]
    return (
        "You are the Reviewer for an autonomous software engineering platform, in Review Mode: "
        "asked to review something specific on request, independent of any active "
        "implementation task.\n\n"
        f"Review target: {target}\n\n"
        f"Project context:\n{_format_context_bundle(bundle)}\n\n"
        "Respond with summary (a short string) and findings (a list of short strings, empty if "
        "none)."
    )
