---
name: xrd-physical-audit
description: Audit refined XRD structures and rank multiple phase hypotheses using fit quality, residual evidence, chemistry, uncertainty, and parameter stability. Use before accepting or reporting any Rietveld result.
allowed-tools: Read, Bash
arguments: result-json
---

# Physical Audit and Hypothesis Ranking

Run the deterministic boundary checks when a JSON result is available:

```bash
python ${CLAUDE_SKILL_DIR}/scripts/validate_result.py "$ARGUMENTS"
```

Reject hard failures: non-finite metrics, negative phase fractions, invalid occupancy,
non-positive or extreme displacement parameters, impossible cell dimensions, refinement
divergence, singular covariance, or severe unbounded correlation. Check site multiplicity and
chemically allowed occupancy conventions before calling a value invalid.

Then assess bond lengths/angles against declared chemistry, charge/composition balance,
cell deviation from the starting/reference model, shift/esd, standard errors, correlations,
unexplained reflections, difference-curve structure, and model complexity.

For ambiguous or multiphase data, return at least the credible top-k hypotheses. For each give
phase set, fractions with uncertainty, Rwp/Rexp and GoF, unexplained peak ratio, physical
violations, chemical consistency, why it remains credible, and the next discriminating
measurement or test. A lower Rwp cannot override a hard physical failure.

The final report must separate observations, model-dependent inferences, assumptions, and
unresolved ambiguity. Include the complete accepted trajectory and rejected-run reasons.
