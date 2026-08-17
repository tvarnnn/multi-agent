# Phase 8 Report — Empirical SWE Benchmark: Configuration A vs Configuration B

**Scope discipline for this phase:** measurement only. No file under
`src/agent_platform/` was modified to produce this report. All benchmark
code lives in `benchmark/` (a new, self-contained directory) and imports
from the platform without the platform ever importing back. No git
command of any kind (including read-only) was run against the real
project this phase. Zero manual intervention occurred during any run:
where a run reached `AWAITING_USER_INPUT`, that is recorded as the run's
terminal outcome, not worked around.

Every number below is labeled **MEASURED** (read directly off collected
data), **DERIVED** (computed from measured values by a documented
formula), or **INTERPRETATION** (a judgment call about what the numbers
mean). Raw data lives in `benchmark/results/raw_results.jsonl` (20
records, one per task/configuration pair) and
`benchmark/results/repeat_results.jsonl` (a 6-run repeat of 3
representative tasks under both configurations, added to probe run-to-run
variance). `benchmark/results/analysis_summary.json` is the full
machine-readable aggregation this report is built from.

## 1. Configurations Under Test

| | Configuration A | Configuration B |
|---|---|---|
| Planner | phi4-reasoning:plus | phi4-reasoning:plus |
| Coder | qwen2.5-coder:14b | qwen2.5-coder:14b |
| Reviewer | phi4-reasoning:plus (shared weights with Planner) | llama3.1:8b (distinct weights) |
| Distinct model weights resident over a run | 2 | 3 |

Both configurations are wrapped identically: real `OllamaModelProvider` →
`ContextAwareModelProvider` (Phase 5 context retrieval, unmodified) →
`Orchestrator` (Phase 6, unmodified). Iteration caps, identical for both:
`max_output_retries=2`, `max_clarification_rounds=1`, `max_fix_iterations=2`
— MEASURED constants, chosen before any run to bound worst-case wall-clock
time for a 20-run sweep while still exercising the fix and clarification
loops for real. Validator: `CompositeValidator(AcceptanceCriteriaFileValidator(),
TestRunValidator(...))`, identical for both — COMPLETE requires both the
Planner's own file-existence criteria and a real, passing `test.run`
invocation, matching Phase 6's demo pattern. Session mode: `AUTO` for both.

Hardware baseline (MEASURED, `nvidia-smi` before any run): 1104 / 12227
MiB VRAM used. All three models confirmed present via `ollama list`
immediately before the sweep: `llama3.1:8b` (4.9 GB), `qwen2.5-coder:14b`
(9.0 GB), `phi4-reasoning:plus` (11 GB).

## 2. Harness Design (methodology)

The harness (`benchmark/`) never modifies orchestrator, provider, prompt,
or context-retrieval code. Instrumentation is two non-invasive
`TimingWrapper` layers stacked around the real provider chain: one wraps
the raw `OllamaModelProvider` (pure generation time), the other wraps
`ContextAwareModelProvider` (generation + context retrieval combined).
`outer_duration − inner_duration` isolates context-retrieval time without
touching `context_aware_provider.py`. Per-call Ollama telemetry
(`load_duration_ns`, `eval_duration_ns`, `total_duration_ns`) is read
directly off Phase 2's existing `OllamaModelProvider.telemetry_log` —
already built, unmodified. VRAM is sampled every 0.5s on a background
thread via Phase 2's `query_gpu_memory()`, also unmodified.

**Ground truth is established independently of the model and of the
orchestrator's own validator.** Each task (except the two deliberately
ambiguous ones) has a hidden pytest file, authored by the harness and
written to the project directory only *after* the orchestrator run
finishes, then executed directly via `pytest` — never seen by any model,
never gating anything during the run. This is compared against (a) the
orchestrator's own internal validator result at each review cycle
(already flowing through `context["validation_result"]`, intercepted by
the timing wrapper) and (b) the Reviewer's decision, to compute
false-positive/false-negative rates against a genuinely independent
standard rather than the system's own (possibly wrong) self-assessment.

**Known measurement limitation:** "model swap" is defined structurally
(the target role's model differs from the immediately preceding call's
model), not from Ollama's actual residency state. If Ollama's own
default keep-alive expired during a long tool-execution gap between two
calls of the *same* model, that reload is invisible to the swap counter
even though it was physically a cold load. The raw `ollama_load_duration_ns`
per call is unaffected by this and is reported alongside the derived
swap/no-swap split so this can be cross-checked.

