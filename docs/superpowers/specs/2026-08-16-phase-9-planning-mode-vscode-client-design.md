# Phase 9 Design: Planning Mode + VS Code Client

Status: DRAFT — awaiting user review

## 0. Scope and baseline

This document specs **Spec A: Backend Planning Mode**, the first of two sequential
sub-projects agreed with the user:

- **Spec A (this document):** `OperatingMode` concept, Planning Mode workflow,
  structured plan schema, Markdown plan artifacts, approval/revision/rejection,
  specification handoff, MCP research integration, the local HTTP+SSE
  backend/frontend contract, and MCP settings backend. Fully testable headless,
  with no VS Code involvement.
- **Spec B (future, separate spec doc):** the VS Code extension itself —
  sidebar, mode selector, plan/code/review UI, MCP settings UI — built as a
  pure client of Spec A's contract once Spec A is implemented and tested.

Section 11 below defines the *boundary* Spec B will consume but does not design
the extension itself.

**Baseline (confirmed 2026-08-16):** `python -m pytest tests/
--ignore=tests/test_ollama_integration.py --ignore=tests/test_mcp_real_integration.py -q`
→ **745 passed, 0 failed, 0 skipped**, 21.74s. Clean. The two excluded suites are
real-network tests excluded consistently since Phase 2/4. No existing test may
be weakened, deleted, or skipped to accommodate this work; the full suite must
stay green after every meaningful change.

No git commands are run as part of this work. Git remains entirely
human-controlled.

## 1. Sessions & Modes

### 1.1 A new, orthogonal dimension

Today, `security/permission.py` has two axes: `Role` (`PLANNER`/`CODER`/`REVIEWER`,
`security/enums.py:9-12`) and `SessionMode` (`AUTO`/`CONFIRMATION`/`MANUAL`,
approval behavior, `security/enums.py:15-18`). Neither represents "what kind of
session is this" — that's new. We add:

```python
class OperatingMode(Enum):
    CHAT = "CHAT"
    PLAN = "PLAN"
    CODE = "CODE"
    EDIT = "EDIT"
    REVIEW = "REVIEW"
```

in `security/enums.py`, alongside the existing three enums, unchanged.

`OperatingMode` is **immutable for the lifetime of a session** (one
`Orchestrator` instance = one mode). Switching modes in the VS Code client
means creating a new session (new `Orchestrator`, new session id), never
mutating an existing session's mode. This avoids "a running Code session
silently becomes Plan mode" ambiguity entirely and keeps every code path that
reasons about mode able to treat it as a constant for the session's duration.

### 1.2 ModePolicy table

New module `security/mode_policy.py`:

```python
@dataclass(frozen=True)
class ModePolicy:
    allowed_roles: Optional[frozenset[Role]]  # None = no role filter (CODE/EDIT: unchanged behavior)
    allowed_tools: Optional[frozenset[str]]   # None = no allowlist filter (CODE/EDIT: unchanged behavior)
    mode_grants: dict[tuple[Role, str], ToolPermission]  # additive grants that exist ONLY in this mode
    write_scope: dict[str, str]               # tool_name -> scope subdirectory name, e.g. {"filesystem.write": ".agent/plans", "filesystem.create_directory": ".agent/plans"}
```

Both `allowed_roles` and `allowed_tools` use the same `None`-means-unrestricted
convention, so CODE/EDIT's "no additional restriction" is expressed
identically for both axes rather than as a special case of one but not the
other.

`MODE_POLICIES: dict[OperatingMode, ModePolicy]`:

| Mode | `allowed_roles` | `allowed_tools` | `mode_grants` | `write_scope` |
|---|---|---|---|---|
| **CODE** | `None` (no filter) | `None` (no filter) | `{}` | `{}` |
| **EDIT** | `None` (no filter) | `None` (no filter) | `{}` | `{}` |
| **CHAT** | `{PLANNER}` | read-only fs + read-only git + configured read-only MCP capability names | `{}` | `{}` |
| **PLAN** | `{PLANNER, REVIEWER}` | read-only fs + read-only git + `filesystem.write` + `filesystem.create_directory` + configured read-only MCP capability names | `{(PLANNER, "filesystem.write"): ALLOW, (PLANNER, "filesystem.create_directory"): ALLOW}` | `{"filesystem.write": ".agent/plans", "filesystem.create_directory": ".agent/plans"}` |
| **REVIEW** | `{REVIEWER}` | read-only fs + read-only git + configured read-only MCP capability names (+ `test.run` only if `PlatformConfig.review_mode_allows_test_run` is set) | `{}` | `{}` |

CODE and EDIT get `allowed_tools=None`, meaning the new gating step is a
structural no-op for them — this **is** "existing `run()` behavior unchanged."
EDIT reuses CODE's policy verbatim; the spec's Chat/Plan/Code/Edit/Review
distinction for Edit is about how a request enters the pipeline (one targeted
requirement vs. an open-ended task), not a different capability grant, so it
doesn't need its own row.

Base-table grant `(Role.CODER, "filesystem.write") = ALLOW`
(`security/permission.py:49`) is untouched. In PLAN mode, Coder isn't in
`allowed_roles` at all, so any Coder tool call — including this exact
grant — is denied before the base table is even consulted. This is the
"deterministic" half of Coder-never-in-Plan-Mode (§1.4).

