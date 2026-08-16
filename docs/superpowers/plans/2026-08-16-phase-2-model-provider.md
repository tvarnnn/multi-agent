> **STATUS: COMPLETE 2026-08-16.** All 8 tasks implemented. Deterministic
> suite: 570/570 passing, 0 network. Real Ollama integration suite: 5/5
> passing against the actual RTX 5070 and both real models. See
> `../../../PHASE2_REPORT.md` for full measurements. Per the standing
> instruction, no further phase was started.

# Phase 2 Model Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `FakeModelProvider` with a real `OllamaModelProvider` that
the Phase 1 orchestrator can use without any change to its own code, then
measure real load time, inference latency, VRAM, and context behavior on
this machine's RTX 5070 against the actual pulled models.

**Architecture:** A `ModelProvider` Protocol formalizes the duck-typed
contract `Orchestrator` already relies on (`.plan()`/`.code()`/`.review()`
each taking a context dict and returning a raw dict). `OllamaModelProvider`
implements it via Ollama's HTTP API (`/api/generate`), using an injectable
transport function so the retry/timeout/lifecycle logic is fully unit-
testable with a fake transport (Tasks 1-6, no network) before any real
call is made (Task 7). Prompts are built per-role from exactly the fields
Phase 1's orchestrator already puts in each context dict — nothing new is
added to those dicts, so context isolation (Coder never sees raw user
conversation or Planner's reasoning; Reviewer never sees Coder's summary/
justification) is enforced by what Phase 1 already does, not by new
orchestrator logic. Structured output is constrained at the Ollama layer
via a JSON-schema `format` parameter (grammar-constrained decoding, per
`architecture-review-v2.md` §1.11) *and* still re-validated by Phase 1's
existing `model_schemas.py` parsers — two layers, no single point of
trust in model output.

**Tech Stack:** Python 3.12.5 standard library only (`urllib.request` for
HTTP — no new dependency) for Tasks 1-6. Task 7 additionally uses the
already-running local Ollama server (confirmed reachable at
`http://localhost:11434`, version 0.32.13) and `nvidia-smi` (confirmed
present, RTX 5070, 12227MiB VRAM) via `subprocess`.

**Spec:** `architecture-review-v2.md`, `architecture-review-v3-agent-
interaction.md`, `architecture-review-v4-human-controlled-git.md`, Phase 1
(`orchestrator/core.py`, `orchestrator/fake_model.py`,
`orchestrator/model_schemas.py`), `PHASE1_REPORT.md`.

## Global Constraints

- Models confirmed present via `ollama list` on this machine:
  `phi4-reasoning:plus` (11 GB) for Planner and Reviewer (shared weights,
  separate contexts per call — never a shared conversation),
  `qwen2.5-coder:14b` (9.0 GB) for Coder. This overrides the earlier
  Llama-3.1-8B-Instruct reviewer decision from this session — flagged to
  the user, proceeding on the latest explicit instruction.
- `orchestrator/core.py` is not modified in this phase. `OllamaModelProvider`
  must be a drop-in replacement for `FakeModelProvider` — same three
  methods, same context-dict shapes in, same raw-dict shapes out. If a
  test needs to change `core.py` to make the real provider work, that is a
  plan defect to flag, not a change to make silently.
- The typed tool gateway from Phase 1 is untouched and still the only path
  to file writes — the model provider only ever returns dicts for the
  orchestrator to parse; it never touches the filesystem itself.
- Git remains read-only for the agent — nothing in this phase adds any
  git-write capability. No git commands run in this session (per the
  standing instruction).
- No model is assumed to stay resident. `OllamaModelProvider` explicitly
  requests unload (`keep_alive: 0`) of the previously-loaded model before
  switching to a different one — two 14B-class models resident
  simultaneously (11 GB + 9 GB) would leave near-zero headroom on a 12 GB
  card. Since Planner and Reviewer share `phi4-reasoning:plus`, the actual
  swap set is two models, not three, matching `architecture-review-v2.md`
  §7's scheduling recommendation.
- MCP is not implemented in this phase, per the explicit instruction.
- Tasks 1-6 run with zero network access (fake transport, injected).
  Task 7 is explicitly the first task in this project that uses the
  network (localhost Ollama only) and real GPU inference — clearly
  separated so `tests/` as a whole no longer has a single "no network"
  guarantee once Task 7's file exists; that file is documented as the one
  exception.

---

### Task 1: `ModelProvider` protocol