**MCP was not registered for this benchmark.** Phase 4 built MCP as
ordinary `ToolSpec`s requiring a live client connection; Phase 6
confirmed that no role's structured-output schema (`CoderCompleted`,
`CoderBlocked`, `PlannerSpec`, reviewer output) has a field for
requesting a tool call mid-task. An MCP call cannot be triggered during
an autonomous run regardless of registration — this is a structural
property of the current orchestrator, identical for both configurations,
confirmed by re-reading `model_schemas.py` and `core.py` before the
sweep. MCP metrics are therefore 0/N/A by design, not by benchmark
oversight — this is itself the finding for that section.

## 3. Dataset (10 tasks)

| ID | Category | Ground truth applicable? |
|---|---|---|
| task01_simple_feature | Greenfield single-file function + test | Yes |
| task02_bug_fix | Existing failing test, fix impl not test | Yes |
| task03_multi_file | Two new files, cross-file import | Yes |
| task04_api_integration | Local dict-backed "config API" + required error handling | Yes |
| task05_test_creation | Untested existing function; write tests, don't touch impl | Yes |
| task06_ambiguous_requirement | "Make the code better." — maximally vague | No (by design) |
| task07_clarification_required | Underspecified security-relevant request ("add authentication") | No (by design) |
| task08_seeded_defect | Subtle wrong-divisor bug, existing failing test | Yes |
| task09_security_sensitive | User-path file read — tests whether path-traversal risk surfaces | Yes (+ qualitative security heuristic) |
| task10_mcp_context | Small self-contained utility — MCP/context usage probe | Yes |

Each task's `starting_files` and hidden-test correctness were validated
before the real sweep: hand-written correct solutions were confirmed to
pass every hidden test, hand-written wrong solutions were confirmed to
fail, and both seeded-bug tasks (02, 08) were confirmed to genuinely fail
their existing test before any fix (`benchmark/dataset.py`).

## 4. Outcome Results (MEASURED, n=1 per task/config)

| Task | Config A final_state | A ground truth | Config B final_state | B ground truth |
|---|---|---|---|---|
| task01_simple_feature | ESCALATE_TO_USER | **True** | COMPLETE | **True** |
| task02_bug_fix | ESCALATE_TO_USER | False | AWAITING_USER_INPUT | False |
| task03_multi_file | ESCALATE_TO_USER | **True** | ESCALATE_TO_USER | False |
| task04_api_integration | ESCALATE_TO_USER | **True** | ESCALATE_TO_USER | False |
| task05_test_creation | COMPLETE | **True** | COMPLETE | **True** |
| task06_ambiguous_requirement | AWAITING_USER_INPUT | N/A | AWAITING_USER_INPUT | N/A |
| task07_clarification_required | ESCALATE_TO_USER | N/A | ESCALATE_TO_USER | N/A |
| task08_seeded_defect | AWAITING_USER_INPUT | False | ESCALATE_TO_USER | False |
| task09_security_sensitive | ESCALATE_TO_USER | **True** | ESCALATE_TO_USER | False |
| task10_mcp_context | ESCALATE_TO_USER | **True** | COMPLETE | **True** |

Outcome distribution (MEASURED):

| Configuration | COMPLETE | ESCALATE_TO_USER | AWAITING_USER_INPUT |
|---|---|---|---|
| A | 1/10 | 7/10 | 2/10 |
| B | 3/10 | 5/10 | 2/10 |

Ground-truth correctness among the 8 evaluable tasks (MEASURED):

| Configuration | Ground-truth passed | Rate (DERIVED) |
|---|---|---|
| A | 6/8 (task01,03,04,05,09,10) | 75% |
| B | 3/8 (task01,05,10) | 37.5% |

**INTERPRETATION — this is the headline finding of the phase.**
`final_state == COMPLETE` rate is a poor proxy for actual code
correctness here, and it is *misleading in opposite directions for the
two configurations*: Configuration A produced functionally correct code
in 6 of 8 evaluable tasks but only reached the orchestrator's own
`COMPLETE` state once — the other 5 correct runs escalated anyway.
Configuration B reached `COMPLETE` three times but was only actually
correct in those same 3 cases — its ground-truth accuracy tracks its
completion rate far more closely than Configuration A's does.

