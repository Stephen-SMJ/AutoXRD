---
name: xrd-structure-audit
description: Parse and conservatively audit a candidate CIF before profile matching or Rietveld refinement. Use when a CIF is supplied, retrieved, transformed, or proposed as a phase model.
allowed-tools: Read, Bash
---

# Candidate Structure Audit

Run the deterministic audit before generating a refinement input:

```bash
python -m xrd.structure "$ARGUMENTS"
```

Reject hard failures and preserve the structure fingerprint with the trajectory. Confirm formula,
space group, lattice, site count, mixed occupancies, minimum interatomic distance, and source. Treat
symmetry tolerance changes as model transformations: save the transformed CIF under a new name and
record both fingerprints. Do not silently repair a CIF or infer oxidation states from composition.

An accepted boundary audit means the file is structurally parseable, not that it is the correct phase.
Pass accepted candidates to profile matching and require peak evidence before Rietveld refinement.
