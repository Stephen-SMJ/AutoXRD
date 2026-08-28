---
name: fullprof-le-bail
description: Validate and run the first FullProf Le Bail profile-matching cycle from a trusted template. Use to establish peak positions, background, and profile alignment before structural refinement.
allowed-tools: Read, Write, Bash
---

# FullProf Le Bail Initialization

Use a trusted profile-matching template created for the phase and instrument. Validate the official
first-run controls:

```bash
python -m xrd.pcr validate-le-bail TEMPLATE.pcr
```

The validator requires constant-wavelength XRD, one or two phases, `Jbt=2`, `Nat=0`, `Irf=0`,
`Isy=0`, `Maxs=0`, and `Aut=0`. It intentionally refuses to convert a structural Rietveld PCR into
a Le Bail template.

Run the initialization:

```bash
python -m xrd.le_bail TEMPLATE.pcr PATTERN.dat RUNS_DIR --case le_bail_000 --fp2k "$FULLPROF_BIN"
```

Inspect the calculated/difference pattern and generated HKL artifacts. For subsequent cycles, use the
FullProf-generated `.new` file (`Irf=2`) as a new immutable PCR template, carry forward every
phase-indexed HKL artifact under the child case name, and invoke `/fullprof-pcr-compiler` for exactly one
typed action group. Start with zero or low-order background only when residual evidence supports it;
then lattice, profile, and asymmetry. Do not refine structure, occupancy, or Biso in profile-matching
mode.