Root-caused (MEASURED, by inspecting the actual final workspace files for
the escalated-but-correct Configuration A runs):
- **task01**: the Coder wrote a genuinely correct `calc.py`, but named
  its test file `tests.py`, which does not match pytest's default
  discovery patterns (`test_*.py` / `*_test.py`). The orchestrator's own
  `TestRunValidator` therefore saw "no tests ran" on every attempt,
  which reads as an identical failure every time, tripping the
  `is_repeated_identical_test_failure` stall heuristic. My independent
  hidden-test check explicitly names its own file as a pytest argument,
  bypassing default discovery — this is why ground truth passed while
  the internal gate never did.
- **task09/task10**: same pattern — a directory or file literally named
  `tests` with no `.py` suffix or pytest-recognizable name, invisible to
  default pytest collection.
- **task03**: by contrast, the coder's tests *were* correctly named
  (`test_shapes.py`, `test_geometry_utils.py`) and pass cleanly when
  re-run directly against the final file state (`2 passed in 0.02s`).
  The stall heuristic still fired mid-run, most likely because an
  earlier fix attempt produced a validation-failure detail string
  identical to a prior attempt's before the files converged to a working
  state — a real, observed case of `is_repeated_identical_test_failure`
  firing on transient, not persistent, failure repetition.

This is a genuine limitation surfaced by real data, not a benchmark
artifact: Phase 6's stall-detection heuristics (necessary and,
individually, well-justified — see PHASE6_REPORT.md) can end a
recoverable run when the Coder's own test-naming choices — not its
logic — repeatedly defeat default pytest discovery. Neither
Configuration is exempt; this is orthogonal to which Reviewer model is
in use.

## 5. Iteration & Latency (MEASURED / DERIVED, n=10 runs per config)

| Metric | Config A mean | Config A median | Config B mean | Config B median |
|---|---|---|---|---|
| Wall-clock per task (s) | 61.8 | 70.0 | 45.7 | 52.7 |
| Model calls per task | 4.5 | 5.0 | 3.6 | 4.0 |
| Model swaps per task | 3.3 | 4.0 | 2.3 | 2.5 |
| Tool invocations per task | 25.4 | 26.0 | 17.9 | 17.5 |
| State transitions per task | 11.2 | 14.0 | 8.1 | 8.0 |

**INTERPRETATION:** Configuration B is faster and shorter-running on
every one of these axes. Part of this is mechanical, not qualitative:
Configuration A's escalations tend to happen *later* (after a full fix
cycle) because its code is more often actually salvageable, so the
orchestrator keeps trying; several of Configuration B's escalations
happen *earlier* because the code is wrong in ways the fix loop doesn't
resolve within the retry budget. Lower call/swap/time counts should not
be read as "more efficient" in isolation from the correctness finding in
§4.

## 6. Latency Breakdown by Role (MEASURED, load vs. generation separated)

All times in seconds. "Generation" = `total_duration − load_duration`
(DERIVED; Phase 2's telemetry does not separately expose prompt-processing
time, so this bucket includes both prompt processing and output-token
generation — reported honestly as a combined figure). "Prompt processing"
below is a further DERIVED split: `total − load − eval` (Ollama's own
`eval_duration` is output-token generation only).

| Config | Role | n calls | Mean load (s) | Mean eval/gen (s) | Mean derived prompt-processing (s) |
|---|---|---|---|---|---|
| A | planner | 15 | 2.62 | 4.22 | 0.25 |
| A | coder | 17 | 6.98 | 3.82 | 0.24 |
| A | reviewer | 13 | 8.73 | 2.36 | 0.97 |
| B | planner | 15 | 4.64 | 5.26 | 0.38 |
| B | coder | 12 | 6.46 | 3.99 | 0.22 |
| B | reviewer | 9 | 4.32 | 0.87 | 0.20 |

**MEASURED:** Configuration B's reviewer (llama3.1:8b) has both a lower
mean load time (4.32s vs 8.73s) and a dramatically lower mean generation
time (0.87s vs 2.36s) than Configuration A's reviewer (phi4-reasoning:plus
reused). **INTERPRETATION:** this is consistent with llama3.1:8b being a
smaller, fully-GPU-resident model producing shorter structured outputs,
against phi4-reasoning:plus's documented (Phase 2) partial CPU offload on
this 12GB card and its longer, more elaborated reasoning-style outputs.
Context-retrieval time is negligible for both configurations and every
role: MEASURED range across all 81 calls with a context bundle was
0.0–0.032s, consistent with Phase 5's bounded, non-vector-search design
holding up under real end-to-end load.

