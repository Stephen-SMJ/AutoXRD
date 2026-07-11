---
name: xrd-residual-diagnosis
description: Diagnose observed-calculated-difference residual morphology and select the next constrained XRD refinement action. Use when a FullProf fit stalls, misfits peaks, leaves unexplained reflections, or improves Rwp for unclear reasons.
allowed-tools: Read, Bash
arguments: run-directory
---

# Residual-Driven Diagnosis

Read the PRF or exported observed/calculated/difference arrays plus the latest action and
metrics. Compare against the previous accepted run. Return ranked hypotheses, evidence,
disambiguating checks, and exactly one minimal next action group.

| Residual evidence | Candidate cause | Next controlled test |
|---|---|---|
| Nearly constant displacement of all peaks | zero offset / specimen displacement | refine zero alone within instrument bounds |
| Angle-dependent peak displacement | incorrect cell or wavelength | verify metadata, then refine cell |
| Peak tops/tails misfit symmetrically | profile U/V/W or profile family | refine profile or compare supported profile functions |
| Consistent low-angle asymmetry | axial divergence / asymmetry | refine supported asymmetry parameters |
| Selected intensities wrong | preferred orientation, structure, absorption | check hkl family and sample geometry before PO |
| Sharp positive residual without calculated peak | missing phase / excluded artifact | search candidate phase; retain multiple hypotheses |
| Broad structured residual | amorphous component, size/strain, background | separate broadening from background with controls |
| Smooth baseline residual | background model | revise background without releasing structure |

Do not diagnose from Rwp alone. Require localization by 2theta and distinguish position,
width, shape, intensity, and background residuals. If evidence is non-identifying, request the
specific metadata or comparison run needed rather than choosing a cause confidently.
