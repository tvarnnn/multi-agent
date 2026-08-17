# Phase 5 Report

## Files created

All new — no existing Phase 0-4 file was modified:

- `src/agent_platform/context/__init__.py`
- `src/agent_platform/context/limits.py` — `ContextLimits`, `DEFAULT_LIMITS`, `estimate_tokens`
- `src/agent_platform/context/bundle.py` — `ContextFile`, `ContextBundle`
- `src/agent_platform/context/staleness.py` — `ContextCache`
- `src/agent_platform/context/discovery.py` — tree walk, git-status parsing, file classification, import extraction/resolution
- `src/agent_platform/context/bundle_builder.py` — `build_context_bundle`, the one retrieval engine
- `src/agent_platform/context/role_context.py` — `build_planner_context`, `build_coder_context`, `build_reviewer_context`
- `tests/test_context_limits.py`, `test_context_staleness.py`, `test_context_discovery.py`, `test_context_bundle_builder.py`, `test_context_role_isolation.py`

## Files modified

**None.** Every file read and every git-status check goes through
`gateway.invoke(...)` — the exact same `ToolGateway` any model-requested
tool call uses. `tools/gateway.py`, `tools/registry.py`,
`security/permission.py`, `orchestrator/core.py`, and `orchestrator/
prompts.py` are all byte-for-byte unchanged from Phase 4.

## Retrieval architecture

One engine, `build_context_bundle`, used by three thin role-specific
entry points:

1. Walk the project tree via repeated `filesystem.list` calls (bounded
   by `max_retrieval_depth`), skipping noise directories
   (`.git`/`__pycache__`/`.pytest_cache`/`.venv`/`node_modules`/`*.egg-info`).
2. Pull changed files via `git.status` (parsed from the existing
   porcelain output Phase 1's tool already returns — no new git
   capability).
3. Classify every discovered path deterministically by filename pattern:
   `test` / `config` / `documentation` / `other`.
4. Match `reference_hints` (free text — a user request, a spec's
   goals/constraints/acceptance criteria, a reviewer's issue
   descriptions) against file names/paths by substring — deterministic,
   no ML, no embeddings.
5. For every "referenced" or "changed" seed file, read it and extract
   top-level Python imports, resolving names that correspond to an actual
   file in the tree as "dependency" candidates.
6. Pull test files whose naming-convention stem matches a seed file's
   stem, plus every config/documentation file in the tree.
7. If nothing was referenced at all, fall back to a single bounded tree
   *listing* (file names only, never content) — the only "broader
   context" this phase includes, and only when nothing more targeted
   exists.
8. Sort everything by a fixed priority
   (`referenced < changed < dependency < test < config < documentation < tree`,
   ties broken alphabetically by path — the alphabetical tiebreak is what
   makes ordering deterministic across repeated calls, proven by test),
   then materialize files up to the limits, recording anything cut in
   `excluded_paths`.

## Context limits

`ContextLimits`: `max_files` (20), `max_total_bytes` (200,000),
`max_tokens_estimate` (50,000, via a dependency-free ~4-chars/token
heuristic), `max_individual_file_bytes` (20,000), `max_retrieval_depth`
(6), `max_search_results` (50, reserved for a future search-based
retrieval path — nothing in this phase performs an unbounded search that
needs it yet). Degradation is always explicit: a file dropped for
exceeding `max_files`/`max_total_bytes`/`max_tokens_estimate` appears in
`ContextBundle.excluded_paths`; a file exceeding
`max_individual_file_bytes` is truncated in place with `truncated=True`,
never silently included in full or silently dropped.

## Role-specific context behavior

- **Planner** (`build_planner_context`): takes the raw user request as
  its only reference hint. This is the *only* entry point that ever sees
  raw user text — matching Phase 2's `orchestrator/prompts.py`, where the
  Planner is likewise the only role that reads `context["request"]`.
- **Coder** (`build_coder_context`): takes a `SpecVersion` and optional
  `ReviewerOutput` — no parameter for user conversation exists at all
  (proven structurally via `inspect.signature`, not just by not passing
  one).
- **Reviewer** (`build_reviewer_context`): takes a `SpecVersion` and
  `CoderCompleted` — reads only `file_writes` paths for hints, never
  `.summary`. Proven with a coder output whose `summary` text explicitly
  names an unrelated file: that file is *not* pulled into the reviewer's
  bundle, confirming summary text plays no role in retrieval.

All three share one engine and one set of limits; nothing about the
retrieval algorithm itself differs by role beyond which hints and which
`Role` (and therefore which gateway permissions) are used.

## Tests added

40 new tests across 5 files, all passing, zero network:
- `test_context_limits.py` — 4
- `test_context_staleness.py` — 5
- `test_context_discovery.py` — 15
- `test_context_bundle_builder.py` — 11 (including changed-file
  priority via a git-status-stubbed gateway, deterministic ordering
  across repeated calls, individual-file truncation, staleness detection
  with the fresh read always winning, and the prompt-injection
  inert-retrieval proof)
- `test_context_role_isolation.py` — 5

## Exact test count

**685 passed, 0 failed, 0 skipped**
(`python -m pytest tests/ --ignore=tests/test_ollama_integration.py
--ignore=tests/test_mcp_real_integration.py -q`) — 645 from Phase 0-4
plus these 40, zero regressions.

## Known limitations

- Import extraction and resolution is Python-only, top-level, single-hop
  (an import's own imports are not transitively followed) — sufficient
  for this project's current size, not a general dependency graph.
- `reference_hints` matching is exact-substring, case-insensitive — a
  hint has to actually contain a file's name or path text. This is
  simple and fully deterministic, but it will miss a file that's
  conceptually relevant without being named (e.g. a request to "add
  authentication" won't find `auth.py` unless the word "auth.py" or a
  matching path substring appears in the hint text). This is a
  deliberate simplicity trade-off, not an oversight — see the verdict
  below.
- No git commands were run this session, including inside test fixtures;
  changed-file-priority behavior against a *scoped* (`scoped: True`) git
  repository was tested via an explicit gateway stub rather than a real
  repository, since Phase 1 never exercised that path either and this
  phase deliberately doesn't start.

## Was vector/indexed retrieval actually necessary?

**No.** At this project's current size (dozens of files, all within a
few directories), deterministic priority-ordered retrieval — direct
reference matching, git-changed-file tracking, single-hop import
following, naming-convention test/config/doc matching, all bounded and
inspectable — fully covers "find the relevant files" without missing
anything a semantic/vector approach would have caught. Introducing a
vector index now would add a real dependency (an embedding model or
service), persistent infrastructure (an index to build and keep in
sync), and non-determinism (nearest-neighbor retrieval isn't perfectly
reproducible the way substring matching and priority sorting are) to
solve a problem this phase's heuristics already solve at this scale.

The one piece built with a future index in mind rather than needed by
this phase alone is `ContextCache`'s staleness detection
(`context/staleness.py`) — a session-scoped, content-hash-based
primitive, not a persistent index itself. It exists so that if a much
larger real project someday demonstrates — by measurement, not
assumption — that heuristic retrieval is missing genuinely relevant
files, a persistent/semantic index has a tested foundation for "is this
cached view still current" to build on, rather than starting from
nothing. Nothing in this phase currently depends on that primitive being
backed by anything more than the in-memory dict it is.
