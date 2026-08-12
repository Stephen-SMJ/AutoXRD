---
name: xrd-pattern-qc
description: Inspect powder XRD pattern quality and metadata before phase analysis or refinement. Use for XY, DAT, CSV, or whitespace two-column scans and for diagnosing scan range, step size, noise, background, and peak sampling.
allowed-tools: Read, Bash
---

# Pattern QC

Treat the input as immutable evidence. Run:

```bash
python ${AUTOXRD_SKILL_DIR}/scripts/pattern_qc.py "$ARGUMENTS"
```

Then report a `PatternState` with: source path, column interpretation, point count,
2theta range, median step and step irregularity, intensity range, robust noise estimate,
detected peak positions, points across the narrowest detected peak, and warnings.

Do not infer radiation or wavelength from peak positions. Ask for instrument metadata when
it is absent. Flag non-monotonic axes, duplicate angles, negative intensity, irregular steps,
coarse sampling, saturation, a broad amorphous component, and too few points. A sampling
warning is diagnostic, not permission to interpolate away evidence.

Save derived or cleaned data under a new filename and record every transformation.
