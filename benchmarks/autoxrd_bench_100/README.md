# AutoXRD-Bench-100

AutoXRD-Bench-100 is a compact, trajectory-aware evaluation suite for powder-XRD agents. It
contains exactly 100 cases and separates deterministic mechanism tests from experimental-data
generalization.

## Composition

| Family | Cases | Data | Primary signal |
|---|---:|---|---|
| `action_contract` | 10 | controlled | valid typed action and contract violations |
| `trajectory_gate` | 20 | controlled | accept/reject decision and gate reasons |
| `residual_diagnosis` | 40 | generated profiles | dominant cause and next action |
| `iucr_qpa` | 20 | IUCr QPA round robin | phase F1, weight-fraction MAE, artifact label |
| `dara_phase_identification` | 10 | Dara experiments | phase F1 and fully-indexed decision |

The 70 controlled cases have exact single-cause oracles. The 30 experimental cases use only
published/reference labels. Natural granodiorite has no invented quantitative ground truth and is
scored only on its reference phase set and artifact class.

## Files

- `cases.jsonl`: public questions, input paths, metadata, and response schemas.
- `oracle.json`: evaluator-side reference answers. Do not expose it to an evaluated agent.
- `manifest.json`: suite version, counts, splits, metrics, and source provenance.
- `data/`: generated or downloaded patterns; ignored by Git.

For a blind evaluation, copy `cases.jsonl` and `data/` into the agent sandbox and keep
`oracle.json` outside that sandbox. The checked-in oracle makes local scorer auditing possible; it
does not provide leaderboard secrecy.

## Build And Materialize

From the repository root:

```bash
.venv/bin/python benchmarks/autoxrd_bench.py build
.venv/bin/python benchmarks/autoxrd_bench.py validate
.venv/bin/python benchmarks/autoxrd_bench.py materialize
```

`materialize` deterministically creates 40 residual patterns and converts 10 local Dara XRDML
files to two-column text. It reports each source as `ready` or `missing` instead of silently
substituting synthetic data.

IUCr currently applies an anti-bot response to some non-browser downloads. Existing CPI files can
be placed directly under `data/iucr/`, or a download can be attempted with:

```bash
.venv/bin/python benchmarks/autoxrd_bench.py materialize --download-iucr
```

Failures are returned per case and do not alter the oracle. Public case records retain each
canonical source URL.

## Submission And Scoring

Submit one JSON object per line:

```json
{"id":"residual-01-01","answer":{"diagnosis":"zero_shift","action":"refine_zero"}}
```

Exact answer fields vary by family and are declared in each case's `response_schema`. Missing cases
receive zero; duplicate and unknown IDs are rejected.

Generate and score a deliberately weak format baseline:

```bash
.venv/bin/python benchmarks/autoxrd_bench.py baseline benchmarks/results/autoxrd-bench-baseline.jsonl
.venv/bin/python benchmarks/autoxrd_bench.py score \
  benchmarks/results/autoxrd-bench-baseline.jsonl \
  --output benchmarks/results/autoxrd-bench-baseline-report.json
```

The scorer reports macro and micro scores, each family score, physical-gate error rate, diagnosis
accuracy, and per-case components. The v1 primary comparison should use `macro_score`; always
publish family scores alongside it.

## Evaluation Rules

1. Give every system the same files, phase candidates, FullProf-call budget, and timeout.
2. Do not let an evaluated process read `oracle.json`.
3. Report controlled and experimental results separately.
4. Treat phase labels as set-valued; aliases such as `Al2O3`/corundum are normalized.
5. Report QPA fractions on `[0, 1]`, not percent. The fraction score reaches zero at MAE 0.20.
6. Run at least three agent seeds and publish mean, paired bootstrap confidence intervals, calls,
   runtime, invalid-action rate, and missing-response rate.
7. Do not claim real-data identifiability from the controlled single-cause cases.

## Baseline Meaning

The included constant baseline is only a parser/scorer smoke test. It scores about 0.26 macro and
must not be presented as a scientific baseline. Paper results should additionally include a fixed
rule policy, direct LLM PCR editing, tool-using LLM without evidence gates, and full AutoXRD under
the same backend-call budget.