Base table has **no** `(Role.PLANNER, "filesystem.write")` entry today — Planner
has never been able to write anything. PLAN mode's `mode_grants` is what
creates that ability, and only inside PLAN mode, only for Planner, only for
`filesystem.write`/`filesystem.create_directory`. Reviewer gets no such grant
in `mode_grants`, so a Reviewer write attempt in PLAN mode falls through to
the base table, finds no `(REVIEWER, "filesystem.write")` entry, and is denied
with `"no ALLOW/CONFIRM grant for REVIEWER:filesystem.write"` — the exact same
deny path that already protects every other undefined role×tool pair. This
gives us "Reviewer may NOT modify plan artifacts" **for free**, with no new
Reviewer-specific logic.

### 1.3 `PermissionEvaluator.evaluate` — the one necessary signature change

```python
def evaluate(self, call: ToolCall, session_mode: SessionMode,
              operating_mode: OperatingMode = OperatingMode.CODE) -> PermissionDecision:
    if call.tool_name in ABSOLUTE_DENY_TOOLS:
        return DENY  # unchanged

    mode = MODE_POLICIES[operating_mode]
    if mode.allowed_roles is not None and call.role not in mode.allowed_roles:
        return DENY("role not permitted in {mode} mode")
    if mode.allowed_tools is not None and call.tool_name not in mode.allowed_tools:
        return DENY("tool not permitted in {mode} mode")

    static_permission = mode.mode_grants.get((call.role, call.tool_name)) \
        or self._table.get((call.role, call.tool_name), ToolPermission.DENY)   # unchanged base lookup
    ...
    scope_root = call.scope_root
    if call.tool_name in mode.write_scope:
        scope_root = (call.scope_root / mode.write_scope[call.tool_name]) if call.scope_root else None
    # sandbox.authorize(call.path_argument, scope_root=scope_root) — unchanged call, mode-forced scope_root
    ...
    # session ceiling logic — completely unchanged
```

This is the **one strictly-necessary additive integration point** flagged
under Sessions & Modes: a new parameter on `PermissionEvaluator.evaluate` and
`ToolGateway.invoke` (`tools/gateway.py:48-65`, which forwards it into the
`ToolCall`/`evaluate` call at line 65), each defaulting to `OperatingMode.CODE`
so that every existing call site — the entire Code/Edit path, and all 745
existing tests that call `evaluate()`/`invoke()` today — is byte-for-byte
unaffected without editing those call sites' signatures.

**Why a default here is safe** (this is the one place in the codebase where a
security-relevant parameter gets a default, so it's worth justifying
explicitly): `OperatingMode.CODE`'s policy is defined as a strict no-op —
identical to "no operating mode concept exists," which is exactly today's
behavior. The default cannot be exploited to gain more access than existed
before Phase 9; at worst, a caller that forgets to pass `operating_mode` gets
today's (already-reviewed) Code-mode permissions. The real risk would be a
Plan/Chat/Review session accidentally *falling through* to the default and
getting Code-mode's broader grants — this is closed structurally, not by
convention: `Orchestrator` stores `self._operating_mode` once at construction
(§1.5) and every one of its own `gateway.invoke(...)` call sites passes
`operating_mode=self._operating_mode` explicitly. The default only matters for
external callers (tests, future direct `ToolGateway` use) who don't specify a
mode at all, and those get Code-mode behavior, not elevated behavior.

The path-scope enforcement reuses `FilesystemSandbox.authorize(requested,
scope_root=...)` (`security/sandbox.py:114-159`) **completely unmodified** —
same UNC/device-path rejection, same drive/root-relative ambiguity rejection,
same pre-resolution reparse-point walk (`_contains_reparse_point`,
`sandbox.py:69-90`, which explicitly checks the *unresolved* path before
`.resolve()` can silently dereference a junction/symlink), same
`resolved.relative_to(base)` containment check, same `.git` exclusion. PLAN
mode's `.agent/plans/**` restriction is just a different `scope_root` value
fed into this existing function — no new path logic is written anywhere. This
directly satisfies the requirement to reuse canonical path-containment and
reparse-point protections rather than naive prefix matching.

### 1.4 Coder-never-in-Plan-Mode: both layers

- **A. Structural:** the Plan Mode orchestrator method (§2) never imports,
  constructs, or calls anything on a Coder provider method. There is no code
  path in `run_plan`/`revise_plan`/`approve_plan`/`reject_plan` that can reach
  `self._model.code(...)`.
- **B. Deterministic:** even if some future code accidentally tried, PLAN
  mode's `allowed_roles = {PLANNER, REVIEWER}` means `PermissionEvaluator`
  denies any `(Role.CODER, *)` call in PLAN mode outright, regardless of the
  base table.