**Files:**
- Create: `src/agent_platform/orchestrator/model_provider.py`
- Create: `tests/test_model_provider_protocol.py`

**Interfaces:**
- Produces: `class ModelProvider(Protocol)` with `plan(context: dict) ->
  dict`, `code(context: dict) -> dict`, `review(context: dict) -> dict`.
  Purely structural (a `Protocol`, not an ABC) — `FakeModelProvider`
  already satisfies it without inheriting from anything, and Task 4's
  `OllamaModelProvider` will too.

- [ ] **Step 1: Write the failing test**

`tests/test_model_provider_protocol.py`:
```python
from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.orchestrator.model_provider import ModelProvider


def test_fake_model_provider_satisfies_the_protocol():
    provider: ModelProvider = FakeModelProvider()
    assert hasattr(provider, "plan")
    assert hasattr(provider, "code")
    assert hasattr(provider, "review")


def test_protocol_is_structural_not_nominal():
    class Anything:
        def plan(self, context: dict) -> dict:
            return {}

        def code(self, context: dict) -> dict:
            return {}

        def review(self, context: dict) -> dict:
            return {}

    instance: ModelProvider = Anything()
    assert instance.plan({}) == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_model_provider_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named
'agent_platform.orchestrator.model_provider'`

- [ ] **Step 3: Implement**

`src/agent_platform/orchestrator/model_provider.py`:
```python
"""Formalizes the ModelProvider contract Orchestrator already relies on
via duck typing (see orchestrator/core.py's constructor, which accepts
any object with .plan/.code/.review). FakeModelProvider (Phase 1) and
OllamaModelProvider (Phase 2, and any future llama.cpp provider) all
satisfy this without inheriting from it - it exists so provider
implementations and their tests have one shared, explicit contract to
type against.
"""
from __future__ import annotations

from typing import Protocol


class ModelProvider(Protocol):
    def plan(self, context: dict) -> dict: ...
    def code(self, context: dict) -> dict: ...
    def review(self, context: dict) -> dict: ...
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_model_provider_protocol.py -v`
Expected: PASS (2 tests)

---

### Task 2: Structured-output JSON schemas

**Files:**
- Create: `src/agent_platform/orchestrator/ollama_schemas.py`
- Create: `tests/test_ollama_schemas.py`

**Interfaces:**
- Produces: `PLANNER_SCHEMA`, `CODER_SCHEMA`, `REVIEWER_SCHEMA` — plain
  `dict` JSON Schema objects matching exactly the fields
  `model_schemas.py`'s `parse_planner_output` / `parse_coder_output` /
  `parse_reviewer_output` (Phase 1) look for. Task 4 passes these as the
  Ollama `format` parameter (grammar-constrained decoding at the model
  layer); Phase 1's parsers remain the second, independent validation
  layer — this task's schemas are a syntactic constraint, not a
  replacement for that semantic validation.

- [ ] **Step 1: Write the failing tests**

