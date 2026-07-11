# AutoXRD Benchmarks

This directory converts the benchmark proposal into reproducible, backend-level tests.
Downloaded corpora and generated trajectories are ignored by Git; manifests and runners are
versioned.

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