Explicit test matrix (from the user's locked requirements), directly
derivable from §1.2/§1.3:

| Call | Expected |
|---|---|
| `PLAN` + `PLANNER` + `filesystem.write` under `.agent/plans/` | **ALLOW** |
| `PLAN` + `REVIEWER` + `filesystem.write` (any path) | **DENY** — no grant |
| `PLAN` + `CODER` + any tool | **DENY** — role not permitted in PLAN mode |
| `PLAN` + `PLANNER` + `filesystem.write` outside `.agent/plans/` (traversal, absolute escape, sibling-prefix, symlink/junction escape, UNC, device path, `.git`) | **DENY** — sandbox denial, reusing `sandbox.py`'s existing protections |
| `PLAN` + `PLANNER` + `test.run`/`shell.run`/any `git.*` write | **DENY** — not in `allowed_tools` (test/shell) or `ABSOLUTE_DENY_TOOLS` (git writes) |

### 1.5 Orchestrator construction

`Orchestrator.__init__` (`orchestrator/core.py:41-56`) gains one new parameter:
`operating_mode: OperatingMode = OperatingMode.CODE`, stored as
`self._operating_mode`. Every existing test that constructs an `Orchestrator`
without specifying it continues to get exactly today's Code-mode object,
unchanged. `run()` and `amend_requirements()` are untouched — they are only
ever called on `OperatingMode.CODE`/`EDIT` sessions.

Three new lightweight methods live on the **same** `Orchestrator` class (no
second orchestrator, per the hard requirement):

```python
def run_chat(self, session_id: str, message: str) -> ChatResult: ...
def run_plan(self, spec_id: str, user_request: str) -> PlanResult: ...
def revise_plan(self, spec_id: str, revision_request: str) -> PlanResult: ...
def approve_plan(self, spec_id: str) -> PlanApprovalResult: ...
def reject_plan(self, spec_id: str, reason: str) -> PlanResult: ...
def run_review(self, session_id: str, target_description: str) -> ReviewResult: ...
```

Each asserts `self._operating_mode` matches what it expects
(`run_plan`/`revise_plan`/`approve_plan`/`reject_plan` require `PLAN`,
`run_chat` requires `CHAT`, `run_review` requires `REVIEW`) and raises a plain
`ValueError` otherwise — a cheap, redundant guard against wiring mistakes, not
a security control (the real control is §1.3).

None of these methods touch the existing `State` enum
(`orchestrator/states.py`) or add reachable states to it — that enum, and
every transition through it, is used exclusively by `run()`/
`amend_requirements()` and stays completely unmodified. Plan Mode's own
(much simpler, non-looping-back-into-Code) progress is tracked via new
`EventType` members (§10) and the return value of each method, not via the
existing `State` machine. This is the concrete form of "CHAT, PLAN, and REVIEW
may use lightweight methods... rather than being forced into the autonomous
SWE state machine."

## 2. Planning Mode workflow

`run_plan(spec_id, user_request)`:

1. Emit `USER_REQUEST_RECEIVED` / user-stream event (reuses `_user_event`,
   `orchestrator/core.py:102-103`).
2. Build the Planner's context the same way `run()` does today (project
   context, dependencies, tests, config — Phase 5's context bundle builder,
   `context/bundle_builder.py`), via `build_planner_context` in
   `context/role_context.py`.
3. Call `self._model.plan_mode({...context...})`, parsed by a new
   `parse_planner_plan_output` (§3). Reuses `_invoke_with_retry`
   (`core.py:105-119`) verbatim — same bounded-retry-then-escalate behavior on
   timeout or schema failure as every other role call in the system.
4. **Research loop** (bounded by a new `max_plan_research_rounds` config field
   on `PlatformConfig`, mirroring `max_clarification_rounds`): if the parsed
   output is a `ResearchRequestBatch`, each request's `capability` string is
   checked against PLAN mode's `allowed_tools`/configured MCP capability set
   *before* any gateway call — a denied capability produces a structured
   "denied" observation fed straight back to the Planner (not a raw exception,
   not a silent drop), same shape as `ToolObservation(status="denied", ...)`
   the gateway already returns for ordinary tool denials
   (`tools/gateway.py:66-68`). Permitted requests go through
   `gateway.invoke(role=Role.PLANNER, tool_name=f"mcp.{server}.{capability}",
   ..., operating_mode=OperatingMode.PLAN)` — the exact same MCP tool-call path
   every other role already uses (`mcp/gateway_tools.py`), nothing MCP-specific
   is added to the orchestrator. Results are appended to the Planner's context
   and it is called again. Exceeding the round limit produces the same
   `_stuck`-shaped escalation the existing loops use (a `PlanResult` with
   status `NEEDS_INPUT` and a clear reason), never a silent failure.
5. If the (possibly research-augmented) output is `PlannerClarification` (the
   existing dataclass, `model_schemas.py:66-67`, reused as-is), behave exactly
   like `run()` does today: transition to the user-facing question, return.
6. Otherwise it's a `StructuredPlan` (§3). Call
   `self._model.review_plan({"plan": structured_plan})`, parsed by
   `parse_reviewer_plan_output`. This is a **single automatic pass** — Reviewer
   critique happens once, before the plan is ever shown to the user, matching
   the workflow diagram (`PLANNER → CONTEXT → MCP RESEARCH → REVIEWER PLAN
   CRITIQUE → STRUCTURED PLAN → PLAN ARTIFACT`). The critique is advisory: it
   is attached to the plan's `reviewer_feedback` field and does **not** gate
   artifact creation. Reviewer never blocks a plan from reaching the user —
   only the user's own Approve/Revise/Reject decision (§6) is a gate.