`tests/test_ollama_schemas.py`:
```python
import json

from agent_platform.orchestrator.ollama_schemas import (
    CODER_SCHEMA,
    PLANNER_SCHEMA,
    REVIEWER_SCHEMA,
)


def test_all_schemas_are_json_serializable():
    for schema in (PLANNER_SCHEMA, CODER_SCHEMA, REVIEWER_SCHEMA):
        json.dumps(schema)  # raises if not serializable


def test_planner_schema_covers_every_field_the_parser_reads():
    props = set(PLANNER_SCHEMA["properties"])
    assert props == {"kind", "goals", "constraints", "acceptance_criteria", "question"}
    assert PLANNER_SCHEMA["required"] == ["kind"]


def test_coder_schema_covers_every_field_the_parser_reads():
    props = set(CODER_SCHEMA["properties"])
    assert props == {"status", "spec_version_label", "summary", "file_writes",
                      "reason", "attempted", "blocking_questions"}
    assert set(CODER_SCHEMA["required"]) == {"status", "spec_version_label"}


def test_coder_schema_file_writes_items_require_path_and_content():
    item_schema = CODER_SCHEMA["properties"]["file_writes"]["items"]
    assert set(item_schema["required"]) == {"path", "content"}


def test_reviewer_schema_covers_every_field_the_parser_reads():
    props = set(REVIEWER_SCHEMA["properties"])
    assert props == {"spec_version_label", "decision", "requirements_met",
                      "security_ok", "validation_ok", "issues"}
    assert set(REVIEWER_SCHEMA["required"]) == {
        "spec_version_label", "decision", "requirements_met", "security_ok", "validation_ok"
    }


def test_reviewer_schema_issue_items_require_all_four_fields():
    item_schema = REVIEWER_SCHEMA["properties"]["issues"]["items"]
    assert set(item_schema["required"]) == {"severity", "file", "description", "required_fix"}
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_ollama_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/agent_platform/orchestrator/ollama_schemas.py`:
```python
"""JSON Schema objects passed as Ollama's `format` parameter to
grammar-constrain each role's output at the model layer (architecture-
review-v2.md section 1.11). Field sets here are deliberately kept in
lockstep with orchestrator/model_schemas.py's parse functions - this is
the syntactic half of structured output; the semantic half (are the
right fields present for this "kind"/"status"/"decision") is still
enforced there, independently.
"""
from __future__ import annotations

PLANNER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["spec", "needs_user_input"]},
        "goals": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        "question": {"type": "string"},
    },
    "required": ["kind"],
}

CODER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["completed", "blocked"]},
        "spec_version_label": {"type": "string"},
        "summary": {"type": "string"},
        "file_writes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
        "reason": {"type": "string"},
        "attempted": {"type": "string"},
        "blocking_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "spec_version_label"],
}

REVIEWER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "spec_version_label": {"type": "string"},
        "decision": {"type": "string", "enum": ["APPROVE", "REJECT"]},
        "requirements_met": {"type": "boolean"},
        "security_ok": {"type": "boolean"},
        "validation_ok": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string"}, "file": {"type": "string"},
                    "description": {"type": "string"}, "required_fix": {"type": "string"},
                },
                "required": ["severity", "file", "description", "required_fix"],
            },
        },
    },
    "required": ["spec_version_label", "decision", "requirements_met", "security_ok", "validation_ok"],
}
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_ollama_schemas.py -v`
Expected: PASS (6 tests)

---

### Task 3: Prompt builders (context isolation, enforced by field selection)

**Files:**
- Create: `src/agent_platform/orchestrator/prompts.py`
- Create: `tests/test_prompts.py`

**Interfaces:**
- Consumes: `SpecVersion` (Phase 0), `ReviewerOutput`/`CoderCompleted`
  (Phase 1's `model_schemas.py`), `ValidationResult` (Phase 1's
  `validation.py`)
- Produces: `build_planner_prompt(context: dict) -> str`,
  `build_coder_prompt(context: dict) -> str`,
  `build_reviewer_prompt(context: dict) -> str`. Task 4's
  `OllamaModelProvider` calls exactly these three functions with exactly
  the context dicts `Orchestrator` already constructs.

- [ ] **Step 1: Write the failing tests**

