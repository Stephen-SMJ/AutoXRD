# AutoXRD-Bench-100: gpt-5.6-luna Report

## Run Configuration

- Benchmark: `autoxrd-bench-100-v1`
- Model: `gpt-5.6-luna`
- Provider protocol: OpenAI-compatible
- Endpoint: `https://api.lambda.org.ai/v1`
- Effort: `high`
- Maximum output tokens: 8192
- Parallel workers: 4
- Agent isolation: fresh session and workspace for every case
- Oracle exposure: none
- Final valid responses: 100/100
- First-pass technical failures: 2; only those two cases were retried

## Primary Strict Score

Every task is worth one point. There is no partial credit in the primary score.

| Task family | Correct | Total | Accuracy |
|---|---:|---:|---:|
| Typed action contract | 10 | 10 | 100.0% |
| Trajectory gate | 20 | 20 | 100.0% |
| Residual diagnosis and next action | 30 | 40 | 75.0% |
| IUCr phase identification and QPA | 19 | 20 | 95.0% |
| Dara experimental phase identification | 10 | 10 | 100.0% |
| **Overall** | **89** | **100** | **89.0%** |

By data split:

| Split | Correct | Total | Accuracy |
|---|---:|---:|---:|
| Controlled | 60 | 70 | 85.7% |
| Experimental | 29 | 30 | 96.7% |

## Strict Scoring Rule

- Action-contract cases require the correct valid/invalid decision.
- Trajectory cases require the correct accept/reject decision.
- Residual cases require both the dominant diagnosis and next-action class.
- Phase cases require the exact phase set and correct indexing/artifact decision.
- QPA cases with published fractions additionally require phase-fraction MAE at or below 0.05.
- Deterministic scientific phrase aliases are accepted, so a correct sentence such as “refine the
  background model” is equivalent to `refine_background`.
- Missing, malformed, or incomplete answers receive zero.
- Machine-code reason F1, phase F1, and continuous QPA scores are diagnostic metrics, not primary
  partial credit.

## Residual Diagnosis Breakdown

| Mechanism | Correct | Total | Accuracy |
|---|---:|---:|---:|
| Zero shift | 5 | 5 | 100.0% |
| Background curvature | 5 | 5 | 100.0% |
| Peak broadening | 4 | 5 | 80.0% |
| Low-angle asymmetry | 1 | 5 | 20.0% |
| Impurity peaks | 4 | 5 | 80.0% |
| Preferred orientation | 5 | 5 | 100.0% |
| Limited 2theta range | 2 | 5 | 40.0% |
| High noise | 4 | 5 | 80.0% |

The dominant scientific failure is confusion between low-angle asymmetry and either preferred
orientation or missing-phase intensity. Limited-range patterns are also frequently interpreted as
background, noise, or preferred orientation instead of triggering a request for broader acquisition.

The only IUCr strict error was the pure-corundum reference: the phase was identified correctly, but
the agent asserted preferred orientation where the benchmark reference artifact is `none`.

## Diagnostic Scores

These retain partial credit and should not replace the strict score:

| Metric | Value |
|---|---:|
| Macro component score | 82.18% |
| Micro component score | 68.43% |
| Physical gate error rate | 8.89% |
| Exact enum diagnosis accuracy | 27.5% |

The low exact-enum diagnosis number is primarily a serialization effect: the agent often returned
correct scientific prose rather than internal enum identifiers. That is why deterministic semantic
class matching is used for the strict task score and raw outputs remain available for audit.

## Runtime And Usage

| Measure | Value |
|---|---:|
| Wall-clock span | approximately 24.5 minutes |
| Sum of per-case elapsed time | 92.2 minutes |
| Mean per case | 55.3 seconds |
| Median per case | 51.2 seconds |
| Approximate p95 per case | 106.3 seconds |
| Tool calls | 1,082 |
| Mean tool calls per case | 10.82 |
| Input tokens reported by endpoint | 10,428,082 |
| Output tokens reported by endpoint | 220,266 |

The endpoint did not expose a pricing table for this model, so no monetary-cost claim is made.

## Limitations

This is one model run, not a confidence interval over stochastic agent seeds. The experimental
candidate libraries are supplied by each public case, so this evaluates reasoning and verification
within a bounded candidate set rather than open-world retrieval. A paper comparison should repeat
at least three seeds and include fixed-rule, no-skills, no-evidence-gate, and direct-PCR-editing
ablations under the same call and time budgets.

Machine-readable artifacts are stored beside this report:

- `report.json`: complete metrics and per-case components
- `predictions.jsonl`: evaluator submission
- `records/*.json`: raw response, tools, usage, timing, and status per task
- `workspaces/`: isolated public inputs used by each agent session
