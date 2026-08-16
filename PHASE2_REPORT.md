# Phase 2 Report

## Implemented
- **`ModelProvider` protocol** (`orchestrator/model_provider.py`) —
  formalizes the duck-typed contract `Orchestrator` already relied on in
  Phase 1. `orchestrator/core.py` was not modified at all in this phase.
- **Structured-output JSON schemas** (`orchestrator/ollama_schemas.py`) —
  one schema per role, passed as Ollama's `format` parameter for
  grammar-constrained decoding, kept in lockstep with Phase 1's
  `model_schemas.py` parsers (syntactic constraint at the model layer,
  semantic validation still independent and unchanged).
- **Prompt builders** (`orchestrator/prompts.py`) — one function per role,
  each reading only the fields Phase 1's orchestrator actually puts in
  that role's context dict. Tested to prove Coder's prompt never contains
  raw user conversation text and Reviewer's prompt never contains the
  Coder's own summary/self-justification, even when present in the dict.
- **`OllamaModelProvider`** (`orchestrator/ollama_provider.py`) — real
  HTTP client via `/api/generate`, injectable transport (unit-testable
  without network), bounded transport retries, explicit model
  load/unload lifecycle (`keep_alive: 0` unload before switching to a
  different model), malformed-JSON-response handling that degrades to a
  sentinel dict rather than raising (so Phase 1's existing retry/escalate
  logic in `core.py` handles it unchanged), and a `telemetry_log`
  recording real per-call durations and token counts from Ollama's own
  response metadata.
- **GPU telemetry** (`orchestrator/gpu_telemetry.py`) — best-effort
  `nvidia-smi` VRAM query, never raises, used for real measurements below.

## Test results
- **Deterministic suite (Tasks 1-6): 570/570 passed, 0 failed, 0
  skipped**, zero network access — the full Phase 0 + Phase 1 + Phase 2
  (fake-transport) suite together.
- **Real Ollama integration suite (Task 7): 5/5 passed**, in 160.48s
  wall-clock, against the actually-running local Ollama server (0.32.13)
  and the RTX 5070. This is the first test file in the project that uses
  the network (localhost only) and real GPU inference — clearly separate
  from the rest.

## Real measurements

### Model footprint and residency
| Model | Disk size | VRAM when loaded | GPU/CPU split |
|---|---|---|---|
| `phi4-reasoning:plus` (Planner + Reviewer) | 11 GB | 11.4-11.5 GB used | **85% GPU / 15% CPU** — does not fully fit in 12GB |
| `qwen2.5-coder:14b` (Coder) | 9.0 GB | 10.4 GB used | 100% GPU — fits fully |

**This is the single most important empirical finding of this phase**:
`phi4-reasoning:plus` does not fit entirely in the RTX 5070's 12GB VRAM.
Ollama automatically falls back to a 15% CPU / 85% GPU split, and the
card sits at 93%+ VRAM utilization with only ~800MB headroom while it's
loaded — confirming `architecture-review-v2.md` §1.1's VRAM-budget concern
was not theoretical. `qwen2.5-coder:14b`, by contrast, fits fully on GPU
with real headroom to spare.

### Load time / inference latency (real numbers, both cold and warm)
| Call | Load time | Eval (generation) time | Output tokens | Notes |
|---|---|---|---|---|
| Planner, cold (first call this session) | 25.9s | 9.2s (103 tokens, ~11 tok/s) | 103 | Partial CPU offload — visibly slower generation |
| Planner, warmer (later call) | 9.6s | 10.6s (289 tokens) | 289 | Faster load — OS/driver page cache from the earlier load, not a true cold start |
| Coder, cold | 14.5s | 4.2s (258 tokens, ~61 tok/s) | 258 | Fully on GPU — ~5.5x faster token rate than the partially-offloaded planner |
| Fix-loop calls (7 calls across a full run) | 6.9-8.8s each | 1.5-1.7s each | short | Every single fix-loop step swaps models (Coder → Reviewer → Coder...), so **every step pays a ~7-9s reload**, not just phase boundaries |

The fix-loop finding is significant: because Planner/Reviewer share one
model but Coder is different, `IMPLEMENT_FIX → REVIEW` alternation forces
a real model swap on *every* iteration. Across the 3-attempt real run
below, that's roughly 6 extra swaps × ~8s ≈ 48s of pure reload overhead
layered on top of actual inference — a concrete, measured version of the
"cold-swap tax" `architecture-review-v2.md` §1.1 and
`architecture-review-v3` §4 discussed in the abstract.

### Unload behavior
Confirmed working, both via a raw exploratory call and via
`OllamaModelProvider`'s real `_ensure_loaded`: an explicit `keep_alive: 0`
request dropped VRAM usage from 11389MiB back to the 1208MiB idle
baseline within ~2 seconds, and `ollama ps` correctly showed zero
resident models afterward. Switching Planner→Coder triggered exactly one
real unload call for the previous model; switching Planner→Reviewer
(same underlying weights) triggered **zero** unload calls, confirmed both
in the fake-transport unit tests (Task 5) and against the real server
(Task 7).