`tests/test_prompts.py`:
```python
from agent_platform.orchestrator.model_schemas import CoderCompleted, CoderFileWrite, ReviewerOutput, ReviewerIssue
from agent_platform.orchestrator.prompts import build_coder_prompt, build_planner_prompt, build_reviewer_prompt
from agent_platform.orchestrator.validation import ValidationResult
from agent_platform.spec.versioning import SpecStore


def _spec(**kwargs):
    store = SpecStore()
    defaults = {"goals": ["build app"], "constraints": ["no network"], "acceptance_criteria": ["file:app.py"]}
    defaults.update(kwargs)
    return store.create("task-1", **defaults)


def test_planner_prompt_includes_the_user_request():
    prompt = build_planner_prompt({"request": "build me a FastAPI app"})
    assert "build me a FastAPI app" in prompt


def test_planner_clarification_prompt_includes_blocking_questions_and_spec():
    spec = _spec()
    prompt = build_planner_prompt({"spec": spec, "blocking_questions": ["OAuth or API keys?"]})
    assert "OAuth or API keys?" in prompt
    assert "build app" in prompt


def test_coder_prompt_includes_spec_and_exact_version_label():
    spec = _spec()
    prompt = build_coder_prompt({"spec": spec, "reviewer_feedback": None})
    assert spec.version_label in prompt
    assert "file:app.py" in prompt


def test_coder_prompt_includes_reviewer_feedback_when_present():
    spec = _spec()
    feedback = ReviewerOutput(spec_version_label=spec.version_label, decision="REJECT",
                               requirements_met=False, security_ok=True, validation_ok=True,
                               issues=(ReviewerIssue(severity="high", file="app.py",
                                                      description="missing auth",
                                                      required_fix="add auth check"),))
    prompt = build_coder_prompt({"spec": spec, "reviewer_feedback": feedback})
    assert "missing auth" in prompt
    assert "add auth check" in prompt


def test_coder_prompt_never_includes_raw_user_conversation_text():
    # Phase 1's orchestrator never puts "request" in the coder context to
    # begin with - this proves the prompt builder doesn't reach for it
    # even if it were accidentally present.
    spec = _spec()
    prompt = build_coder_prompt({"spec": spec, "reviewer_feedback": None, "request": "SECRET USER TEXT"})
    assert "SECRET USER TEXT" not in prompt


def test_reviewer_prompt_includes_files_and_validation_but_not_coder_summary():
    spec = _spec()
    coder_output = CoderCompleted(spec_version_label=spec.version_label,
                                   summary="I cleverly used a singleton pattern here",
                                   file_writes=(CoderFileWrite(path="app.py", content="print('hi')"),))
    validation_result = ValidationResult(passed=True, details=("OK: file:app.py",))
    prompt = build_reviewer_prompt({"spec": spec, "coder_output": coder_output,
                                     "validation_result": validation_result})
    assert "print('hi')" in prompt
    assert "OK: file:app.py" in prompt
    assert "singleton" not in prompt


def test_reviewer_prompt_includes_exact_spec_version_label():
    spec = _spec()
    coder_output = CoderCompleted(spec_version_label=spec.version_label, summary="s", file_writes=())
    validation_result = ValidationResult(passed=True, details=())
    prompt = build_reviewer_prompt({"spec": spec, "coder_output": coder_output,
                                     "validation_result": validation_result})
    assert spec.version_label in prompt
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/agent_platform/orchestrator/prompts.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: PASS (7 tests)

---

### Task 4: `OllamaModelProvider` — invocation, timeout, retries, malformed output

**Files:**
- Create: `src/agent_platform/orchestrator/ollama_provider.py`
- Create: `tests/test_ollama_provider.py`

**Interfaces:**
- Consumes: `ModelProvider` (Task 1), `PLANNER_SCHEMA`/`CODER_SCHEMA`/
  `REVIEWER_SCHEMA` (Task 2), `build_planner_prompt`/`build_coder_prompt`/
  `build_reviewer_prompt` (Task 3), `ModelTimeoutError` (Phase 1's
  `fake_model.py` — reused as-is, the shared timeout contract both
  providers raise, not moved or renamed)
- Produces: `class OllamaTransportError(Exception)`;
  `default_http_post(url: str, payload: dict, timeout: float) -> dict`;
  `@dataclass(frozen=True) class OllamaCallResult(load_duration_ns,
  eval_duration_ns, total_duration_ns, prompt_eval_count, eval_count)`;
  `class OllamaModelProvider` with constructor `OllamaModelProvider(*,
  planner_model: str, coder_model: str, reviewer_model: str, base_url:
  str = "http://localhost:11434", http_post=default_http_post,
  timeout_seconds: float = 120.0, max_transport_retries: int = 2)`,
  methods `plan/code/review` matching `ModelProvider`, and attribute
  `telemetry_log: list[OllamaCallResult]`. Task 5 adds the load/unload
  lifecycle test coverage for behavior already implemented here (write
  `_ensure_loaded` now, Task 5 just adds tests for it — don't leave it
  half-built waiting for Task 5).

- [ ] **Step 1: Write the failing tests**

`tests/test_ollama_provider.py`:
```python
import pytest

from agent_platform.orchestrator.fake_model import ModelTimeoutError
from agent_platform.orchestrator.ollama_provider import OllamaModelProvider, OllamaTransportError
from agent_platform.spec.versioning import SpecStore


def _spec():
    return SpecStore().create("task-1", goals=["g"], constraints=[], acceptance_criteria=["file:app.py"])


def make_fake_transport(responses):
    calls = []

    def fake_http_post(url, payload, timeout):
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        if not responses:
            raise OllamaTransportError("fake transport exhausted")
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return fake_http_post, calls


def _ok_response(body: dict, **timing):
    return {
        "response": __import__("json").dumps(body),
        "load_duration": timing.get("load_duration", 100),
        "eval_duration": timing.get("eval_duration", 200),
        "total_duration": timing.get("total_duration", 300),
        "prompt_eval_count": timing.get("prompt_eval_count", 10),
        "eval_count": timing.get("eval_count", 20),
    }


def test_plan_calls_the_configured_planner_model():
    transport, calls = make_fake_transport([_ok_response({"kind": "needs_user_input", "question": "q?"})])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    result = provider.plan({"request": "build something"})
    assert result == {"kind": "needs_user_input", "question": "q?"}
    assert calls[0]["payload"]["model"] == "phi4-reasoning:plus"