7. Render and write the Markdown artifact (§5), status `DRAFT`.
8. Return `PlanResult(status="DRAFT", spec_id, artifact_path, structured_plan)`.

`revise_plan(spec_id, revision_request)` re-invokes Planner with the current
draft plus the user's revision request as additional context, optionally
re-running the Reviewer critique pass, and overwrites the *same* artifact file
in place with status `REVISED` (§5.3 covers exactly which artifacts are
overwritable vs. immutable).

## 3. Structured plan schema

New module `orchestrator/plan_schemas.py` (kept separate from
`model_schemas.py`, which stays scoped to the Code-mode Planner/Coder/Reviewer
contracts it already owns — this keeps both files focused rather than growing
`model_schemas.py` into a dumping ground). Same validation style as the
existing schemas: a raw dict must pass a parse function or raise
`SchemaValidationError`, which the orchestrator's existing retry/escalate
handling already knows how to deal with. No new error-handling concept is
introduced.

```python
@dataclass(frozen=True)
class ResearchRequest:
    capability: str   # e.g. "mcp.github.repository_read"
    query: str

@dataclass(frozen=True)
class ResearchRequestBatch:
    requests: tuple[ResearchRequest, ...]

@dataclass(frozen=True)
class StructuredPlan:
    objective: str
    requirements: tuple[str, ...]
    existing_context: tuple[str, ...]
    proposed_architecture: str
    files_to_create: tuple[str, ...]
    files_to_modify: tuple[str, ...]
    dependencies: tuple[str, ...]
    implementation_steps: tuple[str, ...]
    validation_strategy: tuple[str, ...]
    risks: tuple[str, ...]
    unknowns: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    reviewer_feedback: tuple[str, ...] = ()          # populated after §2 step 6
    target_spec_version_label: str = ""              # predicted label, e.g. "spec_id-v1" — NOT a SpecStore entry until approved (§7)

PlannerPlanOutput = Union[StructuredPlan, PlannerClarification, ResearchRequestBatch]

def parse_planner_plan_output(raw) -> PlannerPlanOutput:
    kind = raw.get("kind")
    # "plan" -> StructuredPlan, "needs_user_input" -> PlannerClarification (reused),
    # "research_request" -> ResearchRequestBatch
    # every field required-and-typed exactly like parse_planner_output today; malformed
    # output raises SchemaValidationError, same as every other role's parser.

@dataclass(frozen=True)
class PlanReview:
    comments: tuple[str, ...]
    missing_requirements: tuple[str, ...]
    security_concerns: tuple[str, ...]
    unnecessary_complexity: tuple[str, ...]

def parse_reviewer_plan_output(raw) -> PlanReview: ...
```