### Context length
Ollama reports a runtime context window of **4096 tokens** for both
models as configured on this machine (via `ollama ps`) — this is Ollama's
default allocation, not necessarily the model's architectural maximum. A
~24,000-character padded prompt (≈2050 prompt tokens) was ingested
successfully with no truncation error and produced valid structured
output. The actual truncation/failure point above 2050 tokens was not
found — time-boxed rather than explored exhaustively; see Remaining
Concerns. Even at 4096 tokens, this is a tight budget (roughly 3000
words) that reinforces `architecture-review-v2.md` §1.5's point: whole-
file/whole-repo context dumping is not viable, and RAG-based context
selection is load-bearing infrastructure, not a nice-to-have.

### Real model output quality (informational, not a pass/fail gate)
The real Planner did not reliably follow the prompt's request to phrase
acceptance criteria as `file:<path>` — most real responses used full
sentences instead (e.g. "The implementation includes a file named
main.py..." rather than `file:main.py`), which `AcceptanceCriteriaFileValidator`
correctly treats as advisory rather than a hard gate, since it doesn't
match the expected prefix. This is a genuine, useful finding: JSON-schema
grammar constraint enforces *structure* (right fields, right types) but
not the *semantic formatting* of string values inside that structure —
prompt engineering or a stricter acceptance-criteria mini-format would be
needed to make this reliable, not just a JSON schema.

Separately, one real Coder response for a "GPU utilization endpoint"
request produced code that used `psutil.sensors_temperatures()` — a
plausible-looking but technically wrong choice for GPU utilization
monitoring. This is exactly the kind of subtly-incorrect-but-fluent output
the Reviewer role exists to catch, and is a real (not hypothetical)
example of why independent review matters, observed in this session.

### Full real orchestrator run
One complete `Orchestrator.run(...)` call, real models throughout, capped
at `max_fix_iterations=2` for this test: reached **`ESCALATE_TO_USER`**,
not `COMPLETE`, after 90.05s wall-clock and 7 real model calls (1 plan +
3 coder + 3 reviewer). Transition sequence:
```
PLAN, VALIDATE_PLAN, IMPLEMENT, TEST, REVIEW, FINAL_VALIDATION, FEEDBACK,
IMPLEMENT_FIX, TEST, REVIEW, FINAL_VALIDATION, FEEDBACK,
IMPLEMENT_FIX, TEST, REVIEW, FINAL_VALIDATION, FEEDBACK,
STUCK, ESCALATE_TO_USER
```
This is Phase 1's fix-loop cap logic working correctly against real,
imperfect model behavior for the first time — the reviewer kept rejecting
across all 3 attempts, the cap tripped exactly at `max_fix_iterations`,
and the orchestrator escalated cleanly rather than looping indefinitely
or crashing. Both `COMPLETE` and `ESCALATE_TO_USER` were treated as valid
outcomes for this test (a real model choosing not to converge in 2
attempts is informative, not a bug), and this run demonstrates exactly
that distinction in practice.

## Security / determinism invariants confirmed under real models
- `orchestrator/core.py` required zero changes — `OllamaModelProvider` is
  a genuine drop-in replacement for `FakeModelProvider`, proven by running
  the unmodified Phase 1 state machine against real inference.
- Malformed real-model output degrades to a sentinel dict
  (`{"_malformed_raw_text": ...}`) that fails Phase 1's schema parsers
  exactly like a scripted malformed `FakeModelProvider` response would —
  no new orchestrator-side handling was needed, and none was added.
- The typed tool gateway was the only path to file writes throughout the
  real orchestrator run — the model provider never touched the filesystem
  directly.
- No git write capability was added; nothing in this phase touches git at
  all, and this session ran no git commands.
- Context isolation (Task 3's tests) holds structurally regardless of
  which provider is in use, since it's enforced by what the prompt
  builders read, not by the provider or the model's behavior.

## Scope decisions and flags for the user
- **Model reversion flagged, not silently applied**: this phase's
  instructions specified `phi4-reasoning:plus` for both Planner and
  Reviewer (shared weights), reverting the `Llama 3.1 8B Instruct`
  reviewer choice made explicitly earlier in this session. Implemented as
  instructed; flagged at the start of this phase and again here since the
  empirical data now shows the shared-weights choice has a real,
  measured cost — sharing weights but not context still forces a full
  model swap+reload every review, because the *providers* still have to
  physically unload/reload weights to keep the two-model VRAM budget,
  even when the two "roles" are conceptually the same model.
- No MCP work was done, per the explicit instruction.
- `keep_alive` is not set on real invocation payloads (only on explicit
  unload calls, where it's `0`) — Ollama's server-side default keep-alive
  window governs residency between calls otherwise, which is why some
  "cold" loads in the measurements above were actually partially warm
  from OS/driver caching rather than a true first-ever load.

## Remaining concerns
- The actual context-window ceiling (where real truncation/failure
  begins) was not found — only confirmed that ~2050 prompt tokens work
  fine under a 4096-token configured window. Finding the real ceiling
  would need either configuring a larger `num_ctx` or pushing well past
  4096 tokens, both left for a future session given real-inference time
  cost.
- `phi4-reasoning:plus`'s partial CPU offload (85/15 split) means its
  real latency is meaningfully worse than a fully-GPU-resident model of
  similar size would be — worth explicit consideration before treating
  the "Planner + Reviewer share phi4-reasoning:plus" choice as final,
  independent of the earlier model-selection debate in this session.
- This session ran no git commands, per the standing instruction — all of
  Phase 0 through Phase 2's code remains uncommitted, left for the user
  to review.