def test_code_calls_the_configured_coder_model():
    transport, calls = make_fake_transport([_ok_response({"status": "blocked", "spec_version_label": "task-1-v1",
                                                            "reason": "r", "attempted": "a",
                                                            "blocking_questions": ["q?"]})])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.code({"spec": _spec(), "reviewer_feedback": None})
    assert calls[0]["payload"]["model"] == "qwen2.5-coder:14b"


def test_request_includes_the_json_schema_format_and_is_stateless():
    transport, calls = make_fake_transport([_ok_response({"kind": "spec", "goals": [], "constraints": [],
                                                            "acceptance_criteria": []})])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.plan({"request": "x"})
    assert calls[0]["payload"]["format"]["type"] == "object"
    assert calls[0]["payload"]["stream"] is False
    assert "messages" not in calls[0]["payload"]  # single-shot generate, no chat history


def test_malformed_json_response_returns_sentinel_dict_not_raise():
    transport, _ = make_fake_transport([{"response": "not valid json{{{", "load_duration": 0,
                                          "eval_duration": 0, "total_duration": 0,
                                          "prompt_eval_count": 0, "eval_count": 0}])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    result = provider.plan({"request": "x"})
    assert "_malformed_raw_text" in result


def test_transport_error_retries_then_succeeds():
    transport, calls = make_fake_transport([
        OllamaTransportError("connection reset"),
        _ok_response({"kind": "spec", "goals": [], "constraints": [], "acceptance_criteria": []}),
    ])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport,
                                    max_transport_retries=2)
    result = provider.plan({"request": "x"})
    assert result["kind"] == "spec"
    assert len(calls) == 2


def test_transport_error_exhausting_retries_raises_model_timeout_error():
    transport, _ = make_fake_transport([
        OllamaTransportError("e1"), OllamaTransportError("e2"),
    ])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport,
                                    max_transport_retries=2)
    with pytest.raises(ModelTimeoutError):
        provider.plan({"request": "x"})