## 7. Model-Swap Overhead (MEASURED / DERIVED)

| Config | Swap-event mean load (s) | No-swap mean load (s) | n swap / n no-swap | Derived overhead per swap (s) |
|---|---|---|---|---|
| A | 7.87 | 0.95 | 33 / 12 | **6.92** |
| B | 5.84 | 3.97 | 23 / 13 | **1.87** |

**INTERPRETATION, with the caveat from §2 applied directly:** Configuration
A's swap overhead (≈6.9s) matches Phase 2's earlier finding that
phi4-reasoning:plus's partial CPU offload makes every reload of it
expensive, and Configuration A swaps into/out of phi4-reasoning:plus far
more often (it holds both the Planner and Reviewer roles). Configuration
B's *apparent* no-swap load time (3.97s) is suspiciously high for a
"model already resident" case — this is the keep-alive-expiry caveat from
§2 in action: several of Configuration B's structurally-labeled "no swap"
calls were very likely real cold reloads that Ollama triggered on its own
default keep-alive timeout during a long tool-execution gap, not proof
that same-model reuse is actually cheap in this configuration. The
1.87s figure should be read as a **lower bound that is very likely
underestimated**, not a clean measurement — a genuine limitation of this
harness's model-swap definition, disclosed rather than smoothed over.

## 8. Hardware / VRAM (MEASURED)

| Config | Mean baseline (MiB) | Mean peak (MiB) | Max peak observed (MiB) |
|---|---|---|---|
| A | 1109 | 11307 | 11322 |
| B | 3341 | 11550 | 11912 |

Card capacity: 12227 MiB. **MEASURED:** both configurations peak within
~300–900 MiB of the card's total capacity on this hardware — headroom is
thin under either configuration, consistent with Phase 2's finding that
phi4-reasoning:plus alone does not fully fit this 12GB card.
**INTERPRETATION:** the higher mean *baseline* for Configuration B (3341
vs 1109 MiB) is most likely a sequencing artifact — Configuration B ran
second in the sweep, after Configuration A had already exercised the
same Ollama server process — rather than a property of Configuration B
itself; the two configurations never run concurrently and this harness
did not isolate baseline sampling from prior-run residual state. Treat
the peak figures as the reliable comparison and the baseline difference
as unverified.

## 9. Reviewer Quality

### 9a. Internal-gate agreement (MEASURED, every review cycle, n = all reviewer calls)

Reviewer decision vs. the orchestrator's own `CompositeValidator` result
at that same cycle:

| Config | n | False-positive rate (wrongly approved bad) | False-negative rate (wrongly rejected good) | Accuracy |
|---|---|---|---|---|
| A | 13 | **92.3%** (12/13) | N/A (0 negative cases) | 7.7% |
| B | 9 | 62.5% (5/8) | 0.0% (0/1) | 44.4% |

**INTERPRETATION — important, and easy to over-read:** Configuration A's
Reviewer (phi4-reasoning:plus) approved code the deterministic validator
had just rejected in 12 of 13 review cycles. Read in isolation this looks
like a severe reviewer defect. It is not catastrophic *for the system's
soundness*, because `Orchestrator._final_validation` ANDs reviewer
approval with the deterministic `validation_result.passed` — a Reviewer
`APPROVE` can never by itself complete a task whose tests are actually
failing (this is Phase 1/6's designed, unmodified behavior, verified in
`core.py` and `validation.py`, and empirically confirmed by the fact that
none of these 12 false-approvals produced a false `COMPLETE`). What it
*does* cost is efficiency and legibility: an over-approving Reviewer adds
no filtering value in the loop and pushes essentially all the real work
of gatekeeping onto the deterministic validator and the stall-detection
heuristics, which is a real quality difference between the two Reviewer
choices even though it didn't produce an unsound completion in this
sweep.

### 9b. Final-decision agreement against independent ground truth (MEASURED, last reviewer call per run, n=6 evaluable per config)

| Config | n | False-positive rate | False-negative rate | Accuracy |
|---|---|---|---|---|
| A | 6 | 0.0% (0/6) | N/A (0 negative cases) | **100%** |
| B | 6 | 40.0% (2/5) | 0.0% (0/1) | **66.7%** |

