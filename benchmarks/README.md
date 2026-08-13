# AutoXRD Benchmarks

This directory converts the benchmark proposal into reproducible, backend-level tests.
Downloaded corpora and generated trajectories are ignored by Git; manifests and runners are
versioned.

## AutoXRD-Bench-100

The tiered v2 agent benchmark is checked in under
[`autoxrd_bench_100/`](autoxrd_bench_100/README.md). It contains 30 objective select-all Easy cases,
40 Judge-scored Medium reports, and 30 metric-plus-Judge Hard tasks.

```bash
.venv/bin/python benchmarks/autoxrd_bench.py validate
.venv/bin/python benchmarks/autoxrd_bench.py materialize
.venv/bin/python benchmarks/download_iucr_qarr.py
.venv/bin/python benchmarks/autoxrd_bench.py check-data
.venv/bin/python benchmarks/autoxrd_bench.py baseline benchmarks/results/autoxrd-bench-baseline.jsonl
.venv/bin/python benchmarks/autoxrd_bench.py score benchmarks/results/autoxrd-bench-baseline.jsonl
```

Public questions and the evaluator oracle are separate files. The runner confines file tools and
uses a networkless Docker container for Bash. Generated/downloaded patterns remain ignored by Git.

Run the actual tool-using agent with one isolated session per case:

```bash
export OPENAI_API_KEY="your-api-key"
.venv/bin/python benchmarks/run_agent_benchmark.py \
  --output benchmarks/results/agent-run \
  --base-url https://api.example.com/v1 \
  --model your-model \
  --effort high \
  --workers 4
```

The initial runner report is provisional because Medium and part of Hard require independent Judge
records. Generate one frozen-model judgment per non-Easy case with `judge_benchmark.py`, then rerun the scorer
with `--judgments`; the complete protocol and formulas are in the suite README.

Each case record includes input/output/cache tokens, successful model turns, API attempts and
retries, requested/executed/error tool calls, wall/API/tool timing, termination reason, and a raw
per-turn/per-tool trace. `agent_step_count` is defined as successful model turns plus executed tool
calls. Records are written atomically after every case, and immutable copies are retained under
`attempts/`. A normal resume preserves API errors; `--retry-errors-only` makes one new attempt only
for missing/error cases.

For a sequential multi-model paper run, create ignored `benchmarks/model_matrix.local.json` from
the documented schema in `run_model_batch.py`, then run:

```bash
nohup .venv/bin/python -u benchmarks/run_model_batch.py \
  > benchmarks/results/model-batch.log 2>&1 &

# After every model has completed, make one recovery attempt for transport/API errors.
.venv/bin/python -u benchmarks/run_model_batch.py --recovery
```

The sanitized `manifest.json` never contains credentials. `batch-state.json`, `probes.json`, and
one log per model provide progress and failure diagnostics. Each solver uses one case worker while
`--model-workers` controls model-level concurrency; judging is deliberately deferred until all
solver outputs are frozen.

After final Judge scoring, export task/model tables, Pearson/Spearman associations, and
performance-vs-token/time/step plots with:

```bash
.venv/bin/python benchmarks/analyze_agent_runs.py \
  benchmarks/results/model-a benchmarks/results/model-b \
  --output benchmarks/results/paper-analysis
```

## Current Suites

### FullProf official examples

Run:

```bash
.venv/bin/python benchmarks/run_fullprof.py
```

The manifest covers conventional XRD, multiphase QPA, neutron powder, TOF, and magnetic
examples: CeO2, rutile/anatase, Tb2BaCoO5, PbSO4, Si3N4, and magnetite/hematite. Metrics retain
the refinement history and final conventional Rp, Rwp, Rexp, Chi2, global weighted Chi2,
Bragg R, phase fractions, convergence, runtime, warnings, and artifacts.

Current backend result: 8/8 valid executions and 8/8 convergence. This measures the FullProf
runner/parser baseline, not autonomous phase identification.

### Guarded Le Bail workflow

Run a zero-parameter initialization followed by one typed low-order background action:

```bash
.venv/bin/python benchmarks/run_le_bail_workflow.py --results benchmarks/results/le_bail_run_001
```

The runner validates the official first-run controls, preserves separate immutable run directories,
copies the generated HKL into the child run, and records the typed action and compilation report. It
also parses both PRFs and applies the evidence gate. In the current Tb2BaCoO5 smoke run, initialization
finishes with FullProf Rwp 17.4. Releasing background `b0,b1` reduces the targeted absolute low-angle
bias from 0.01138 to 0.00599, but raises Rwp to 17.6 and worsens aggregate residual utility. The gate
therefore records a mechanism-supported but rejected edge.

### Experimental pattern QC

Run:

```bash
.venv/bin/python benchmarks/run_pattern_qc.py --opxrd-limit 500
```

The opXRD run uses deterministic sampling across the 92,552-pattern archive. The Dara run
uses all 70 XRDML scans from the paper supplement. Current parse success is 500/500 opXRD and
70/70 Dara. QC flags are reported separately; they are not silently repaired.

### Dara reference

Run:

```bash
.venv/bin/python benchmarks/analyze_dara_reference.py
```

This extracts phase-indexing and manual Rietveld reference metrics from the paper's supplied
spreadsheets. Dara itself is installed in `~/.local/share/autoxrd/venvs/dara` because its Ray,
database, and pinned scientific dependencies should not constrain AutoXRD's core environment.

The upstream core XRD/CIF tests pass 7/7 and its BGMN refinement test passes 1/1 with the
published NumPy 1.26.4/Pymatgen 2025.5.1 compatibility pins. With unconstrained current NumPy
2.x, Dara 1.2.0 fails in peak matching after BGMN refinement.

### SimXRD and SIMPOD

The official code repositories and bundled samples are stored under `benchmarks/data/repos/`.
The SimXRD demo smoke test generates 3,500-point patterns from five structures successfully.

The full SimXRD test split alone is roughly 30 GB compressed for in-library and 39 GB for
out-of-library data. SIMPOD contains 467,861 structures plus radial images. These are ML
space-group-classification corpora rather than Rietveld trajectories, so the current checkout
retains their code, metadata, and sample databases. Full downloads should be a separately
provisioned training-data job with checksums and storage quotas.

## Interpretation

- A successful backend run does not imply a scientifically correct structure.
- Rwp and GoF are reported with physical violations, convergence, and residual evidence.
- Official FullProf templates are educational baselines and are not assumed optimal.
- AutoXRD phase retrieval and autonomous staged-action accuracy are not yet implemented, so
  phase precision/recall and trajectory policy metrics are pending rather than fabricated.
