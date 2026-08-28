---
name: gsasii-executable-workflow
description: Build and execute auditable GSAS-II powder-XRD workflows from raw tutorial data, CIFs, and instrument files without importing a completed project.
allowed-tools: Read, Write, Edit, Bash
---

# GSAS-II Executable Workflow

Treat `.fxye`, `.gsa`, `.XRA`, `.prm`, `.instprm`, and `.cif` as real inputs,
not as answer text. Do not rename formats or copy a completed `.gpx`/`.EXP`
project into the workspace. Create a clean project or a Python analysis script
under `runs/` and retain the exact command, version, inputs, and generated
outputs for every state.

Use the installed `GSASIIscriptable`/GSAS-II APIs or a documented scientific
Python implementation. First inspect the measured range, units, wavelength or
TOF instrument model, candidate structure formula/space group, and data count.
For multiple datasets, keep dataset-specific instrument parameters explicit and
do not compare Rwp values across modalities without stating the convention.

For staged refinement, establish a baseline before releasing parameters. Use
scale/background/cell/profile terms before coordinates, occupancy, size/strain,
or preferred orientation. After every state, inspect observed/calculated/
difference data and record Rwp, Rp, GoF or chi-square, warnings, covariance or
uncertainty, and physical checks. A lower Rwp alone is not acceptance evidence.

For phase identification or candidate validation, compute or fit the supplied
candidate structures against the measured pattern and report rejected
candidates and ambiguity. For Le Bail or peak fitting, distinguish extracted
intensities/peak components from a solved atomic structure. For sequential
workflows, preserve one row and one artifact set per profile and flag failed or
physically discontinuous states rather than interpolating them silently.

The final report must separate measured observations, model-dependent
inferences, assumptions, and unresolved ambiguity. Never claim a backend run or
metric that is not present in a generated artifact.
