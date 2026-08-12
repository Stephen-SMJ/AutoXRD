---
name: xrd-residual-features
description: Extract deterministic morphology features from observed and calculated powder XRD patterns. Use before residual diagnosis, after every refinement intervention, and when comparing hypotheses.
allowed-tools: Read, Bash
---

# Residual Feature Extraction

Provide a FullProf `.prf` file or a whitespace/CSV table with
`2theta observed calculated [sigma]`, then run:

```bash
python -m xrd.residual "$ARGUMENTS"
```

Use the emitted Rwp only as a consistency check. Base diagnosis on localized signed regions,
autocorrelation, low/high-angle bias, structured-region fraction, and unexplained-peak ratio. Compare
features against the parent accepted run. Never interpret a feature causally by itself: propose one
minimal intervention whose predicted feature change can falsify the suspected mechanism.

If the table was converted from FullProf PRF, retain the original PRF and conversion command in the
run artifacts. Do not smooth, interpolate, clip, or baseline-correct residuals without recording a
derived artifact and the exact transformation.