**INTERPRETATION:** at the *final* decision point of a run (as opposed to
every intermediate cycle in 9a), Configuration A's Reviewer was right
every time in this sample — its apparent over-approval in 9a never
actually coincided with genuinely broken final code. Configuration B's
Reviewer approved code that was still broken in 2 of 6 final decisions.
This is the strongest single piece of evidence in this benchmark that
favors phi4-reasoning:plus as Reviewer over llama3.1:8b for final-judgment
reliability — but n=6 per configuration is a very small sample, and this
finding should be read alongside §12's variance check before being
treated as settled.

## 10. MCP Metrics

**MEASURED:** 0 MCP tool calls occurred in any of the 20 runs, for
either configuration. **INTERPRETATION:** this is not a capability gap
discovered by the benchmark — it was known before the sweep started (see
§2) and is architectural: no role's structured-output schema has a field
for requesting a tool call mid-task, so an MCP call could not have been
triggered regardless of what got registered. `task10_mcp_context` was
retained in the dataset anyway because it still exercises everything
else (a real end-to-end run, ground-truth scoring, context retrieval) —
its category label documents the intended future probe, not an achieved
measurement.

## 11. Context-Retrieval Metrics

**MEASURED:** across all 81 model calls with a context bundle attached,
retrieval time ranged 0.0–0.032s (mean well under Phase 5's own reported
bounds). Zero tool denials occurred during context retrieval or anywhere
else in the sweep (`tool_denial_count == 0` for all 20 runs).
**INTERPRETATION:** at this project's current scale (single- and
few-file greenfield/bugfix tasks), context retrieval is not a measurable
cost center for either configuration — consistent with Phase 5's original
rejection of vector search as unneeded at this scale, and this benchmark
adds a second, independent, real-workload confirmation of that call.

## 12. Variance / Repeatability (MEASURED, second independent run)

The primary sweep is n=1 per (task, configuration) cell — insufficient on
its own to separate a real configuration effect from LLM sampling noise.
A second, independent run of 3 representative tasks
(task01_simple_feature, task02_bug_fix, task08_seeded_defect) under both
configurations was executed to probe this (`benchmark/results/repeat_results.jsonl`).

| Task | Config | Run 1 final_state | Run 1 gt | Run 2 final_state | Run 2 gt | gt agree? |
|---|---|---|---|---|---|---|
| task01 | A | ESCALATE_TO_USER | True | COMPLETE | True | **yes** |
| task01 | B | COMPLETE | True | ESCALATE_TO_USER | True | **yes** |
| task02 | A | ESCALATE_TO_USER | False | AWAITING_USER_INPUT | False | **yes** |
| task02 | B | AWAITING_USER_INPUT | False | ESCALATE_TO_USER | False | **yes** |
| task08 | A | AWAITING_USER_INPUT | False | ESCALATE_TO_USER | False | **yes** |
| task08 | B | ESCALATE_TO_USER | False | ESCALATE_TO_USER | False | **yes** |

**MEASURED, and the single most load-bearing result in this report:**
ground-truth correctness agreed across both independent runs in **6/6**
repeated cells (100%), while `final_state` (the label a naive reading of
this system would use) agreed in only **2/6** (33%) — it flipped between
`COMPLETE`/`ESCALATE_TO_USER`/`AWAITING_USER_INPUT` for the same task and
configuration across runs in 4 of 6 cases. This independently confirms
§4's finding with a second sample: `final_state` alone is materially
unreliable as a quality signal for this system as currently tuned, while
ground-truth functional correctness is markedly more stable run-to-run.

**MEASURED, second finding from the repeat:** both configurations failed
to actually fix the seeded/existing bug in task02 and task08 in *both*
independent runs (4/4 gt=False). Since this failure is identical across
Configuration A and B, it is attributable to the Coder
(qwen2.5-coder:14b, identical in both configurations) or to the fix-loop
design, not to Reviewer choice — DERIVED conclusion: Reviewer identity
does not appear to drive the bug-fix weakness observed in this dataset.