Malformed output at any point (Planner, Reviewer, or a research request
referencing a capability that doesn't parse as a string) is rejected by these
parse functions before it can influence anything — "arbitrary free-form model
output" never becomes a requirement, matching the existing architecture's
core invariant.

## 4. Planner/Reviewer interaction

Already resolved by §2 step 6 and §3's `PlanReview`: Reviewer sees the
Planner's `StructuredPlan` and returns structured, itemized critique — never
prose the orchestrator has to interpret, never a decision that blocks or
approves anything. The Planner does not automatically loop on Reviewer
feedback beyond incorporating it into the one plan that gets shown to the user
(no back-and-forth Planner↔Reviewer negotiation loop — that would be exactly
the kind of unbounded multi-round complexity the existing Code-mode fix-loop
needs `max_fix_iterations`/stall-detection for for good reason). The user, not
the Reviewer, decides whether requirements are adequately addressed;
`revise_plan` is the only mechanism for iterating further, and it's
user-initiated.

Reviewer's plan-mode tool grants are identical to its existing grants
(read-only fs/git, `test.run`/`lint.run`/`typecheck.run` in Code mode only —
PLAN mode's `allowed_tools` excludes those three per §1.2, so a Reviewer plan
critique cannot execute tests even though the base table technically grants
it `test.run`; PLAN mode's allowlist is the thing narrowing it out).

## 5. Plan artifact lifecycle

### 5.1 Location and naming

`<project-root>/.agent/plans/{YYYY-MM-DD}-{spec_id}-spec-v{N}.md`, adapting
the task's example filename to guarantee uniqueness deterministically: `N` is
`(spec_store.latest(spec_id).version if any versions exist else 0) + 1` at
draft time — a *prediction* of the version this plan will become if approved,
not a reservation (§7 covers why nothing is reserved in `SpecStore` until
approval) — and `spec_id` is already required to be unique per planning
effort by the caller (§9's `POST /sessions` takes `spec_id` as an input, not
something the backend invents), so `(spec_id, N)` is unique by construction
with no collision handling needed. `spec_id` is sanitized the same way any
user/client-supplied string destined for a filesystem path must be — rejected
characters stripped, not "fixed" — and the final candidate still goes through
`FilesystemSandbox.authorize` like every other write, so even a
maliciously-crafted `spec_id` cannot escape `.agent/plans/`. A short
human-readable slug of the request may be appended for readability
(`...{spec_id}-spec-v{N}-{slug}.md`) but is never load-bearing for
uniqueness.

### 5.2 Content

Exactly the sections the task specifies (`# Implementation Plan` through
`## Specification`), rendered deterministically from the `StructuredPlan`
dataclass — one field, one section, no model-authored Markdown structure. The
renderer is a pure function `render_plan_markdown(plan: StructuredPlan,
*, status: str, spec_version_label: str) -> str` with a snapshot-style test
(same rendering in, same bytes out, every time) so "deterministic Markdown
formatting" is a property the test suite actually checks, not an assumption.
`Specification Version: {spec_version_label}` and `Status: {status}` appear
prominently near the top, matching the task's requirement.

### 5.3 Immutability rule

An artifact file is **overwritable only while its status is `DRAFT` or
`REVISED`**. The moment `approve_plan`/`reject_plan` sets status to `APPROVED`
or `REJECTED`, that specific file is never written again. A later planning
round for the same `spec_id` (e.g. amending already-approved requirements)
predicts the next version number (§5.1) and creates a **new** file; the old
one stays on disk, untouched, exactly as historical evidence of what was
approved/rejected and when. This is the entire mechanism behind "historical
plan preservation" and "do not destroy historical approved plans" — no
retroactive status mutation (e.g. marking old files `SUPERSEDED`) is needed or
implemented, because nothing ever needs to change about a file once it's
final. (Documented limitation: this assumes one active drafting round per
`spec_id` at a time — concurrent approvals for the same `spec_id` from two
different sessions is out of scope, matching the single-writer assumption the
rest of the platform already makes.)

### 5.4 Provenance inside the artifact

The `## Reviewer Feedback` section is populated only from `PlanReview` fields
(§3/§4) — never from the Planner's own text — so a reader can tell which
content came from which role. No chain-of-thought or private reasoning from
either role is ever included; both parse functions only extract the typed
fields defined in §3, so there is nothing else *to* leak into the artifact.

## 6. Plan approval / revision / rejection

- **`approve_plan(spec_id)`**: mints the real `SpecVersion` (§7), rewrites the
  artifact one final time with `Status: APPROVED` and the now-real
  `spec_version_label` (identical to the predicted one in the normal case —
  see §7 for the mismatch edge case), emits `PLAN_APPROVED` +
  `SPEC_VERSION_CREATED`. This is the only place `SpecStore.create` is ever
  called from the planning path.
- **`revise_plan(spec_id, revision_request)`**: only legal while the current
  draft's status is `DRAFT`/`REVISED` (§5.3); re-runs §2 steps 3-7 with the
  revision request folded into context, overwrites the same file, status
  `REVISED`.
- **`reject_plan(spec_id, reason)`**: rewrites the artifact with
  `Status: REJECTED`, emits `PLAN_REJECTED`. No `SpecVersion` is ever created
  for a rejected plan.

Generating a plan is explicitly **not** approval — nothing about `run_plan`
touches `SpecStore`, so there is no way for a draft to accidentally become
"current" for Code Mode. Approval is a distinct, explicit call the VS Code
client only exposes after the user clicks Approve (§11); the backend does not
infer approval from anything else (not from the plan looking complete, not
from the user opening the file, not from silence).

### Manual Markdown edits are non-authoritative

The backend never re-reads `.agent/plans/*.md` to determine plan content or
status — the `StructuredPlan`/`PlanReview` objects the orchestrator already
holds in memory (and, once approved, the `SpecVersion` in `SpecStore`) are the
only authority. If a user hand-edits the Markdown file, the next
`revise_plan`/`approve_plan`/`reject_plan` call operates on the backend's own
state and **overwrites the hand edit** the next time that file is written
(while still `DRAFT`/`REVISED`) or simply ignores it (once `APPROVED`/
`REJECTED`, since the file is never written again per §5.3, a hand edit at
that point just sits there as an inaccurate — but clearly non-authoritative,
since the real record is `SpecStore` — document). This satisfies "manual
changes must not silently become authoritative" without needing a
file-watcher, diffing, or import mechanism of any kind: the simplest correct
answer is that the file was never the source of truth to begin with.

## 7. Specification / version handoff

`SpecStore`/`SpecVersion` (`spec/versioning.py`) are used **completely
unmodified** — zero changes to that module. This was a deliberate design
choice worth calling out explicitly: `SpecStore.create()` immediately makes a
version "current" (`.latest()`, used by `assert_current` which Coder/Reviewer
pin every invocation to, `spec/versioning.py:60-76`), with no notion of
draft/approved status. Adding a status concept to `SpecStore` itself would
mean changing a module that's deliberately minimal, already fully tested, and
whose only user today (Code Mode) has no approval gate at all — changing its
semantics risks regressing something that works. Instead, Planning Mode simply
**never calls `SpecStore.create()` until `approve_plan`** — the draft/revision
loop lives entirely in Planning-Mode-owned data (the in-memory `StructuredPlan`
plus the Markdown artifact), and `SpecStore` only ever sees finished, approved
specs, exactly as before. `approve_plan` calls:

```python
spec = self._spec_store.create(spec_id, goals=plan.requirements,
                                constraints=derived from plan.risks/unknowns,
                                acceptance_criteria=plan.acceptance_criteria)
```

— the same call `_after_plan` already makes today (`core.py:128-130`), just
triggered by explicit user approval instead of automatically after a single
Planner call. `spec.version_label` is compared against the artifact's
predicted `target_spec_version_label` (§5.1); in the normal single-writer case
they match. If they don't (the documented concurrent-approval edge case), the
mismatch is surfaced as an error to the user rather than silently
proceeding — never silently overwriting or misattributing a version.

Code Mode then consumes this exactly as it does today: a `spec_id` +
version created by `SpecStore.create()`, pinned via `assert_current`. **No
second specification format is invented; no version-validation logic is
bypassed.**

## 8. MCP/GitHub research integration

Fully covered by §2 step 4 and §3's `ResearchRequestBatch`. To restate the
security property explicitly: a capability the Planner asks for is only ever
executed if (a) it's in PLAN mode's `allowed_tools` (§1.2, itself derived from
`MCPServerConfig.capabilities ∩ client.discover()` per
`mcp/gateway_tools.py:65-68` — discovery can only narrow, never expand, exactly
as today), and (b) `PermissionEvaluator` grants it for `(Role.PLANNER,
mcp.<server>.<capability>)` in PLAN mode. GitHub write capabilities
(`commit`, `push`, `merge`, branch creation, repo deletion, PR modification)
are simply never in any server's configured read-only capability set that
Planner/Coder/Reviewer are granted — this is a trusted-configuration property,
not something Phase 9 code enforces at the call site, matching how the
existing MCP gateway already works (`mcp/gateway_tools.py`'s docstring: "there
is no MCP-specific authority check anywhere").

**Explicitly deferred, not silently assumed:** the task's "Coder GitHub
Access" section describes Coder optionally issuing the same kind of
structured research request mid-task (`Coder → structured research request →
Orchestrator → MCP Gateway → observation → Coder`). The baseline inspection
(§0) confirmed this hook does not exist for Code Mode either — `CoderCompleted`/
`CoderBlocked` (`model_schemas.py:90-109`) have no field for it, and no MCP
call has ever fired during an autonomous `run()`. Adding one would mean
changing Code Mode's existing output schema — exactly the "strictly necessary
additive integration point" requirement #6 says must be justified and
explicitly documented before touching CODE/EDIT. Since the task states Coder
"MAY" have this capability (not a Phase 9 completion requirement — it's absent
from the STOP CONDITIONS list) and Spec A's mandate is to leave `run()`
behaviorally frozen, this document deliberately **does not** add a Coder-side
research hook. Code Mode continues to make zero MCP calls, identical to
today. This is called out as a candidate for a later, separate spec, not an
oversight — see Known Limitations.

## 9. Backend/frontend transport

Local FastAPI + uvicorn process, spawned by the VS Code extension as a child
process on activation (`python -m agent_platform.server --port 0`). Binds to
`127.0.0.1` only — never `0.0.0.0`. The OS assigns the port (`--port 0`); the
process writes a single JSON line to its stdout on startup:
`{"port": 54231, "token": "<32-byte urlsafe random>"}`. The extension reads
this line to learn where to connect and what bearer token to present. Every
request (HTTP and the SSE/WebSocket upgrade) must include
`Authorization: Bearer <token>`; a missing/wrong token is a 401 before any
session or orchestrator state is touched. The token is generated fresh per
process launch (`secrets.token_urlsafe(32)`), lives only in memory and the
one stdout line, and is never written to disk or logged. This is "an
authenticated local session/channel mechanism" without inventing a user
account system — there's exactly one legitimate client (the extension that
spawned this exact process) and one shared secret it alone has seen.

The HTTP layer is a **pure client interface** — every route handler is a thin
wrapper that constructs the appropriate `Orchestrator` call (or reads
already-emitted `EventLog`/`PlanResult` state) and serializes the result. No
route handler calls `ToolGateway`, `PermissionEvaluator`, `MCPClient`, or the
filesystem directly; every one of those still only has one caller,
`Orchestrator`, exactly as today. This is what "must never bypass the
Orchestrator/PermissionEvaluator/ToolGateway/MCP Gateway/sandbox/validation"
means concretely: the API layer literally has no import of those modules
except transitively through `Orchestrator`.

## 10. JSON / structured event contract

New `EventType` members, purely additive (`events.py:18-27`, no existing
member removed or renamed, so nothing that matches on the existing set
breaks): `PLAN_CREATED`, `PLAN_RESEARCH_REQUESTED`, `PLAN_RESEARCH_COMPLETED`,
`PLAN_REVIEWED`, `PLAN_ARTIFACT_WRITTEN`, `PLAN_REVISED`, `PLAN_APPROVED`,
`PLAN_REJECTED`.

Minimum route surface (all JSON in/out; SSE for the event stream):

| Route | Method | Purpose |
|---|---|---|
| `/sessions` | POST | create session: `{operating_mode, spec_id?}` → `{session_id}` |
| `/sessions/{id}/messages` | POST | submit a request/message for the session's mode |
| `/sessions/{id}/events` | GET (SSE) | stream `EventLog.user_stream()` events for this session as they're emitted — internal-stream events are never sent over this route |
| `/sessions/{id}/plan` | GET | current `StructuredPlan` + status + artifact path |
| `/sessions/{id}/plan/revise` | POST | `{revision_request}` |
| `/sessions/{id}/plan/approve` | POST | → `{spec_version_label}` |
| `/sessions/{id}/plan/reject` | POST | `{reason}` |
| `/sessions/{id}/state` | GET | current `State`/status, changed files, validation results (Code/Edit sessions) |
| `/mcp/servers` | GET | trusted server list + discovered capabilities + connection status (credentials always redacted, reusing `mcp/secrets.py`'s existing `redact_secret_string`/`redact_secrets`) |
| `/mcp/servers/{id}/preferences` | PUT | user enablement toggle only (§12) — never touches trusted config |

Every payload is built from the existing typed dataclasses (`StructuredPlan`,
`PlanReview`, `ToolObservation`, `Event`, etc.) via explicit `asdict()`-style
serialization functions — never `vars()`/`__dict__` reflection over arbitrary
Python objects, so a field can't leak into the wire format just by existing on
some internal class. Internal-stream events, secrets, and any private
reasoning are excluded by construction (only `user_stream()` is ever
serialized for `/events`; `/mcp/servers` only ever serializes the redacted
view).

## 11. VS Code integration boundary

Out of scope for this document (Spec B). What Spec B may assume: the routes
in §10 exist, are the *only* way to reach the backend, and the extension's
entire responsibility is presenting them (sidebar, mode selector, plan
viewer/approval controls, opening the artifact file via VS Code's own editor
API, MCP settings screen backed by `/mcp/servers`). Spec B will not receive
Planner/Coder/Reviewer logic, permission evaluation, the filesystem sandbox,
MCP authority, or model orchestration in any form — every one of those stays
server-side per the task's explicit prohibition.

## 12. MCP settings / configuration architecture

Trusted MCP configuration (`MCPServerRegistry`, `mcp/server_registry.py`) has
no mutation method today and gets none — adding/removing a server or changing
its structurally-permitted capabilities remains a human editing trusted
config and restarting the backend process, exactly as Phase 4 already works.
The VS Code Settings UI is **read-only** with respect to that trust boundary.

What the UI *can* change: a new, separate `MCPUserPreferences` store (backend
in-memory, or a small JSON file the backend itself owns — not the trusted
config file) holding only `{server_id: {enabled: bool, capability_overrides:
{capability: bool}}}`. Effective enablement for MCP capability registration
(`mcp/gateway_tools.py`'s `_usable_capabilities`) becomes: `discovered ∩
trusted_config.capabilities ∩ (user_preference, default True if unset)` — a
pure narrowing intersection. There is no code path from a user preference to
an `ALLOW` that trusted config/discovery didn't already establish — the
preference can only ever remove a capability from the effective set, never
add one, which is the concrete mechanism behind "the UI may expose permitted
read capabilities... must NOT convert DENY→ALLOW."

Credentials (`MCPServerConfig.credential`) are never included in any API
response — `/mcp/servers` builds its payload from a redacted view that omits
the field entirely (not merely masks it), so there's no redaction bug surface
to worry about in the wire format at all.

Neither the model (Planner/Coder/Reviewer output) nor an MCP server's own
response can reach `MCPUserPreferences` or trusted config — both are only
ever written by the `/mcp/servers/{id}/preferences` route, which is only
reachable by the authenticated VS Code client (§9), and that route's handler
only ever narrows, never grants.

## 13. Error handling

Every failure mode reuses an existing pattern rather than inventing a new one:

- Malformed Planner/Reviewer plan output → `SchemaValidationError` →
  `_invoke_with_retry`'s existing bounded-retry-then-`None` path (§2 step 3) →
  surfaced to the client as a structured `PlanResult(status="FAILED", reason=...)`,
  the Plan Mode equivalent of `_stuck()` (`core.py:250-255`) — never a raw
  traceback over the wire.
- Denied/errored tool calls (including MCP research requests) → the existing
  `ToolObservation` `status`/`error` fields (`tools/gateway.py:34-39`),
  serialized as-is.
- HTTP-layer errors (bad auth, unknown session, wrong mode for a route) →
  standard 401/404/409 JSON error bodies `{error: str, code: str}` — no stack
  traces, no internal file paths, no internal-stream event content ever
  appears in an HTTP error body.
- MCP transport failures already come back as a typed `MCPResponse` with
  `status`/`error` (`mcp/schemas.py:22-25`) and secret-redacted strings
  (`mcp/gateway_tools.py:54-62`) — nothing new needed here either.

## 14. Testing and regression strategy

TDD throughout, per the established workflow: write the test, watch it fail
for the right reason, implement, watch it pass, then run the full suite.
Baseline is 745 passed / 0 failed (§0); it must stay that way after every
meaningful change, checked before moving to the next piece of work.

New test files (headless, no VS Code involved, matching "backend Planning
Mode must be independently tested" before any UI work begins):

- `test_operating_mode_policy.py` — the full ModePolicy table, including the
  three explicit matrix rows from §1.4 and the Code/Edit-unchanged property
  (assert identical `PermissionDecision`s with and without an explicit
  `operating_mode=CODE` for a representative sample of today's existing
  `test_permission.py` cases).
- `test_plan_mode_sandbox.py` — every existing sandbox attack test
  (`test_sandbox.py`'s traversal/UNC/drive-relative/reserved-device/reparse-
  point/sibling-prefix/`.git` cases) re-parametrized against
  `scope_root=.agent/plans`, confirming the exact same protections apply
  there as everywhere else.
- `test_plan_schemas.py` — `StructuredPlan`/`PlanReview`/`ResearchRequestBatch`
  parsing, valid and malformed cases.
- `test_plan_markdown.py` — deterministic rendering (snapshot-style),
  including the `Specification Version:`/`Status:` lines.
- `test_orchestrator_plan_mode.py` — `run_plan`/`revise_plan`/`approve_plan`/
  `reject_plan`, including: Coder never invoked (mock model asserts `.code()`
  never called), single automatic Reviewer pass, research loop-back with an
  allowed and a denied capability, bounded research rounds, artifact
  immutability after approval/rejection, `SpecStore` untouched until
  approval, spec-v1/v2/v3 historical file preservation across an
  amend-after-approval cycle, manual-Markdown-edit non-authority.
- `test_backend_api.py` — FastAPI `TestClient`-based: session
  create/message/events/plan/approve/revise/reject, missing/wrong-token 401,
  wrong-mode-for-route 409, `/mcp/servers` credential redaction,
  `/mcp/servers/{id}/preferences` narrowing-only behavior (attempt to "enable"
  a capability absent from trusted config/discovery and confirm it stays
  unusable).

## 15. Security boundaries

Summary of what's authoritative and unchanged vs. what's new, for the
self-review pass and for the user's final read:

**Unchanged, still the sole authority:**
`PermissionEvaluator` (one evaluator, one new parameter), `FilesystemSandbox`
(zero changes), `ToolGateway`'s six-step pipeline (zero changes to its
steps — only a new pass-through parameter), `SpecStore`/`SpecVersion` (zero
changes), `MCPServerRegistry`/`MCPServerConfig` (zero changes, still no
mutation method), `ABSOLUTE_DENY_TOOLS` (zero changes — git writes and
`shell.run` remain unconditionally denied in every mode including Plan).

**New, and where its authority actually comes from:**
`OperatingMode`/`ModePolicy` — authority is `PermissionEvaluator.evaluate`,
same as everything else. `MCPUserPreferences` — authority is intersection-only
narrowing, can't grant. The FastAPI layer — authority is zero; it's a
translation shim over `Orchestrator` calls and has no independent power to
allow anything.

**Explicitly still untrusted, never a grant of authority:** Planner output,
Coder output, Reviewer output, MCP responses, the Markdown plan file on disk,
GitHub content returned by MCP, and all VS Code UI input — none of these can
reach a code path that installs an MCP server, mutates trusted config,
changes a permission table entry, or bypasses the orchestrator, because no
such code path exists for any of them to reach in the first place (this
document adds none).

## Decisions log (flagged explicitly per the "ask on material ambiguity"
instruction — resolved here rather than left open, since each has a clearly
dominant answer; call out if any should be revisited)

1. **`SpecStore` stays fully unmodified; drafts never touch it until
   approval** (§7) — avoids risking a hardened, fully-tested module for a
   feature (draft/approved status) it doesn't otherwise need.
2. **Plan artifacts are immutable once APPROVED/REJECTED; new rounds create
   new files rather than mutating old ones** (§5.3) — satisfies historical
   preservation with no new mutation mechanism.
3. **The Markdown file is never re-read as input to any backend decision**
   (§6) — the simplest possible way to guarantee manual edits can't become
   authoritative.
4. **FastAPI + uvicorn** (asked and confirmed) for the transport, spawned as a
   token-authenticated child process bound to loopback only (§9).
5. **New `OperatingMode`/`ModePolicy` dimension with a `CODE`-default
   parameter on `PermissionEvaluator.evaluate`** (asked and confirmed) (§1).
6. **MCP research is a new schema field the orchestrator mediates, not a
   fixed pre-fetch** (asked and confirmed) (§2, §8).

## Known limitations (deliberate, not oversights)

1. **No Coder-side MCP research hook.** See §8. Code Mode makes zero MCP
   calls in Spec A, identical to today. Adding this would require changing
   `CoderCompleted`/`CoderBlocked`'s schema and is deferred to a later spec.
2. **Single-writer assumption per `spec_id`.** Concurrent `approve_plan` calls
   for the same `spec_id` from two different sessions is out of scope (§5.3,
   §7); the mismatch case is detected and surfaced as an error, not silently
   resolved.
3. **Reviewer plan critique is single-pass, not a negotiation loop.** (§4) —
   a deliberate complexity bound, matching why Code Mode's own fix-loop needs
   `max_fix_iterations`/stall-detection in the first place.

## Non-goals (explicitly out of scope, per the task's own constraints)

No cloud infrastructure, no remote agent services, no database, no
authentication/user-account system beyond the per-launch bearer token, no
multi-user support, no web dashboard, no custom editor, no vector database, no
additional model providers, no additional MCP servers beyond what's already
configured, no project rename. Git remains 100% human-controlled — no git
command of any kind is run as part of this work or its future implementation
plan.