def test_telemetry_log_records_durations_and_counts():
    transport, _ = make_fake_transport([_ok_response(
        {"kind": "spec", "goals": [], "constraints": [], "acceptance_criteria": []},
        load_duration=555, eval_duration=777, total_duration=1332, prompt_eval_count=42, eval_count=99)])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.plan({"request": "x"})
    assert len(provider.telemetry_log) == 1
    entry = provider.telemetry_log[0]
    assert entry.load_duration_ns == 555
    assert entry.eval_duration_ns == 777
    assert entry.total_duration_ns == 1332
    assert entry.prompt_eval_count == 42
    assert entry.eval_count == 99
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_ollama_provider.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/agent_platform/orchestrator/ollama_provider.py`:
```python
"""Real ModelProvider backed by Ollama's HTTP API. Drop-in replacement
for FakeModelProvider - Orchestrator imports neither this module nor
fake_model.py, it only ever calls .plan/.code/.review on whatever it was
constructed with.

Kept replaceable for a future llama.cpp-direct provider: the transport
(default_http_post) is injectable, and everything above the transport
(prompt building, schema selection, retry, lifecycle, telemetry) is
Ollama-specific but structurally the same shape a llama.cpp provider
would need.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from .fake_model import ModelTimeoutError
from .ollama_schemas import CODER_SCHEMA, PLANNER_SCHEMA, REVIEWER_SCHEMA
from .prompts import build_coder_prompt, build_planner_prompt, build_reviewer_prompt


class OllamaTransportError(Exception):
    pass


def default_http_post(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OllamaTransportError(str(exc)) from exc


@dataclass(frozen=True)
class OllamaCallResult:
    load_duration_ns: int
    eval_duration_ns: int
    total_duration_ns: int
    prompt_eval_count: int
    eval_count: int


class OllamaModelProvider:
    def __init__(self, *, planner_model: str, coder_model: str, reviewer_model: str,
                 base_url: str = "http://localhost:11434",
                 http_post: Callable[[str, dict, float], dict] = default_http_post,
                 timeout_seconds: float = 120.0, max_transport_retries: int = 2):
        self._planner_model = planner_model
        self._coder_model = coder_model
        self._reviewer_model = reviewer_model
        self._base_url = base_url
        self._http_post = http_post
        self._timeout_seconds = timeout_seconds
        self._max_transport_retries = max_transport_retries
        self._loaded_model: Optional[str] = None
        self.telemetry_log: list[OllamaCallResult] = []

    def plan(self, context: dict) -> dict:
        return self._invoke(self._planner_model, build_planner_prompt(context), PLANNER_SCHEMA)

    def code(self, context: dict) -> dict:
        return self._invoke(self._coder_model, build_coder_prompt(context), CODER_SCHEMA)

    def review(self, context: dict) -> dict:
        return self._invoke(self._reviewer_model, build_reviewer_prompt(context), REVIEWER_SCHEMA)

    def _ensure_loaded(self, model_name: str) -> None:
        """Explicitly unload a different previously-loaded model before
        switching, rather than trusting Ollama's automatic multi-model
        residency - two 14B-class models resident at once would leave
        near-zero VRAM headroom on a 12GB card. A failed unload is
        best-effort, not fatal - the new call still proceeds."""
        if self._loaded_model is not None and self._loaded_model != model_name:
            try:
                self._http_post(f"{self._base_url}/api/generate",
                                 {"model": self._loaded_model, "keep_alive": 0}, self._timeout_seconds)
            except OllamaTransportError:
                pass
        self._loaded_model = model_name

    def _invoke(self, model_name: str, prompt: str, schema: dict) -> dict:
        self._ensure_loaded(model_name)
        payload = {"model": model_name, "prompt": prompt, "format": schema, "stream": False}
        last_error: Optional[Exception] = None
        response = None
        for _ in range(self._max_transport_retries):
            try:
                response = self._http_post(f"{self._base_url}/api/generate", payload, self._timeout_seconds)
                break
            except OllamaTransportError as exc:
                last_error = exc
                continue
        if response is None:
            raise ModelTimeoutError(
                f"transport failed after {self._max_transport_retries} attempts: {last_error}"
            )

        self.telemetry_log.append(OllamaCallResult(
            load_duration_ns=response.get("load_duration", 0),
            eval_duration_ns=response.get("eval_duration", 0),
            total_duration_ns=response.get("total_duration", 0),
            prompt_eval_count=response.get("prompt_eval_count", 0),
            eval_count=response.get("eval_count", 0),
        ))

        text = response.get("response", "")
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"_malformed_raw_text": text}
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_ollama_provider.py -v`
Expected: PASS (7 tests)

---

### Task 5: Model lifecycle (load/unload) and GPU telemetry helper

**Files:**
- Modify: `tests/test_ollama_provider.py` (add lifecycle coverage for
  `_ensure_loaded`, already implemented in Task 4)
- Create: `src/agent_platform/orchestrator/gpu_telemetry.py`
- Create: `tests/test_gpu_telemetry.py`

**Interfaces:**
- Produces: `query_gpu_memory(nvidia_smi=<injectable subprocess.run-like
  callable>) -> Optional[dict]` returning `{"used_mib": int, "total_mib":
  int}` parsed from `nvidia-smi --query-gpu=memory.used,memory.total
  --format=csv,noheader,nounits`, or `None` if `nvidia-smi` isn't
  available/fails — never raises, since telemetry is a nice-to-have, not
  a dependency the orchestrator's correctness relies on.

- [ ] **Step 1: Add lifecycle tests to `tests/test_ollama_provider.py`**

Append:
```python
def test_switching_to_a_different_model_sends_an_unload_call_first():
    transport, calls = make_fake_transport([
        _ok_response({"kind": "spec", "goals": [], "constraints": [], "acceptance_criteria": []}),
        _ok_response({"status": "blocked", "spec_version_label": "task-1-v1", "reason": "r",
                      "attempted": "a", "blocking_questions": ["q?"]}),
    ])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.plan({"request": "x"})
    provider.code({"spec": _spec(), "reviewer_feedback": None})
    # call 1: plan (loads phi4-reasoning:plus). call 2: unload phi4-reasoning:plus
    # (keep_alive: 0). call 3: code (loads qwen2.5-coder:14b).
    assert len(calls) == 3
    assert calls[1]["payload"] == {"model": "phi4-reasoning:plus", "keep_alive": 0}
    assert calls[2]["payload"]["model"] == "qwen2.5-coder:14b"


def test_reusing_the_same_shared_model_does_not_trigger_an_unload():
    # Planner and Reviewer share phi4-reasoning:plus per architecture-review-v2
    # section 7 - calling plan() then review() back to back must not unload
    # in between, since it's the same underlying model both times.
    transport, calls = make_fake_transport([
        _ok_response({"kind": "spec", "goals": [], "constraints": [], "acceptance_criteria": []}),
        _ok_response({"spec_version_label": "task-1-v1", "decision": "APPROVE",
                      "requirements_met": True, "security_ok": True, "validation_ok": True, "issues": []}),
    ])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.plan({"request": "x"})
    from agent_platform.orchestrator.validation import ValidationResult
    from agent_platform.orchestrator.model_schemas import CoderCompleted
    provider.review({"spec": _spec(),
                      "coder_output": CoderCompleted(spec_version_label="task-1-v1", summary="s", file_writes=()),
                      "validation_result": ValidationResult(passed=True, details=())})
    assert len(calls) == 2  # no unload call in between


def test_a_failed_unload_does_not_block_the_next_call():
    transport, calls = make_fake_transport([
        _ok_response({"kind": "spec", "goals": [], "constraints": [], "acceptance_criteria": []}),
        OllamaTransportError("unload endpoint hiccup"),
        _ok_response({"status": "blocked", "spec_version_label": "task-1-v1", "reason": "r",
                      "attempted": "a", "blocking_questions": ["q?"]}),
    ])
    provider = OllamaModelProvider(planner_model="phi4-reasoning:plus", coder_model="qwen2.5-coder:14b",
                                    reviewer_model="phi4-reasoning:plus", http_post=transport)
    provider.plan({"request": "x"})
    result = provider.code({"spec": _spec(), "reviewer_feedback": None})
    assert result["status"] == "blocked"
```

- [ ] **Step 2: Run to verify the new lifecycle tests fail meaningfully or pass**

Run: `python -m pytest tests/test_ollama_provider.py -v`
Expected: these three additions PASS immediately — `_ensure_loaded` was
already fully implemented in Task 4. If any fails, that's a real gap in
Task 4's implementation to fix now, not a Task 5 deferral.

- [ ] **Step 3: Write the GPU telemetry tests**

`tests/test_gpu_telemetry.py`:
```python
from agent_platform.orchestrator.gpu_telemetry import query_gpu_memory


def test_parses_valid_nvidia_smi_csv_output():
    def fake_run(*args, **kwargs):
        class Result:
            returncode = 0
            stdout = "1215, 12227\n"
        return Result()

    result = query_gpu_memory(nvidia_smi=fake_run)
    assert result == {"used_mib": 1215, "total_mib": 12227}


def test_returns_none_when_nvidia_smi_is_unavailable():
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi not found")

    assert query_gpu_memory(nvidia_smi=fake_run) is None


def test_returns_none_on_nonzero_exit_code():
    def fake_run(*args, **kwargs):
        class Result:
            returncode = 1
            stdout = ""
        return Result()

    assert query_gpu_memory(nvidia_smi=fake_run) is None


def test_returns_none_on_malformed_output():
    def fake_run(*args, **kwargs):
        class Result:
            returncode = 0
            stdout = "not,numbers\n"
        return Result()

    assert query_gpu_memory(nvidia_smi=fake_run) is None
```

- [ ] **Step 4: Run to verify failure**

Run: `python -m pytest tests/test_gpu_telemetry.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 5: Implement**

`src/agent_platform/orchestrator/gpu_telemetry.py`:
```python
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
    except (OSError, Exception):
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    try:
        used, total = result.stdout.strip().split(",")
        return {"used_mib": int(used.strip()), "total_mib": int(total.strip())}
    except (ValueError, AttributeError):
        return None
```

- [ ] **Step 6: Run to verify pass**

Run: `python -m pytest tests/test_ollama_provider.py tests/test_gpu_telemetry.py -v`
Expected: PASS (10 + 4 = 14 tests)

---

### Task 6: Full deterministic suite re-run

**Files:** none (verification only)

- [ ] **Step 1: Run everything built so far, still zero network**

Run: `python -m pytest tests/ -v --tb=short`
Expected: all Phase 0 + Phase 1 tests plus every test from Tasks 1-5 of
this phase pass together, 0 failures, 0 skips. Record the exact count for
the Phase 2 report - this is the last point before Task 7 introduces real
network/GPU calls.

---

### Task 7: Real Ollama integration — empirical measurement

**Files:**
- Create: `tests/test_ollama_integration.py`
- Create: `docs/superpowers/plans/phase-2-ollama-observations.md` (scratch
  notes on actual API response shape, filled in during this task, not a
  deliverable to polish - the report in Task 8 is the polished version)

This task is different in kind from the ones before it: exact model
output can't be pinned down in a plan written before the model has been
called. Follow this sequence rather than a fully pre-specified test file:

- [ ] **Step 1: One raw exploratory call, outside pytest**

Before writing any test, make one real call to `phi4-reasoning:plus`
through `OllamaModelProvider` (real `default_http_post`, real
`PLANNER_SCHEMA`) with a simple planner context, and print the full raw
HTTP response (not just the parsed `response` field). Record in
`phase-2-ollama-observations.md`: does the model return a "thinking"
field separate from the structured JSON, or does the JSON come back
directly in `response`? Does the JSON schema `format` parameter produce
valid JSON on the first try? What do `load_duration`/`eval_duration`/
`total_duration` actually look like in practice (seconds, not just raw
ns)? Repeat once for `qwen2.5-coder:14b` with a simple coder context.

- [ ] **Step 2: Adjust `OllamaModelProvider` if Step 1 revealed a real gap**

If the model wraps output in a separate thinking/reasoning field that
`response.get("response")` doesn't capture correctly, or the schema
constraint behaves differently than assumed, fix `ollama_provider.py` now
and re-run Task 4's fake-transport tests to confirm the fix doesn't break
the unit-level contract - a real behavior discovery here is exactly the
kind of thing the fake-transport tests can't catch and the plan can't
predict.

- [ ] **Step 3: Write and run the real integration tests**

`tests/test_ollama_integration.py` - construct real `OllamaModelProvider`
instances (no injected transport) and exercise, at minimum:
1. A real `plan()` call - assert the result parses via
   `parse_planner_output` without raising, record wall-clock time and
   `telemetry_log` entry.
2. A real `code()` call - same assertions, plus confirm switching from
   planner to coder produced an unload call (inspect via a wrapped
   `http_post` that logs calls even when hitting the real server) and
   that `nvidia-smi` VRAM usage after the coder call reflects a different
   model resident than after the planner call.
3. A real `review()` call using the planner model again (shared weights
   with Planner) - confirm no unload was needed switching planner→reviewer
   since they're the same model name.
4. One full real orchestrator run (`Orchestrator.run(...)` constructed
   with a real `OllamaModelProvider`, `AcceptanceCriteriaFileValidator`,
   and a temp project directory) for a small, concrete request - this is
   the first time the real models drive the actual state machine
   end-to-end. Assert the run reaches a terminal state (`COMPLETE` or
   `ESCALATE_TO_USER` are both acceptable outcomes to assert on - a real
   model choosing not to converge within the iteration caps is a valid,
   informative result, not a test failure, as long as it terminates
   rather than hanging).
5. Query `query_gpu_memory()` before any model is loaded, immediately
   after loading each model, and after an explicit unload - record actual
   MiB figures.
6. Attempt one deliberately large prompt (repeat a long string in the
   context) to observe actual context-length behavior - does Ollama
   truncate silently, error, or handle it, and at what rough input size
   does behavior change? Record findings rather than asserting a specific
   number, since this depends on the model's configured context window.

Keep the total real-call count modest (roughly 6-10 calls across both
models) - this is about getting real, defensible numbers for the report,
not building another large combinatorial suite against a slow local
GPU.

- [ ] **Step 4: Run the integration file and capture output**

Run: `python -m pytest tests/test_ollama_integration.py -v -s`
(`-s` so any printed timing/telemetry output is visible, not captured)
Record pass/fail and every measurement gathered.

---

### Task 8: Phase 2 report

**Files:**
- Create: `PHASE2_REPORT.md`

- [ ] **Step 1: Write the report**

Structure like Phase 0/1's reports: Implemented, Test results (Task 6's
deterministic count plus Task 7's integration results), Real measurements
(load time per model, inference latency per role, VRAM before/during/
after each model, unload behavior confirmed or not, context-length
observation from Task 7 Step 3.6, any deviation discovered in Task 7 Step
1-2 from the assumed API shape), security/determinism invariants (context
isolation confirmed - prove via the Task 3 tests that Coder/Reviewer
prompts never contain user conversation or coder summary; malformed real
model output observed, if any, and confirmed it retried/escalated
correctly through Phase 1's unchanged orchestrator logic), scope
decisions, remaining concerns.

- [ ] **Step 2: Stop**

Per the standing instruction, do not proceed to any further phase. Report
back: what was implemented, real measurements, and any architecture
findings (e.g. the Planner/Reviewer model reversion noted in Global
Constraints) worth the user's attention. Wait for further instructions.
