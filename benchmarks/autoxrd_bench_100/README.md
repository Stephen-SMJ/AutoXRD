# AutoXRD-Bench-100 v2

This is a tiered 100-case evaluation of powder-XRD reasoning and agent behavior. The primary score
is a percentage: every case contributes at most one point, with a fixed 30/40/30 Easy/Medium/Hard
composition. Scores without all required LLM judgments are explicitly marked `provisional`.

## Composition

| Difficulty | Cases | Answer form | Evaluation |
|---|---:|---|---|
| Easy | 30 | select-all-that-apply, at least four distractors | exact option-set match |
| Medium | 40 | scientific conclusion with metrics and next action | one blinded rubric judgment |
| Hard | 30 | mixed-defect recovery, QPA, or phase identification plus report | objective outcome metrics plus report judgment |

Easy contains 10 typed-action, 10 trajectory-gate, and 10 residual-mechanism questions. Medium
contains 20 controlled residual reports, 10 trajectory reports, and 10 experimental phase-analysis
reports. Hard contains 10 generated mixed-defect parameter-recovery cases, 10 IUCr QARR QPA cases,
and 10 Dara phase-identification cases.

## Hard Metrics

Hard cases do not ask a Judge to invent numerical correctness. The evaluator computes phase F1,
fraction MAE/RMSE, unknown handling, artifact accuracy, and normalized parameter MAE/RMSE directly.
Metrics are converted to `[0,1]` relative utility using frozen references:

```text
higher is better: clip((metric - baseline) / (oracle - baseline), 0, 1)
lower is better:  clip((baseline - metric) / (baseline - oracle), 0, 1)
```

The denominator never depends on which models enter a comparison. Hard explanation quality accounts
for only 20-25% of a case; objective outcomes account for the remainder.

## Ground Truth And Judge Protocol

`oracle.json` stores generated parameters or published/reference answers and the case-specific Judge
rubric. It is evaluator-only. The Judge receives the task, candidate answer, reference answer, and
rubric. It scores scientific correctness, evidence grounding, action quality, and completeness from
0 to 4 and flags fatal scientific errors. Run one deterministic judgment per case with the same
frozen Judge model, version, and prompt for all compared systems.

The checked-in oracle supports local auditability but is not a secret leaderboard test. A paper run
must place the solver in a clean checkout/container containing only the public case and pattern. The
included Agent runner enforces scoped file tools and runs Bash in a networkless Docker container that
mounts only the current case workspace.

## Build And Validate

```bash
.venv/bin/python benchmarks/autoxrd_bench.py build
.venv/bin/python benchmarks/autoxrd_bench.py materialize
.venv/bin/python benchmarks/download_iucr_qarr.py
.venv/bin/python benchmarks/autoxrd_bench.py check-data
```

The materializer deterministically generates 40 single-defect residual patterns and 10 mixed-defect
recovery patterns. IUCr QARR and Dara patterns use the locally acquired source data.

## Run, Judge, Score

```bash
export OPENAI_API_KEY="your-api-key"

.venv/bin/python benchmarks/run_agent_benchmark.py \
  --output benchmarks/results/model-run \
  --base-url https://api.example.com/v1 \
  --model solver-model \
  --effort high \
  --tool-call-budget 20 \
  --workers 4

.venv/bin/python benchmarks/judge_benchmark.py \
  benchmarks/results/model-run/predictions.jsonl \
  --output benchmarks/results/model-run/judgments.jsonl \
  --base-url https://api.example.com/v1 \
  --model judge-model \
  --repeats 1

.venv/bin/python benchmarks/autoxrd_bench.py score \
  benchmarks/results/model-run/predictions.jsonl \
  --judgments benchmarks/results/model-run/judgments.jsonl \
  --output benchmarks/results/model-run/final-report.json
```

Report overall percentage, all three difficulty percentages, every family percentage, missing-answer
rate, Judge model/version, calls, runtime, and confidence intervals across at least three Agent seeds.
Do not report a provisional score as a final benchmark result.

## Leakage Rules

1. The solver must not access `oracle.json`, benchmark source, prior records, Git history, or Judge output.
2. Remove source URLs, original sample names, and upstream identifiers from the solver workspace.
3. Disable network access for all solver tools.
4. Freeze cases, metric baselines, semantic normalization, Judge prompt, and rubric before model runs.
5. Use separate solver and Judge contexts; the Judge never sends feedback to the solver.
6. Audit tool traces and publish any exclusion or retry rule before evaluation.
7. Enforce a maximum of 20 executed tool calls per case across all three difficulty tiers.
8. The 21st requested tool call immediately fails the case for zero points.
9. Retry only explicit transport/API failures that occur within the tool budget, at most once.