**MEASURED, third finding:** wall-clock time for the *same* task and
configuration varied enormously between runs — task08 under Configuration
B took 52.2s in run 1 and 416.5s in run 2. Inspecting the run 2 trace
directly: two Planner (phi4-reasoning:plus) calls had `eval_duration` of
85.8s and 108.2s respectively — long but legitimate extended-reasoning
generations, not a stall or transport retry. **INTERPRETATION:** wall-clock
time has high variance for this Planner model specifically and should
never be read from a single run; the mean/median figures in §5 should be
treated as directional, not precise, for exactly this reason.

Reviewer final-decision accuracy (§9b) extended with the repeat sweep's
evaluable pairs (A: 2 more, both correct; B: 1 more, correct; the other
2 B repeat tasks never reached a reviewer decision before escalating):
**Configuration A: 8/8 correct across both sweeps (100%). Configuration
B: 5/7 correct across both sweeps (71.4%).** The direction and rough
magnitude of §9b's finding held up under a second, independent sample.

## 13. Final Recommendation

**On which configuration to use by default: Configuration A
(phi4-reasoning:plus as both Planner and Reviewer), with a caveat.**
This is supported by the strongest, most-replicated evidence in this
report — ground-truth code correctness was higher for Configuration A in
the primary sweep (75% vs 37.5%) on tasks where the two configurations
actually differed in outcome, and Configuration A's Reviewer was right
about its final judgment far more often across both sweeps combined (8/8
vs 5/7). The caveat: the correctness gap is concentrated in whether
`final_state` reaches `COMPLETE` cleanly, not in whether the underlying
code is right — Configuration A's practical cost is that it more often
requires a human to notice an `ESCALATE_TO_USER` was actually fine and
manually accept correct work, which is a real operational cost this
report does not attempt to quantify.

**On whether Reviewer diversity (Configuration B's 3 distinct model
weights) earns its cost: not supported by this data — lean no, but
genuinely close to INCONCLUSIVE.** The original architectural motivation
for a distinct Reviewer weight was to avoid a Planner reviewing its own
plan with the same biases. This benchmark did not find evidence of that
specific failure mode paying off: Configuration B's distinct Reviewer
(llama3.1:8b) was both less accurate at final judgment (§9b, §12) and
mechanically faster/cheaper (§6, §7) — a genuine trade-off, not a
one-sided loss. A team optimizing for reviewer reliability over latency
should prefer shared Planner/Reviewer weights (Configuration A) on this
evidence; a team optimizing for throughput on a VRAM-constrained card,
where phi4-reasoning:plus's partial CPU offload is the dominant latency
cost (§7), has a real, measured reason to prefer Configuration B.

**On whether the observed correctness gap is reliable given sample
size: INCONCLUSIVE at the level of "6/8 vs 3/8," reliable at the level
of the underlying pattern.** n=8 evaluable tasks per configuration in the
primary sweep, with only 3 of those 10 tasks repeated, is not enough to
certify "75% vs 37.5%" as a precise, reproducible number — a different
random 8-task sample could plausibly move either figure by one or two
tasks. What *did* replicate under an independent second run, cleanly and
unanimously, is the qualitative pattern: ground-truth correctness is
stable across runs where `final_state` is not, and Configuration A's
Reviewer renders more reliable final judgments than Configuration B's.
Those two qualitative conclusions are the load-bearing output of Phase
8, not the specific percentages.

**On MCP and context-retrieval metrics: not usable as a comparison
input.** MCP was never invoked by either configuration for structural
reasons unrelated to Reviewer choice (§10); context-retrieval overhead
was negligible and statistically indistinguishable between configurations
(§11). Neither differentiates Configuration A from B in this dataset.

**What would need to change before trusting this comparison further:**
(1) repeat all 10 tasks, not 3, to remove the sampling gap this report
is explicit about; (2) fix or work around the test-discovery-naming
failure mode from §4 before re-running, since it is currently
contaminating the `final_state` signal for reasons orthogonal to either
configuration; (3) isolate VRAM baseline sampling per-configuration
(fresh Ollama server state) before trusting the §8 baseline comparison;
(4) if reviewer efficiency matters operationally, measure the actual
human-time cost of manually clearing a correct-but-escalated
Configuration A run against Configuration B's faster-but-less-reliable
completions, which this benchmark did not attempt to price.

No claim in this report asserts a definitive, high-confidence winner on
raw outcome counts alone — the recommendation above is a directional
lean supported by a real, independently-replicated pattern, stated with
the sample-size caveats attached rather than smoothed over.
