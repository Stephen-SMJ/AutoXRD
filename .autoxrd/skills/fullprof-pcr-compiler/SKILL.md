---
name: fullprof-pcr-compiler
description: Inspect a validated FullProf PCR template and compile one typed refinement action into guarded codeword changes. Use before every FullProf refinement after Le Bail initialization or from a validated Rietveld template.
allowed-tools: Read, Write, Bash
---

# Guarded PCR Compilation

First inspect the source without modifying it:

```bash
python -m xrd.pcr inspect SOURCE.pcr
```

Choose parameter selectors only from the emitted catalog. Create a JSON specification containing
`template`, `template_sha256`, `output`, the complete typed `action`, and explicit `selectors`. Compile:

```bash
python -m xrd.pcr compile SPEC.json
```

The compiler freezes every catalogued codeword, releases only the selected parameter group, preserves
shared codeword constraints, updates `Maxs`, refuses unsupported PCR modes, and writes a provenance
report beside the output. Never overwrite the source template. Prefer explicit selectors such as
`background.b0` and `background.b1` over broad wildcards.

The current compiler supports scale, zero, background, lattice, profile, and asymmetry codewords.
It rejects coordinate, Biso, occupancy, preferred-orientation, and size/strain actions until numeric
limits, restraints, and refined-value parsing are implemented. In `Jbt=2` Le Bail mode it also rejects
scale refinement because FullProf defines this mode with constant scale.

If compilation reports an uncatalogued codeword, crossed action boundary, missing anchor, or unsupported
phase model, stop. Do not repair the PCR with free-form text. Add and test a parser for that validated
template family first. Read `docs/fullprof-pcr.md` for the compilation schema and supported scope.
