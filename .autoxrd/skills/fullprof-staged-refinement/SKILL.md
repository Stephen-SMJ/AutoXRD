---
name: fullprof-staged-refinement
description: Plan and execute an auditable staged FullProf Rietveld refinement from a powder pattern and candidate CIF or validated PCR template. Use for known-phase profile matching, Le Bail fitting, Rietveld refinement, QPA, and FullProf output review.
allowed-tools: Read, Write, Edit, Bash
---

# Staged FullProf Refinement

Never freely rewrite an entire PCR from prose. Start from a FullProf example or a validated
template, make one typed action group per run, and retain each input and output.

## Preconditions

1. Run `/xrd-pattern-qc` and establish wavelength, radiation, geometry, scan range, and units.
2. Run `/xrd-structure-audit` and validate CIF formula, space group, cell, atom labels, Wyckoff multiplicities, occupancies,
   and displacement conventions.
3. Use `/fullprof-le-bail` and `/fullprof-pcr-compiler`; never modify PCR codewords directly.
4. Preserve the source files. Create `runs/run_NNN/` containing `input.pcr`, `action.json`,
   program output, refined PCR, PRF, `metrics.json`, and warnings.

## Curriculum

1. Profile match or Le Bail: scale, zero, background, cell, U/V/W, then asymmetry. Keep
   coordinates, occupancy, and B factors fixed.
2. Rietveld instrument stage: scale; zero only with evidence; lattice; background; profile.
3. Structure stage: coordinates under symmetry/restraints. Release the smallest justified set.
4. Late stage: Biso, occupancy, preferred orientation, and size/strain only when residual
   morphology supports them and correlations remain acceptable.
5. Final cycle: freeze unstable terms, rerun, parse covariance and uncertainties, and invoke
   `/xrd-physical-audit`.

After every run invoke `/xrd-residual-features` and `/xrd-trajectory-gate`, then compare Rwp, Rp,
Rexp, GoF, maximum shift/esd, warnings, unexplained peaks, and parameter correlations. Reject singular, divergent, NaN, or physically invalid runs even
when Rwp decreases. Do not simultaneously compensate uncertain wavelength with zero and cell.

Consult `$FULLPROF_MANUAL` for PCR fields and the official FullProf documentation
for program-specific semantics. Do not guess a codeword or field position.
